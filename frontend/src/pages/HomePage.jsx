// /home: balance hero, payment counts, pending payments, recent transactions. One shared GET /transactions feeds it all.
import { Link } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'
import { useAccount, useProfile, useTransactions } from '../hooks/queries.js'
import { ENDED_STATUSES } from '../utils/format.js'
import HistoryTable from '../components/HistoryTable.jsx'
import PendingPaymentsCard from '../components/PendingPaymentsCard.jsx'
import { Alert, Button, ButtonLink, EyeToggle, Money, Skeleton } from '../components/ui.jsx'

// One line of the counts card. `caption` is hidden on phones, where the two counts sit side by side.
const Count = ({ label, value, caption, className = '' }) => (
  <div className={`min-w-0 md:py-3.5 ${className}`}>
    <p className="text-[13px] text-ink-2">{label}</p>
    <div className="flex flex-wrap items-baseline gap-x-2.5">
      <b className="text-[22px] font-bold md:text-2xl">{value}</b>
      <small className="hidden text-[13px] text-ink-2 md:inline">{caption}</small>
    </div>
  </div>
)

export default function HomePage() {
  // Profile, balance and transaction list.
  const profile = useProfile()
  const account = useAccount()
  const txns = useTransactions()

  // Transactions, or [] while loading.
  const list = txns.data || []
  // Successful payments.
  const succeeded = list.filter((t) => t.status === 'SUCCESS')
  // Failed, timed-out or cancelled payments.
  const notCompleted = list.filter((t) => ENDED_STATUSES.includes(t.status))
  // Total of successful payments.
  const totalPaid = succeeded.reduce((sum, t) => sum + Number(t.amount), 0)

  return (
    <div className="grid gap-3.5 md:gap-5">
      <h1 tabIndex={-1} className="text-[22px] font-bold outline-none md:text-[26px]">
        Welcome back{profile.data ? `, ${profile.data.full_name}` : ''}
      </h1>

      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_340px] md:gap-5">
        <section aria-label="Balance" className="flex flex-col gap-3.5 rounded-[18px] bg-hero p-5 text-white md:gap-[18px] md:rounded-[20px] md:p-7">
          <div className="flex items-center gap-1 text-sm text-white/90">
            <span>Available balance</span>
            <EyeToggle className="h-9 w-9 hover:bg-white/15 focus-visible:outline-white" />
          </div>
          <div>
            <div className="text-[30px] font-bold leading-tight md:text-[44px]">
              {account.isPending ? <Skeleton className="h-10 w-2/3 opacity-30" /> : account.error ? '—' : <Money value={account.data.balance} />}
            </div>
            <p className="mt-1 text-[13px] text-white/80">{profile.data ? `Account · ${profile.data.username}` : ' '}</p>
          </div>
          <ButtonLink to="/pay" variant="onHero" className="self-stretch md:self-start">Pay tuition</ButtonLink>
        </section>

        <section aria-label="Payment counts" className="grid grid-cols-2 content-center rounded-2xl border border-line bg-card p-3.5 md:grid-cols-1 md:px-5 md:py-1.5">
          <Count label="Successful payments" value={txns.isPending ? '–' : succeeded.length} caption={<><Money value={totalPaid} /> total</>} />
          <Count label="Not completed" value={txns.isPending ? '–' : notCompleted.length} caption="Failed or cancelled" className="border-l border-line pl-3.5 md:border-l-0 md:border-t md:pl-0" />
        </section>
      </div>

      {(account.error || txns.error) && (
        <Alert action={<Button variant="secondary" onClick={() => { account.refetch(); txns.refetch() }}>Retry</Button>}>
          {(account.error || txns.error).message}
        </Alert>
      )}

      {/* Remount on each refetch so countdowns restart from fresh data. */}
      <PendingPaymentsCard key={txns.dataUpdatedAt} transactions={list} fetchedAt={txns.dataUpdatedAt} />

      <section aria-label="Recent transactions" className="overflow-hidden rounded-2xl border border-line bg-card">
        <div className="flex items-center justify-between px-4 pb-1 pt-2 md:pb-2 md:pt-3.5">
          <h2 className="text-base font-semibold">Recent transactions</h2>
          {list.length > 0 && (
            <Link to="/history" className="inline-flex min-h-11 items-center gap-1.5 px-1.5 text-sm font-medium text-ink-2">View all <ArrowRight className="h-4 w-4" aria-hidden="true" /></Link>
          )}
        </div>
        <HistoryTable transactions={txns.data} loading={txns.isPending} compact />
      </section>
    </div>
  )
}
