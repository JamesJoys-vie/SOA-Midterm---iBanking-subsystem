// Shared shell for every signed-in page: header (logo, nav, eye toggle, user, sign out) + centered column.
import { Link, NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { useProfile } from '../hooks/queries.js'
import { EyeToggle, Skeleton } from './ui.jsx'

const NAV = [
  { to: '/home', label: 'Home' },
  { to: '/pay', label: 'Pay tuition' },
  { to: '/history', label: 'History' },
]

export default function AppLayout() {
  const { signOut } = useAuth()
  const { data: profile } = useProfile()

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="sticky top-0 z-30 border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-[920px] flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <Link to="/home" className="text-lg font-bold text-blue-700">iBanking</Link>
          <nav className="order-3 flex w-full gap-1 text-sm sm:order-none sm:w-auto">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                className={({ isActive }) => `rounded-lg px-3 py-1.5 ${isActive ? 'bg-blue-50 font-medium text-blue-700' : 'text-slate-600 hover:bg-slate-100'}`}
              >
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2 text-sm">
            <EyeToggle />
            <span className="hidden max-w-[12rem] truncate text-slate-700 sm:inline">
              {profile ? profile.full_name : <Skeleton className="h-4 w-24" />}
            </span>
            <button type="button" onClick={signOut} className="rounded-lg px-3 py-1.5 text-slate-600 hover:bg-slate-100">Sign out</button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[920px] px-4 py-6">
        <Outlet />
      </main>
    </div>
  )
}
