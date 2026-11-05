// OTP step of /pay (see "OTP verification" in docs/wireframes/modernization-proposal.html): 6-box input, expiry countdown,
// resend cooldown, verify / cancel. ✕ and Esc only close the box: the payment stays open and can be resumed until its
// timer ends. "Cancel payment" ends it now, after asking. The backdrop does nothing.
// The code only lives in component state and request bodies: it is never put in the URL, storage or logs.
import { useEffect, useId, useRef, useState } from 'react'
import { X } from 'lucide-react'
import { cancelTransaction, getTransaction, resendOtp, verifyOtp } from '../api/client.js'
import { useSecondsLeft } from '../hooks/useTimers.js'
import { formatClock, maskEmail } from '../utils/format.js'
import { ConfirmBody, Modal } from './Dialog.jsx'
import { Alert, Button, ExpiryBar, Money, Stepper } from './ui.jsx'

// Number of digits in a code (otp-service issues 6-digit codes).
const LENGTH = 6
// Seconds between two codes of one transaction; otp-service enforces the same value and answers 429 otherwise.
export const RESEND_COOLDOWN = 30
// Code lifetime in seconds (default OTP_TTL_SECONDS); used to estimate a code's age.
export const OTP_TTL = 300

// Resend cooldown left for a code with `expiresIn` seconds left (used on Resume).
// With a shorter server TTL it returns 0; a 429 then sets the wait instead.
export const resendCooldownLeft = (expiresIn) =>
  Math.min(RESEND_COOLDOWN, Math.max(0, RESEND_COOLDOWN - (OTP_TTL - (expiresIn ?? 0))))

// Six one-digit boxes that behave like a single field: typing moves forward, Backspace moves back, arrows move,
// pasting or autofilling the whole code fills every box. `value` is the code typed so far ('' to 6 digits);
// `onChange` receives the new code; `onComplete` fires once all 6 digits are present (submits automatically).
export function OtpInput({ value, onChange, disabled, onComplete }) {
  // DOM nodes of the six boxes, used to move the focus.
  const refs = useRef([])
  // One entry per box ('' when empty), derived from `value`.
  const digits = Array.from({ length: LENGTH }, (_, i) => value[i] || '')
  // The box that should receive focus when the input becomes usable.
  const firstEmpty = Math.min(value.length, LENGTH - 1)

  // Focus the first empty box whenever the input becomes usable (modal opened, request finished).
  useEffect(() => { if (!disabled) refs.current[firstEmpty]?.focus() }, [disabled]) // eslint-disable-line react-hooks/exhaustive-deps

  // Writes digit `d` into box `i` and returns the resulting code.
  const setAt = (i, d) => {
    const next = digits.slice()
    next[i] = d
    const joined = next.join('')
    onChange(joined)
    return joined
  }

  // Typing in box `i`: keep digits only, take the newest one, then move to the next box (or submit on the last).
  const onInput = (i, e) => {
    const typed = e.target.value.replace(/\D/g, '')
    if (!typed) return
    if (typed.length >= LENGTH) return onPaste(typed) // autofill of the whole code
    const joined = setAt(i, typed.slice(-1)) // box already had a digit: keep the newly typed one
    if (i < LENGTH - 1) refs.current[i + 1]?.focus()
    else if (joined.length === LENGTH) onComplete?.(joined)
  }

  // Pasted / autofilled text: spread its digits over the boxes and submit when it is a full code.
  const onPaste = (text) => {
    const code = text.replace(/\D/g, '').slice(0, LENGTH)
    if (!code) return
    onChange(code)
    refs.current[Math.min(code.length, LENGTH - 1)]?.focus()
    if (code.length === LENGTH) onComplete?.(code)
  }

  // Keyboard navigation: Backspace clears this box (or the previous one when empty), arrows move the focus.
  const onKeyDown = (i, e) => {
    if (e.key === 'Backspace') {
      e.preventDefault()
      if (digits[i]) setAt(i, '')
      else if (i > 0) { setAt(i - 1, ''); refs.current[i - 1]?.focus() }
    } else if (e.key === 'ArrowLeft' && i > 0) refs.current[i - 1]?.focus()
    else if (e.key === 'ArrowRight' && i < LENGTH - 1) refs.current[i + 1]?.focus()
  }

  return (
    <div className="flex justify-center gap-1.5 sm:gap-2" onPaste={(e) => { e.preventDefault(); onPaste(e.clipboardData.getData('text')) }}>
      {digits.map((d, i) => (
        <input
          key={i}
          ref={(el) => { refs.current[i] = el }}
          value={d}
          onChange={(e) => onInput(i, e)}
          onKeyDown={(e) => onKeyDown(i, e)}
          onFocus={(e) => e.target.select()}
          disabled={disabled}
          inputMode="numeric"
          autoComplete={i === 0 ? 'one-time-code' : 'off'}
          maxLength={LENGTH}
          aria-label={`Digit ${i + 1}`}
          data-autofocus={i === firstEmpty ? true : undefined}
          className="h-14 w-12 min-w-0 flex-[0_1_48px] rounded-[10px] border border-line-strong bg-card text-center text-[22px] font-semibold outline-none focus:border-action focus:ring-1 focus:ring-action disabled:bg-subtle disabled:text-muted"
        />
      ))}
    </div>
  )
}

// Promise that resolves after `ms` milliseconds (used between status polls).
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// PROCESSING = money already debited, the tuition commit is still finishing. Poll GET /transactions/{id}
// every 2 s for up to ~30 s and return the latest transaction (still PROCESSING if it did not finish in time).
async function waitWhileProcessing(txn) {
  let t = txn
  for (let i = 0; i < 15 && t.status === 'PROCESSING'; i++) {
    await sleep(2000)
    t = await getTransaction(t.id).catch(() => t)
  }
  return t
}

// The modal itself. `txn`: the PENDING_OTP transaction. `tuition`: its tuition (for the student name), may be null.
// `email`: payer email, shown masked. `initialExpiresIn`: seconds left on the current code (from `otp_expires_in`).
// `initialCooldown`: seconds before Resend is allowed (30 right after a code was sent, 0 when resuming).
// `onResult({transaction, balance_after})`: the attempt ended (or is finishing). `onCancelled(txn)`: the user cancelled.
// `onClose()`: the user closed the box; the payment stays open.
export default function OtpModal({ txn, tuition, email, initialExpiresIn, initialCooldown = RESEND_COOLDOWN, onResult, onCancelled, onClose }) {
  // Digits typed so far.
  const [code, setCode] = useState('')
  // Inline error from the last request (wrong code, rate limit, network...).
  const [error, setError] = useState(null)
  // Inline confirmation, e.g. after a resend.
  const [info, setInfo] = useState(null)
  // Request in flight: 'verify' | 'resend' | 'cancel' | null; disables the other actions meanwhile.
  const [busy, setBusy] = useState(null)
  // "Cancel this payment?" replaces the code form.
  const [asking, setAsking] = useState(false)
  // Epoch ms when the current code expires; moved forward by a successful resend.
  const [deadline, setDeadline] = useState(() => Date.now() + (initialExpiresIn ?? 0) * 1000)
  // Epoch ms from which Resend is allowed again.
  const [resendAt, setResendAt] = useState(() => Date.now() + initialCooldown * 1000)
  // Seconds left on the code and on the resend cooldown, ticking every second.
  const left = useSecondsLeft(deadline)
  const cooldown = useSecondsLeft(resendAt)
  // The code ran out: boxes disable and only Resend / Cancel remain.
  const expired = left === 0
  // Ids tying the dialog to its heading.
  const titleId = useId()
  const bodyId = useId()

  // The transaction moved on without us (expired, cancelled elsewhere, already finished): read its real state and
  // hand it to the result view; `fallbackStatus` is used when even that read fails.
  const finishWith = async (fallbackStatus) => {
    const t = await getTransaction(txn.id).catch(() => ({ ...txn, status: fallbackStatus }))
    onResult({ transaction: t, balance_after: null })
  }

  // POST /transactions/{id}/verify-otp with the 6 digits. A wrong / expired / locked code (400) stays in the modal
  // with the server's message; 410 / 409 / 404 mean the transaction is over, so the result view takes over.
  const verify = async (value = code) => {
    if (value.length !== LENGTH || busy) return
    setBusy('verify'); setError(null); setInfo(null)
    try {
      const res = await verifyOtp(txn.id, value)
      const t = res.transaction.status === 'PROCESSING' ? await waitWhileProcessing(res.transaction) : res.transaction
      onResult({ ...res, transaction: t })
    } catch (e) {
      if (e.status === 410) return finishWith('EXPIRED')
      if (e.status === 409 || e.status === 404) return finishWith('FAILED')
      setError(e.status === 429 ? `Too many attempts. Wait ${e.retryAfter || 60} seconds.` : e.message)
      setCode('')
    } finally {
      setBusy(null)
    }
  }

  // POST /transactions/{id}/resend-otp: a new code is emailed, the old one stops working, and both timers restart.
  // 429 (cooldown or max codes reached) moves the cooldown to the server's Retry-After.
  const resend = async () => {
    setBusy('resend'); setError(null); setInfo(null)
    try {
      const { otp_expires_in } = await resendOtp(txn.id)
      setDeadline(Date.now() + otp_expires_in * 1000)
      setResendAt(Date.now() + RESEND_COOLDOWN * 1000)
      setCode('')
      setInfo('A new code was sent. The previous code no longer works.')
    } catch (e) {
      if (e.status === 410) return finishWith('EXPIRED')
      if (e.status === 409) return finishWith('FAILED')
      if (e.status === 429) {
        if (e.retryAfter) setResendAt(Date.now() + e.retryAfter * 1000)
        setError(e.retryAfter ? `Too many requests. Try again in ${e.retryAfter} s.` : e.message)
      } else setError(e.message)
    } finally {
      setBusy(null)
    }
  }

  // "Yes, cancel": POST /transactions/{id}/cancel (releases the tuition hold).
  const cancel = async () => {
    setBusy('cancel'); setError(null)
    try {
      onCancelled(await cancelTransaction(txn.id))
    } catch (e) {
      if (e.status === 409) return finishWith('FAILED')
      setError(e.message)
      setBusy(null)
    }
  }

  // Student name and amount, so it is clear what is being confirmed. The amount stays visible when amounts are hidden.
  const recap = (
    <div className="flex items-center justify-between gap-2.5 rounded-[10px] bg-subtle px-3 py-2.5 text-[13px] text-ink-2">
      <span>MSSV {txn.student_id}{tuition?.student_name ? ` · ${tuition.student_name}` : ''}</span>
      <Money value={txn.amount} alwaysVisible className="text-sm font-semibold text-ink" />
    </div>
  )

  // Esc goes back from the question, otherwise closes the box. It waits while a request is running.
  const onEscape = () => {
    if (busy) return
    if (asking) { setAsking(false); setError(null) } else onClose()
  }

  return (
    <Modal role={asking ? 'alertdialog' : 'dialog'} labelledBy={titleId} describedBy={asking ? bodyId : undefined} onEscape={onEscape}>
      {asking ? (
        <ConfirmBody
          titleId={titleId}
          bodyId={bodyId}
          title="Cancel this payment?"
          body="No money has been taken. The tuition is released so it can be paid again."
          recap={recap}
          error={error}
          keepLabel="Keep paying"
          confirmLabel="Yes, cancel"
          busy={busy === 'cancel'}
          onKeep={() => { setAsking(false); setError(null) }}
          onConfirm={cancel}
        />
      ) : (
        // method="post" + no action: even if the submit handler failed, the browser would never put the code in the URL.
        <form method="post" onSubmit={(e) => { e.preventDefault(); verify() }} className="grid gap-3.5">
          <Stepper current={2} />
          <div className="flex items-center justify-between gap-2.5">
            <h2 id={titleId} className="text-xl font-bold">Enter verification code</h2>
            <button type="button" onClick={onClose} disabled={!!busy} aria-label="Close. The payment stays open until the code expires" title="Close" className="flex h-11 w-11 flex-none items-center justify-center rounded-[10px] text-ink-2 hover:bg-subtle disabled:opacity-40">
              <X className="h-5 w-5" aria-hidden="true" />
            </button>
          </div>
          <p className="text-sm text-ink-2">We sent a 6-digit code to {maskEmail(email) || 'your email'}</p>
          {recap}

          <OtpInput value={code} onChange={setCode} disabled={expired || !!busy} onComplete={verify} />

          <div className="grid gap-1">
            <ExpiryBar share={left / OTP_TTL} tone={left > 60 ? 'bg-action' : 'bg-warn'} />
            <div className="flex items-center justify-between gap-2.5 text-[13px] text-ink-2">
              {expired
                ? <span className="font-medium text-bad">Code expired. Send a new one.</span>
                : <span>Code expires in <span className="tabular-nums">{formatClock(left)}</span></span>}
              <button
                type="button"
                onClick={resend}
                disabled={cooldown > 0 || !!busy}
                className="min-h-11 font-semibold text-action disabled:cursor-not-allowed disabled:font-normal disabled:text-muted"
              >
                {busy === 'resend' ? 'Sending…' : cooldown > 0 ? `Resend code (${formatClock(cooldown).replace(/^0/, '')})` : 'Resend code'}
              </button>
            </div>
          </div>

          {error && <Alert>{error}</Alert>}
          {info && !error && <Alert kind="info">{info}</Alert>}

          <div className="grid grid-cols-2 gap-2.5">
            <Button variant="ghost" onClick={() => { setAsking(true); setError(null) }} disabled={!!busy}>Cancel payment</Button>
            <Button type="submit" loading={busy === 'verify'} disabled={code.length !== LENGTH || expired || (!!busy && busy !== 'verify')}>
              {busy === 'verify' ? 'Verifying…' : 'Verify and pay'}
            </Button>
          </div>
        </form>
      )}
    </Modal>
  )
}
