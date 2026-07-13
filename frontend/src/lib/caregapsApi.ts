// Client for the care gap closure agent (Agent 8). All staff endpoints use
// the Django admin session cookie (log into /admin/ in this browser first),
// same convention as outreach/referrals/priorauth.

import { ApiError, BASE_URL } from './api'

export type GapStatus =
  | 'open'
  | 'outreach'
  | 'scheduled'
  | 'completed'
  | 'closed'

export type RiskTier = 'high' | 'medium' | 'low'

export type PlanStatus =
  | 'draft'
  | 'sent'
  | 'accepted'
  | 'in_progress'
  | 'completed'
  | 'recycled'

export interface GapRow {
  id: number
  patient_id: number
  patient_name: string
  contact_number: string
  guideline_id: number
  guideline_name: string
  care_item_type: string
  risk_tier: RiskTier
  status: GapStatus
  due_since: string
  days_overdue: number
  detected_at: string
  closed_at: string | null
}

export interface PlanDetail {
  id: number
  patient_id: number
  patient_name: string
  status: PlanStatus
  plan_text: string
  created_at: string
  gaps: GapRow[]
  shared_visit_gap_ids: number[]
  separate_gap_ids: number[]
}

export interface PatientGapPanel {
  patient_id: number
  patient_name: string
  open_gaps: GapRow[]
  closed_gaps: GapRow[]
  care_plans: PlanDetail[]
}

export interface QualityMetrics {
  gaps: {
    total: number
    open: number
    closed: number
    closure_rate: number
    by_guideline: {
      guideline_id: number
      guideline_name: string
      risk_tier: RiskTier
      is_active: boolean
      open_gaps: number
      closed_gaps: number
    }[]
  }
  care_plans: {
    by_status: Record<PlanStatus, number>
    response_rate: number
    completion_rate: number
  }
  per_provider: {
    provider: string
    open_gaps: number
    closed_gaps: number
    closure_rate: number
  }[]
}

export interface ScanResult {
  scope: string
  patients_scanned?: number
  opened: number
  refreshed: number
  closed: number
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

export const getGapWorklist = (status?: GapStatus, guidelineId?: number) => {
  const params = new URLSearchParams()
  if (status) params.set('status', status)
  if (guidelineId) params.set('guideline', String(guidelineId))
  const qs = params.toString()
  return request<GapRow[]>(`/api/staff/caregaps/${qs ? `?${qs}` : ''}`, {
    credentials: 'include',
  })
}

export const getPatientGaps = (patientId: number) =>
  request<PatientGapPanel>(`/api/staff/caregaps/patients/${patientId}/`, {
    credentials: 'include',
  })

export const bundleCarePlan = (patientId: number) =>
  request<PlanDetail>(`/api/staff/caregaps/patients/${patientId}/bundle/`, staffPost())

export const getCarePlan = (planId: number) =>
  request<PlanDetail>(`/api/staff/caregaps/plans/${planId}/`, { credentials: 'include' })

export const triggerScan = (patientId?: number) =>
  request<ScanResult>(
    '/api/staff/caregaps/scan/',
    staffPost(patientId ? { patient_id: patientId } : {}),
  )

export const getQualityMetrics = () =>
  request<QualityMetrics>('/api/staff/caregaps/metrics/', { credentials: 'include' })
