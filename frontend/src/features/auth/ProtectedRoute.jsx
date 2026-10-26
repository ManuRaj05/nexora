import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from './AuthContext.jsx'
import LoadingState from '../../components/ui/LoadingState.jsx'

export default function ProtectedRoute({ children, requiredRole }) {
  const { isAuthenticated, status, sessionMessage, user } = useAuth()
  const location = useLocation()

  if (status === 'loading') return <LoadingState label="Checking your account…" />
  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location, sessionMessage }} />
  }
  if (requiredRole && user?.role !== requiredRole) return <Navigate to="/" replace />

  return children
}
