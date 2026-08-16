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
  sortBy, sortOrder, search,
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
    search,
  })
  return apiFetch(`/admin/calls${query}`)
}

// Phase D: projectId/userId/status/actionType added alongside the two the
// task explicitly called for (status/actionType) — B2 already wired all four
// onto the /admin/summary route, and leaving project/user half-fixed in the
// same call site (tiles silently ignoring Project/User while now honoring
// Status/Action Type) would be a stranger inconsistency than just finishing it.
// Phase F: dayRef/targetLanguage added too — same reasoning, closes the last
// gap (FilterRail's Day/Language sub-filters previously narrowed the grouped
// list but not these row-level tiles).
export async function getAdminSummary({
  dateFrom, dateTo, includeTestData, projectId, userId, status, actionType,
  dayRef, targetLanguage, search,
} = {}) {
  const query = buildQuery({
    date_from: dateFrom,
    date_to: dateTo,
    include_test_data: includeTestData ? "true" : undefined,
    project_id: projectId,
    user_id: userId,
    status,
    action_type: actionType,
    day_ref: dayRef,
    target_language: targetLanguage,
    search,
  })
  return apiFetch(`/admin/summary${query}`)
}

// Phase F — group-level (trace_id/operation) counterpart to getAdminSummary's
// row totals. Same filter shape as listAdminCallsGrouped.
export async function getAdminOperationSummary({
  dateFrom, dateTo, projectId, userId, includeTestData,
  status, actionType, dayRef, targetLanguage, search,
} = {}) {
  const query = buildQuery({
    date_from: dateFrom,
    date_to: dateTo,
    project_id: projectId,
    user_id: userId,
    include_test_data: includeTestData ? "true" : undefined,
    status,
    action_type: actionType,
    day_ref: dayRef,
    target_language: targetLanguage,
    search,
  })
  return apiFetch(`/admin/operations/summary${query}`)
}

// Phase D primary source — grouped by trace_id (B1/B2/B2b/B2c). Replaces
// listAdminCalls as AdminPage's main feed; listAdminCalls stays below,
// unused by the UI now, because the backend route deliberately still works
// (B2 kept it running on purpose) and this file mirrors the real API surface.
// Phase Q: sortBy/sortOrder added — /admin/calls/grouped now takes real
// sort_by/sort_order params (GROUP_SORT_COLUMNS allowlist), same shape
// listAdminCalls already had for the flat /admin/calls route.
export async function listAdminCallsGrouped({
  dateFrom, dateTo, projectId, userId, includeTestData,
  status, actionType, dayRef, targetLanguage, search,
  limit = 20, offset = 0, sortBy, sortOrder,
} = {}) {
  const query = buildQuery({
    date_from: dateFrom,
    date_to: dateTo,
    project_id: projectId,
    user_id: userId,
    include_test_data: includeTestData ? "true" : undefined,
    status,
    action_type: actionType,
    day_ref: dayRef,
    target_language: targetLanguage,
    search,
    limit,
    offset,
    sort_by: sortBy,
    sort_order: sortOrder,
  })
  return apiFetch(`/admin/calls/grouped${query}`)
}

// Phase I — the COMPLETE filtered set for a bulk download, unpaginated.
// Same filter shape as listAdminCallsGrouped deliberately: a bulk export must
// respect every active filter, and reusing the shape is what guarantees it.
// Not served by listAdminCallsGrouped with a big limit — that route caps at
// 100 groups, which would make a full export 58 round-trips (~182s measured)
// instead of one (~1.8s).
export async function exportAdminCallsGrouped({
  dateFrom, dateTo, projectId, userId, includeTestData,
  status, actionType, dayRef, targetLanguage, search,
} = {}) {
  const query = buildQuery({
    date_from: dateFrom,
    date_to: dateTo,
    project_id: projectId,
    user_id: userId,
    include_test_data: includeTestData ? "true" : undefined,
    status,
    action_type: actionType,
    day_ref: dayRef,
    target_language: targetLanguage,
    search,
  })
  return apiFetch(`/admin/calls/export${query}`)
}

// Real per-day counts over the COMPLETE filtered set — not derived from any
// capped row fetch. Phase F: status/actionType/dayRef/targetLanguage added —
// the trend line used to silently ignore Action Type (and everything since
// B2) while every other view on the page already honored it.
export async function getAdminCallVolume({
  dateFrom, dateTo, callType, projectId, userId, includeTestData,
  status, actionType, dayRef, targetLanguage, search,
} = {}) {
  const query = buildQuery({
    date_from: dateFrom,
    date_to: dateTo,
    call_type: callType,
    project_id: projectId,
    user_id: userId,
    include_test_data: includeTestData ? "true" : undefined,
    status,
    action_type: actionType,
    day_ref: dayRef,
    target_language: targetLanguage,
    search,
  })
  return apiFetch(`/admin/calls/volume${query}`)
}

export async function getAdminCallTree(runId) {
  return apiFetch(`/admin/calls/${encodeURIComponent(runId)}/tree`)
}
