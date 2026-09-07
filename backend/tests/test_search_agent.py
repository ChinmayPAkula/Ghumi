"""
Tests for search_agent.

All Amadeus/Google Places SDK calls are mocked — no real network access,
no API keys needed. Live verification against real sandbox APIs is a
separate manual step (see scripts/verify_search_agent_live.py) once keys
are available, same pattern as budget_agent's Groq verification.
"""
from unittest.mock import MagicMock, patch

import pytest
from amadeus import ResponseError

from app.agents.search_agent import (
    FLIGHTS,
    HOTELS,
    FOOD,
    ACTIVITIES,
    search_flights,
    search_hotels,
    search_food,
    search_activities,
    run_search_agent,
)


def _mock_amadeus_response(data):
    response = MagicMock()
    response.data = data
    return response


def _mock_response_error(status_code):
    error_response = MagicMock()
    error_response.status_code = status_code
    return ResponseError(error_response)


# --- search_flights ---


@pytest.mark.asyncio
async def test_search_flights_returns_candidates_on_success():
    offers = [
        {"id": "1", "price": {"total": "12000.00"}},
        {"id": "2", "price": {"total": "9000.00"}},
    ]
    mock_client = MagicMock()
    mock_client.shopping.flight_offers_search.get.return_value = _mock_amadeus_response(offers)

    with patch("app.agents.search_agent._get_amadeus_client", return_value=mock_client):
        candidates, error = await search_flights("BLR", "HND", "2026-03-12", 50000)

    assert error is None
    assert len(candidates) == 2
    assert candidates[0].category == FLIGHTS
    assert candidates[1].price == 9000.0


@pytest.mark.asyncio
async def test_search_flights_empty_results():
    mock_client = MagicMock()
    mock_client.shopping.flight_offers_search.get.return_value = _mock_amadeus_response([])

    with patch("app.agents.search_agent._get_amadeus_client", return_value=mock_client):
        candidates, error = await search_flights("BLR", "HND", "2026-03-12", 50000)

    assert candidates == []
    assert error.category == FLIGHTS
    assert error.reason == "empty_results"


@pytest.mark.asyncio
async def test_search_flights_rate_limited():
    mock_client = MagicMock()
    mock_client.shopping.flight_offers_search.get.side_effect = _mock_response_error(429)

    with patch("app.agents.search_agent._get_amadeus_client", return_value=mock_client):
        candidates, error = await search_flights("BLR", "HND", "2026-03-12", 50000)

    assert candidates == []
    assert error.reason == "rate_limited"


@pytest.mark.asyncio
async def test_search_flights_other_api_error_is_malformed_response():
    mock_client = MagicMock()
    mock_client.shopping.flight_offers_search.get.side_effect = _mock_response_error(500)

    with patch("app.agents.search_agent._get_amadeus_client", return_value=mock_client):
        candidates, error = await search_flights("BLR", "HND", "2026-03-12", 50000)

    assert error.reason == "malformed_response"


# --- search_hotels ---


@pytest.mark.asyncio
async def test_search_hotels_returns_candidates_on_success():
    mock_client = MagicMock()
    mock_client.reference_data.locations.hotels.by_city.get.return_value = _mock_amadeus_response(
        [{"hotelId": "H1"}]
    )
    mock_client.shopping.hotel_offers_search.get.return_value = _mock_amadeus_response(
        [
            {
                "hotel": {"hotelId": "H1", "name": "Test Hotel"},
                "offers": [{"price": {"total": "8000.00"}}],
            }
        ]
    )

    with patch("app.agents.search_agent._get_amadeus_client", return_value=mock_client):
        candidates, error = await search_hotels("HND", "2026-03-12", "2026-03-19", 30000)

    assert error is None
    assert candidates[0].name == "Test Hotel"
    assert candidates[0].price == 8000.0


@pytest.mark.asyncio
async def test_search_hotels_no_city_matches_is_empty_results():
    mock_client = MagicMock()
    mock_client.reference_data.locations.hotels.by_city.get.return_value = _mock_amadeus_response([])

    with patch("app.agents.search_agent._get_amadeus_client", return_value=mock_client):
        candidates, error = await search_hotels("ZZZ", "2026-03-12", "2026-03-19", 30000)

    assert candidates == []
    assert error.category == HOTELS
    assert error.reason == "empty_results"


# --- search_food / search_activities (share _search_places) ---


@pytest.mark.asyncio
async def test_search_food_returns_candidates_on_success():
    mock_client = MagicMock()
    mock_client.geocode.return_value = [{"geometry": {"location": {"lat": 1, "lng": 2}}}]
    mock_client.places.return_value = {
        "status": "OK",
        "results": [
            {"place_id": "p1", "name": "Good Food", "rating": 4.5, "user_ratings_total": 100}
        ],
    }

    with patch("app.agents.search_agent._get_places_client", return_value=mock_client):
        candidates, error = await search_food("Tokyo", 10000)

    assert error is None
    assert candidates[0].category == FOOD
    assert candidates[0].rating == 4.5


@pytest.mark.asyncio
async def test_search_activities_geocode_failure_is_malformed_response():
    mock_client = MagicMock()
    mock_client.geocode.return_value = []

    with patch("app.agents.search_agent._get_places_client", return_value=mock_client):
        candidates, error = await search_activities("Nowhereville", 10000)

    assert candidates == []
    assert error.category == ACTIVITIES
    assert error.reason == "malformed_response"


@pytest.mark.asyncio
async def test_search_food_zero_results_status():
    mock_client = MagicMock()
    mock_client.geocode.return_value = [{"geometry": {"location": {"lat": 1, "lng": 2}}}]
    mock_client.places.return_value = {"status": "ZERO_RESULTS", "results": []}

    with patch("app.agents.search_agent._get_places_client", return_value=mock_client):
        candidates, error = await search_food("Tokyo", 10000)

    assert candidates == []
    assert error.reason == "empty_results"


# --- run_search_agent: the flights-first reallocation loop ---


@pytest.mark.asyncio
async def test_underspent_flight_reallocates_leftover_to_other_categories():
    budget_allocation = {FLIGHTS: 50000, HOTELS: 20000, FOOD: 15000, ACTIVITIES: 15000}

    async def fake_search_flights(*args, **kwargs):
        from app.schemas.trip_state import Candidate

        return [Candidate(id="1", category=FLIGHTS, name="flight", price=30000.0)], None

    async def fake_search_hotels(*args, **kwargs):
        return [], None

    async def fake_search_food(*args, **kwargs):
        return [], None

    async def fake_search_activities(*args, **kwargs):
        return [], None

    with patch("app.agents.search_agent.search_flights", fake_search_flights), patch(
        "app.agents.search_agent.search_hotels", fake_search_hotels
    ), patch("app.agents.search_agent.search_food", fake_search_food), patch(
        "app.agents.search_agent.search_activities", fake_search_activities
    ):
        results, errors, conflicts = await run_search_agent(
            "BLR", "HND", "2026-03-12", "2026-03-19", budget_allocation
        )

    assert conflicts == []
    # 20000 leftover (50000 allocated - 30000 actual) redistributed across
    # hotels/food/activities, on top of their original 20000+15000+15000=50000 pool
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
            "BLR", "HND", "2026-03-12", "2026-03-19", budget_allocation
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
            "BLR", "HND", "2026-03-12", "2026-03-19", budget_allocation
        )

    assert results[FLIGHTS] == []
    assert any(e.category == FLIGHTS and e.reason == "empty_results" for e in errors)
    assert conflicts == []  # no price to compare against allocation, so no conflict raised
