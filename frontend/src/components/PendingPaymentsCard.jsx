// Home's "Waiting for OTP" card (see "2. Home" in docs/wireframes/wireframes.html): PENDING_OTP transactions with a
// live countdown, Resume (reopens the OTP modal on /pay) and Cancel. Hidden when nothing is pending.
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { cancelTransaction } from '../api/client.js'
import { keys } from '../hooks/queries.js'
import { useSecondsLeft } from '../hooks/useTimers.js'
import { formatClock, formatDateTime } from '../utils/format.js'
import { Alert, Button, Card, Money } from './ui.jsx'

// One pending transaction. `txn`: the transaction; `fetchedAt`: epoch ms when the list was fetched
// (its `otp_expires_in` counts from that moment).
function PendingRow({ txn, fetchedAt }) {
  // Opens /pay for Resume.
  const navigate = useNavigate()
  // Refreshes history and balance after a cancel.
  const queryClient = useQueryClient()
  // Epoch ms when this transaction's current code expires; fixed for the row's lifetime (the card remounts on refetch).
  const [deadline] = useState(() => fetchedAt + (txn.otp_expires_in ?? 0) * 1000)
  // Seconds left, ticking every second; 0 disables Resume.
  const left = useSecondsLeft(deadline)
  // POST /transactions/{id}/cancel; whatever the outcome, reload the list and balance so the card shows the truth.
  const cancel = useMutation({
    mutationFn: () => cancelTransaction(txn.id),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: keys.transactions })
      queryClient.invalidateQueries({ queryKey: keys.account })
    },
  })

  // Cancel button: confirm first, as the wireframe asks.
  const onCancel = () => {
    if (window.confirm(`Cancel the payment for MSSV ${txn.student_id}?`)) cancel.mutate()
  }

  // Resume button: the id travels in router state, not in the URL, so the address bar stays plain /pay.
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

// `transactions`: the shared GET /transactions list. `fetchedAt`: when it was fetched (React Query dataUpdatedAt).
export default function PendingPaymentsCard({ transactions, fetchedAt }) {
  // Only the transactions still waiting for their code.
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
