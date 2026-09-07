import { useState, type FormEvent } from 'react'
import { postTripInput, ValidationApiError, type FieldError } from '../lib/api'

const STYLES = [
  { value: 'hidden_gems', label: 'Hidden gems' },
  { value: 'popular', label: 'Popular spots' },
  { value: 'relaxed', label: 'Relaxed' },
  { value: 'adventurous', label: 'Adventurous' },
  { value: 'cultural', label: 'Cultural' },
  { value: 'food_focused', label: 'Food-focused' },
]

interface UserInputResponse {
  destination: string | null
  surprise_me: boolean
  budget_total: number
  currency: string
  duration_days: number
  priorities_raw: string
  style: string | null
}

export default function PlanPage() {
  const [destination, setDestination] = useState('')
  const [surpriseMe, setSurpriseMe] = useState(false)
  const [budgetTotal, setBudgetTotal] = useState('')
  const [durationDays, setDurationDays] = useState('')
  const [prioritiesRaw, setPrioritiesRaw] = useState('')
  const [style, setStyle] = useState('')

  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)
  const [confirmed, setConfirmed] = useState<UserInputResponse | null>(null)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setFieldErrors({})
    setSubmitting(true)

    const payload = {
      destination: destination.trim() || null,
      surprise_me: surpriseMe,
      budget_total: budgetTotal === '' ? null : Number(budgetTotal),
      duration_days: durationDays === '' ? null : Number(durationDays),
      priorities_raw: prioritiesRaw,
      style: style || null,
    }

    try {
      const result = await postTripInput<UserInputResponse>(payload)
      setConfirmed(result)
    } catch (err) {
      if (err instanceof ValidationApiError) {
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
      } else {
        setFieldErrors({ _general: 'Something went wrong reaching the server. Is the backend running?' })
      }
    } finally {
      setSubmitting(false)
    }
  }

  if (confirmed) {
    return (
      <div className="min-h-screen bg-paper flex items-center justify-center px-6">
        <div className="max-w-md text-center">
          <div className="w-14 h-14 rounded-full bg-brand text-paper flex items-center justify-center text-2xl mx-auto mb-6">
            ✓
          </div>
          <h1 className="font-display font-semibold text-2xl text-ink mb-2">Got it</h1>
          <p className="text-muted mb-8">
            {confirmed.surprise_me
              ? "We'll surprise you — the agents take it from here."
              : `Planning for ${confirmed.destination}. The agents take it from here.`}
          </p>
          <pre className="text-left text-xs font-mono bg-white border border-line rounded-xl p-4 overflow-auto text-muted">
            {JSON.stringify(confirmed, null, 2)}
          </pre>
          <p className="text-xs text-muted mt-4">
            (This is the raw validated response — budget_agent/search_agent aren't wired to this form yet.)
          </p>
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
            {submitting ? 'Checking...' : 'Continue'}
          </button>
        </form>
      </div>
    </div>
  )
}