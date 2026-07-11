import type { RegistrationStage } from '../lib/registrationApi'

const STEPS: { key: RegistrationStage; label: string }[] = [
  { key: 'demographics', label: 'Details' },
  { key: 'identity_verification', label: 'Identity' },
  { key: 'insurance', label: 'Insurance' },
  { key: 'intake', label: 'Medical intake' },
  { key: 'done', label: 'Done' },
]

export default function ProgressSteps({ stage }: { stage: RegistrationStage }) {
  // duplicate_hold pauses inside the first step.
  const current = Math.max(0, STEPS.findIndex((s) => s.key === stage))

  return (
    <ol className="flex items-center gap-1 text-xs">
      {STEPS.map((step, index) => {
        const state =
          index < current ? 'done' : index === current ? 'current' : 'todo'
        return (
          <li key={step.key} className="flex items-center gap-1">
            {index > 0 && <span className="h-px w-4 bg-slate-300" />}
            <span
              className={
                state === 'done'
                  ? 'rounded-full bg-teal-600 px-2 py-0.5 text-white'
                  : state === 'current'
                    ? 'rounded-full border border-teal-600 px-2 py-0.5 font-semibold text-teal-700'
                    : 'rounded-full border border-slate-300 px-2 py-0.5 text-slate-400'
              }
            >
              {state === 'done' ? '✓ ' : ''}{step.label}
            </span>
          </li>
        )
      })}
    </ol>
  )
}
