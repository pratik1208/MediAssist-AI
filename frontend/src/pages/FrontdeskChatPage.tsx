// Agent 9 Phase 5: the front desk chat is the DEFAULT patient-facing
// surface. Registration/triage/scheduling/refills stay reachable as
// destinations (nav links + contextual "open in ..." links after a
// routed reply) rather than separate entry points patients have to know
// to visit.

import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import OtpInput from '../components/OtpInput'
import {
  sendFrontdeskMessage,
  startFrontdesk,
  startFrontdeskAuth,
  verifyFrontdeskOtp,
} from '../lib/frontdeskApi'
import type { FrontdeskResult } from '../lib/frontdeskApi'

interface Bubble {
  id: number
  kind: 'user' | 'assistant'
  text: string
  tone?: 'emergency' | 'escalated' | 'success' | 'error'
  extras?: FrontdeskResult[]
}

type AuthPhase = 'closed' | 'collecting' | 'code_sent'

const STORAGE_KEY = 'mediassist.frontdesk'

let nextId = 1

const GREETING: Bubble = {
  id: 0,
  kind: 'assistant',
  text:
    "Hi, I'm the MediAssist front desk — here any time, day or night. " +
    'Tell me what you need: book or check an appointment, refill a ' +
    "medication, ask about a referral or insurance approval, see if you're " +
    'due for any preventive care, or just ask a question about the clinic.',
}

export default function FrontdeskChatPage() {
  const [token, setToken] = useState<string | null>(null)
  const [items, setItems] = useState<Bubble[]>([GREETING])
  const [authenticated, setAuthenticated] = useState(false)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [startError, setStartError] = useState(false)

  const [authPhase, setAuthPhase] = useState<AuthPhase>('closed')
  const [authPhone, setAuthPhone] = useState('')
  const [authDob, setAuthDob] = useState('')
  const [pendingDob, setPendingDob] = useState('')
  const [authBusy, setAuthBusy] = useState(false)
  const [authNote, setAuthNote] = useState<string | null>(null)

  const bottomRef = useRef<HTMLDivElement>(null)

  // Start (or restore) the front-door session.
  useEffect(() => {
    const saved = sessionStorage.getItem(STORAGE_KEY)
    if (saved) {
      const state = JSON.parse(saved)
      setToken(state.token)
      setItems(state.items)
      setAuthenticated(state.authenticated ?? false)
      nextId = state.items.length + 1
      return
    }
    startFrontdesk()
      .then((session) => setToken(session.session_token))
      .catch(() => setStartError(true))
  }, [])

  useEffect(() => {
    if (token) {
      sessionStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ token, items, authenticated }),
      )
    }
  }, [token, items, authenticated])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [items, sending, authPhase])

  const append = (bubble: Omit<Bubble, 'id'>) =>
    setItems((prev) => [...prev, { ...bubble, id: nextId++ }])

  const toneFor = (status: string): Bubble['tone'] => {
    if (status === 'emergency') return 'emergency'
    if (status === 'escalated') return 'escalated'
    return undefined
  }

  const send = async () => {
    const text = input.trim()
    if (!text || !token || sending) return
    setInput('')
    append({ kind: 'user', text })
    setSending(true)
    try {
      const outcome = await sendFrontdeskMessage(token, text)
      append({
        kind: 'assistant',
        text: outcome.reply,
        tone: toneFor(outcome.status),
        extras: outcome.results ?? [outcome],
      })
      if (outcome.status === 'auth_required') setAuthPhase('collecting')
    } catch {
      append({
        kind: 'assistant',
        tone: 'error',
        text: "Sorry — I couldn't reach the clinic system. Please try again.",
      })
    } finally {
      setSending(false)
    }
  }

  const submitAuthStart = async () => {
    if (!token || !authPhone.trim() || !authDob) return
    setAuthBusy(true)
    setAuthNote(null)
    try {
      const outcome = await startFrontdeskAuth(token, authPhone.trim(), authDob)
      if (outcome.status === 'auth_started') {
        setPendingDob(authDob)
        setAuthPhase('code_sent')
        append({ kind: 'assistant', text: outcome.reply })
      } else {
        setAuthNote(outcome.reply)
      }
    } catch {
      setAuthNote("Couldn't reach the clinic system — please try again.")
    } finally {
      setAuthBusy(false)
    }
  }

  const submitOtp = async (code: string) => {
    if (!token) return
    setAuthBusy(true)
    setAuthNote(null)
    try {
      const outcome = await verifyFrontdeskOtp(token, pendingDob, code)
      if (outcome.status === 'authenticated') {
        setAuthenticated(true)
        setAuthPhase('closed')
        setAuthPhone('')
        setAuthDob('')
        setPendingDob('')
        append({ kind: 'assistant', tone: 'success', text: `✓ ${outcome.reply}` })
        for (const item of outcome.resumed ?? []) {
          append({
            kind: 'assistant',
            text: item.reply,
            tone: toneFor(item.status),
            extras: [item],
          })
        }
      } else {
        setAuthNote(outcome.reply)
      }
    } catch {
      setAuthNote("Couldn't reach the clinic system — please try again.")
    } finally {
      setAuthBusy(false)
    }
  }

  const bubbleClass = (bubble: Bubble): string => {
    if (bubble.kind === 'user') return 'ml-auto bg-teal-600 text-white'
    if (bubble.tone === 'emergency') return 'mr-auto border-2 border-red-600 bg-red-50 text-red-800'
    if (bubble.tone === 'escalated') return 'mr-auto border border-amber-300 bg-amber-50 text-amber-900'
    if (bubble.tone === 'error') return 'mr-auto border border-amber-300 bg-amber-50 text-amber-900'
    if (bubble.tone === 'success') return 'mr-auto border border-green-300 bg-green-50 text-green-900'
    return 'mr-auto border border-slate-200 bg-white text-slate-800'
  }

  return (
    <div className="mx-auto flex h-screen max-w-3xl flex-col bg-slate-50">
      <header className="border-b border-slate-200 bg-white px-4 py-3">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-lg font-bold text-slate-900">MediAssist AI</h1>
            <p className="text-xs text-slate-500">
              Front desk{authenticated && <span className="text-green-700"> · ✓ verified</span>}
            </p>
          </div>
          <nav className="flex flex-wrap items-center justify-end gap-x-3 gap-y-1 text-sm">
            <Link to="/schedule" className="font-medium text-teal-700 hover:underline">
              Schedule
            </Link>
            <Link to="/refills" className="font-medium text-teal-700 hover:underline">
              Refills
            </Link>
            <Link to="/referrals" className="font-medium text-teal-700 hover:underline">
              Referrals
            </Link>
            <Link to="/authorizations" className="font-medium text-teal-700 hover:underline">
              Authorizations
            </Link>
            <Link to="/triage" className="font-medium text-teal-700 hover:underline">
              Symptom check
            </Link>
            <Link to="/register" className="font-medium text-teal-700 hover:underline">
              New patient? Register →
            </Link>
            <Link to="/staff/frontdesk/tasks" className="text-slate-400 hover:text-teal-700">
              Staff queue
            </Link>
          </nav>
        </div>
      </header>

      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {startError && (
          <div className="mx-auto rounded-2xl border border-amber-300 bg-amber-50 px-4 py-2.5 text-center text-sm text-amber-900">
            Couldn't start a session — is the backend running on port 8001?
          </div>
        )}

        {items.map((item) => (
          <div key={item.id}>
            <div
              className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm shadow-sm ${bubbleClass(item)}`}
            >
              {item.tone === 'emergency' && (
                <p className="mb-1 font-bold">🚨 Emergency</p>
              )}
              {item.text}
            </div>
            {item.extras && <ResultExtras results={item.extras} />}
          </div>
        ))}

        {sending && (
          <div className="mr-auto max-w-[85%] rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-400 shadow-sm">
            <span className="animate-pulse">Thinking…</span>
          </div>
        )}

        {authPhase === 'collecting' && (
          <div className="mr-auto max-w-[85%] rounded-2xl border border-teal-200 bg-teal-50 px-4 py-3 shadow-sm">
            <p className="text-sm font-medium text-teal-900">
              Verify your identity to continue
            </p>
            <form
              className="mt-2 flex flex-wrap items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                void submitAuthStart()
              }}
            >
              <label className="text-xs text-teal-800">
                Phone number
                <input
                  value={authPhone}
                  onChange={(e) => setAuthPhone(e.target.value)}
                  placeholder="9876543210"
                  className="mt-1 block w-36 rounded-lg border border-slate-300 px-2 py-1.5 text-sm
                             text-slate-900 focus:border-teal-600 focus:outline-none"
                />
              </label>
              <label className="text-xs text-teal-800">
                Date of birth
                <input
                  type="date"
                  value={authDob}
                  onChange={(e) => setAuthDob(e.target.value)}
                  className="mt-1 block rounded-lg border border-slate-300 px-2 py-1.5 text-sm
                             text-slate-900 focus:border-teal-600 focus:outline-none"
                />
              </label>
              <button
                type="submit"
                disabled={authBusy || !authPhone.trim() || !authDob}
                className="rounded-lg bg-teal-600 px-3 py-1.5 text-sm font-semibold text-white
                           transition hover:bg-teal-700 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Send code
              </button>
            </form>
            {authNote && <p className="mt-2 text-xs text-amber-700">{authNote}</p>}
          </div>
        )}

        {authPhase === 'code_sent' && (
          <div className="mr-auto max-w-[85%] rounded-2xl border border-teal-200 bg-teal-50 px-4 py-3 shadow-sm">
            <p className="text-sm font-medium text-teal-900">
              Enter your 6-digit verification code
            </p>
            <OtpInput disabled={authBusy} onSubmit={submitOtp} />
            <button
              type="button"
              onClick={() => setAuthPhase('collecting')}
              className="mt-2 text-xs text-teal-700 underline"
            >
              Use a different number
            </button>
            {authNote && <p className="mt-2 text-xs text-amber-700">{authNote}</p>}
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      <form
        className="flex gap-2 border-t border-slate-200 bg-white p-3"
        onSubmit={(e) => {
          e.preventDefault()
          void send()
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={token ? 'Type your question or request…' : 'Starting session…'}
          disabled={!token}
          className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm
                     text-slate-900 focus:border-teal-600 focus:outline-none"
        />
        <button
          type="submit"
          disabled={!token || sending || input.trim() === ''}
          className="rounded-lg bg-teal-600 px-4 py-2 text-sm font-semibold text-white
                     transition hover:bg-teal-700 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Send
        </button>
      </form>
    </div>
  )
}

const RISK_STYLE: Record<string, string> = {
  high: 'bg-red-100 text-red-800',
  medium: 'bg-amber-100 text-amber-800',
  low: 'bg-slate-200 text-slate-700',
}

/** Structured data behind a routed reply — appointment/prescription/
 * referral/authorization/care-gap lists, article citations, and a
 * contextual "open in ..." link into the specialist agent that owns it. */
function ResultExtras({ results }: { results: FrontdeskResult[] }) {
  const appointments = results.flatMap((r) => r.appointments ?? [])
  const prescriptions = results.flatMap((r) => r.prescriptions ?? [])
  const referrals = results.flatMap((r) => r.referrals ?? [])
  const authorizations = results.flatMap((r) => r.authorizations ?? [])
  const careGaps = results.flatMap((r) => r.care_gaps ?? [])
  const articles = results.flatMap((r) => r.articles ?? [])
  const handoffToTriage = results.some((r) => r.handoff === 'triage')
  const hasAppointmentIntent = results.some((r) => 'appointments' in r)
  const hasStaffTask = results.some((r) => r.staff_task_id !== undefined)

  const nothing =
    !hasAppointmentIntent && prescriptions.length === 0 && referrals.length === 0 &&
    authorizations.length === 0 && careGaps.length === 0 && articles.length === 0 &&
    !handoffToTriage && !hasStaffTask

  if (nothing) return null

  return (
    <div className="mr-auto mt-1.5 max-w-[85%] space-y-1.5 text-xs">
      {appointments.map((a) => (
        <div key={a.id} className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-700">
          📅 {new Date(a.start_time).toLocaleString(undefined, {
            weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
          })} with {a.doctor} — {a.reason}
        </div>
      ))}
      {prescriptions.map((p) => (
        <div key={p.id} className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-700">
          💊 {p.medication} — {p.refills_left} refill{p.refills_left === 1 ? '' : 's'} left
          {p.controlled && <span className="ml-1.5 rounded bg-amber-100 px-1.5 py-0.5 text-amber-800">controlled</span>}
        </div>
      ))}
      {referrals.map((r) => (
        <div key={r.id} className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-700">
          🩺 Referral to {r.specialty} — <span className="font-medium">{r.status.replace(/_/g, ' ')}</span>
        </div>
      ))}
      {authorizations.map((a) => (
        <div key={a.id} className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-700">
          📋 {a.order_type.replace(/_/g, ' ')} authorization — <span className="font-medium">{a.status.replace(/_/g, ' ')}</span>
        </div>
      ))}
      {careGaps.map((g) => (
        <div key={g.gap_id} className="flex items-center justify-between rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-700">
          <span>
            <span className={`mr-1.5 rounded px-1.5 py-0.5 text-[10px] font-semibold ${RISK_STYLE[g.risk_tier] ?? 'bg-slate-200 text-slate-700'}`}>
              {g.risk_tier}
            </span>
            {g.guideline}
            {g.days_overdue > 0 && ` — ${g.days_overdue}d overdue`}
          </span>
        </div>
      ))}
      {articles.length > 0 && (
        <p className="text-slate-400">
          Source: {articles.map((a) => a.title).join(', ')}
        </p>
      )}
      {hasStaffTask && (
        <p className="text-slate-400">🧑‍⚕️ A team member will follow up on this.</p>
      )}

      <div className="flex flex-wrap gap-3 pt-0.5">
        {hasAppointmentIntent && (
          <Link to="/schedule" className="font-medium text-teal-700 hover:underline">Book or manage in Scheduling →</Link>
        )}
        {prescriptions.length > 0 && (
          <Link to="/refills" className="font-medium text-teal-700 hover:underline">Open in Refills →</Link>
        )}
        {referrals.length > 0 && (
          <Link to="/referrals" className="font-medium text-teal-700 hover:underline">Open in Referrals →</Link>
        )}
        {authorizations.length > 0 && (
          <Link to="/authorizations" className="font-medium text-teal-700 hover:underline">Open in Authorizations →</Link>
        )}
        {careGaps.length > 0 && (
          <Link to="/schedule" className="font-medium text-teal-700 hover:underline">Book this care →</Link>
        )}
        {handoffToTriage && (
          <Link to="/triage" className="font-medium text-teal-700 hover:underline">Continue symptom check →</Link>
        )}
      </div>
    </div>
  )
}
