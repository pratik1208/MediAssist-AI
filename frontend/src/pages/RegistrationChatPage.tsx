import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import OtpInput from '../components/OtpInput'
import ProgressSteps from '../components/ProgressSteps'
import SlotPicker from '../components/SlotPicker'
import { createAppointment, getDoctors, streamChat } from '../lib/api'
import {
  getRegistrationStatus,
  requestOtp,
  startRegistration,
  streamRegistrationChat,
  uploadDocument,
  verifyOtp,
} from '../lib/registrationApi'
import type { RegistrationStage, UiHint } from '../lib/registrationApi'
import type { ChatMessage, ChatResult, Slot } from '../lib/types'

interface TextBubble {
  id: number
  kind: 'user' | 'assistant' | 'note' | 'success' | 'error'
  text: string
}

interface SlotsBubble {
  id: number
  kind: 'slots'
  result: Extract<ChatResult, { type: 'slots' }>
  booked: boolean
}

type Bubble = TextBubble | SlotsBubble

const STORAGE_KEY = 'mediassist.registration'

const OTP_ERRORS: Record<string, string> = {
  otp_invalid: "That code isn't right — please check and try again.",
  otp_expired: 'That code has expired — request a new one below.',
  otp_too_many_attempts: 'Too many attempts — request a new code below.',
  otp_missing: 'No active code — request one below.',
}

let nextId = 1

const GREETING: TextBubble = {
  id: 0,
  kind: 'assistant',
  text:
    "Welcome to MediAssist! I'll help you register as a patient. " +
    'To get started, could you tell me your full name?',
}

export default function RegistrationChatPage() {
  const [token, setToken] = useState<string | null>(null)
  const [items, setItems] = useState<Bubble[]>([GREETING])
  const [stage, setStage] = useState<RegistrationStage>('demographics')
  const [hints, setHints] = useState<UiHint[]>([])
  const [complete, setComplete] = useState(false)
  const [patientId, setPatientId] = useState<number | null>(null)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [streamText, setStreamText] = useState('')
  const [otpSent, setOtpSent] = useState(false)
  const [otpBusy, setOtpBusy] = useState(false)
  const [startError, setStartError] = useState(false)
  // After registration completes, "Book an appointment" keeps the same chat
  // going in scheduling mode instead of navigating away to /schedule.
  const [booking, setBooking] = useState(false)
  const [schedHistory, setSchedHistory] = useState<ChatMessage[]>([])
  const [bookingBusy, setBookingBusy] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  // Start (or restore) the registration session.
  useEffect(() => {
    const saved = sessionStorage.getItem(STORAGE_KEY)
    if (saved) {
      const state = JSON.parse(saved)
      setToken(state.token)
      setItems(state.items)
      setStage(state.stage)
      setHints(state.hints ?? [])
      setComplete(state.complete ?? false)
      setPatientId(state.patientId ?? null)
      setOtpSent(state.otpSent ?? false)
      setBooking(state.booking ?? false)
      setSchedHistory(state.schedHistory ?? [])
      nextId = state.items.length + 1
      return
    }
    startRegistration()
      .then((session) => setToken(session.session_token))
      .catch(() => setStartError(true))
  }, [])

  // Persist so a page refresh doesn't restart registration.
  useEffect(() => {
    if (token) {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(
        { token, items, stage, hints, complete, patientId, otpSent, booking, schedHistory },
      ))
    }
  }, [token, items, stage, hints, complete, patientId, otpSent, booking, schedHistory])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [items, streamText])

  const append = (kind: TextBubble['kind'], text: string) =>
    setItems((prev) => [...prev, { id: nextId++, kind, text }])

  const needsOtp = hints.includes('otp_required') && !complete
  const uploadHint = hints.find(
    (h): h is { upload: string } => typeof h === 'object' && 'upload' in h,
  )

  // The backend expects the UI to trigger the code send when it sees the hint.
  useEffect(() => {
    if (needsOtp && !otpSent && token) {
      requestOtp(token)
        .then(() => {
          setOtpSent(true)
          append('note', 'A 6-digit verification code has been sent to your phone.')
        })
        .catch(() => append('error', "Couldn't send the verification code — try again shortly."))
    }
  }, [needsOtp, otpSent, token])

  // Scheduling mode: same window, but messages go to the (stateless)
  // scheduling agent, which replies with either text or bookable slots.
  const sendScheduling = async (text: string) => {
    if (sending) return
    append('user', text)
    const history = [...schedHistory, { role: 'user' as const, content: text }]
    setSchedHistory(history)
    setSending(true)
    try {
      await streamChat(history, (result) => {
        if (result.type === 'slots') {
          setItems((prev) => [...prev, { id: nextId++, kind: 'slots', result, booked: false }])
          setSchedHistory((h) => [...h, {
            role: 'assistant',
            content: `Offered appointment slots with ${result.doctor} (${result.specialty}).`,
          }])
        } else {
          append('assistant', result.message)
          setSchedHistory((h) => [...h, { role: 'assistant', content: result.message }])
        }
      })
    } catch {
      append('error', "Sorry — I couldn't reach the clinic system. Please try again.")
    } finally {
      setSending(false)
    }
  }

  const startBooking = () => {
    if (booking) return
    setBooking(true)
    append('assistant',
      "Great — let's book your appointment right here. Describe your symptoms " +
      "and when you'd like to come in — for example: \"I've had a mild fever " +
      'since yesterday, can I see someone tomorrow morning?"')
  }

  const bookSlot = async (bubble: SlotsBubble, slot: Slot) => {
    if (bookingBusy) return
    if (patientId === null) {
      append('error', "We couldn't find your patient record — please refresh and try again.")
      return
    }
    setBookingBusy(true)
    try {
      const doctors = await getDoctors()
      const doctor = doctors.find((d) => d.name === bubble.result.doctor)
      if (!doctor) {
        append('error', "Couldn't identify the doctor for this slot — please ask for times again.")
        return
      }
      const reason = schedHistory.find((m) => m.role === 'user')?.content
        ?? 'Appointment requested via chat'
      const appointment = await createAppointment({
        doctor: doctor.id,
        patient: patientId,
        start_time: slot[0],
        end_time: slot[1],
        reason,
        urgency: 'routine',
        source: 'scheduling',
      })
      setItems((prev) => prev.map((item) =>
        item.kind === 'slots' ? { ...item, booked: true } : item,
      ))
      const when = new Date(slot[0]).toLocaleString(undefined, {
        weekday: 'long', month: 'short', day: 'numeric',
        hour: 'numeric', minute: '2-digit',
      })
      append('success', `🎉 You're booked for ${when} (appointment #${appointment.id}). See you then!`)
    } catch {
      append('error', "That slot couldn't be booked — it may have just been taken. Please pick another time.")
    } finally {
      setBookingBusy(false)
    }
  }

  const send = async (text: string, visible = true) => {
    if (booking) {
      await sendScheduling(text)
      return
    }
    if (!token || sending) return
    if (visible) append('user', text)
    setSending(true)
    setStreamText('')
    let assembled = ''
    try {
      await streamRegistrationChat(token, text, (event) => {
        if ('delta' in event) {
          assembled += event.delta
          setStreamText(assembled)
        } else if ('done' in event) {
          setStage(event.stage)
          setHints(event.ui_hints)
          if (event.patient_id !== null) setPatientId(event.patient_id)
          if (event.registration_complete) setComplete(true)
        }
      })
      if (assembled) append('assistant', assembled)
    } catch (err: unknown) {
      const status_ = (err as { status?: number })?.status
      if (status_ === 401 || status_ === 403) {
        // The saved session no longer exists on the server (expired or
        // cleaned up) — a dead token can never recover, so start fresh
        // instead of failing on every message forever.
        sessionStorage.removeItem(STORAGE_KEY)
        window.location.reload()
        return
      }
      append('error', "Sorry — I couldn't reach the clinic system. Please try again.")
    } finally {
      setStreamText('')
      setSending(false)
    }
  }

  const submitOtp = async (code: string) => {
    if (!token) return
    setOtpBusy(true)
    try {
      const result = await verifyOtp(token, code)
      if (result.verified) {
        append('success', 'Identity verified ✓')
        setHints([])
        // Nudge the agent forward now that verification is on file.
        await send("I've entered my verification code.", false)
      }
    } catch (err: unknown) {
      const code_ = (err as { body?: { code?: string } })?.body?.code ?? ''
      append('error', OTP_ERRORS[code_] ?? 'Verification failed — please try again.')
      if (code_ === 'otp_expired' || code_ === 'otp_too_many_attempts') setOtpSent(false)
    } finally {
      setOtpBusy(false)
    }
  }

  const onFilePicked = async (file: File) => {
    if (!token) return
    const docType = uploadHint?.upload ?? 'insurance_card'
    try {
      const result = await uploadDocument(token, file, docType)
      if (result.policy_created) {
        append('success', '✓ Insurance card read — your policy is on file.')
        await send(`I've uploaded my ${docType.replace('_', ' ')} and it was read successfully.`, false)
      } else {
        append('note',
          "We saved your document but couldn't read the details from it. " +
          'Please type your insurance provider name and policy number instead — ' +
          'for example: "My provider is Star Health, policy number SH-12345".')
      }
    } catch {
      append('error', "The upload didn't go through — please try another image or PDF.")
    }
  }

  const restart = () => {
    sessionStorage.removeItem(STORAGE_KEY)
    window.location.reload()
  }

  const checkStatus = async () => {
    if (!token) return
    const status = await getRegistrationStatus(token)
    append('note', status.missing.length
      ? `Still to do: ${status.missing.join(', ')}.`
      : `Registration status: ${status.registration_status}.`)
  }

  const bubbleClass: Record<Bubble['kind'], string> = {
    user: 'ml-auto bg-teal-600 text-white',
    assistant: 'mr-auto border border-slate-200 bg-white text-slate-800',
    note: 'mx-auto border border-slate-200 bg-slate-100 text-slate-600 text-center',
    success: 'mr-auto border border-green-300 bg-green-50 text-green-900',
    error: 'mr-auto border border-amber-300 bg-amber-50 text-amber-900',
    slots: 'mr-auto border border-slate-200 bg-white text-slate-800',
  }

  return (
    <div className="mx-auto flex h-screen max-w-3xl flex-col bg-slate-50">
      <header className="border-b border-slate-200 bg-white px-4 py-3">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-lg font-bold text-slate-900">MediAssist AI</h1>
            <p className="text-xs text-slate-500">Patient registration</p>
          </div>
          <nav className="flex items-center gap-3 text-sm">
            <button onClick={checkStatus} className="text-slate-500 hover:text-teal-700">
              Check status
            </button>
            <button onClick={restart} className="text-slate-500 hover:text-teal-700">
              Start over
            </button>
            <Link
              to="/schedule"
              state={{ patientId }}
              className="font-medium text-teal-700 hover:underline"
            >
              Book appointment →
            </Link>
          </nav>
        </div>
        <div className="mt-2">
          <ProgressSteps stage={stage} />
        </div>
      </header>

      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {startError && (
          <div className="mx-auto rounded-2xl border border-amber-300 bg-amber-50 px-4 py-2.5 text-center text-sm text-amber-900">
            Couldn't start a registration session — is the backend running on port 8001?
          </div>
        )}

        {items.map((item) => (
          <div
            key={item.id}
            className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm shadow-sm ${bubbleClass[item.kind]}`}
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
                  disabled={item.booked || bookingBusy}
                  onPick={(slot) => void bookSlot(item, slot)}
                />
              </>
            ) : (
              item.text
            )}
          </div>
        ))}

        {streamText && (
          <div className="mr-auto max-w-[85%] rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-800 shadow-sm">
            {streamText}
          </div>
        )}
        {sending && !streamText && (
          <div className="mr-auto max-w-[85%] rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-400 shadow-sm">
            <span className="animate-pulse">Thinking…</span>
          </div>
        )}

        {stage === 'duplicate_hold' && (
          <div className="mx-auto rounded-2xl border border-amber-300 bg-amber-50 px-4 py-2.5 text-center text-sm text-amber-900">
            A very similar record already exists. A staff member will review it
            before your registration continues.
          </div>
        )}

        {needsOtp && otpSent && (
          <div className="mr-auto rounded-2xl border border-teal-200 bg-teal-50 px-4 py-3 shadow-sm">
            <p className="text-sm font-medium text-teal-900">
              Enter your 6-digit verification code
            </p>
            <OtpInput disabled={otpBusy} onSubmit={submitOtp} />
            <button
              type="button"
              onClick={() => setOtpSent(false)}
              className="mt-2 text-xs text-teal-700 underline"
            >
              Resend code
            </button>
          </div>
        )}

        {complete && !booking && (
          <div className="mx-auto rounded-2xl border border-green-300 bg-green-50 px-4 py-3 text-center text-sm text-green-900">
            🎉 Registration complete! A clinician will review your information.{' '}
            <button type="button" onClick={startBooking} className="font-semibold underline">
              Book an appointment
            </button>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <form
        className="flex items-center gap-2 border-t border-slate-200 bg-white p-3"
        onSubmit={(e) => {
          e.preventDefault()
          const text = input.trim()
          if (text) {
            setInput('')
            void send(text)
          }
        }}
      >
        <input
          ref={fileInput}
          type="file"
          accept="image/*,.pdf"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0]
            e.target.value = ''
            if (file) void onFilePicked(file)
          }}
        />
        {!booking && (
        <button
          type="button"
          title={`Upload ${(uploadHint?.upload ?? 'insurance_card').replace('_', ' ')}`}
          onClick={() => fileInput.current?.click()}
          disabled={!token || sending}
          className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-600
                     transition hover:border-teal-600 hover:text-teal-700
                     disabled:cursor-not-allowed disabled:opacity-40"
        >
          📎
        </button>
        )}
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={
            booking
              ? 'Describe your symptoms and preferred time…'
              : token ? 'Type your answer…' : 'Starting session…'
          }
          disabled={!token}
          className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm
                     text-slate-900 focus:border-teal-600 focus:outline-none"
        />
        <button
          type="submit"
          disabled={!token || sending || input.trim() === ''}
          className="rounded-lg bg-teal-600 px-4 py-2 text-sm font-semibold text-white
                     transition hover:bg-teal-700 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Send
        </button>
      </form>
    </div>
  )
}
