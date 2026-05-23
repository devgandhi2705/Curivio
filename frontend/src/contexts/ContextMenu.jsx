import { createContext, useContext, useState, useCallback } from 'react'

const ContextMenuCtx = createContext(null)

export function ContextMenuProvider({ children }) {
  const [actionsByView, setActionsByView] = useState({})

  const setViewActions = useCallback((viewName, actionsArray) => {
    setActionsByView(prev => ({ ...prev, [viewName]: actionsArray ?? [] }))
  }, [])

  const clearViewActions = useCallback((viewName) => {
    setActionsByView(prev => {
      const next = { ...prev }
      delete next[viewName]
      return next
    })
  }, [])

  return (
    <ContextMenuCtx.Provider value={{ actionsByView, setViewActions, clearViewActions }}>
      {children}
    </ContextMenuCtx.Provider>
  )
}

export function useContextMenu() {
  const ctx = useContext(ContextMenuCtx)
  if (!ctx) throw new Error('useContextMenu must be inside ContextMenuProvider')
  return ctx
}
