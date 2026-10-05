"""
Integration tests for POST /api/trip/validate-input.

These hit the route through FastAPI's TestClient (real HTTP request/response
cycle), unlike test_input_handler.py which tests UserInput/handle_input
directly. Both matter: this file proves the wiring works, that file proves
the validation logic works.
"""
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.agents.orchestrator import get_compiled_graph
from app.main import app

client = TestClient(app)

FUTURE_DATE = (date.today() + timedelta(days=30)).isoformat()


def _plan_payload(**overrides):
    payload = {
        "destination": "Tokyo",
        "origin": "Bangalore",
        "start_date": FUTURE_DATE,
        "budget_total": 200000,
        "duration_days": 3,
        "style": "cultural",
    }
    payload.update(overrides)
    return payload


def _patch_agents(
    iata_result="HND",
    search_result=None,
    itinerary_result=None,
):
    search_result = search_result or ({"flights": []}, [], [])
    itinerary_result = itinerary_result or ([], [])
    return (
        patch(
            "app.agents.orchestrator.parse_priority_weights",
            return_value={"flights": 0.2, "hotels": 0.2, "food": 0.2, "activities": 0.2, "transport": 0.2},
        ),
        patch(
            "app.agents.orchestrator.allocate_budget",
            return_value={"flights": 20000, "hotels": 20000, "food": 20000, "activities": 20000, "transport": 20000},
        ),
        patch("app.agents.orchestrator.resolve_iata_code", new=AsyncMock(return_value=iata_result)),
        patch("app.agents.orchestrator.run_search_agent", new=AsyncMock(return_value=search_result)),
        patch("app.agents.orchestrator.resolve_city_center", new=AsyncMock(return_value=None)),
        patch("app.agents.orchestrator.rank_search_results", return_value={"flights": []}),
        patch("app.agents.orchestrator.compose_itinerary", return_value=itinerary_result),
    )


def setup_function():
    # get_compiled_graph() is @lru_cache'd (process-wide singleton) -- clear
    # it between tests so each test gets a fresh InMemorySaver, otherwise
    # thread_ids could theoretically collide with leftover state across tests.
    get_compiled_graph.cache_clear()


def test_valid_input_returns_200_with_normalized_data():
    response = client.post("/api/trip/validate-input", json={
        "destination": "  paris  ",
        "origin": "Bangalore",
        "start_date": FUTURE_DATE,
        "budget_total": 90000,
        "duration_days": 6,
        "style": "cultural",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["destination"] == "Paris"
    assert body["budget_total"] == 90000


def test_surprise_me_without_destination_returns_200():
    response = client.post("/api/trip/validate-input", json={
        "surprise_me": True,
        "origin": "Bangalore",
        "start_date": FUTURE_DATE,
        "budget_total": 60000,
        "duration_days": 5,
    })
    assert response.status_code == 200
    assert response.json()["destination"] is None


def test_negative_budget_returns_422_with_field_location():
    response = client.post("/api/trip/validate-input", json={
        "destination": "Goa",
        "budget_total": -500,
        "duration_days": 4,
    })
    assert response.status_code == 422
    errors = response.json()["detail"]
    assert any(e["loc"][-1] == "budget_total" for e in errors)


def test_duration_over_50_returns_422():
    response = client.post("/api/trip/validate-input", json={
        "destination": "Ladakh",
        "budget_total": 40000,
        "duration_days": 51,
    })
    assert response.status_code == 422
    errors = response.json()["detail"]
    assert any(e["loc"][-1] == "duration_days" for e in errors)


def test_no_destination_no_surprise_me_returns_422():
    response = client.post("/api/trip/validate-input", json={
        "budget_total": 40000,
        "duration_days": 5,
    })
    assert response.status_code == 422


# --- POST /trip/plan + /trip/plan/{run_id}/resume ---


def test_plan_invalid_input_still_returns_422():
    # UserInput validation runs before the graph does anything real --
    # confirms /plan doesn't bypass the same field validation /validate-input uses.
    response = client.post("/api/trip/plan", json={"budget_total": -1, "duration_days": 5})
    assert response.status_code == 422


def test_plan_happy_path_returns_completed_with_itinerary():
    from app.schemas.trip_state import DayPlan

    patches = _patch_agents(itinerary_result=([DayPlan(day_number=1)], []))
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        response = client.post("/api/trip/plan", json=_plan_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert len(body["itinerary"]) == 1
    assert body["conflicts"] == []
    assert "run_id" in body


def test_plan_conflict_returns_needs_clarification():
    from app.schemas.trip_state import Conflict

    flight_conflict = Conflict(description="flight overspend", category="flights")
    patches = _patch_agents(search_result=({"flights": []}, [], [flight_conflict]))
    with patches[0], patches[1], patches[2], patches[3]:
        response = client.post("/api/trip/plan", json=_plan_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "needs_clarification"
    assert body["clarification"]["stage"] == "after_search"
    assert len(body["clarification"]["conflicts"]) == 1
    assert body["itinerary"] == []


def test_resume_unknown_run_id_returns_404():
    response = client.post("/api/trip/plan/nonexistent-run-id/resume", json={"choice": "ack"})
    assert response.status_code == 404


def test_resume_continues_paused_run_to_completion():
    from app.schemas.trip_state import Conflict, DayPlan

    flight_conflict = Conflict(description="flight overspend", category="flights")
    patches = _patch_agents(search_result=({"flights": []}, [], [flight_conflict]))
    with patches[0], patches[1], patches[2], patches[3]:
        first = client.post("/api/trip/plan", json=_plan_payload())
    run_id = first.json()["run_id"]
    assert first.json()["status"] == "needs_clarification"

    patches2 = _patch_agents(itinerary_result=([DayPlan(day_number=1)], []))
    with patches2[4], patches2[5], patches2[6]:
        second = client.post(f"/api/trip/plan/{run_id}/resume", json={"choice": "increase_budget"})

    assert second.status_code == 200
    body = second.json()
    assert body["status"] == "completed"
    assert len(body["itinerary"]) == 1


def test_resume_already_completed_run_returns_404():
    patches = _patch_agents()
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        first = client.post("/api/trip/plan", json=_plan_payload())
    run_id = first.json()["run_id"]
    assert first.json()["status"] == "completed"

    response = client.post(f"/api/trip/plan/{run_id}/resume", json={"choice": "ack"})
    assert response.status_code == 404


def test_plan_endpoint_is_rate_limited():
    """
    Proves rate limiting actually blocks excess requests, rather than just
    trusting the decorator is wired correctly. Re-enables the limiter
    (disabled everywhere else by conftest.py's autouse fixture) just for
    this one test, and resets its counter afterward so it doesn't bleed
    into other tests.
    """
    from app.core.rate_limit import limiter

    limiter.enabled = True
    try:
        limiter.reset()
        patches = _patch_agents()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            responses = [client.post("/api/trip/plan", json=_plan_payload()) for _ in range(6)]
    finally:
        limiter.reset()
        limiter.enabled = False

    statuses = [r.status_code for r in responses]
    assert statuses.count(200) == 5  # the configured 5/minute limit
    assert statuses.count(429) == 1  # the 6th request gets blocked