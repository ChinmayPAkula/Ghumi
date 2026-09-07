"""
Trip API routes — Phase 1: just the input-handling endpoint.
Per Ghumi_Agent_Architecture_Spec.docx §3.1 / §6.

More routes (start planning run, get status, submit clarification answer)
get added here as later agents/nodes come online — this file grows with
the graph, not ahead of it.
"""
from fastapi import APIRouter

from app.schemas.trip_state import UserInput

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