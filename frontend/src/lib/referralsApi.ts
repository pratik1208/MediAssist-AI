// Client for the referral execution agent (Agent 5). Physician/care-
// coordinator/specialist-office endpoints use the Django admin session
// cookie (log into /admin/ in this browser first), like the triage and
// refills staff pages. Patient endpoints use the shared X-Session-Token.

import { ApiError, BASE_URL } from './api'

export type ReferralStatus =
  | 'created'
  | 'accepted'
  | 'appointment_scheduled'
  | 'patient_confirmed'
  | 'visit_completed'
  | 'report_received'
  | 'closed'
  | 'stalled'

// Matches core.models.Specialty exactly.
export const SPECIALTIES = [
  'General Medicine', 'Cardiology', 'Dermatology', 'Pediatrics', 'Orthopedics',
  'Gynecology', 'Neurology', 'Psychiatry', 'Ophthalmology', 'ENT',
  'Gastroenterology', 'Endocrinology', 'Pulmonology', 'Urology', 'Oncology',
] as const

export const URGENCIES = ['routine', 'low', 'medium', 'high', 'emergency'] as const

export interface ReferralSummary {
  id: number
  patient_id: number
  specialty_needed: string
  specialist: string | null
  // Null means this is a draft auto-created from a triage handoff — a
  // physician must confirm it (accept with doctor_id) before it can proceed.
  referring_doctor: string | null
  reason: string
  urgency: string
  status: ReferralStatus
  status_display: string
  stalled: boolean
  appointment_id: number | null
  external_appointment_at: string | null
  created_at: string
}

export interface ReferralTimeline extends ReferralSummary {
  status_history: { status: ReferralStatus; at: string }[]
}

export interface SpecialistCandidate {
  id: number
  name: string
  practice_name: string
  specialty: string
  address: { city?: string; area?: string; postal_code?: string }
  accepted_insurances: string[]
  languages: string[]
  accepting_new_patients: boolean
  contact_channel: string
  consultation_fee: string | null
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

export const getMyReferrals = (token: string) =>
  request<ReferralSummary[]>('/api/referrals/status/', withToken(token))

export const confirmReferral = (token: string, referralId: number) =>
  request<{ status: string }>(`/api/referrals/${referralId}/confirm/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Session-Token': token },
    body: JSON.stringify({}),
  })

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

/** Physician: one click during consultation (FR-F1). */
export const createReferral = (data: {
  patient_id: number
  doctor_id: number
  specialty: string
  reason: string
  urgency: string
}) => request<{ id: number; status: string }>('/api/referrals/', staffPost(data))

export const getReferralQueue = (status?: string) =>
  request<ReferralSummary[]>(
    `/api/staff/referrals/${status ? `?status=${status}` : ''}`,
    { credentials: 'include' },
  )

export const getReferralTimeline = (referralId: number) =>
  request<ReferralTimeline>(`/api/staff/referrals/${referralId}/`, { credentials: 'include' })

/** A stalled referral must resume to its prior status before the normal
 * next action (book/visit-completed/report) becomes available again. */
export const resumeReferral = (referralId: number) =>
  request<{ status: string }>(`/api/staff/referrals/${referralId}/resume/`, staffPost())

export const getSpecialistCandidates = (referralId: number) =>
  request<SpecialistCandidate[]>(`/api/staff/referrals/${referralId}/candidates/`,
    { credentials: 'include' })

/** doctorId is required the first time for a draft referral (referring_doctor
 * is null) — that's the physician-confirmation gate; a referral that
 * already has one ignores it. */
export const acceptReferral = (referralId: number, specialistId: number, doctorId?: number) =>
  request<{ status: string; specialist: string }>(
    `/api/staff/referrals/${referralId}/accept/`,
    staffPost({ specialist_id: specialistId, ...(doctorId ? { doctor_id: doctorId } : {}) }),
  )

export const bookReferralVisit = (referralId: number, start: string, end: string) =>
  request<{ status: string; appointment_id: number }>(
    `/api/staff/referrals/${referralId}/book/`, staffPost({ start, end }),
  )

export const markVisitCompleted = (referralId: number) =>
  request<{ status: string }>(`/api/staff/referrals/${referralId}/visit-completed/`, staffPost())

export const uploadConsultationReportJson = (referralId: number, data: {
  diagnosis: string
  treatment_plan: string
  medications: string[]
  followup_recommendations: string[]
}) => request<{ status: string; report_id: number }>(
  `/api/staff/referrals/${referralId}/report/`, staffPost(data),
)

export async function uploadConsultationReportFile(
  referralId: number, file: File,
): Promise<{ status: string; report_id: number }> {
  const form = new FormData()
  form.append('file', file)
  const response = await fetch(`${BASE_URL}/api/staff/referrals/${referralId}/report/`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'X-CSRFToken': csrfToken() },
    body: form,
  })
  const data = await response.json().catch(() => null)
  if (!response.ok) throw new ApiError(response.status, data)
  return data
}
