"""
Booking Agent — PRD Phase 3: "Booking flow + failure injection"

Sandbox-only (PRD §2.2 non-goal: no real payment processing). A
deliberate, separate action from the main graph: a user plans a trip
first (budget -> search -> ranking -> itinerary), looks at the result,
and only THEN decides to book something -- booking isn't a pipeline
step, it's a user-triggered action on an already-completed plan. So this
reads a completed run's stored state (via orchestrator's checkpointer)
rather than being wired in as a graph node.

Two providers, two real booking flows, both live-verified before writing
this (see conversation history):

  Flights (Duffel): one call, POST /air/orders. The flow forks on the
  offer's own payment_requirements.requires_instant_payment (already
  present in Candidate.metadata["raw"] from search_agent -- no extra
  lookup needed):
    - False -> type="hold" order, no payment yet (airline reserves a
      seat, payment due by payment_required_by)
    - True  -> type="instant" order with a "balance" payment (Duffel's
      test-mode virtual balance -- no real card involved)

  Hotels (LiteAPI): two calls, POST /rates/prebook then POST /rates/book.
  Sandbox uses ACC_CREDIT_CARD as the payment method, which LiteAPI
  simulates in test mode without charging anything (per their docs).

Failure handling is NOT faked for a demo -- both functions surface
whatever real error the provider returns (a validation error, Duffel's
"Unexpected Airline Error" on genuinely booking-failure-prone routes,
etc.) as a clean BookingResult(success=False, ...) rather than crashing.
That IS the "failure injection" story: real provider failures, handled
gracefully, not a scripted fake one.
"""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

import httpx
from pydantic import BaseModel, EmailStr, Field

from app.agents.search_agent import _duffel_post, _liteapi_post
from app.schemas.trip_state import Candidate

FLIGHT_PROVIDER = "duffel"
HOTEL_PROVIDER = "liteapi"


class PassengerDetails(BaseModel):
    """What Duffel needs to create an order for one adult passenger."""

    title: Literal["mr", "mrs", "ms", "miss", "dr"]
    gender: Literal["m", "f"]
    given_name: str = Field(min_length=1, max_length=100)
    family_name: str = Field(min_length=1, max_length=100)
    born_on: date
    email: EmailStr
    phone_number: str = Field(min_length=1, max_length=30)  # E.164, e.g. "+919876543210"


class GuestDetails(BaseModel):
    """What LiteAPI needs for the booking holder/guest."""

    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr


class BookingResult(BaseModel):
    success: bool
    provider: str
    confirmation_code: Optional[str] = None  # Duffel booking_reference / LiteAPI hotelConfirmationCode
    booking_id: Optional[str] = None  # Duffel order id / LiteAPI bookingId
    error_message: Optional[str] = None


async def book_flight(flight: Candidate, passenger: PassengerDetails) -> BookingResult:
    raw_offer = flight.metadata.get("raw")
    if not isinstance(raw_offer, dict) or "id" not in raw_offer:
        return BookingResult(
            success=False, provider=FLIGHT_PROVIDER, error_message="No bookable flight offer found."
        )

    offer_id = raw_offer["id"]
    passenger_slots = raw_offer.get("passengers") or []
    if not passenger_slots:
        return BookingResult(
            success=False,
            provider=FLIGHT_PROVIDER,
            error_message="This flight offer has no passenger slots to book.",
        )
    passenger_id = passenger_slots[0]["id"]

    requires_instant_payment = (
        raw_offer.get("payment_requirements", {}).get("requires_instant_payment", True)
    )

    passenger_payload = {
        "id": passenger_id,
        "title": passenger.title,
        "gender": passenger.gender,
        "given_name": passenger.given_name,
        "family_name": passenger.family_name,
        "born_on": passenger.born_on.isoformat(),
        "email": passenger.email,
        "phone_number": passenger.phone_number,
    }

    if requires_instant_payment:
        order_body = {
            "data": {
                "type": "instant",
                "selected_offers": [offer_id],
                "payments": [
                    {
                        "type": "balance",
                        "amount": raw_offer["total_amount"],
                        "currency": raw_offer["total_currency"],
                    }
                ],
                "passengers": [passenger_payload],
            }
        }
    else:
        order_body = {
            "data": {
                "type": "hold",
                "selected_offers": [offer_id],
                "passengers": [passenger_payload],
            }
        }

    try:
        response = await _duffel_post("/air/orders", order_body)
    except httpx.RequestError as exc:
        return BookingResult(
            success=False, provider=FLIGHT_PROVIDER, error_message=f"Network error contacting Duffel: {exc}"
        )

    if response.status_code >= 400:
        message = _extract_duffel_error(response)
        return BookingResult(success=False, provider=FLIGHT_PROVIDER, error_message=message)

    try:
        data = response.json()["data"]
    except (ValueError, KeyError):
        return BookingResult(
            success=False, provider=FLIGHT_PROVIDER, error_message="Duffel returned an unreadable response."
        )

    return BookingResult(
        success=True,
        provider=FLIGHT_PROVIDER,
        confirmation_code=data.get("booking_reference"),
        booking_id=data.get("id"),
    )


def _extract_duffel_error(response: httpx.Response) -> str:
    try:
        errors = response.json().get("errors", [])
    except ValueError:
        return f"Duffel error (status {response.status_code})."
    if errors:
        return errors[0].get("message", f"Duffel error (status {response.status_code}).")
    return f"Duffel error (status {response.status_code})."


async def book_hotel(hotel: Candidate, guest: GuestDetails) -> BookingResult:
    raw = hotel.metadata.get("raw")
    if not isinstance(raw, dict):
        return BookingResult(
            success=False, provider=HOTEL_PROVIDER, error_message="No bookable hotel rate found."
        )

    rate_entry = raw.get("rate_entry")
    offer_id = None
    if isinstance(rate_entry, dict):
        room_types = rate_entry.get("roomTypes") or []
        if room_types:
            offer_id = room_types[0].get("offerId")

    if not offer_id:
        return BookingResult(
            success=False, provider=HOTEL_PROVIDER, error_message="No bookable hotel rate found."
        )

    try:
        prebook_response = await _liteapi_post(
            "/rates/prebook", {"offerId": offer_id, "usePaymentSdk": False}
        )
    except httpx.RequestError as exc:
        return BookingResult(
            success=False, provider=HOTEL_PROVIDER, error_message=f"Network error contacting LiteAPI: {exc}"
        )

    if prebook_response.status_code >= 400:
        return BookingResult(
            success=False, provider=HOTEL_PROVIDER, error_message=_extract_liteapi_error(prebook_response)
        )

    try:
        prebook_id = prebook_response.json()["data"]["prebookId"]
    except (ValueError, KeyError):
        return BookingResult(
            success=False, provider=HOTEL_PROVIDER, error_message="LiteAPI prebook returned an unreadable response."
        )

    book_body = {
        "prebookId": prebook_id,
        "holder": {"firstName": guest.first_name, "lastName": guest.last_name, "email": guest.email},
        "guests": [
            {
                "occupancyNumber": 1,
                "remarks": "",
                "firstName": guest.first_name,
                "lastName": guest.last_name,
                "email": guest.email,
            }
        ],
        "payment": {"method": "ACC_CREDIT_CARD"},
    }

    try:
        book_response = await _liteapi_post("/rates/book", book_body)
    except httpx.RequestError as exc:
        return BookingResult(
            success=False, provider=HOTEL_PROVIDER, error_message=f"Network error contacting LiteAPI: {exc}"
        )

    if book_response.status_code >= 400:
        return BookingResult(
            success=False, provider=HOTEL_PROVIDER, error_message=_extract_liteapi_error(book_response)
        )

    try:
        data = book_response.json()["data"]
    except (ValueError, KeyError):
        return BookingResult(
            success=False, provider=HOTEL_PROVIDER, error_message="LiteAPI book returned an unreadable response."
        )

    return BookingResult(
        success=(data.get("status") == "CONFIRMED"),
        provider=HOTEL_PROVIDER,
        confirmation_code=data.get("hotelConfirmationCode"),
        booking_id=data.get("bookingId"),
        error_message=None if data.get("status") == "CONFIRMED" else f"Booking status: {data.get('status')}",
    )


def _extract_liteapi_error(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"LiteAPI error (status {response.status_code})."
    return body.get("error") or body.get("message") or f"LiteAPI error (status {response.status_code})."
