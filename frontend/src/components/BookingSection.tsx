import { useState, type FormEvent } from 'react'
import {
  bookFlight,
  bookHotel,
  BookingApiError,
  ValidationApiError,
  type BookingResult,
  type FieldError,
  type GuestDetails,
  type PassengerDetails,
} from '../lib/api'

const TITLES: PassengerDetails['title'][] = ['mr', 'mrs', 'ms', 'miss', 'dr']

interface BookingSectionProps {
  runId: string
}

/**
 * Sandbox-only booking (PRD §2.2 non-goal: no real payment). Two
 * independent mini-forms -- flight needs Duffel's passenger fields
 * (title/gender/DOB/phone, for airline compliance even in test mode),
 * hotel only needs a name + email for LiteAPI. Each books against
 * whatever search_agent/itinerary_agent already picked for this run_id
 * -- there's no candidate-selection UI here, booking acts on the plan
 * already shown above.
 */
export default function BookingSection({ runId }: BookingSectionProps) {
  return (
    <div className="max-w-2xl mx-auto mt-10 space-y-8">
      <div>
        <span className="block font-mono text-[11px] tracking-wider text-brass uppercase mb-4">
          Book this trip (sandbox — no real payment)
        </span>
        <div className="grid sm:grid-cols-2 gap-6">
          <FlightBookingForm runId={runId} />
          <HotelBookingForm runId={runId} />
        </div>
      </div>
    </div>
  )
}

function ResultBanner({ result }: { result: BookingResult }) {
  if (result.success) {
    return (
      <div className="mt-4 bg-brand/5 border border-brand/20 rounded-lg px-4 py-3 text-sm text-ink">
        Booked. Confirmation: <span className="font-mono">{result.confirmation_code}</span>
      </div>
    )
  }
  return (
    <div className="mt-4 bg-route/5 border border-route/20 rounded-lg px-4 py-3 text-sm text-route">
      {result.error_message ?? 'Booking failed.'}
    </div>
  )
}

function FlightBookingForm({ runId }: { runId: string }) {
  const [title, setTitle] = useState<PassengerDetails['title']>('mr')
  const [gender, setGender] = useState<PassengerDetails['gender']>('m')
  const [givenName, setGivenName] = useState('')
  const [familyName, setFamilyName] = useState('')
  const [bornOn, setBornOn] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')

  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<BookingResult | null>(null)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setFieldErrors({})
    setSubmitting(true)
    try {
      const booked = await bookFlight(runId, {
        title,
        gender,
        given_name: givenName,
        family_name: familyName,
        born_on: bornOn,
        email,
        phone_number: phone,
      })
      setResult(booked)
    } catch (err) {
      if (err instanceof ValidationApiError) {
        const mapped: Record<string, string> = {}
        err.fieldErrors.forEach((fe: FieldError) => {
          mapped[String(fe.loc[fe.loc.length - 1])] = fe.msg.replace(/^Value error, /, '')
        })
        setFieldErrors(mapped)
      } else if (err instanceof BookingApiError) {
        setFieldErrors({ _general: err.message })
      } else {
        setFieldErrors({ _general: 'Something unexpected went wrong. Please try again.' })
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="bg-white border border-line rounded-xl p-5 space-y-3">
      <h3 className="font-mono text-[10px] tracking-wider text-muted uppercase">Book flight</h3>

      <div className="flex gap-2">
        <select
          value={title}
          onChange={(e) => setTitle(e.target.value as PassengerDetails['title'])}
          className="border border-line rounded-lg px-2 py-2 text-sm bg-white"
        >
          {TITLES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <select
          value={gender}
          onChange={(e) => setGender(e.target.value as PassengerDetails['gender'])}
          className="border border-line rounded-lg px-2 py-2 text-sm bg-white"
        >
          <option value="m">Male</option>
          <option value="f">Female</option>
        </select>
      </div>

      <input
        type="text"
        value={givenName}
        onChange={(e) => setGivenName(e.target.value)}
        placeholder="Given name"
        required
        className="w-full border border-line rounded-lg px-3 py-2 text-sm bg-white"
      />
      <input
        type="text"
        value={familyName}
        onChange={(e) => setFamilyName(e.target.value)}
        placeholder="Family name"
        required
        className="w-full border border-line rounded-lg px-3 py-2 text-sm bg-white"
      />
      <input
        type="date"
        value={bornOn}
        onChange={(e) => setBornOn(e.target.value)}
        required
        className="w-full border border-line rounded-lg px-3 py-2 text-sm bg-white"
      />
      <input
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="Email"
        required
        className="w-full border border-line rounded-lg px-3 py-2 text-sm bg-white"
      />
      <input
        type="tel"
        value={phone}
        onChange={(e) => setPhone(e.target.value)}
        placeholder="Phone (e.g. +919876543210)"
        required
        className="w-full border border-line rounded-lg px-3 py-2 text-sm bg-white"
      />

      {fieldErrors._general && <p className="text-route text-xs">{fieldErrors._general}</p>}

      <button
        type="submit"
        disabled={submitting}
        className="w-full bg-brand hover:bg-brand/90 disabled:opacity-50 text-paper font-mono text-xs tracking-wider uppercase py-3 rounded-full transition-colors"
      >
        {submitting ? 'Booking...' : 'Book flight'}
      </button>

      {result && <ResultBanner result={result} />}
    </form>
  )
}

function HotelBookingForm({ runId }: { runId: string }) {
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [email, setEmail] = useState('')

  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<BookingResult | null>(null)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setFieldErrors({})
    setSubmitting(true)
    try {
      const guest: GuestDetails = { first_name: firstName, last_name: lastName, email }
      const booked = await bookHotel(runId, guest)
      setResult(booked)
    } catch (err) {
      if (err instanceof ValidationApiError) {
        const mapped: Record<string, string> = {}
        err.fieldErrors.forEach((fe: FieldError) => {
          mapped[String(fe.loc[fe.loc.length - 1])] = fe.msg.replace(/^Value error, /, '')
        })
        setFieldErrors(mapped)
      } else if (err instanceof BookingApiError) {
        setFieldErrors({ _general: err.message })
      } else {
        setFieldErrors({ _general: 'Something unexpected went wrong. Please try again.' })
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="bg-white border border-line rounded-xl p-5 space-y-3">
      <h3 className="font-mono text-[10px] tracking-wider text-muted uppercase">Book hotel</h3>

      <input
        type="text"
        value={firstName}
        onChange={(e) => setFirstName(e.target.value)}
        placeholder="First name"
        required
        className="w-full border border-line rounded-lg px-3 py-2 text-sm bg-white"
      />
      <input
        type="text"
        value={lastName}
        onChange={(e) => setLastName(e.target.value)}
        placeholder="Last name"
        required
        className="w-full border border-line rounded-lg px-3 py-2 text-sm bg-white"
      />
      <input
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="Email"
        required
        className="w-full border border-line rounded-lg px-3 py-2 text-sm bg-white"
      />

      {fieldErrors._general && <p className="text-route text-xs">{fieldErrors._general}</p>}

      <button
        type="submit"
        disabled={submitting}
        className="w-full bg-brand hover:bg-brand/90 disabled:opacity-50 text-paper font-mono text-xs tracking-wider uppercase py-3 rounded-full transition-colors"
      >
        {submitting ? 'Booking...' : 'Book hotel'}
      </button>

      {result && <ResultBanner result={result} />}
    </form>
  )
}
