import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
import './index.css'
import router from './router/index.jsx'
import { AuthProvider } from './contexts/AuthContext.jsx'
import { SidebarSubsectionProvider } from './contexts/SidebarSubsection.jsx'
import { ContextMenuProvider } from './contexts/ContextMenu.jsx'
import { registerSW } from './lib/registerSW.js'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <AuthProvider>
      <SidebarSubsectionProvider>
        <ContextMenuProvider>
          <RouterProvider router={router} />
        </ContextMenuProvider>
      </SidebarSubsectionProvider>
    </AuthProvider>
  </StrictMode>,
)

if (import.meta.env.PROD) {
  registerSW()
} else if ('serviceWorker' in navigator) {
  // Dev mode: a cache-first service worker fights Vite's HMR module graph —
  // it can serve a stale cached .js/.css file alongside freshly-fetched ones,
  // producing a version-mismatched module graph that crashes the app to a
  // blank white screen with no visible error. Unregister + clear on every
  // dev load so a stale SW from an earlier session can't linger.
  navigator.serviceWorker.getRegistrations().then((regs) => {
    regs.forEach((reg) => reg.unregister())
  })
  caches?.keys?.().then((keys) => keys.forEach((key) => caches.delete(key)))
}
