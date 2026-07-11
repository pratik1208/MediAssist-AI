import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import TriageAccessGate from '../components/TriageAccessGate'
import { startAssessment, submitAnswer } from '../lib/triageApi'
import type { Acuity, Disposition } from '../lib/triageApi'
import {
  clearTriageSession,
  registrationSessionToken,
  triageSessionToken,
} from '../lib/session'

interface Bubble {
  id: number
  kind: 'user' | 'assistant' | 'error'
  text: string
}

interface Result {
  emergency: boolean
  acuity: Acuity
  disposition?: Disposition
  text: string
  offerBooking: boolean
}

const ACUITY_LABEL: Record<Acuity, string> = {
  minimal: 'Minimal concern',
  low: 'Low urgency',
  medium: 'Medium urgency',
  high: 'High urgency',
  emergency: 'Emergency',
}

// How soon to ask for when handing off to the scheduling chat.
const TIMEFRAME_FOR: Partial<Record<Disposition, string>> = {
  same_day: 'today',
  '24_48h': 'tomorrow',
  routine: 'this week',
}

let nextId = 1

export default function TriageChatPage() {
  const [token, setToken] = useState<string | null>(
    () => triageSessionToken() ?? registrationSessionToken(),
  )
  const [items, setItems] = useState<Bubble[]>([])
  const [assessmentId, setAssessmentId] = useState<number | null>(null)
  const [symptoms, setSymptoms] = useState('')
  const [result, setResult] = useState<Result | null>(null)
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [items, result])

  const append = (kind: Bubble['kind'], text: string) =>
    setItems((prev) => [...prev, { id: nextId++, kind, text }])

  const finish = (payload: {
    acuity?: Acuity
    disposition?: Disposition
    message?: string
    explanation?: string
    ui_hints?: { emergency?: boolean; offer_booking?: boolean }
  }) => {
    setResult({
      emergency: payload.ui_hints?.emergency ?? false,
      acuity: payload.acuity ?? 'minimal',
      disposition: payload.disposition,
      text: payload.message ?? payload.explanation ?? '',
      offerBooking: payload.ui_hints?.offer_booking ?? false,
    })
  }

  const handleAuthFailure = () => {
    clearTriageSession()
    setToken(null)
    setItems([])
    setAssessmentId(null)
  }

  const send = async () => {
    const text = input.trim()
    if (!text || !token || busy || result) return
    setInput('')
    append('user', text)
    setBusy(true)
    try {
      if (assessmentId === null) {
        setSymptoms(text)
        const started = await startAssessment(token, text)
        setAssessmentId(started.id)
        if (started.complete) {
          finish(started)
        } else {
          append('assistant', started.first_question ?? '')
        }
      } else {
        const answer = await submitAnswer(token, assessmentId, text)
        if ('next_question' in answer) {
          append('assistant', answer.next_question)
        } else {
          finish(answer)
        }
      }
    } catch (err: unknown) {
      const e = err as { status?: number; body?: { error?: string } }
      if (e.status === 401 || e.status === 403) {
        handleAuthFailure()
      } else if (e.status === 422) {
        setAssessmentId(null)
        append('error', e.body?.error ??
          "We couldn't match your symptoms to an assessment — please describe them differently.")
      } else {
        append('error', "Sorry — I couldn't reach the clinic system. Please try again.")
      }
    } finally {
      setBusy(false)
    }
  }

  const restart = () => {
    setItems([])
    setAssessmentId(null)
    setSymptoms('')
    setResult(null)
  }

  const bookNow = () => {
    const timeframe = TIMEFRAME_FOR[result?.disposition ?? 'routine'] ?? 'this week'
    navigate('/schedule', {
      state: { prefill: `${symptoms} — can I get an appointment ${timeframe}?` },
    })
  }

  return (
    <div className="mx-auto flex h-screen max-w-3xl flex-col bg-slate-50">
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
        <div>
          <h1 className="text-lg font-bold text-slate-900">MediAssist AI</h1>
          <p className="text-xs text-slate-500">Symptom check (triage)</p>
        </div>
        <nav className="flex items-center gap-3 text-sm">
          {result && (
            <button onClick={restart} className="text-slate-500 hover:text-teal-700">
              New assessment
            </button>
          )}
          <Link to="/schedule" className="font-medium text-teal-700 hover:underline">
            Book appointment →
          </Link>
        </nav>
      </header>

      {!token ? (
        <TriageAccessGate onReady={setToken} />
      ) : (
        <>
          <div className="flex-1 space-y-3 overflow-y-auto p-4">
            {items.length === 0 && !result && (
              <div className="mt-16 text-center text-slate-500">
                <p className="text-lg font-medium text-slate-700">
                  Let's check your symptoms.
                </p>
                <p className="mt-1 text-sm">
                  Describe what you're feeling — for example: “I've had a
                  headache and nausea since this morning.”
                </p>
                <p className="mt-3 text-xs text-red-600">
                  If this is a medical emergency, call your local emergency
                  number now — don't wait for this assessment.
                </p>
              </div>
            )}

            {items.map((item) => (
              <div
                key={item.id}
                className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm shadow-sm ${
                  item.kind === 'user'
                    ? 'ml-auto bg-teal-600 text-white'
                    : item.kind === 'error'
                      ? 'mr-auto border border-amber-300 bg-amber-50 text-amber-900'
                      : 'mr-auto border border-slate-200 bg-white text-slate-800'
                }`}
              >
                {item.text}
              </div>
            ))}

            {busy && (
              <div className="mr-auto max-w-[85%] rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-400 shadow-sm">
                <span className="animate-pulse">Checking…</span>
              </div>
            )}

            {result && result.emergency && (
              <div className="rounded-2xl border-2 border-red-600 bg-red-50 p-6 text-center">
                <p className="text-3xl">🚨</p>
                <h2 className="mt-2 text-xl font-bold text-red-700">
                  Seek emergency care now
                </h2>
                <p className="mx-auto mt-2 max-w-md text-sm text-red-800">
                  {result.text}
                </p>
                <p className="mt-4 text-lg font-bold text-red-700">
                  Call 911 / your local emergency number
                </p>
              </div>
            )}

            {result && !result.emergency && (
              <div className="rounded-2xl border border-slate-200 bg-white p-6">
                <span className="rounded-full border border-teal-600 px-3 py-1 text-xs font-semibold text-teal-700">
                  {ACUITY_LABEL[result.acuity]}
                </span>
                <p className="mt-3 text-sm text-slate-800">{result.text}</p>
                {result.offerBooking && (
                  <button
                    onClick={bookNow}
                    className="mt-4 rounded-lg bg-teal-600 px-4 py-2 text-sm font-semibold text-white
                               transition hover:bg-teal-700"
                  >
                    Book an appointment →
                  </button>
                )}
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {!result && (
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
                placeholder={
                  assessmentId === null
                    ? 'Describe your symptoms…'
                    : 'Type your answer…'
                }
                className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm
                           text-slate-900 focus:border-teal-600 focus:outline-none"
              />
              <button
                type="submit"
                disabled={busy || input.trim() === ''}
                className="rounded-lg bg-teal-600 px-4 py-2 text-sm font-semibold text-white
                           transition hover:bg-teal-700 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Send
              </button>
            </form>
          )}
        </>
      )}
    </div>
  )
}
