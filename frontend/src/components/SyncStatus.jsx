import { useState, useEffect, useRef } from "react"
import { getSyncState } from "../lib/backgroundSync.js"

/** Small status icon reflecting background-sync progress: syncing dot → done checkmark → hidden. */
export default function SyncStatus() {
  const [state, setState] = useState(getSyncState())
  const hideTimerRef = useRef(null)

  useEffect(() => {
    function onSyncState(e) {
      setState(e.detail)
      clearTimeout(hideTimerRef.current)
      if (e.detail === "done") {
        hideTimerRef.current = setTimeout(() => setState("idle"), 3000)
      }
    }
    window.addEventListener("curivio:sync-state", onSyncState)
    return () => {
      window.removeEventListener("curivio:sync-state", onSyncState)
      clearTimeout(hideTimerRef.current)
    }
  }, [])

  if (state === "syncing") {
    return (
      <span
        aria-label="Syncing for offline use"
        title="Syncing for offline use"
        style={{
          display: "inline-block",
          width: 8,
          height: 8,
          borderRadius: "50%",
          background: "currentColor",
          opacity: 0.6,
          animation: "curivio-sync-pulse 1.2s ease-in-out infinite",
        }}
      >
        <style>{`@keyframes curivio-sync-pulse { 0%,100%{opacity:.3} 50%{opacity:.8} }`}</style>
      </span>
    )
  }

  if (state === "done") {
    return (
      <svg
        width="16" height="16" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth="2"
        strokeLinecap="round" strokeLinejoin="round"
        aria-label="Synced for offline use"
      >
        <title>Synced for offline use</title>
        <path d="M20 16.2A4.5 4.5 0 0 0 17.5 8h-1.8A7 7 0 1 0 4 15" />
        <polyline points="9 15 12 18 16 11" />
      </svg>
    )
  }

  return null
}
