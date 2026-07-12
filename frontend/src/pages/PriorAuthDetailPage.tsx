import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import { getPatients } from '../lib/api'
import {
  getAuthorizationDetail,
  pollAuthorizationStatus,
  simulatePayerResponse,
  submitAuthorization,
  suggestAppeal,
} from '../lib/priorauthApi'
import type { AppealSuggestion } from '../lib/priorauthApi'

const STATUS_LABEL: Record<string, string> = {
  detected: 'Detected', gathering_evidence: 'Gathering evidence',
  ready_for_review: 'Ready for review', submitted: 'Submitted',
  under_review: 'Under review', info_requested: 'Info requested',
  approved: 'Approved', denied: 'Denied',
}

const EVIDENCE_CATEGORIES = ['diagnosis', 'physician_notes', 'labs', 'imaging_reports',
                             'medication_history', 'prior_treatments', 'allergies']

export default function PriorAuthDetailPage() {
  const { id } = useParams()
  const requestId = Number(id)
  const queryClient = useQueryClient()
  const [actionError, setActionError] = useState('')
  const [simulateStatus, setSimulateStatus] = useState('approved')
  const [simulateItems, setSimulateItems] = useState<string[]>([])
  const [appeal, setAppeal] = useState<AppealSuggestion | null>(null)

  const detail = useQuery({
    queryKey: ['authorizationDetail', requestId],
    queryFn: () => getAuthorizationDetail(requestId),
    refetchInterval: 15_000,
  })
  const patients = useQuery({ queryKey: ['patients'], queryFn: getPatients })

  const refresh = () => {
    setActionError('')
    void queryClient.invalidateQueries({ queryKey: ['authorizationDetail', requestId] })
    void queryClient.invalidateQueries({ queryKey: ['authorizationQueue'] })
  }
  const onError = (label: string) => () =>
    setActionError(`${label} didn't go through — please check and try again.`)

  const submit = useMutation({
    mutationFn: () => submitAuthorization(requestId),
    onSuccess: refresh, onError: onError('Submitting'),
  })
  const poll = useMutation({
    mutationFn: () => pollAuthorizationStatus(requestId),
    onSuccess: refresh, onError: onError('Checking status'),
  })
  const simulate = useMutation({
    mutationFn: () => simulatePayerResponse(requestId, {
      status: simulateStatus,
      ...(simulateStatus === 'denied' ? { denial_reason: 'Simulated denial for testing' } : {}),
      ...(simulateStatus === 'info_requested' ? { requested_items: simulateItems } : {}),
    }),
    onSuccess: refresh, onError: onError('Forcing the simulator response'),
  })
  const appealMutation = useMutation({
    mutationFn: () => suggestAppeal(requestId),
    onSuccess: (result) => { setAppeal(result); setActionError('') },
    onError: onError('Getting an appeal suggestion'),
  })

  const patientName = (pid: number) => {
    const p = patients.data?.find((p) => p.id === pid)
    return p ? `${p.first_name} ${p.last_name}` : `#${pid}`
  }

  if (detail.isPending) return <p className="p-6 text-sm text-slate-400">Loading…</p>
  if (detail.isError) {
    const forbidden = (detail.error as { status?: number })?.status === 403
    return (
      <div className="mx-auto max-w-2xl p-6">
        {forbidden ? (
          <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
            This page is for clinic staff. Log into the{' '}
            <a href="http://localhost:8001/admin/" target="_blank" rel="noreferrer"
               className="font-semibold underline">Django admin</a>{' '}
            with a staff account, then reload.
          </div>
        ) : (
          <p className="text-sm text-amber-700">Couldn't load this authorization request.</p>
        )}
      </div>
    )
  }

  const r = detail.data!
  const inFlight = ['submitted', 'under_review', 'info_requested'].includes(r.status)

  return (
    <div className="mx-auto min-h-screen max-w-3xl bg-slate-50 px-4 py-6">
      <Link to="/staff/priorauth" className="text-sm text-teal-700 hover:underline">
        ← All authorization requests
      </Link>

      <header className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-xl font-bold text-slate-900">
            {patientName(r.patient_id)} — {r.order_type}{r.treatment ? ` (${r.treatment})` : ''}
          </h1>
          {r.external_reference && (
            <p className="text-sm text-slate-500">Payer reference: {r.external_reference}</p>
          )}
        </div>
        <span className="rounded-full bg-slate-200 px-3 py-1 text-xs font-semibold text-slate-700">
          {STATUS_LABEL[r.status] ?? r.status}
        </span>
      </header>

      {/* -- AI reviewer summary + package, shown before submission -- */}
      {r.package && (
        <section className="mt-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-700">Authorization package</h2>
          {r.package.reviewer_summary && (
            <p className="mt-2 whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
              {r.package.reviewer_summary}
            </p>
          )}
          <dl className="mt-3 grid grid-cols-1 gap-2 text-xs sm:grid-cols-2">
            {EVIDENCE_CATEGORIES.filter((c) => (r.package!.evidence[c] as unknown[] | undefined)?.length)
              .map((category) => (
                <div key={category}>
                  <dt className="font-medium text-slate-500">{category.replace(/_/g, ' ')}</dt>
                  <dd className="text-slate-700">
                    {(r.package!.evidence[category] as unknown[])
                      .map((item) => (typeof item === 'string' ? item : JSON.stringify(item)))
                      .join('; ')}
                  </dd>
                </div>
              ))}
          </dl>
        </section>
      )}

      {actionError && (
        <p className="mt-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          {actionError}
        </p>
      )}

      {/* -- submit -- */}
      {r.status === 'ready_for_review' && (
        <section className="mt-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <button
            onClick={() => submit.mutate()}
            disabled={submit.isPending}
            className="rounded-lg bg-teal-600 px-4 py-2 text-sm font-semibold text-white
                       transition hover:bg-teal-700 disabled:opacity-40"
          >
            Submit to payer
          </button>
        </section>
      )}

      {/* -- in flight: check status + dev simulator -- */}
      {inFlight && (
        <section className="mt-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-700">Waiting on the payer</h2>
            <button
              onClick={() => poll.mutate()}
              disabled={poll.isPending}
              className="rounded-lg bg-teal-600 px-3 py-1.5 text-xs font-semibold text-white
                         transition hover:bg-teal-700 disabled:opacity-40"
            >
              Check status now
            </button>
          </div>

          <details className="mt-3 rounded-lg border border-dashed border-slate-300 p-3">
            <summary className="cursor-pointer text-xs font-medium text-slate-500">
              Dev: simulate the payer's next response
            </summary>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <select
                value={simulateStatus}
                onChange={(e) => setSimulateStatus(e.target.value)}
                className="rounded-md border border-slate-300 px-2 py-1 text-xs"
              >
                <option value="approved">approved</option>
                <option value="denied">denied</option>
                <option value="info_requested">info_requested</option>
                <option value="under_review">under_review</option>
              </select>
              {simulateStatus === 'info_requested' && (
                <div className="flex flex-wrap gap-2 text-xs">
                  {EVIDENCE_CATEGORIES.map((c) => (
                    <label key={c} className="flex items-center gap-1">
                      <input
                        type="checkbox"
                        checked={simulateItems.includes(c)}
                        onChange={(e) => setSimulateItems(
                          e.target.checked
                            ? [...simulateItems, c]
                            : simulateItems.filter((x) => x !== c),
                        )}
                      />
                      {c.replace(/_/g, ' ')}
                    </label>
                  ))}
                </div>
              )}
              <button
                onClick={() => simulate.mutate()}
                disabled={simulate.isPending}
                className="rounded-lg border border-teal-600 px-3 py-1 text-xs font-medium
                           text-teal-700 transition hover:bg-teal-50 disabled:opacity-40"
              >
                Force this response
              </button>
            </div>
            <p className="mt-1 text-[11px] text-slate-400">
              Sets what the simulator returns, then click "Check status now" to react to it.
            </p>
          </details>
        </section>
      )}

      {/* -- approved -- */}
      {r.status === 'approved' && (
        <p className="mt-4 rounded-lg border border-green-300 bg-green-50 p-4 text-sm text-green-900">
          🎉 Approved. The physician and patient have been notified — Scheduling can now book
          this treatment.
        </p>
      )}

      {/* -- denied + appeal suggestion -- */}
      {r.status === 'denied' && (
        <section className="mt-4 rounded-xl border border-red-300 bg-red-50 p-4">
          <p className="text-sm text-red-900">
            Denied{r.denial_reason ? `: ${r.denial_reason}` : ''}.
          </p>
          {!appeal ? (
            <button
              onClick={() => appealMutation.mutate()}
              disabled={appealMutation.isPending}
              className="mt-2 rounded-lg border border-red-600 px-3 py-1.5 text-xs font-semibold
                         text-red-700 transition hover:bg-red-100 disabled:opacity-40"
            >
              Suggest an appeal
            </button>
          ) : (
            <div className="mt-2 rounded-lg bg-white p-3 text-sm">
              <p className="font-medium text-slate-900">
                {appeal.should_appeal === true ? '👍 Worth appealing'
                  : appeal.should_appeal === false ? '👎 Not likely worth appealing'
                  : 'Suggestion unavailable'}
              </p>
              <p className="mt-1 text-slate-700">{appeal.recommendation}</p>
              {appeal.draft_argument && (
                <p className="mt-2 whitespace-pre-wrap rounded bg-slate-50 p-2 text-xs text-slate-600">
                  {appeal.draft_argument}
                </p>
              )}
              <p className="mt-2 text-[11px] text-slate-400">
                Suggestion only — review and submit any appeal yourself.
              </p>
            </div>
          )}
        </section>
      )}

      {/* -- timeline -- */}
      <section className="mt-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <h2 className="text-sm font-semibold text-slate-700">Timeline</h2>
        <ol className="mt-2 space-y-1">
          {r.status_history.map((entry, i) => (
            <li key={i} className="flex justify-between text-sm text-slate-600">
              <span>{STATUS_LABEL[entry.status] ?? entry.status}</span>
              <span className="text-xs text-slate-400">{new Date(entry.at).toLocaleString()}</span>
            </li>
          ))}
        </ol>
      </section>

      {/* -- payer message audit trail -- */}
      {r.messages.length > 0 && (
        <section className="mt-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-700">Payer messages</h2>
          <ul className="mt-2 space-y-2">
            {r.messages.map((m, i) => (
              <li key={i} className="text-sm">
                <span className={`mr-2 rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                  m.direction === 'outbound' ? 'bg-slate-200 text-slate-700' : 'bg-sky-100 text-sky-800'
                }`}>
                  {m.direction}
                </span>
                <span className="text-slate-700">{m.content}</span>
                <span className="ml-2 text-xs text-slate-400">
                  {new Date(m.created_at).toLocaleString()}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
