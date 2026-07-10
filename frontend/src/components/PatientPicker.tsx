import { useQuery } from '@tanstack/react-query'

import { getPatients } from '../lib/api'

interface Props {
  value: number | null
  onChange: (patientId: number | null) => void
}

/**
 * The scheduling chat itself is anonymous; booking an appointment needs a
 * patient row. Until the registration UI provides a logged-in patient, pick
 * one of the seeded patients here.
 */
export default function PatientPicker({ value, onChange }: Props) {
  const { data, isPending, isError } = useQuery({
    queryKey: ['patients'],
    queryFn: getPatients,
  })

  if (isPending) {
    return <span className="text-sm text-slate-400">Loading patients…</span>
  }
  if (isError) {
    return (
      <span className="text-sm text-red-600">
        Couldn't load patients — is the backend running?
      </span>
    )
  }

  return (
    <label className="flex items-center gap-2 text-sm text-slate-600">
      Booking as
      <select
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
        className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm
                   text-slate-900 focus:border-teal-600 focus:outline-none"
      >
        <option value="">— select a patient —</option>
        {data.map((p) => (
          <option key={p.id} value={p.id}>
            {p.first_name} {p.last_name}
          </option>
        ))}
      </select>
    </label>
  )
}
