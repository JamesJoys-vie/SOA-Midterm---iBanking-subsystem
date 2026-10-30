import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App.jsx'
import { AuthProvider } from './context/AuthContext.jsx'
import { AmountVisibilityProvider } from './context/AmountVisibility.jsx'
import './index.css'

// Client errors (404 lookup, 401, 409...) are answers, not glitches: don't retry them.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: (count, err) => (err?.status === 0 || err?.status >= 500) && count < 2, refetchOnWindowFocus: false },
  },
})

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <AmountVisibilityProvider>
            <App />
          </AmountVisibilityProvider>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
)
