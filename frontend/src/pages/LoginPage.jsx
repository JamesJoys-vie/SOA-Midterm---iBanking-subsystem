import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Navigate, useNavigate } from 'react-router-dom'
import { ShieldCheck } from 'lucide-react'
import { login } from '../api/client.js'
import { useAuth } from '../context/AuthContext.jsx'
import { LogoMark } from '../components/AppLayout.jsx'
import { Alert, Button, TextField } from '../components/ui.jsx'

const HOW_IT_WORKS = [
  ['Find the student', 'Type the MSSV and we look it up'],
  ['Check the amount', 'See your balance before and after'],
  ['Confirm by email code', 'A 6-digit code keeps the payment yours'],
]
const DEMO_ACCOUNTS = ['alice', 'bob', 'carol']

export default function LoginPage() {
  const { register, handleSubmit, setValue, setFocus, formState: { errors, isSubmitting }, setError } = useForm()
  const { token, signIn } = useAuth()
  const navigate = useNavigate()
  const [showPassword, setShowPassword] = useState(false)

  if (token) return <Navigate to="/home" replace />

  const onSubmit = async ({ username, password }) => {
    try {
      const { access_token } = await login(username.trim(), password)
      signIn(access_token)
      navigate('/home', { replace: true })
    } catch (e) {
      const message = e.status === 401 ? 'Invalid username or password.'
        : e.status === 429 ? `Too many sign-in attempts. Try again in ${e.retryAfter || 60} seconds.`
        : e.message
      setError('root', { message })
    }
  }

  // Demo chip: fills the username and moves on to the password.
  const pickDemo = (name) => {
    setValue('username', name, { shouldValidate: true })
    setFocus('password')
  }

  return (
    <main className="grid min-h-screen md:grid-cols-[44%_1fr]">
      <aside className="hidden flex-col justify-between gap-8 bg-hero p-12 text-white md:flex">
        <div className="flex items-center gap-2.5 text-[17px] font-bold"><LogoMark className="bg-white text-ink" />iBanking</div>
        <div>
          <p className="mb-6 text-4xl font-bold leading-tight">Pay tuition in three short steps</p>
          <ol className="grid gap-[18px]">
            {HOW_IT_WORKS.map(([title, text], i) => (
              <li key={title} className="flex gap-3.5">
                <span className="flex h-8 w-8 flex-none items-center justify-center rounded-full border border-current text-[13px] font-semibold">{i + 1}</span>
                <span>
                  <b className="block text-[15px] font-semibold">{title}</b>
                  <span className="text-[13px] text-white/80">{text}</span>
                </span>
              </li>
            ))}
          </ol>
        </div>
        <p className="flex items-center gap-2 text-xs text-white/80"><ShieldCheck className="h-4 w-4" aria-hidden="true" />Your password and codes never appear in the address bar.</p>
      </aside>

      <div className="grid place-items-center px-4 py-8">
        {/* method="post": a native submit (if the handler ever failed) would never put the password in the URL. */}
        <form method="post" onSubmit={handleSubmit(onSubmit)} noValidate className="grid w-full max-w-[360px] gap-4">
          <div className="flex items-center gap-2.5 text-[17px] font-bold md:hidden"><LogoMark />iBanking</div>
          <div>
            <h1 className="text-[26px] font-bold">Sign in</h1>
            <p className="text-sm text-ink-2">Use your iBanking account</p>
          </div>

          {errors.root && <Alert>{errors.root.message}</Alert>}

          <TextField
            label="Username"
            autoComplete="username"
            autoFocus
            error={errors.username && 'Required'}
            {...register('username', { required: true, validate: (v) => v.trim() !== '' })}
          />
          <TextField
            label="Password"
            type={showPassword ? 'text' : 'password'}
            autoComplete="current-password"
            error={errors.password && 'Required'}
            sidePadding="pr-16"
            side={(
              <button type="button" onClick={() => setShowPassword((s) => !s)} className="flex h-11 min-w-11 items-center justify-center px-1.5 text-xs font-medium text-ink-2 hover:text-ink">
                {showPassword ? 'Hide' : 'Show'}
              </button>
            )}
            {...register('password', { required: true })}
          />

          <Button type="submit" loading={isSubmitting} className="w-full">{isSubmitting ? 'Signing in…' : 'Sign in'}</Button>

          <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
            <span>Demo accounts:</span>
            {DEMO_ACCOUNTS.map((name) => (
              <button key={name} type="button" onClick={() => pickDemo(name)} className="min-h-7 rounded-full border border-line bg-card px-2.5 font-medium text-ink-2 hover:border-line-strong">{name}</button>
            ))}
          </div>
        </form>
      </div>
    </main>
  )
}
