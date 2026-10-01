import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import {
  postTripPlan,
  resumeTripPlan,
  ValidationApiError,
  type FieldError,
  type PlanResult,
} from '../lib/api'
import { saveTrip } from '../lib/savedTrips'
import ItineraryView from '../components/ItineraryView'

const STYLES = [
  { value: 'hidden_gems', label: 'Hidden gems' },
  { value: 'popular', label: 'Popular spots' },
  { value: 'relaxed', label: 'Relaxed' },
  { value: 'adventurous', label: 'Adventurous' },
  { value: 'cultural', label: 'Cultural' },
  { value: 'food_focused', label: 'Food-focused' },
]

const RESOLUTION_LABELS: Record<string, string> = {
  increase_budget: 'Increase the budget for this',
  compromise_equally: 'Trim other categories equally to cover it',
  compromise_specific: 'Trim a specific category to cover it',
  proceed_without_hotel: 'Continue without a hotel',
}

export default function PlanPage() {
  const [origin, setOrigin] = useState('')
  const [destination, setDestination] = useState('')
  const [surpriseMe, setSurpriseMe] = useState(false)
  const [startDate, setStartDate] = useState('')
  const [budgetTotal, setBudgetTotal] = useState('')
  const [durationDays, setDurationDays] = useState('')
  const [prioritiesRaw, setPrioritiesRaw] = useState('')
  const [style, setStyle] = useState('')
  const [hotelStarPreference, setHotelStarPreference] = useState('')

  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)
  const [plan, setPlan] = useState<PlanResult | null>(null)
  const [saved, setSaved] = useState(false)

  function buildPayload() {
    return {
      destination: destination.trim() || null,
      origin: origin.trim(),
      start_date: startDate || null,
      surprise_me: surpriseMe,
      budget_total: budgetTotal === '' ? null : Number(budgetTotal),
      duration_days: durationDays === '' ? null : Number(durationDays),
      priorities_raw: prioritiesRaw,
      style: style || null,
      hotel_star_preference: hotelStarPreference === '' ? null : Number(hotelStarPreference),
    }
  }

  function mapValidationError(err: ValidationApiError) {
    const mapped: Record<string, string> = {}
    err.fieldErrors.forEach((fe: FieldError) => {
      const rawField = String(fe.loc[fe.loc.length - 1])
      // model-level validators (like destination_or_surprise_me) have
      // loc=['body'], not a specific field — route those to the
      // destination field since that's the only model-level check we have
      const field = rawField === 'body' ? 'destination' : rawField
      mapped[field] = fe.msg.replace(/^Value error, /, '')
    })
    setFieldErrors(mapped)
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setFieldErrors({})
    setSubmitting(true)
    try {
      const result = await postTripPlan(buildPayload())
      setPlan(result)
      setSaved(false)
    } catch (err) {
      if (err instanceof ValidationApiError) {
        mapValidationError(err)
      } else {
        setFieldErrors({ _general: 'Something went wrong reaching the server. Is the backend running?' })
      }
    } finally {
      setSubmitting(false)
    }
  }

  async function handleResume(choice: string) {
    if (!plan) return
    setSubmitting(true)
    try {
      const result = await resumeTripPlan(plan.run_id, choice)
      setPlan(result)
    } catch {
      setFieldErrors({ _general: 'Could not continue planning. Is the backend running?' })
    } finally {
      setSubmitting(false)
    }
  }

  if (plan?.status === 'needs_clarification' && plan.clarification) {
    const { clarification } = plan
    return (
      <div className="min-h-screen bg-paper flex items-center justify-center px-6">
        <div className="max-w-lg w-full">
          <div className="w-14 h-14 rounded-full bg-route/10 text-route flex items-center justify-center text-2xl mx-auto mb-6">
            !
          </div>
          <h1 className="font-display font-semibold text-2xl text-ink mb-2 text-center">
            Need your input
          </h1>
          {clarification.clarification_needed && (
            <p className="text-muted mb-6 text-center">{clarification.clarification_needed}</p>
          )}
          <div className="space-y-4 mb-8">
            {clarification.conflicts.map((conflict, i) => (
              <div
                key={i}
                className="bg-white border border-route/20 rounded-xl p-4 text-sm text-ink"
              >
                {conflict.description}
              </div>
            ))}
          </div>
          <div className="space-y-3">
            {(clarification.conflicts[0]?.resolution_options ?? []).map((option) => (
              <button
                key={option}
                onClick={() => handleResume(option)}
                disabled={submitting}
                className="w-full bg-brand hover:bg-brand/90 disabled:opacity-50 text-paper font-mono text-xs tracking-wider uppercase py-4 rounded-full transition-colors"
              >
                {submitting ? 'Continuing...' : RESOLUTION_LABELS[option] ?? option}
              </button>
            ))}
          </div>
          {fieldErrors._general && (
            <p className="text-route text-sm bg-route/5 border border-route/20 rounded-lg px-4 py-3 mt-4">
              {fieldErrors._general}
            </p>
          )}
        </div>
      </div>
    )
  }

  if (plan?.status === 'completed') {
    const tripDestination = destination || 'Your trip'
    return (
      <div className="min-h-screen bg-paper px-6 py-16">
        <ItineraryView
          destination={tripDestination}
          itinerary={plan.itinerary}
          conflicts={plan.conflicts}
        />
        <div className="max-w-2xl mx-auto mt-10 flex items-center gap-6">
          <button
            onClick={() => {
              saveTrip({
                destination: tripDestination,
                itinerary: plan.itinerary,
                budgetAllocation: plan.budget_allocation,
                conflicts: plan.conflicts,
              })
              setSaved(true)
            }}
            disabled={saved}
            className="bg-brand hover:bg-brand/90 disabled:opacity-50 text-paper font-mono text-xs tracking-wider uppercase px-6 py-3 rounded-full transition-colors"
          >
            {saved ? 'Saved' : 'Save trip'}
          </button>
          <button
            onClick={() => {
              setPlan(null)
              setSaved(false)
            }}
            className="text-sm text-muted hover:text-ink underline"
          >
            Plan another trip
          </button>
          <Link to="/trips" className="text-sm text-muted hover:text-ink underline">
            My trips
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-paper px-6 py-16">
      <div className="max-w-lg mx-auto">
        <span className="block font-mono text-[11px] tracking-wider text-brass uppercase mb-2">
          Plan your trip
        </span>
        <h1 className="font-display font-semibold text-3xl text-ink mb-8">Where to?</h1>

        <form onSubmit={handleSubmit} className="space-y-6">
          <div>
            <label className="block font-mono text-[10px] tracking-wider text-muted uppercase mb-2">
              Flying from
            </label>
            <input
              type="text"
              value={origin}
              onChange={(e) => setOrigin(e.target.value)}
              placeholder="Bangalore"
              className={`w-full border rounded-xl px-4 py-3 font-body text-ink bg-white focus:outline-none focus:ring-2 focus:ring-brand/40 ${
                fieldErrors.origin ? 'border-route' : 'border-line'
              }`}
            />
            {fieldErrors.origin && <p className="text-route text-xs mt-1.5">{fieldErrors.origin}</p>}
          </div>

          <div>
            <label className="block font-mono text-[10px] tracking-wider text-muted uppercase mb-2">
              Destination
            </label>
            <input
              type="text"
              value={destination}
              onChange={(e) => setDestination(e.target.value)}
              disabled={surpriseMe}
              placeholder="Tokyo, Ladakh, Paris..."
              className={`w-full border rounded-xl px-4 py-3 font-body text-ink bg-white disabled:opacity-40 disabled:bg-line/20 focus:outline-none focus:ring-2 focus:ring-brand/40 ${
                fieldErrors.destination ? 'border-route' : 'border-line'
              }`}
            />
            <label className="flex items-center gap-2 mt-3 text-sm text-muted cursor-pointer">
              <input
                type="checkbox"
                checked={surpriseMe}
                onChange={(e) => {
                  setSurpriseMe(e.target.checked)
                  if (e.target.checked) setDestination('')
                }}
                className="accent-brand"
              />
              Surprise me
            </label>
            {fieldErrors.destination && (
              <p className="text-route text-xs mt-1.5">{fieldErrors.destination}</p>
            )}
          </div>

          <div>
            <label className="block font-mono text-[10px] tracking-wider text-muted uppercase mb-2">
              Start date
            </label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className={`w-full border rounded-xl px-4 py-3 font-body text-ink bg-white focus:outline-none focus:ring-2 focus:ring-brand/40 ${
                fieldErrors.start_date ? 'border-route' : 'border-line'
              }`}
            />
            {fieldErrors.start_date && (
              <p className="text-route text-xs mt-1.5">{fieldErrors.start_date}</p>
            )}
          </div>

          <div>
            <label className="block font-mono text-[10px] tracking-wider text-muted uppercase mb-2">
              Budget (₹)
            </label>
            <input
              type="number"
              value={budgetTotal}
              onChange={(e) => setBudgetTotal(e.target.value)}
              placeholder="50000"
              className={`w-full border rounded-xl px-4 py-3 font-mono text-ink bg-white focus:outline-none focus:ring-2 focus:ring-brand/40 ${
                fieldErrors.budget_total ? 'border-route' : 'border-line'
              }`}
            />
            {fieldErrors.budget_total && (
              <p className="text-route text-xs mt-1.5">{fieldErrors.budget_total}</p>
            )}
          </div>

          <div>
            <label className="block font-mono text-[10px] tracking-wider text-muted uppercase mb-2">
              Duration (days)
            </label>
            <input
              type="number"
              value={durationDays}
              onChange={(e) => setDurationDays(e.target.value)}
              placeholder="7"
              className={`w-full border rounded-xl px-4 py-3 font-mono text-ink bg-white focus:outline-none focus:ring-2 focus:ring-brand/40 ${
                fieldErrors.duration_days ? 'border-route' : 'border-line'
              }`}
            />
            {fieldErrors.duration_days && (
              <p className="text-route text-xs mt-1.5">{fieldErrors.duration_days}</p>
            )}
          </div>

          <div>
            <label className="block font-mono text-[10px] tracking-wider text-muted uppercase mb-2">
              Style
            </label>
            <select
              value={style}
              onChange={(e) => setStyle(e.target.value)}
              className={`w-full border rounded-xl px-4 py-3 font-body text-ink bg-white focus:outline-none focus:ring-2 focus:ring-brand/40 ${
                fieldErrors.style ? 'border-route' : 'border-line'
              }`}
            >
              <option value="">No preference</option>
              {STYLES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
            {fieldErrors.style && <p className="text-route text-xs mt-1.5">{fieldErrors.style}</p>}
          </div>

          <div>
            <label className="block font-mono text-[10px] tracking-wider text-muted uppercase mb-2">
              Hotel star preference (optional)
            </label>
            <select
              value={hotelStarPreference}
              onChange={(e) => setHotelStarPreference(e.target.value)}
              className={`w-full border rounded-xl px-4 py-3 font-body text-ink bg-white focus:outline-none focus:ring-2 focus:ring-brand/40 ${
                fieldErrors.hotel_star_preference ? 'border-route' : 'border-line'
              }`}
            >
              <option value="">No preference</option>
              {[1, 2, 3, 4, 5].map((n) => (
                <option key={n} value={n}>
                  {n} star{n > 1 ? 's' : ''}
                </option>
              ))}
            </select>
            {fieldErrors.hotel_star_preference && (
              <p className="text-route text-xs mt-1.5">{fieldErrors.hotel_star_preference}</p>
            )}
          </div>

          <div>
            <label className="block font-mono text-[10px] tracking-wider text-muted uppercase mb-2">
              Anything you care about?
            </label>
            <textarea
              value={prioritiesRaw}
              onChange={(e) => setPrioritiesRaw(e.target.value)}
              placeholder="I care more about food than fancy hotels..."
              rows={3}
              className="w-full border border-line rounded-xl px-4 py-3 font-body text-ink bg-white focus:outline-none focus:ring-2 focus:ring-brand/40 resize-none"
            />
          </div>

          {fieldErrors._general && (
            <p className="text-route text-sm bg-route/5 border border-route/20 rounded-lg px-4 py-3">
              {fieldErrors._general}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full bg-brand hover:bg-brand/90 disabled:opacity-50 text-paper font-mono text-xs tracking-wider uppercase py-4 rounded-full transition-colors"
          >
            {submitting ? 'Planning your trip...' : 'Plan my trip'}
          </button>
        </form>
      </div>
    </div>
  )
}
