// Client for the clinical triage agent (Agent 3). The patient flow uses the
// same X-Session-Token as registration; the staff endpoints use the Django
// admin session cookie (log into /admin/ in this browser first).

import { ApiError, BASE_URL } from './api'

// Matches ACUITY_ORDER in backend triage/services.py.
export type Acuity = 'minimal' | 'low' | 'medium' | 'high' | 'emergency'
export type Disposition = 'ed_now' | 'same_day' | '24_48h' | 'routine' | 'self_care'

export interface TriageStart {
  id: number
  protocol?: string
  first_question?: string
  // emergency shape
  complete?: boolean
  acuity?: Acuity
  message?: string
  ui_hints?: { emergency?: boolean; offer_booking?: boolean }
}

export type TriageAnswerResult =
  | { next_question: string }
  | {
      complete: true
      acuity: Acuity
      disposition?: Disposition
      message?: string
      explanation?: string
      ui_hints: { emergency?: boolean; offer_booking?: boolean }
    }

export interface EscalationAlert {
  id: number
  patient_id: number
  patient_name: string
  assessment_id: number | null
  category: string
  priority: string
  summary: string
  status: string
  acknowledged_at: string | null
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, init)
  const data = await response.json().catch(() => null)
  if (!response.ok) throw new ApiError(response.status, data)
  return data as T
}

const jsonPost = (body: unknown, token: string): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json', 'X-Session-Token': token },
  body: JSON.stringify(body),
})

export const startAssessment = (token: string, symptomsText: string) =>
  request<TriageStart>('/api/triage/assessments/', jsonPost({ symptoms_text: symptomsText }, token))

export const submitAnswer = (token: string, assessmentId: number, answer: string) =>
  request<TriageAnswerResult>(
    `/api/triage/assessments/${assessmentId}/answer/`, jsonPost({ answer }, token))

// --- staff endpoints (Django admin session cookie) ------------------------

function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : ''
}

export const getEscalations = (status?: string) =>
  request<EscalationAlert[]>(
    `/api/staff/triage/escalations/${status ? `?status=${status}` : ''}`,
    { credentials: 'include' },
  )

export const acknowledgeEscalation = (alertId: number) =>
  request<{ status: string }>(`/api/staff/triage/escalations/${alertId}/ack/`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'X-CSRFToken': csrfToken() },
  })
