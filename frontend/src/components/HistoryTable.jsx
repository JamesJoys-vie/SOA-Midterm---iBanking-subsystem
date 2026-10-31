// Transactions table. Full mode (History): filters + paging. Compact mode (Home): 5 newest rows.
// Filters stay in component state, never in the URL.
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { formatDateTime, shortId } from '../utils/format.js'
import { Money, Skeleton, StatusBadge } from './ui.jsx'

// Status filter options.
const STATUSES = ['SUCCESS', 'PENDING_OTP', 'PROCESSING', 'FAILED', 'EXPIRED', 'CANCELLED']
// Rows per page (full mode).
const PAGE_SIZE = 10
// Rows shown in compact mode.
const COMPACT_ROWS = 5

// Shown when the user has no transactions yet.
export function EmptyTransactions() {
  return (
    <div className="py-10 text-center">
      <p className="font-medium text-slate-800">No transactions yet</p>
      <p className="mt-1 text-sm text-slate-500">Payments you make will appear here.</p>
      <Link to="/pay" className="mt-4 inline-block rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700">Pay tuition</Link>
    </div>
  )
}

// transactions: list from GET /transactions (newest first). loading: show skeletons. compact: Home mode.
export default function HistoryTable({ transactions, loading, compact = false }) {
  // MSSV search text.
  const [mssv, setMssv] = useState('')
  // Selected status ('' = all).
  const [status, setStatus] = useState('')
  // Requested page (1-based).
  const [page, setPage] = useState(1)

  // Rows after filtering (full) or the newest rows (compact).
  const filtered = useMemo(() => {
    const list = transactions || []
    if (compact) return list.slice(0, COMPACT_ROWS)
    return list.filter((t) => (!mssv || t.student_id.toUpperCase().includes(mssv.trim().toUpperCase())) && (!status || t.status === status))
  }, [transactions, compact, mssv, status])

  // Total pages (at least 1).
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  // Page shown, kept within range.
  const current = Math.min(page, pages)
  // Rows on screen.
  const rows = compact ? filtered : filtered.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE)

  if (!loading && transactions?.length === 0) return <EmptyTransactions />

  return (
    <div className="space-y-3">
      {!compact && (
        <div className="flex flex-wrap gap-2">
          <input
            value={mssv}
            // New search -> back to page 1.
            onChange={(e) => { setMssv(e.target.value); setPage(1) }}
            placeholder="Search by MSSV"
            aria-label="Search by MSSV"
            autoCapitalize="characters"
            autoComplete="off"
            className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500 sm:max-w-xs"
          />
          <select
            value={status}
            onChange={(e) => { setStatus(e.target.value); setPage(1) }}
            aria-label="Filter by status"
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
          >
            <option value="">All statuses</option>
            {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
              <th className="py-2 pr-3 font-medium">Date</th>
              {!compact && <th className="py-2 pr-3 font-medium">Transaction ID</th>}
              <th className="py-2 pr-3 font-medium">MSSV</th>
              <th className="py-2 pr-3 text-right font-medium">Amount</th>
              <th className="py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {loading && Array.from({ length: compact ? 3 : 4 }, (_, i) => (
              <tr key={i} className="border-b border-slate-100">
                <td colSpan={compact ? 4 : 5} className="py-3"><Skeleton /></td>
              </tr>
            ))}
            {!loading && rows.map((t) => (
              <tr key={t.id} className="border-b border-slate-100 last:border-0">
                <td className="whitespace-nowrap py-2.5 pr-3 text-slate-600">{formatDateTime(t.created_at)}</td>
                {!compact && <td className="py-2.5 pr-3 font-mono text-xs text-slate-500" title={t.id}>{shortId(t.id)}</td>}
                <td className="py-2.5 pr-3 font-medium text-slate-800">{t.student_id}</td>
                <td className="py-2.5 pr-3 text-right"><Money value={t.amount} /></td>
                {/* Hover shows the failure reason. */}
                <td className="py-2.5" title={t.failure_reason || undefined}><StatusBadge status={t.status} /></td>
              </tr>
            ))}
            {!loading && rows.length === 0 && (
              <tr><td colSpan={5} className="py-8 text-center text-slate-500">No transactions match these filters.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {!compact && !loading && filtered.length > 0 && (
        <div className="flex items-center justify-between text-sm text-slate-500">
          <span>Showing {(current - 1) * PAGE_SIZE + 1}–{Math.min(current * PAGE_SIZE, filtered.length)} of {filtered.length}</span>
          <div className="flex items-center gap-1">
            <button type="button" disabled={current === 1} onClick={() => setPage(current - 1)} className="rounded px-2 py-1 hover:bg-slate-100 disabled:opacity-40" aria-label="Previous page">‹</button>
            <span className="px-2">{current} / {pages}</span>
            <button type="button" disabled={current === pages} onClick={() => setPage(current + 1)} className="rounded px-2 py-1 hover:bg-slate-100 disabled:opacity-40" aria-label="Next page">›</button>
          </div>
        </div>
      )}
    </div>
  )
}
