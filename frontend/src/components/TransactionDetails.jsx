// Details drawer opened from a transaction row. This is where the failure reason is visible, also on touch screens.
import { useNavigate } from 'react-router-dom'
import { ENDED_STATUSES, failureText, formatDateTime } from '../utils/format.js'
import { Drawer } from './Dialog.jsx'
import { Button, CopyId, KeyValue, Money, StatusBadge } from './ui.jsx'

export default function TransactionDetails({ txn, onClose }) {
  const navigate = useNavigate()
  // Ended without paying: explain why and offer a new attempt.
  const ended = ENDED_STATUSES.includes(txn.status)

  return (
    <Drawer title="Transaction details" onClose={onClose}>
      <div><StatusBadge status={txn.status} /></div>
      <div className="text-[30px] font-bold leading-tight"><Money value={txn.amount} /></div>
      {ended && (
        <div className="grid gap-1 rounded-[10px] border border-bad p-3 text-sm">
          <b className="text-xs font-semibold text-bad">Why it did not complete</b>
          <span>{failureText(txn)}. No money was taken from your account.</span>
        </div>
      )}
      <dl className="grid gap-2.5">
        <KeyValue label="MSSV">{txn.student_id}</KeyValue>
        <KeyValue label="Created">{formatDateTime(txn.created_at)}</KeyValue>
        {txn.completed_at && <KeyValue label="Completed">{formatDateTime(txn.completed_at)}</KeyValue>}
        <KeyValue label="Transaction ID"><CopyId id={txn.id} /></KeyValue>
      </dl>
      {/* Ids and MSSVs travel in router state, never in the URL. */}
      {txn.status === 'PENDING_OTP' && <Button className="w-full" onClick={() => navigate('/pay', { state: { resumeId: txn.id } })}>Resume payment</Button>}
      {ended && <Button className="w-full" onClick={() => navigate('/pay', { state: { mssv: txn.student_id } })}>Pay this MSSV again</Button>}
    </Drawer>
  )
}
