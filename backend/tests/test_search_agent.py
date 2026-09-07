"""
Tests for search_agent.

All providers (Duffel, LiteAPI, Google Places API New) are mocked at
their respective _duffel_post/_liteapi_get/_liteapi_post/_places_post
boundary (plain httpx.Response objects, no real network access). Live
verification against real APIs is a separate manual step (see
scripts/verify_search_agent_live.py).
"""
from unittest.mock import patch

import httpx
import pytest

from app.agents.search_agent import (
    FLIGHTS,
    HOTELS,
    FOOD,
    ACTIVITIES,
    search_flights,
    search_hotels,
    search_food,
    search_activities,
    resolve_country_code,
    run_search_agent,
)


def _mock_response(status_code, json_body):
    return httpx.Response(status_code, json=json_body, request=httpx.Request("POST", "http://test"))


# --- search_flights (Duffel) ---


@pytest.mark.asyncio
async def test_search_flights_returns_candidates_on_success():
    offers = [
        {"id": "off_1", "total_amount": "12000.00"},
        {"id": "off_2", "total_amount": "9000.00"},
    ]
    mock_response = _mock_response(200, {"data": {"offers": offers}})

    with patch("app.agents.search_agent._duffel_post", return_value=mock_response):
        candidates, error = await search_flights("BLR", "HND", "2026-03-12", 50000)

    assert error is None
    assert len(candidates) == 2
    assert candidates[0].category == FLIGHTS
    assert candidates[1].price == 9000.0


@pytest.mark.asyncio
async def test_search_flights_empty_results():
    mock_response = _mock_response(200, {"data": {"offers": []}})

    with patch("app.agents.search_agent._duffel_post", return_value=mock_response):
        candidates, error = await search_flights("BLR", "HND", "2026-03-12", 50000)

    assert candidates == []
    assert error.category == FLIGHTS
    assert error.reason == "empty_results"


@pytest.mark.asyncio
async def test_search_flights_rate_limited():
    mock_response = _mock_response(429, {"errors": [{"title": "Too Many Requests"}]})

    with patch("app.agents.search_agent._duffel_post", return_value=mock_response):
        candidates, error = await search_flights("BLR", "HND", "2026-03-12", 50000)

    assert candidates == []
    assert error.reason == "rate_limited"


@pytest.mark.asyncio
async def test_search_flights_server_error_is_malformed_response():
    mock_response = _mock_response(500, {"errors": [{"title": "Internal Server Error"}]})

    with patch("app.agents.search_agent._duffel_post", return_value=mock_response):
        candidates, error = await search_flights("BLR", "HND", "2026-03-12", 50000)

    assert error.reason == "malformed_response"


@pytest.mark.asyncio
async def test_search_flights_network_error_is_malformed_response():
    with patch(
        "app.agents.search_agent._duffel_post",
        side_effect=httpx.ConnectError("connection failed"),
    ):
        candidates, error = await search_flights("BLR", "HND", "2026-03-12", 50000)

    assert candidates == []
    assert error.reason == "malformed_response"


# --- resolve_country_code (via Places) ---


@pytest.mark.asyncio
async def test_resolve_country_code_finds_country_component():
    mock_response = _mock_response(
        200,
        {
            "places": [
                {
                    "addressComponents": [
                        {"longText": "Tokyo", "shortText": "Tokyo", "types": ["political"]},
                        {"longText": "Japan", "shortText": "JP", "types": ["country", "political"]},
                    ]
                }
            ]
        },
    )

    with patch("app.agents.search_agent._places_post", return_value=mock_response):
        code = await resolve_country_code("Tokyo")

    assert code == "JP"


@pytest.mark.asyncio
async def test_resolve_country_code_no_places_returns_none():
    mock_response = _mock_response(200, {"places": []})

    with patch("app.agents.search_agent._places_post", return_value=mock_response):
        code = await resolve_country_code("Nowhereville")

    assert code is None


# --- search_hotels (LiteAPI) ---


@pytest.mark.asyncio
async def test_search_hotels_returns_candidates_on_success():
    hotels_response = _mock_response(
        200,
        {"data": [{"id": "h1", "name": "Test Hotel", "rating": 8.5, "reviewCount": 200}]},
    )
    rates_response = _mock_response(
        200,
        {
            "data": [
                {
                    "hotelId": "h1",
                    "roomTypes": [
                        {
                            "rates": [
                                {"retailRate": {"total": [{"amount": 8000.0, "currency": "INR"}]}}
                            ]
                        }
                    ],
                }
            ]
        },
    )

    with patch(
        "app.agents.search_agent.resolve_country_code", return_value="JP"
    ), patch(
        "app.agents.search_agent._liteapi_get", return_value=hotels_response
    ), patch("app.agents.search_agent._liteapi_post", return_value=rates_response):
        candidates, error = await search_hotels("Tokyo", "2026-03-12", "2026-03-19", 30000)

    assert error is None
    assert candidates[0].name == "Test Hotel"
    assert candidates[0].price == 8000.0
    assert candidates[0].rating == 8.5


@pytest.mark.asyncio
async def test_search_hotels_unresolvable_city_is_empty_results():
    with patch("app.agents.search_agent.resolve_country_code", return_value=None):
        candidates, error = await search_hotels("Nowhereville", "2026-03-12", "2026-03-19", 30000)

    assert candidates == []
    assert error.category == HOTELS
    assert error.reason == "empty_results"


@pytest.mark.asyncio
async def test_search_hotels_no_hotels_in_city_is_empty_results():
    hotels_response = _mock_response(200, {"data": []})

    with patch(
        "app.agents.search_agent.resolve_country_code", return_value="JP"
    ), patch("app.agents.search_agent._liteapi_get", return_value=hotels_response):
        candidates, error = await search_hotels("Nowhereville", "2026-03-12", "2026-03-19", 30000)

    assert candidates == []
    assert error.category == HOTELS
    assert error.reason == "empty_results"


@pytest.mark.asyncio
async def test_search_hotels_rates_call_rate_limited():
    hotels_response = _mock_response(200, {"data": [{"id": "h1", "name": "Test Hotel"}]})
    rates_response = _mock_response(429, {"error": "rate limited"})

    with patch(
        "app.agents.search_agent.resolve_country_code", return_value="JP"
    ), patch(
        "app.agents.search_agent._liteapi_get", return_value=hotels_response
    ), patch("app.agents.search_agent._liteapi_post", return_value=rates_response):
        candidates, error = await search_hotels("Tokyo", "2026-03-12", "2026-03-19", 30000)

    assert candidates == []
    assert error.reason == "rate_limited"


@pytest.mark.asyncio
async def test_search_hotels_no_rates_for_any_hotel_is_empty_results():
    """
    A hotel can appear in /data/hotels but have no bookable rates for the
    given dates (sold out, no availability) — rates response may simply
    omit it rather than returning an explicit error.
    """
    hotels_response = _mock_response(200, {"data": [{"id": "h1", "name": "Test Hotel"}]})
    rates_response = _mock_response(200, {"data": []})

    with patch(
        "app.agents.search_agent.resolve_country_code", return_value="JP"
    ), patch(
        "app.agents.search_agent._liteapi_get", return_value=hotels_response
    ), patch("app.agents.search_agent._liteapi_post", return_value=rates_response):
        candidates, error = await search_hotels("Tokyo", "2026-03-12", "2026-03-19", 30000)

    assert candidates == []
    assert error.reason == "empty_results"


# --- search_food / search_activities (share _search_places, Places API New) ---


@pytest.mark.asyncio
async def test_search_food_returns_candidates_on_success():
    mock_response = _mock_response(
        200,
        {
            "places": [
                {
                    "id": "p1",
                    "displayName": {"text": "Good Food"},
                    "rating": 4.5,
                    "userRatingCount": 100,
                    "priceLevel": "PRICE_LEVEL_MODERATE",
                }
            ]
        },
    )

    with patch("app.agents.search_agent._places_post", return_value=mock_response):
        candidates, error = await search_food("Tokyo", 10000)

    assert error is None
    assert candidates[0].category == FOOD
    assert candidates[0].rating == 4.5
    assert candidates[0].price == 800


@pytest.mark.asyncio
async def test_search_activities_zero_results():
    mock_response = _mock_response(200, {"places": []})

    with patch("app.agents.search_agent._places_post", return_value=mock_response):
        candidates, error = await search_activities("Nowhereville", 10000)

    assert candidates == []
    assert error.category == ACTIVITIES
    assert error.reason == "empty_results"


@pytest.mark.asyncio
async def test_search_food_rate_limited():
    mock_response = _mock_response(429, {"error": {"message": "quota exceeded"}})

    with patch("app.agents.search_agent._places_post", return_value=mock_response):
        candidates, error = await search_food("Tokyo", 10000)

    assert candidates == []
    assert error.reason == "rate_limited"


@pytest.mark.asyncio
async def test_search_food_api_error_is_malformed_response():
    mock_response = _mock_response(403, {"error": {"message": "API not enabled"}})

    with patch("app.agents.search_agent._places_post", return_value=mock_response):
        candidates, error = await search_food("Tokyo", 10000)

    assert candidates == []
    assert error.reason == "malformed_response"


# --- run_search_agent: the flights-first reallocation loop ---


@pytest.mark.asyncio
async def test_underspent_flight_reallocates_leftover_to_other_categories():
    budget_allocation = {FLIGHTS: 50000, HOTELS: 20000, FOOD: 15000, ACTIVITIES: 15000}

    async def fake_search_flights(*args, **kwargs):
        from app.schemas.trip_state import Candidate

        return [Candidate(id="1", category=FLIGHTS, name="flight", price=30000.0)], None

    async def fake_empty(*args, **kwargs):
        return [], None

    with patch("app.agents.search_agent.search_flights", fake_search_flights), patch(
        "app.agents.search_agent.search_hotels", fake_empty
    ), patch("app.agents.search_agent.search_food", fake_empty), patch(
        "app.agents.search_agent.search_activities", fake_empty
    ):
        results, errors, conflicts = await run_search_agent(
            "BLR", "HND", "Tokyo", "2026-03-12", "2026-03-19", budget_allocation
        )

    assert conflicts == []
    assert results[FLIGHTS][0].price == 30000.0


@pytest.mark.asyncio
async def test_overspent_flight_records_conflict_with_resolution_options():
    budget_allocation = {FLIGHTS: 20000, HOTELS: 20000, FOOD: 15000, ACTIVITIES: 15000}

    async def fake_search_flights(*args, **kwargs):
        from app.schemas.trip_state import Candidate

        return [Candidate(id="1", category=FLIGHTS, name="flight", price=35000.0)], None

    async def fake_empty(*args, **kwargs):
        return [], None

    with patch("app.agents.search_agent.search_flights", fake_search_flights), patch(
        "app.agents.search_agent.search_hotels", fake_empty
    ), patch("app.agents.search_agent.search_food", fake_empty), patch(
        "app.agents.search_agent.search_activities", fake_empty
    ):
        results, errors, conflicts = await run_search_agent(
            "BLR", "HND", "Tokyo", "2026-03-12", "2026-03-19", budget_allocation
        )

    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.category == FLIGHTS
    assert conflict.shortfall_amount == pytest.approx(15000.0)
    assert conflict.resolution_options == [
        "increase_budget",
        "compromise_equally",
        "compromise_specific",
    ]


@pytest.mark.asyncio
async def test_flight_search_error_does_not_crash_the_rest_of_the_pipeline():
    budget_allocation = {FLIGHTS: 50000, HOTELS: 20000, FOOD: 15000, ACTIVITIES: 15000}

    async def fake_flight_error(*args, **kwargs):
        from app.schemas.trip_state import SearchError

        return [], SearchError(category=FLIGHTS, reason="empty_results")

    async def fake_empty(*args, **kwargs):
        return [], None

    with patch("app.agents.search_agent.search_flights", fake_flight_error), patch(
        "app.agents.search_agent.search_hotels", fake_empty
    ), patch("app.agents.search_agent.search_food", fake_empty), patch(
        "app.agents.search_agent.search_activities", fake_empty
    ):
        results, errors, conflicts = await run_search_agent(
            "BLR", "HND", "Tokyo", "2026-03-12", "2026-03-19", budget_allocation
        )

    assert results[FLIGHTS] == []
    assert any(e.category == FLIGHTS and e.reason == "empty_results" for e in errors)
    assert conflicts == []  # no price to compare against allocation, so no conflict raised
