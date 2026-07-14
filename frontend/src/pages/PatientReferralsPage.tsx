import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import TriageAccessGate from '../components/TriageAccessGate'
import { getAppointment } from '../lib/api'
import { confirmReferral, getMyReferrals } from '../lib/referralsApi'
import {
  clearTriageSession,
  registrationSessionToken,
  sessionUnusable,
  triageSessionToken,
} from '../lib/session'

const STATUS_LABEL: Record<string, string> = {
  created: 'Reviewing your referral', accepted: 'Specialist confirmed',
  appointment_scheduled: 'Appointment scheduled', patient_confirmed: 'Visit confirmed',
  visit_completed: 'Visit completed', report_received: 'Report received',
  closed: 'Complete', stalled: 'Being followed up on',
}

// A generic, always-true prep note — we don't have specialist-specific
// prep instructions or directions on file yet, so this covers the basics
// rather than showing nothing.
const PREP_NOTE =
  "Bring a valid photo ID, your insurance card, and a list of your current " +
  'medications. Please arrive 15 minutes before your appointment time.'

function AppointmentTime({ appointmentId }: { appointmentId: number }) {
  const appt = useQuery({
    queryKey: ['appointment', appointmentId],
    queryFn: () => getAppointment(appointmentId),
  })
  if (!appt.data) return null
  return (
    <p className="text-sm text-slate-700">
      📅 {new Date(appt.data.start_time).toLocaleString(undefined, {
        weekday: 'long', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
      })}
    </p>
  )
}

export default function PatientReferralsPage() {
  const [token, setToken] = useState<string | null>(
    () => triageSessionToken() ?? registrationSessionToken(),
  )
  const [error, setError] = useState('')
  const queryClient = useQueryClient()

  const referrals = useQuery({
    queryKey: ['myReferrals'],
    queryFn: () => getMyReferrals(token!),
    enabled: token !== null,
    retry: false,
  })

  const authFailed = referrals.isError && sessionUnusable(referrals.error)
  if (authFailed && token !== null) {
    clearTriageSession()
    setToken(null)
  }

  const confirm = useMutation({
    mutationFn: (referralId: number) => confirmReferral(token!, referralId),
    onSuccess: () => {
      setError('')
      void queryClient.invalidateQueries({ queryKey: ['myReferrals'] })
    },
    onError: () => setError("Couldn't confirm — please try again."),
  })

  return (
    <div className="mx-auto min-h-screen max-w-3xl bg-slate-50 px-4 py-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">MediAssist AI</h1>
          <p className="text-sm text-slate-500">Specialist referrals</p>
        </div>
        <nav className="flex items-center gap-3 text-sm">
          <Link to="/refills" className="font-medium text-teal-700 hover:underline">
            Refills
          </Link>
          <Link to="/authorizations" className="font-medium text-teal-700 hover:underline">
            Authorizations
          </Link>
          <Link to="/schedule" className="font-medium text-teal-700 hover:underline">
            Book appointment →
          </Link>
        </nav>
      </header>

      {!token ? (
        <div className="mt-6 overflow-hidden rounded-xl border border-slate-200 bg-white">
          <TriageAccessGate onReady={setToken} />
        </div>
      ) : (
        <main className="mt-6 space-y-3">
          {referrals.isPending && <p className="text-sm text-slate-400">Loading your referrals…</p>}
          {referrals.isError && !authFailed && (
            <p className="text-sm text-amber-700">Couldn't load your referrals — is the backend running?</p>
          )}
          {referrals.data?.length === 0 && (
            <p className="rounded-xl border border-slate-200 bg-white p-6 text-center text-sm text-slate-500">
              No specialist referrals on file yet.
            </p>
          )}

          {referrals.data?.map((r) => (
            <article key={r.id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="text-sm font-semibold text-slate-900">{r.specialty_needed}</p>
                  {r.specialist && <p className="text-xs text-slate-500">with {r.specialist}</p>}
                </div>
                <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                  r.stalled ? 'bg-amber-100 text-amber-800' : 'bg-teal-100 text-teal-800'
                }`}>
                  {STATUS_LABEL[r.status] ?? r.status}
                </span>
              </div>

              {r.appointment_id && <div className="mt-2"><AppointmentTime appointmentId={r.appointment_id} /></div>}

              {r.status === 'appointment_scheduled' && (
                <div className="mt-3 rounded-lg border border-teal-200 bg-teal-50 p-3">
                  <p className="text-sm text-teal-900">Please confirm you'll attend this visit.</p>
                  <button
                    onClick={() => confirm.mutate(r.id)}
                    disabled={confirm.isPending}
                    className="mt-2 rounded-lg bg-teal-600 px-3 py-1.5 text-xs font-semibold text-white
                               transition hover:bg-teal-700 disabled:opacity-40"
                  >
                    Confirm my visit
                  </button>
                </div>
              )}

              {['appointment_scheduled', 'patient_confirmed'].includes(r.status) && (
                <p className="mt-2 text-xs text-slate-500">{PREP_NOTE}</p>
              )}

              {r.status === 'closed' && (
                <p className="mt-2 text-xs text-green-700">
                  🎉 Your specialist's report is on file — your doctor has been notified.
                </p>
              )}
            </article>
          ))}

          {error && <p className="text-sm text-amber-700">{error}</p>}
        </main>
      )}
    </div>
  )
}
