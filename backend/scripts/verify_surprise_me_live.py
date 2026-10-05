"""
Run this manually to sanity-check the "surprise me" destination-suggestion
flow end to end against the REAL Groq API and real search providers --
this is NOT part of the pytest suite (pytest mocks every agent call, see
tests/test_orchestrator.py).

Run from backend/ (with PYTHONPATH=. if running outside an installed
package):
    python scripts/verify_surprise_me_live.py
"""
import asyncio
from datetime import date, timedelta

from langgraph.checkpoint.memory import InMemorySaver

from app.agents.orchestrator import compile_graph, suggest_surprise_destination
from app.schemas.trip_state import TripState, UserInput


async def main():
    # First, just the suggestion step in isolation -- cheapest way to
    # sanity-check the LLM call/prompt actually produces sensible cities
    # across different budgets/styles before running the full graph.
    print("=== suggest_surprise_destination() in isolation ===")
    samples = [
        {"budget_total": 30000, "duration_days": 3, "style": "relaxed", "priorities_raw": ""},
        {"budget_total": 250000, "duration_days": 7, "style": "adventurous", "priorities_raw": "I love mountains and hiking"},
        {"budget_total": 60000, "duration_days": 4, "style": "cultural", "priorities_raw": "history and museums"},
    ]
    for sample in samples:
        ui = UserInput(
            origin="Bangalore",
            start_date=date.today() + timedelta(days=60),
            surprise_me=True,
            **sample,
        )
        suggestion = suggest_surprise_destination(ui)
        print(f"  budget={sample['budget_total']} style={sample['style']!r} -> {suggestion}")

    # Now the full graph, end to end, for one surprise-me trip.
    print("\n=== full graph run with surprise_me=True ===")
    user_input = UserInput(
        origin="Bangalore",
        start_date=date.today() + timedelta(days=90),
        budget_total=150000,
        duration_days=2,
        surprise_me=True,
        style="relaxed",
    )
    initial_state = TripState(run_id="surprise-me-verify", user_input=user_input)
    app = compile_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "surprise-me-verify"}}
    result = await app.ainvoke(initial_state, config=config)

    print("chosen_destination:", result.get("chosen_destination"))
    if result.get("__interrupt__"):
        print("INTERRUPTED:", result["__interrupt__"][0].value)
    else:
        print("num days:", len(result.get("itinerary", [])))
        for day in result.get("itinerary", []):
            print(f"  Day {day.day_number}: {day.summary[:100]}")


if __name__ == "__main__":
    asyncio.run(main())
