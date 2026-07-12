// Client for the prior authorization agent (Agent 6). Physician/staff
// endpoints use the Django admin session cookie (log into /admin/ in this
// browser first), like referrals/refills/triage staff pages. Patient
// endpoints use the shared X-Session-Token.

import { ApiError, BASE_URL } from './api'

export type AuthorizationStatus =
  | 'detected'
  | 'gathering_evidence'
  | 'ready_for_review'
  | 'submitted'
  | 'under_review'
  | 'info_requested'
  | 'approved'
  | 'denied'

export const ORDER_TYPES = ['medication', 'imaging', 'procedure', 'device', 'therapy'] as const

export interface AuthorizationSummary {
  id: number
  order_id: number
  patient_id: number
  order_type: string
  treatment: string | null
  status: AuthorizationStatus
  status_display: string
  denial_reason: string | null
  appeal_suggested: boolean
  external_reference: string | null
  created_at: string
}

export interface AuthorizationPackageData {
  codes: { cpt_code: string | null; icd10_code: string | null; medication: string | null }
  evidence: Record<string, unknown[]>
  demographics_snapshot: Record<string, string>
  reviewer_summary: string
}

export interface AuthorizationDetail extends AuthorizationSummary {
  status_history: { status: AuthorizationStatus; at: string }[]
  package: AuthorizationPackageData | null
  messages: { direction: 'outbound' | 'inbound'; content: string; created_at: string }[]
}

export interface StagedTask {
  id: number
  patient_id: number
  priority: string
  summary: string
  status: string
  acknowledged_at: string | null
}

export interface AppealSuggestion {
  should_appeal: boolean | null
  recommendation: string
  draft_argument: string | null
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, init)
  const data = await response.json().catch(() => null)
  if (!response.ok) throw new ApiError(response.status, data)
  return data as T
}

const withToken = (token: string): RequestInit => ({
  headers: { 'X-Session-Token': token },
})

// --- patient (session token) -------------------------------------------------

export const getMyAuthorizations = (token: string) =>
  request<AuthorizationSummary[]>('/api/priorauth/status/', withToken(token))

// --- staff (Django admin session cookie) ------------------------------------

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

/** Physician: one call creates the order and auto-triggers detection (FR-P1). */
export const createTreatmentOrder = (data: {
  patient_id: number
  order_type: string
  doctor_id?: number
  cpt_code?: string
  icd10_code?: string
  medication?: string
  referral_id?: number
}) => request<{
  order_id: number; authorization_required: boolean
  request_id: number | null; status: AuthorizationStatus | null
}>('/api/priorauth/orders/', staffPost(data))

export const getAuthorizationQueue = (status?: string) =>
  request<AuthorizationSummary[]>(
    `/api/staff/priorauth/${status ? `?status=${status}` : ''}`,
    { credentials: 'include' },
  )

export const getAuthorizationDetail = (requestId: number) =>
  request<AuthorizationDetail>(`/api/staff/priorauth/${requestId}/`, { credentials: 'include' })

export const getReferralAuthorizations = (referralId: number) =>
  request<AuthorizationSummary[]>(`/api/priorauth/for-referral/${referralId}/`,
    { credentials: 'include' })

export const getStagedTasks = (status: 'open' | 'all' = 'open') =>
  request<StagedTask[]>(`/api/staff/priorauth/tasks/?status=${status}`, { credentials: 'include' })

export const submitAuthorization = (requestId: number) =>
  request<{ status: AuthorizationStatus; external_reference: string }>(
    `/api/staff/priorauth/${requestId}/submit/`, staffPost(),
  )

export const pollAuthorizationStatus = (requestId: number) =>
  request<AuthorizationSummary>(`/api/staff/priorauth/${requestId}/poll/`, staffPost())

export const suggestAppeal = (requestId: number) =>
  request<AppealSuggestion>(`/api/staff/priorauth/${requestId}/suggest-appeal/`, staffPost())

/** Dev only — force what the simulated payer returns on the NEXT poll. */
export const simulatePayerResponse = (requestId: number, data: {
  status: string
  denial_reason?: string
  appeal_suggested?: boolean
  requested_items?: string[]
}) => request<{ forced: Record<string, unknown> }>(
  `/api/staff/priorauth/${requestId}/simulate/`, staffPost(data),
)
