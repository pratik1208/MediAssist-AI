import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import {
  dispatchWave,
  getCampaign,
  getCampaignMembers,
  launchCampaign,
  pauseCampaign,
  simulateInboundReply,
} from '../lib/outreachApi'
import type { CampaignStats, MemberState } from '../lib/outreachApi'

const FUNNEL_STEPS: { key: keyof CampaignStats; label: string }[] = [
  { key: 'identified', label: 'Identified' },
  { key: 'sent', label: 'Sent' },
  { key: 'delivered', label: 'Delivered' },
  { key: 'responded', label: 'Responded' },
  { key: 'scheduled', label: 'Scheduled' },
  { key: 'completed', label: 'Completed' },
]

const STATE_STYLE: Record<MemberState, string> = {
  identified: 'bg-slate-200 text-slate-700',
  contacted: 'bg-sky-100 text-sky-800',
  responded: 'bg-indigo-100 text-indigo-800',
  scheduled: 'bg-green-100 text-green-800',
  completed: 'bg-green-100 text-green-800',
  snoozed: 'bg-amber-100 text-amber-800',
  opted_out: 'bg-red-100 text-red-800',
  unreachable: 'bg-slate-200 text-slate-500',
}

export default function CampaignAnalyticsPage() {
  const { id } = useParams<{ id: string }>()
  const campaignId = Number(id)
  const queryClient = useQueryClient()
  const [replyText, setReplyText] = useState('')
  const [replyMemberId, setReplyMemberId] = useState('')
  const [replyResult, setReplyResult] = useState('')

  const campaign = useQuery({
    queryKey: ['campaign', campaignId],
    queryFn: () => getCampaign(campaignId),
    refetchInterval: 10_000,
  })
  const members = useQuery({
    queryKey: ['campaignMembers', campaignId],
    queryFn: () => getCampaignMembers(campaignId),
    refetchInterval: 10_000,
  })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['campaign', campaignId] })
    void queryClient.invalidateQueries({ queryKey: ['campaignMembers', campaignId] })
  }

  const launch = useMutation({ mutationFn: () => launchCampaign(campaignId), onSuccess: invalidate })
  const pause = useMutation({ mutationFn: () => pauseCampaign(campaignId), onSuccess: invalidate })
  const wave = useMutation({ mutationFn: () => dispatchWave(campaignId), onSuccess: invalidate })

  const reply = useMutation({
    mutationFn: simulateInboundReply,
    onSuccess: (result) => {
      setReplyResult(`Recorded — member is now “${result.member_state}”.`)
      setReplyText('')
      invalidate()
    },
    onError: (err) => {
      const body = (err as { body?: { error?: string } })?.body
      setReplyResult(body?.error ?? "Couldn't record the reply.")
    },
  })

  const forbidden =
    campaign.isError && (campaign.error as { status?: number })?.status === 403

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

  const c = campaign.data
  const stats = c?.stats
  const maxFunnel = stats ? Math.max(stats.identified, 1) : 1

  return (
    <div className="mx-auto min-h-screen max-w-4xl bg-slate-50 px-4 py-6">
      <Link to="/staff/outreach" className="text-sm font-medium text-teal-700 hover:underline">
        ← All campaigns
      </Link>

      {campaign.isPending && <p className="mt-4 text-sm text-slate-400">Loading…</p>}

      {c && stats && (
        <>
          <header className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h1 className="text-xl font-bold text-slate-900">{c.name}</h1>
              <p className="text-sm text-slate-500">{c.clinical_goal}</p>
            </div>
            <div className="flex items-center gap-2">
              <span className="rounded-full bg-slate-200 px-2.5 py-0.5 text-xs font-semibold text-slate-700">
                {c.status}
              </span>
              {(c.status === 'draft' || c.status === 'paused') && (
                <button
                  onClick={() => launch.mutate()}
                  disabled={launch.isPending}
                  className="rounded-lg bg-teal-600 px-3 py-1 text-xs font-semibold text-white
                             transition hover:bg-teal-700 disabled:opacity-40"
                >
                  {c.status === 'paused' ? 'Resume' : 'Launch'}
                </button>
              )}
              {c.status === 'running' && (
                <>
                  <button
                    onClick={() => wave.mutate()}
                    disabled={wave.isPending}
                    className="rounded-lg border border-teal-600 px-3 py-1 text-xs font-semibold text-teal-700
                               transition hover:bg-teal-50 disabled:opacity-40"
                  >
                    Dispatch wave
                  </button>
                  <button
                    onClick={() => pause.mutate()}
                    disabled={pause.isPending}
                    className="rounded-lg border border-slate-300 px-3 py-1 text-xs font-semibold text-slate-700
                               transition hover:bg-slate-100 disabled:opacity-40"
                  >
                    Pause
                  </button>
                </>
              )}
            </div>
          </header>

          {/* Funnel */}
          <section className="mt-6 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-900">Funnel</h2>
              <span className="text-sm text-slate-500">
                Conversion:{' '}
                <span className="font-semibold text-teal-700">
                  {(stats.conversion_rate * 100).toFixed(1)}%
                </span>
              </span>
            </div>
            <div className="mt-3 space-y-2">
              {FUNNEL_STEPS.map((step) => {
                const value = stats[step.key] as number
                return (
                  <div key={step.key} className="flex items-center gap-3">
                    <span className="w-24 shrink-0 text-xs text-slate-500">{step.label}</span>
                    <div className="h-5 flex-1 overflow-hidden rounded bg-slate-100">
                      <div
                        className="h-full rounded bg-teal-500 transition-all"
                        style={{ width: `${(value / maxFunnel) * 100}%` }}
                      />
                    </div>
                    <span className="w-8 shrink-0 text-right text-sm font-semibold text-slate-900">
                      {value}
                    </span>
                  </div>
                )
              })}
            </div>
          </section>

          {/* Per-channel breakdown */}
          <section className="mt-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="text-sm font-semibold text-slate-900">Messages sent per channel</h2>
            {Object.keys(stats.by_channel).length === 0 ? (
              <p className="mt-2 text-sm text-slate-400">No messages sent yet.</p>
            ) : (
              <div className="mt-2 flex flex-wrap gap-2">
                {Object.entries(stats.by_channel).map(([channel, count]) => (
                  <span
                    key={channel}
                    className="rounded-lg bg-slate-100 px-3 py-1 text-sm text-slate-700"
                  >
                    {channel}: <span className="font-semibold text-slate-900">{count}</span>
                  </span>
                ))}
              </div>
            )}
          </section>

          {/* Dev: simulate an inbound reply (manual E2E) */}
          <section className="mt-4 rounded-xl border border-dashed border-slate-300 bg-white p-4">
            <h2 className="text-sm font-semibold text-slate-900">Simulate an inbound reply</h2>
            <p className="mt-1 text-xs text-slate-400">
              Dev tool: posts to the inbound webhook as if a patient replied, so the funnel
              updates. Leave the AI to classify it, or the member picker targets one member.
            </p>
            <form
              onSubmit={(e) => {
                e.preventDefault()
                if (!replyText.trim()) return
                reply.mutate({
                  text: replyText.trim(),
                  member_id: replyMemberId ? Number(replyMemberId) : undefined,
                })
              }}
              className="mt-2 flex flex-wrap items-center gap-2"
            >
              <select
                value={replyMemberId}
                onChange={(e) => setReplyMemberId(e.target.value)}
                className="rounded-lg border border-slate-300 px-2 py-2 text-sm text-slate-900"
              >
                <option value="">— pick a member —</option>
                {members.data?.map((m) => (
                  <option key={m.id} value={m.id}>
                    #{m.id} {m.patient_name}
                  </option>
                ))}
              </select>
              <input
                value={replyText}
                onChange={(e) => setReplyText(e.target.value)}
                placeholder='e.g. "yes please book me"'
                className="min-w-[14rem] flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
              />
              <button
                type="submit"
                disabled={reply.isPending || !replyMemberId}
                className="rounded-lg bg-teal-600 px-4 py-2 text-sm font-semibold text-white
                           transition hover:bg-teal-700 disabled:opacity-40"
              >
                Send reply
              </button>
            </form>
            {replyResult && <p className="mt-2 text-sm text-teal-700">{replyResult}</p>}
          </section>

          {/* Members */}
          <section className="mt-4">
            <h2 className="text-sm font-semibold text-slate-900">
              Members{members.data ? ` (${members.data.length})` : ''}
            </h2>
            <div className="mt-2 space-y-1.5">
              {members.data?.map((m) => (
                <div
                  key={m.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border
                             border-slate-200 bg-white px-4 py-2 text-sm shadow-sm"
                >
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-slate-900">{m.patient_name}</span>
                    <span className="text-xs text-slate-400">
                      {m.preferred_language} · {m.channel_attempts.length} attempt
                      {m.channel_attempts.length === 1 ? '' : 's'}
                    </span>
                  </div>
                  <span
                    className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${STATE_STYLE[m.state]}`}
                  >
                    {m.state}
                  </span>
                </div>
              ))}
              {members.data?.length === 0 && (
                <p className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-500">
                  No members yet — launch the campaign to enroll the cohort.
                </p>
              )}
            </div>
          </section>
        </>
      )}
    </div>
  )
}
