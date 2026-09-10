"""
Run this manually to sanity-check itinerary_agent end to end against REAL
search results (Duffel/LiteAPI/Google Places) and a REAL Groq narrative
call — this is NOT part of the pytest suite (pytest mocks the Groq call
and uses synthetic candidates, see tests/test_itinerary_agent.py).

Requires the same .env keys as verify_search_agent_live.py, plus
GROQ_API_KEY.

Run from backend/ (with PYTHONPATH=. if running outside an installed
package):
    python scripts/verify_itinerary_agent_live.py
"""
import asyncio

from app.agents.search_agent import run_search_agent, resolve_city_center
from app.agents.ranking_agent import rank_search_results
from app.agents.itinerary_agent import compose_itinerary

BUDGET_ALLOCATION = {
    "flights": 50000.0,
    "hotels": 20000.0,
    "food": 15000.0,
    "activities": 15000.0,
    "transport": 10000.0,
}
DURATION_DAYS = 3
DESTINATION = "Tokyo"


async def main():
    search_results, errors, conflicts = await run_search_agent(
        origin_iata="BLR",
        destination_iata="HND",
        destination_city=DESTINATION,
        departure_date="2026-12-12",
        return_date="2026-12-19",
        budget_allocation=BUDGET_ALLOCATION,
    )
    center = await resolve_city_center(DESTINATION)
    ranked = rank_search_results(search_results, style="cultural", reference_location=center)

    days, itinerary_conflicts = compose_itinerary(ranked, BUDGET_ALLOCATION, DURATION_DAYS, DESTINATION)

    for day in days:
        print(f"\n--- Day {day.day_number} ---")
        print(f"Summary: {day.summary}")
        for item in day.items:
            print(f"  [{item.category}] {item.name} (₹{item.price:.0f})")

    if itinerary_conflicts:
        print("\nConflicts:")
        for c in itinerary_conflicts:
            print(f"  - {c.description} (options: {c.resolution_options})")


if __name__ == "__main__":
    asyncio.run(main())
