// Small presentational building blocks (see the component inventory in docs/wireframes/wireframes.html).
import { useAmountVisibility } from '../context/AmountVisibility.jsx'
import { formatVnd } from '../utils/format.js'

export function Card({ title, hint, children, className = '' }) {
  return (
    <section className={`bg-white rounded-xl border border-slate-200 shadow-sm p-5 ${className}`}>
      {(title || hint) && (
        <div className="flex items-center justify-between gap-3 mb-4">
          {title && <h2 className="font-semibold text-slate-800">{title}</h2>}
          {hint && <span className="text-xs text-slate-500">{hint}</span>}
        </div>
      )}
      {children}
    </section>
  )
}

const BUTTON_STYLES = {
  primary: 'bg-blue-600 text-white hover:bg-blue-700 disabled:bg-blue-300',
  secondary: 'bg-white text-slate-700 border border-slate-300 hover:bg-slate-50 disabled:text-slate-400',
  ghost: 'text-slate-600 hover:bg-slate-100 disabled:text-slate-300',
  danger: 'bg-white text-red-600 border border-red-200 hover:bg-red-50 disabled:text-red-300',
}

export function Button({ variant = 'primary', loading = false, disabled, children, className = '', ...props }) {
  return (
    <button
      type="button"
      disabled={disabled || loading}
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed ${BUTTON_STYLES[variant]} ${className}`}
      {...props}
    >
      {loading && <Spinner />}
      {children}
    </button>
  )
}

export const Spinner = ({ className = 'h-4 w-4' }) => (
  <span className={`inline-block animate-spin rounded-full border-2 border-current border-r-transparent ${className}`} aria-hidden="true" />
)

const ALERT_STYLES = {
  error: 'bg-red-50 text-red-700 border-red-200',
  info: 'bg-blue-50 text-blue-800 border-blue-200',
  warning: 'bg-amber-50 text-amber-800 border-amber-200',
}

export function Alert({ kind = 'error', children, action }) {
  return (
    <div role={kind === 'error' ? 'alert' : 'status'} className={`flex items-center justify-between gap-3 rounded-lg border px-3 py-2 text-sm ${ALERT_STYLES[kind]}`}>
      <span>{children}</span>
      {action}
    </div>
  )
}

// solid = SUCCESS / PAID, outline = in progress, dashed = ended without paying.
const BADGE_STYLES = {
  SUCCESS: 'bg-emerald-600 text-white border-emerald-600',
  PAID: 'bg-emerald-600 text-white border-emerald-600',
  UNPAID: 'bg-white text-slate-700 border-slate-400',
  RESERVED: 'bg-white text-amber-700 border-amber-500',
  PENDING_OTP: 'bg-white text-amber-700 border-amber-500',
  PROCESSING: 'bg-white text-blue-700 border-blue-500',
  FAILED: 'bg-white text-red-700 border-red-400 border-dashed',
  EXPIRED: 'bg-white text-slate-500 border-slate-400 border-dashed',
  CANCELLED: 'bg-white text-slate-500 border-slate-400 border-dashed',
}

export const StatusBadge = ({ status }) => (
  <span className={`inline-block whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium ${BADGE_STYLES[status] || BADGE_STYLES.UNPAID}`}>
    {status}
  </span>
)

// Every ₫ value goes through this so the global hide / show switch covers all of them.
export function Money({ value, className = '' }) {
  const { visible } = useAmountVisibility()
  if (!visible) {
    return <span className={`tabular-nums whitespace-nowrap ${className}`} aria-label="Amount hidden">•••••••• ₫</span>
  }
  return <span className={`tabular-nums whitespace-nowrap ${className}`}>{formatVnd(value)}</span>
}

export function EyeToggle({ className = '' }) {
  const { visible, toggle } = useAmountVisibility()
  return (
    <button
      type="button"
      onClick={toggle}
      aria-pressed={visible}
      aria-label={visible ? 'Hide amounts' : 'Show amounts'}
      title={visible ? 'Hide amounts' : 'Show amounts'}
      className={`inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-800 ${className}`}
    >
      <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" />
        <circle cx="12" cy="12" r="3" />
        {!visible && <path d="M3 3l18 18" />}
      </svg>
    </button>
  )
}

export function ReadOnlyField({ label, children }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5 text-sm">
      <span className="text-slate-500">{label}</span>
      <span className="text-right font-medium text-slate-800">{children ?? '—'}</span>
    </div>
  )
}

export const Skeleton = ({ className = 'h-4 w-full' }) => <div className={`animate-pulse rounded bg-slate-200 ${className}`} />

export function StatCard({ label, value, caption, action }) {
  return (
    <Card>
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm text-slate-500">{label}</p>
        {action}
      </div>
      <div className="mt-1 text-2xl font-semibold text-slate-900">{value}</div>
      {caption && <div className="mt-1 text-xs text-slate-500">{caption}</div>}
    </Card>
  )
}

const STEPS = ['Details', 'Verify OTP', 'Result']

export function Stepper({ current }) {
  return (
    <ol className="flex items-center gap-2 text-sm">
      {STEPS.map((label, i) => {
        const n = i + 1
        const state = n < current ? 'done' : n === current ? 'active' : 'todo'
        return (
          <li key={label} className="flex items-center gap-2">
            {i > 0 && <span className="h-px w-6 bg-slate-300 sm:w-10" />}
            <span className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold ${
              state === 'todo' ? 'bg-slate-200 text-slate-500' : 'bg-blue-600 text-white'}`}>
              {state === 'done' ? '✓' : n}
            </span>
            <span className={state === 'active' ? 'font-medium text-slate-900' : 'text-slate-500'}>{label}</span>
          </li>
        )
      })}
    </ol>
  )
}
