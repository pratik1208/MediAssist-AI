import type { Slot } from '../lib/types'

function formatSlot([start, end]: Slot): string {
  const s = new Date(start)
  const e = new Date(end)
  const day = s.toLocaleDateString(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  })
  const time = (d: Date) =>
    d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
  return `${day}, ${time(s)} – ${time(e)}`
}

interface Props {
  slots: Slot[]
  disabled: boolean
  onPick: (slot: Slot) => void
}

export default function SlotPicker({ slots, disabled, onPick }: Props) {
  if (slots.length === 0) {
    return (
      <p className="mt-2 text-sm text-slate-500">
        No open slots in that window — try asking for another day or time.
      </p>
    )
  }
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {slots.map((slot) => (
        <button
          key={slot[0]}
          type="button"
          disabled={disabled}
          onClick={() => onPick(slot)}
          className="rounded-lg border border-teal-600 px-3 py-1.5 text-sm font-medium
                     text-teal-700 transition hover:bg-teal-600 hover:text-white
                     disabled:cursor-not-allowed disabled:opacity-40"
        >
          {formatSlot(slot)}
        </button>
      ))}
    </div>
  )
}
