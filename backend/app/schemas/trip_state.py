"""
TripState — the single shared state object threaded through every LangGraph
node, per Ghumi_Agent_Architecture_Spec.docx §1.

Only Phase 1 fields are active below. Phase 2/3 fields are listed but
commented out — uncomment as each phase is actually built, so the schema
never claims to support something the graph doesn't do yet.

Agents read the fields they need and write back only their own fields
(per PRD §6.2's LLM-vs-code split) — this is what keeps the pipeline
auditable.
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class UserInput(BaseModel):
    """Written by: input_handler (Phase 1)."""

    destination: Optional[str] = None       # None + surprise_me=True if unset
    surprise_me: bool = False
    budget_total: float
    currency: str = "INR"
    duration_days: int
    priorities_raw: str = ""                # free text, e.g. "I care more about food"
    style: Optional[str] = None              # hidden_gems / popular / relaxed / adventurous / cultural / food_focused


class Candidate(BaseModel):
    """A single search result item (flight, hotel, activity, or food option)."""

    id: str
    category: str  # flight | hotel | activity | food
    name: str
    price: float
    rating: Optional[float] = None
    review_count: Optional[int] = None
    metadata: dict = Field(default_factory=dict)


class ScoredCandidate(Candidate):
    score: float
    reasoning: Optional[str] = None  # written by rerank_shortlist() (LLM)


class SearchError(BaseModel):
    category: str
    reason: str  # "empty_results" | "rate_limited" | "malformed_response"


class Conflict(BaseModel):
    description: str
    affected_days: list[int] = Field(default_factory=list)


class DayPlan(BaseModel):
    day_number: int
    summary: str = ""  # LLM-written narrative
    items: list[ScoredCandidate] = Field(default_factory=list)


class TripState(BaseModel):
    """The graph's shared state. One instance per run."""

    # --- Orchestrator-owned ---
    run_id: str
    clarification_needed: Optional[str] = None

    # --- Phase 1 ---
    user_input: Optional[UserInput] = None                          # input_handler
    priority_weights: dict[str, float] = Field(default_factory=dict)  # budget_agent (LLM)
    budget_allocation: dict[str, float] = Field(default_factory=dict)  # budget_agent (code)
    search_results: dict[str, list[Candidate]] = Field(default_factory=dict)  # search_agent
    search_errors: list[SearchError] = Field(default_factory=list)     # search_agent
    ranked_shortlist: dict[str, list[ScoredCandidate]] = Field(default_factory=dict)  # ranking_agent
    itinerary: list[DayPlan] = Field(default_factory=list)             # itinerary_agent
    conflicts: list[Conflict] = Field(default_factory=list)            # orchestrator / itinerary_agent

    # --- Phase 2 (uncomment when built) ---
    # pacing_profile: Optional[str] = None                     # itinerary_agent
    # price_comparisons: dict[str, list[dict]] = Field(default_factory=dict)  # search_agent
    # seasonal_flags: list[str] = Field(default_factory=list)  # rules module
    # overpricing_flags: list[str] = Field(default_factory=list)  # ranking_agent
    # replan_history: list[dict] = Field(default_factory=list)  # orchestrator

    # --- Phase 3 (uncomment when built) ---
    # booking_attempts: list[dict] = Field(default_factory=list)
    # group_members: list[dict] = Field(default_factory=list)
    # merged_preferences: Optional[dict] = None
    # explanations: dict[str, str] = Field(default_factory=dict)

    # --- Observability (auto-logged, Phase 1) ---
    trace_id: Optional[str] = None
    token_usage: dict[str, int] = Field(default_factory=dict)
    latency_ms: dict[str, float] = Field(default_factory=dict)
