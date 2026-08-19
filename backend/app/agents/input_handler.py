"""
Input Handler — Ghumi_Agent_Architecture_Spec.docx §3.1

Purpose: validates and normalizes raw user input into UserInput.
Pure code, no LLM. Since Ghumi is GUI-first (form gives clean structured
fields, not free text to parse), validation lives as Pydantic
field_validators directly on UserInput (see schemas/trip_state.py) rather
than as separate validate_destination()/validate_budget()/validate_duration()
functions — Pydantic already IS that layer for structured input.

This module is the thin entry point: raw dict in, UserInput out, or the
ValidationError propagates up to FastAPI's request handling, which turns
it into a 422 the frontend can map onto form fields.
"""
from app.schemas.trip_state import UserInput


def handle_input(raw: dict) -> UserInput:
    """
    Raw form payload -> validated UserInput.

    Raises pydantic.ValidationError on bad input — let it propagate.
    FastAPI's route handler converts it into a 422 response automatically
    when UserInput is used as a request body type; if calling this
    directly (e.g. from a script or another agent), catch ValidationError
    yourself.
    """
    return UserInput(**raw)