// Per-patient gap panel: what this patient is due for, their history of
// closed gaps (with evidence dates), and their care plans with the
// shared-visit vs. separate-appointment split. This is the surface front
// desk glances at during scheduling ("also due for a cholesterol
// screening") — Phase 6 wires it into the booking flow itself.

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import { bundleCarePlan, getPatientGaps, triggerScan } from '../lib/caregapsApi'
import type { PlanDetail, RiskTier } from '../lib/caregapsApi'

const RISK_STYLE: Record<RiskTier, string> = {
  high: 'bg-red-100 text-red-800',
  medium: 'bg-amber-100 text-amber-800',
  low: 'bg-slate-200 text-slate-700',
}

const PLAN_STATUS_STYLE: Record<PlanDetail['status'], string> = {
  draft: 'bg-slate-200 text-slate-700',
  sent: 'bg-sky-100 text-sky-800',
  accepted: 'bg-indigo-100 text-indigo-800',
  in_progress: 'bg-amber-100 text-amber-800',
  completed: 'bg-green-100 text-green-800',
  recycled: 'bg-orange-100 text-orange-800',
}

export default function PatientGapPanelPage() {
  const { id } = useParams<{ id: string }>()
  const patientId = Number(id)
  const queryClient = useQueryClient()
  const [actionResult, setActionResult] = useState('')

  const panel = useQuery({
    queryKey: ['patientGaps', patientId],
    queryFn: () => getPatientGaps(patientId),
    refetchInterval: 15_000,
  })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['patientGaps', patientId] })
    void queryClient.invalidateQueries({ queryKey: ['caregapMetrics'] })
    void queryClient.invalidateQueries({ queryKey: ['caregapWorklist'] })
  }

  const rescan = useMutation({
    mutationFn: () => triggerScan(patientId),
    onSuccess: (result) => {
      setActionResult(
        `Rescanned: ${result.opened} opened, ${result.refreshed} refreshed, ${result.closed} closed.`,
      )
      invalidate()
    },
    onError: () => setActionResult("Couldn't rescan this patient."),
  })

  const bundle = useMutation({
    mutationFn: () => bundleCarePlan(patientId),
    onSuccess: (plan) => {
      setActionResult(`Care plan #${plan.id} ready (${plan.gaps.length} item(s)).`)
      invalidate()
    },
    onError: (err) => {
      const body = (err as { body?: { error?: string } })?.body
      setActionResult(body?.error ?? "Couldn't bundle a care plan.")
    },
  })

  const forbidden = panel.isError && (panel.error as { status?: number })?.status === 403
  if (forbidden) {
    return (
      <div className="mx-auto min-h-screen max-w-4xl bg-slate-50 px-4 py-6">
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
          with a staff account, then reload.
        </div>
      </div>
    )
  }

  const p = panel.data

  return (
    <div className="mx-auto min-h-screen max-w-4xl bg-slate-50 px-4 py-6">
      <Link to="/staff/caregaps" className="text-sm font-medium text-teal-700 hover:underline">
        ← Care gap dashboard
      </Link>

      {panel.isPending && <p className="mt-4 text-sm text-slate-400">Loading…</p>}
      {panel.isError && !forbidden && (
        <p className="mt-4 text-sm text-red-600">Patient not found.</p>
      )}

      {p && (
        <>
          <header className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h1 className="text-xl font-bold text-slate-900">{p.patient_name}</h1>
              <p className="text-sm text-slate-500">
                {p.open_gaps.length} open gap{p.open_gaps.length === 1 ? '' : 's'} ·{' '}
                {p.closed_gaps.length} closed
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => rescan.mutate()}
                disabled={rescan.isPending}
                className="rounded-lg border border-slate-300 px-3 py-1 text-xs font-semibold
                           text-slate-700 transition hover:bg-slate-100 disabled:opacity-40"
              >
                Rescan
              </button>
              <button
                onClick={() => bundle.mutate()}
                disabled={bundle.isPending || p.open_gaps.length === 0}
                className="rounded-lg bg-teal-600 px-3 py-1 text-xs font-semibold text-white
                           transition hover:bg-teal-700 disabled:opacity-40"
              >
                Bundle into care plan
              </button>
            </div>
          </header>
          {actionResult && <p className="mt-2 text-sm text-teal-700">{actionResult}</p>}

          {/* open gaps */}
          <section className="mt-5">
            <h2 className="text-sm font-semibold text-slate-900">Due now</h2>
            <div className="mt-2 space-y-1.5">
              {p.open_gaps.map((gap) => (
                <div
                  key={gap.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border
                             border-slate-200 bg-white px-4 py-2 text-sm shadow-sm"
                >
                  <div className="flex items-center gap-2">
                    <span
                      className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${RISK_STYLE[gap.risk_tier]}`}
                    >
                      {gap.risk_tier}
                    </span>
                    <span className="font-medium text-slate-900">{gap.guideline_name}</span>
                    <span className="text-xs text-slate-400">{gap.care_item_type}</span>
                  </div>
                  <span className="text-xs text-slate-500">
                    {gap.status} · overdue{' '}
                    <span className="font-semibold text-slate-900">{gap.days_overdue}</span> day
                    {gap.days_overdue === 1 ? '' : 's'}
                  </span>
                </div>
              ))}
              {p.open_gaps.length === 0 && (
                <p className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-500">
                  Nothing due — this patient is up to date. 🎉
                </p>
              )}
            </div>
          </section>

          {/* care plans */}
          <section className="mt-5">
            <h2 className="text-sm font-semibold text-slate-900">Care plans</h2>
            <div className="mt-2 space-y-2">
              {p.care_plans.map((plan) => (
                <div
                  key={plan.id}
                  className="rounded-lg border border-slate-200 bg-white p-4 text-sm shadow-sm"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium text-slate-900">Plan #{plan.id}</span>
                    <span
                      className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${PLAN_STATUS_STYLE[plan.status]}`}
                    >
                      {plan.status}
                    </span>
                  </div>
                  {plan.plan_text && (
                    <p className="mt-2 rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
                      {plan.plan_text}
                    </p>
                  )}
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {plan.gaps.map((gap) => (
                      <span
                        key={gap.id}
                        className={`rounded-full px-2 py-0.5 text-[11px] ${
                          gap.status === 'closed'
                            ? 'bg-green-100 text-green-800 line-through'
                            : plan.shared_visit_gap_ids.includes(gap.id)
                              ? 'bg-teal-50 text-teal-800'
                              : 'bg-slate-100 text-slate-700'
                        }`}
                        title={
                          gap.status === 'closed'
                            ? 'done'
                            : plan.shared_visit_gap_ids.includes(gap.id)
                              ? 'can share one visit'
                              : 'needs its own appointment'
                        }
                      >
                        {gap.guideline_name}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
              {p.care_plans.length === 0 && (
                <p className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-500">
                  No care plans yet — bundle the open gaps to create one.
                </p>
              )}
            </div>
          </section>

          {/* closed history */}
          {p.closed_gaps.length > 0 && (
            <section className="mt-5">
              <h2 className="text-sm font-semibold text-slate-900">Completed</h2>
              <div className="mt-2 space-y-1.5">
                {p.closed_gaps.map((gap) => (
                  <div
                    key={gap.id}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-lg
                               border border-slate-200 bg-white px-4 py-2 text-sm opacity-70"
                  >
                    <span className="text-slate-700">{gap.guideline_name}</span>
                    <span className="text-xs text-slate-500">
                      closed{' '}
                      {gap.closed_at ? new Date(gap.closed_at).toLocaleDateString() : ''}
                    </span>
                  </div>
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </div>
  )
}
