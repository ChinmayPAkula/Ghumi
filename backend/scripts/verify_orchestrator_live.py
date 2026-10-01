"""
Run this manually to sanity-check the full orchestrator graph end to end
against REAL APIs (Duffel, LiteAPI, Google Places, Groq) -- this is NOT
part of the pytest suite (pytest mocks every agent call, see
tests/test_orchestrator.py).

Requires every key verify_search_agent_live.py / verify_itinerary_agent_live.py
need (DUFFEL_API_KEY, LITEAPI_KEY, GOOGLE_PLACES_API_KEY, GROQ_API_KEY).

Run from backend/ (with PYTHONPATH=. if running outside an installed
package):
    python scripts/verify_orchestrator_live.py
"""
import asyncio
from datetime import date, timedelta

from langgraph.checkpoint.memory import InMemorySaver

from app.agents.orchestrator import compile_graph
from app.schemas.trip_state import TripState, UserInput


async def main():
    user_input = UserInput(
        destination="Tokyo",
        origin="Bangalore",
        start_date=date.today() + timedelta(days=90),
        budget_total=200000,
        duration_days=3,
        priorities_raw="I care a lot about food, don't mind budget flights",
        style="cultural",
    )
    initial_state = TripState(run_id="live-verify-1", user_input=user_input)

    app = compile_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "live-verify-1"}}

    result = await app.ainvoke(initial_state, config=config)

    if result.get("__interrupt__"):
        print("GRAPH PAUSED FOR CLARIFICATION:")
        for i in result["__interrupt__"]:
            print(f"  {i.value}")
        print("\nResuming with acknowledgment...")
        from langgraph.types import Command

        result = await app.ainvoke(Command(resume="acknowledged"), config=config)

    print("\n=== Priority weights ===")
    print(result["priority_weights"])

    print("\n=== Budget allocation ===")
    print(result["budget_allocation"])

    print("\n=== Search result counts ===")
    for category, candidates in result["search_results"].items():
        print(f"  {category}: {len(candidates)}")

    print("\n=== Itinerary ===")
    for day in result["itinerary"]:
        print(f"\n--- Day {day.day_number} ---")
        print(f"Summary: {day.summary}")
        for item in day.items:
            print(f"  [{item.category}] {item.name} (₹{item.price:.0f})")

    if result["conflicts"]:
        print("\n=== Conflicts ===")
        for c in result["conflicts"]:
            print(f"  - {c.description}")


if __name__ == "__main__":
    asyncio.run(main())
