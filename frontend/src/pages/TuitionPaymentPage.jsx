// /pay: Details (tuition lookup, payer, summary) -> OTP modal -> Result (replaces the form, same route).
// Resuming a PENDING_OTP transaction passes its id in router state, and "Pay this MSSV again" passes the MSSV:
//   navigate('/pay', { state: { resumeId } })  /  navigate('/pay', { state: { mssv } })
// so the address bar always shows plain /pay - no transaction id, MSSV or code ever appears in the URL.
import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getTransaction, getTuition, initiateTransaction } from '../api/client.js'
import { keys, useAccount, useProfile, useTransactions } from '../hooks/queries.js'
import { useDebounce } from '../hooks/useTimers.js'
import { maskEmail, newIdempotencyKey } from '../utils/format.js'
import { isActivePayment } from '../utils/status.js'
import CancelPaymentDialog from '../components/CancelPaymentDialog.jsx'
import { PayerCard, StickyConfirm, SummaryCard, TuitionCard, blockReason } from '../components/PaymentCards.jsx'
import OtpModal, { RESEND_COOLDOWN, resendCooldownLeft } from '../components/OtpModal.jsx'
import ResultCard from '../components/ResultCard.jsx'
import { Alert, Stepper } from '../components/ui.jsx'

// Shortest MSSV worth looking up; shorter input never hits the API.
const MIN_MSSV = 8
// How often a reserved tuition is re-read, so its card updates without a reload (no gateway rate limit on this route).
const RESERVED_REFRESH_MS = 15_000
// How often a payment that is still finishing is re-read on the Result card.
const PROCESSING_REFRESH_MS = 3_000

export default function TuitionPaymentPage() {
  // Moves between routes (Home / History buttons) and clears the resume state once it is used.
  const navigate = useNavigate()
  // Current history entry; `location.state` carries the transaction to resume or the MSSV to pay (kept out of the URL).
  const location = useLocation()
  // Used to refresh cached account / transactions / tuition data after the server state changes.
  const queryClient = useQueryClient()
  // Payer details, balance and my payments, shared with other pages through the React Query cache.
  const profile = useProfile()
  const account = useAccount()
  const transactions = useTransactions()

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
  // Message of the last failed POST /transactions, shown above Confirm.
  const [submitError, setSubmitError] = useState(null)
  // Message of a 409 on POST /transactions: another payment got there after our lookup.
  const [conflict, setConflict] = useState(null)
  // Page-level banner after an action ends: { kind: 'info' | 'success' | 'error', text }.
  const [notice, setNotice] = useState(null)
  // My own payment being cancelled from the reserved card.
  const [cancelling, setCancelling] = useState(null)
  // "Check now" on someone else's reservation: request running / answered "still reserved".
  const [checking, setChecking] = useState(false)
  const [checked, setChecked] = useState(false)
  // After closing the OTP box, move focus to Resume once it is on screen.
  const [focusResume, setFocusResume] = useState(false)
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
    refetchInterval: (query) => (query.state.data?.status === 'RESERVED' && phase === 'details' ? RESERVED_REFRESH_MS : false),
  })
  // Tuition for the MSSV currently typed (undefined while typing or when the lookup failed).
  const currentTuition = lookupEnabled ? tuition.data : undefined
  // Status of that tuition.
  const tuitionStatus = currentTuition?.status

  // The API never says who holds a tuition: it is mine when my own list has an active payment for this MSSV.
  const mine = tuitionStatus === 'RESERVED'
    ? (transactions.data || []).find((t) => t.student_id === currentTuition.student_id && isActivePayment(t))
    : undefined
  // MSSV whose holder has been worked out from a list at least as new as the lookup. Later refetches keep the answer
  // on screen instead of flashing a skeleton every 15 s.
  const ownerKnownFor = useRef(null)
  if (lookupEnabled && transactions.data && transactions.dataUpdatedAt >= tuition.dataUpdatedAt) ownerKnownFor.current = debounced
  // True for the moment "someone else" cannot be told from "you" yet.
  const ownerUnknown = tuitionStatus === 'RESERVED' && !mine && ownerKnownFor.current !== debounced

  // Marks balance, history and tuition lookups as stale so every screen shows the server's new state.
  const refreshAll = () => {
    queryClient.invalidateQueries({ queryKey: keys.account })
    queryClient.invalidateQueries({ queryKey: keys.transactions })
    queryClient.invalidateQueries({ queryKey: ['tuition'] })
  }

  // Each read of a reserved tuition (and the first read after one) also refreshes my list and balance.
  const wasReserved = useRef(false)
  useEffect(() => {
    const reserved = tuition.data?.status === 'RESERVED'
    if (reserved || wasReserved.current) {
      queryClient.invalidateQueries({ queryKey: keys.transactions })
      queryClient.invalidateQueries({ queryKey: keys.account })
    }
    wasReserved.current = reserved
  }, [tuition.dataUpdatedAt, tuition.data?.status, queryClient])

  // Who held the reservation last seen: { mssv, txnId } (txnId null = someone else). Tells the student how a hold ended.
  const lastHold = useRef(null)
  useEffect(() => {
    if (!currentTuition) return
    const id = currentTuition.student_id
    if (tuitionStatus === 'RESERVED') {
      if (ownerUnknown) return
      if (mine) lastHold.current = { mssv: id, txnId: mine.id }
      else if (lastHold.current?.mssv !== id) lastHold.current = { mssv: id, txnId: null }
      return
    }
    const hold = lastHold.current
    if (hold?.mssv !== id) return
    if (tuitionStatus === 'UNPAID' && !hold.txnId) {
      setNotice({ kind: 'success', text: 'This tuition is available again. You can pay it now.' })
      setChecked(false)
    } else if (tuitionStatus === 'UNPAID') {
      // Mine: wait until my list has caught up, then only a timeout needs explaining (a cancel has its own message).
      const txn = (transactions.data || []).find((t) => t.id === hold.txnId)
      if (!txn || isActivePayment(txn)) return
      if (txn.status === 'EXPIRED') setNotice({ kind: 'info', text: 'Your payment was cancelled because the code was not entered in time. No money was taken.' })
    }
    lastHold.current = null
  }, [currentTuition, tuitionStatus, mine, ownerUnknown, transactions.data])

  // Transaction id handed over by a Resume button, if any.
  const resumeId = location.state?.resumeId
  // MSSV handed over by "Pay this MSSV again", if any.
  const presetMssv = location.state?.mssv
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
        setNotice(null)
        if (txn.status === 'PENDING_OTP') {
          // Keep Resend locked for the rest of the 30 s cooldown.
          setPending({ txn, tuition: info, expiresIn: txn.otp_expires_in ?? 0, cooldown: resendCooldownLeft(txn.otp_expires_in) })
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

  // "Pay this MSSV again": fill the form, and clear the router state like Resume does.
  useEffect(() => {
    if (!presetMssv) return
    navigate(location.pathname, { replace: true, state: null })
    setMssv(presetMssv)
  }, [presetMssv, navigate, location.pathname])

  // Move focus to Resume when the OTP box was just closed and my payment is on the card.
  useEffect(() => {
    if (!focusResume || !mine) return
    document.querySelector('[data-resume]')?.focus()
    setFocusResume(false)
  }, [focusResume, mine])

  // Status of the attempt shown by the Result card (undefined outside the 'result' step).
  const status = outcome?.result.transaction.status
  // A payment still finishing: keep reading it, so the Result card turns into the final answer by itself.
  const finishing = useQuery({
    queryKey: ['transaction', outcome?.result.transaction.id],
    queryFn: () => getTransaction(outcome.result.transaction.id),
    enabled: status === 'PROCESSING',
    refetchInterval: PROCESSING_REFRESH_MS,
  })
  useEffect(() => {
    if (!finishing.data || finishing.data.status === 'PROCESSING') return
    setOutcome((o) => (o?.result.transaction.id === finishing.data.id ? { ...o, result: { ...o.result, transaction: finishing.data } } : o))
    queryClient.invalidateQueries({ queryKey: keys.account })
    queryClient.invalidateQueries({ queryKey: keys.transactions })
    queryClient.invalidateQueries({ queryKey: ['tuition'] })
  }, [finishing.data, queryClient])

  // New MSSV typed: clear messages that described the previous one.
  const onMssvChange = (value) => {
    setMssv(value)
    setSubmitError(null)
    setConflict(null)
    setNotice(null)
    setChecked(false)
  }

  // Clear / "New payment": back to an empty form and a fresh payment attempt.
  const resetForm = () => {
    setMssv(''); setAgreed(false); setSubmitError(null); setConflict(null); setNotice(null); setChecked(false)
    setPending(null); setOutcome(null); setPhase('details')
    attempt.current = null
  }

  // Confirm button: POST /transactions with this attempt's Idempotency-Key. On PENDING_OTP the server has
  // reserved the tuition and emailed the code, so the OTP modal opens (resend locked for the first 30 s).
  const onConfirm = async () => {
    const t = currentTuition
    if (!t) return
    if (attempt.current?.mssv !== t.student_id) attempt.current = { key: newIdempotencyKey(), mssv: t.student_id }
    setSubmitting(true); setSubmitError(null); setConflict(null); setNotice(null)
    try {
      const txn = await initiateTransaction(t.student_id, attempt.current.key)
      queryClient.invalidateQueries({ queryKey: keys.transactions })
      if (txn.status === 'PENDING_OTP') {
        setPending({ txn, tuition: t, expiresIn: txn.otp_expires_in ?? 300, cooldown: RESEND_COOLDOWN })
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
      if (e.status === 409) {
        setConflict(e.message)
        setAgreed(false)
      } else setSubmitError(e.status === 429 ? `Too many requests. Try again in ${e.retryAfter || 60} seconds.` : e.message)
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
    setAgreed(false)
    setNotice({ kind: 'success', text: 'Payment cancelled. No money was taken from your account.' })
    refreshAll()
  }

  // The user closed the box: the payment stays open until its timer ends. Resume is on the tuition card and on Home.
  const onCloseOtp = () => {
    attempt.current = null
    resumed.current = null // the same payment can be resumed again
    setPending(null)
    setPhase('details')
    setAgreed(false)
    setNotice({ kind: 'info', text: 'Your payment is still open. Resume it before the code expires. If you do nothing, it ends by itself and no money is taken.' })
    setFocusResume(true)
    refreshAll()
  }

  // "Try again" after a failure: back to the form with the same MSSV; the next Confirm uses a new Idempotency-Key.
  const tryAgain = () => {
    setOutcome(null); setSubmitError(null); setConflict(null); setNotice(null); setAgreed(false); setPhase('details')
    attempt.current = null
    refreshAll()
  }

  // "Check now" on someone else's reservation.
  const onCheckNow = async () => {
    setChecking(true); setChecked(false)
    const { data } = await tuition.refetch()
    setChecking(false)
    setChecked(data?.status === 'RESERVED')
  }

  // Result card buttons for the status: success -> Home / New payment, still finishing -> History / New payment,
  // ended without paying -> Back to form / Try again.
  const resultButtons = status === 'SUCCESS'
    ? { secondary: { label: 'Back to home', onClick: () => navigate('/home') }, primary: { label: 'New payment', onClick: resetForm } }
    : status === 'PROCESSING' || status === 'PENDING_OTP'
      ? { secondary: { label: 'View history', onClick: () => navigate('/history') }, primary: { label: 'New payment', onClick: resetForm } }
      : { secondary: { label: 'Back to form', onClick: resetForm }, primary: { label: 'Try again', onClick: tryAgain } }

  // State of the lookup, for the reason above Confirm.
  const lookup = !lookupEnabled
    ? (mssv.length >= MIN_MSSV ? 'loading' : 'idle')
    : tuition.error?.status === 404 ? 'notfound'
    : tuition.error ? 'error'
    : tuition.isFetching && !currentTuition ? 'loading'
    : currentTuition ? 'ok' : 'idle'
  // Current reason Confirm is disabled, or null when it can be pressed.
  const reason = blockReason({ lookup, tuition: currentTuition, mine, ownerUnknown, balance: account.data?.balance, agreed })
  // A tuition this user could pay right now (terms aside): on phones the Confirm bar then replaces the tab bar.
  const payable = phase === 'details' && tuitionStatus === 'UNPAID' && reason !== 'insufficient' && account.data != null
  // A 409 explained by the fresh lookup: taken by someone else, or the server's own message if the status did not change.
  const conflictText = !conflict ? null
    : tuitionStatus === 'RESERVED' && !mine && !ownerUnknown ? 'Someone else started paying this tuition just before you. No money was taken.'
    : tuitionStatus === 'UNPAID' ? conflict
    : null

  return (
    <div className="grid gap-3.5 md:gap-5">
      <div className="grid gap-0 sm:flex sm:flex-wrap sm:items-center sm:justify-between sm:gap-3">
        <h1 tabIndex={-1} className="text-[22px] font-bold outline-none md:text-[26px]">Tuition payment</h1>
        <div className="no-print"><Stepper current={phase === 'details' ? 1 : phase === 'otp' ? 2 : 3} /></div>
      </div>

      {phase === 'result' && outcome ? (
        <ResultCard result={outcome.result} tuition={outcome.tuition} {...resultButtons} />
      ) : (
        <>
          {notice && <Alert kind={notice.kind}>{notice.text}</Alert>}
          <div className="grid items-start gap-3.5 md:grid-cols-[minmax(0,1fr)_370px] md:gap-5">
            {/* On phones `contents` lets the summary sit between the two cards. */}
            <div className="contents md:grid md:min-w-0 md:gap-5">
              <TuitionCard
                mssv={mssv}
                onMssvChange={onMssvChange}
                lookupEnabled={lookupEnabled}
                tuition={tuition}
                disabled={submitting || phase === 'otp'}
                held={{
                  mine,
                  fetchedAt: transactions.dataUpdatedAt,
                  unknown: ownerUnknown,
                  onResume: () => navigate('/pay', { state: { resumeId: mine?.id } }),
                  onCancel: () => setCancelling(mine),
                  onCheckNow,
                  checking,
                  checked,
                }}
              />
              <PayerCard profile={profile} />
            </div>
            <SummaryCard
              tuition={currentTuition}
              balance={account.data?.balance}
              reason={reason}
              alert={submitError || conflictText}
              email={maskEmail(profile.data?.email)}
              agreed={agreed}
              onAgreedChange={setAgreed}
              onClear={resetForm}
              onConfirm={onConfirm}
              submitting={submitting}
              payable={payable}
            />
          </div>
          {payable && (
            <>
              <div className="h-24 md:hidden" aria-hidden="true" />
              <StickyConfirm tuition={currentTuition} reason={reason} agreed={agreed} onAgreedChange={setAgreed} onConfirm={onConfirm} submitting={submitting} />
            </>
          )}
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
          onClose={onCloseOtp}
        />
      )}

      {cancelling && (
        <CancelPaymentDialog
          txn={cancelling}
          onClose={() => setCancelling(null)}
          onCancelled={() => {
            attempt.current = null
            setNotice({ kind: 'success', text: 'Payment cancelled. No money was taken from your account.' })
          }}
        />
      )}
    </div>
  )
}
