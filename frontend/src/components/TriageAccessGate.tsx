import { useState } from 'react'
import { Link } from 'react-router-dom'

import OtpInput from './OtpInput'
import {
  requestOtp,
  startRegistration,
  submitDemographics,
  verifyOtp,
} from '../lib/registrationApi'
import { saveTriageSessionToken } from '../lib/session'

interface Props {
  onReady: (token: string) => void
}

/**
 * Triage needs a verified patient. Returning patients confirm who they are
 * (matched against their existing record) and verify with an OTP; brand-new
 * patients are pointed at the registration chat instead.
 */
export default function TriageAccessGate({ onReady }: Props) {
  const [form, setForm] = useState({
    first_name: '', last_name: '', dob: '', contact_number: '',
  })
  const [phase, setPhase] = useState<'form' | 'otp'>('form')
  const [token, setToken] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const field = (key: keyof typeof form, label: string, props = {}) => (
    <label className="block text-sm text-slate-600">
      {label}
      <input
        value={form[key]}
        onChange={(e) => setForm({ ...form, [key]: e.target.value })}
        required
        className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm
                   text-slate-900 focus:border-teal-600 focus:outline-none"
        {...props}
      />
    </label>
  )

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const session = await startRegistration()
      await submitDemographics(session.session_token, form)
      await requestOtp(session.session_token)
      setToken(session.session_token)
      setPhase('otp')
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status
      setError(
        status === 409
          ? 'Your details are close to an existing record — a staff member needs to review this before you can continue.'
          : "Couldn't verify your details — please check them and try again.",
      )
    } finally {
      setBusy(false)
    }
  }

  const submitCode = async (code: string) => {
    if (!token) return
    setBusy(true)
    setError(null)
    try {
      const result = await verifyOtp(token, code)
      if (result.verified) {
        saveTriageSessionToken(token)
        onReady(token)
      }
    } catch {
      setError("That code isn't right — check the Django terminal (or use 123456 in dev).")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto mt-10 w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold text-slate-900">Before we check your symptoms</h2>
      <p className="mt-1 text-sm text-slate-500">
        Confirm who you are so we can attach the assessment to your record.
        New here?{' '}
        <Link to="/register" className="font-medium text-teal-700 underline">
          Register first
        </Link>
        .
      </p>

      {phase === 'form' ? (
        <form onSubmit={submit} className="mt-4 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            {field('first_name', 'First name')}
            {field('last_name', 'Last name')}
          </div>
          {field('dob', 'Date of birth', { type: 'date' })}
          {field('contact_number', 'Phone number', { inputMode: 'tel' })}
          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-lg bg-teal-600 px-4 py-2 text-sm font-semibold text-white
                       transition hover:bg-teal-700 disabled:opacity-40"
          >
            {busy ? 'Checking…' : 'Continue'}
          </button>
        </form>
      ) : (
        <div className="mt-4">
          <p className="text-sm font-medium text-slate-700">
            Enter the 6-digit code we sent to your phone
          </p>
          <p className="text-xs text-slate-400">
            (dev: check the Django terminal, or use 123456)
          </p>
          <OtpInput disabled={busy} onSubmit={submitCode} />
        </div>
      )}

      {error && <p className="mt-3 text-sm text-amber-700">{error}</p>}
    </div>
  )
}
