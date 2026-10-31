// Result step of /pay (see "5. Result" in docs/wireframes/wireframes.html): replaces the form once an attempt is over.
// Shows success, still processing, or ended without paying (FAILED / EXPIRED / CANCELLED) with the reason.
import { failureText, formatDateTime, shortId } from '../utils/format.js'
import { Button, Card, Money, ReadOnlyField, StatusBadge } from './ui.jsx'

// Look of each outcome: icon, icon colours, title and subtitle.
const HEADS = {
  success: { icon: '✓', ring: 'bg-emerald-100 text-emerald-700', title: 'Payment successful', sub: 'A receipt was sent to your email.' },
  processing: { icon: '…', ring: 'bg-blue-100 text-blue-700', title: 'Payment is being finished', sub: 'This can take a moment. Check History for the final status.' },
  failed: { icon: '✕', ring: 'bg-red-100 text-red-700', title: 'Payment failed', sub: 'No money was taken from your account.' },
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
  // Header texts and colours for that outcome.
  const head = HEADS[variant]

  return (
    <Card className="mx-auto max-w-[480px]">
      <div className="text-center">
        <div className={`mx-auto flex h-14 w-14 items-center justify-center rounded-full text-2xl font-bold ${head.ring}`}>{head.icon}</div>
        <h2 className="mt-3 text-xl font-semibold text-slate-900">{head.title}</h2>
        <p className="text-sm text-slate-500">{head.sub}</p>
      </div>

      <div className="mt-5 border-t border-slate-100 pt-3">
        {variant === 'failed' && <ReadOnlyField label="Reason">{failureText(t)}</ReadOnlyField>}
        <ReadOnlyField label="Transaction ID"><span className="font-mono text-xs" title={t.id}>{shortId(t.id)}</span></ReadOnlyField>
        <ReadOnlyField label="Student">{student}</ReadOnlyField>
        {tuition?.term && <ReadOnlyField label="Term">{tuition.term}</ReadOnlyField>}
        <ReadOnlyField label="Amount"><Money value={t.amount} /></ReadOnlyField>
        {variant === 'success' && result.balance_after != null && (
          <ReadOnlyField label="New balance"><Money value={result.balance_after} /></ReadOnlyField>
        )}
        {variant === 'success'
          ? <ReadOnlyField label="Completed">{formatDateTime(t.completed_at)}</ReadOnlyField>
          : <ReadOnlyField label="Status"><StatusBadge status={t.status} /></ReadOnlyField>}
      </div>

      <div className="mt-5 flex justify-center gap-2">
        {secondary && <Button variant="secondary" onClick={secondary.onClick}>{secondary.label}</Button>}
        {primary && <Button onClick={primary.onClick}>{primary.label}</Button>}
      </div>
    </Card>
  )
}
