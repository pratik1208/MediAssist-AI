import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { getPatients } from '../lib/api'
import { acknowledgeEscalation, getEscalations } from '../lib/triageApi'

const PRIORITY_STYLE: Record<string, string> = {
  critical: 'bg-red-600 text-white',
  immediate: 'bg-red-600 text-white',
  urgent: 'bg-amber-500 text-white',
  high: 'bg-amber-500 text-white',
  routine: 'bg-slate-200 text-slate-700',
}

export default function EscalationQueuePage() {
  const [showAll, setShowAll] = useState(false)
  const queryClient = useQueryClient()

  const alerts = useQuery({
    queryKey: ['escalations', showAll],
    queryFn: () => getEscalations(showAll ? undefined : 'open'),
    refetchInterval: 15_000, // staff page: keep the queue fresh
  })
  const patients = useQuery({ queryKey: ['patients'], queryFn: getPatients })

  const ack = useMutation({
    mutationFn: acknowledgeEscalation,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['escalations'] }),
  })

  const contactFor = (patientId: number) =>
    patients.data?.find((p) => p.id === patientId)?.contact_number ?? '—'

  const forbidden =
    alerts.isError && (alerts.error as { status?: number })?.status === 403

  return (
    <div className="mx-auto min-h-screen max-w-4xl bg-slate-50 px-4 py-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Escalation queue</h1>
          <p className="text-sm text-slate-500">
            Triage and refill alerts needing clinician attention
          </p>
        </div>
        <nav className="flex items-center gap-4 text-sm">
          <label className="flex items-center gap-1.5 text-slate-600">
            <input
              type="checkbox"
              checked={showAll}
              onChange={(e) => setShowAll(e.target.checked)}
            />
            Show acknowledged
          </label>
          <Link to="/triage" className="font-medium text-teal-700 hover:underline">
            Patient triage →
          </Link>
        </nav>
      </header>

      <main className="mt-6 space-y-3">
        {alerts.isPending && <p className="text-sm text-slate-400">Loading alerts…</p>}

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
        {alerts.isError && !forbidden && (
          <p className="text-sm text-amber-700">
            Couldn't load the queue — is the backend running?
          </p>
        )}

        {alerts.data?.length === 0 && (
          <p className="rounded-xl border border-slate-200 bg-white p-6 text-center text-sm text-slate-500">
            No {showAll ? '' : 'open '}alerts — all clear. 🎉
          </p>
        )}

        {alerts.data?.map((alert) => (
          <article
            key={alert.id}
            className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span
                  className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                    PRIORITY_STYLE[alert.priority] ?? 'bg-slate-200 text-slate-700'
                  }`}
                >
                  {alert.priority}
                </span>
                <span className="text-sm font-semibold text-slate-900">
                  {alert.patient_name}
                </span>
                <span className="text-xs text-slate-400">
                  📞 {contactFor(alert.patient_id)}
                </span>
                <span className="text-xs text-slate-400">
                  · {alert.category.replace(/_/g, ' ')}
                </span>
              </div>
              {alert.status === 'open' ? (
                <button
                  onClick={() => ack.mutate(alert.id)}
                  disabled={ack.isPending}
                  className="rounded-lg bg-teal-600 px-3 py-1.5 text-xs font-semibold text-white
                             transition hover:bg-teal-700 disabled:opacity-40"
                >
                  Acknowledge
                </button>
              ) : (
                <span className="text-xs text-green-700">
                  ✓ acknowledged
                  {alert.acknowledged_at &&
                    ` · ${new Date(alert.acknowledged_at).toLocaleString()}`}
                </span>
              )}
            </div>
            <p className="mt-2 whitespace-pre-wrap text-sm text-slate-700">
              {alert.summary}
            </p>
            {alert.assessment_id && (
              <p className="mt-1 text-xs text-slate-400">
                Assessment #{alert.assessment_id}
              </p>
            )}
          </article>
        ))}

        {ack.isError && (
          <p className="text-sm text-amber-700">
            Couldn't acknowledge — make sure you're logged into the Django admin,
            then try again.
          </p>
        )}
      </main>
    </div>
  )
}
