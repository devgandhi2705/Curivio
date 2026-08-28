import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext.jsx'
import LandingPage from '../components/landing/LandingPage.jsx'
import UnpackListener from '../components/unpack/UnpackListener.jsx'

export default function LandingRoute() {
  const { isAuthenticated } = useAuth()
  const navigate = useNavigate()

  return (
    <>
      <LandingPage
        isAuthenticated={isAuthenticated}
        onEnterApp={() => navigate('/feed')}
        onShowAuth={() => navigate('/login')}
      />
      <UnpackListener />
    </>
  )
}
