// Home's "Waiting for OTP" card: pending payments with countdown, Resume and Cancel. Hidden when empty.
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { cancelTransaction } from '../api/client.js'
import { keys } from '../hooks/queries.js'
import { useSecondsLeft } from '../hooks/useTimers.js'
import { formatClock, formatDateTime } from '../utils/format.js'
import { Alert, Button, Card, Money } from './ui.jsx'

// One pending payment. fetchedAt: when the list was loaded (otp_expires_in counts from then).
function PendingRow({ txn, fetchedAt }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  // When the code expires (epoch ms).
  const [deadline] = useState(() => fetchedAt + (txn.otp_expires_in ?? 0) * 1000)
  // Seconds left; 0 disables Resume.
  const left = useSecondsLeft(deadline)
  // Cancels the payment, then reloads the list and balance.
  const cancel = useMutation({
    mutationFn: () => cancelTransaction(txn.id),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: keys.transactions })
      queryClient.invalidateQueries({ queryKey: keys.account })
    },
  })

  // Asks before cancelling.
  const onCancel = () => {
    if (window.confirm(`Cancel the payment for MSSV ${txn.student_id}?`)) cancel.mutate()
  }

  // Reopens the OTP modal on /pay; the id goes in router state, not the URL.
  const onResume = () => navigate('/pay', { state: { resumeId: txn.id } })

  return (
    <li className="flex flex-wrap items-center justify-between gap-3 py-3">
      <div>
        <p className="font-medium text-slate-800">{txn.student_id}</p>
        <p className="text-xs text-slate-500">
          Started {formatDateTime(txn.created_at).slice(-5)} · {left > 0 ? `expires in ${formatClock(left)}` : 'expired'}
        </p>
        {cancel.error && <p className="mt-1 text-xs text-red-600">{cancel.error.message}</p>}
      </div>
      <div className="flex items-center gap-3">
        <Money value={txn.amount} className="font-medium" />
        <Button variant="secondary" onClick={onCancel} loading={cancel.isPending}>Cancel</Button>
        <Button onClick={onResume} disabled={left === 0}>Resume</Button>
      </div>
    </li>
  )
}

// transactions: shared GET /transactions list. fetchedAt: its load time.
export default function PendingPaymentsCard({ transactions, fetchedAt }) {
  // Payments still waiting for their code.
  const pending = (transactions || []).filter((t) => t.status === 'PENDING_OTP')
  if (pending.length === 0) return null
  return (
    <Card title={`Waiting for OTP · ${pending.length}`} hint="Finish or cancel before it expires" className="border-amber-300">
      <Alert kind="warning">Lost the email? Resume and press “Resend code”.</Alert>
      <ul className="divide-y divide-slate-100">
        {pending.map((t) => <PendingRow key={t.id} txn={t} fetchedAt={fetchedAt} />)}
      </ul>
    </Card>
  )
}
