/**
 * Base URL for the FastAPI backend.
 * In dev, Vite proxies /api/* to localhost:8000 (see vite.config.ts),
 * so this stays "/api" unless VITE_API_BASE_URL overrides it (prod).
 */
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${await res.text()}`)
  }
  return res.json()
}

/** One entry from FastAPI/Pydantic's 422 error body. */
export interface FieldError {
  loc: (string | number)[]
  msg: string
}

/** Thrown by postTripInput on a 422 — carries the field-level errors, not just a generic message. */
export class ValidationApiError extends Error {
  fieldErrors: FieldError[]
  constructor(fieldErrors: FieldError[]) {
    super('Validation failed')
    this.fieldErrors = fieldErrors
  }
}

/**
 * Shared by every endpoint that takes UserInput as its body (validate-input,
 * plan) — preserves the structured 422 body (field name + message per
 * failing field) instead of collapsing it into a plain string, since the
 * form needs to show a red error under the specific field.
 */
async function postJson<T>(path: string, payload: unknown): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

  if (res.status === 422) {
    const body = await res.json().catch(() => null)
    const detail = Array.isArray(body?.detail) ? (body.detail as FieldError[]) : []
    throw new ValidationApiError(detail)
  }
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${await res.text()}`)
  }
  return res.json()
}

/** POST /trip/validate-input */
export async function postTripInput<T>(payload: unknown): Promise<T> {
  return postJson<T>('/trip/validate-input', payload)
}

/** Matches backend Candidate/ScoredCandidate (app/schemas/trip_state.py). */
export interface ScoredCandidate {
  id: string
  category: string
  name: string
  price: number
  rating: number | null
  review_count: number | null
  score: number
  reasoning: string | null
}

/** Matches backend DayPlan. */
export interface DayPlan {
  day_number: number
  summary: string
  items: ScoredCandidate[]
}

/** Matches backend Conflict. */
export interface Conflict {
  description: string
  affected_days: number[]
  category: string | null
  shortfall_amount: number | null
  resolution_options: string[]
}

/** Matches backend ClarificationInfo (app/api/trip.py). */
export interface ClarificationInfo {
  stage: string
  clarification_needed: string | null
  conflicts: Conflict[]
}

/** Matches backend PlanResult (app/api/trip.py). */
export interface PlanResult {
  run_id: string
  status: 'completed' | 'needs_clarification'
  // The resolved destination -- for a "surprise me" trip this is the
  // LLM-suggested city, not whatever (empty) value the form had. Always
  // prefer this over local form state when displaying the trip.
  destination: string | null
  itinerary: DayPlan[]
  budget_allocation: Record<string, number>
  conflicts: Conflict[]
  clarification: ClarificationInfo | null
}

/** POST /trip/plan — runs the full agent pipeline for one trip. */
export async function postTripPlan(payload: unknown): Promise<PlanResult> {
  return postJson<PlanResult>('/trip/plan', payload)
}

/**
 * POST /trip/plan/{run_id}/resume — continues a paused run past a
 * clarification checkpoint. `choice` is one of the Conflict's
 * resolution_options (or free text — the backend currently just
 * acknowledges and continues, see orchestrator.py).
 */
export async function resumeTripPlan(runId: string, choice: string): Promise<PlanResult> {
  const res = await fetch(`${API_BASE_URL}/trip/plan/${encodeURIComponent(runId)}/resume`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ choice }),
  })
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${await res.text()}`)
  }
  return res.json()
}