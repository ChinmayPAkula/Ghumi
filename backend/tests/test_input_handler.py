"""
Tests for input_handler. Currently just a placeholder proving the test
harness itself works — real validation tests get added once
input_handler.py has actual logic in it.
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check():
    """Sanity check that the app boots and /health responds correctly."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"