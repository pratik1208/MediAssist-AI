// Population health / care gap dashboard (PRD Screen #6): open gaps by
// guideline, closure rate, the care-plan funnel, per-provider quality view,
// and the risk-prioritized worklist. "Closure rate trend" needs a metrics
// history the backend doesn't record yet, so this shows the live rate.

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { getGapWorklist, getQualityMetrics, triggerScan } from '../lib/caregapsApi'
import type { GapStatus, RiskTier } from '../lib/caregapsApi'

const RISK_STYLE: Record<RiskTier, string> = {
  high: 'bg-red-100 text-red-800',
  medium: 'bg-amber-100 text-amber-800',
  low: 'bg-slate-200 text-slate-700',
}

const STATUS_OPTIONS: GapStatus[] = ['open', 'outreach', 'scheduled', 'completed', 'closed']

const PLAN_FUNNEL: { key: string; label: string }[] = [
  { key: 'draft', label: 'Draft' },
  { key: 'sent', label: 'Sent' },
  { key: 'accepted', label: 'Accepted' },
  { key: 'in_progress', label: 'In progress' },
  { key: 'completed', label: 'Completed' },
  { key: 'recycled', label: 'Recycled' },
]

export default function CareGapDashboardPage() {
  const [statusFilter, setStatusFilter] = useState<GapStatus>('open')
  const [scanResult, setScanResult] = useState('')
  const queryClient = useQueryClient()

  const metrics = useQuery({
    queryKey: ['caregapMetrics'],
    queryFn: getQualityMetrics,
    refetchInterval: 15_000,
  })
  const worklist = useQuery({
    queryKey: ['caregapWorklist', statusFilter],
    queryFn: () => getGapWorklist(statusFilter),
    refetchInterval: 15_000,
  })

  const scan = useMutation({
    mutationFn: () => triggerScan(),
    onSuccess: (result) => {
      setScanResult(
        `Scanned ${result.patients_scanned ?? 0} patient(s): ${result.opened} opened, ` +
          `${result.refreshed} refreshed, ${result.closed} closed on evidence.`,
      )
      void queryClient.invalidateQueries({ queryKey: ['caregapMetrics'] })
      void queryClient.invalidateQueries({ queryKey: ['caregapWorklist'] })
    },
    onError: () => setScanResult("Couldn't run the scan."),
  })

  const forbidden = metrics.isError && (metrics.error as { status?: number })?.status === 403
  if (forbidden) {
    return (
      <div className="mx-auto min-h-screen max-w-5xl bg-slate-50 px-4 py-6">
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

  const m = metrics.data
  const maxGuideline = m
    ? Math.max(...m.gaps.by_guideline.map((g) => g.open_gaps + g.closed_gaps), 1)
    : 1

  return (
    <div className="mx-auto min-h-screen max-w-5xl bg-slate-50 px-4 py-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Care gaps — population health</h1>
          <p className="text-sm text-slate-500">
            Preventive care the panel is due for, prioritized by risk.
          </p>
        </div>
        <button
          onClick={() => scan.mutate()}
          disabled={scan.isPending}
          className="rounded-lg bg-teal-600 px-4 py-2 text-sm font-semibold text-white
                     transition hover:bg-teal-700 disabled:opacity-40"
        >
          {scan.isPending ? 'Scanning…' : 'Run scan now'}
        </button>
      </header>
      {scanResult && <p className="mt-2 text-sm text-teal-700">{scanResult}</p>}

      {metrics.isPending && <p className="mt-4 text-sm text-slate-400">Loading…</p>}

      {m && (
        <>
          {/* headline numbers */}
          <section className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              { label: 'Open gaps', value: m.gaps.open },
              { label: 'Closed gaps', value: m.gaps.closed },
              { label: 'Closure rate', value: `${(m.gaps.closure_rate * 100).toFixed(1)}%` },
              {
                label: 'Plan completion',
                value: `${(m.care_plans.completion_rate * 100).toFixed(1)}%`,
              },
            ].map((card) => (
              <div
                key={card.label}
                className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
              >
                <p className="text-xs text-slate-500">{card.label}</p>
                <p className="mt-1 text-2xl font-bold text-slate-900">{card.value}</p>
              </div>
            ))}
          </section>

          {/* open gaps by guideline */}
          <section className="mt-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="text-sm font-semibold text-slate-900">Gaps by guideline</h2>
            <div className="mt-3 space-y-2">
              {m.gaps.by_guideline.map((g) => (
                <div key={g.guideline_id} className="flex items-center gap-3">
                  <span className="w-64 shrink-0 truncate text-xs text-slate-600">
                    {g.guideline_name}
                  </span>
                  <span
                    className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${RISK_STYLE[g.risk_tier]}`}
                  >
                    {g.risk_tier}
                  </span>
                  <div className="flex h-5 flex-1 overflow-hidden rounded bg-slate-100">
                    <div
                      className="h-full bg-teal-500"
                      style={{ width: `${(g.open_gaps / maxGuideline) * 100}%` }}
                      title={`${g.open_gaps} open`}
                    />
                    <div
                      className="h-full bg-slate-300"
                      style={{ width: `${(g.closed_gaps / maxGuideline) * 100}%` }}
                      title={`${g.closed_gaps} closed`}
                    />
                  </div>
                  <span className="w-20 shrink-0 text-right text-xs text-slate-500">
                    <span className="font-semibold text-slate-900">{g.open_gaps}</span> open ·{' '}
                    {g.closed_gaps} closed
                  </span>
                </div>
              ))}
              {m.gaps.by_guideline.length === 0 && (
                <p className="text-sm text-slate-400">No guidelines seeded yet.</p>
              )}
            </div>
          </section>

          <div className="mt-4 grid gap-4 md:grid-cols-2">
            {/* care plan funnel */}
            <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-slate-900">Care plans</h2>
                <span className="text-xs text-slate-500">
                  Response:{' '}
                  <span className="font-semibold text-teal-700">
                    {(m.care_plans.response_rate * 100).toFixed(1)}%
                  </span>
                </span>
              </div>
              <div className="mt-2 grid grid-cols-3 gap-2">
                {PLAN_FUNNEL.map((step) => (
                  <div key={step.key} className="rounded-lg bg-slate-50 px-2 py-1.5 text-center">
                    <p className="text-lg font-bold text-slate-900">
                      {m.care_plans.by_status[step.key as keyof typeof m.care_plans.by_status] ?? 0}
                    </p>
                    <p className="text-[10px] text-slate-500">{step.label}</p>
                  </div>
                ))}
              </div>
            </section>

            {/* per-provider quality */}
            <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <h2 className="text-sm font-semibold text-slate-900">Per-provider closure</h2>
              <p className="mt-0.5 text-[11px] text-slate-400">
                By the patient's most recent completed visit's doctor.
              </p>
              <div className="mt-2 space-y-1">
                {m.per_provider.map((row) => (
                  <div key={row.provider} className="flex items-center justify-between text-sm">
                    <span className="truncate text-slate-700">{row.provider}</span>
                    <span className="shrink-0 text-xs text-slate-500">
                      {row.open_gaps} open · {row.closed_gaps} closed ·{' '}
                      <span className="font-semibold text-slate-900">
                        {(row.closure_rate * 100).toFixed(0)}%
                      </span>
                    </span>
                  </div>
                ))}
                {m.per_provider.length === 0 && (
                  <p className="text-sm text-slate-400">No gaps recorded yet.</p>
                )}
              </div>
            </section>
          </div>
        </>
      )}

      {/* risk-prioritized worklist */}
      <section className="mt-5">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-900">
            Prioritized worklist{worklist.data ? ` (${worklist.data.length})` : ''}
          </h2>
          <div className="flex gap-1">
            {STATUS_OPTIONS.map((s) => (
              <button
                key={s}
                onClick={() => setStatusFilter(s)}
                className={`rounded-full px-2.5 py-0.5 text-xs font-medium transition ${
                  statusFilter === s
                    ? 'bg-teal-600 text-white'
                    : 'bg-white text-slate-600 hover:bg-slate-100'
                }`}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
        <div className="mt-2 space-y-1.5">
          {worklist.data?.map((gap) => (
            <Link
              key={gap.id}
              to={`/staff/caregaps/patients/${gap.patient_id}`}
              className="flex flex-wrap items-center justify-between gap-2 rounded-lg border
                         border-slate-200 bg-white px-4 py-2 text-sm shadow-sm transition
                         hover:border-teal-300"
            >
              <div className="flex items-center gap-2">
                <span
                  className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${RISK_STYLE[gap.risk_tier]}`}
                >
                  {gap.risk_tier}
                </span>
                <span className="font-medium text-slate-900">{gap.patient_name}</span>
                <span className="text-xs text-slate-500">{gap.guideline_name}</span>
              </div>
              <span className="text-xs text-slate-500">
                {gap.status === 'closed' ? (
                  <>closed {gap.closed_at ? new Date(gap.closed_at).toLocaleDateString() : ''}</>
                ) : (
                  <>
                    overdue{' '}
                    <span className="font-semibold text-slate-900">{gap.days_overdue}</span> day
                    {gap.days_overdue === 1 ? '' : 's'}
                  </>
                )}
              </span>
            </Link>
          ))}
          {worklist.data?.length === 0 && (
            <p className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-500">
              No {statusFilter} gaps — run a scan or pick another status.
            </p>
          )}
        </div>
      </section>
    </div>
  )
}
