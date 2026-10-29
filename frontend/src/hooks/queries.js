// Shared React Query hooks. One cache entry per resource, reused across pages.
import { useQuery } from '@tanstack/react-query'
import { getAccount, getHistory, getProfile } from '../api/client.js'

export const keys = {
  profile: ['profile'],
  account: ['account'],
  transactions: ['transactions'],
}

export const useProfile = () => useQuery({ queryKey: keys.profile, queryFn: getProfile, staleTime: 5 * 60_000 })
export const useAccount = () => useQuery({ queryKey: keys.account, queryFn: getAccount })
export const useTransactions = () => useQuery({ queryKey: keys.transactions, queryFn: getHistory })
