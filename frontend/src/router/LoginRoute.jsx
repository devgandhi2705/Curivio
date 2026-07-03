import { Navigate, Link, useSearchParams } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext.jsx'
import AuthPage from '../components/auth/AuthPage.jsx'

export default function LoginRoute() {
  const { isAuthenticated } = useAuth()
  const [searchParams] = useSearchParams()

  if (isAuthenticated) {
    const next = searchParams.get('next')
    return <Navigate to={next && next.startsWith('/') ? next : '/feed'} replace />
  }

  return (
    <div className="relative min-h-screen min-h-dvh bg-slate-950">
      <Link
        to="/"
        className="absolute top-4 left-4 z-50 flex items-center gap-1.5 px-3 py-1.5 text-[13px] text-slate-400 hover:text-slate-200 bg-slate-900/80 border border-slate-800 rounded-xl backdrop-blur-sm transition-all"
      >
        <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
          <path fillRule="evenodd" d="M9.78 4.22a.75.75 0 0 1 0 1.06L7.06 8l2.72 2.72a.75.75 0 1 1-1.06 1.06L5.47 8.53a.75.75 0 0 1 0-1.06l3.25-3.25a.75.75 0 0 1 1.06 0Z" clipRule="evenodd" />
        </svg>
        Back
      </Link>
      <AuthPage />
    </div>
  )
}
