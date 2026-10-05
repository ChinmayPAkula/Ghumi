"""
Trip API routes. Per Ghumi_Agent_Architecture_Spec.docx §3.1 / §6.

/validate-input: Phase 1's original field-validation-only endpoint, kept
as-is for the PlanPage's live inline validation.
/plan + /plan/{run_id}/resume: triggers the actual orchestrator.py graph.
Synchronous (awaits the full graph run before responding) — matches
TechStack.docx §3.1's "no task queue for v1" decision.
"""
from typing import Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from langgraph.types import Command
from pydantic import BaseModel

from app.agents.orchestrator import get_compiled_graph
from app.core.rate_limit import limiter
from app.schemas.trip_state import Conflict, DayPlan, TripState, UserInput

router = APIRouter(prefix="/trip", tags=["trip"])


@router.post("/validate-input", response_model=UserInput)
def validate_input(payload: UserInput) -> UserInput:
    """
    Validates raw trip input.

    Using UserInput directly as the request body type means FastAPI runs
    all of Pydantic's field_validators (budget > 0, duration 1-30, etc.)
    automatically, and any failure becomes a 422 with a per-field
    {loc, msg} error list — no need to call input_handler.handle_input()
    by hand here, FastAPI + Pydantic already do exactly that.

    Returns the same, now-normalized UserInput on success (e.g.
    destination gets .title()-cased) so the frontend can show the user
    what was actually understood before moving on.
    """
    return payload


class ClarificationInfo(BaseModel):
    stage: str
    clarification_needed: Optional[str] = None
    conflicts: list[Conflict] = []


class PlanResult(BaseModel):
    run_id: str
    status: Literal["completed", "needs_clarification"]
    destination: Optional[str] = None
    itinerary: list[DayPlan] = []
    budget_allocation: dict[str, float] = {}
    conflicts: list[Conflict] = []
    clarification: Optional[ClarificationInfo] = None


class ResumePayload(BaseModel):
    choice: str  # one of Conflict.resolution_options, or free text acknowledgment


def _resolve_destination(graph_output: dict) -> Optional[str]:
    """
    chosen_destination is only set for "surprise me" runs (search_agent_node
    picks it via an LLM call) -- for a normal run it's always None, so the
    user-typed destination is the real answer. Centralized here so both
    branches of _build_plan_result stay consistent.
    """
    chosen = graph_output.get("chosen_destination")
    if chosen:
        return chosen
    user_input = graph_output.get("user_input")
    return user_input.destination if user_input else None


def _build_plan_result(run_id: str, graph_output: dict) -> PlanResult:
    interrupts = graph_output.get("__interrupt__")
    destination = _resolve_destination(graph_output)
    if interrupts:
        payload = interrupts[0].value
        return PlanResult(
            run_id=run_id,
            status="needs_clarification",
            destination=destination,
            budget_allocation=graph_output.get("budget_allocation", {}),
            conflicts=graph_output.get("conflicts", []),
            clarification=ClarificationInfo(
                stage=payload.get("stage", "unknown"),
                clarification_needed=payload.get("clarification_needed"),
                conflicts=[Conflict(**c) for c in payload.get("conflicts", [])],
            ),
        )
    return PlanResult(
        run_id=run_id,
        status="completed",
        destination=destination,
        itinerary=graph_output.get("itinerary", []),
        budget_allocation=graph_output.get("budget_allocation", {}),
        conflicts=graph_output.get("conflicts", []),
    )


@router.post("/plan", response_model=PlanResult)
@limiter.limit("5/minute")
async def plan_trip(request: Request, payload: UserInput) -> PlanResult:
    """
    Runs the full orchestrator graph (budget -> search -> ranking ->
    itinerary) for one trip. May come back as status="needs_clarification"
    if a budget conflict was found (see orchestrator.py's checkpointed
    interrupts) -- resume via POST /plan/{run_id}/resume with the user's
    chosen resolution_option.

    Rate-limited (5/min per IP, see app/core/rate_limit.py) -- this
    endpoint fans out to Duffel, LiteAPI, Google Places, and Groq per
    call, all against real quota/cost once this is publicly reachable.
    """
    run_id = str(uuid4())
    initial_state = TripState(run_id=run_id, user_input=payload)
    config = {"configurable": {"thread_id": run_id}}

    graph = get_compiled_graph()
    result = await graph.ainvoke(initial_state, config=config)
    return _build_plan_result(run_id, result)


@router.post("/plan/{run_id}/resume", response_model=PlanResult)
@limiter.limit("10/minute")
async def resume_trip(request: Request, run_id: str, payload: ResumePayload) -> PlanResult:
    """
    Resumes a paused run. First-pass scope (see orchestrator.py's module
    docstring): resuming acknowledges the conflict and continues with
    whatever was already selected -- it does not yet renegotiate budget
    or propose alternatives (that's PRD Phase 2's "conflict-aware
    replanning"). A run_id from a completed or unknown run 404s.

    Rate-limited (10/min per IP) -- lighter than /plan (resumes an
    existing graph state rather than starting a full new search), but
    still calls ranking_agent + Groq's narrative generation.
    """
    config = {"configurable": {"thread_id": run_id}}
    graph = get_compiled_graph()

    state = await graph.aget_state(config)
    if state is None or not state.next:
        raise HTTPException(status_code=404, detail="No paused run found for this run_id")

    result = await graph.ainvoke(Command(resume=payload.choice), config=config)
    return _build_plan_result(run_id, result)