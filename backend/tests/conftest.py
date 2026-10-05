"""
Shared pytest fixtures.
"""
import pytest

from app.core.rate_limit import limiter


@pytest.fixture(autouse=True)
def disable_rate_limiting():
    """
    test_trip_routes.py makes several real calls to /api/trip/plan within
    one test run, sharing slowapi's in-memory counter (keyed by the
    TestClient's fixed IP) across every test in the session. Without this,
    the suite would sit right at the 5/minute limit and start failing with
    429s the moment a test is added or the suite is re-run quickly --
    rate limiting is a production concern, not something the test suite
    itself should be subject to.
    """
    limiter.enabled = False
    yield
    limiter.enabled = True
