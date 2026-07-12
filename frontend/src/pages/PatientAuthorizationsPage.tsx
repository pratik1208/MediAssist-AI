import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import TriageAccessGate from '../components/TriageAccessGate'
import { getMyAuthorizations } from '../lib/priorauthApi'
import {
  clearTriageSession,
  registrationSessionToken,
  triageSessionToken,
} from '../lib/session'

// Plain-language status + what happens next, per status (Phase 5's
// "authorization status card" — patients never see internal stage names).
const STATUS_COPY: Record<string, { label: string; next: string; tone: string }> = {
  detected: {
    label: 'Checking your coverage',
    next: "We're confirming whether your insurance requires approval for this treatment.",
    tone: 'bg-slate-100 text-slate-700',
  },
  gathering_evidence: {
    label: 'Checking your coverage',
    next: "We're gathering what your insurance needs to review this request.",
    tone: 'bg-slate-100 text-slate-700',
  },
  ready_for_review: {
    label: 'Ready to submit',
    next: "We're about to send this request to your insurance.",
    tone: 'bg-amber-100 text-amber-800',
  },
  submitted: {
    label: 'Sent to your insurance',
    next: 'Your insurance has received the request. This can take a few days.',
    tone: 'bg-sky-100 text-sky-800',
  },
  under_review: {
    label: 'Being reviewed',
    next: 'Your insurance is reviewing the request now.',
    tone: 'bg-sky-100 text-sky-800',
  },
  info_requested: {
    label: 'More information requested',
    next: "Your insurance asked for more details — we're handling it. No action needed from you.",
    tone: 'bg-amber-100 text-amber-800',
  },
  approved: {
    label: 'Approved',
    next: "🎉 Approved! We'll be in touch to schedule your treatment.",
    tone: 'bg-green-100 text-green-800',
  },
  denied: {
    label: 'Not approved',
    next: 'Your insurance did not approve this request. Please contact the clinic to discuss next steps.',
    tone: 'bg-red-100 text-red-800',
  },
}

export default function PatientAuthorizationsPage() {
  const [token, setToken] = useState<string | null>(
    () => triageSessionToken() ?? registrationSessionToken(),
  )

  const authorizations = useQuery({
    queryKey: ['myAuthorizations'],
    queryFn: () => getMyAuthorizations(token!),
    enabled: token !== null,
    retry: false,
  })

  const authFailed =
    authorizations.isError && [401, 403].includes((authorizations.error as { status?: number })?.status ?? 0)
  if (authFailed && token !== null) {
    clearTriageSession()
    setToken(null)
  }

  return (
    <div className="mx-auto min-h-screen max-w-3xl bg-slate-50 px-4 py-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">MediAssist AI</h1>
          <p className="text-sm text-slate-500">Insurance authorizations</p>
        </div>
        <nav className="flex items-center gap-3 text-sm">
          <Link to="/referrals" className="font-medium text-teal-700 hover:underline">
            Referrals
          </Link>
          <Link to="/schedule" className="font-medium text-teal-700 hover:underline">
            Book appointment →
          </Link>
        </nav>
      </header>

      {!token ? (
        <div className="mt-6 overflow-hidden rounded-xl border border-slate-200 bg-white">
          <TriageAccessGate onReady={setToken} />
        </div>
      ) : (
        <main className="mt-6 space-y-3">
          {authorizations.isPending && <p className="text-sm text-slate-400">Loading…</p>}
          {authorizations.isError && !authFailed && (
            <p className="text-sm text-amber-700">Couldn't load your authorizations — is the backend running?</p>
          )}
          {authorizations.data?.length === 0 && (
            <p className="rounded-xl border border-slate-200 bg-white p-6 text-center text-sm text-slate-500">
              No insurance authorizations on file.
            </p>
          )}

          {authorizations.data?.map((a) => {
            const copy = STATUS_COPY[a.status] ?? {
              label: a.status_display, next: '', tone: 'bg-slate-100 text-slate-700',
            }
            return (
              <article key={a.id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-semibold text-slate-900">
                    {a.treatment ?? a.order_type}
                  </p>
                  <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${copy.tone}`}>
                    {copy.label}
                  </span>
                </div>
                <p className="mt-2 text-sm text-slate-700">{copy.next}</p>
              </article>
            )
          })}
        </main>
      )}
    </div>
  )
}
