// /pay: the Details step of the tuition payment (payer, tuition lookup, confirm) -> POST /transactions.
// The OTP modal and the Result card arrive in segment fe-otp-result; until then a created transaction is shown
// in an interim "waiting for the code" card that can cancel it, so the tuition hold is never left behind.
import { useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { cancelTransaction, getTuition, initiateTransaction } from '../api/client.js'
import { keys, useAccount, useProfile } from '../hooks/queries.js'
import { useDebounce } from '../hooks/useTimers.js'
import { maskEmail, newIdempotencyKey, shortId } from '../utils/format.js'
import { ConfirmCard, PayerCard, TuitionCard } from '../components/PaymentCards.jsx'
import { Alert, Button, Card, Money, ReadOnlyField, Stepper } from '../components/ui.jsx'

// Shortest MSSV worth looking up; shorter input never hits the API.
const MIN_MSSV = 8

export default function TuitionPaymentPage() {
  // Used to refresh cached account / transactions / tuition data after the server state changes.
  const queryClient = useQueryClient()
  // Payer details and balance, shared with the header and other pages through the React Query cache.
  const profile = useProfile()
  const account = useAccount()

  // MSSV exactly as typed (already upper-cased, no spaces).
  const [mssv, setMssv] = useState('')
  // Terms & conditions checkbox.
  const [agreed, setAgreed] = useState(false)
  // Which step is on screen: 'details' (the form) or 'otp' (a transaction is waiting for its code).
  const [phase, setPhase] = useState('details')
  // Transaction created by Confirm and the tuition it pays: { txn, tuition }; null while on the form.
  const [pending, setPending] = useState(null)
  // True while POST /transactions is in flight.
  const [submitting, setSubmitting] = useState(false)
  // Message of the last failed POST /transactions, shown in the Confirm card.
  const [submitError, setSubmitError] = useState(null)
  // Page-level banner after an action ends: { kind: 'info' | 'error', text }.
  const [notice, setNotice] = useState(null)
  // True while the interim card's Cancel request is in flight.
  const [cancelling, setCancelling] = useState(false)
  // One Idempotency-Key per payment attempt: { key, mssv }. Reused when the same attempt is retried
  // (e.g. a network error after the server already created it), replaced once the attempt is over or the MSSV changes.
  const attempt = useRef(null)

  // MSSV after the user stopped typing for 400 ms.
  const debounced = useDebounce(mssv, 400)
  // Look up only a long-enough MSSV, and only once the debounce caught up with what is on screen.
  const lookupEnabled = mssv.length >= MIN_MSSV && debounced === mssv
  // GET /tuitions/{mssv}; staleTime 0 so coming back to an MSSV always shows its current status.
  const tuition = useQuery({
    queryKey: ['tuition', debounced],
    queryFn: () => getTuition(debounced),
    enabled: lookupEnabled,
    staleTime: 0,
  })
  // Tuition for the MSSV currently typed (undefined while typing or when the lookup failed).
  const currentTuition = lookupEnabled ? tuition.data : undefined

  // Marks balance, history and tuition lookups as stale so every screen shows the server's new state.
  const refreshAll = () => {
    queryClient.invalidateQueries({ queryKey: keys.account })
    queryClient.invalidateQueries({ queryKey: keys.transactions })
    queryClient.invalidateQueries({ queryKey: ['tuition'] })
  }

  // New MSSV typed: clear messages that described the previous one.
  const onMssvChange = (value) => {
    setMssv(value)
    setSubmitError(null)
    setNotice(null)
  }

  // Clear button: back to an empty form and a fresh payment attempt.
  const resetForm = () => {
    setMssv(''); setAgreed(false); setSubmitError(null); setNotice(null)
    setPending(null); setPhase('details')
    attempt.current = null
  }

  // Confirm button: POST /transactions with this attempt's Idempotency-Key. On PENDING_OTP the server has
  // reserved the tuition and emailed the code, so the page moves to the 'otp' step.
  const onConfirm = async () => {
    const t = currentTuition
    if (!t) return
    if (attempt.current?.mssv !== t.student_id) attempt.current = { key: newIdempotencyKey(), mssv: t.student_id }
    setSubmitting(true); setSubmitError(null); setNotice(null)
    try {
      const txn = await initiateTransaction(t.student_id, attempt.current.key)
      queryClient.invalidateQueries({ queryKey: keys.transactions })
      if (txn.status === 'PENDING_OTP') {
        setPending({ txn, tuition: t })
        setPhase('otp')
      } else {
        // Same key replayed for an attempt that already ended: report it and start over with a new key.
        attempt.current = null
        setNotice({ kind: 'info', text: `This payment attempt already ended (status ${txn.status}). Check History.` })
        refreshAll()
      }
    } catch (e) {
      if (e.status === 409 || e.status === 422 || e.status === 404) {
        attempt.current = null // the server rejected this attempt; a later one is a new request
        refreshAll()
      }
      setSubmitError(e.status === 429 ? `Too many requests. Try again in ${e.retryAfter || 60} seconds.` : e.message)
    } finally {
      setSubmitting(false)
    }
  }

  // Interim Cancel (until the OTP modal exists): POST /transactions/{id}/cancel releases the tuition hold.
  const onCancelPending = async () => {
    if (!pending) return
    setCancelling(true)
    try {
      await cancelTransaction(pending.txn.id)
      attempt.current = null
      setPending(null)
      setPhase('details')
      setNotice({ kind: 'info', text: 'Payment cancelled. No money was taken from your account.' })
    } catch (e) {
      // 404 / 409: the transaction is gone or already ended (e.g. expired), so there is nothing left to cancel.
      if (e.status === 404 || e.status === 409) {
        attempt.current = null
        setPending(null)
        setPhase('details')
      }
      setNotice({ kind: 'error', text: e.message })
    } finally {
      setCancelling(false)
      refreshAll()
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-slate-900">Tuition payment</h1>
        <Stepper current={phase === 'details' ? 1 : 2} />
      </div>

      {notice && <Alert kind={notice.kind}>{notice.text}</Alert>}

      {phase === 'otp' && pending ? (
        <Card title="Waiting for the verification code" hint={`Transaction ${shortId(pending.txn.id)}`}>
          <ReadOnlyField label="Student">{pending.tuition.student_name} ({pending.tuition.student_id})</ReadOnlyField>
          <ReadOnlyField label="Amount"><Money value={pending.tuition.amount} /></ReadOnlyField>
          <ReadOnlyField label="Code sent to">{maskEmail(profile.data?.email)}</ReadOnlyField>
          <p className="mt-3 text-sm text-slate-500">Entering the code is added in the next update of this page. Cancel to release the tuition.</p>
          <div className="mt-4 flex justify-end">
            <Button variant="danger" onClick={onCancelPending} loading={cancelling}>Cancel payment</Button>
          </div>
        </Card>
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            <PayerCard profile={profile} account={account} />
            <TuitionCard
              mssv={mssv}
              onMssvChange={onMssvChange}
              lookupEnabled={lookupEnabled}
              tuition={tuition}
              disabled={submitting}
            />
          </div>
          <ConfirmCard
            tuition={currentTuition}
            balance={account.data?.balance}
            agreed={agreed}
            onAgreedChange={setAgreed}
            onClear={resetForm}
            onConfirm={onConfirm}
            submitting={submitting}
            submitError={submitError}
          />
        </>
      )}
    </div>
  )
}
