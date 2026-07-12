// Client for the outreach campaigns agent (Agent 7). Staff endpoints use
// the Django admin session cookie (log into /admin/ in this browser first),
// like referrals/priorauth. The inbound webhook is unauthenticated (a real
// SMS/email provider posts to it) and is only used here to simulate a reply
// during the manual E2E.

import { ApiError, BASE_URL } from './api'

export type CampaignStatus = 'draft' | 'running' | 'paused' | 'completed'

export type MemberState =
  | 'identified'
  | 'contacted'
  | 'responded'
  | 'scheduled'
  | 'completed'
  | 'snoozed'
  | 'opted_out'
  | 'unreachable'

export interface ChannelStep {
  channel: string
  wait_days: number
}

export interface CampaignSummary {
  id: number
  name: string
  clinical_goal: string
  cohort_criteria: Record<string, unknown>
  channel_plan: ChannelStep[]
  status: CampaignStatus
  launched_at: string | null
  created_at: string
  member_count: number
}

export interface CampaignStats {
  identified: number
  sent: number
  delivered: number
  responded: number
  scheduled: number
  completed: number
  conversion_rate: number
  by_channel: Record<string, number>
}

export interface CampaignDetail extends CampaignSummary {
  stats: CampaignStats
}

export interface CohortPreview {
  count: number
  sample: {
    id: number
    name: string
    dob: string
    contact_number: string
    preferred_language: string
  }[]
}

export interface CampaignMemberRow {
  id: number
  patient_id: number
  patient_name: string
  contact_number: string
  email: string | null
  preferred_language: string
  state: MemberState
  snooze_until: string | null
  channel_attempts: { channel: string; at: string; message_id: number | null }[]
  outreach_reason: string
  assigned_physician: string | null
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, init)
  const data = await response.json().catch(() => null)
  if (!response.ok) throw new ApiError(response.status, data)
  return data as T
}

function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : ''
}

const staffPost = (body?: unknown): RequestInit => ({
  method: 'POST',
  credentials: 'include',
  headers: {
    'X-CSRFToken': csrfToken(),
    ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
  },
  ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
})

// --- staff (Django admin session cookie) ------------------------------------

export const getCampaigns = (status?: string) =>
  request<CampaignSummary[]>(
    `/api/staff/outreach/${status ? `?status=${status}` : ''}`,
    { credentials: 'include' },
  )

export const getCampaign = (id: number) =>
  request<CampaignDetail>(`/api/staff/outreach/${id}/`, { credentials: 'include' })

export const getCampaignStats = (id: number) =>
  request<CampaignStats>(`/api/staff/outreach/${id}/stats/`, { credentials: 'include' })

export const getCampaignMembers = (id: number, state?: string) =>
  request<CampaignMemberRow[]>(
    `/api/staff/outreach/${id}/members/${state ? `?state=${state}` : ''}`,
    { credentials: 'include' },
  )

export const previewCohort = (cohort_criteria: Record<string, unknown>) =>
  request<CohortPreview>('/api/staff/outreach/preview-cohort/', staffPost({ cohort_criteria }))

export const createCampaign = (data: {
  name: string
  clinical_goal: string
  cohort_criteria: Record<string, unknown>
  channel_plan: ChannelStep[]
}) => request<CampaignSummary>('/api/staff/outreach/', staffPost(data))

export const launchCampaign = (id: number) =>
  request<{ status: string; enrolled?: number; first_wave?: { queued: number; unreachable: number }; resumed?: boolean }>(
    `/api/staff/outreach/${id}/launch/`, staffPost(),
  )

export const pauseCampaign = (id: number) =>
  request<{ status: string }>(`/api/staff/outreach/${id}/pause/`, staffPost())

export const dispatchWave = (id: number) =>
  request<{ queued: number; unreachable: number }>(
    `/api/staff/outreach/${id}/dispatch-wave/`, staffPost(),
  )

// --- inbound webhook (unauthenticated — used to simulate a reply in dev) ----

export const simulateInboundReply = (data: {
  from?: string
  member_id?: number
  text: string
  intent?: string
  snooze_until?: string
}) => request<{
  response_id: number; member_id: number; campaign_id: number
  handled: boolean; member_state: MemberState
}>('/api/outreach/webhook/', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(data),
})
