import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext.jsx'
import LandingPage from '../components/landing/LandingPage.jsx'
import AuthLoadingScreen from '../components/AuthLoadingScreen.jsx'

// Renders the marketing landing page.
//   redirectAuthed=true  ("/")      — returning logged-in visitors skip straight
//                                     to their feed instead of the marketing page.
//   redirectAuthed=false ("/about") — always shows the landing page, so a signed-in
//                                     user can still read it (CTA becomes "Open app").
export default function LandingRoute({ redirectAuthed = true }) {
  const { isAuthenticated, authChecked } = useAuth()
  const navigate = useNavigate()

  if (redirectAuthed) {
    // isAuthenticated is true synchronously on mount when a session is stored
    // (AuthContext seeds user from localStorage), so there's no landing-page flash.
    if (isAuthenticated) return <Navigate to="/feed" replace />

    // Degenerate case: a token exists but the stored user blob is missing/corrupt.
    // Wait for getMe() to settle rather than flashing the landing page at someone
    // who is in fact logged in. With no token, authChecked is already true.
    if (!authChecked) return <AuthLoadingScreen />
  }

  return (
    <LandingPage
      isAuthenticated={isAuthenticated}
      onEnterApp={() => navigate('/feed')}
      onShowAuth={() => navigate('/login')}
    />
  )
}
