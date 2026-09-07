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
  - Food/activities: Google Places SDK (unaffected, still official/sync).

Duffel and Hotelbeds are called directly over HTTP via httpx.AsyncClient
(no official/blocking SDK involved, so no thread-pool wrapping needed).
The Google Places SDK is synchronous, so its calls are run via
asyncio.to_thread so they don't block the event loop.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Optional

import googlemaps
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


def _get_places_client() -> googlemaps.Client:
    settings = get_settings()
    return googlemaps.Client(key=settings.google_places_api_key)


def _hotelbeds_signature(api_key: str, secret: str) -> str:
    timestamp = str(int(time.time()))
    return hashlib.sha256(f"{api_key}{secret}{timestamp}".encode()).hexdigest()


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
    destination: str, check_in: str, check_out: str, budget_amount: float
) -> tuple[list[Candidate], Optional[SearchError]]:
    """Hotelbeds hotel-content availability search by destination city code."""
    body = {
        "stay": {"checkIn": check_in, "checkOut": check_out},
        "occupancies": [{"rooms": 1, "adults": 1, "children": 0}],
        "destination": {"code": destination},
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
        hotels = payload["hotels"]["hotels"]
    except (ValueError, KeyError, TypeError):
        return [], SearchError(category=HOTELS, reason="malformed_response")

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


async def _search_places(
    destination: str, place_type: str, category: str, budget_amount: float
) -> tuple[list[Candidate], Optional[SearchError]]:
    """Shared Google Places lookup for both food and activities."""
    client = _get_places_client()

    def _call():
        geocode = client.geocode(destination)
        if not geocode:
            return None
        location = geocode[0]["geometry"]["location"]
        return client.places(query=place_type, location=location, type=place_type)

    try:
        response = await asyncio.to_thread(_call)
    except googlemaps.exceptions.ApiError:
        return [], SearchError(category=category, reason="malformed_response")
    except googlemaps.exceptions.Timeout:
        return [], SearchError(category=category, reason="rate_limited")

    if response is None or response.get("status") not in ("OK", "ZERO_RESULTS"):
        return [], SearchError(category=category, reason="malformed_response")

    results = response.get("results", [])
    if not results:
        return [], SearchError(category=category, reason="empty_results")

    candidates = [
        Candidate(
            id=place["place_id"],
            category=category,
            name=place.get("name", "Unknown place"),
            price=float(place.get("price_level", 2)) * 500,  # rough proxy, refined in Phase 2
            rating=place.get("rating"),
            review_count=place.get("user_ratings_total"),
            metadata={"raw": place},
        )
        for place in results
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
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str,
    budget_allocation: dict[str, float],
) -> tuple[dict[str, list[Candidate]], list[SearchError], list[Conflict]]:
    """
    Flights first, then reallocate (or flag a conflict), then the
    remaining three categories concurrently.

    Returns (search_results, search_errors, conflicts) — plain data, no
    TripState coupling, so this stays unit-testable without constructing
    a full graph state.
    """
    search_results: dict[str, list[Candidate]] = {}
    search_errors: list[SearchError] = []
    conflicts: list[Conflict] = []

    flight_candidates, flight_error = await search_flights(
        origin, destination, departure_date, budget_allocation[FLIGHTS]
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
        destination, departure_date, return_date, remaining_allocation[HOTELS]
    )
    food_task = search_food(destination, remaining_allocation[FOOD])
    activity_task = search_activities(destination, remaining_allocation[ACTIVITIES])

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
