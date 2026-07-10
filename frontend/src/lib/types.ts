// Shapes coming from the Django backend (see backend/scheduling/ai/handler.py
// and the CRUD serializers — all fields are serialized as-is).

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

/** A slot is a [start, end] pair of ISO datetime strings. */
export type Slot = [string, string]

/** The single JSON event streamed back by POST /api/chat. */
export type ChatResult =
  | { type: 'emergency'; message: string }
  | { type: 'clarification'; message: string }
  | { type: 'no_doctor'; message: string }
  | { type: 'slots'; doctor: string; specialty: string; slots: Slot[] }

export interface Doctor {
  id: number
  name: string
  specialty: string
  is_active: boolean
}

export interface Patient {
  id: number
  first_name: string
  last_name: string
  contact_number: string
}

export interface Appointment {
  id: number
  doctor: number
  patient: number
  start_time: string
  end_time: string
  reason: string
  urgency: string
  status: string
}

/** Body for POST /api/appointments. */
export interface AppointmentCreate {
  doctor: number
  patient: number
  start_time: string
  end_time: string
  reason: string
  urgency: string
  source?: string
}
