// Time-based React hooks shared by the payment screens (MSSV lookup debounce, OTP countdowns).
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

// Whole seconds left until `deadline` (epoch ms), re-rendering every second; 0 once passed or when deadline is null.
// The OTP modal uses it for the code expiry countdown and the resend cooldown.
export function useSecondsLeft(deadline) {
  // Seconds left right now, rounded up so "00:01" is shown until the deadline really passes.
  const calc = () => (deadline ? Math.max(0, Math.ceil((deadline - Date.now()) / 1000)) : 0)
  // Value shown on screen; recomputed from the clock on each tick so a throttled background tab stays accurate.
  const [left, setLeft] = useState(calc)
  useEffect(() => {
    setLeft(calc())
    if (!deadline) return undefined
    // Tick every second; the cleanup stops the old interval when the deadline changes (e.g. after a resend).
    const id = setInterval(() => setLeft(calc()), 1000)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deadline])
  return left
}
