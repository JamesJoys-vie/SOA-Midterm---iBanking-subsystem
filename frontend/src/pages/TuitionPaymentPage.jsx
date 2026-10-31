// /pay: Details (payer, tuition lookup, confirm) -> OTP modal -> Result (replaces the form, same route).
// Resuming a PENDING_OTP transaction (Home's "Waiting for OTP" card) passes its id in router state:
//   navigate('/pay', { state: { resumeId } })
// so the address bar always shows plain /pay - no transaction id, MSSV or code ever appears in the URL.
import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getTransaction, getTuition, initiateTransaction } from '../api/client.js'
import { keys, useAccount, useProfile } from '../hooks/queries.js'
import { useDebounce } from '../hooks/useTimers.js'
import { newIdempotencyKey } from '../utils/format.js'
import { ConfirmCard, PayerCard, TuitionCard } from '../components/PaymentCards.jsx'
import OtpModal from '../components/OtpModal.jsx'
import ResultCard from '../components/ResultCard.jsx'
import { Alert, Stepper } from '../components/ui.jsx'

// Shortest MSSV worth looking up; shorter input never hits the API.
const MIN_MSSV = 8

export default function TuitionPaymentPage() {
  // Moves between routes (Home / History buttons) and clears the resume state once it is used.
  const navigate = useNavigate()
  // Current history entry; `location.state.resumeId` carries the transaction to resume (kept out of the URL).
  const location = useLocation()
  // Used to refresh cached account / transactions / tuition data after the server state changes.
  const queryClient = useQueryClient()
  // Payer details and balance, shared with the header and other pages through the React Query cache.
  const profile = useProfile()
  const account = useAccount()

  // MSSV exactly as typed (already upper-cased, no spaces).
  const [mssv, setMssv] = useState('')
  // Terms & conditions checkbox.
  const [agreed, setAgreed] = useState(false)
  // Which step is on screen: 'details' (the form), 'otp' (modal over the form) or 'result' (replaces the form).
  const [phase, setPhase] = useState('details')
  // Transaction waiting for its code: { txn, tuition, expiresIn, cooldown }; null outside the 'otp' step.
  const [pending, setPending] = useState(null)
  // Finished attempt shown by the Result card: { result: {transaction, balance_after}, tuition }.
  const [outcome, setOutcome] = useState(null)
  // True while POST /transactions is in flight.
  const [submitting, setSubmitting] = useState(false)
  // Message of the last failed POST /transactions, shown in the Confirm card.
  const [submitError, setSubmitError] = useState(null)
  // Page-level banner after an action ends: { kind: 'info' | 'error', text }.
  const [notice, setNotice] = useState(null)
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

  // Transaction id handed over by Home's Resume button, if any.
  const resumeId = location.state?.resumeId
  // Last id already resumed, so React's double effects or re-renders never load it twice.
  const resumed = useRef(null)
  // Resume: load the transaction, then reopen the modal (still PENDING_OTP) or show how it ended.
  // The router state is cleared right away, so Back / reload do not resume the same transaction again.
  useEffect(() => {
    if (!resumeId || resumed.current === resumeId) return
    resumed.current = resumeId
    navigate(location.pathname, { replace: true, state: null })
    ;(async () => {
      try {
        const txn = await getTransaction(resumeId)
        const info = await getTuition(txn.student_id).catch(() => null)
        setMssv(txn.student_id)
        if (txn.status === 'PENDING_OTP') {
          setPending({ txn, tuition: info, expiresIn: txn.otp_expires_in ?? 0, cooldown: 0 })
          setPhase('otp')
        } else {
          setOutcome({ result: { transaction: txn, balance_after: null }, tuition: info })
          setPhase('result')
        }
      } catch (e) {
        setNotice({ kind: 'error', text: e.status === 404 ? 'That transaction was not found.' : e.message })
      }
    })()
  }, [resumeId, navigate, location.pathname])

  // New MSSV typed: clear messages that described the previous one.
  const onMssvChange = (value) => {
    setMssv(value)
    setSubmitError(null)
    setNotice(null)
  }

  // Clear / "New payment": back to an empty form and a fresh payment attempt.
  const resetForm = () => {
    setMssv(''); setAgreed(false); setSubmitError(null); setNotice(null)
    setPending(null); setOutcome(null); setPhase('details')
    attempt.current = null
  }

  // Confirm button: POST /transactions with this attempt's Idempotency-Key. On PENDING_OTP the server has
  // reserved the tuition and emailed the code, so the OTP modal opens (resend locked for the first 30 s).
  const onConfirm = async () => {
    const t = currentTuition
    if (!t) return
    if (attempt.current?.mssv !== t.student_id) attempt.current = { key: newIdempotencyKey(), mssv: t.student_id }
    setSubmitting(true); setSubmitError(null); setNotice(null)
    try {
      const txn = await initiateTransaction(t.student_id, attempt.current.key)
      queryClient.invalidateQueries({ queryKey: keys.transactions })
      if (txn.status === 'PENDING_OTP') {
        setPending({ txn, tuition: t, expiresIn: txn.otp_expires_in ?? 300, cooldown: 30 })
        setPhase('otp')
      } else {
        // Same key replayed for an attempt that already ended: show how it ended.
        attempt.current = null
        setOutcome({ result: { transaction: txn, balance_after: null }, tuition: t })
        setPhase('result')
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

  // The modal reports an ended (or finishing) attempt: show the Result card and refresh balance / history.
  const onResult = (result) => {
    attempt.current = null
    setOutcome({ result, tuition: pending?.tuition })
    setPending(null)
    setPhase('result')
    refreshAll()
  }

  // The user cancelled in the modal: back to the form (MSSV kept) with a reassuring notice.
  const onCancelled = () => {
    attempt.current = null
    setPending(null)
    setPhase('details')
    setNotice({ kind: 'info', text: 'Payment cancelled. No money was taken from your account.' })
    refreshAll()
  }

  // "Try again" after a failure: back to the form with the same MSSV; the next Confirm uses a new Idempotency-Key.
  const tryAgain = () => {
    setOutcome(null); setSubmitError(null); setNotice(null); setPhase('details')
    attempt.current = null
    refreshAll()
  }

  // Status of the attempt shown by the Result card (undefined outside the 'result' step).
  const status = outcome?.result.transaction.status
  // Result card buttons for that status: success -> Home / New payment, still finishing -> History / New payment,
  // ended without paying -> Back to form / Try again.
  const resultButtons = status === 'SUCCESS'
    ? { secondary: { label: 'Back to home', onClick: () => navigate('/home') }, primary: { label: 'New payment', onClick: resetForm } }
    : status === 'PROCESSING' || status === 'PENDING_OTP'
      ? { secondary: { label: 'View history', onClick: () => navigate('/history') }, primary: { label: 'New payment', onClick: resetForm } }
      : { secondary: { label: 'Back to form', onClick: resetForm }, primary: { label: 'Try again', onClick: tryAgain } }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-slate-900">Tuition payment</h1>
        <Stepper current={phase === 'details' ? 1 : phase === 'otp' ? 2 : 3} />
      </div>

      {phase === 'result' && outcome ? (
        <ResultCard result={outcome.result} tuition={outcome.tuition} {...resultButtons} />
      ) : (
        <>
          {notice && <Alert kind={notice.kind}>{notice.text}</Alert>}
          <div className="grid gap-4 md:grid-cols-2">
            <PayerCard profile={profile} account={account} />
            <TuitionCard
              mssv={mssv}
              onMssvChange={onMssvChange}
              lookupEnabled={lookupEnabled}
              tuition={tuition}
              disabled={submitting || phase === 'otp'}
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

      {phase === 'otp' && pending && (
        <OtpModal
          txn={pending.txn}
          tuition={pending.tuition}
          email={profile.data?.email}
          initialExpiresIn={pending.expiresIn}
          initialCooldown={pending.cooldown}
          onResult={onResult}
          onCancelled={onCancelled}
        />
      )}
    </div>
  )
}
