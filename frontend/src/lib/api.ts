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
 * POST /trip/validate-input — the one route that exists so far.
 * Unlike apiFetch, this preserves the structured 422 body (field name +
 * message per failing field) instead of collapsing it into a plain string,
 * since the form needs to show a red error under the specific field.
 */
export async function postTripInput<T>(payload: unknown): Promise<T> {
  const res = await fetch(`${API_BASE_URL}/trip/validate-input`, {
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