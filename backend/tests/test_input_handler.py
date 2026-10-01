"""
Tests for input_handler / UserInput validation.
Covers every rule from Agent_Architecture_Spec.docx §3.1.
"""
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.agents.input_handler import handle_input

FUTURE_DATE = (date.today() + timedelta(days=30)).isoformat()


def _base(**overrides):
    """Minimal valid payload (origin/start_date always present) with overrides applied."""
    payload = {
        "destination": "Tokyo",
        "origin": "Bangalore",
        "start_date": FUTURE_DATE,
        "budget_total": 50000,
        "duration_days": 5,
    }
    payload.update(overrides)
    return payload


def test_valid_input_passes():
    result = handle_input(
        _base(
            destination="tokyo",
            budget_total=140000,
            duration_days=7,
            priorities_raw="I care more about food",
            style="food_focused",
        )
    )
    assert result.destination == "Tokyo"  # normalized via .title()
    assert result.budget_total == 140000
    assert result.duration_days == 7


def test_destination_is_trimmed_and_titlecased():
    result = handle_input(_base(destination="  tokyo, japan  "))
    assert result.destination == "Tokyo, Japan"


def test_origin_is_trimmed_and_titlecased():
    result = handle_input(_base(origin="  bangalore  "))
    assert result.origin == "Bangalore"


def test_missing_origin_rejected():
    payload = _base()
    del payload["origin"]
    with pytest.raises(ValidationError):
        handle_input(payload)


def test_missing_start_date_rejected():
    payload = _base()
    del payload["start_date"]
    with pytest.raises(ValidationError):
        handle_input(payload)


def test_start_date_in_past_rejected():
    past_date = (date.today() - timedelta(days=1)).isoformat()
    with pytest.raises(ValidationError, match="can't be in the past"):
        handle_input(_base(start_date=past_date))


def test_return_date_computed_from_start_date_and_duration():
    start = date.today() + timedelta(days=10)
    result = handle_input(_base(start_date=start.isoformat(), duration_days=7))
    assert result.return_date == start + timedelta(days=7)


def test_surprise_me_allows_no_destination():
    payload = _base()
    del payload["destination"]
    result = handle_input({**payload, "surprise_me": True})
    assert result.destination is None
    assert result.surprise_me is True


def test_missing_destination_and_no_surprise_me_rejected():
    payload = _base()
    del payload["destination"]
    with pytest.raises(ValidationError, match="Choose a destination or turn on Surprise me"):
        handle_input(payload)


def test_zero_budget_rejected():
    with pytest.raises(ValidationError, match="Budget must be greater than 0"):
        handle_input(_base(budget_total=0))


def test_negative_budget_rejected():
    with pytest.raises(ValidationError, match="Budget must be greater than 0"):
        handle_input(_base(budget_total=-100))


def test_duration_zero_rejected():
    with pytest.raises(ValidationError, match="at least 1 day"):
        handle_input(_base(duration_days=0))


def test_duration_over_50_rejected():
    with pytest.raises(ValidationError, match="longer than 50 days"):
        handle_input(_base(duration_days=51))


def test_duration_boundary_50_allowed_51_rejected():
    ok = handle_input(_base(duration_days=50))
    assert ok.duration_days == 50
    with pytest.raises(ValidationError):
        handle_input(_base(duration_days=51))


def test_invalid_style_rejected():
    with pytest.raises(ValidationError, match="Style must be one of"):
        handle_input(_base(style="luxury_yacht"))  # not in VALID_STYLES


def test_hotel_star_preference_within_range_accepted():
    ok = handle_input(_base(hotel_star_preference=4))
    assert ok.hotel_star_preference == 4


def test_hotel_star_preference_out_of_range_rejected():
    with pytest.raises(ValidationError, match="between 1 and 5"):
        handle_input(_base(hotel_star_preference=6))


def test_hotel_star_preference_zero_rejected():
    with pytest.raises(ValidationError, match="between 1 and 5"):
        handle_input(_base(hotel_star_preference=0))


def test_hotel_star_preference_omitted_defaults_to_none():
    ok = handle_input(_base())
    assert ok.hotel_star_preference is None


def test_valid_style_accepted():
    result = handle_input(_base(style="hidden_gems"))
    assert result.style == "hidden_gems"


def test_error_shape_matches_frontend_expectations():
    """
    Confirms the ValidationError's structure is what the frontend's
    field-level red-error mapping relies on: e['loc'][-1] = field name,
    e['msg'] = display message.
    """
    with pytest.raises(ValidationError) as exc_info:
        handle_input(_base(budget_total=-5))
    errors = exc_info.value.errors()
    assert any(e["loc"][-1] == "budget_total" and "greater than 0" in e["msg"] for e in errors)
