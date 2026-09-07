"""
Search Agent — Ghumi_Agent_Architecture_Spec.docx §3.3, PRD §5.4

Responsibilities:
  1. One function per category (search_flights/hotels/food/activities) —
     each owns its own retry/error handling and returns Candidates or a
     SearchError, never raises.
  2. run_search_agent() — orchestrates the flights-first → budget
     reallocation loop decided in §5.4:
       - flights are searched first, alone, since they're "locked in"
         once a price is found (unlike hotels/food/activities)
       - if the real flight price undercuts its allocation, the leftover
         is redistributed across the remaining categories by reusing
         allocate_budget() on the smaller pool/category set
       - if the real flight price EXCEEDS its allocation, that's a
         conflict search_agent detects but does not resolve — it's
         recorded with concrete resolution options for the orchestrator's
         (not yet built) clarification interrupt to surface to the user

Providers:
  - Flights: Duffel (REST, Bearer token) — replaces Amadeus, whose
    self-service/test tier was decommissioned 2026-07-17.
  - Hotels: Hotelbeds (REST, Api-key + SHA-256 X-Signature) — same reason.
  - Food/activities: Google Places API (New) (REST, X-Goog-Api-Key +
    field mask) — the legacy googlemaps SDK's places()/geocode() methods
    hit the old Places API, which isn't enabled on a plain (unbilled)
    API key; the New API's searchText endpoint takes a destination name
    directly in the query text, so no separate geocoding call is needed.

All three providers are plain REST APIs, called directly via
httpx.AsyncClient — no SDK, no thread-pool wrapping needed.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Optional

import httpx

from app.agents.budget_agent import allocate_budget
from app.core.config import get_settings
from app.schemas.trip_state import Candidate, Conflict, SearchError

FLIGHTS = "flights"
HOTELS = "hotels"
FOOD = "food"
ACTIVITIES = "activities"

REALLOCATABLE_CATEGORIES = (HOTELS, FOOD, ACTIVITIES)

RESOLUTION_OPTIONS = ["increase_budget", "compromise_equally", "compromise_specific"]

# Google's enum price levels -> a rough rupee proxy, refined in Phase 2
# once real pricing data sources exist.
PRICE_LEVEL_PROXY = {
    "PRICE_LEVEL_FREE": 0,
    "PRICE_LEVEL_INEXPENSIVE": 300,
    "PRICE_LEVEL_MODERATE": 800,
    "PRICE_LEVEL_EXPENSIVE": 1500,
    "PRICE_LEVEL_VERY_EXPENSIVE": 3000,
}
DEFAULT_PRICE_PROXY = 800


def _hotelbeds_signature(api_key: str, secret: str) -> str:
    timestamp = str(int(time.time()))
    return hashlib.sha256(f"{api_key}{secret}{timestamp}".encode()).hexdigest()


async def _hotelbeds_get(path: str, params: dict) -> httpx.Response:
    """Isolated so tests can monkeypatch this instead of mocking httpx internals."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=15.0) as client:
        return await client.get(
            f"{settings.hotelbeds_base_url}{path}",
            params=params,
            headers={
                "Api-key": settings.hotelbeds_api_key,
                "X-Signature": _hotelbeds_signature(
                    settings.hotelbeds_api_key, settings.hotelbeds_api_secret
                ),
                "Accept": "application/json",
            },
        )


# Hotelbeds' destination codes are their own proprietary system (e.g. "TYO"
# for Tokyo) — not IATA airport codes, and there's no name-search endpoint,
# only a paginated master list (~7,300 entries as of 2026-09). Fetched once
# per process and cached in memory rather than re-fetched on every hotel
# search.
_hotelbeds_destination_cache: Optional[dict[str, str]] = None
_HOTELBEDS_DESTINATION_PAGE_SIZE = 500


async def _load_hotelbeds_destinations() -> dict[str, str]:
    destinations: dict[str, str] = {}
    start = 1
    while True:
        response = await _hotelbeds_get(
            "/hotel-content-api/1.0/locations/destinations",
            {
                "fields": "code,name",
                "language": "ENG",
                "from": start,
                "to": start + _HOTELBEDS_DESTINATION_PAGE_SIZE - 1,
            },
        )
        payload = response.json()
        page = payload.get("destinations", [])
        for entry in page:
            name = entry.get("name", {}).get("content", "").strip().lower()
            if name:
                destinations[name] = entry["code"]
        total = payload.get("total", 0)
        start += _HOTELBEDS_DESTINATION_PAGE_SIZE
        if start > total or not page:
            break
    return destinations


async def resolve_hotelbeds_destination_code(city_name: str) -> Optional[str]:
    """
    City name (e.g. "Tokyo", matching UserInput.destination) -> Hotelbeds
    destination code (e.g. "TYO"). Returns None if no match is found —
    callers should treat that as an empty_results SearchError, not a crash.
    """
    global _hotelbeds_destination_cache
    if _hotelbeds_destination_cache is None:
        _hotelbeds_destination_cache = await _load_hotelbeds_destinations()

    name_lower = city_name.strip().lower()
    if name_lower in _hotelbeds_destination_cache:
        return _hotelbeds_destination_cache[name_lower]

    # Fall back to substring match (e.g. "Tokyo" matching "Greater Tokyo")
    for name, code in _hotelbeds_destination_cache.items():
        if name_lower in name or name in name_lower:
            return code
    return None


async def _duffel_post(path: str, json_body: dict) -> httpx.Response:
    """Isolated so tests can monkeypatch this instead of mocking httpx internals."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=15.0) as client:
        return await client.post(
            f"{settings.duffel_base_url}{path}",
            json=json_body,
            headers={
                "Authorization": f"Bearer {settings.duffel_api_key}",
                "Duffel-Version": "v2",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )


async def _hotelbeds_post(path: str, json_body: dict) -> httpx.Response:
    """Isolated so tests can monkeypatch this instead of mocking httpx internals."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=15.0) as client:
        return await client.post(
            f"{settings.hotelbeds_base_url}{path}",
            json=json_body,
            headers={
                "Api-key": settings.hotelbeds_api_key,
                "X-Signature": _hotelbeds_signature(
                    settings.hotelbeds_api_key, settings.hotelbeds_api_secret
                ),
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )


async def _places_post(json_body: dict, field_mask: str) -> httpx.Response:
    """Isolated so tests can monkeypatch this instead of mocking httpx internals."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=15.0) as client:
        return await client.post(
            "https://places.googleapis.com/v1/places:searchText",
            json=json_body,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": settings.google_places_api_key,
                "X-Goog-FieldMask": field_mask,
            },
        )


async def search_flights(
    origin: str, destination: str, departure_date: str, budget_amount: float
) -> tuple[list[Candidate], Optional[SearchError]]:
    """Duffel offer request, one-way, single adult — cheapest offers first."""
    body = {
        "data": {
            "slices": [
                {"origin": origin, "destination": destination, "departure_date": departure_date}
            ],
            "passengers": [{"type": "adult"}],
            "cabin_class": "economy",
        }
    }

    try:
        response = await _duffel_post("/air/offer_requests?return_offers=true", body)
    except httpx.RequestError:
        return [], SearchError(category=FLIGHTS, reason="malformed_response")

    if response.status_code == 429:
        return [], SearchError(category=FLIGHTS, reason="rate_limited")
    if response.status_code >= 400:
        return [], SearchError(category=FLIGHTS, reason="malformed_response")

    try:
        payload = response.json()
        offers = payload["data"]["offers"]
    except (ValueError, KeyError, TypeError):
        return [], SearchError(category=FLIGHTS, reason="malformed_response")

    if not offers:
        return [], SearchError(category=FLIGHTS, reason="empty_results")

    candidates = [
        Candidate(
            id=offer["id"],
            category=FLIGHTS,
            name=f"{origin} -> {destination}",
            price=float(offer["total_amount"]),
            metadata={"raw": offer},
        )
        for offer in offers
    ]
    return candidates, None


async def search_hotels(
    city_name: str, check_in: str, check_out: str, budget_amount: float
) -> tuple[list[Candidate], Optional[SearchError]]:
    """
    Hotelbeds hotel-content availability search. Takes a human-readable
    city name (e.g. "Tokyo", matching UserInput.destination) — Hotelbeds
    itself needs its own proprietary destination code, so that's resolved
    internally via resolve_hotelbeds_destination_code() first.
    """
    destination_code = await resolve_hotelbeds_destination_code(city_name)
    if destination_code is None:
        return [], SearchError(category=HOTELS, reason="empty_results")

    body = {
        "stay": {"checkIn": check_in, "checkOut": check_out},
        "occupancies": [{"rooms": 1, "adults": 1, "children": 0}],
        "destination": {"code": destination_code},
    }

    try:
        response = await _hotelbeds_post("/hotel-api/1.0/hotels", body)
    except httpx.RequestError:
        return [], SearchError(category=HOTELS, reason="malformed_response")

    if response.status_code == 429:
        return [], SearchError(category=HOTELS, reason="rate_limited")
    if response.status_code >= 400:
        return [], SearchError(category=HOTELS, reason="malformed_response")

    try:
        payload = response.json()
        hotels_block = payload["hotels"]
    except (ValueError, KeyError, TypeError):
        return [], SearchError(category=HOTELS, reason="malformed_response")

    # Hotelbeds omits the "hotels" list key entirely (not even []) when
    # zero hotels match — {"hotels": {"total": 0}} is a valid empty
    # response, not a malformed one.
    hotels = hotels_block.get("hotels", [])
    if not hotels:
        return [], SearchError(category=HOTELS, reason="empty_results")

    candidates = [
        Candidate(
            id=str(hotel["code"]),
            category=HOTELS,
            name=hotel.get("name", "Unknown hotel"),
            price=float(hotel["minRate"]),
            metadata={"raw": hotel},
        )
        for hotel in hotels
        if "minRate" in hotel
    ]
    if not candidates:
        return [], SearchError(category=HOTELS, reason="empty_results")
    return candidates, None


PLACES_FIELD_MASK = (
    "places.id,places.displayName,places.rating,places.userRatingCount,places.priceLevel"
)


async def _search_places(
    destination: str, query_term: str, category: str, budget_amount: float
) -> tuple[list[Candidate], Optional[SearchError]]:
    """
    Shared Google Places (New) text search for both food and activities.
    The destination name goes straight into the query text (e.g. "restaurant
    in Tokyo") — no separate geocoding call needed.
    """
    body = {"textQuery": f"{query_term} in {destination}"}

    try:
        response = await _places_post(body, PLACES_FIELD_MASK)
    except httpx.RequestError:
        return [], SearchError(category=category, reason="malformed_response")

    if response.status_code == 429:
        return [], SearchError(category=category, reason="rate_limited")
    if response.status_code >= 400:
        return [], SearchError(category=category, reason="malformed_response")

    try:
        places = response.json().get("places", [])
    except ValueError:
        return [], SearchError(category=category, reason="malformed_response")

    if not places:
        return [], SearchError(category=category, reason="empty_results")

    candidates = [
        Candidate(
            id=place["id"],
            category=category,
            name=place.get("displayName", {}).get("text", "Unknown place"),
            price=PRICE_LEVEL_PROXY.get(place.get("priceLevel"), DEFAULT_PRICE_PROXY),
            rating=place.get("rating"),
            review_count=place.get("userRatingCount"),
            metadata={"raw": place},
        )
        for place in places
    ]
    return candidates, None


async def search_food(
    destination: str, budget_amount: float
) -> tuple[list[Candidate], Optional[SearchError]]:
    return await _search_places(destination, "restaurant", FOOD, budget_amount)


async def search_activities(
    destination: str, budget_amount: float
) -> tuple[list[Candidate], Optional[SearchError]]:
    return await _search_places(destination, "tourist_attraction", ACTIVITIES, budget_amount)


def _cheapest_price(candidates: list[Candidate]) -> Optional[float]:
    if not candidates:
        return None
    return min(c.price for c in candidates)


async def run_search_agent(
    origin_iata: str,
    destination_iata: str,
    destination_city: str,
    departure_date: str,
    return_date: str,
    budget_allocation: dict[str, float],
) -> tuple[dict[str, list[Candidate]], list[SearchError], list[Conflict]]:
    """
    Flights first, then reallocate (or flag a conflict), then the
    remaining three categories concurrently.

    origin_iata/destination_iata are airport codes (Duffel-specific).
    destination_city is the human-readable name (e.g. "Tokyo", matching
    UserInput.destination) used by Hotelbeds (resolved to its own
    destination code internally) and Google Places. These are genuinely
    different values, not redundant — Duffel, Hotelbeds, and Google Places
    each use their own location identifier system.

    Returns (search_results, search_errors, conflicts) — plain data, no
    TripState coupling, so this stays unit-testable without constructing
    a full graph state.
    """
    search_results: dict[str, list[Candidate]] = {}
    search_errors: list[SearchError] = []
    conflicts: list[Conflict] = []

    flight_candidates, flight_error = await search_flights(
        origin_iata, destination_iata, departure_date, budget_allocation[FLIGHTS]
    )
    search_results[FLIGHTS] = flight_candidates
    if flight_error:
        search_errors.append(flight_error)

    remaining_allocation = dict(budget_allocation)
    actual_flight_price = _cheapest_price(flight_candidates)

    if actual_flight_price is not None:
        delta = budget_allocation[FLIGHTS] - actual_flight_price  # positive = underspent

        if delta > 0:
            # Underspent: redistribute the leftover across hotels/food/
            # activities, reusing allocate_budget() on the smaller pool —
            # same weights, renormalized over the smaller category set.
            reallocatable_pool = sum(budget_allocation[c] for c in REALLOCATABLE_CATEGORIES)
            new_pool = reallocatable_pool + delta
            weight_sum = sum(budget_allocation[c] for c in REALLOCATABLE_CATEGORIES) or 1.0
            renormalized_weights = {
                c: budget_allocation[c] / weight_sum for c in REALLOCATABLE_CATEGORIES
            }
            reallocated = allocate_budget(new_pool, renormalized_weights)
            remaining_allocation[FLIGHTS] = actual_flight_price
            remaining_allocation.update(reallocated)
        elif delta < 0:
            # Overspent: flights are locked in, but we don't auto-resolve.
            # Record the conflict with concrete options for the (not yet
            # built) orchestrator clarification interrupt to present.
            remaining_allocation[FLIGHTS] = actual_flight_price
            conflicts.append(
                Conflict(
                    description=(
                        f"Cheapest flight found ({actual_flight_price:.2f}) exceeds its "
                        f"budget allocation ({budget_allocation[FLIGHTS]:.2f}) by "
                        f"{-delta:.2f}."
                    ),
                    category=FLIGHTS,
                    shortfall_amount=-delta,
                    resolution_options=list(RESOLUTION_OPTIONS),
                )
            )

    hotel_task = search_hotels(
        destination_city, departure_date, return_date, remaining_allocation[HOTELS]
    )
    food_task = search_food(destination_city, remaining_allocation[FOOD])
    activity_task = search_activities(destination_city, remaining_allocation[ACTIVITIES])

    (hotel_candidates, hotel_error), (food_candidates, food_error), (
        activity_candidates,
        activity_error,
    ) = await asyncio.gather(hotel_task, food_task, activity_task)

    search_results[HOTELS] = hotel_candidates
    search_results[FOOD] = food_candidates
    search_results[ACTIVITIES] = activity_candidates

    for error in (hotel_error, food_error, activity_error):
        if error:
            search_errors.append(error)

    return search_results, search_errors, conflicts
