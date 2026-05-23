import { createContext, useContext, useState, useCallback } from 'react'

const SidebarSubsectionContext = createContext(null)

export function SidebarSubsectionProvider({ children }) {
  // subsection = { type: 'feed'|'bookmarks', render: () => ReactNode } | null
  // Stores a render *function* so the sidebar always calls into the latest closure
  const [subsection, setSubsection] = useState(null)

  const register = useCallback((type, renderFn) => {
    setSubsection({ type, render: renderFn })
  }, [])

  const unregister = useCallback((type) => {
    setSubsection(prev => (prev?.type === type ? null : prev))
  }, [])

  return (
    <SidebarSubsectionContext.Provider value={{ subsection, register, unregister }}>
      {children}
    </SidebarSubsectionContext.Provider>
  )
}

export function useSidebarSubsection() {
  const ctx = useContext(SidebarSubsectionContext)
  if (!ctx) throw new Error('useSidebarSubsection must be used inside SidebarSubsectionProvider')
  return ctx
}
