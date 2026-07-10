import { useState } from 'react'

import ChatWindow from '../components/ChatWindow'
import PatientPicker from '../components/PatientPicker'

export default function SchedulingChatPage() {
  const [patientId, setPatientId] = useState<number | null>(null)

  return (
    <div className="mx-auto flex h-screen max-w-3xl flex-col bg-slate-50">
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
        <div>
          <h1 className="text-lg font-bold text-slate-900">MediAssist AI</h1>
          <p className="text-xs text-slate-500">Appointment scheduling assistant</p>
        </div>
        <PatientPicker value={patientId} onChange={setPatientId} />
      </header>
      <div className="min-h-0 flex-1">
        <ChatWindow patientId={patientId} />
      </div>
    </div>
  )
}
