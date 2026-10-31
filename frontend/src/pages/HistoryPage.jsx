// /history: every transaction (GET /transactions, newest first, max 100) with client-side MSSV / status filters
// and paging (see "6. History" in docs/wireframes/wireframes.html).
import { useTransactions } from '../hooks/queries.js'
import HistoryTable from '../components/HistoryTable.jsx'
import { Alert, Button, Card } from '../components/ui.jsx'

export default function HistoryPage() {
  // Shared transaction list (same cache entry as Home, so switching pages is instant).
  const txns = useTransactions()

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-slate-900">Transaction history</h1>
        {/* Spinner only for a manual refresh, not for the first load (the table shows skeletons then). */}
        <Button variant="secondary" onClick={() => txns.refetch()} loading={txns.isFetching && !txns.isPending}>Refresh</Button>
      </div>
      <Card>
        {txns.error ? (
          <Alert action={<Button variant="secondary" onClick={() => txns.refetch()}>Retry</Button>}>{txns.error.message}</Alert>
        ) : (
          <HistoryTable transactions={txns.data} loading={txns.isPending} />
        )}
      </Card>
    </div>
  )
}
