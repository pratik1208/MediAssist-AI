// Client for the refill coordination agent (Agent 4). Patient endpoints use
// the shared X-Session-Token (verified patient required); the physician
// queue uses the Django admin session cookie, like the triage staff pages.

import { ApiError, BASE_URL } from './api'

export interface PatientPrescription {
  id: number
  medication: string
  quantity: number
  refills_remaining: number
  controlled_substance: boolean
}

export type RefillStatus =
  | 'received'
  | 'eligibility_check'
  | 'paused'
  | 'pending_approval'
  | 'approved'
  | 'rejected'
  | 'visit_required'
  | 'sent_to_pharmacy'
  | 'ready_for_pickup'

export interface RefillRequestStatus {
  id: number
  medication: string
  status: RefillStatus
  status_display: string
  pause_reason?: string
}

export interface Pharmacy {
  id: number
  name: string
}

export interface RenewalSummary {
  medication?: string
  quantity?: number
  last_prescribed?: string
  refills_remaining?: number
  recent_labs?: { test?: string; date?: string; findings?: string }[]
  allergies?: string[]
  adverse_events?: string[]
  adherence?: string | number | null
  controlled_substance?: boolean
}

export interface RefillQueueEntry {
  id: number
  patient: string
  medication: string
  requested_at: string
  summary_text: string
  renewal_summary: RenewalSummary
  controlled_substance: boolean
  actions: string[]
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

const withToken = (token: string): RequestInit => ({
  headers: { 'X-Session-Token': token },
})

export const getPrescriptions = (token: string) =>
  request<PatientPrescription[]>('/api/refills/prescriptions/', withToken(token))

export const getPharmacies = () => request<Pharmacy[]>('/api/pharmacy')

/**
 * Start a refill. 201 -> {id, status}; 409 -> ApiError whose body is
 * {id, code: "paused", reason} OR {id, code: "already_requested", status}
 * when one is already in flight for this prescription; 400 when no
 * pharmacy could be resolved (send pharmacy_id then).
 */
export const createRefillRequest = (
  token: string,
  prescriptionId: number,
  pharmacyId?: number,
) =>
  request<{ id: number; status: RefillStatus; is_renewal: boolean }>(
    '/api/refills/requests/',
    jsonPost(
      pharmacyId
        ? { prescription_id: prescriptionId, pharmacy_id: pharmacyId }
        : { prescription_id: prescriptionId },
      token,
    ),
  )

export const getRefillStatus = (token: string, requestId: number) =>
  request<RefillRequestStatus>(`/api/refills/requests/${requestId}/`, withToken(token))

// --- physician endpoints (Django admin session cookie) ---------------------

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

export const getRefillQueue = () =>
  request<RefillQueueEntry[]>('/api/staff/refills/queue/', { credentials: 'include' })

export const approveRefill = (requestId: number) =>
  request<{ status: string }>(`/api/staff/refills/${requestId}/approve/`, staffPost())

export const rejectRefill = (requestId: number, reason: string) =>
  request<{ status: string }>(`/api/staff/refills/${requestId}/reject/`, staffPost({ reason }))

export const requestVisit = (requestId: number) =>
  request<{ status: string }>(`/api/staff/refills/${requestId}/request-visit/`, staffPost())
