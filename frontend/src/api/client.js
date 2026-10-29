// Thin fetch wrapper. Same-origin: nginx (or the Vite dev proxy) forwards /api/* to the gateway.
const TOKEN_KEY = 'token'

export const getToken = () => sessionStorage.getItem(TOKEN_KEY)
export const setToken = (t) => (t ? sessionStorage.setItem(TOKEN_KEY, t) : sessionStorage.removeItem(TOKEN_KEY))

// AuthProvider registers this so an expired/invalid token (401 on any call but login) signs the user out.
let onUnauthorized = () => {}
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn }

// FastAPI sends `detail` as a string, or as a list of validation errors for 422 schema failures.
const errorMessage = (data, res) => {
  const d = data?.detail
  if (Array.isArray(d)) return d[0]?.msg || 'Invalid request'
  return d || res.statusText || 'Request failed'
}

export async function api(path, { method = 'GET', body, headers = {} } = {}) {
  const token = getToken()
  let res
  try {
    res = await fetch(`/api${path}`, {
      method,
      headers: {
        ...(body ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
      body: body ? JSON.stringify(body) : undefined,
    })
  } catch {
    const err = new Error('Cannot reach the server. Check your connection and try again.')
    err.status = 0
    throw err
  }
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    if (res.status === 401 && path !== '/auth/login') onUnauthorized()
    const err = new Error(errorMessage(data, res))
    err.status = res.status
    err.retryAfter = Number(res.headers.get('Retry-After')) || null
    throw err
  }
  return data
}

// Endpoint helpers (see docs/api/endpoints.md)
export const login = (username, password) => api('/auth/login', { method: 'POST', body: { username, password } })
export const getProfile = () => api('/users/me')
export const getAccount = () => api('/accounts/me')
export const getTuition = (mssv) => api(`/tuitions/${encodeURIComponent(mssv)}`)
export const initiateTransaction = (studentId, idempotencyKey) =>
  api('/transactions', { method: 'POST', body: { student_id: studentId }, headers: { 'Idempotency-Key': idempotencyKey } })
export const verifyOtp = (txnId, otp) => api(`/transactions/${txnId}/verify-otp`, { method: 'POST', body: { otp } })
export const resendOtp = (txnId) => api(`/transactions/${txnId}/resend-otp`, { method: 'POST' })
export const cancelTransaction = (txnId) => api(`/transactions/${txnId}/cancel`, { method: 'POST' })
export const getTransaction = (txnId) => api(`/transactions/${txnId}`)
export const getHistory = () => api('/transactions')
