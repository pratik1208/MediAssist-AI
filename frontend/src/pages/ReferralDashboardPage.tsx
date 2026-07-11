import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { getDoctors, getPatients } from '../lib/api'
import {
  createReferral,
  getReferralQueue,
  SPECIALTIES,
  URGENCIES,
} from '../lib/referralsApi'
import type { ReferralStatus } from '../lib/referralsApi'

const STATUS_STYLE: Record<ReferralStatus, string> = {
  created: 'bg-slate-200 text-slate-700',
  accepted: 'bg-sky-100 text-sky-800',
  appointment_scheduled: 'bg-sky-100 text-sky-800',
  patient_confirmed: 'bg-teal-100 text-teal-800',
  visit_completed: 'bg-teal-100 text-teal-800',
  report_received: 'bg-teal-100 text-teal-800',
  closed: 'bg-green-100 text-green-800',
  stalled: 'bg-red-600 text-white',
}

const EMPTY_FORM = { patient_id: '', doctor_id: '', specialty: SPECIALTIES[0],
                     reason: '', urgency: 'routine' }

export default function ReferralDashboardPage() {
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<{
    patient_id: string; doctor_id: string; specialty: string; reason: string; urgency: string
  }>(EMPTY_FORM)
  const [statusFilter, setStatusFilter] = useState('')
  const [formError, setFormError] = useState('')
  const queryClient = useQueryClient()

  const referrals = useQuery({
    queryKey: ['referralQueue', statusFilter],
    queryFn: () => getReferralQueue(statusFilter || undefined),
    refetchInterval: 15_000,
  })
  const patients = useQuery({ queryKey: ['patients'], queryFn: getPatients })
  const doctors = useQuery({ queryKey: ['doctors'], queryFn: getDoctors })

  const create = useMutation({
    mutationFn: createReferral,
    onSuccess: () => {
      setForm(EMPTY_FORM)
      setShowForm(false)
      setFormError('')
      void queryClient.invalidateQueries({ queryKey: ['referralQueue'] })
    },
    onError: () => setFormError("Couldn't create the referral — check the fields and try again."),
  })

  const patientName = (id: number) => {
    const p = patients.data?.find((p) => p.id === id)
    return p ? `${p.first_name} ${p.last_name}` : `#${id}`
  }

  const forbidden =
    referrals.isError && (referrals.error as { status?: number })?.status === 403

  return (
    <div className="mx-auto min-h-screen max-w-5xl bg-slate-50 px-4 py-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Referral pipeline</h1>
          <p className="text-sm text-slate-500">
            Create referrals and track them from created to closed
          </p>
        </div>
        <nav className="flex items-center gap-4 text-sm">
          <Link to="/staff/refills" className="font-medium text-teal-700 hover:underline">
            Refill approvals →
          </Link>
          <Link to="/staff/escalations" className="font-medium text-teal-700 hover:underline">
            Escalation queue →
          </Link>
          <button
            onClick={() => setShowForm((v) => !v)}
            className="rounded-lg bg-teal-600 px-3 py-1.5 text-sm font-semibold text-white
                       transition hover:bg-teal-700"
          >
            + New Referral
          </button>
        </nav>
      </header>

      {showForm && (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (!form.patient_id || !form.doctor_id || !form.reason.trim()) {
              setFormError('Please fill in patient, referring doctor, and reason.')
              return
            }
            create.mutate({
              patient_id: Number(form.patient_id), doctor_id: Number(form.doctor_id),
              specialty: form.specialty, reason: form.reason.trim(), urgency: form.urgency,
            })
          }}
          className="mt-4 grid grid-cols-1 gap-3 rounded-xl border border-slate-200 bg-white p-4
                     shadow-sm sm:grid-cols-2"
        >
          <label className="text-sm text-slate-600">
            Patient
            <select
              value={form.patient_id}
              onChange={(e) => setForm({ ...form, patient_id: e.target.value })}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
            >
              <option value="">— select —</option>
              {patients.data?.map((p) => (
                <option key={p.id} value={p.id}>{p.first_name} {p.last_name}</option>
              ))}
            </select>
          </label>
          <label className="text-sm text-slate-600">
            Referring doctor
            <select
              value={form.doctor_id}
              onChange={(e) => setForm({ ...form, doctor_id: e.target.value })}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
            >
              <option value="">— select —</option>
              {doctors.data?.map((d) => (
                <option key={d.id} value={d.id}>{d.name}</option>
              ))}
            </select>
          </label>
          <label className="text-sm text-slate-600">
            Specialty needed
            <select
              value={form.specialty}
              onChange={(e) => setForm({ ...form, specialty: e.target.value })}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
            >
              {SPECIALTIES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label className="text-sm text-slate-600">
            Urgency
            <select
              value={form.urgency}
              onChange={(e) => setForm({ ...form, urgency: e.target.value })}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
            >
              {URGENCIES.map((u) => <option key={u} value={u}>{u}</option>)}
            </select>
          </label>
          <label className="text-sm text-slate-600 sm:col-span-2">
            Reason
            <input
              value={form.reason}
              onChange={(e) => setForm({ ...form, reason: e.target.value })}
              placeholder="e.g. chest pain on exertion"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
            />
          </label>
          <div className="sm:col-span-2">
            <button
              type="submit"
              disabled={create.isPending}
              className="rounded-lg bg-teal-600 px-4 py-2 text-sm font-semibold text-white
                         transition hover:bg-teal-700 disabled:opacity-40"
            >
              Create referral
            </button>
            {formError && <span className="ml-3 text-sm text-amber-700">{formError}</span>}
          </div>
        </form>
      )}

      <div className="mt-6 flex items-center gap-2 text-sm">
        <label className="text-slate-600">Filter:</label>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-md border border-slate-300 px-2 py-1 text-sm text-slate-900"
        >
          <option value="">All statuses</option>
          {Object.keys(STATUS_STYLE).map((s) => (
            <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>
          ))}
        </select>
      </div>

      <main className="mt-3 space-y-2">
        {referrals.isPending && <p className="text-sm text-slate-400">Loading referrals…</p>}

        {forbidden && (
          <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
            This page is for clinic staff. Log into the{' '}
            <a href="http://localhost:8001/admin/" target="_blank" rel="noreferrer"
               className="font-semibold underline">
              Django admin
            </a>{' '}
            with a staff account in this browser, then reload this page.
          </div>
        )}
        {referrals.isError && !forbidden && (
          <p className="text-sm text-amber-700">Couldn't load referrals — is the backend running?</p>
        )}
        {referrals.data?.length === 0 && (
          <p className="rounded-xl border border-slate-200 bg-white p-6 text-center text-sm text-slate-500">
            No referrals yet.
          </p>
        )}

        {referrals.data?.map((r) => (
          <Link
            key={r.id}
            to={`/staff/referrals/${r.id}`}
            className={`block rounded-xl border p-4 shadow-sm transition hover:shadow-md ${
              r.stalled ? 'border-red-400 bg-red-50' : 'border-slate-200 bg-white'
            }`}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-slate-900">
                  {patientName(r.patient_id)}
                </span>
                <span className="text-sm text-slate-600">→ {r.specialty_needed}</span>
                {r.specialist && <span className="text-xs text-slate-400">with {r.specialist}</span>}
                {r.referring_doctor === null && (
                  <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800">
                    🩺 from triage — needs confirmation
                  </span>
                )}
              </div>
              <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${STATUS_STYLE[r.status]}`}>
                {r.stalled ? '⚠ stalled' : r.status_display}
              </span>
            </div>
            <p className="mt-1 text-xs text-slate-400">
              {r.reason} · {r.urgency} · created {new Date(r.created_at).toLocaleDateString()}
            </p>
          </Link>
        ))}
      </main>
    </div>
  )
}
