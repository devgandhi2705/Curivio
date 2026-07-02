import { useState, useEffect, useCallback } from "react"
import { getAllMetadata } from "../lib/offlineStorage.js"

/** @returns {{offlineIds: Set<string>, isLoading: boolean}} */
export function useOfflineArticles() {
  const [offlineIds, setOfflineIds] = useState(new Set())
  const [isLoading, setIsLoading] = useState(true)

  const refresh = useCallback(() => {
    getAllMetadata()
      .then((records) => setOfflineIds(new Set(records.map((r) => r.id))))
      .catch(() => setOfflineIds(new Set()))
      .finally(() => setIsLoading(false))
  }, [])

  useEffect(() => {
    refresh()
    window.addEventListener("curivio:offline-saved", refresh)
    return () => window.removeEventListener("curivio:offline-saved", refresh)
  }, [refresh])

  return { offlineIds, isLoading }
}
