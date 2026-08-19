/**
 * Base URL for the FastAPI backend.
 * In dev, Vite proxies /api/* to localhost:8000 (see vite.config.ts),
 * so this stays "/api" unless VITE_API_BASE_URL overrides it (prod).
 */
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api'

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
