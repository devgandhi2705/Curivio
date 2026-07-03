import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext.jsx'
import AuthLoadingScreen from '../components/AuthLoadingScreen.jsx'

export default function AuthGuard() {
  const { isAuthenticated, authChecked } = useAuth()
  const location = useLocation()

  if (!authChecked) return <AuthLoadingScreen />

  if (!isAuthenticated) {
    const next = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/login?next=${next}`} replace />
  }

  return <Outlet />
}
