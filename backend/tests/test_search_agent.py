"""
Tests for search_agent.

All three providers (Duffel, Hotelbeds, Google Places API New) are mocked
at their respective _duffel_post/_hotelbeds_post/_places_post boundary
(plain httpx.Response objects, no real network access). Live verification
against real APIs is a separate manual step (see
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
    resolve_hotelbeds_destination_code,
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


# --- _load_hotelbeds_destinations (pagination) ---


@pytest.mark.asyncio
async def test_load_hotelbeds_destinations_paginates_until_total_reached():
    """
    Regression test: live-verified against the real sandbox that a single
    page tops out at 500 entries while the full list is ~7,300 — the loop
    must keep paging using "total" rather than stopping after one page.
    """
    from app.agents.search_agent import _load_hotelbeds_destinations, _HOTELBEDS_DESTINATION_PAGE_SIZE

    page_1 = _mock_response(
        200,
        {
            "total": _HOTELBEDS_DESTINATION_PAGE_SIZE + 1,
            "destinations": [
                {"code": f"C{i}", "name": {"content": f"City{i}"}}
                for i in range(_HOTELBEDS_DESTINATION_PAGE_SIZE)
            ],
        },
    )
    page_2 = _mock_response(
        200,
        {
            "total": _HOTELBEDS_DESTINATION_PAGE_SIZE + 1,
            "destinations": [{"code": "TYO", "name": {"content": "Tokyo"}}],
        },
    )

    with patch(
        "app.agents.search_agent._hotelbeds_get", side_effect=[page_1, page_2]
    ) as mock_get:
        destinations = await _load_hotelbeds_destinations()

    assert mock_get.call_count == 2
    assert len(destinations) == _HOTELBEDS_DESTINATION_PAGE_SIZE + 1
    assert destinations["tokyo"] == "TYO"


@pytest.mark.asyncio
async def test_load_hotelbeds_destinations_single_page_when_total_fits():
    from app.agents.search_agent import _load_hotelbeds_destinations

    page_1 = _mock_response(
        200, {"total": 2, "destinations": [{"code": "TYO", "name": {"content": "Tokyo"}}]}
    )

    with patch("app.agents.search_agent._hotelbeds_get", return_value=page_1) as mock_get:
        destinations = await _load_hotelbeds_destinations()

    assert mock_get.call_count == 1
    assert destinations == {"tokyo": "TYO"}


# --- resolve_hotelbeds_destination_code ---


@pytest.mark.asyncio
async def test_resolve_hotelbeds_destination_code_exact_match():
    import app.agents.search_agent as search_agent_module

    search_agent_module._hotelbeds_destination_cache = {"tokyo": "TYO", "paris": "PAR"}
    try:
        code = await resolve_hotelbeds_destination_code("Tokyo")
    finally:
        search_agent_module._hotelbeds_destination_cache = None

    assert code == "TYO"


@pytest.mark.asyncio
async def test_resolve_hotelbeds_destination_code_no_match_returns_none():
    import app.agents.search_agent as search_agent_module

    search_agent_module._hotelbeds_destination_cache = {"tokyo": "TYO"}
    try:
        code = await resolve_hotelbeds_destination_code("Nowhereville")
    finally:
        search_agent_module._hotelbeds_destination_cache = None

    assert code is None


# --- search_hotels (Hotelbeds) ---


@pytest.mark.asyncio
async def test_search_hotels_returns_candidates_on_success():
    mock_response = _mock_response(
        200,
        {"hotels": {"hotels": [{"code": 123, "name": "Test Hotel", "minRate": "8000.00"}]}},
    )

    with patch(
        "app.agents.search_agent.resolve_hotelbeds_destination_code", return_value="TYO"
    ), patch("app.agents.search_agent._hotelbeds_post", return_value=mock_response):
        candidates, error = await search_hotels("Tokyo", "2026-03-12", "2026-03-19", 30000)

    assert error is None
    assert candidates[0].name == "Test Hotel"
    assert candidates[0].price == 8000.0


@pytest.mark.asyncio
async def test_search_hotels_unresolvable_city_is_empty_results():
    with patch(
        "app.agents.search_agent.resolve_hotelbeds_destination_code", return_value=None
    ):
        candidates, error = await search_hotels("Nowhereville", "2026-03-12", "2026-03-19", 30000)

    assert candidates == []
    assert error.category == HOTELS
    assert error.reason == "empty_results"


@pytest.mark.asyncio
async def test_search_hotels_no_matches_is_empty_results():
    mock_response = _mock_response(200, {"hotels": {"hotels": []}})

    with patch(
        "app.agents.search_agent.resolve_hotelbeds_destination_code", return_value="ZZZ"
    ), patch("app.agents.search_agent._hotelbeds_post", return_value=mock_response):
        candidates, error = await search_hotels("Nowhereville", "2026-03-12", "2026-03-19", 30000)

    assert candidates == []
    assert error.category == HOTELS
    assert error.reason == "empty_results"


@pytest.mark.asyncio
async def test_search_hotels_malformed_json_shape():
    mock_response = _mock_response(200, {"unexpected": "shape"})

    with patch(
        "app.agents.search_agent.resolve_hotelbeds_destination_code", return_value="TYO"
    ), patch("app.agents.search_agent._hotelbeds_post", return_value=mock_response):
        candidates, error = await search_hotels("Tokyo", "2026-03-12", "2026-03-19", 30000)

    assert candidates == []
    assert error.reason == "malformed_response"


@pytest.mark.asyncio
async def test_search_hotels_omitted_list_key_is_empty_not_malformed():
    """
    Regression test: Hotelbeds omits the "hotels" list key entirely (not
    even []) when zero hotels match a destination — {"hotels": {"total": 0}}
    is a valid empty response, caught live against the real sandbox API,
    and must not be misclassified as malformed_response.
    """
    mock_response = _mock_response(200, {"hotels": {"total": 0}})

    with patch(
        "app.agents.search_agent.resolve_hotelbeds_destination_code", return_value="TYO"
    ), patch("app.agents.search_agent._hotelbeds_post", return_value=mock_response):
        candidates, error = await search_hotels("Tokyo", "2026-12-12", "2026-12-19", 30000)

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
