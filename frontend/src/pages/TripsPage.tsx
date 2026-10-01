import { useState } from 'react'
import { Link } from 'react-router-dom'
import { listSavedTrips, deleteSavedTrip, type SavedTrip } from '../lib/savedTrips'
import ItineraryView from '../components/ItineraryView'

export default function TripsPage() {
  const [trips, setTrips] = useState<SavedTrip[]>(() => listSavedTrips())
  const [selected, setSelected] = useState<SavedTrip | null>(null)

  function handleDelete(id: string) {
    deleteSavedTrip(id)
    setTrips(listSavedTrips())
    if (selected?.id === id) setSelected(null)
  }

  if (selected) {
    return (
      <div className="min-h-screen bg-paper px-6 py-16">
        <ItineraryView
          destination={selected.destination}
          itinerary={selected.itinerary}
          conflicts={selected.conflicts}
        />
        <div className="max-w-2xl mx-auto mt-10">
          <button
            onClick={() => setSelected(null)}
            className="text-sm text-muted hover:text-ink underline"
          >
            Back to my trips
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-paper px-6 py-16">
      <div className="max-w-lg mx-auto">
        <span className="block font-mono text-[11px] tracking-wider text-brass uppercase mb-2">
          Saved on this device
        </span>
        <h1 className="font-display font-semibold text-3xl text-ink mb-8">My trips</h1>

        {trips.length === 0 ? (
          <p className="text-muted">
            No saved trips yet.{' '}
            <Link to="/plan" className="text-brand underline">
              Plan one
            </Link>
            .
          </p>
        ) : (
          <div className="space-y-4">
            {trips.map((trip) => (
              <div
                key={trip.id}
                className="bg-white border border-line rounded-xl p-5 flex items-center justify-between"
              >
                <button
                  onClick={() => setSelected(trip)}
                  className="text-left flex-1 hover:opacity-70 transition-opacity"
                >
                  <h2 className="font-display font-semibold text-lg text-ink">
                    {trip.destination}
                  </h2>
                  <p className="text-xs text-muted font-mono mt-1">
                    {trip.itinerary.length} day{trip.itinerary.length !== 1 ? 's' : ''} · saved{' '}
                    {new Date(trip.savedAt).toLocaleDateString()}
                  </p>
                </button>
                <button
                  onClick={() => handleDelete(trip.id)}
                  className="text-route text-xs font-mono uppercase tracking-wider ml-4 hover:opacity-70"
                >
                  Delete
                </button>
              </div>
            ))}
          </div>
        )}

        <Link to="/plan" className="block mt-10 text-sm text-muted hover:text-ink underline">
          Plan another trip
        </Link>
      </div>
    </div>
  )
}
