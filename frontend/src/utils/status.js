// What students see for each API status. EXPIRED stays the stored status; a payment that timed out is shown as
// Cancelled, with the timeout as its reason (see failureText). This table is the only place that mapping lives.
// `kind`: ok = finished well, progress = still running, ended = ended without paying, neutral = nothing happened yet.
export const STATUS_UI = {
  SUCCESS: { label: 'Successful', kind: 'ok' },
  PAID: { label: 'Paid', kind: 'ok' },
  PENDING_OTP: { label: 'Waiting for code', kind: 'progress' },
  PROCESSING: { label: 'Processing', kind: 'progress' },
  RESERVED: { label: 'Reserved', kind: 'progress' },
  FAILED: { label: 'Failed', kind: 'ended' },
  EXPIRED: { label: 'Cancelled', kind: 'ended' },
  CANCELLED: { label: 'Cancelled', kind: 'ended' },
  UNPAID: { label: 'Unpaid', kind: 'neutral' },
}

export const statusLabel = (status) => STATUS_UI[status]?.label || status

// History filter chips: plain words mapped to the statuses they cover (null = all).
export const STATUS_FILTERS = [
  { id: 'all', label: 'All', statuses: null },
  { id: 'ok', label: 'Successful', statuses: ['SUCCESS'] },
  { id: 'progress', label: 'In progress', statuses: ['PENDING_OTP', 'PROCESSING'] },
  { id: 'ended', label: 'Not completed', statuses: ['FAILED', 'EXPIRED', 'CANCELLED'] },
]

// A payment of mine that still holds its tuition: this is how /pay tells "reserved by you" from "by someone else".
export const isActivePayment = (t) => t.status === 'PENDING_OTP' || t.status === 'PROCESSING'
