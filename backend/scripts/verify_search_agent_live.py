"""
Run this manually to sanity-check search_agent against the REAL Duffel
(flights), LiteAPI (hotels), and Google Places APIs — this is NOT part
of the pytest suite (pytest tests mock all three on purpose, see
tests/test_search_agent.py).

Requires in your .env:
    DUFFEL_API_KEY         (Duffel sandbox/test access token)
    LITEAPI_KEY            (LiteAPI private sandbox key)
    GOOGLE_PLACES_API_KEY  (needs Places API (New) enabled, not legacy Places API)

Amadeus is not used — its self-service/test tier was decommissioned
2026-07-17 (Enterprise API only now, not viable for this project).
Hotelbeds was also tried for hotels but its sandbox quota proved too
restrictive for active development (a handful of calls before "Quota
exceeded") — replaced with LiteAPI, whose sandbox allows 5 req/s.

Run from backend/ (with PYTHONPATH=. if running outside an installed package):
    python scripts/verify_search_agent_live.py
"""
import asyncio

from app.agents.search_agent import run_search_agent

SAMPLE_BUDGET_ALLOCATION = {
    "flights": 50000.0,
    "hotels": 20000.0,
    "food": 15000.0,
    "activities": 15000.0,
}


async def main():
    # Duffel needs IATA airport codes (BLR/HND); LiteAPI needs a country
    # code + city name (country code resolved internally from
    # destination_city via resolve_country_code(), reusing Google Places);
    # Google Places itself just takes destination_city as plain text.
    # These are genuinely different location identifier systems, not
    # redundant parameters.
    results, errors, conflicts = await run_search_agent(
        origin_iata="BLR",
        destination_iata="HND",
        destination_city="Tokyo",
        departure_date="2026-12-12",
        return_date="2026-12-19",
        budget_allocation=SAMPLE_BUDGET_ALLOCATION,
    )

    for category, candidates in results.items():
        print(f"\n{category}: {len(candidates)} result(s)")
        for c in candidates[:3]:
            print(f"  - {c.name}: {c.price}")

    if errors:
        print("\nErrors:")
        for e in errors:
            print(f"  - {e.category}: {e.reason}")

    if conflicts:
        print("\nConflicts:")
        for c in conflicts:
            print(f"  - {c.description} (options: {c.resolution_options})")


if __name__ == "__main__":
    asyncio.run(main())
