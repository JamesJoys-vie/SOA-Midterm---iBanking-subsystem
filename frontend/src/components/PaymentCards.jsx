// The cards of the /pay Details step (see "Tuition payment" and "Reserved tuition" in docs/wireframes/modernization-proposal.html).
// TuitionCard looks up what is paid, PayerCard shows who pays, SummaryCard owns the rule that enables Confirm.
import { GraduationCap, Lock, Mail } from 'lucide-react'
import { useAmountVisibility } from '../context/AmountVisibility.jsx'
import { useSecondsLeft } from '../hooks/useTimers.js'
import { formatClock, formatVnd } from '../utils/format.js'
import { OTP_TTL } from './OtpModal.jsx'
import { Alert, Button, ButtonLink, Card, EyeToggle, ExpiryBar, Money, Reason, Skeleton, Spinner, StatusBadge, TextField } from './ui.jsx'

// A RESERVED tuition, by who holds it. The API does not say who: `mine` is my own active payment for this MSSV, if any.
// `fetchedAt`: when my transaction list was loaded (otp_expires_in counts from then). `unknown`: that list is still loading.
function HeldNotice({ mine, fetchedAt, unknown, onResume, onCancel, onCheckNow, checking, checked }) {
  const deadline = mine?.status === 'PENDING_OTP' ? fetchedAt + (mine.otp_expires_in ?? 0) * 1000 : null
  const left = useSecondsLeft(deadline)

  if (unknown) return <div className="grid gap-2 border-t border-line-strong pt-3"><Skeleton /><Skeleton className="h-4 w-2/3" /></div>

  const Text = ({ title, children }) => <div><b className="block text-sm font-semibold">{title}</b><span className="text-[13px] text-ink-2">{children}</span></div>
  const box = 'grid gap-2.5 border-t border-line-strong pt-3'

  if (mine?.status === 'PROCESSING') {
    return (
      <div className={box}>
        <Text title="Your payment is being finished">The amount has left your balance and we are confirming it. This page updates by itself.</Text>
        <ButtonLink to="/history" variant="secondary">View history</ButtonLink>
      </div>
    )
  }
  if (mine) {
    return (
      <div className={box}>
        <Text title="You started this payment">
          {left > 0
            ? <>Code expires in <span className="tabular-nums">{formatClock(left)}</span>. Resume to enter the code, or cancel to release the tuition.</>
            : 'Code expired. This payment is ending, and no money was taken.'}
        </Text>
        <ExpiryBar share={left / OTP_TTL} />
        <div className="grid grid-cols-2 gap-2">
          <Button variant="ghost" onClick={onCancel}>Cancel</Button>
          <Button onClick={onResume} disabled={left === 0} data-resume>Resume</Button>
        </div>
      </div>
    )
  }
  // Someone else: never named, and no release time is promised because a resend extends the hold.
  return (
    <div className={box}>
      <Text title="Someone else is paying this tuition">You cannot pay it right now, and you have not been charged. If their payment does not finish, it becomes available again. This page updates by itself.</Text>
      <Button variant="secondary" onClick={onCheckNow} loading={checking}>{checking ? 'Checking…' : 'Check now'}</Button>
      {checked && <span className="text-xs text-muted">Still reserved. Checked just now.</span>}
    </div>
  )
}

// MSSV input plus the looked-up tuition (GET /tuitions/{mssv}), with its errors shown inside this card.
// `mssv` / `onMssvChange`: controlled input owned by the page. `lookupEnabled`: true when the typed MSSV is long
// enough and the debounce has settled, so the result belongs to what is on screen. `tuition`: the React Query result.
// `disabled`: locks the input while a payment is being created or is waiting for its OTP. `held`: props for HeldNotice.
export function TuitionCard({ mssv, onMssvChange, lookupEnabled, tuition, disabled, held }) {
  // 404 from tuition-service = this MSSV has no tuition; shown as its own message, without a Retry button.
  const notFound = lookupEnabled && tuition.error?.status === 404
  // Lookup result for the MSSV currently typed; undefined while typing so stale data is never shown.
  const data = lookupEnabled ? tuition.data : undefined
  // First load for this MSSV (a background refetch keeps the old rows and only shows the spinner in the input).
  const loading = lookupEnabled && tuition.isFetching && !data

  return (
    <Card className="grid gap-4 md:p-6">
      <h2 className="text-lg font-semibold">Who are you paying for?</h2>
      <TextField
        label="Student ID (MSSV)"
        value={mssv}
        // MSSVs have no spaces and are stored upper-case ("521H0081"), so normalise while typing.
        onChange={(e) => onMssvChange(e.target.value.replace(/\s/g, '').toUpperCase())}
        disabled={disabled}
        maxLength={12}
        autoCapitalize="characters"
        autoComplete="off"
        placeholder="e.g. 52100001 or 521H0081"
        help="8 characters, may include letters. We look it up as you type."
        error={notFound ? `No tuition found for MSSV ${mssv}.` : undefined}
        side={lookupEnabled && tuition.isFetching ? <span className="px-2 text-action"><Spinner /></span> : undefined}
      />

      {loading && <div className="grid gap-3 rounded-xl bg-subtle p-4"><Skeleton className="h-4 w-3/5 bg-line" /><Skeleton className="h-4 w-2/5 bg-line" /><Skeleton className="h-4 bg-line" /></div>}

      {lookupEnabled && tuition.error && !notFound && (
        <Alert action={<Button variant="secondary" onClick={() => tuition.refetch()}>Retry</Button>}>{tuition.error.message}</Alert>
      )}

      {data && (
        <div className="grid gap-3 rounded-xl bg-subtle p-4">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 flex-none items-center justify-center rounded-full bg-card text-ink-2"><GraduationCap className="h-5 w-5" aria-hidden="true" /></span>
            <div className="min-w-0 flex-1">
              <b className="block text-base font-semibold">{data.student_name}</b>
              <small className="text-[13px] text-ink-2">MSSV {data.student_id} · Term {data.term}</small>
            </div>
            <StatusBadge status={held.mine ? held.mine.status : data.status} />
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line-strong pt-3">
            <span className="text-sm text-ink-2">Amount due</span>
            <Money value={data.amount} alwaysVisible className="text-[22px] font-bold" />
          </div>
          {data.status === 'RESERVED' && <HeldNotice {...held} />}
        </div>
      )}
    </Card>
  )
}

// Read-only payer details: name, phone, email (GET /users/me).
export function PayerCard({ profile }) {
  const Item = ({ label, children }) => (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="break-words text-sm font-medium">{children ?? '—'}</dd>
    </div>
  )
  return (
    <Card className="order-2 md:order-none">
      <p className="mb-2.5 flex items-center gap-2 text-sm font-semibold"><Lock className="h-4 w-4" aria-hidden="true" />Paying from your account</p>
      {profile.isPending
        ? <Skeleton />
        : (
          <dl className="grid gap-x-10 gap-y-2 md:flex md:flex-wrap">
            <Item label="Full name">{profile.data?.full_name}</Item>
            <Item label="Phone number">{profile.data?.phone}</Item>
            <Item label="Email">{profile.data?.email}</Item>
          </dl>
        )}
      {profile.error && <div className="mt-2"><Alert>{profile.error.message}</Alert></div>}
    </Card>
  )
}

// Why the Confirm button is disabled, checked in the order the user fixes things; null = enabled.
// `lookup`: idle | loading | notfound | error | ok. `mine` / `ownerUnknown`: who holds a RESERVED tuition.
// `insufficient` is a code, not text: SummaryCard renders it with the missing amount.
export function blockReason({ lookup, tuition, mine, ownerUnknown, balance, agreed }) {
  if (lookup === 'notfound') return 'Check the MSSV and try again.'
  if (lookup === 'loading') return 'Looking up this MSSV…'
  if (lookup === 'error') return 'The lookup failed. Try it again.'
  if (!tuition) return 'Enter an MSSV to find the tuition.'
  if (tuition.status === 'PAID') return 'This tuition is already paid.'
  if (tuition.status !== 'UNPAID') {
    if (ownerUnknown) return 'Checking this tuition…'
    if (mine) return mine.status === 'PROCESSING' ? 'This payment is already being finished.' : 'You already started this payment. Resume or cancel it first.'
    return 'Someone else is paying this tuition right now.'
  }
  if (balance == null) return 'Loading your balance…'
  if (Number(balance) < Number(tuition.amount)) return 'insufficient'
  if (!agreed) return 'Accept the terms & conditions to continue.'
  return null
}

const TERMS = [
  'The full tuition amount is paid in one transaction; partial payment is not possible.',
  'The payment is confirmed with a one-time code sent to your email, valid for 5 minutes.',
  'After it succeeds the payment cannot be reversed from this app.',
]

function TermsCheck({ agreed, onAgreedChange }) {
  return (
    <div className="grid gap-1">
      <label className="flex min-h-11 cursor-pointer items-center gap-2.5 text-[13px]">
        <input type="checkbox" checked={agreed} onChange={(e) => onAgreedChange(e.target.checked)} className="h-5 w-5 flex-none accent-action" />
        <span>I agree to the <b className="font-semibold">terms &amp; conditions</b></span>
      </label>
      <details className="text-xs text-ink-2">
        <summary className="min-h-6">Read the terms</summary>
        <ul className="mt-1 grid list-disc gap-0.5 pl-4">{TERMS.map((t) => <li key={t}>{t}</li>)}</ul>
      </details>
    </div>
  )
}

// The reason text, with the missing amount only when amounts are visible.
function ReasonLine({ reason, shortfall }) {
  const { visible } = useAmountVisibility()
  if (reason === 'insufficient') return <Reason danger>{visible ? `You need ${formatVnd(shortfall)} more.` : 'Your balance is lower than this tuition.'}</Reason>
  return <Reason>{reason}</Reason>
}

// Balance summary, terms and the Confirm / Clear buttons. Confirm stays visible but disabled, with the reason just above it.
// `tuition`: the looked-up tuition or undefined. `balance`: the payer's balance (Decimal string) or undefined while loading.
// `reason`: blockReason's answer. `alert`: message from a failed POST /transactions. `email`: masked address for the code.
// `payable`: on phones the terms and Confirm then move to StickyConfirm.
export function SummaryCard({ tuition, balance, reason, alert, email, agreed, onAgreedChange, onClear, onConfirm, submitting, payable }) {
  const { visible } = useAmountVisibility()
  // Amount to pay; only a tuition that can actually be paid (UNPAID) feeds the summary.
  const amount = tuition?.status === 'UNPAID' ? Number(tuition.amount) : null
  // Balance left after paying; negative means the balance is too low.
  const after = balance != null && amount != null ? Number(balance) - amount : null

  return (
    <section aria-label="Payment summary" className="grid gap-3.5 rounded-2xl border border-line bg-card p-4 md:sticky md:top-20 md:p-6">
      <h2 className="text-lg font-semibold">Payment summary</h2>
      <div className="grid gap-2.5 text-sm">
        <div className="flex items-center justify-between gap-2.5">
          <span className="inline-flex items-center text-ink-2">Available balance<EyeToggle className="h-8 w-8 text-ink-2 hover:bg-subtle" size="h-4 w-4" /></span>
          {balance != null ? <Money value={balance} className="font-medium" /> : <span>—</span>}
        </div>
        <div className="flex items-center justify-between gap-2.5">
          <span className="text-ink-2">Tuition</span>
          {amount != null ? <span className="font-medium">− <Money value={amount} alwaysVisible /></span> : <span>—</span>}
        </div>
        <div className="flex items-center justify-between gap-2.5 border-t border-line pt-2.5 text-base font-bold">
          <span>Balance after</span>
          {after == null ? <span>—</span>
            : after >= 0 ? <Money value={after} />
            : <span className="tabular-nums text-bad">{visible ? `− ${formatVnd(-after)}` : 'Not enough'}</span>}
        </div>
      </div>

      <div className={payable ? 'hidden md:grid md:gap-3.5' : 'grid gap-3.5'}>
        <TermsCheck agreed={agreed} onAgreedChange={onAgreedChange} />
        {alert && <Alert>{alert}</Alert>}
        {reason
          ? <ReasonLine reason={reason} shortfall={after != null ? -after : 0} />
          : <p className="flex items-start gap-2 text-[13px] text-ink-2"><Mail className="mt-0.5 h-4 w-4 flex-none" aria-hidden="true" /><span>Next, we email a 6-digit code to {email || 'your email'}.</span></p>}
        <Button className="w-full" onClick={onConfirm} disabled={reason !== null} loading={submitting}>Confirm and send code</Button>
      </div>
      <Button variant="ghost" className="w-full" onClick={onClear} disabled={submitting}>Clear form</Button>
    </section>
  )
}

// Phones only: terms and Confirm stay reachable at the bottom, and cover the tab bar while a tuition can be paid.
export function StickyConfirm({ tuition, reason, agreed, onAgreedChange, onConfirm, submitting }) {
  return (
    <div className="no-print fixed inset-x-0 bottom-0 z-40 grid gap-1 border-t border-line bg-card px-4 pb-4 pt-2 md:hidden">
      <TermsCheck agreed={agreed} onAgreedChange={onAgreedChange} />
      {reason && <Reason>{reason}</Reason>}
      <Button className="mt-1 w-full" onClick={onConfirm} disabled={reason !== null} loading={submitting}>
        <span>Confirm · <Money value={tuition.amount} alwaysVisible /></span>
      </Button>
    </div>
  )
}
