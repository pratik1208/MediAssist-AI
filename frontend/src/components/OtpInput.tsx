import { useRef, useState } from 'react'

interface Props {
  disabled: boolean
  onSubmit: (code: string) => void
}

/** Six single-digit boxes with auto-advance; submits when all are filled. */
export default function OtpInput({ disabled, onSubmit }: Props) {
  const [digits, setDigits] = useState<string[]>(Array(6).fill(''))
  const boxes = useRef<(HTMLInputElement | null)[]>([])

  const update = (index: number, raw: string) => {
    // Accept a full code pasted into any box.
    const pasted = raw.replace(/\D/g, '')
    const next = [...digits]
    if (pasted.length > 1) {
      for (let i = 0; i < 6 - index && i < pasted.length; i++) {
        next[index + i] = pasted[i]
      }
    } else {
      next[index] = pasted
    }
    setDigits(next)

    const firstEmpty = next.findIndex((d) => d === '')
    if (firstEmpty === -1) {
      onSubmit(next.join(''))
    } else if (pasted) {
      boxes.current[firstEmpty]?.focus()
    }
  }

  const onKeyDown = (index: number, e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Backspace' && digits[index] === '' && index > 0) {
      boxes.current[index - 1]?.focus()
    }
  }

  return (
    <div className="mt-3 flex gap-2">
      {digits.map((digit, index) => (
        <input
          key={index}
          ref={(el) => { boxes.current[index] = el }}
          value={digit}
          disabled={disabled}
          inputMode="numeric"
          autoFocus={index === 0}
          onChange={(e) => update(index, e.target.value)}
          onKeyDown={(e) => onKeyDown(index, e)}
          className="h-11 w-9 rounded-lg border border-slate-300 text-center text-lg
                     font-semibold text-slate-900 focus:border-teal-600
                     focus:outline-none disabled:opacity-40"
        />
      ))}
    </div>
  )
}
