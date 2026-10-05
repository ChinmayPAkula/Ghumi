"""
Run this manually to sanity-check the full plan -> book flow end to end
against REAL APIs (Duffel, LiteAPI, Google Places, Groq) -- this is NOT
part of the pytest suite (pytest mocks every agent/booking call).

Run from backend/ (with PYTHONPATH=. if running outside an installed
package):
    python scripts/verify_booking_live.py
"""
from datetime import date, timedelta

import httpx

BASE_URL = "http://localhost:8000/api/trip"


def main():
    future_date = (date.today() + timedelta(days=90)).isoformat()

    plan_payload = {
        "destination": "Tokyo",
        "origin": "Bangalore",
        "start_date": future_date,
        "budget_total": 300000,
        "duration_days": 2,
        "style": "cultural",
    }

    print("=== Planning trip ===")
    resp = httpx.post(f"{BASE_URL}/plan", json=plan_payload, timeout=120)
    plan = resp.json()
    print("status:", plan["status"])
    run_id = plan["run_id"]

    if plan["status"] == "needs_clarification":
        print("Resuming past clarification...")
        resp = httpx.post(
            f"{BASE_URL}/plan/{run_id}/resume", json={"choice": "increase_budget"}, timeout=120
        )
        plan = resp.json()
        print("status after resume:", plan["status"])

    print("destination:", plan["destination"])

    print("\n=== Booking flight ===")
    passenger = {
        "title": "mr",
        "gender": "m",
        "given_name": "Test",
        "family_name": "Traveler",
        "born_on": "1990-01-01",
        "email": "test@example.com",
        "phone_number": "+919876543210",
    }
    resp = httpx.post(f"{BASE_URL}/{run_id}/book/flight", json=passenger, timeout=60)
    print("status code:", resp.status_code)
    print(resp.json())

    print("\n=== Booking hotel ===")
    guest = {"first_name": "Test", "last_name": "Traveler", "email": "test@example.com"}
    resp = httpx.post(f"{BASE_URL}/{run_id}/book/hotel", json=guest, timeout=60)
    print("status code:", resp.status_code)
    print(resp.json())


if __name__ == "__main__":
    main()
