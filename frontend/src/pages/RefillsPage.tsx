import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'

import TriageAccessGate from '../components/TriageAccessGate'
import {
  createRefillRequest,
  getPharmacies,
  getPrescriptions,
  getRefillStatus,
} from '../lib/refillsApi'
import type { RefillStatus } from '../lib/refillsApi'
import {
  clearTriageSession,
  registrationSessionToken,
  triageSessionToken,
} from '../lib/session'

const REQUEST_KEY = 'mediassist.refill.request'

// The happy path shown as progress chips (plan: requested → checking →
// with your doctor → sent to pharmacy → ready).
const STEPS: { label: string; statuses: RefillStatus[] }[] = [
  { label: 'Requested', statuses: ['received'] },
  { label: 'Checking', statuses: ['eligibility_check'] },
  { label: 'With your doctor', statuses: ['pending_approval'] },
  { label: 'Sent to pharmacy', statuses: ['approved', 'sent_to_pharmacy'] },
  { label: 'Ready for pickup', statuses: ['ready_for_pickup'] },
]

const TERMINAL: RefillStatus[] = ['ready_for_pickup', 'rejected', 'paused', 'visit_required']

function savedRequestId(): number | null {
  const raw = sessionStorage.getItem(REQUEST_KEY)
  if (!raw) return null
  const id = Number(JSON.parse(raw).id)
  return Number.isFinite(id) ? id : null
}

export default function RefillsPage() {
  const [token, setToken] = useState<string | null>(
    () => triageSessionToken() ?? registrationSessionToken(),
  )
  const [requestId, setRequestId] = useState<number | null>(savedRequestId)
  // Prescription id waiting on a pharmacy choice (backend answered 400).
  const [needsPharmacyFor, setNeedsPharmacyFor] = useState<number | null>(null)
  const [error, setError] = useState('')
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  useEffect(() => {
    if (requestId !== null) {
      sessionStorage.setItem(REQUEST_KEY, JSON.stringify({ id: requestId }))
    } else {
      sessionStorage.removeItem(REQUEST_KEY)
    }
  }, [requestId])

  const prescriptions = useQuery({
    queryKey: ['prescriptions'],
    queryFn: () => getPrescriptions(token!),
    enabled: token !== null,
    retry: false,
  })

  const pharmacies = useQuery({
    queryKey: ['pharmacies'],
    queryFn: getPharmacies,
    enabled: needsPharmacyFor !== null,
  })

  const status = useQuery({
    queryKey: ['refillStatus', requestId],
    queryFn: () => getRefillStatus(token!, requestId!),
    enabled: token !== null && requestId !== null,
    // Poll while the request is moving through the pipeline.
    refetchInterval: (query) =>
      query.state.data && TERMINAL.includes(query.state.data.status) ? false : 10_000,
    retry: false,
  })

  // A stale session token means every patient call 401/403s — back to sign-in.
  const authFailed = [prescriptions, status].some(
    (q) => q.isError && [401, 403].includes((q.error as { status?: number })?.status ?? 0),
  )
  useEffect(() => {
    if (authFailed) {
      clearTriageSession()
      setToken(null)
    }
  }, [authFailed])

  const requestRefill = useMutation({
    mutationFn: ({ rxId, pharmacyId }: { rxId: number; pharmacyId?: number }) =>
      createRefillRequest(token!, rxId, pharmacyId),
    onSuccess: (created) => {
      setError('')
      setNeedsPharmacyFor(null)
      setRequestId(created.id)
      void queryClient.invalidateQueries({ queryKey: ['prescriptions'] })
    },
    onError: (err, variables) => {
      const e = err as { status?: number; body?: { id?: number; code?: string; reason?: string } }
      if (e.status === 409 && e.body?.id) {
        // Two reasons land here: the request was created but paused (the
        // status card explains why), or one was already in flight for this
        // prescription (code "already_requested") — either way, jump to
        // that request's status card instead of starting a duplicate.
        setNeedsPharmacyFor(null)
        setError(
          e.body.code === 'already_requested'
            ? 'You already have a refill request in progress for this medication.'
            : '',
        )
        setRequestId(e.body.id)
      } else if (e.status === 400) {
        setNeedsPharmacyFor(variables.rxId) // no pharmacy on file — ask
      } else {
        setError("Couldn't start the refill — please try again.")
      }
    },
  })

  const bookVisit = () => {
    const medication = status.data?.medication ?? 'my medication'
    navigate('/schedule', {
      state: {
        prefill: `My doctor asked to see me before renewing my ${medication} refill — can I get an appointment this week?`,
      },
    })
  }

  const stepIndex = status.data
    ? STEPS.findIndex((s) => s.statuses.includes(status.data.status))
    : -1

  return (
    <div className="mx-auto min-h-screen max-w-3xl bg-slate-50 px-4 py-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">MediAssist AI</h1>
          <p className="text-sm text-slate-500">Prescription refills</p>
        </div>
        <nav className="flex items-center gap-3 text-sm">
          <Link to="/triage" className="font-medium text-teal-700 hover:underline">
            Symptom check
          </Link>
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
        <main className="mt-6 space-y-4">
          {/* ---- active request status card ---- */}
          {requestId !== null && status.data && (
            <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-slate-900">
                  Refill request — {status.data.medication}
                </h2>
                <button
                  onClick={() => setRequestId(null)}
                  className="text-xs text-slate-500 hover:text-teal-700"
                >
                  Start another refill
                </button>
              </div>

              {stepIndex >= 0 && (
                <ol className="mt-4 flex flex-wrap items-center gap-2">
                  {STEPS.map((step, i) => (
                    <li key={step.label} className="flex items-center gap-2">
                      <span
                        className={`rounded-full px-3 py-1 text-xs font-medium ${
                          i < stepIndex
                            ? 'bg-teal-100 text-teal-800'
                            : i === stepIndex
                              ? 'bg-teal-600 text-white'
                              : 'bg-slate-100 text-slate-400'
                        }`}
                      >
                        {i < stepIndex ? '✓ ' : ''}
                        {step.label}
                      </span>
                      {i < STEPS.length - 1 && <span className="text-slate-300">→</span>}
                    </li>
                  ))}
                </ol>
              )}

              {status.data.status === 'ready_for_pickup' && (
                <p className="mt-3 rounded-lg border border-green-300 bg-green-50 px-3 py-2 text-sm text-green-900">
                  🎉 Your refill is ready for pickup at your pharmacy.
                </p>
              )}
              {status.data.status === 'paused' && (
                <p className="mt-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                  This request is paused: {status.data.pause_reason ?? 'a staff member will review it'}.
                  The clinic will follow up — no action needed right now.
                </p>
              )}
              {status.data.status === 'rejected' && (
                <p className="mt-3 rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-900">
                  Your doctor declined this refill
                  {status.data.pause_reason ? `: ${status.data.pause_reason}` : ''}. Please
                  contact the clinic if you have questions.
                </p>
              )}
              {status.data.status === 'visit_required' && (
                <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                  Your doctor wants to see you before renewing this prescription.
                  <button
                    onClick={bookVisit}
                    className="ml-2 rounded-lg bg-teal-600 px-3 py-1 text-xs font-semibold text-white
                               transition hover:bg-teal-700"
                  >
                    Book a visit →
                  </button>
                </div>
              )}
            </section>
          )}

          {/* ---- prescriptions ---- */}
          <section>
            <h2 className="text-sm font-semibold text-slate-700">Your active prescriptions</h2>
            {prescriptions.isPending && (
              <p className="mt-2 text-sm text-slate-400">Loading prescriptions…</p>
            )}
            {prescriptions.isError && !authFailed && (
              <p className="mt-2 text-sm text-amber-700">
                Couldn't load your prescriptions — is the backend running?
              </p>
            )}
            {prescriptions.data?.length === 0 && (
              <p className="mt-2 rounded-xl border border-slate-200 bg-white p-6 text-center text-sm text-slate-500">
                No active prescriptions on file. If that seems wrong, please contact the clinic.
              </p>
            )}

            <div className="mt-2 space-y-2">
              {prescriptions.data?.map((rx) => (
                <article
                  key={rx.id}
                  className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <p className="text-sm font-semibold text-slate-900">{rx.medication}</p>
                      <p className="text-xs text-slate-500">
                        Qty {rx.quantity} · {rx.refills_remaining} refill
                        {rx.refills_remaining === 1 ? '' : 's'} remaining
                        {rx.controlled_substance && (
                          <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800">
                            controlled — doctor review required
                          </span>
                        )}
                      </p>
                    </div>
                    <button
                      onClick={() => requestRefill.mutate({ rxId: rx.id })}
                      disabled={requestRefill.isPending}
                      className="rounded-lg bg-teal-600 px-3 py-1.5 text-xs font-semibold text-white
                                 transition hover:bg-teal-700 disabled:opacity-40"
                    >
                      Request refill
                    </button>
                  </div>

                  {needsPharmacyFor === rx.id && (
                    <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
                      <p className="text-slate-700">
                        We don't have a pharmacy on file for you — pick one:
                      </p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {pharmacies.data?.map((ph) => (
                          <button
                            key={ph.id}
                            onClick={() =>
                              requestRefill.mutate({ rxId: rx.id, pharmacyId: ph.id })
                            }
                            disabled={requestRefill.isPending}
                            className="rounded-lg border border-teal-600 px-3 py-1 text-xs
                                       font-medium text-teal-700 transition hover:bg-teal-50
                                       disabled:opacity-40"
                          >
                            {ph.name}
                          </button>
                        ))}
                        {pharmacies.isPending && (
                          <span className="text-xs text-slate-400">Loading pharmacies…</span>
                        )}
                        {pharmacies.data?.length === 0 && (
                          <span className="text-xs text-amber-700">
                            No pharmacies configured — please contact the clinic.
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                </article>
              ))}
            </div>
          </section>

          {error && <p className="text-sm text-amber-700">{error}</p>}
        </main>
      )}
    </div>
  )
}
