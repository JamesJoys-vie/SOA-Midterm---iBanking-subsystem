import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Navigate, useNavigate } from 'react-router-dom'
import { login } from '../api/client.js'
import { useAuth } from '../context/AuthContext.jsx'
import { Alert, Button } from '../components/ui.jsx'

export default function LoginPage() {
  const { register, handleSubmit, formState: { errors, isSubmitting }, setError } = useForm()
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

  const input = 'w-full rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100'

  return (
    <main className="grid min-h-screen place-items-center bg-slate-50 px-4">
      <form onSubmit={handleSubmit(onSubmit)} noValidate className="w-full max-w-sm space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div>
          <h1 className="text-2xl font-bold text-blue-700">iBanking</h1>
          <p className="text-sm text-slate-500">Sign in to pay tuition</p>
        </div>

        {errors.root && <Alert>{errors.root.message}</Alert>}

        <label className="block space-y-1">
          <span className="text-sm font-medium text-slate-700">Username</span>
          <input className={input} autoComplete="username" autoFocus {...register('username', { required: true, validate: (v) => v.trim() !== '' })} />
          {errors.username && <span className="text-xs text-red-600">Required</span>}
        </label>

        <label className="block space-y-1">
          <span className="text-sm font-medium text-slate-700">Password</span>
          <div className="relative">
            <input className={`${input} pr-16`} type={showPassword ? 'text' : 'password'} autoComplete="current-password" {...register('password', { required: true })} />
            <button type="button" onClick={() => setShowPassword((s) => !s)} className="absolute inset-y-0 right-2 px-2 text-xs text-slate-500 hover:text-slate-800">
              {showPassword ? 'Hide' : 'Show'}
            </button>
          </div>
          {errors.password && <span className="text-xs text-red-600">Required</span>}
        </label>

        <Button type="submit" loading={isSubmitting} className="w-full">{isSubmitting ? 'Signing in…' : 'Sign in'}</Button>
        <p className="text-center text-xs text-slate-400">Demo accounts: alice · bob · carol</p>
      </form>
    </main>
  )
}
