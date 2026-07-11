/**
 * API service for the Feed-6.3 admin query endpoints.
 * No mock mode — this is an internal ops tool, not part of the product surface.
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

function buildQuery(params) {
  const qs = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") qs.set(k, v)
  })
  const s = qs.toString()
  return s ? `?${s}` : ""
}

// Cheap, real backend check — 200 means the logged-in user is an admin, 404
// means they aren't. Never guess this from a hardcoded/local email list: that
// would ship the admin allowlist in the public JS bundle.
export async function checkIsAdmin() {
  try {
    await apiFetch("/admin/projects")
    return true
  } catch {
    return false
  }
}

export async function listAdminProjects() {
  return apiFetch("/admin/projects")
}

export async function listAdminCalls({
  dateFrom, dateTo, callType, projectId, userId, includeTestData, limit = 20, offset = 0,
  sortBy, sortOrder,
} = {}) {
  const query = buildQuery({
    date_from: dateFrom,
    date_to: dateTo,
    call_type: callType,
    project_id: projectId,
    user_id: userId,
    include_test_data: includeTestData ? "true" : undefined,
    limit,
    offset,
    sort_by: sortBy,
    sort_order: sortOrder,
  })
  return apiFetch(`/admin/calls${query}`)
}

export async function getAdminSummary({ dateFrom, dateTo, includeTestData } = {}) {
  const query = buildQuery({
    date_from: dateFrom,
    date_to: dateTo,
    include_test_data: includeTestData ? "true" : undefined,
  })
  return apiFetch(`/admin/summary${query}`)
}

// Real per-day counts over the COMPLETE filtered set — not derived from any
// capped row fetch. Mirrors listAdminCalls' full filter set (unlike summary,
// which is date+test-data scoped only).
export async function getAdminCallVolume({ dateFrom, dateTo, callType, projectId, userId, includeTestData } = {}) {
  const query = buildQuery({
    date_from: dateFrom,
    date_to: dateTo,
    call_type: callType,
    project_id: projectId,
    user_id: userId,
    include_test_data: includeTestData ? "true" : undefined,
  })
  return apiFetch(`/admin/calls/volume${query}`)
}

export async function getAdminCallTree(runId) {
  return apiFetch(`/admin/calls/${encodeURIComponent(runId)}/tree`)
}
