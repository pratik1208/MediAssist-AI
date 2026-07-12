import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import { getDoctors, getPatients } from '../lib/api'
import { getReferralAuthorizations } from '../lib/priorauthApi'
import {
  acceptReferral,
  bookReferralVisit,
  getReferralTimeline,
  getSpecialistCandidates,
  markVisitCompleted,
  resumeReferral,
  uploadConsultationReportFile,
  uploadConsultationReportJson,
} from '../lib/referralsApi'

const PA_STATUS_STYLE: Record<string, string> = {
  approved: 'bg-green-100 text-green-800',
  denied: 'bg-red-100 text-red-800',
}

const STATUS_LABEL: Record<string, string> = {
  created: 'Created', accepted: 'Accepted', appointment_scheduled: 'Appointment scheduled',
  patient_confirmed: 'Patient confirmed', visit_completed: 'Visit completed',
  report_received: 'Report received', closed: 'Closed', stalled: 'Stalled',
}

export default function ReferralDetailPage() {
  const { id } = useParams()
  const referralId = Number(id)
  const queryClient = useQueryClient()
  const [reportMode, setReportMode] = useState<'json' | 'file'>('json')
  const [reportForm, setReportForm] = useState({
    diagnosis: '', treatment_plan: '', medications: '', followup_recommendations: '',
  })
  const [bookForm, setBookForm] = useState({ start: '', end: '' })
  const [confirmingDoctorId, setConfirmingDoctorId] = useState('')
  const [actionError, setActionError] = useState('')

  const timeline = useQuery({
    queryKey: ['referralTimeline', referralId],
    queryFn: () => getReferralTimeline(referralId),
    refetchInterval: 15_000,
  })
  const patients = useQuery({ queryKey: ['patients'], queryFn: getPatients })
  const doctors = useQuery({ queryKey: ['doctors'], queryFn: getDoctors })
  const candidates = useQuery({
    queryKey: ['referralCandidates', referralId],
    queryFn: () => getSpecialistCandidates(referralId),
    enabled: timeline.data?.status === 'created',
  })
  const authorizations = useQuery({
    queryKey: ['referralAuthorizations', referralId],
    queryFn: () => getReferralAuthorizations(referralId),
    enabled: !!timeline.data,
  })

  const refresh = () => {
    setActionError('')
    void queryClient.invalidateQueries({ queryKey: ['referralTimeline', referralId] })
    void queryClient.invalidateQueries({ queryKey: ['referralQueue'] })
  }
  const onError = (label: string) => () =>
    setActionError(`${label} didn't go through — please check and try again.`)

  const accept = useMutation({
    mutationFn: (specialistId: number) =>
      acceptReferral(referralId, specialistId, confirmingDoctorId ? Number(confirmingDoctorId) : undefined),
    onSuccess: refresh, onError: onError('Accepting'),
  })
  const resume = useMutation({
    mutationFn: () => resumeReferral(referralId),
    onSuccess: refresh, onError: onError('Resuming'),
  })
  const book = useMutation({
    mutationFn: () => bookReferralVisit(referralId, new Date(bookForm.start).toISOString(),
                                       new Date(bookForm.end).toISOString()),
    onSuccess: refresh, onError: onError('Booking'),
  })
  const visitCompleted = useMutation({
    mutationFn: () => markVisitCompleted(referralId),
    onSuccess: refresh, onError: onError('Marking the visit complete'),
  })
  const submitJsonReport = useMutation({
    mutationFn: () => uploadConsultationReportJson(referralId, {
      diagnosis: reportForm.diagnosis,
      treatment_plan: reportForm.treatment_plan,
      medications: reportForm.medications.split(',').map((s) => s.trim()).filter(Boolean),
      followup_recommendations: reportForm.followup_recommendations
        .split(',').map((s) => s.trim()).filter(Boolean),
    }),
    onSuccess: refresh, onError: onError('Closing the loop'),
  })
  const submitFileReport = useMutation({
    mutationFn: (file: File) => uploadConsultationReportFile(referralId, file),
    onSuccess: refresh,
    onError: () => setActionError(
      "Couldn't read that report reliably — try a clearer scan, or switch to typing the details in.",
    ),
  })

  const patientName = (pid: number) => {
    const p = patients.data?.find((p) => p.id === pid)
    return p ? `${p.first_name} ${p.last_name}` : `#${pid}`
  }

  if (timeline.isPending) return <p className="p-6 text-sm text-slate-400">Loading…</p>
  if (timeline.isError) {
    const forbidden = (timeline.error as { status?: number })?.status === 403
    return (
      <div className="mx-auto max-w-2xl p-6">
        {forbidden ? (
          <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
            This page is for clinic staff. Log into the{' '}
            <a href="http://localhost:8001/admin/" target="_blank" rel="noreferrer"
               className="font-semibold underline">Django admin</a>{' '}
            with a staff account, then reload.
          </div>
        ) : (
          <p className="text-sm text-amber-700">Couldn't load this referral.</p>
        )}
      </div>
    )
  }

  const r = timeline.data!

  return (
    <div className="mx-auto min-h-screen max-w-3xl bg-slate-50 px-4 py-6">
      <Link to="/staff/referrals" className="text-sm text-teal-700 hover:underline">
        ← All referrals
      </Link>

      <header className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-xl font-bold text-slate-900">
            {patientName(r.patient_id)} → {r.specialty_needed}
          </h1>
          <p className="text-sm text-slate-500">{r.reason} · urgency: {r.urgency}</p>
        </div>
        <span className={`rounded-full px-3 py-1 text-xs font-semibold ${
          r.stalled ? 'bg-red-600 text-white' : 'bg-slate-200 text-slate-700'
        }`}>
          {r.stalled ? '⚠ stalled' : STATUS_LABEL[r.status]}
        </span>
      </header>

      {/* -- PA status column (Phase 5): any authorizations tied to orders
           linked to this referral -- */}
      {(authorizations.data?.length ?? 0) > 0 && (
        <section className="mt-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-700">Prior authorization</h2>
          <div className="mt-2 space-y-1">
            {authorizations.data!.map((a) => (
              <Link
                key={a.id}
                to={`/staff/priorauth/${a.id}`}
                className="flex items-center justify-between rounded-lg px-2 py-1 text-sm
                           hover:bg-slate-50"
              >
                <span className="text-slate-700">{a.treatment ?? a.order_type}</span>
                <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                  PA_STATUS_STYLE[a.status] ?? 'bg-slate-200 text-slate-700'
                }`}>
                  {a.status_display}
                </span>
              </Link>
            ))}
          </div>
        </section>
      )}

      {/* -- timeline -- */}
      <section className="mt-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <h2 className="text-sm font-semibold text-slate-700">Timeline</h2>
        <ol className="mt-2 space-y-1">
          {r.status_history.map((entry, i) => (
            <li key={i} className="flex justify-between text-sm text-slate-600">
              <span>{STATUS_LABEL[entry.status] ?? entry.status}</span>
              <span className="text-xs text-slate-400">{new Date(entry.at).toLocaleString()}</span>
            </li>
          ))}
        </ol>
      </section>

      {actionError && (
        <p className="mt-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          {actionError}
        </p>
      )}

      {/* -- stalled: must resume before anything else -- */}
      {r.stalled && (
        <section className="mt-4 rounded-xl border border-red-300 bg-red-50 p-4">
          <p className="text-sm text-red-900">
            This referral has been incomplete too long and needs attention.
          </p>
          <button
            onClick={() => resume.mutate()}
            disabled={resume.isPending}
            className="mt-2 rounded-lg bg-red-600 px-3 py-1.5 text-xs font-semibold text-white
                       transition hover:bg-red-700 disabled:opacity-40"
          >
            Resume where it left off
          </button>
        </section>
      )}

      {/* -- specialist-side (simulated): accept -- */}
      {!r.stalled && r.status === 'created' && (
        <section className="mt-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          {r.referring_doctor === null && (
            <div className="mb-3 rounded-lg border border-amber-300 bg-amber-50 p-3">
              <p className="text-sm text-amber-900">
                🩺 This referral was auto-suggested from a symptom check — a physician must
                confirm it before it can proceed.
              </p>
              <label className="mt-2 block text-sm text-amber-900">
                Confirming physician
                <select
                  value={confirmingDoctorId}
                  onChange={(e) => setConfirmingDoctorId(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-amber-300 px-3 py-2 text-sm"
                >
                  <option value="">— select —</option>
                  {doctors.data?.map((d) => (
                    <option key={d.id} value={d.id}>{d.name}</option>
                  ))}
                </select>
              </label>
            </div>
          )}

          <h2 className="text-sm font-semibold text-slate-700">Matched specialists</h2>
          {candidates.isPending && <p className="mt-2 text-sm text-slate-400">Finding matches…</p>}
          {candidates.data?.length === 0 && (
            <p className="mt-2 text-sm text-amber-700">No matching specialists on file.</p>
          )}
          <div className="mt-2 space-y-2">
            {candidates.data?.map((c) => (
              <div key={c.id} className="flex items-center justify-between rounded-lg border
                                          border-slate-200 p-3 text-sm">
                <div>
                  <p className="font-medium text-slate-900">{c.name}</p>
                  <p className="text-xs text-slate-500">
                    {c.practice_name} · {c.address.area ?? c.address.city ?? ''}
                    {c.consultation_fee && ` · ₹${c.consultation_fee}`}
                  </p>
                </div>
                <button
                  onClick={() => accept.mutate(c.id)}
                  disabled={accept.isPending || (r.referring_doctor === null && !confirmingDoctorId)}
                  title={r.referring_doctor === null && !confirmingDoctorId
                    ? 'Select a confirming physician first' : undefined}
                  className="rounded-lg bg-teal-600 px-3 py-1.5 text-xs font-semibold text-white
                             transition hover:bg-teal-700 disabled:opacity-40"
                >
                  Accept
                </button>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* -- book the visit -- */}
      {!r.stalled && r.status === 'accepted' && (
        <section className="mt-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-700">Book the specialist visit</h2>
          <form
            onSubmit={(e) => { e.preventDefault(); book.mutate() }}
            className="mt-2 flex flex-wrap items-end gap-2"
          >
            <label className="text-sm text-slate-600">
              Start
              <input type="datetime-local" required value={bookForm.start}
                     onChange={(e) => setBookForm({ ...bookForm, start: e.target.value })}
                     className="mt-1 block rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            </label>
            <label className="text-sm text-slate-600">
              End
              <input type="datetime-local" required value={bookForm.end}
                     onChange={(e) => setBookForm({ ...bookForm, end: e.target.value })}
                     className="mt-1 block rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            </label>
            <button type="submit" disabled={book.isPending}
                    className="rounded-lg bg-teal-600 px-3 py-2 text-xs font-semibold text-white
                               transition hover:bg-teal-700 disabled:opacity-40">
              Book visit
            </button>
          </form>
        </section>
      )}

      {r.status === 'appointment_scheduled' && !r.stalled && (
        <p className="mt-4 rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-600">
          Waiting for the patient to confirm their appointment.
        </p>
      )}

      {/* -- specialist-side (simulated): visit completed -- */}
      {!r.stalled && r.status === 'patient_confirmed' && (
        <section className="mt-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <button
            onClick={() => visitCompleted.mutate()}
            disabled={visitCompleted.isPending}
            className="rounded-lg bg-teal-600 px-3 py-2 text-sm font-semibold text-white
                       transition hover:bg-teal-700 disabled:opacity-40"
          >
            Mark visit completed
          </button>
        </section>
      )}

      {/* -- specialist-side (simulated): upload consultation report -- */}
      {!r.stalled && r.status === 'visit_completed' && (
        <section className="mt-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-700">Consultation report</h2>
            <button
              onClick={() => setReportMode(reportMode === 'json' ? 'file' : 'json')}
              className="text-xs text-teal-700 underline"
            >
              {reportMode === 'json' ? 'Upload a file instead' : 'Type it in instead'}
            </button>
          </div>

          {reportMode === 'json' ? (
            <form
              onSubmit={(e) => { e.preventDefault(); submitJsonReport.mutate() }}
              className="mt-2 space-y-2"
            >
              <input
                required placeholder="Diagnosis" value={reportForm.diagnosis}
                onChange={(e) => setReportForm({ ...reportForm, diagnosis: e.target.value })}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
              <input
                placeholder="Treatment plan" value={reportForm.treatment_plan}
                onChange={(e) => setReportForm({ ...reportForm, treatment_plan: e.target.value })}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
              <input
                placeholder="Medications (comma-separated)" value={reportForm.medications}
                onChange={(e) => setReportForm({ ...reportForm, medications: e.target.value })}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
              <input
                placeholder="Follow-up recommendations (comma-separated)"
                value={reportForm.followup_recommendations}
                onChange={(e) => setReportForm({ ...reportForm, followup_recommendations: e.target.value })}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
              <button type="submit" disabled={submitJsonReport.isPending}
                      className="rounded-lg bg-teal-600 px-3 py-2 text-xs font-semibold text-white
                                 transition hover:bg-teal-700 disabled:opacity-40">
                Close the loop
              </button>
            </form>
          ) : (
            <div className="mt-2">
              <input
                type="file" accept="image/*,.pdf"
                onChange={(e) => {
                  const file = e.target.files?.[0]
                  if (file) submitFileReport.mutate(file)
                }}
                disabled={submitFileReport.isPending}
                className="text-sm"
              />
              <p className="mt-1 text-xs text-slate-400">
                AI reads the diagnosis, treatment plan, medications, and follow-ups off the page.
              </p>
            </div>
          )}
        </section>
      )}

      {(r.status === 'report_received' || r.status === 'closed') && (
        <p className="mt-4 rounded-lg border border-green-300 bg-green-50 p-4 text-sm text-green-900">
          🎉 Consultation report received — this referral is closed. The referring physician has
          been notified.
        </p>
      )}
    </div>
  )
}
