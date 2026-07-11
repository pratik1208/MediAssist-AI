import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import {
  approveRefill,
  getRefillQueue,
  rejectRefill,
  requestVisit,
} from '../lib/refillsApi'
import type { RefillQueueEntry } from '../lib/refillsApi'

/** Structured renewal data (FR-M5) beside the AI summary. */
function SummaryFacts({ entry }: { entry: RefillQueueEntry }) {
  const s = entry.renewal_summary ?? {}
  const facts: [string, string][] = []
  if (s.last_prescribed) facts.push(['Last prescribed', s.last_prescribed])
  if (s.refills_remaining !== undefined)
    facts.push(['Refills remaining', String(s.refills_remaining)])
  if (s.adherence !== undefined && s.adherence !== null)
    facts.push(['Adherence', String(s.adherence)])
  if (s.allergies?.length) facts.push(['Allergies', s.allergies.join(', ')])
  if (s.recent_labs?.length)
    facts.push([
      'Recent labs',
      s.recent_labs
        .map((lab) => [lab.test, lab.date, lab.findings].filter(Boolean).join(' — '))
        .join('; '),
    ])
  if (facts.length === 0) return null
  return (
    <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs text-slate-600">
      {facts.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="font-medium text-slate-500">{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  )
}

export default function RefillQueuePage() {
  // Entry id whose inline reject-reason box is open.
  const [rejectingId, setRejectingId] = useState<number | null>(null)
  const [reason, setReason] = useState('')
  const [actionError, setActionError] = useState('')
  const queryClient = useQueryClient()

  const queue = useQuery({
    queryKey: ['refillQueue'],
    queryFn: getRefillQueue,
    refetchInterval: 15_000, // staff page: keep the queue fresh
  })

  const refresh = () => {
    setRejectingId(null)
    setReason('')
    setActionError('')
    void queryClient.invalidateQueries({ queryKey: ['refillQueue'] })
  }
  const onError = () =>
    setActionError(
      "That action didn't go through — make sure you're logged into the Django admin, then try again.",
    )

  const approve = useMutation({ mutationFn: approveRefill, onSuccess: refresh, onError })
  const reject = useMutation({
    mutationFn: ({ id, why }: { id: number; why: string }) => rejectRefill(id, why),
    onSuccess: refresh,
    onError,
  })
  const visit = useMutation({ mutationFn: requestVisit, onSuccess: refresh, onError })
  const busy = approve.isPending || reject.isPending || visit.isPending

  const forbidden =
    queue.isError && (queue.error as { status?: number })?.status === 403

  return (
    <div className="mx-auto min-h-screen max-w-4xl bg-slate-50 px-4 py-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Refill approvals</h1>
          <p className="text-sm text-slate-500">
            Renewal requests awaiting a physician decision
          </p>
        </div>
        <Link to="/staff/escalations" className="text-sm font-medium text-teal-700 hover:underline">
          Escalation queue →
        </Link>
      </header>

      <main className="mt-6 space-y-3">
        {queue.isPending && <p className="text-sm text-slate-400">Loading queue…</p>}

        {forbidden && (
          <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
            This page is for clinic staff. Log into the{' '}
            <a
              href="http://localhost:8001/admin/"
              target="_blank"
              rel="noreferrer"
              className="font-semibold underline"
            >
              Django admin
            </a>{' '}
            with a staff account in this browser, then reload this page.
          </div>
        )}
        {queue.isError && !forbidden && (
          <p className="text-sm text-amber-700">
            Couldn't load the queue — is the backend running?
          </p>
        )}

        {queue.data?.length === 0 && (
          <p className="rounded-xl border border-slate-200 bg-white p-6 text-center text-sm text-slate-500">
            No refills waiting for approval. 🎉
          </p>
        )}

        {queue.data?.map((entry) => (
          <article
            key={entry.id}
            className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-slate-900">{entry.patient}</span>
                <span className="text-sm text-slate-700">· {entry.medication}</span>
                {entry.controlled_substance && (
                  <span className="rounded-full bg-red-100 px-2 py-0.5 text-[11px] font-semibold text-red-800">
                    controlled substance
                  </span>
                )}
                <span className="text-xs text-slate-400">
                  requested {new Date(entry.requested_at).toLocaleString()}
                </span>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => approve.mutate(entry.id)}
                  disabled={busy}
                  className="rounded-lg bg-teal-600 px-3 py-1.5 text-xs font-semibold text-white
                             transition hover:bg-teal-700 disabled:opacity-40"
                >
                  Approve
                </button>
                <button
                  onClick={() => {
                    setRejectingId(rejectingId === entry.id ? null : entry.id)
                    setReason('')
                  }}
                  disabled={busy}
                  className="rounded-lg border border-red-300 px-3 py-1.5 text-xs font-semibold
                             text-red-700 transition hover:bg-red-50 disabled:opacity-40"
                >
                  Reject
                </button>
                <button
                  onClick={() => visit.mutate(entry.id)}
                  disabled={busy}
                  className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-semibold
                             text-slate-700 transition hover:bg-slate-100 disabled:opacity-40"
                >
                  Request visit
                </button>
              </div>
            </div>

            {entry.summary_text && (
              <p className="mt-2 whitespace-pre-wrap text-sm text-slate-700">
                {entry.summary_text}
              </p>
            )}
            <SummaryFacts entry={entry} />

            {rejectingId === entry.id && (
              <form
                className="mt-3 flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault()
                  if (reason.trim()) reject.mutate({ id: entry.id, why: reason.trim() })
                }}
              >
                <input
                  autoFocus
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="Reason for rejecting (shared with the patient)…"
                  className="flex-1 rounded-lg border border-slate-300 px-3 py-1.5 text-sm
                             text-slate-900 focus:border-teal-600 focus:outline-none"
                />
                <button
                  type="submit"
                  disabled={busy || reason.trim() === ''}
                  className="rounded-lg bg-red-600 px-3 py-1.5 text-xs font-semibold text-white
                             transition hover:bg-red-700 disabled:opacity-40"
                >
                  Confirm reject
                </button>
              </form>
            )}
          </article>
        ))}

        {actionError && <p className="text-sm text-amber-700">{actionError}</p>}
      </main>
    </div>
  )
}
