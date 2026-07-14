// Client for the after-hours front desk (Agent 9). One entry point,
// /api/frontdesk/chat, understands free text (routed by the Phase 4 AI
// layer) and two auth actions (start_auth / verify_otp) — all through the
// same signed X-Session-Token every other patient flow uses. The endpoint
// is SSE-shaped but only ever emits a single, already-computed event.

import { ApiError, BASE_URL, readSseStream } from './api'

export interface FrontdeskSession {
  session_token: string
  conversation_id: number
  session_id: number
}

/** The shape returned by a single dispatched intent (frontdesk/services.py's
 * dispatch_intent) — also what each entry of `results`/`resumed` looks like. */
export interface FrontdeskResult {
  status: string
  reply: string
  staff_task_id?: number
  articles?: { id: number; title: string }[]
  appointments?: { id: number; doctor: string; start_time: string; reason: string }[]
  prescriptions?: { id: number; medication: string; refills_left: number; controlled: boolean }[]
  referrals?: { id: number; specialty: string; status: string }[]
  authorizations?: { id: number; status: string; order_type: string }[]
  care_gaps?: {
    gap_id: number
    guideline: string
    care_item_type: string
    risk_tier: string
    days_overdue: number
  }[]
  handoff?: string
}

/** The top-level /frontdesk/chat response. Free text is always wrapped by
 * the router's _combine(), so its structured fields live in `results[]`
 * rather than at the top level; `resumed` (post-auth) is a flat list of
 * separately-answered intents. */
export interface FrontdeskOutcome extends FrontdeskResult {
  results?: FrontdeskResult[]
  resumed?: FrontdeskResult[]
  ui_hints?: { emergency?: boolean }
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await response.json().catch(() => null)
  if (!response.ok) throw new ApiError(response.status, data)
  return data as T
}

export const startFrontdesk = () =>
  post<FrontdeskSession>('/api/frontdesk/start', { channel: 'web' })

async function chat(token: string, body: unknown): Promise<FrontdeskOutcome> {
  const response = await fetch(`${BASE_URL}/api/frontdesk/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Session-Token': token },
    body: JSON.stringify(body),
  })
  let outcome: FrontdeskOutcome | undefined
  await readSseStream<FrontdeskOutcome>(response, (event) => { outcome = event })
  if (!outcome) throw new ApiError(response.status, null)
  return outcome
}

/** Free text -> the Phase 4 AI router (multi-intent, red-flag screened). */
export const sendFrontdeskMessage = (token: string, message: string) =>
  chat(token, { message })

/** Step 1 of the auth gate: phone + DOB -> an OTP to that patient's phone. */
export const startFrontdeskAuth = (token: string, contactNumber: string, dob: string) =>
  chat(token, { action: 'start_auth', contact_number: contactNumber, dob })

/** Step 2: DOB + OTP -> verified session, with any queued intents resumed. */
export const verifyFrontdeskOtp = (token: string, dob: string, otp: string) =>
  chat(token, { action: 'verify_otp', dob, otp })

// -- staff task queue (FR-A7) --------------------------------------------------------

export interface StaffTask {
  id: number
  category: string
  priority: string
  status: string
  summary: string
  patient_id: number | null
  patient_name: string | null
  session_id: number | null
  claimed_by: string
  resolved_at: string | null
  created_at: string
}

function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : ''
}

async function staffRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, { credentials: 'include', ...init })
  const data = await response.json().catch(() => null)
  if (!response.ok) throw new ApiError(response.status, data)
  return data as T
}

export const getStaffTasks = (status?: string) =>
  staffRequest<StaffTask[]>(
    `/api/staff/frontdesk/tasks/${status ? `?status=${status}` : ''}`,
  )

export const claimStaffTask = (id: number, claimedBy?: string) =>
  staffRequest<StaffTask>(`/api/staff/frontdesk/tasks/${id}/claim/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
    body: JSON.stringify(claimedBy ? { claimed_by: claimedBy } : {}),
  })

export const resolveStaffTask = (id: number, claimedBy?: string) =>
  staffRequest<StaffTask>(`/api/staff/frontdesk/tasks/${id}/resolve/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
    body: JSON.stringify(claimedBy ? { claimed_by: claimedBy } : {}),
  })
