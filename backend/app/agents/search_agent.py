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

Amadeus/Google Places' official SDKs are synchronous. Every SDK call is
run via asyncio.to_thread so the category searches still overlap from
FastAPI's async event loop's perspective instead of blocking it.
"""
from __future__ import annotations

import asyncio
from typing import Optional

import googlemaps
from amadeus import Client as AmadeusClient
from amadeus import ResponseError as AmadeusResponseError

from app.agents.budget_agent import allocate_budget
from app.core.config import get_settings
from app.schemas.trip_state import Candidate, Conflict, SearchError

FLIGHTS = "flights"
HOTELS = "hotels"
FOOD = "food"
ACTIVITIES = "activities"

REALLOCATABLE_CATEGORIES = (HOTELS, FOOD, ACTIVITIES)

RESOLUTION_OPTIONS = ["increase_budget", "compromise_equally", "compromise_specific"]


def _get_amadeus_client() -> AmadeusClient:
    """Isolated so tests can monkeypatch this instead of mocking the SDK's internals."""
    settings = get_settings()
    return AmadeusClient(
        client_id=settings.amadeus_client_id,
        client_secret=settings.amadeus_client_secret,
    )


def _get_places_client() -> googlemaps.Client:
    settings = get_settings()
    return googlemaps.Client(key=settings.google_places_api_key)


async def search_flights(
    origin: str, destination: str, departure_date: str, budget_amount: float
) -> tuple[list[Candidate], Optional[SearchError]]:
    """Amadeus Flight Offers Search, cheapest offers first."""
    client = _get_amadeus_client()

    def _call():
        return client.shopping.flight_offers_search.get(
            originLocationCode=origin,
            destinationLocationCode=destination,
            departureDate=departure_date,
            adults=1,
            max=10,
        )

    try:
        response = await asyncio.to_thread(_call)
    except AmadeusResponseError as exc:
        status = getattr(exc.response, "status_code", None)
        reason = "rate_limited" if status == 429 else "malformed_response"
        return [], SearchError(category=FLIGHTS, reason=reason)

    offers = response.data or []
    if not offers:
        return [], SearchError(category=FLIGHTS, reason="empty_results")

    candidates = [
        Candidate(
            id=offer["id"],
            category=FLIGHTS,
            name=f"{origin} -> {destination}",
            price=float(offer["price"]["total"]),
            metadata={"raw": offer},
        )
        for offer in offers
    ]
    return candidates, None


async def search_hotels(
    destination: str, check_in: str, check_out: str, budget_amount: float
) -> tuple[list[Candidate], Optional[SearchError]]:
    """Amadeus Hotel Search: city-code lookup, then offers for that city."""
    client = _get_amadeus_client()

    def _call():
        hotel_ids_response = client.reference_data.locations.hotels.by_city.get(
            cityCode=destination
        )
        hotel_ids = [h["hotelId"] for h in (hotel_ids_response.data or [])[:20]]
        if not hotel_ids:
            return None
        return client.shopping.hotel_offers_search.get(
            hotelIds=",".join(hotel_ids),
            checkInDate=check_in,
            checkOutDate=check_out,
            adults=1,
        )

    try:
        response = await asyncio.to_thread(_call)
    except AmadeusResponseError as exc:
        status = getattr(exc.response, "status_code", None)
        reason = "rate_limited" if status == 429 else "malformed_response"
        return [], SearchError(category=HOTELS, reason=reason)

    if response is None:
        return [], SearchError(category=HOTELS, reason="empty_results")

    offers = response.data or []
    if not offers:
        return [], SearchError(category=HOTELS, reason="empty_results")

    candidates = [
        Candidate(
            id=offer["hotel"]["hotelId"],
            category=HOTELS,
            name=offer["hotel"].get("name", "Unknown hotel"),
            price=float(offer["offers"][0]["price"]["total"]),
            metadata={"raw": offer},
        )
        for offer in offers
        if offer.get("offers")
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
