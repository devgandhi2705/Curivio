import { createBrowserRouter } from 'react-router-dom'
import AuthGuard from './AuthGuard.jsx'
import LandingRoute from './LandingRoute.jsx'
import LoginRoute from './LoginRoute.jsx'
import AppLayout from '../App.jsx'
import SharePage from '../pages/SharePage.jsx'

const router = createBrowserRouter([
  { path: '/', element: <LandingRoute /> },
  // Landing page that never redirects — the only way a signed-in user can read it,
  // reachable from Settings → "About Curivio".
  { path: '/about', element: <LandingRoute redirectAuthed={false} /> },
  { path: '/login', element: <LoginRoute /> },
  { path: '/share/:token', element: <SharePage /> },
  {
    element: <AuthGuard />,
    children: [
      // Single catch-all: every protected URL (/feed, /feed/:projectId/:day/:articleKey,
      // /chat/:chatId, /dashboard, /bookmarks, /read-later, ...) resolves to the
      // same AppLayout element, which keeps Feed/Chat/Dashboard/Bookmarks/Read
      // Later all mounted at once (so in-flight generation and chat streams
      // survive switching tabs, matching the pre-router behavior) and derives
      // the active section + any :projectId/:day/:articleKey or :chatId target
      // from the URL itself. Using one route (instead of one per path) guarantees
      // React never unmounts AppLayout when navigating between sections.
      { path: '*', element: <AppLayout /> },
    ],
  },
])

export default router
