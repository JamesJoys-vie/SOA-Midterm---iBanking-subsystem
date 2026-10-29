// Temporary page for routes whose screens are built in later segments. Shows the layout, auth and
// hide / show amounts working end to end (profile + balance from the API).
import { useAccount, useProfile } from '../hooks/queries.js'
import { Alert, Card, EyeToggle, Money, ReadOnlyField, Skeleton } from '../components/ui.jsx'

export default function PlaceholderPage({ title }) {
  const profile = useProfile()
  const account = useAccount()

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-slate-900">{title}</h1>
      <Card title="Signed in as" hint="This screen is not built yet">
        {profile.isError && <Alert>{profile.error.message}</Alert>}
        <ReadOnlyField label="Full name">{profile.data?.full_name ?? <Skeleton className="h-4 w-32" />}</ReadOnlyField>
        <ReadOnlyField label="Email">{profile.data?.email ?? <Skeleton className="h-4 w-40" />}</ReadOnlyField>
        <ReadOnlyField label="Balance">
          {account.isError ? '—' : account.data
            ? <span className="inline-flex items-center gap-1"><Money value={account.data.balance} /><EyeToggle /></span>
            : <Skeleton className="h-4 w-28" />}
        </ReadOnlyField>
      </Card>
    </div>
  )
}
