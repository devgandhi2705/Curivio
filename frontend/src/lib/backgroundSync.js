/**
 * Silent background sync — pre-caches the user's data into IndexedDB so the
 * app is usable offline. Runs once on authenticated mount and again whenever
 * the browser regains connectivity. Never blocks the UI, never throws.
 *
 * Note: Read Later has no backend endpoint (api/queue.js is localStorage-only),
 * so it's mirrored from the local queue rather than fetched.
 */
import { getQueue } from "../api/queue.js"
import { articleKeyFromTitle } from "../api/feed.js"
import {
  saveProjectsList, saveProject,
  savePackage,
  saveDashboardOffline, saveBookmarks, saveReadLater,
  saveChatSessionsList, saveChatMessages,
  saveDiscussions,
} from "./offlineStorage.js"

const API_URL = import.meta.env.VITE_API_URL ?? ""
const SYNC_DELAY_MS = 300 // pause between batches so we don't hammer the backend
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

let _syncState = "idle" // 'idle' | 'syncing' | 'done' | 'offline'
export function getSyncState() { return _syncState }
function setSyncState(state) {
  _syncState = state
  window.dispatchEvent(new CustomEvent("curivio:sync-state", { detail: state }))
}

/** @param {string|null} authToken */
export async function runBackgroundSync(authToken) {
  if (!navigator.onLine) { setSyncState("offline"); return }
  if (!authToken) return

  const headers = { Authorization: `Bearer ${authToken}` }
  const safeFetch = async (url) => {
    try {
      const res = await fetch(url, { headers })
      if (!res.ok) return null
      return await res.json()
    } catch {
      return null
    }
  }

  setSyncState("syncing")

  try {
    // ── PRIORITY 1: Projects list ──────────────────────────────
    const projects = await safeFetch(`${API_URL}/projects`)
    const projectArray = Array.isArray(projects) ? projects : []
    if (projects) await saveProjectsList(projects)

    await sleep(SYNC_DELAY_MS)
    if (!navigator.onLine) { setSyncState("offline"); return }

    // ── PRIORITY 2: Project detail + all packages, per project ──
    // (The real API has no per-day sub-endpoint — one insights call already
    // returns every generated package for a project, so there's no per-day loop.)
    const syncedPackages = [] // { project, pkg } — reused for discussions below
    for (const project of projectArray) {
      if (!navigator.onLine) { setSyncState("offline"); return }

      const detail = await safeFetch(`${API_URL}/projects/${encodeURIComponent(project.project_id)}`)
      if (detail) await saveProject(detail)

      await sleep(100)
      const packages = await safeFetch(`${API_URL}/projects/${encodeURIComponent(project.project_id)}/insights?limit=20`)
      if (Array.isArray(packages)) {
        for (const pkg of packages) {
          await savePackage(pkg.id, pkg)
          syncedPackages.push({ project, pkg })
        }
      }

      await sleep(SYNC_DELAY_MS)
    }

    if (!navigator.onLine) { setSyncState("offline"); return }

    // ── PRIORITY 3: Dashboard ───────────────────────────────────
    const dashboard = await safeFetch(`${API_URL}/stats/reading`)
    if (dashboard) await saveDashboardOffline(dashboard)

    await sleep(SYNC_DELAY_MS)
    if (!navigator.onLine) { setSyncState("offline"); return }

    // ── PRIORITY 4: Bookmarks + Read Later ─────────────────────
    const bookmarks = await safeFetch(`${API_URL}/bookmarks`)
    if (bookmarks) await saveBookmarks(bookmarks)
    await saveReadLater(getQueue()) // local-only, no fetch needed

    await sleep(SYNC_DELAY_MS)
    if (!navigator.onLine) { setSyncState("offline"); return }

    // ── PRIORITY 5: Chat sessions + messages ───────────────────
    const sessions = await safeFetch(`${API_URL}/chat/sessions?limit=20`)
    const sessionArray = Array.isArray(sessions) ? sessions : []
    if (sessions) await saveChatSessionsList(sessionArray)

    for (const session of sessionArray) {
      if (!navigator.onLine) { setSyncState("offline"); return }
      await sleep(100)
      const messages = await safeFetch(`${API_URL}/chat/history/${encodeURIComponent(session.session_id)}?limit=50`)
      if (messages) await saveChatMessages(session.session_id, messages)
    }

    // ── PRIORITY 6: Discussions — lowest priority, best-effort only ──
    if (navigator.onLine) {
      try {
        for (const { project, pkg } of syncedPackages) {
          if (!navigator.onLine) break
          const cards = [...(pkg.insights ?? []), ...(pkg.curiosity_insights ?? [])]
          for (const card of cards) {
            if (!navigator.onLine) break
            await sleep(150)
            const articleKey = articleKeyFromTitle(card.title || "")
            const url = `${API_URL}/feed-chat-links?project_id=${encodeURIComponent(project.project_id)}&article_key=${encodeURIComponent(articleKey)}`
            const discussions = await safeFetch(url)
            if (discussions) await saveDiscussions(`${project.project_id}_${articleKey}`, discussions)
          }
        }
      } catch {
        // best-effort, silent failure
      }
    }

    setSyncState("done")
  } catch {
    // Top-level catch — entire sync is best-effort, never crashes the app.
    setSyncState("idle")
  }
}
