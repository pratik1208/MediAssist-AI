import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { getDoctors, getPatients } from '../lib/api'
import {
  createTreatmentOrder,
  getAuthorizationQueue,
  ORDER_TYPES,
} from '../lib/priorauthApi'
import type { AuthorizationStatus } from '../lib/priorauthApi'

const STATUS_STYLE: Record<AuthorizationStatus, string> = {
  detected: 'bg-slate-200 text-slate-700',
  gathering_evidence: 'bg-slate-200 text-slate-700',
  ready_for_review: 'bg-amber-100 text-amber-800',
  submitted: 'bg-sky-100 text-sky-800',
  under_review: 'bg-sky-100 text-sky-800',
  info_requested: 'bg-amber-100 text-amber-800',
  approved: 'bg-green-100 text-green-800',
  denied: 'bg-red-100 text-red-800',
}

const EMPTY_FORM = { patient_id: '', doctor_id: '', order_type: ORDER_TYPES[0] as string,
                     cpt_code: '', icd10_code: '', medication: '' }

export default function PriorAuthQueuePage() {
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [statusFilter, setStatusFilter] = useState('')
  const [formError, setFormError] = useState('')
  const [formResult, setFormResult] = useState('')
  const queryClient = useQueryClient()

  const queue = useQuery({
    queryKey: ['authorizationQueue', statusFilter],
    queryFn: () => getAuthorizationQueue(statusFilter || undefined),
    refetchInterval: 15_000,
  })
  const patients = useQuery({ queryKey: ['patients'], queryFn: getPatients })
  const doctors = useQuery({ queryKey: ['doctors'], queryFn: getDoctors })

  const create = useMutation({
    mutationFn: createTreatmentOrder,
    onSuccess: (result) => {
      setFormError('')
      setFormResult(
        result.authorization_required
          ? `Order #${result.order_id} created — authorization required (status: ${result.status}).`
          : `Order #${result.order_id} created — no authorization required.`,
      )
      setForm(EMPTY_FORM)
      void queryClient.invalidateQueries({ queryKey: ['authorizationQueue'] })
    },
    onError: () => setFormError("Couldn't create the order — check the fields and try again."),
  })

  const patientName = (id: number) => {
    const p = patients.data?.find((p) => p.id === id)
    return p ? `${p.first_name} ${p.last_name}` : `#${id}`
  }

  const forbidden = queue.isError && (queue.error as { status?: number })?.status === 403

  return (
    <div className="mx-auto min-h-screen max-w-5xl bg-slate-50 px-4 py-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Prior authorizations</h1>
          <p className="text-sm text-slate-500">
            Treatment orders and their insurance authorization status
          </p>
        </div>
        <nav className="flex items-center gap-4 text-sm">
          <Link to="/staff/priorauth/tasks" className="font-medium text-teal-700 hover:underline">
            Staged tasks →
          </Link>
          <Link to="/staff/referrals" className="font-medium text-teal-700 hover:underline">
            Referrals →
          </Link>
          <button
            onClick={() => setShowForm((v) => !v)}
            className="rounded-lg bg-teal-600 px-3 py-1.5 text-sm font-semibold text-white
                       transition hover:bg-teal-700"
          >
            + New Order
          </button>
        </nav>
      </header>

      {showForm && (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (!form.patient_id) {
              setFormError('Please select a patient.')
              return
            }
            setFormResult('')
            create.mutate({
              patient_id: Number(form.patient_id),
              doctor_id: form.doctor_id ? Number(form.doctor_id) : undefined,
              order_type: form.order_type,
              cpt_code: form.cpt_code.trim() || undefined,
              icd10_code: form.icd10_code.trim() || undefined,
              medication: form.medication.trim() || undefined,
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
            Ordering doctor (optional)
            <select
              value={form.doctor_id}
              onChange={(e) => setForm({ ...form, doctor_id: e.target.value })}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
            >
              <option value="">— none —</option>
              {doctors.data?.map((d) => (
                <option key={d.id} value={d.id}>{d.name}</option>
              ))}
            </select>
          </label>
          <label className="text-sm text-slate-600">
            Order type
            <select
              value={form.order_type}
              onChange={(e) => setForm({ ...form, order_type: e.target.value })}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
            >
              {ORDER_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </label>
          <div />
          <label className="text-sm text-slate-600">
            CPT code
            <input
              value={form.cpt_code}
              onChange={(e) => setForm({ ...form, cpt_code: e.target.value })}
              placeholder="e.g. 70551"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
            />
          </label>
          <label className="text-sm text-slate-600">
            ICD-10 code
            <input
              value={form.icd10_code}
              onChange={(e) => setForm({ ...form, icd10_code: e.target.value })}
              placeholder="e.g. M25.561"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
            />
          </label>
          <label className="text-sm text-slate-600 sm:col-span-2">
            Medication
            <input
              value={form.medication}
              onChange={(e) => setForm({ ...form, medication: e.target.value })}
              placeholder="e.g. atorvastatin 20mg"
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
              Create order
            </button>
            {formError && <span className="ml-3 text-sm text-amber-700">{formError}</span>}
            {formResult && <span className="ml-3 text-sm text-teal-700">{formResult}</span>}
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
        {queue.isPending && <p className="text-sm text-slate-400">Loading requests…</p>}

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
        {queue.isError && !forbidden && (
          <p className="text-sm text-amber-700">Couldn't load requests — is the backend running?</p>
        )}
        {queue.data?.length === 0 && (
          <p className="rounded-xl border border-slate-200 bg-white p-6 text-center text-sm text-slate-500">
            No authorization requests yet.
          </p>
        )}

        {queue.data?.map((r) => (
          <Link
            key={r.id}
            to={`/staff/priorauth/${r.id}`}
            className="block rounded-xl border border-slate-200 bg-white p-4 shadow-sm
                       transition hover:shadow-md"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-slate-900">
                  {patientName(r.patient_id)}
                </span>
                <span className="text-sm text-slate-600">· {r.order_type}</span>
                {r.treatment && <span className="text-xs text-slate-400">({r.treatment})</span>}
              </div>
              <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${STATUS_STYLE[r.status]}`}>
                {r.status_display}
              </span>
            </div>
            {r.denial_reason && (
              <p className="mt-1 text-xs text-red-700">Denied: {r.denial_reason}</p>
            )}
            <p className="mt-1 text-xs text-slate-400">
              created {new Date(r.created_at).toLocaleDateString()}
              {r.external_reference && ` · ref ${r.external_reference}`}
            </p>
          </Link>
        ))}
      </main>
    </div>
  )
}
