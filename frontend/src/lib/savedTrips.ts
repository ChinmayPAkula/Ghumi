import type { DayPlan, Conflict } from './api'

/**
 * "Save trip" quick win: browser localStorage, not a real backend feature
 * yet. Supabase (the tech stack's intended real DB) isn't configured —
 * no keys, no auth, no schema — so this is a stepping stone: it works
 * today, but only on this browser/device, and isn't the final design
 * (the actual dashboard mockup in the design spec expects a real "Your
 * trips" page backed by a database).
 */
export interface SavedTrip {
  id: string
  destination: string
  savedAt: string // ISO timestamp
  itinerary: DayPlan[]
  budgetAllocation: Record<string, number>
  conflicts: Conflict[]
}

const STORAGE_KEY = 'ghumi_saved_trips'

function readAll(): SavedTrip[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    // Private browsing, cleared storage, corrupted JSON, etc. -- treat as
    // "nothing saved" rather than crashing the page.
    return []
  }
}

function writeAll(trips: SavedTrip[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(trips))
  } catch {
    // Storage full or unavailable -- silently no-op, same reasoning as
    // read: a failed save shouldn't crash the page the user is on.
  }
}

export function listSavedTrips(): SavedTrip[] {
  return readAll().sort((a, b) => b.savedAt.localeCompare(a.savedAt))
}

export function getSavedTrip(id: string): SavedTrip | undefined {
  return readAll().find((t) => t.id === id)
}

export function saveTrip(trip: Omit<SavedTrip, 'id' | 'savedAt'>): SavedTrip {
  const saved: SavedTrip = {
    ...trip,
    id: crypto.randomUUID(),
    savedAt: new Date().toISOString(),
  }
  writeAll([...readAll(), saved])
  return saved
}

export function deleteSavedTrip(id: string): void {
  writeAll(readAll().filter((t) => t.id !== id))
}
