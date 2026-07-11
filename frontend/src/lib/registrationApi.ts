// Client for the registration agent (Agent 2). Every endpoint after
// /registration/start requires the signed session token in an
// X-Session-Token header.

import { ApiError, BASE_URL, readSseStream } from './api'

export type RegistrationStage =
  | 'demographics'
  | 'duplicate_hold'
  | 'identity_verification'
  | 'insurance'
  | 'intake'
  | 'done'

/** "otp_required" or {"upload": "insurance_card"} — see registration/ai/handler.py */
export type UiHint = string | { upload: string }

export interface RegistrationSession {
  session_token: string
  conversation_id: number
}

/** Streaming events from POST /api/registration/chat. */
export type RegistrationChatEvent =
  | { delta: string }
  | {
      done: true
      stage: RegistrationStage
      ui_hints: UiHint[]
      registration_complete: boolean
      patient_id: number | null
    }

export interface RegistrationStatus {
  registration_status: string
  missing: string[]
}

async function post<T>(
  path: string,
  body: unknown,
  token?: string,
): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { 'X-Session-Token': token } : {}),
    },
    body: JSON.stringify(body),
  })
  const data = await response.json().catch(() => null)
  if (!response.ok) throw new ApiError(response.status, data)
  return data as T
}

export const startRegistration = () =>
  post<RegistrationSession>('/api/registration/start', { channel: 'web' })

export function streamRegistrationChat(
  token: string,
  message: string,
  onEvent: (event: RegistrationChatEvent) => void,
): Promise<void> {
  return fetch(`${BASE_URL}/api/registration/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Session-Token': token,
    },
    body: JSON.stringify({ message }),
  }).then((response) => readSseStream(response, onEvent))
}

/**
 * Attach a patient to the session by demographics. A returning patient is
 * matched to their existing record (200); a new one is created (201); a
 * near-match returns 409 and needs staff review.
 */
export const submitDemographics = (
  token: string,
  demographics: {
    first_name: string
    last_name: string
    dob: string
    contact_number: string
  },
) =>
  post<{ patient_id: number; match: string }>(
    '/api/registration/demographics', demographics, token,
  )

export const requestOtp = (token: string) =>
  post<{ detail: string }>('/api/registration/otp/request', { channel: 'SMS' }, token)

export const verifyOtp = (token: string, code: string) =>
  post<{ verified: boolean; code?: string }>(
    '/api/registration/otp/verify', { code }, token,
  )

export async function uploadDocument(
  token: string,
  file: File,
  docType: string,
): Promise<{ id: number; doc_type: string; extraction_status: string }> {
  const form = new FormData()
  form.append('file', file)
  form.append('doc_type', docType)
  const response = await fetch(`${BASE_URL}/api/registration/documents`, {
    method: 'POST',
    headers: { 'X-Session-Token': token }, // browser sets the multipart type
    body: form,
  })
  const data = await response.json().catch(() => null)
  if (!response.ok) throw new ApiError(response.status, data)
  return data
}

export async function getRegistrationStatus(token: string): Promise<RegistrationStatus> {
  const response = await fetch(`${BASE_URL}/api/registration/status`, {
    headers: { 'X-Session-Token': token },
  })
  const data = await response.json().catch(() => null)
  if (!response.ok) throw new ApiError(response.status, data)
  return data as RegistrationStatus
}
