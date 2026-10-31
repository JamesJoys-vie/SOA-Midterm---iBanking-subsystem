// /home: landing page after login (see "2. Home" in docs/wireframes/wireframes.html): balance, success /
// not-completed counts, pending OTPs, last 5 transactions. One cached GET /transactions feeds every section.
import { Link } from 'react-router-dom'
import { useAccount, useProfile, useTransactions } from '../hooks/queries.js'
import { ENDED_STATUSES } from '../utils/format.js'
import HistoryTable from '../components/HistoryTable.jsx'
import PendingPaymentsCard from '../components/PendingPaymentsCard.jsx'
import { Alert, Button, Card, EyeToggle, Money, Skeleton, StatCard } from '../components/ui.jsx'

export default function HomePage() {
  // Payer profile (name, username), balance, and the shared transaction list.
  const profile = useProfile()
  const account = useAccount()
  const txns = useTransactions()

  // Transactions (newest first), empty while loading so the counts below never break.
  const list = txns.data || []
  // Payments that went through.
  const succeeded = list.filter((t) => t.status === 'SUCCESS')
  // Attempts that ended without paying (FAILED / EXPIRED / CANCELLED).
  const notCompleted = list.filter((t) => ENDED_STATUSES.includes(t.status))
  // Sum of the successful payments, shown under their count.
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

      {/* key = fetch time: each refetch remounts the card so every countdown restarts from fresh otp_expires_in. */}
      <PendingPaymentsCard key={txns.dataUpdatedAt} transactions={list} fetchedAt={txns.dataUpdatedAt} />

      <Card title="Recent transactions" hint={<Link to="/history" className="text-sm text-blue-600 hover:underline">View all →</Link>}>
        <HistoryTable transactions={txns.data} loading={txns.isPending} compact />
      </Card>
    </div>
  )
}
