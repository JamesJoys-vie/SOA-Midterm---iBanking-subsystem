// Global "hide / show amounts" flag. Visual privacy only: values are still in the API responses.
// Remembered per browser in localStorage, hidden by default.
import { createContext, useContext, useState } from 'react'

const KEY = 'amountsVisible'
const AmountVisibilityContext = createContext({ visible: false, toggle: () => {} })

const read = () => {
  try { return localStorage.getItem(KEY) === '1' } catch { return false }
}

export function AmountVisibilityProvider({ children }) {
  const [visible, setVisible] = useState(read)
  const toggle = () => setVisible((v) => {
    try { localStorage.setItem(KEY, v ? '0' : '1') } catch { /* storage blocked: keep in memory only */ }
    return !v
  })
  return <AmountVisibilityContext.Provider value={{ visible, toggle }}>{children}</AmountVisibilityContext.Provider>
}

export const useAmountVisibility = () => useContext(AmountVisibilityContext)
