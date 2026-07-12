import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { getPatients } from '../lib/api'
import { getStagedTasks } from '../lib/priorauthApi'
import { acknowledgeEscalation } from '../lib/triageApi'

const PRIORITY_STYLE: Record<string, string> = {
  high: 'bg-red-600 text-white',
  medium: 'bg-amber-500 text-white',
  low: 'bg-slate-200 text-slate-700',
}

export default function PriorAuthTasksPage() {
  const [showAll, setShowAll] = useState(false)
  const queryClient = useQueryClient()

  const tasks = useQuery({
    queryKey: ['priorauthTasks', showAll],
    queryFn: () => getStagedTasks(showAll ? 'all' : 'open'),
    refetchInterval: 15_000,
  })
  const patients = useQuery({ queryKey: ['patients'], queryFn: getPatients })

  const ack = useMutation({
    mutationFn: acknowledgeEscalation,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['priorauthTasks'] }),
  })

  const patientName = (id: number) => {
    const p = patients.data?.find((p) => p.id === id)
    return p ? `${p.first_name} ${p.last_name}` : `#${id}`
  }

  const forbidden = tasks.isError && (tasks.error as { status?: number })?.status === 403

  return (
    <div className="mx-auto min-h-screen max-w-4xl bg-slate-50 px-4 py-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Prior authorization tasks</h1>
          <p className="text-sm text-slate-500">
            Info-requests that couldn't be auto-answered — need a human to find the missing item
          </p>
        </div>
        <nav className="flex items-center gap-4 text-sm">
          <label className="flex items-center gap-1.5 text-slate-600">
            <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
            Show acknowledged
          </label>
          <Link to="/staff/priorauth" className="font-medium text-teal-700 hover:underline">
            Authorizations →
          </Link>
        </nav>
      </header>

      <main className="mt-6 space-y-3">
        {tasks.isPending && <p className="text-sm text-slate-400">Loading tasks…</p>}

        {forbidden && (
          <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
            This page is for clinic staff. Log into the{' '}
            <a href="http://localhost:8001/admin/" target="_blank" rel="noreferrer"
               className="font-semibold underline">Django admin</a>{' '}
            with a staff account in this browser, then reload this page.
          </div>
        )}
        {tasks.isError && !forbidden && (
          <p className="text-sm text-amber-700">Couldn't load tasks — is the backend running?</p>
        )}
        {tasks.data?.length === 0 && (
          <p className="rounded-xl border border-slate-200 bg-white p-6 text-center text-sm text-slate-500">
            No {showAll ? '' : 'open '}tasks — all clear. 🎉
          </p>
        )}

        {tasks.data?.map((task) => (
          <article key={task.id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                  PRIORITY_STYLE[task.priority] ?? 'bg-slate-200 text-slate-700'
                }`}>
                  {task.priority}
                </span>
                <span className="text-sm font-semibold text-slate-900">
                  {patientName(task.patient_id)}
                </span>
              </div>
              {task.status === 'open' ? (
                <button
                  onClick={() => ack.mutate(task.id)}
                  disabled={ack.isPending}
                  className="rounded-lg bg-teal-600 px-3 py-1.5 text-xs font-semibold text-white
                             transition hover:bg-teal-700 disabled:opacity-40"
                >
                  Acknowledge
                </button>
              ) : (
                <span className="text-xs text-green-700">
                  ✓ acknowledged
                  {task.acknowledged_at && ` · ${new Date(task.acknowledged_at).toLocaleString()}`}
                </span>
              )}
            </div>
            <p className="mt-2 whitespace-pre-wrap text-sm text-slate-700">{task.summary}</p>
          </article>
        ))}

        {ack.isError && (
          <p className="text-sm text-amber-700">
            Couldn't acknowledge — make sure you're logged into the Django admin, then try again.
          </p>
        )}
      </main>
    </div>
  )
}
