import type { DayPlan, Conflict } from '../lib/api'

interface ItineraryViewProps {
  destination: string
  itinerary: DayPlan[]
  conflicts: Conflict[]
}

/**
 * Shared by PlanPage's completed-plan view and the saved-trip detail view
 * (TripsPage) — extracted so both render an identical itinerary instead
 * of two copies of the same JSX drifting apart over time.
 */
export default function ItineraryView({ destination, itinerary, conflicts }: ItineraryViewProps) {
  return (
    <div className="max-w-2xl mx-auto">
      <span className="block font-mono text-[11px] tracking-wider text-brass uppercase mb-2">
        Itinerary
      </span>
      <h1 className="font-display font-semibold text-3xl text-ink mb-8">{destination}</h1>

      {conflicts.length > 0 && (
        <div className="mb-8 space-y-2">
          {conflicts.map((c, i) => (
            <p
              key={i}
              className="text-sm text-route bg-route/5 border border-route/20 rounded-lg px-4 py-3"
            >
              {c.description}
            </p>
          ))}
        </div>
      )}

      <div className="space-y-8">
        {itinerary.map((day) => (
          <div key={day.day_number} className="bg-white border border-line rounded-xl p-6">
            <span className="block font-mono text-[10px] tracking-wider text-muted uppercase mb-2">
              Day {day.day_number}
            </span>
            <p className="text-ink font-body mb-4">{day.summary}</p>
            <div className="space-y-2 border-t border-line pt-4">
              {day.items.map((item) => (
                <div key={item.id} className="flex justify-between text-sm">
                  <span className="text-muted font-mono text-[10px] uppercase mr-3 mt-0.5">
                    {item.category}
                  </span>
                  <span className="text-ink flex-1">{item.name}</span>
                  <span className="text-muted font-mono ml-3">₹{Math.round(item.price)}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
