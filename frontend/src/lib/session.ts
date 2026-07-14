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

/**
 * True when an API error means this session token can't access patient data
 * and the user should go through the sign-in gate: an invalid/expired token
 * (401/403), or a session that never attached a patient — e.g. a registration
 * chat that was opened but never finished. The backend session gate answers
 * that case with 400 "submit demographics before this step", which must not
 * be confused with a "backend down" error.
 */
export function sessionUnusable(error: unknown): boolean {
  const e = error as { status?: number; body?: { error?: string } } | null
  if (e?.status === 401 || e?.status === 403) return true
  return e?.status === 400 && (e?.body?.error ?? '').includes('demographics')
}
