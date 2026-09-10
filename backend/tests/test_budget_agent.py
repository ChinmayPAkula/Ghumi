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
    fake_response = PriorityWeights(
        flights=0.15, hotels=0.20, food=0.40, activities=0.15, transport=0.10
    )
    mock_structured_llm = MagicMock()
    mock_structured_llm.invoke.return_value = fake_response

    with patch("app.agents.budget_agent._get_structured_llm", return_value=mock_structured_llm):
        result = parse_priority_weights("I care a lot about food")

    assert result == {
        "flights": 0.15,
        "hotels": 0.20,
        "food": 0.40,
        "activities": 0.15,
        "transport": 0.10,
    }
    mock_structured_llm.invoke.assert_called_once()
    sent_prompt = mock_structured_llm.invoke.call_args[0][0]
    assert "I care a lot about food" in sent_prompt


def test_llm_invalid_weights_retries_then_falls_back_to_default():
    """
    Regression test: live-verified against the real Groq API that five
    weights summing to exactly 1.0 is a harder ask than four was -- the
    model sometimes returns e.g. a 1.12 sum, which raises a
    pydantic.ValidationError inside PriorityWeights' own validator (via
    with_structured_output). parse_priority_weights must retry once, then
    fall back to equal weights rather than letting that crash the caller.
    """
    from pydantic import ValidationError

    mock_structured_llm = MagicMock()
    mock_structured_llm.invoke.side_effect = ValidationError.from_exception_data(
        "PriorityWeights", []
    )

    with patch("app.agents.budget_agent._get_structured_llm", return_value=mock_structured_llm):
        result = parse_priority_weights("some real text")

    assert result == DEFAULT_WEIGHTS
    assert mock_structured_llm.invoke.call_count == 2  # one retry, then fallback


def test_llm_succeeds_on_retry_after_one_failure():
    from pydantic import ValidationError

    good_response = PriorityWeights(
        flights=0.2, hotels=0.2, food=0.2, activities=0.2, transport=0.2
    )
    mock_structured_llm = MagicMock()
    mock_structured_llm.invoke.side_effect = [
        ValidationError.from_exception_data("PriorityWeights", []),
        good_response,
    ]

    with patch("app.agents.budget_agent._get_structured_llm", return_value=mock_structured_llm):
        result = parse_priority_weights("some real text")

    assert result == DEFAULT_WEIGHTS  # equal weights, but came from the LLM this time
    assert mock_structured_llm.invoke.call_count == 2


def test_weights_must_sum_to_one():
    with pytest.raises(ValueError, match="must sum to ~1.0"):
        PriorityWeights(flights=0.5, hotels=0.5, food=0.5, activities=0.5, transport=0.5)


def test_weights_within_float_tolerance_accepted():
    weights = PriorityWeights(flights=0.25, hotels=0.25, food=0.25, activities=0.23, transport=0.02)
    assert weights.food == 0.25


def test_allocate_budget_sums_to_total():
    weights = {"flights": 0.4, "hotels": 0.3, "food": 0.2, "activities": 0.1}
    result = allocate_budget(100000, weights)
    assert sum(result.values()) == pytest.approx(100000)


def test_allocate_budget_equal_weights_gives_equal_amounts():
    result = allocate_budget(100000, DEFAULT_WEIGHTS)
    for category, amount in result.items():
        assert amount == pytest.approx(20000)  # 100000 / 5 categories


def test_allocate_budget_zero_weight_still_gets_floor():
    weights = {"flights": 0.5, "hotels": 0.5, "food": 0.0, "activities": 0.0}
    result = allocate_budget(100000, weights)
    expected_floor = 100000 * MIN_CATEGORY_FLOOR
    assert result["food"] == pytest.approx(expected_floor)
    assert result["activities"] == pytest.approx(expected_floor)
    assert sum(result.values()) == pytest.approx(100000)


def test_allocate_budget_heavily_weighted_category_respects_ceiling():
    # transport omitted from weights -> defaults to 0 via .get(c, 0.0), still
    # gets its floor. With 5 categories' floors eating 75% of the budget,
    # food's absolute share is smaller than in the old 4-category math even
    # though its relative dominance (0.7 weight) is unchanged.
    weights = {"flights": 0.1, "hotels": 0.1, "food": 0.7, "activities": 0.1}
    result = allocate_budget(100000, weights)
    assert result["food"] > result["flights"]
    assert result["food"] > 25000
    assert result["food"] <= 50000  # never exceeds the 50% ceiling
    assert sum(result.values()) == pytest.approx(100000)


def test_allocate_budget_extreme_single_category_hits_ceiling_not_100_percent():
    """
    The case that motivated adding a ceiling at all: if the LLM (or a
    contrived input) puts ALL weight on one category, that category
    should NOT get the entire budget — it should cap well under 100%
    (40% here, since floors across 5 categories eat more of the pool
    than the old 4-category math did), and the other categories split
    the rest at their floor.
    """
    weights = {"flights": 1.0, "hotels": 0.0, "food": 0.0, "activities": 0.0}
    result = allocate_budget(100000, weights)
    assert result["flights"] == pytest.approx(40000)
    for category in ("hotels", "food", "activities", "transport"):
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