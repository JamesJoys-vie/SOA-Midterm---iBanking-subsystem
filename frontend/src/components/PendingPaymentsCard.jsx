// Home's pending payments: one call to action per payment, with an expiry bar, Resume and Cancel. Hidden when there are none.
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Clock3 } from 'lucide-react'
import { keys } from '../hooks/queries.js'
import { useSecondsLeft } from '../hooks/useTimers.js'
import { formatClock } from '../utils/format.js'
import CancelPaymentDialog from './CancelPaymentDialog.jsx'
import { OTP_TTL } from './OtpModal.jsx'
import { Button, ExpiryBar, Money } from './ui.jsx'

// Seconds between re-reads once a code ran out, until the expiry job has ended the payment.
const EXPIRY_RECHECK_MS = 5000

// One pending payment. fetchedAt: when the list was loaded (otp_expires_in counts from then).
function PendingRow({ txn, fetchedAt }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  // When the code expires (epoch ms).
  const [deadline] = useState(() => fetchedAt + (txn.otp_expires_in ?? 0) * 1000)
  // Seconds left; 0 disables Resume.
  const left = useSecondsLeft(deadline)
  // The cancel question is open.
  const [asking, setAsking] = useState(false)

  // Timer over: keep re-reading so the card turns into a Cancelled row without a page reload.
  useEffect(() => {
    if (left > 0) return undefined
    const id = setTimeout(() => {
      queryClient.invalidateQueries({ queryKey: keys.transactions })
      queryClient.invalidateQueries({ queryKey: ['tuition'] })
    }, EXPIRY_RECHECK_MS)
    return () => clearTimeout(id)
  }, [left, queryClient])

  // Reopens the OTP modal on /pay; the id goes in router state, not the URL.
  const onResume = () => navigate('/pay', { state: { resumeId: txn.id } })

  return (
    <section aria-label="Payment waiting for code" className="flex flex-wrap items-center gap-x-4 gap-y-2.5 rounded-2xl border-2 border-warn bg-card p-3.5 md:flex-nowrap md:px-5 md:py-4">
      <span className="flex h-10 w-10 flex-none items-center justify-center rounded-full bg-subtle text-warn"><Clock3 className="h-5 w-5" aria-hidden="true" /></span>
      <div className="grid min-w-0 flex-[1_1_calc(100%-56px)] gap-1.5 md:flex-1">
        <b className="text-sm font-semibold">Finish your payment: MSSV {txn.student_id} · <Money value={txn.amount} /></b>
        <small className="text-[13px] text-ink-2">
          {left > 0 ? <>Code expires in <span className="tabular-nums">{formatClock(left)}</span>. Lost the email? Resume and press Resend.</> : 'Code expired. This payment is ending, and no money was taken.'}
        </small>
        <ExpiryBar share={left / OTP_TTL} />
      </div>
      <div className="grid w-full grid-cols-2 gap-2 md:flex md:w-auto">
        <Button variant="ghost" onClick={() => setAsking(true)}>Cancel</Button>
        <Button onClick={onResume} disabled={left === 0}>Resume</Button>
      </div>
      {asking && <CancelPaymentDialog txn={txn} onClose={() => setAsking(false)} />}
    </section>
  )
}

// transactions: shared GET /transactions list. fetchedAt: its load time.
export default function PendingPaymentsCard({ transactions, fetchedAt }) {
  // Payments still waiting for their code.
  const pending = (transactions || []).filter((t) => t.status === 'PENDING_OTP')
  return pending.map((t) => <PendingRow key={t.id} txn={t} fetchedAt={fetchedAt} />)
}
