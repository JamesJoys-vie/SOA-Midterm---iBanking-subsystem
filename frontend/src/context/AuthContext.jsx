import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { getToken, setToken, setUnauthorizedHandler } from '../api/client.js'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const queryClient = useQueryClient()
  const [token, setTokenState] = useState(getToken())
  const signIn = (t) => { setToken(t); setTokenState(t) }
  // Drop cached data too, so the next user never sees the previous user's balance or history.
  const signOut = useCallback(() => { setToken(null); setTokenState(null); queryClient.clear() }, [queryClient])

  useEffect(() => { setUnauthorizedHandler(signOut) }, [signOut])

  return <AuthContext.Provider value={{ token, signIn, signOut }}>{children}</AuthContext.Provider>
}

export const useAuth = () => useContext(AuthContext)
