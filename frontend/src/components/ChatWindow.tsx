import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'

import { createAppointment, getDoctors, streamChat } from '../lib/api'
import type { ChatMessage, ChatResult, Slot } from '../lib/types'
import SlotPicker from './SlotPicker'

type ChatItem =
  | { id: number; kind: 'user'; text: string }
  | { id: number; kind: 'assistant'; text: string; tone?: 'emergency' | 'success' | 'error' }
  | { id: number; kind: 'slots'; result: Extract<ChatResult, { type: 'slots' }>; booked: boolean }

let nextId = 1

// Omit that distributes over each member of the ChatItem union (plain Omit
// would collapse the union and lose the per-kind fields).
type NewChatItem = ChatItem extends infer T
  ? T extends ChatItem
    ? Omit<T, 'id'>
    : never
  : never

/** Flatten the visible chat into the {role, content} history the API expects. */
function toConversation(items: ChatItem[]): ChatMessage[] {
  return items.map((item) => {
    if (item.kind === 'user') return { role: 'user' as const, content: item.text }
    if (item.kind === 'slots') {
      return {
        role: 'assistant' as const,
        content: `Offered appointment slots with ${item.result.doctor} (${item.result.specialty}).`,
      }
    }
    return { role: 'assistant' as const, content: item.text }
  })
}

interface Props {
  patientId: number | null
  /** Pre-filled composer text, e.g. handed off from the triage result. */
  initialInput?: string
}

export default function ChatWindow({ patientId, initialInput }: Props) {
  const [items, setItems] = useState<ChatItem[]>([])
  const [input, setInput] = useState(initialInput ?? '')
  const [sending, setSending] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  const doctors = useQuery({ queryKey: ['doctors'], queryFn: getDoctors })

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [items, sending])

  const append = (item: NewChatItem) =>
    setItems((prev) => [...prev, { ...item, id: nextId++ } as ChatItem])

  const handleResult = (result: ChatResult) => {
    if (result.type === 'slots') {
      append({ kind: 'slots', result, booked: false })
    } else {
      append({
        kind: 'assistant',
        text: result.message,
        tone: result.type === 'emergency' ? 'emergency' : undefined,
      })
    }
  }

  const send = async () => {
    const text = input.trim()
    if (!text || sending) return
    setInput('')
    const history = [...toConversation(items), { role: 'user' as const, content: text }]
    append({ kind: 'user', text })
    setSending(true)
    try {
      await streamChat(history, handleResult)
    } catch {
      append({
        kind: 'assistant',
        tone: 'error',
        text: "Sorry — I couldn't reach the clinic system. Please check that the backend is running and try again.",
      })
    } finally {
      setSending(false)
    }
  }

  const booking = useMutation({
    mutationFn: createAppointment,
    onSuccess: (appointment, variables) => {
      setItems((prev) =>
        prev.map((item) =>
          item.kind === 'slots' ? { ...item, booked: true } : item,
        ),
      )
      const when = new Date(variables.start_time).toLocaleString(undefined, {
        weekday: 'long', month: 'short', day: 'numeric',
        hour: 'numeric', minute: '2-digit',
      })
      append({
        kind: 'assistant',
        tone: 'success',
        text: `You're booked for ${when} (appointment #${appointment.id}). See you then!`,
      })
    },
    onError: () => {
      append({
        kind: 'assistant',
        tone: 'error',
        text: "That slot couldn't be booked — it may have just been taken. Please pick another time.",
      })
    },
  })

  const bookSlot = (item: Extract<ChatItem, { kind: 'slots' }>, slot: Slot) => {
    if (patientId === null) {
      append({
        kind: 'assistant',
        tone: 'error',
        text: 'Please choose a patient (top right) before booking a slot.',
      })
      return
    }
    const doctor = doctors.data?.find((d) => d.name === item.result.doctor)
    if (!doctor) {
      append({
        kind: 'assistant',
        tone: 'error',
        text: "Couldn't identify the doctor for this slot — please refresh and try again.",
      })
      return
    }
    const reason =
      items.find((i): i is Extract<ChatItem, { kind: 'user' }> => i.kind === 'user')
        ?.text ?? 'Appointment requested via chat'
    booking.mutate({
      doctor: doctor.id,
      patient: patientId,
      start_time: slot[0],
      end_time: slot[1],
      reason,
      urgency: 'routine',
      source: 'scheduling',
    })
  }

  const bubbleClass = (item: ChatItem): string => {
    if (item.kind === 'user') return 'ml-auto bg-teal-600 text-white'
    if (item.kind === 'assistant' && item.tone === 'emergency')
      return 'mr-auto border border-red-300 bg-red-50 text-red-800'
    if (item.kind === 'assistant' && item.tone === 'error')
      return 'mr-auto border border-amber-300 bg-amber-50 text-amber-900'
    if (item.kind === 'assistant' && item.tone === 'success')
      return 'mr-auto border border-green-300 bg-green-50 text-green-900'
    return 'mr-auto border border-slate-200 bg-white text-slate-800'
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {items.length === 0 && (
          <div className="mt-16 text-center text-slate-500">
            <p className="text-lg font-medium text-slate-700">
              Hi! I can help you book an appointment.
            </p>
            <p className="mt-1 text-sm">
              Describe your symptoms and when you'd like to come in — for
              example: “I've had a mild fever since yesterday, can I see
              someone tomorrow morning?”
            </p>
          </div>
        )}

        {items.map((item) => (
          <div
            key={item.id}
            className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm shadow-sm ${bubbleClass(item)}`}
          >
            {item.kind === 'slots' ? (
              <>
                <p>
                  {item.booked
                    ? `Slots with ${item.result.doctor} (${item.result.specialty}):`
                    : `Here are the available times with ${item.result.doctor} (${item.result.specialty}) — tap one to book:`}
                </p>
                <SlotPicker
                  slots={item.result.slots}
                  disabled={item.booked || booking.isPending}
                  onPick={(slot) => bookSlot(item, slot)}
                />
              </>
            ) : (
              item.text
            )}
          </div>
        ))}

        {sending && (
          <div className="mr-auto max-w-[85%] rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-400 shadow-sm">
            <span className="animate-pulse">Thinking…</span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <form
        className="flex gap-2 border-t border-slate-200 bg-white p-3"
        onSubmit={(e) => {
          e.preventDefault()
          void send()
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Describe your symptoms and preferred time…"
          className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm
                     text-slate-900 focus:border-teal-600 focus:outline-none"
        />
        <button
          type="submit"
          disabled={sending || input.trim() === ''}
          className="rounded-lg bg-teal-600 px-4 py-2 text-sm font-semibold text-white
                     transition hover:bg-teal-700 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Send
        </button>
      </form>
    </div>
  )
}
