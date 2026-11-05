// Transaction list. Full mode (History): search, filter chips, day groups, paging. Compact mode (Home): 5 newest rows.
// Both open the same details drawer. Filters stay in component state, never in the URL.
import { Fragment, useMemo, useState } from 'react'
import { ChevronLeft, ChevronRight, Search } from 'lucide-react'
import { dayLabel, formatDateTime, formatTime, shortId } from '../utils/format.js'
import { STATUS_FILTERS, statusLabel } from '../utils/status.js'
import TransactionDetails from './TransactionDetails.jsx'
import { ButtonLink, Money, Skeleton, StatusBadge } from './ui.jsx'

// Rows per page (full mode).
const PAGE_SIZE = 10
// Rows shown in compact mode.
const COMPACT_ROWS = 5

// Shown when the user has no transactions yet.
export function EmptyTransactions() {
  return (
    <div className="grid justify-items-center gap-1 px-4 py-10 text-center">
      <p className="text-base font-semibold">No transactions yet</p>
      <p className="mb-3 text-sm text-ink-2">Payments you make will appear here.</p>
      <ButtonLink to="/pay">Pay tuition</ButtonLink>
    </div>
  )
}

// One transaction. Two lines on phones so Amount and Status are never pushed off-screen.
function TransactionRow({ txn, subtitle, onOpen }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={`MSSV ${txn.student_id}, ${statusLabel(txn.status)}, open details`}
      className="grid min-h-[60px] w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 border-t border-line px-4 py-3 text-left hover:bg-subtle md:grid-cols-[minmax(0,1fr)_140px_160px_16px] md:gap-x-3.5"
    >
      <span className="row-span-2 min-w-0 md:row-span-1">
        <b className="block text-sm font-semibold">MSSV {txn.student_id}</b>
        <small className="block truncate text-xs text-muted">{subtitle}</small>
      </span>
      <span className="text-right text-sm font-semibold"><Money value={txn.amount} /></span>
      <span className="justify-self-end md:justify-self-start"><StatusBadge status={txn.status} /></span>
      <ChevronRight className="hidden h-4 w-4 text-muted md:block" aria-hidden="true" />
    </button>
  )
}

// transactions: list from GET /transactions (newest first). loading: show skeletons. compact: Home mode.
export default function HistoryTable({ transactions, loading, compact = false }) {
  // MSSV search text.
  const [mssv, setMssv] = useState('')
  // Selected filter chip.
  const [filter, setFilter] = useState('all')
  // Requested page (1-based).
  const [page, setPage] = useState(1)
  // Id of the transaction shown in the drawer.
  const [openId, setOpenId] = useState(null)

  // Rows after filtering (full) or the newest rows (compact).
  const filtered = useMemo(() => {
    const list = transactions || []
    if (compact) return list.slice(0, COMPACT_ROWS)
    const statuses = STATUS_FILTERS.find((f) => f.id === filter).statuses
    return list.filter((t) => (!mssv || t.student_id.toUpperCase().includes(mssv.trim().toUpperCase())) && (!statuses || statuses.includes(t.status)))
  }, [transactions, compact, mssv, filter])

  // Total pages (at least 1).
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  // Page shown, kept within range.
  const current = Math.min(page, pages)
  // Rows on screen.
  const rows = compact ? filtered : filtered.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE)
  // Latest copy of the open transaction, so the drawer follows refetches.
  const openTxn = (transactions || []).find((t) => t.id === openId)

  if (!loading && transactions?.length === 0) return <EmptyTransactions />

  return (
    <>
      {!compact && (
        <div className="flex flex-wrap items-center gap-2.5 p-3 md:p-4">
          <div className="relative w-full md:w-[260px]">
            <Search className="absolute left-3 top-3 h-4 w-4 text-muted" aria-hidden="true" />
            <input
              value={mssv}
              // New search -> back to page 1.
              onChange={(e) => { setMssv(e.target.value); setPage(1) }}
              placeholder="Search by MSSV"
              aria-label="Search by MSSV"
              autoCapitalize="characters"
              autoComplete="off"
              className="h-10 w-full rounded-[10px] border border-line-strong bg-card pl-[34px] pr-3 text-[13px] outline-none focus:border-action focus:ring-1 focus:ring-action"
            />
          </div>
          <div role="group" aria-label="Filter by status" className="flex w-full gap-1.5 overflow-x-auto [scrollbar-width:none] md:w-auto md:flex-wrap md:overflow-visible">
            {STATUS_FILTERS.map((f) => (
              <button
                key={f.id}
                type="button"
                aria-pressed={filter === f.id}
                onClick={() => { setFilter(f.id); setPage(1) }}
                className={`min-h-11 flex-none rounded-full border px-3.5 text-[13px] md:min-h-9 ${filter === f.id ? 'border-action bg-action font-semibold text-white' : 'border-line-strong bg-card font-medium text-ink-2'}`}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {loading && Array.from({ length: compact ? 3 : 4 }, (_, i) => (
        <div key={i} className="border-t border-line px-4 py-[18px]"><Skeleton /></div>
      ))}

      {!loading && rows.map((t, i) => {
        // Full mode starts a new group whenever the day changes.
        const day = compact ? null : dayLabel(t.created_at)
        const newDay = day && (i === 0 || dayLabel(rows[i - 1].created_at) !== day)
        return (
          <Fragment key={t.id}>
            {newDay && <div className="border-t border-line px-4 pb-1.5 pt-3.5 text-xs font-semibold text-muted">{day}</div>}
            <TransactionRow
              txn={t}
              subtitle={`${compact ? formatDateTime(t.created_at) : formatTime(t.created_at)} · ${shortId(t.id)}`}
              onOpen={() => setOpenId(t.id)}
            />
          </Fragment>
        )
      })}

      {!loading && rows.length === 0 && (
        <div className="grid gap-1 border-t border-line px-4 py-10 text-center">
          <p className="text-base font-semibold">No transactions match</p>
          <p className="text-sm text-ink-2">Try another MSSV or status.</p>
        </div>
      )}

      {!compact && !loading && filtered.length > 0 && (
        <div className="flex items-center justify-between gap-2.5 border-t border-line px-4 py-2.5 text-[13px] text-muted">
          <span>Showing {(current - 1) * PAGE_SIZE + 1}–{Math.min(current * PAGE_SIZE, filtered.length)} of {filtered.length}</span>
          <div className="flex items-center gap-1">
            <button type="button" disabled={current === 1} onClick={() => setPage(current - 1)} aria-label="Previous page" className="flex h-9 w-9 items-center justify-center rounded-lg hover:bg-subtle disabled:opacity-35"><ChevronLeft className="h-4 w-4" aria-hidden="true" /></button>
            <span>{current} / {pages}</span>
            <button type="button" disabled={current === pages} onClick={() => setPage(current + 1)} aria-label="Next page" className="flex h-9 w-9 items-center justify-center rounded-lg hover:bg-subtle disabled:opacity-35"><ChevronRight className="h-4 w-4" aria-hidden="true" /></button>
          </div>
        </div>
      )}

      {openTxn && <TransactionDetails txn={openTxn} onClose={() => setOpenId(null)} />}
    </>
  )
}
