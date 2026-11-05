// /history: all transactions with MSSV search, filter chips, day groups and paging.
import { RefreshCw } from 'lucide-react'
import { useTransactions } from '../hooks/queries.js'
import HistoryTable from '../components/HistoryTable.jsx'
import { Alert, Button } from '../components/ui.jsx'

export default function HistoryPage() {
  // Transaction list (same cache as Home).
  const txns = useTransactions()

  return (
    <div className="grid gap-3.5 md:gap-5">
      <div className="flex items-center justify-between gap-3">
        <h1 tabIndex={-1} className="text-[22px] font-bold outline-none md:text-[26px]">Transaction history</h1>
        <button
          type="button"
          onClick={() => txns.refetch()}
          aria-label="Refresh"
          title="Refresh"
          className="flex h-11 w-11 items-center justify-center rounded-[10px] border border-line-strong bg-card text-ink-2 hover:text-ink"
        >
          {/* Spins only on a manual refresh. */}
          <RefreshCw className={`h-[18px] w-[18px] ${txns.isFetching && !txns.isPending ? 'animate-spin' : ''}`} aria-hidden="true" />
        </button>
      </div>
      <section aria-label="Transactions" className="overflow-hidden rounded-2xl border border-line bg-card">
        {txns.error ? (
          <div className="p-4"><Alert action={<Button variant="secondary" onClick={() => txns.refetch()}>Retry</Button>}>{txns.error.message}</Alert></div>
        ) : (
          <HistoryTable transactions={txns.data} loading={txns.isPending} />
        )}
      </section>
    </div>
  )
}
