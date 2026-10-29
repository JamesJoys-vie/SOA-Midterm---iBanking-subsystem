// Display helpers shared by every page.
const vnd = new Intl.NumberFormat('vi-VN')

// API amounts are Decimal strings ("15000000.00"); render as "15.000.000 ₫".
export const formatVnd = (value) => `${vnd.format(Math.round(Number(value) || 0))} ₫`

// Backend datetimes are naive UTC ("2026-10-09T14:32:00"); mark them as UTC before parsing.
export const parseUtc = (s) => (s ? new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : `${s}Z`) : null)

export const formatDateTime = (s) => {
  const d = parseUtc(s)
  if (!d) return '—'
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getDate())}/${p(d.getMonth() + 1)}/${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`
}

export const formatClock = (seconds) => {
  const s = Math.max(0, Math.floor(seconds))
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}

export const shortId = (id) => (id && id.length > 10 ? `${id.slice(0, 4)}…${id.slice(-4)}` : id)

// "alice@example.com" -> "a****@example.com"
export const maskEmail = (email) => {
  if (!email || !email.includes('@')) return email || ''
  const [name, domain] = email.split('@')
  return `${name[0]}****@${domain}`
}

// crypto.randomUUID needs a secure context (https or localhost); fall back for plain-http LAN access.
export const newIdempotencyKey = () =>
  globalThis.crypto?.randomUUID?.() ??
  'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16)
  })

// Plain-words reason for a transaction that ended without paying.
export const failureText = (t) => {
  if (!t) return ''
  if (t.failure_reason) return t.failure_reason
  if (t.status === 'EXPIRED') return 'Verification code expired'
  if (t.status === 'CANCELLED') return 'Payment was cancelled'
  return 'The payment could not be completed'
}

export const ENDED_STATUSES = ['FAILED', 'EXPIRED', 'CANCELLED']
