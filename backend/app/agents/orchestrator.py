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

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

from app.agents.budget_agent import parse_priority_weights, allocate_budget
from app.agents.itinerary_agent import compose_itinerary
from app.agents.ranking_agent import rank_search_results
from app.agents.search_agent import resolve_iata_code, resolve_city_center, run_search_agent
from app.schemas.trip_state import TripState


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

    if user_input.surprise_me and not user_input.destination:
        # "Surprise me" destination selection is a separate, not-yet-built
        # concern (no destination-picking logic exists anywhere in Phase 1)
        # -- surface it as a clarification rather than guessing a city.
        return {"clarification_needed": "Surprise-me destination selection isn't built yet."}

    destination_iata = await resolve_iata_code(user_input.destination)
    if destination_iata is None:
        return {
            "clarification_needed": f"Couldn't find an airport for '{user_input.destination}'."
        }

    results, errors, conflicts = await run_search_agent(
        origin_iata=origin_iata,
        destination_iata=destination_iata,
        destination_city=user_input.destination,
        departure_date=user_input.start_date.isoformat(),
        return_date=user_input.return_date.isoformat(),
        budget_allocation=state.budget_allocation,
    )
    update = {
        "search_results": results,
        "search_errors": errors,
        "conflicts": state.conflicts + conflicts,
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
    reference_location = None
    if user_input.destination:
        reference_location = await resolve_city_center(user_input.destination)

    ranked = rank_search_results(
        state.search_results,
        style=user_input.style,
        reference_location=reference_location,
        hotel_star_preference=user_input.hotel_star_preference,
    )
    return {"ranked_shortlist": ranked}


def itinerary_agent_node(state: TripState) -> dict:
    user_input = state.user_input
    days, conflicts = compose_itinerary(
        state.ranked_shortlist,
        state.budget_allocation,
        user_input.duration_days,
        user_input.destination or "your destination",
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
