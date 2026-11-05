// Small presentational building blocks (see docs/wireframes/modernization-proposal.html).
import { forwardRef, useId, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertCircle, Check, CircleCheck, Clock3, Copy, Eye, EyeOff, Info, X } from 'lucide-react'
import { useAmountVisibility } from '../context/AmountVisibility.jsx'
import { formatVnd, shortId } from '../utils/format.js'
import { STATUS_UI } from '../utils/status.js'

export function Card({ title, hint, children, className = '' }) {
  return (
    <section className={`rounded-2xl border border-line bg-card p-5 ${className}`}>
      {(title || hint) && (
        <div className="mb-4 flex items-center justify-between gap-3">
          {title && <h2 className="text-lg font-semibold">{title}</h2>}
          {hint && <span className="text-xs text-muted">{hint}</span>}
        </div>
      )}
      {children}
    </section>
  )
}

const BUTTON_BASE = 'inline-flex min-h-11 items-center justify-center gap-2 whitespace-nowrap rounded-[10px] px-[18px] text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:border-transparent disabled:bg-subtle disabled:text-muted'
const BUTTON_STYLES = {
  primary: 'bg-action text-white hover:bg-action-hover',
  secondary: 'border border-line-strong bg-card text-ink hover:border-ink-2',
  ghost: 'text-ink-2 hover:bg-subtle disabled:bg-transparent',
  onHero: 'bg-white text-ink hover:bg-subtle focus-visible:outline-white',
}
export const buttonClass = (variant = 'primary', className = '') => `${BUTTON_BASE} ${BUTTON_STYLES[variant]} ${className}`

export function Button({ variant = 'primary', loading = false, disabled, children, className = '', ...props }) {
  return (
    <button type="button" disabled={disabled || loading} className={buttonClass(variant, className)} {...props}>
      {loading && <Spinner />}
      {children}
    </button>
  )
}

export const ButtonLink = ({ variant = 'primary', className = '', ...props }) => <Link className={buttonClass(variant, className)} {...props} />

export const Spinner = ({ className = 'h-4 w-4' }) => (
  <span className={`inline-block animate-spin rounded-full border-2 border-current border-r-transparent ${className}`} aria-hidden="true" />
)

const ALERT_STYLES = {
  error: { box: 'border-bad text-bad', Icon: AlertCircle },
  info: { box: 'border-line-strong text-ink-2', Icon: Info },
  success: { box: 'border-line-strong text-ink-2', Icon: CircleCheck },
  warning: { box: 'border-warn text-warn', Icon: AlertCircle },
}

export function Alert({ kind = 'error', children, action }) {
  const { box, Icon } = ALERT_STYLES[kind]
  return (
    <div role={kind === 'error' ? 'alert' : 'status'} className={`flex items-start justify-between gap-3 rounded-[10px] border px-3 py-2.5 text-sm ${box}`}>
      <span className="flex items-start gap-2"><Icon className="mt-0.5 h-4 w-4 flex-none" aria-hidden="true" /><span>{children}</span></span>
      {action}
    </div>
  )
}

// One line above a disabled Confirm that says why it is disabled.
export const Reason = ({ danger, children }) => (
  <p className={`flex items-start gap-2 text-sm ${danger ? 'text-bad' : 'text-ink-2'}`}>
    <AlertCircle className="mt-0.5 h-4 w-4 flex-none" aria-hidden="true" /><span>{children}</span>
  </p>
)

// Each kind differs by icon and outline too, so a status never depends on color alone.
const BADGE_STYLES = {
  ok: { box: 'bg-ok text-white border-ok', Icon: Check },
  progress: { box: 'bg-card text-warn border-warn', Icon: Clock3 },
  ended: { box: 'bg-card text-ink-2 border-line-strong border-dashed', Icon: X },
  neutral: { box: 'bg-card text-ink-2 border-line', Icon: null },
}

export function StatusBadge({ status }) {
  const ui = STATUS_UI[status] || { label: status, kind: 'neutral' }
  const { box, Icon } = BADGE_STYLES[ui.kind]
  return (
    <span className={`inline-flex min-h-6 items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 text-xs font-medium ${box}`}>
      {Icon && <Icon className="h-3.5 w-3.5" strokeWidth={2.5} aria-hidden="true" />}
      {ui.label}
    </span>
  )
}

// Every ₫ value goes through this so the global hide / show switch covers all of them.
// `alwaysVisible`: tuition amounts inside the payment flow, because people must see what they are paying.
export function Money({ value, className = '', alwaysVisible = false }) {
  const { visible } = useAmountVisibility()
  if (!visible && !alwaysVisible) {
    return <span className={`tabular-nums whitespace-nowrap ${className}`} aria-label="Amount hidden">•••••••• ₫</span>
  }
  return <span className={`tabular-nums whitespace-nowrap ${className}`}>{formatVnd(value)}</span>
}

export function EyeToggle({ className = 'h-11 w-11 text-ink-2 hover:bg-subtle hover:text-ink', size = 'h-5 w-5' }) {
  const { visible, toggle } = useAmountVisibility()
  const Icon = visible ? Eye : EyeOff
  return (
    <button
      type="button"
      onClick={toggle}
      aria-pressed={visible}
      aria-label={visible ? 'Hide amounts' : 'Show amounts'}
      title={visible ? 'Hide amounts' : 'Show amounts'}
      className={`inline-flex flex-none items-center justify-center rounded-[10px] ${className}`}
    >
      <Icon className={size} aria-hidden="true" />
    </button>
  )
}

// Label + input + error or help text, wired together for screen readers. `side` sits inside the input, on the right.
export const TextField = forwardRef(function TextField({ label, error, help, side, sidePadding = 'pr-10', className = '', ...props }, ref) {
  const id = useId()
  const noteId = `${id}-note`
  return (
    <div className="grid gap-1.5">
      <label htmlFor={id} className="text-[13px] font-medium text-ink-2">{label}</label>
      <div className="relative">
        <input
          id={id}
          ref={ref}
          aria-invalid={error ? true : undefined}
          aria-describedby={error || help ? noteId : undefined}
          className={`h-[46px] w-full rounded-[10px] border bg-card px-3.5 text-[15px] outline-none focus:border-action focus:ring-1 focus:ring-action disabled:bg-subtle disabled:text-muted ${error ? 'border-bad ring-1 ring-bad' : 'border-line-strong'} ${side ? sidePadding : ''} ${className}`}
          {...props}
        />
        {side && <div className="absolute inset-y-0 right-1.5 flex items-center">{side}</div>}
      </div>
      {error
        ? <span id={noteId} className="text-xs font-medium text-bad">{error}</span>
        : help && <span id={noteId} className="text-xs text-muted">{help}</span>}
    </div>
  )
})

// Label on the left, value on the right.
export function KeyValue({ label, children, strong = false }) {
  return (
    <div className="flex items-center justify-between gap-4 text-sm">
      <dt className={strong ? 'font-bold text-ink' : 'text-ink-2'}>{label}</dt>
      <dd className={`text-right ${strong ? 'text-base font-bold' : 'font-medium'}`}>{children ?? '—'}</dd>
    </div>
  )
}

export function CopyId({ id }) {
  const [copied, setCopied] = useState(false)
  // navigator.clipboard needs a secure context, so plain-http LAN access simply copies nothing.
  const copy = () => {
    navigator.clipboard?.writeText(id).catch(() => {})
    setCopied(true)
  }
  const Icon = copied ? Check : Copy
  return (
    <button type="button" onClick={copy} title={id} aria-label="Copy transaction ID" className="inline-flex min-h-8 items-center gap-1.5 text-ink-2">
      <span className="font-mono text-xs">{shortId(id)}</span>
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
    </button>
  )
}

export const Skeleton = ({ className = 'h-4 w-full' }) => <div className={`animate-pulse rounded-md bg-subtle ${className}`} />

// A thin bar showing how much of a code's lifetime is left. `share`: 0 to 1.
export const ExpiryBar = ({ share, tone = 'bg-warn' }) => (
  <div className="h-1 overflow-hidden rounded-sm bg-subtle">
    <div className={`h-full rounded-sm transition-[width] duration-1000 ease-linear ${tone}`} style={{ width: `${Math.min(1, Math.max(0, share)) * 100}%` }} />
  </div>
)

const STEPS = ['Details', 'Verify code', 'Result']

export function Stepper({ current }) {
  return (
    <>
      <ol className="hidden items-center gap-2 text-[13px] text-muted sm:flex" aria-label="Progress">
        {STEPS.map((label, i) => {
          const n = i + 1
          const state = n < current ? 'done' : n === current ? 'active' : 'todo'
          return (
            <li key={label} className="flex items-center gap-2" aria-current={state === 'active' ? 'step' : undefined}>
              {i > 0 && <span className="h-px w-6 bg-line-strong" aria-hidden="true" />}
              <span className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold ${state === 'todo' ? 'bg-subtle' : 'bg-action text-white'}`}>
                {state === 'done' ? <Check className="h-3.5 w-3.5" strokeWidth={3} aria-hidden="true" /> : n}
              </span>
              <span className={state === 'active' ? 'font-semibold text-ink' : ''}>{label}</span>
            </li>
          )
        })}
      </ol>
      <p className="text-[13px] text-ink-2 sm:hidden">Step {current} of {STEPS.length} · {STEPS[current - 1]}</p>
    </>
  )
}
