"""
Itinerary Agent — Ghumi_Agent_Architecture_Spec.docx §3.3, PRD §6.1

Two responsibilities, split per the LLM/code rule (PRD §5.2):
  1. build_itinerary()      — code: assembles day-by-day schedule from
                                ranking_agent's output
  2. write_day_narrative()  — LLM (Groq): writes a short natural-language
                                summary of one day's plan

Scope decided collaboratively (see conversation history) for this first
pass:
  - ONE hotel for the entire stay (the top-ranked one THAT FITS ITS BUDGET
    ALLOCATION — see _select_hotel_within_budget below), not a different
    hotel per day. Proximity-based multi-hotel assignment was considered
    and explicitly deferred — it cascades into ranking_agent (geographic
    clustering of a day's activities) and budget_agent (inter-hotel
    transfer cost) in ways that don't belong in itinerary_agent's first
    build. Revisit as a Phase 2 "Intelligence Layer" item.
  - 3 meals/day (breakfast/lunch/dinner) and 1 activity/day, fixed counts,
    top-ranked-first, no repeats until the shortlist is exhausted (then
    cycles). Real pacing/intensity curves (PRD Phase 2) are out of scope
    here — this is deliberately the simplest schedule that's still
    realistic, not yet an optimized one. Per-item food/activity budget
    checks are deliberately NOT done here either — a single meal rarely
    approaches a whole category's total budget the way one hotel booking
    can consume its entire category in one line item, so the acute
    budget-accuracy risk is specifically the hotel pick.
  - Local transport has no searchable candidates (no provider), so its
    per-day budget share is represented as a synthetic placeholder
    ScoredCandidate in each day's items, rather than adding a new field
    to the existing DayPlan schema for a single number.

Bug found and fixed after live-testing exposed it (see conversation
history): search_agent's search functions accept a budget_amount
parameter but never actually use it to filter results — so
ranked_shortlist[HOTELS][0] could genuinely be a hotel several times over
its budget allocation. _select_hotel_within_budget() below picks the
top-ranked hotel that actually fits, falling back to the cheapest
available (with a Conflict recorded) only if none do — the same
detect-but-don't-silently-resolve pattern search_agent already uses for
an overspent flight.
"""
from __future__ import annotations

from langchain_groq import ChatGroq

from app.agents.search_agent import RESOLUTION_OPTIONS
from app.core.config import get_settings
from app.schemas.trip_state import Conflict, DayPlan, ScoredCandidate

HOTELS = "hotels"
FOOD = "food"
ACTIVITIES = "activities"
TRANSPORT = "transport"

MEALS_PER_DAY = 3
ACTIVITIES_PER_DAY = 1


def _cycle(items: list[ScoredCandidate], count: int, start: int) -> tuple[list[ScoredCandidate], int]:
    """
    Pull `count` items starting at index `start`, wrapping around (cycling
    back to the top-ranked item) if the shortlist runs out rather than
    leaving a day empty. Returns (picked, next_start_index).
    """
    if not items:
        return [], start
    picked = [items[(start + i) % len(items)] for i in range(count)]
    return picked, (start + count) % len(items)


def _transport_placeholder(day_number: int, per_day_amount: float) -> ScoredCandidate:
    """
    No provider searches local transport, so there's no real Candidate for
    it. A synthetic one keeps DayPlan.items as the single place a day's
    full cost breakdown lives, rather than a separate field for one number.
    """
    return ScoredCandidate(
        id=f"transport-day-{day_number}",
        category=TRANSPORT,
        name="Local transport (estimated)",
        price=per_day_amount,
        score=1.0,
        metadata={"synthetic": True},
    )


def _select_hotel_within_budget(
    hotel_list: list[ScoredCandidate], hotel_budget: float
) -> tuple[ScoredCandidate | None, Conflict | None]:
    """
    Top-ranked hotel that actually fits its budget allocation — ranking
    alone doesn't guarantee this, since search_agent's budget_amount
    parameter is currently unused for actual filtering (see module
    docstring). Falls back to the cheapest available hotel, with a
    Conflict recorded, only if nothing in the shortlist fits — mirrors
    search_agent's own overspent-flight handling: detect and describe,
    don't silently resolve.
    """
    if not hotel_list:
        return None, None

    for hotel in hotel_list:
        if hotel.price <= hotel_budget:
            return hotel, None

    cheapest = min(hotel_list, key=lambda h: h.price)
    shortfall = cheapest.price - hotel_budget
    conflict = Conflict(
        description=(
            f"Cheapest available hotel ({cheapest.name}, {cheapest.price:.2f}) exceeds "
            f"its budget allocation ({hotel_budget:.2f}) by {shortfall:.2f}."
        ),
        category=HOTELS,
        shortfall_amount=shortfall,
        resolution_options=list(RESOLUTION_OPTIONS),
    )
    return cheapest, conflict


def build_itinerary(
    ranked_shortlist: dict[str, list[ScoredCandidate]],
    budget_allocation: dict[str, float],
    duration_days: int,
) -> tuple[list[DayPlan], list[Conflict]]:
    """
    Pure code: assembles day_number -> items for every day of the trip.
    Never calls an LLM — narrative text is added separately by
    write_day_narrative(), per the LLM/code split.

    Returns (days, conflicts) — conflicts is currently only ever a single
    hotel-overspend entry (or empty), same shape as search_agent's
    run_search_agent() return, so callers can merge both into
    TripState.conflicts uniformly.
    """
    hotel_list = ranked_shortlist.get(HOTELS, [])
    hotel_budget = budget_allocation.get(HOTELS, float("inf"))
    hotel, hotel_conflict = _select_hotel_within_budget(hotel_list, hotel_budget)
    conflicts = [hotel_conflict] if hotel_conflict else []

    meals = ranked_shortlist.get(FOOD, [])
    activities = ranked_shortlist.get(ACTIVITIES, [])
    transport_per_day = budget_allocation.get(TRANSPORT, 0.0) / duration_days if duration_days else 0.0

    meal_cursor = 0
    activity_cursor = 0
    days: list[DayPlan] = []

    for day_number in range(1, duration_days + 1):
        day_meals, meal_cursor = _cycle(meals, MEALS_PER_DAY, meal_cursor)
        day_activities, activity_cursor = _cycle(activities, ACTIVITIES_PER_DAY, activity_cursor)

        items: list[ScoredCandidate] = []
        if hotel is not None:
            items.append(hotel)
        items.append(_transport_placeholder(day_number, transport_per_day))
        items.extend(day_meals)
        items.extend(day_activities)

        days.append(DayPlan(day_number=day_number, items=items))

    return days, conflicts


NARRATIVE_PROMPT_TEMPLATE = """You are writing a short, warm day-plan summary
for a travel itinerary app. Given the items scheduled for this day, write
2-3 sentences describing the day in natural language — mention the
highlights (activity, standout meal), not every line item mechanically.
Don't mention prices or scores. Don't invent details not in the list.

Day {day_number} in {destination}, items scheduled:
{item_list}
"""


def _get_narrative_llm() -> ChatGroq:
    """
    Isolated so tests can monkeypatch this instead of mocking ChatGroq's
    internals directly — same pattern as budget_agent._get_structured_llm().
    """
    settings = get_settings()
    return ChatGroq(
        # openai/gpt-oss-120b per TechStack.docx — "the one genuinely
        # open-ended generation task" among Ghumi's LLM calls.
        model="openai/gpt-oss-120b",
        api_key=settings.groq_api_key,
        temperature=0.7,  # narrative writing benefits from some variation
    )


def write_day_narrative(day: DayPlan, destination: str) -> str:
    """
    LLM call: turns one day's assembled items into a short natural-
    language summary. Falls back to a plain, code-generated sentence if
    the LLM call fails — a missing narrative shouldn't break the whole
    itinerary, same reasoning as parse_priority_weights' fallback.
    """
    item_list = "\n".join(f"- {item.category}: {item.name}" for item in day.items)
    prompt = NARRATIVE_PROMPT_TEMPLATE.format(
        day_number=day.day_number, destination=destination, item_list=item_list
    )

    try:
        llm = _get_narrative_llm()
        response = llm.invoke(prompt)
        text = response.content
        if isinstance(text, str) and text.strip():
            return text.strip()
    except Exception:
        pass

    names = ", ".join(item.name for item in day.items if item.category != TRANSPORT)
    return f"Day {day.day_number} in {destination}: {names}."


def compose_itinerary(
    ranked_shortlist: dict[str, list[ScoredCandidate]],
    budget_allocation: dict[str, float],
    duration_days: int,
    destination: str,
) -> tuple[list[DayPlan], list[Conflict]]:
    """
    Full pipeline: build the schedule (code), then write each day's
    narrative (LLM). Kept separate from build_itinerary() so the
    code-only assembly stays independently testable without touching Groq.
    """
    days, conflicts = build_itinerary(ranked_shortlist, budget_allocation, duration_days)
    for day in days:
        day.summary = write_day_narrative(day, destination)
    return days, conflicts
