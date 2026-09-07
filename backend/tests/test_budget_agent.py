"""
Tests for budget_agent.parse_priority_weights and allocate_budget.

The Groq LLM call is mocked throughout for parse_priority_weights tests.
allocate_budget is pure arithmetic — no mocking needed, fully verified here.
"""
import pytest
from unittest.mock import MagicMock, patch

from app.agents.budget_agent import (
    parse_priority_weights,
    allocate_budget,
    PriorityWeights,
    DEFAULT_WEIGHTS,
    MIN_CATEGORY_FLOOR,
)


def test_empty_string_returns_default_weights_no_llm_call():
    with patch("app.agents.budget_agent._get_structured_llm") as mock_get_llm:
        result = parse_priority_weights("")
        assert result == DEFAULT_WEIGHTS
        mock_get_llm.assert_not_called()


def test_whitespace_only_returns_default_weights_no_llm_call():
    with patch("app.agents.budget_agent._get_structured_llm") as mock_get_llm:
        result = parse_priority_weights("   ")
        assert result == DEFAULT_WEIGHTS
        mock_get_llm.assert_not_called()


def test_real_text_calls_llm_and_returns_its_weights():
    fake_response = PriorityWeights(flights=0.15, hotels=0.20, food=0.50, activities=0.15)
    mock_structured_llm = MagicMock()
    mock_structured_llm.invoke.return_value = fake_response

    with patch("app.agents.budget_agent._get_structured_llm", return_value=mock_structured_llm):
        result = parse_priority_weights("I care a lot about food")

    assert result == {"flights": 0.15, "hotels": 0.20, "food": 0.50, "activities": 0.15}
    mock_structured_llm.invoke.assert_called_once()
    sent_prompt = mock_structured_llm.invoke.call_args[0][0]
    assert "I care a lot about food" in sent_prompt


def test_weights_must_sum_to_one():
    with pytest.raises(ValueError, match="must sum to ~1.0"):
        PriorityWeights(flights=0.5, hotels=0.5, food=0.5, activities=0.5)


def test_weights_within_float_tolerance_accepted():
    weights = PriorityWeights(flights=0.25, hotels=0.25, food=0.25, activities=0.23)
    assert weights.food == 0.25


def test_allocate_budget_sums_to_total():
    weights = {"flights": 0.4, "hotels": 0.3, "food": 0.2, "activities": 0.1}
    result = allocate_budget(100000, weights)
    assert sum(result.values()) == pytest.approx(100000)


def test_allocate_budget_equal_weights_gives_equal_amounts():
    result = allocate_budget(100000, DEFAULT_WEIGHTS)
    for category, amount in result.items():
        assert amount == pytest.approx(25000)


def test_allocate_budget_zero_weight_still_gets_floor():
    weights = {"flights": 0.5, "hotels": 0.5, "food": 0.0, "activities": 0.0}
    result = allocate_budget(100000, weights)
    expected_floor = 100000 * MIN_CATEGORY_FLOOR
    assert result["food"] == pytest.approx(expected_floor)
    assert result["activities"] == pytest.approx(expected_floor)
    assert sum(result.values()) == pytest.approx(100000)


def test_allocate_budget_heavily_weighted_category_respects_ceiling():
    weights = {"flights": 0.1, "hotels": 0.1, "food": 0.7, "activities": 0.1}
    result = allocate_budget(100000, weights)
    assert result["food"] > result["flights"]
    assert result["food"] > 40000
    assert result["food"] <= 50000  # never exceeds the 50% ceiling
    assert sum(result.values()) == pytest.approx(100000)


def test_allocate_budget_extreme_single_category_hits_ceiling_not_100_percent():
    """
    The case that motivated adding a ceiling at all: if the LLM (or a
    contrived input) puts ALL weight on one category, that category
    should NOT get the entire budget — it should cap at 50%, and the
    other three categories split the rest.
    """
    weights = {"flights": 1.0, "hotels": 0.0, "food": 0.0, "activities": 0.0}
    result = allocate_budget(100000, weights)
    assert result["flights"] == pytest.approx(50000)
    for category in ("hotels", "food", "activities"):
        assert result[category] >= 15000 - 0.01
    assert sum(result.values()) == pytest.approx(100000)


def test_allocate_budget_two_categories_both_hit_ceiling():
    weights = {"flights": 0.45, "hotels": 0.45, "food": 0.05, "activities": 0.05}
    result = allocate_budget(100000, weights)
    assert result["flights"] <= 50000
    assert result["hotels"] <= 50000
    assert sum(result.values()) == pytest.approx(100000)


def test_allocate_budget_never_loses_money_to_zero_weight_pool():
    """
    Regression test: when a category gets capped at the ceiling and the
    REMAINING free categories all have weight 0, the leftover pool must
    still be split across them evenly — not silently dropped from the total.
    """
    weights = {"flights": 1.0, "hotels": 0.0, "food": 0.0, "activities": 0.0}
    result = allocate_budget(100000, weights)
    assert sum(result.values()) == pytest.approx(100000)