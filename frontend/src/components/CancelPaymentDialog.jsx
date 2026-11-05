// "Cancel this payment?" for a payment still waiting for its code. Used by Home's pending card and by /pay.
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { cancelTransaction } from '../api/client.js'
import { keys } from '../hooks/queries.js'
import { ConfirmDialog } from './Dialog.jsx'
import { Money } from './ui.jsx'

// `txn`: the PENDING_OTP transaction. `onClose`: the dialog is done. `onCancelled`: the payment was cancelled.
export default function CancelPaymentDialog({ txn, onClose, onCancelled }) {
  const queryClient = useQueryClient()
  // Cancels the payment (releases the tuition), then reloads everything that shows it.
  const cancel = useMutation({
    mutationFn: () => cancelTransaction(txn.id),
    onSuccess: () => { onCancelled?.(); onClose() },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: keys.transactions })
      queryClient.invalidateQueries({ queryKey: keys.account })
      queryClient.invalidateQueries({ queryKey: ['tuition'] })
    },
  })

  return (
    <ConfirmDialog
      title="Cancel this payment?"
      body="No money has been taken. The tuition is released so it can be paid again."
      recap={(
        <div className="flex items-center justify-between gap-2.5 rounded-[10px] bg-subtle px-3 py-2.5 text-[13px] text-ink-2">
          <span>MSSV {txn.student_id}</span>
          <Money value={txn.amount} className="text-sm font-semibold text-ink" />
        </div>
      )}
      error={cancel.error?.message}
      keepLabel="Keep it"
      confirmLabel="Yes, cancel"
      busy={cancel.isPending}
      onKeep={onClose}
      onConfirm={() => cancel.mutate()}
    />
  )
}
