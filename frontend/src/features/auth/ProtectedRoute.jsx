import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from './AuthContext.jsx'
import LoadingState from '../../components/ui/LoadingState.jsx'

export default function ProtectedRoute({ children }) {
  const { isAuthenticated, status, sessionMessage } = useAuth()
  const location = useLocation()

  if (status === 'loading') return <LoadingState label="Checking your account…" />
  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location, sessionMessage }} />
  }

  return children
}
