"""
Integration tests for POST /api/trip/validate-input.

These hit the route through FastAPI's TestClient (real HTTP request/response
cycle), unlike test_input_handler.py which tests UserInput/handle_input
directly. Both matter: this file proves the wiring works, that file proves
the validation logic works.
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_valid_input_returns_200_with_normalized_data():
    response = client.post("/api/trip/validate-input", json={
        "destination": "  paris  ",
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


def test_duration_over_30_returns_422():
    response = client.post("/api/trip/validate-input", json={
        "destination": "Ladakh",
        "budget_total": 40000,
        "duration_days": 45,
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