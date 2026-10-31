// /home: balance, payment counts, pending payments, recent transactions. One shared GET /transactions feeds it all.
import { Link } from 'react-router-dom'
import { useAccount, useProfile, useTransactions } from '../hooks/queries.js'
import { ENDED_STATUSES } from '../utils/format.js'
import HistoryTable from '../components/HistoryTable.jsx'
import PendingPaymentsCard from '../components/PendingPaymentsCard.jsx'
import { Alert, Button, Card, EyeToggle, Money, Skeleton, StatCard } from '../components/ui.jsx'

export default function HomePage() {
  // Profile, balance and transaction list.
  const profile = useProfile()
  const account = useAccount()
  const txns = useTransactions()

  // Transactions, or [] while loading.
  const list = txns.data || []
  // Successful payments.
  const succeeded = list.filter((t) => t.status === 'SUCCESS')
  // Failed, expired or cancelled payments.
  const notCompleted = list.filter((t) => ENDED_STATUSES.includes(t.status))
  // Total of successful payments.
  const totalPaid = succeeded.reduce((sum, t) => sum + Number(t.amount), 0)

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">
            Welcome back{profile.data ? `, ${profile.data.full_name}` : ''}
          </h1>
          <p className="text-sm text-slate-500">Here is the status of your account.</p>
        </div>
        <Link to="/pay" className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700">Pay tuition</Link>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard
          label="Available balance"
          action={<EyeToggle className="-mr-2 -mt-1" />}
          value={account.isPending ? <Skeleton className="h-8 w-40" /> : account.error ? '—' : <Money value={account.data.balance} />}
          caption={profile.data ? `Account · ${profile.data.username}` : ' '}
        />
        <StatCard
          label="Successful payments"
          value={txns.isPending ? <Skeleton className="h-8 w-12" /> : succeeded.length}
          caption={<><Money value={totalPaid} /> in total</>}
        />
        <StatCard
          label="Not completed"
          value={txns.isPending ? <Skeleton className="h-8 w-12" /> : notCompleted.length}
          caption="Failed, expired or cancelled"
        />
      </div>

      {(account.error || txns.error) && (
        <Alert action={<Button variant="secondary" onClick={() => { account.refetch(); txns.refetch() }}>Retry</Button>}>
          {(account.error || txns.error).message}
        </Alert>
      )}

      {/* Remount on each refetch so countdowns restart from fresh data. */}
      <PendingPaymentsCard key={txns.dataUpdatedAt} transactions={list} fetchedAt={txns.dataUpdatedAt} />

      <Card title="Recent transactions" hint={<Link to="/history" className="text-sm text-blue-600 hover:underline">View all →</Link>}>
        <HistoryTable transactions={txns.data} loading={txns.isPending} compact />
      </Card>
    </div>
  )
}
