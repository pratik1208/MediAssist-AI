// Small typed API client. Every request goes through the same base URL:
// empty in dev (the Vite proxy forwards /api/* to Django), the deployed
// backend URL in production.

import type {
  Appointment,
  AppointmentCreate,
  ChatMessage,
  ChatResult,
  Doctor,
  Patient,
} from './types'

const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? ''

export class ApiError extends Error {
  status: number
  body: unknown

  constructor(status: number, body: unknown) {
    super(`API error ${status}`)
    this.status = status
    this.body = body
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new ApiError(response.status, body)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const getDoctors = () => request<Doctor[]>('/api/doctors')
export const getPatients = () => request<Patient[]>('/api/patients')
export const getAppointment = (id: number) => request<Appointment>(`/api/appointments/${id}`)

export const createAppointment = (body: AppointmentCreate) =>
  request<Appointment>('/api/appointments', {
    method: 'POST',
    body: JSON.stringify(body),
  })

/**
 * Consume an SSE response body, firing `onEvent` with each parsed
 * `data: {...}` event as it arrives.
 */
export async function readSseStream<T>(
  response: Response,
  onEvent: (event: T) => void,
): Promise<void> {
  if (!response.ok || response.body === null) {
    throw new ApiError(response.status, await response.text().catch(() => null))
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // SSE events are separated by a blank line.
    let boundary = buffer.indexOf('\n\n')
    while (boundary !== -1) {
      const rawEvent = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      const data = rawEvent
        .split('\n')
        .filter((line) => line.startsWith('data: '))
        .map((line) => line.slice('data: '.length))
        .join('\n')
      if (data) onEvent(JSON.parse(data) as T)
      boundary = buffer.indexOf('\n\n')
    }
  }
}

/** POST /api/chat (scheduling agent) and consume the SSE stream. */
export async function streamChat(
  conversation: ChatMessage[],
  onEvent: (event: ChatResult) => void,
): Promise<void> {
  const response = await fetch(`${BASE_URL}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ conversation }),
  })
  await readSseStream(response, onEvent)
}

export { BASE_URL }
