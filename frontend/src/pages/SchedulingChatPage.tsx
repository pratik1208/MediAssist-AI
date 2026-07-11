import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'

import ChatWindow from '../components/ChatWindow'
import PatientPicker from '../components/PatientPicker'

export default function SchedulingChatPage() {
  const location = useLocation()
  // Handed off from the triage result ("Book an appointment") or from a
  // completed registration (which passes the new patient's id).
  const handoff = location.state as { prefill?: string; patientId?: number } | null
  const [patientId, setPatientId] = useState<number | null>(handoff?.patientId ?? null)
  const prefill = handoff?.prefill

  return (
    <div className="mx-auto flex h-screen max-w-3xl flex-col bg-slate-50">
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
        <div>
          <h1 className="text-lg font-bold text-slate-900">MediAssist AI</h1>
          <p className="text-xs text-slate-500">Appointment scheduling assistant</p>
        </div>
        <div className="flex items-center gap-3">
          <Link to="/triage" className="text-sm font-medium text-teal-700 hover:underline">
            Symptom check
          </Link>
          <Link to="/register" className="text-sm font-medium text-teal-700 hover:underline">
            New patient? Register →
          </Link>
          <PatientPicker value={patientId} onChange={setPatientId} />
        </div>
      </header>
      <div className="min-h-0 flex-1">
        <ChatWindow patientId={patientId} initialInput={prefill} />
      </div>
    </div>
  )
}
