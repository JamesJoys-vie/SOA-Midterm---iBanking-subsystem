// Shared shell for every signed-in page: header (logo, nav, eye toggle, account menu), centered column, tab bar on phones.
import { useEffect, useRef, useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { ChevronDown, CreditCard, History, House } from 'lucide-react'
import { useAuth } from '../context/AuthContext.jsx'
import { useProfile } from '../hooks/queries.js'
import { EyeToggle, Skeleton } from './ui.jsx'

const NAV = [
  { to: '/home', label: 'Home', short: 'Home', Icon: House },
  { to: '/pay', label: 'Pay tuition', short: 'Pay', Icon: CreditCard },
  { to: '/history', label: 'History', short: 'History', Icon: History },
]

// "Nguyen Van A" -> "NA" (first and last word).
const initials = (name) => {
  const words = (name || '').trim().split(/\s+/).filter(Boolean)
  if (!words.length) return ''
  return `${words[0][0]}${words.length > 1 ? words[words.length - 1][0] : ''}`.toUpperCase()
}

export const LogoMark = ({ className = 'bg-action text-white' }) => (
  <span aria-hidden="true" className={`flex h-7 w-7 items-center justify-center rounded-lg text-base font-bold ${className}`}>i</span>
)

// Avatar button with the signed-in user's details and Sign out. Esc or a click outside closes it.
function AccountMenu({ profile, onSignOut }) {
  const [open, setOpen] = useState(false)
  const root = useRef(null)
  const button = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const onClick = (e) => { if (!root.current.contains(e.target)) setOpen(false) }
    const onKey = (e) => { if (e.key === 'Escape') { setOpen(false); button.current.focus() } }
    document.addEventListener('mousedown', onClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div ref={root} className="relative">
      <button
        ref={button}
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="true"
        aria-label="Account menu"
        className="flex min-h-11 items-center gap-2 rounded-[10px] px-2 text-sm font-medium hover:bg-subtle"
      >
        <span aria-hidden="true" className="flex h-[30px] w-[30px] items-center justify-center rounded-full bg-subtle text-[11px] font-semibold text-ink-2">{initials(profile?.full_name)}</span>
        <span className="hidden max-w-[12rem] truncate md:inline">{profile ? profile.full_name : <Skeleton className="h-4 w-24" />}</span>
        <ChevronDown className="hidden h-4 w-4 md:block" aria-hidden="true" />
      </button>
      {open && (
        <div className="absolute right-0 top-[calc(100%+6px)] z-40 w-60 rounded-xl border border-line bg-card p-2 shadow-lg">
          <p className="mb-1.5 break-words border-b border-line px-2.5 pb-2.5 pt-1.5 text-xs text-muted">
            <b className="block text-sm font-semibold text-ink">{profile?.full_name}</b>
            {profile?.email}
          </p>
          <button type="button" onClick={onSignOut} className="min-h-11 w-full rounded-lg px-2.5 text-left text-sm font-medium hover:bg-subtle">Sign out</button>
        </div>
      )}
    </div>
  )
}

export default function AppLayout() {
  const { signOut } = useAuth()
  const { data: profile } = useProfile()
  const { pathname } = useLocation()

  // Each page starts at the top. Focus moves to its heading so keyboard and screen-reader users land on the new page.
  useEffect(() => {
    window.scrollTo(0, 0)
    document.querySelector('main h1')?.focus({ preventScroll: true })
  }, [pathname])

  return (
    <div className="flex min-h-screen flex-col">
      <header className="no-print sticky top-0 z-30 border-b border-line bg-card">
        <div className="mx-auto flex h-14 max-w-[1104px] items-center gap-7 pl-4 pr-2 md:h-16 md:px-8">
          <Link to="/home" className="flex min-h-11 items-center gap-2.5 text-[17px] font-bold"><LogoMark />iBanking</Link>
          <nav aria-label="Main" className="hidden gap-1 md:flex">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                className={({ isActive }) => `flex min-h-[38px] items-center rounded-lg px-3.5 text-sm ${isActive ? 'bg-subtle font-semibold text-ink' : 'font-medium text-ink-2 hover:bg-subtle'}`}
              >
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-1.5">
            <EyeToggle />
            <AccountMenu profile={profile} onSignOut={signOut} />
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1104px] flex-1 px-4 pb-24 pt-4 md:px-8 md:pb-12 md:pt-8">
        <Outlet />
      </main>

      <nav aria-label="Main, mobile" className="no-print fixed inset-x-0 bottom-0 z-30 flex gap-2 border-t border-line bg-card px-4 pb-3 pt-2 md:hidden">
        {NAV.map(({ to, short, Icon }) => (
          <NavLink key={to} to={to} className={({ isActive }) => `group flex min-h-[52px] flex-1 flex-col items-center gap-1 text-xs ${isActive ? 'font-semibold text-ink' : 'font-medium text-muted'}`}>
            {({ isActive }) => (
              <>
                <span className={`flex h-7 w-14 items-center justify-center rounded-full ${isActive ? 'bg-subtle' : ''}`}><Icon className="h-5 w-5" aria-hidden="true" /></span>
                {short}
              </>
            )}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
