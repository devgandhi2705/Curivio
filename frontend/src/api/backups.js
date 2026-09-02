/**
 * Backup / restore API client.
 *
 * Admin endpoints mirror routes/backups.py. Restore is merge-only server-side
 * (INSERT OR IGNORE, never overwrite or delete), which is why the UI can offer
 * it as an ordinary button rather than a typed-confirmation danger zone — the
 * worst case of a mistaken restore is rows coming back that were already there.
 */

import { getAuthHeaders } from "./auth.js"

const API_URL = import.meta.env.VITE_API_URL ?? ""

async function apiFetch(path, options = {}) {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    const error = new Error(err.detail || `Request failed: ${res.status}`)
    error.status = res.status
    throw error
  }
  return res.json()
}

// ── admin ───────────────────────────────────────────────────────────────────

export async function listBackups() {
  return apiFetch("/admin/backups")
}

export async function createBackup() {
  return apiFetch("/admin/backups/create", { method: "POST" })
}

// The file itself. Fetched rather than linked to with a plain <a href> because
// /admin/* is gated by an Authorization header, which a browser navigation
// cannot send. Returns the Blob; the caller decides how to save it.
export async function fetchBackupFile(filename) {
  const res = await fetch(
    `${API_URL}/admin/backups/download?filename=${encodeURIComponent(filename)}`,
    { headers: getAuthHeaders() },
  )
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Download failed: ${res.status}`)
  }
  return res.blob()
}

export async function usersInBackup(filename) {
  return apiFetch(`/admin/backups/users?filename=${encodeURIComponent(filename)}`)
}

// Dry run — reports what a restore would pull in and writes nothing.
export async function previewRestore(filename, userId = null) {
  return apiFetch("/admin/backups/preview", {
    method: "POST",
    body: JSON.stringify({ filename, user_id: userId }),
  })
}

export async function runRestore(filename, userId = null) {
  return apiFetch("/admin/backups/restore", {
    method: "POST",
    body: JSON.stringify({ filename, user_id: userId }),
  })
}

export async function listDataLossRequests(status) {
  const q = status ? `?status=${encodeURIComponent(status)}` : ""
  return apiFetch(`/admin/data-loss-requests${q}`)
}

export async function resolveDataLossRequest(requestId, status, adminNote = "") {
  return apiFetch(`/admin/data-loss-requests/${encodeURIComponent(requestId)}`, {
    method: "PATCH",
    body: JSON.stringify({ status, admin_note: adminNote }),
  })
}

// ── signed-in user ──────────────────────────────────────────────────────────

export async function raiseDataLossRequest(description) {
  return apiFetch("/me/data-loss-request", {
    method: "POST",
    body: JSON.stringify({ description }),
  })
}

export async function myDataLossRequests() {
  return apiFetch("/me/data-loss-requests")
}
