// Modal surfaces: Modal (centered, bottom sheet on phones), ConfirmDialog (replaces window.confirm), Drawer (side panel).
// All of them keep the keyboard inside, leave the page inert behind them and give focus back when they close.
import { useEffect, useId, useRef } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { Alert, Button } from './ui.jsx'

const FOCUSABLE = 'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), summary'

// `onEscape` may be undefined (Esc then does nothing).
function useModalBehaviour(panelRef, onEscape) {
  // Latest callback, so the effect below only runs on open and close.
  const escape = useRef(onEscape)
  escape.current = onEscape
  // What had focus before opening. Read during the first render, because children may take focus before effects run.
  const opener = useRef(document.activeElement)

  useEffect(() => {
    const root = document.getElementById('root')
    root.inert = true
    document.body.style.overflow = 'hidden'
    if (!panelRef.current.contains(document.activeElement)) {
      (panelRef.current.querySelector('[data-autofocus]') || panelRef.current.querySelector(FOCUSABLE))?.focus()
    }

    const onKeyDown = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        escape.current?.()
      } else if (e.key === 'Tab') {
        const items = [...panelRef.current.querySelectorAll(FOCUSABLE)]
        if (!items.length) return
        const first = items[0]
        const last = items[items.length - 1]
        const inside = panelRef.current.contains(document.activeElement)
        if (e.shiftKey && (document.activeElement === first || !inside)) { e.preventDefault(); last.focus() }
        else if (!e.shiftKey && (document.activeElement === last || !inside)) { e.preventDefault(); first.focus() }
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      root.inert = false
      document.body.style.overflow = ''
      if (opener.current?.isConnected) opener.current.focus()
    }
  }, [panelRef])
}

// The backdrop never closes a Modal: a stray click must not lose the user's place.
export function Modal({ role = 'dialog', labelledBy, describedBy, onEscape, children }) {
  const panel = useRef(null)
  useModalBehaviour(panel, onEscape)
  return createPortal(
    <div className="fixed inset-0 z-50 flex animate-fade items-end justify-center overflow-auto bg-ink/50 sm:items-center sm:p-4">
      <div
        ref={panel}
        role={role}
        aria-modal="true"
        aria-labelledby={labelledBy}
        aria-describedby={describedBy}
        className="w-full max-w-md animate-rise rounded-t-[20px] bg-card px-4 pb-6 pt-5 shadow-xl sm:rounded-[20px] sm:p-6"
      >
        {children}
      </div>
    </div>,
    document.body,
  )
}

// The body of a "are you sure?" question; OtpModal shows it in place of the code form, ConfirmDialog in its own Modal.
export function ConfirmBody({ titleId, bodyId, title, body, recap, error, keepLabel, confirmLabel, busy, onKeep, onConfirm }) {
  return (
    <div className="grid gap-3.5">
      <h2 id={titleId} className="text-xl font-bold">{title}</h2>
      <p id={bodyId} className="text-sm text-ink-2">{body}</p>
      {recap}
      {error && <Alert>{error}</Alert>}
      <div className="grid grid-cols-2 gap-2.5">
        <Button variant="secondary" onClick={onKeep} disabled={busy} autoFocus data-autofocus>{keepLabel}</Button>
        <Button onClick={onConfirm} loading={busy}>{confirmLabel}</Button>
      </div>
    </div>
  )
}

export function ConfirmDialog({ onKeep, busy, ...props }) {
  const titleId = useId()
  const bodyId = useId()
  return (
    <Modal role="alertdialog" labelledBy={titleId} describedBy={bodyId} onEscape={busy ? undefined : onKeep}>
      <ConfirmBody titleId={titleId} bodyId={bodyId} onKeep={onKeep} busy={busy} {...props} />
    </Modal>
  )
}

// Side panel on desktop, bottom sheet on phones. Unlike a Modal it holds nothing to lose, so the backdrop closes it.
export function Drawer({ title, onClose, children }) {
  const panel = useRef(null)
  const titleId = useId()
  useModalBehaviour(panel, onClose)
  return createPortal(
    <div className="fixed inset-0 z-50 animate-fade bg-ink/50" onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="absolute inset-x-0 bottom-0 flex max-h-[85%] animate-rise flex-col gap-3.5 overflow-auto rounded-t-[20px] bg-card px-4 pb-6 pt-5 shadow-xl md:inset-y-0 md:left-auto md:right-0 md:max-h-none md:w-[400px] md:rounded-none md:p-6"
      >
        <div className="flex items-center justify-between gap-2.5">
          <h2 id={titleId} className="text-lg font-bold">{title}</h2>
          <button type="button" onClick={onClose} aria-label="Close details" className="flex h-11 w-11 items-center justify-center rounded-[10px] text-ink-2 hover:bg-subtle">
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  )
}
