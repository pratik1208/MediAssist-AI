// One patient session per browser tab, shared by the registration and triage
// pages. The registration page owns the stored object (token + its chat
// state); other pages only ever read the token.

const REGISTRATION_KEY = 'mediassist.registration'
const TRIAGE_KEY = 'mediassist.triage.session'

/** Token from a registration flow in this tab, if any. */
export function registrationSessionToken(): string | null {
  try {
    const saved = sessionStorage.getItem(REGISTRATION_KEY)
    return saved ? (JSON.parse(saved).token ?? null) : null
  } catch {
    return null
  }
}

/** Token from a triage sign-in in this tab, if any. */
export function triageSessionToken(): string | null {
  return sessionStorage.getItem(TRIAGE_KEY)
}

export function saveTriageSessionToken(token: string): void {
  sessionStorage.setItem(TRIAGE_KEY, token)
}

export function clearTriageSession(): void {
  sessionStorage.removeItem(TRIAGE_KEY)
}
