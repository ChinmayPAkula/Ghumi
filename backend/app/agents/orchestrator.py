"""
Orchestrator — Ghumi_Agent_Architecture_Spec.docx §5.1/§5.3, PRD §8.1 item 5

Wires the already-built, already-unit-tested agent functions into a real
LangGraph StateGraph:

    input_handler -> budget_agent -> search_agent -> [checkpoint] ->
    ranking_agent -> itinerary_agent -> [checkpoint] -> END

Every node function here is a THIN wrapper — it reads TripState fields,
calls the real agent function (already covered by its own test suite:
test_budget_agent.py, test_search_agent.py, test_ranking_agent.py,
test_itinerary_agent.py), and returns only the state fields it owns, per
PRD §6.2's "every agent writes back only its own fields" rule. No agent
logic lives in this file — that was the whole point of building each
agent standalone first (see PRD §8.2's working principles).

Checkpointed interrupts (§5.3): the graph pauses via interrupt() at two
points rather than one true "anytime" interruption point:
  - after search_agent, if a flight-overspend Conflict was recorded, or
    an origin/destination airport code couldn't be resolved
  - after itinerary_agent, if a hotel-overspend Conflict was recorded
Resolving a conflict smartly (auto re-negotiating budget shares, proposing
concrete tradeoffs) is explicitly PRD Phase 2's "conflict-aware
replanning" — NOT built here. For this first pass, the interrupt is a
real structural checkpoint (the graph genuinely pauses and a caller must
resume it), but resuming just acknowledges the conflict and continues
with whatever was already selected (e.g. the over-budget-but-cheapest
hotel/flight) rather than attempting to fix it. Documented as a
deliberate scope boundary, not an oversight.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from langchain_groq import ChatGroq
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

from app.agents.budget_agent import parse_priority_weights, allocate_budget
from app.agents.itinerary_agent import compose_itinerary
from app.agents.ranking_agent import rank_search_results
from app.agents.search_agent import resolve_iata_code, resolve_city_center, run_search_agent
from app.core.config import get_settings
from app.schemas.trip_state import TripState, UserInput

SURPRISE_ME_PROMPT = """You are suggesting ONE real travel destination for a
traveler who wants to be surprised. Pick a specific, well-known CITY (not a
country or region) that is realistic for their budget and trip length, and
fits their stated style/priorities if any were given. The city must have its
own commercial airport or be served by a nearby major airport.

Budget: {budget} {currency}
Trip length: {duration} days
Style: {style}
What they care about: {priorities}

Respond with ONLY the city name -- no punctuation, no explanation, no extra
words. Just the name, e.g.: Lisbon
"""


def _get_destination_llm() -> ChatGroq:
    """
    Isolated so tests can monkeypatch this instead of mocking ChatGroq's
    internals directly — same pattern as itinerary_agent._get_narrative_llm().

    Plain chat completion, NOT with_structured_output(): live-tested that
    Groq's gpt-oss models (both 20b and 120b) unreliably honor a forced
    tool_choice for a task this simple -- the model would correctly answer
    in plain text (e.g. "Udaipur") but fail Groq's "tool choice is
    required but model did not call a tool" check, a real upstream quirk,
    not a bug in the schema. Parsing one line of plain text ourselves
    sidesteps the whole problem.
    """
    settings = get_settings()
    return ChatGroq(
        # 120b: this needs actual judgment (balancing budget, duration,
        # style into one sensible pick), the same reasoning itinerary_agent's
        # narrative composition needed the larger model for.
        model="openai/gpt-oss-120b",
        api_key=settings.groq_api_key,
        temperature=0.9,  # a "surprise" should vary between runs, unlike budget parsing
    )


def suggest_surprise_destination(user_input: UserInput) -> Optional[str]:
    """
    LLM call: picks a real city for "surprise me" based on budget/duration/
    style/priorities. One retry, then None rather than raising --
    search_agent_node treats that as a clarification-needed case, same
    safety net as before this existed.
    """
    prompt = SURPRISE_ME_PROMPT.format(
        budget=user_input.budget_total,
        currency=user_input.currency,
        duration=user_input.duration_days,
        style=user_input.style or "no particular style",
        priorities=user_input.priorities_raw or "nothing specific",
    )

    for _ in range(2):  # one retry
        try:
            llm = _get_destination_llm()
            response = llm.invoke(prompt)
            text = response.content
            if isinstance(text, str) and text.strip():
                # The model occasionally adds a trailing period/quotes
                # despite instructions -- take the first line, strip stray
                # punctuation rather than failing on an otherwise-good answer.
                destination = text.strip().splitlines()[0].strip(" \"'.")
                if destination:
                    return destination
        except Exception:
            continue

    return None


def input_handler_node(state: TripState) -> dict:
    """
    No-op by design: UserInput validation already happened via Pydantic
    before the initial TripState was constructed (see
    app/agents/input_handler.py) -- TripState.user_input can't exist in
    an invalid shape by the time the graph runs. This node exists only so
    the graph's node list matches the documented pipeline diagram
    (input_handler -> budget_agent -> ...) for readability/tracing.
    """
    if state.user_input is None:
        raise ValueError("TripState.user_input must be set before running the graph")
    return {}


def budget_agent_node(state: TripState) -> dict:
    user_input = state.user_input
    weights = parse_priority_weights(user_input.priorities_raw)
    allocation = allocate_budget(user_input.budget_total, weights)
    return {"priority_weights": weights, "budget_allocation": allocation}


async def search_agent_node(state: TripState) -> dict:
    user_input = state.user_input

    origin_iata = await resolve_iata_code(user_input.origin)
    if origin_iata is None:
        return {"clarification_needed": f"Couldn't find an airport for '{user_input.origin}'."}

    destination_city = user_input.destination
    chosen_destination = None
    if user_input.surprise_me and not destination_city:
        chosen_destination = suggest_surprise_destination(user_input)
        if not chosen_destination:
            return {
                "clarification_needed": (
                    "Couldn't come up with a surprise destination — try entering one directly."
                )
            }
        destination_city = chosen_destination

    destination_iata = await resolve_iata_code(destination_city)
    if destination_iata is None:
        return {"clarification_needed": f"Couldn't find an airport for '{destination_city}'."}

    results, errors, conflicts = await run_search_agent(
        origin_iata=origin_iata,
        destination_iata=destination_iata,
        destination_city=destination_city,
        departure_date=user_input.start_date.isoformat(),
        return_date=user_input.return_date.isoformat(),
        budget_allocation=state.budget_allocation,
    )
    update = {
        "search_results": results,
        "search_errors": errors,
        "conflicts": state.conflicts + conflicts,
        "chosen_destination": chosen_destination,
    }
    if conflicts:
        # Routing keys off clarification_needed, NOT the cumulative
        # conflicts list -- an older, already-acknowledged conflict
        # (e.g. from a previous checkpoint) must not re-trigger this one.
        # See route_after_itinerary for the matching half of this fix.
        update["clarification_needed"] = (
            f"{len(conflicts)} conflict(s) found during search: "
            + "; ".join(c.description for c in conflicts)
        )
    return update


def route_after_search(state: TripState) -> str:
    if state.clarification_needed:
        return "clarify_after_search"
    return "ranking_agent"


def clarify_after_search_node(state: TripState) -> dict:
    interrupt(
        {
            "stage": "after_search",
            "clarification_needed": state.clarification_needed,
            "conflicts": [c.model_dump() for c in state.conflicts],
        }
    )
    # See module docstring: resuming just acknowledges and continues with
    # the state as-is. Smart conflict resolution is Phase 2.
    return {"clarification_needed": None}


async def ranking_agent_node(state: TripState) -> dict:
    user_input = state.user_input
    destination_city = state.chosen_destination or user_input.destination
    reference_location = None
    if destination_city:
        reference_location = await resolve_city_center(destination_city)

    ranked = rank_search_results(
        state.search_results,
        style=user_input.style,
        reference_location=reference_location,
        hotel_star_preference=user_input.hotel_star_preference,
    )
    return {"ranked_shortlist": ranked}


def itinerary_agent_node(state: TripState) -> dict:
    user_input = state.user_input
    destination_city = state.chosen_destination or user_input.destination
    days, conflicts = compose_itinerary(
        state.ranked_shortlist,
        state.budget_allocation,
        user_input.duration_days,
        destination_city or "your destination",
    )
    update = {"itinerary": days, "conflicts": state.conflicts + conflicts}
    if conflicts:
        # Same reasoning as search_agent_node: key routing off a fresh
        # clarification_needed set by whichever node just ran, not the
        # cumulative conflicts list -- otherwise an already-acknowledged
        # search-stage conflict would spuriously re-trigger this checkpoint.
        update["clarification_needed"] = (
            f"{len(conflicts)} conflict(s) found while building the itinerary: "
            + "; ".join(c.description for c in conflicts)
        )
    return update


def route_after_itinerary(state: TripState) -> str:
    if state.clarification_needed:
        return "clarify_after_itinerary"
    return END


def clarify_after_itinerary_node(state: TripState) -> dict:
    interrupt(
        {
            "stage": "after_itinerary",
            "conflicts": [c.model_dump() for c in state.conflicts],
        }
    )
    return {"clarification_needed": None}


def build_graph() -> StateGraph:
    """Assembles the graph structure. Split from compile_graph() so tests
    can inspect node/edge wiring without needing a checkpointer."""
    graph = StateGraph(TripState)

    graph.add_node("input_handler", input_handler_node)
    graph.add_node("budget_agent", budget_agent_node)
    graph.add_node("search_agent", search_agent_node)
    graph.add_node("clarify_after_search", clarify_after_search_node)
    graph.add_node("ranking_agent", ranking_agent_node)
    graph.add_node("itinerary_agent", itinerary_agent_node)
    graph.add_node("clarify_after_itinerary", clarify_after_itinerary_node)

    graph.add_edge(START, "input_handler")
    graph.add_edge("input_handler", "budget_agent")
    graph.add_edge("budget_agent", "search_agent")
    graph.add_conditional_edges(
        "search_agent", route_after_search, ["clarify_after_search", "ranking_agent"]
    )
    graph.add_edge("clarify_after_search", "ranking_agent")
    graph.add_edge("ranking_agent", "itinerary_agent")
    graph.add_conditional_edges(
        "itinerary_agent", route_after_itinerary, ["clarify_after_itinerary", END]
    )
    graph.add_edge("clarify_after_itinerary", END)

    return graph


def compile_graph(checkpointer=None):
    """
    checkpointer is required for interrupt()/resume to actually work
    across separate calls (e.g. InMemorySaver for dev, a real persistent
    checkpointer for production) -- passed in rather than hardcoded here
    so tests can supply their own and production can supply a real one
    once that infra decision is made (PRD Phase 4).
    """
    return build_graph().compile(checkpointer=checkpointer)


@lru_cache
def get_compiled_graph():
    """
    Process-wide singleton, used by the API layer (app/api/trip.py).
    InMemorySaver only persists within this process's memory -- fine for
    dev/demo scale (matches TechStack.docx §3.1's "no task queue for v1"
    decision: synchronous request/response, no durable job infra yet).
    Swap for a real persistent checkpointer before Phase 4 deployment,
    where a restart shouldn't lose an in-progress paused run.
    """
    return compile_graph(checkpointer=InMemorySaver())
