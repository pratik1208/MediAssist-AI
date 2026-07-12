import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import {
  createCampaign,
  getCampaigns,
  launchCampaign,
  pauseCampaign,
  previewCohort,
} from '../lib/outreachApi'
import type { CampaignStatus } from '../lib/outreachApi'

const STATUS_STYLE: Record<CampaignStatus, string> = {
  draft: 'bg-slate-200 text-slate-700',
  running: 'bg-green-100 text-green-800',
  paused: 'bg-amber-100 text-amber-800',
  completed: 'bg-sky-100 text-sky-800',
}

const DEFAULT_CRITERIA = JSON.stringify({ age_min: 65 }, null, 2)
const DEFAULT_PLAN = JSON.stringify(
  [
    { channel: 'sms', wait_days: 0 },
    { channel: 'email', wait_days: 3 },
    { channel: 'voice', wait_days: 7 },
  ],
  null,
  2,
)

export default function CampaignManagerPage() {
  const [showForm, setShowForm] = useState(false)
  const [name, setName] = useState('')
  const [goal, setGoal] = useState('')
  const [criteriaText, setCriteriaText] = useState(DEFAULT_CRITERIA)
  const [planText, setPlanText] = useState(DEFAULT_PLAN)
  const [formError, setFormError] = useState('')
  const [previewResult, setPreviewResult] = useState<string>('')
  const queryClient = useQueryClient()

  const campaigns = useQuery({
    queryKey: ['campaigns'],
    queryFn: () => getCampaigns(),
    refetchInterval: 15_000,
  })

  const parseCriteria = (): Record<string, unknown> | null => {
    try {
      const parsed = JSON.parse(criteriaText)
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        setFormError('Cohort criteria must be a JSON object, e.g. {"age_min": 65}.')
        return null
      }
      return parsed
    } catch {
      setFormError('Cohort criteria is not valid JSON.')
      return null
    }
  }

  const preview = useMutation({
    mutationFn: previewCohort,
    onSuccess: (result) => {
      setFormError('')
      const names = result.sample.map((s) => s.name).slice(0, 5).join(', ')
      setPreviewResult(
        `${result.count} patient${result.count === 1 ? '' : 's'} match` +
          (names ? ` — e.g. ${names}${result.count > 5 ? ', …' : ''}` : ''),
      )
    },
    onError: (err) => {
      setPreviewResult('')
      const body = (err as { body?: { error?: string } })?.body
      setFormError(body?.error ?? "Couldn't preview the cohort.")
    },
  })

  const create = useMutation({
    mutationFn: createCampaign,
    onSuccess: () => {
      setShowForm(false)
      setName('')
      setGoal('')
      setCriteriaText(DEFAULT_CRITERIA)
      setPlanText(DEFAULT_PLAN)
      setPreviewResult('')
      setFormError('')
      void queryClient.invalidateQueries({ queryKey: ['campaigns'] })
    },
    onError: (err) => {
      const body = (err as { body?: { error?: string } })?.body
      setFormError(body?.error ?? "Couldn't create the campaign.")
    },
  })

  const launch = useMutation({
    mutationFn: launchCampaign,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['campaigns'] }),
  })
  const pause = useMutation({
    mutationFn: pauseCampaign,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['campaigns'] }),
  })

  const onPreview = () => {
    const criteria = parseCriteria()
    if (criteria) preview.mutate(criteria)
  }

  const onCreate = (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim() || !goal.trim()) {
      setFormError('Name and clinical goal are required.')
      return
    }
    const criteria = parseCriteria()
    if (!criteria) return
    let plan
    try {
      plan = JSON.parse(planText)
    } catch {
      setFormError('Channel plan is not valid JSON.')
      return
    }
    create.mutate({
      name: name.trim(),
      clinical_goal: goal.trim(),
      cohort_criteria: criteria,
      channel_plan: plan,
    })
  }

  const forbidden =
    campaigns.isError && (campaigns.error as { status?: number })?.status === 403

  return (
    <div className="mx-auto min-h-screen max-w-5xl bg-slate-50 px-4 py-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Outreach campaigns</h1>
          <p className="text-sm text-slate-500">
            Population-scale reminders: define a cohort, pick channels, launch
          </p>
        </div>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="rounded-lg bg-teal-600 px-3 py-1.5 text-sm font-semibold text-white
                     transition hover:bg-teal-700"
        >
          {showForm ? 'Close' : '+ New campaign'}
        </button>
      </header>

      {showForm && (
        <form
          onSubmit={onCreate}
          className="mt-4 grid grid-cols-1 gap-3 rounded-xl border border-slate-200 bg-white p-4
                     shadow-sm sm:grid-cols-2"
        >
          <label className="text-sm text-slate-600">
            Campaign name
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Flu shot 65+"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
            />
          </label>
          <label className="text-sm text-slate-600">
            Clinical goal (becomes the message)
            <input
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              placeholder="Get 65+ patients their annual flu shot"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
            />
          </label>

          <label className="text-sm text-slate-600">
            Cohort criteria (JSON)
            <textarea
              value={criteriaText}
              onChange={(e) => setCriteriaText(e.target.value)}
              rows={6}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-xs
                         text-slate-900"
            />
            <span className="mt-1 block text-xs text-slate-400">
              Supported keys: age_min, age_max, months_since_last_visit_gte,
              missed_appointments_gte, preferred_language_in, exclude_patient_ids
            </span>
          </label>
          <label className="text-sm text-slate-600">
            Channel escalation plan (JSON)
            <textarea
              value={planText}
              onChange={(e) => setPlanText(e.target.value)}
              rows={6}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-xs
                         text-slate-900"
            />
            <span className="mt-1 block text-xs text-slate-400">
              Non-responders escalate to the next channel after wait_days.
            </span>
          </label>

          <div className="sm:col-span-2 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={onPreview}
              disabled={preview.isPending}
              className="rounded-lg border border-teal-600 px-4 py-2 text-sm font-semibold text-teal-700
                         transition hover:bg-teal-50 disabled:opacity-40"
            >
              Preview cohort
            </button>
            <button
              type="submit"
              disabled={create.isPending}
              className="rounded-lg bg-teal-600 px-4 py-2 text-sm font-semibold text-white
                         transition hover:bg-teal-700 disabled:opacity-40"
            >
              Create draft
            </button>
            {previewResult && <span className="text-sm text-teal-700">{previewResult}</span>}
            {formError && <span className="text-sm text-amber-700">{formError}</span>}
          </div>
        </form>
      )}

      <main className="mt-6 space-y-2">
        {campaigns.isPending && <p className="text-sm text-slate-400">Loading campaigns…</p>}

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
        {campaigns.isError && !forbidden && (
          <p className="text-sm text-amber-700">Couldn't load campaigns — is the backend running?</p>
        )}
        {campaigns.data?.length === 0 && (
          <p className="rounded-xl border border-slate-200 bg-white p-6 text-center text-sm text-slate-500">
            No campaigns yet. Create one to get started.
          </p>
        )}

        {campaigns.data?.map((c) => (
          <div key={c.id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Link
                  to={`/staff/outreach/${c.id}`}
                  className="text-sm font-semibold text-slate-900 hover:text-teal-700 hover:underline"
                >
                  {c.name}
                </Link>
                <span className="text-xs text-slate-400">· {c.member_count} members</span>
              </div>
              <div className="flex items-center gap-2">
                <span
                  className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${STATUS_STYLE[c.status]}`}
                >
                  {c.status}
                </span>
                {(c.status === 'draft' || c.status === 'paused') && (
                  <button
                    onClick={() => launch.mutate(c.id)}
                    disabled={launch.isPending}
                    className="rounded-lg bg-teal-600 px-3 py-1 text-xs font-semibold text-white
                               transition hover:bg-teal-700 disabled:opacity-40"
                  >
                    {c.status === 'paused' ? 'Resume' : 'Launch'}
                  </button>
                )}
                {c.status === 'running' && (
                  <button
                    onClick={() => pause.mutate(c.id)}
                    disabled={pause.isPending}
                    className="rounded-lg border border-slate-300 px-3 py-1 text-xs font-semibold text-slate-700
                               transition hover:bg-slate-100 disabled:opacity-40"
                  >
                    Pause
                  </button>
                )}
              </div>
            </div>
            <p className="mt-1 text-xs text-slate-500">{c.clinical_goal}</p>
            <p className="mt-1 text-xs text-slate-400">
              {c.channel_plan.map((s) => s.channel).join(' → ')}
              {c.launched_at && ` · launched ${new Date(c.launched_at).toLocaleDateString()}`}
            </p>
          </div>
        ))}
      </main>
    </div>
  )
}
