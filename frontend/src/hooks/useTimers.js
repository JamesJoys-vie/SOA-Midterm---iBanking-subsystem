// Time-based React hooks shared by the payment screens.
import { useEffect, useState } from 'react'

// Returns `value` only after it has stopped changing for `delay` ms. /pay uses it so the tuition lookup
// fires once the user pauses typing the MSSV, instead of one request per keystroke.
export function useDebounce(value, delay = 400) {
  // Last value that stayed unchanged for a full `delay`; starts equal to the first value.
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    // Each new value restarts the timer; the cleanup cancels the timer of the previous value.
    const id = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(id)
  }, [value, delay])
  return debounced
}
