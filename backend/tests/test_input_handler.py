"""
Tests for input_handler / UserInput validation.
Covers every rule from Agent_Architecture_Spec.docx §3.1.
"""
import pytest
from pydantic import ValidationError

from app.agents.input_handler import handle_input


def test_valid_input_passes():
    result = handle_input({
        "destination": "tokyo",
        "budget_total": 140000,
        "duration_days": 7,
        "priorities_raw": "I care more about food",
        "style": "food_focused",
    })
    assert result.destination == "Tokyo"  # normalized via .title()
    assert result.budget_total == 140000
    assert result.duration_days == 7


def test_destination_is_trimmed_and_titlecased():
    result = handle_input({
        "destination": "  tokyo, japan  ",
        "budget_total": 50000,
        "duration_days": 5,
    })
    assert result.destination == "Tokyo, Japan"


def test_surprise_me_allows_no_destination():
    result = handle_input({
        "surprise_me": True,
        "budget_total": 50000,
        "duration_days": 5,
    })
    assert result.destination is None
    assert result.surprise_me is True


def test_missing_destination_and_no_surprise_me_rejected():
    with pytest.raises(ValidationError, match="Choose a destination or turn on Surprise me"):
        handle_input({
            "budget_total": 50000,
            "duration_days": 5,
        })


def test_zero_budget_rejected():
    with pytest.raises(ValidationError, match="Budget must be greater than 0"):
        handle_input({
            "destination": "Tokyo",
            "budget_total": 0,
            "duration_days": 5,
        })


def test_negative_budget_rejected():
    with pytest.raises(ValidationError, match="Budget must be greater than 0"):
        handle_input({
            "destination": "Tokyo",
            "budget_total": -100,
            "duration_days": 5,
        })


def test_duration_zero_rejected():
    with pytest.raises(ValidationError, match="at least 1 day"):
        handle_input({
            "destination": "Tokyo",
            "budget_total": 50000,
            "duration_days": 0,
        })


def test_duration_over_30_rejected():
    with pytest.raises(ValidationError, match="longer than 30 days"):
        handle_input({
            "destination": "Tokyo",
            "budget_total": 50000,
            "duration_days": 31,
        })


def test_duration_boundary_30_allowed_31_rejected():
    ok = handle_input({"destination": "Tokyo", "budget_total": 50000, "duration_days": 30})
    assert ok.duration_days == 30
    with pytest.raises(ValidationError):
        handle_input({"destination": "Tokyo", "budget_total": 50000, "duration_days": 31})


def test_invalid_style_rejected():
    with pytest.raises(ValidationError, match="Style must be one of"):
        handle_input({
            "destination": "Tokyo",
            "budget_total": 50000,
            "duration_days": 5,
            "style": "luxury_yacht",  # not in VALID_STYLES
        })


def test_valid_style_accepted():
    result = handle_input({
        "destination": "Tokyo",
        "budget_total": 50000,
        "duration_days": 5,
        "style": "hidden_gems",
    })
    assert result.style == "hidden_gems"


def test_error_shape_matches_frontend_expectations():
    """
    Confirms the ValidationError's structure is what the frontend's
    field-level red-error mapping relies on: e['loc'][-1] = field name,
    e['msg'] = display message.
    """
    with pytest.raises(ValidationError) as exc_info:
        handle_input({
            "destination": "Tokyo",
            "budget_total": -5,
            "duration_days": 5,
        })
    errors = exc_info.value.errors()
    assert errors[0]["loc"][-1] == "budget_total"
    assert "greater than 0" in errors[0]["msg"]