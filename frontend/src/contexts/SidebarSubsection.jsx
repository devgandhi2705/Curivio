import { createContext, useContext, useState, useCallback } from 'react'

const SidebarSubsectionContext = createContext(null)

export function SidebarSubsectionProvider({ children }) {
  // subsections = { [type]: (query) => ReactNode }
  // Using a map so multiple always-mounted views (feed, chat) can coexist without overwriting each other
  const [subsections, setSubsections] = useState({})

  const register = useCallback((type, renderFn) => {
    setSubsections(prev => ({ ...prev, [type]: renderFn }))
  }, [])

  const unregister = useCallback((type) => {
    setSubsections(prev => {
      const next = { ...prev }
      delete next[type]
      return next
    })
  }, [])

  return (
    <SidebarSubsectionContext.Provider value={{ subsections, register, unregister }}>
      {children}
    </SidebarSubsectionContext.Provider>
  )
}

export function useSidebarSubsection() {
  const ctx = useContext(SidebarSubsectionContext)
  if (!ctx) throw new Error('useSidebarSubsection must be used inside SidebarSubsectionProvider')
  return ctx
}
