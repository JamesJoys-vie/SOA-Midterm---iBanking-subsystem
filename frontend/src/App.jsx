import { Routes, Route, Navigate } from 'react-router-dom'
import LoginPage from './pages/LoginPage.jsx'
import HomePage from './pages/HomePage.jsx'
import TuitionPaymentPage from './pages/TuitionPaymentPage.jsx'
import HistoryPage from './pages/HistoryPage.jsx'
import ProtectedRoute from './components/ProtectedRoute.jsx'
import AppLayout from './components/AppLayout.jsx'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ProtectedRoute><AppLayout /></ProtectedRoute>}>
        <Route path="/home" element={<HomePage />} />
        <Route path="/pay" element={<TuitionPaymentPage />} />
        <Route path="/history" element={<HistoryPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/home" replace />} />
    </Routes>
  )
}
