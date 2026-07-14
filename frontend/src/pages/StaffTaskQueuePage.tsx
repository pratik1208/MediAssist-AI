// Agent 9 Phase 5: the "human needed" queue (FR-A7), reusing the Agent 3
// escalation queue's layout and interaction pattern (PRD Screens #8).

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { claimStaffTask, getStaffTasks, resolveStaffTask } from '../lib/frontdeskApi'

const PRIORITY_STYLE: Record<string, string> = {
  critical: 'bg-red-600 text-white',
  high: 'bg-amber-500 text-white',
  normal: 'bg-slate-200 text-slate-700',
}

const STATUS_STYLE: Record<string, string> = {
  open: 'text-slate-500',
  claimed: 'text-teal-700',
  resolved: 'text-green-700',
}

export default function StaffTaskQueuePage() {
  const [showAll, setShowAll] = useState(false)
  const [claimingBy, setClaimingBy] = useState('')
  const queryClient = useQueryClient()

  const tasks = useQuery({
    queryKey: ['frontdesk-tasks', showAll],
    queryFn: () => getStaffTasks(showAll ? undefined : 'open'),
    refetchInterval: 15_000, // staff page: keep the queue fresh
  })

  const claim = useMutation({
    mutationFn: (id: number) => claimStaffTask(id, claimingBy.trim() || undefined),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['frontdesk-tasks'] }),
  })
  const resolve = useMutation({
    mutationFn: (id: number) => resolveStaffTask(id, claimingBy.trim() || undefined),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['frontdesk-tasks'] }),
  })

  const forbidden =
    tasks.isError && (tasks.error as { status?: number })?.status === 403

  return (
    <div className="mx-auto min-h-screen max-w-4xl bg-slate-50 px-4 py-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Front desk queue</h1>
          <p className="text-sm text-slate-500">
            Requests the front desk couldn't finish on its own
          </p>
        </div>
        <nav className="flex flex-wrap items-center justify-end gap-4 text-sm">
          <label className="flex items-center gap-1.5 text-slate-600">
            <input
              type="checkbox"
              checked={showAll}
              onChange={(e) => setShowAll(e.target.checked)}
            />
            Show resolved
          </label>
          <Link to="/staff/escalations" className="font-medium text-teal-700 hover:underline">
            Triage escalations →
          </Link>
          <Link to="/staff/caregaps" className="font-medium text-teal-700 hover:underline">
            Care gaps →
          </Link>
          <Link to="/" className="font-medium text-teal-700 hover:underline">
            Front desk chat →
          </Link>
        </nav>
      </header>

      <div className="mt-4">
        <label className="text-sm text-slate-600">
          Claiming as:{' '}
          <input
            value={claimingBy}
            onChange={(e) => setClaimingBy(e.target.value)}
            placeholder="your name (optional)"
            className="rounded-lg border border-slate-300 px-2 py-1 text-sm text-slate-900
                       focus:border-teal-600 focus:outline-none"
          />
        </label>
      </div>

      <main className="mt-4 space-y-3">
        {tasks.isPending && <p className="text-sm text-slate-400">Loading queue…</p>}

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
        {tasks.isError && !forbidden && (
          <p className="text-sm text-amber-700">
            Couldn't load the queue — is the backend running?
          </p>
        )}

        {tasks.data?.length === 0 && (
          <p className="rounded-xl border border-slate-200 bg-white p-6 text-center text-sm text-slate-500">
            No {showAll ? '' : 'open '}tasks — all clear. 🎉
          </p>
        )}

        {tasks.data?.map((task) => (
          <article
            key={task.id}
            className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                    PRIORITY_STYLE[task.priority] ?? 'bg-slate-200 text-slate-700'
                  }`}
                >
                  {task.priority}
                </span>
                <span className="text-sm font-semibold text-slate-900">
                  {task.category.replace(/_/g, ' ')}
                </span>
                {task.patient_name && (
                  <span className="text-xs text-slate-400">· {task.patient_name}</span>
                )}
                <span className={`text-xs font-medium ${STATUS_STYLE[task.status]}`}>
                  {task.status}
                  {task.claimed_by && task.status !== 'resolved' && ` · ${task.claimed_by}`}
                </span>
              </div>
              <div className="flex items-center gap-2">
                {task.status === 'open' && (
                  <button
                    onClick={() => claim.mutate(task.id)}
                    disabled={claim.isPending}
                    className="rounded-lg bg-teal-600 px-3 py-1.5 text-xs font-semibold text-white
                               transition hover:bg-teal-700 disabled:opacity-40"
                  >
                    Claim
                  </button>
                )}
                {task.status !== 'resolved' && (
                  <button
                    onClick={() => resolve.mutate(task.id)}
                    disabled={resolve.isPending}
                    className="rounded-lg border border-teal-600 px-3 py-1.5 text-xs font-semibold text-teal-700
                               transition hover:bg-teal-50 disabled:opacity-40"
                  >
                    Resolve
                  </button>
                )}
                {task.status === 'resolved' && task.resolved_at && (
                  <span className="text-xs text-green-700">
                    ✓ resolved · {new Date(task.resolved_at).toLocaleString()}
                  </span>
                )}
              </div>
            </div>
            <p className="mt-2 whitespace-pre-wrap text-sm text-slate-700">{task.summary}</p>
            {task.session_id && (
              <p className="mt-1 text-xs text-slate-400">Session #{task.session_id}</p>
            )}
          </article>
        ))}

        {(claim.isError || resolve.isError) && (
          <p className="text-sm text-amber-700">
            That didn't go through — make sure you're logged into the Django admin, then try again.
          </p>
        )}
      </main>
    </div>
  )
}
