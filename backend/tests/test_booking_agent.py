"""
Tests for booking_agent.

Mocked at the _duffel_post/_liteapi_post boundary (same pattern as
test_search_agent.py) -- no real network access. Live-verified separately
against real Duffel/LiteAPI sandbox APIs before this was written (see
conversation history): a real Duffel hold order, a real Duffel instant
order with balance payment, and a real LiteAPI prebook+book flow all
confirmed working with the exact field names/shapes used here.
"""
from datetime import date
from unittest.mock import patch

import httpx
import pytest

from app.agents.booking_agent import (
    GuestDetails,
    PassengerDetails,
    book_flight,
    book_hotel,
)
from app.schemas.trip_state import Candidate

FLIGHTS = "flights"
HOTELS = "hotels"


def _mock_response(status_code, json_body):
    return httpx.Response(status_code, json=json_body, request=httpx.Request("POST", "http://test"))


def _passenger(**overrides):
    payload = dict(
        title="mr",
        gender="m",
        given_name="Test",
        family_name="Traveler",
        born_on=date(1990, 1, 1),
        email="test@example.com",
        phone_number="+919876543210",
    )
    payload.update(overrides)
    return PassengerDetails(**payload)


def _guest(**overrides):
    payload = dict(first_name="Test", last_name="Traveler", email="test@example.com")
    payload.update(overrides)
    return GuestDetails(**payload)


# --- book_flight ---


@pytest.mark.asyncio
async def test_book_flight_hold_order_success():
    flight = Candidate(
        id="off_1",
        category=FLIGHTS,
        name="BLR -> HND",
        price=253.16,
        metadata={
            "raw": {
                "id": "off_1",
                "total_amount": "253.16",
                "total_currency": "USD",
                "passengers": [{"id": "pas_1"}],
                "payment_requirements": {"requires_instant_payment": False},
            }
        },
    )
    mock_response = _mock_response(
        201, {"data": {"id": "ord_1", "booking_reference": "LYLU4B"}}
    )

    with patch("app.agents.booking_agent._duffel_post", return_value=mock_response) as mock_post:
        result = await book_flight(flight, _passenger())

    assert result.success is True
    assert result.provider == "duffel"
    assert result.confirmation_code == "LYLU4B"
    assert result.booking_id == "ord_1"
    sent_body = mock_post.call_args[0][1]
    assert sent_body["data"]["type"] == "hold"
    assert "payments" not in sent_body["data"]


@pytest.mark.asyncio
async def test_book_flight_instant_payment_order_success():
    flight = Candidate(
        id="off_2",
        category=FLIGHTS,
        name="BLR -> HND",
        price=821.92,
        metadata={
            "raw": {
                "id": "off_2",
                "total_amount": "821.92",
                "total_currency": "USD",
                "passengers": [{"id": "pas_1"}],
                "payment_requirements": {"requires_instant_payment": True},
            }
        },
    )
    mock_response = _mock_response(
        201, {"data": {"id": "ord_2", "booking_reference": "5CFKJH"}}
    )

    with patch("app.agents.booking_agent._duffel_post", return_value=mock_response) as mock_post:
        result = await book_flight(flight, _passenger())

    assert result.success is True
    assert result.confirmation_code == "5CFKJH"
    sent_body = mock_post.call_args[0][1]
    assert sent_body["data"]["type"] == "instant"
    assert sent_body["data"]["payments"][0]["type"] == "balance"
    assert sent_body["data"]["payments"][0]["amount"] == "821.92"


@pytest.mark.asyncio
async def test_book_flight_duffel_error_surfaced_not_raised():
    flight = Candidate(
        id="off_3",
        category=FLIGHTS,
        name="LHR -> LGW",
        price=31.40,
        metadata={
            "raw": {
                "id": "off_3",
                "total_amount": "31.40",
                "total_currency": "USD",
                "passengers": [{"id": "pas_1"}],
                "payment_requirements": {"requires_instant_payment": False},
            }
        },
    )
    mock_response = _mock_response(
        502,
        {
            "errors": [
                {"title": "Unexpected Airline Error", "message": "The airline returned an unrecognised error."}
            ]
        },
    )

    with patch("app.agents.booking_agent._duffel_post", return_value=mock_response):
        result = await book_flight(flight, _passenger())

    assert result.success is False
    assert result.provider == "duffel"
    assert "unrecognised error" in result.error_message


@pytest.mark.asyncio
async def test_book_flight_network_error_surfaced_not_raised():
    flight = Candidate(
        id="off_4",
        category=FLIGHTS,
        name="BLR -> HND",
        price=100.0,
        metadata={
            "raw": {
                "id": "off_4",
                "total_amount": "100.0",
                "total_currency": "USD",
                "passengers": [{"id": "pas_1"}],
                "payment_requirements": {"requires_instant_payment": False},
            }
        },
    )

    with patch("app.agents.booking_agent._duffel_post", side_effect=httpx.ConnectError("boom")):
        result = await book_flight(flight, _passenger())

    assert result.success is False
    assert "Network error" in result.error_message


@pytest.mark.asyncio
async def test_book_flight_missing_raw_offer_fails_cleanly():
    flight = Candidate(id="off_5", category=FLIGHTS, name="BLR -> HND", price=100.0, metadata={})

    result = await book_flight(flight, _passenger())

    assert result.success is False
    assert "No bookable flight offer" in result.error_message


# --- book_hotel ---


@pytest.mark.asyncio
async def test_book_hotel_full_flow_success():
    hotel = Candidate(
        id="lp1db0a1",
        category=HOTELS,
        name="THE BLOSSOM HIBIYA",
        price=1900.88,
        metadata={"raw": {"rate_entry": {"roomTypes": [{"offerId": "offer_abc"}]}}},
    )
    prebook_response = _mock_response(200, {"data": {"prebookId": "hS4Z681LZ"}})
    book_response = _mock_response(
        200,
        {
            "data": {
                "bookingId": "T7hAwrQS4",
                "status": "CONFIRMED",
                "hotelConfirmationCode": "test",
            }
        },
    )

    with patch(
        "app.agents.booking_agent._liteapi_post", side_effect=[prebook_response, book_response]
    ) as mock_post:
        result = await book_hotel(hotel, _guest())

    assert result.success is True
    assert result.provider == "liteapi"
    assert result.confirmation_code == "test"
    assert result.booking_id == "T7hAwrQS4"
    assert mock_post.call_count == 2
    prebook_call_args = mock_post.call_args_list[0][0]
    assert prebook_call_args[0] == "/rates/prebook"
    assert prebook_call_args[1]["offerId"] == "offer_abc"
    book_call_args = mock_post.call_args_list[1][0]
    assert book_call_args[1]["prebookId"] == "hS4Z681LZ"


@pytest.mark.asyncio
async def test_book_hotel_prebook_failure_stops_before_book_call():
    hotel = Candidate(
        id="lp1db0a1",
        category=HOTELS,
        name="Some Hotel",
        price=1000.0,
        metadata={"raw": {"rate_entry": {"roomTypes": [{"offerId": "offer_abc"}]}}},
    )
    prebook_response = _mock_response(400, {"error": "Rate no longer available"})

    with patch("app.agents.booking_agent._liteapi_post", return_value=prebook_response) as mock_post:
        result = await book_hotel(hotel, _guest())

    assert result.success is False
    assert result.provider == "liteapi"
    assert "Rate no longer available" in result.error_message
    mock_post.assert_called_once()  # never reached the book call


@pytest.mark.asyncio
async def test_book_hotel_book_step_non_confirmed_status_is_failure():
    hotel = Candidate(
        id="lp1db0a1",
        category=HOTELS,
        name="Some Hotel",
        price=1000.0,
        metadata={"raw": {"rate_entry": {"roomTypes": [{"offerId": "offer_abc"}]}}},
    )
    prebook_response = _mock_response(200, {"data": {"prebookId": "pb_1"}})
    book_response = _mock_response(200, {"data": {"bookingId": "bk_1", "status": "FAILED"}})

    with patch(
        "app.agents.booking_agent._liteapi_post", side_effect=[prebook_response, book_response]
    ):
        result = await book_hotel(hotel, _guest())

    assert result.success is False
    assert "FAILED" in result.error_message


@pytest.mark.asyncio
async def test_book_hotel_missing_offer_id_fails_cleanly():
    hotel = Candidate(id="lp1db0a1", category=HOTELS, name="Some Hotel", price=1000.0, metadata={})

    result = await book_hotel(hotel, _guest())

    assert result.success is False
    assert "No bookable hotel rate" in result.error_message


@pytest.mark.asyncio
async def test_book_hotel_network_error_surfaced_not_raised():
    hotel = Candidate(
        id="lp1db0a1",
        category=HOTELS,
        name="Some Hotel",
        price=1000.0,
        metadata={"raw": {"rate_entry": {"roomTypes": [{"offerId": "offer_abc"}]}}},
    )

    with patch("app.agents.booking_agent._liteapi_post", side_effect=httpx.ConnectError("boom")):
        result = await book_hotel(hotel, _guest())

    assert result.success is False
    assert "Network error" in result.error_message
