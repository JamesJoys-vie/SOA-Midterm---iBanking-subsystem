// Result step of /pay (see "Result" in docs/wireframes/modernization-proposal.html): replaces the form once an attempt is over.
// Shows success, still processing, or ended without paying (FAILED / EXPIRED / CANCELLED) with the reason.
import { Check, Clock3, Printer, X } from 'lucide-react'
import { failureText, formatDateTime } from '../utils/format.js'
import { Button, CopyId, KeyValue, Money, StatusBadge } from './ui.jsx'

// Look of each outcome: icon, icon color, title and subtitle.
const HEADS = {
  success: { Icon: Check, tone: 'text-ok', title: 'Payment successful', sub: 'A receipt was sent to your email.' },
  processing: { Icon: Clock3, tone: 'text-warn', title: 'Payment is being finished', sub: 'This can take a moment, and we keep checking for you.' },
  failed: { Icon: X, tone: 'text-bad', title: 'Payment not completed', sub: 'No money was taken from your account.' },
}

// `result`: { transaction, balance_after } from verify-otp (balance_after is null when the outcome came from a read).
// `tuition`: the paid tuition (student name, term), may be null. `primary` / `secondary`: { label, onClick } buttons.
export default function ResultCard({ result, tuition, primary, secondary }) {
  // The final (or still finishing) transaction.
  const t = result.transaction
  // "52100001 · Pham Minh D", or just the MSSV when the name is unknown.
  const student = `${t.student_id}${tuition?.student_name ? ` · ${tuition.student_name}` : ''}`
  // Which of the three outcomes to show.
  const variant = t.status === 'SUCCESS' ? 'success' : t.status === 'PROCESSING' || t.status === 'PENDING_OTP' ? 'processing' : 'failed'
  // Header texts and colors for that outcome.
  const head = HEADS[variant]

  return (
    <section aria-label="Result" className="receipt mx-auto grid w-full max-w-[480px] gap-4 rounded-2xl border border-line bg-card px-4 py-5 sm:p-7">
      <div role="status" className="grid justify-items-center gap-1.5 text-center">
        <span className={`flex h-14 w-14 items-center justify-center rounded-full bg-subtle ${head.tone}`}><head.Icon className="h-[26px] w-[26px]" strokeWidth={2.5} aria-hidden="true" /></span>
        <h2 className="text-[21px] font-bold">{head.title}</h2>
        <p className="text-sm text-ink-2">{head.sub}</p>
      </div>

      <div className="border-t border-dashed border-line-strong" />

      <dl className="grid gap-2.5">
        {variant === 'failed'
          ? <KeyValue label="Reason">{failureText(t)}</KeyValue>
          : <KeyValue label="Transaction ID"><CopyId id={t.id} /></KeyValue>}
        <KeyValue label="Student">{student}</KeyValue>
        {tuition?.term && <KeyValue label="Term">{tuition.term}</KeyValue>}
        <KeyValue label="Amount"><Money value={t.amount} alwaysVisible className="font-bold" /></KeyValue>
        {variant === 'success' && result.balance_after != null && (
          <KeyValue label="New balance"><Money value={result.balance_after} /></KeyValue>
        )}
        {variant === 'success'
          ? <KeyValue label="Completed">{formatDateTime(t.completed_at)}</KeyValue>
          : <KeyValue label="Status"><StatusBadge status={t.status} /></KeyValue>}
      </dl>

      {variant === 'success' && (
        <button type="button" onClick={() => window.print()} className="no-print inline-flex min-h-11 items-center justify-center gap-1.5 text-[13px] font-medium text-ink-2">
          <Printer className="h-4 w-4" aria-hidden="true" />Print receipt
        </button>
      )}

      <div className="no-print grid grid-cols-2 gap-2.5">
        {secondary && <Button variant="secondary" onClick={secondary.onClick}>{secondary.label}</Button>}
        {primary && <Button onClick={primary.onClick}>{primary.label}</Button>}
      </div>
    </section>
  )
}
