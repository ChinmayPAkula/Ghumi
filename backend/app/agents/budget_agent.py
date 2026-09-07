"""
Budget Agent — Ghumi_Agent_Architecture_Spec.docx §3.2

This file has two responsibilities per the architecture doc:
  1. parse_priority_weights()  — LLM call (Groq, per TechStack.docx)
  2. allocate_budget()         — pure code, split total budget by weights
"""
from __future__ import annotations

from langchain_groq import ChatGroq
from pydantic import BaseModel, Field, model_validator

from app.core.config import get_settings

CATEGORIES = ("flights", "hotels", "food", "activities")

DEFAULT_WEIGHTS: dict[str, float] = {c: 0.25 for c in CATEGORIES}

PROMPT_TEMPLATE = """You are extracting trip-planning priority weights from a
traveler's own words. Read what they wrote and output a weight from 0 to 1
for each of these four categories: flights, hotels, food, activities.

Rules:
- The four weights must sum to 1.0.
- If they emphasize one category, raise its weight and lower the others
  proportionally — don't just nudge it slightly.
- If something isn't mentioned, keep it near its default share (0.25) rather
  than dropping it to near-zero.

Traveler's own words: "{text}"
"""


class PriorityWeights(BaseModel):
    """
    Structured output contract for the LLM call. Validated the same way
    UserInput is — the LLM's response is untrusted input until this passes.
    """

    flights: float = Field(ge=0.0, le=1.0)
    hotels: float = Field(ge=0.0, le=1.0)
    food: float = Field(ge=0.0, le=1.0)
    activities: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> "PriorityWeights":
        total = self.flights + self.hotels + self.food + self.activities
        if not (0.97 <= total <= 1.03):  # small float-arithmetic tolerance
            raise ValueError(f"Priority weights must sum to ~1.0, got {total}")
        return self


def _get_structured_llm():
    """
    Isolated so tests can monkeypatch this one function instead of mocking
    ChatGroq's internals directly — see test_budget_agent.py.
    """
    settings = get_settings()
    llm = ChatGroq(
        # llama-3.1-8b-instant was deprecated by Groq on 2026-06-17 (free/dev
        # tier). openai/gpt-oss-20b is Groq's official recommended replacement
        # for this size/speed tier — see console.groq.com/docs/deprecations
        model="openai/gpt-oss-20b",
        api_key=settings.groq_api_key,
        temperature=0,  # deterministic-ish; we want consistent weights, not creativity
    )
    return llm.with_structured_output(PriorityWeights)


def parse_priority_weights(priorities_raw: str) -> dict[str, float]:
    """
    Free text -> category weights.

    Empty/blank input skips the LLM entirely and returns equal weights —
    no point spending a call on nothing, and it keeps the function fast
    and free for the common case of "user didn't type anything here."
    """
    if not priorities_raw or not priorities_raw.strip():
        return dict(DEFAULT_WEIGHTS)

    structured_llm = _get_structured_llm()
    result: PriorityWeights = structured_llm.invoke(
        PROMPT_TEMPLATE.format(text=priorities_raw.strip())
    )
    return result.model_dump()


# Every category is guaranteed at least this share of the total budget,
# regardless of how low its weight came out — prevents a category from
# collapsing toward ₹0 just because the LLM (or equal-weight default)
# gave it a small weight.
MIN_CATEGORY_FLOOR = 0.15

# No single category can exceed this share, no matter how strongly the
# user weighted it — e.g. "I only care about food" still needs flights
# and somewhere to sleep. Excess above this gets redistributed to the
# other categories, proportional to their own weights.
MAX_CATEGORY_CEILING = 0.50


def allocate_budget(
    budget_total: float, priority_weights: dict[str, float]
) -> dict[str, float]:
    """
    Total budget + weights -> rupee amount per category, respecting both
    MIN_CATEGORY_FLOOR and MAX_CATEGORY_CEILING.

    Pure code, no LLM — per Agent_Architecture_Spec.docx §3.2.

    Water-filling algorithm: any category whose weight-driven share would
    exceed the ceiling gets capped at the ceiling, and the excess is
    redistributed among the remaining (uncapped) categories proportional
    to their weights. Repeats until no category exceeds its ceiling.

    Guarantees:
      - every category gets >= MIN_CATEGORY_FLOOR share of budget_total
      - no category gets > MAX_CATEGORY_CEILING share of budget_total
      - the amounts sum exactly to budget_total (floating point aside)
    """
    floor_amt = budget_total * MIN_CATEGORY_FLOOR
    ceiling_amt = budget_total * MAX_CATEGORY_CEILING

    capped: dict[str, float] = {}
    free_categories = list(CATEGORIES)
    free_budget = budget_total - floor_amt * len(CATEGORIES)  # pool above everyone's floor

    while True:
        weight_sum = sum(priority_weights.get(c, 0.0) for c in free_categories)
        if weight_sum > 0:
            shares = {
                c: floor_amt + free_budget * (priority_weights.get(c, 0.0) / weight_sum)
                for c in free_categories
            }
        else:
            # all remaining categories have zero weight — split the pool
            # evenly rather than dividing by zero (or silently losing it,
            # which is what a naive "or 1.0" fallback on the divisor does)
            shares = {c: floor_amt + free_budget / len(free_categories) for c in free_categories}

        over_ceiling = [c for c, amt in shares.items() if amt > ceiling_amt]
        if not over_ceiling:
            capped.update(shares)
            break

        for c in over_ceiling:
            capped[c] = ceiling_amt
            free_budget -= ceiling_amt - floor_amt
            free_categories.remove(c)

    return capped