/**
 * API client for shareable links (feed packages and chat threads).
 */
import { getAuthHeaders } from "./auth.js"

const API_URL = import.meta.env.VITE_API_URL ?? ""

async function post(path, body, { auth = true } = {}) {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(auth ? getAuthHeaders() : {}) },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Request failed: ${res.status}`)
  }
  return res.json()
}

async function get(path, { auth = false } = {}) {
  const res = await fetch(`${API_URL}${path}`, { headers: { ...(auth ? getAuthHeaders() : {}) } })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Request failed: ${res.status}`)
  }
  return res.json()
}

export function createShareLink(type, resourceId) {
  return post("/share/create", { type, resource_id: resourceId })
}

export function resolveShareLink(token) {
  return get(`/share/${encodeURIComponent(token)}`)
}

export function forkSharedChat(token) {
  return post(`/share/chat/${encodeURIComponent(token)}/fork`, {})
}
