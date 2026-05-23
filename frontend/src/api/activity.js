/**
 * API client for the per-project learning activity calendar.
 * Returns 365 daily records: { date, packages_generated, cards_read }.
 */

import { getAuthHeaders } from "./auth.js"

const API_URL = import.meta.env.VITE_API_URL ?? ""
const USE_MOCK = import.meta.env.VITE_USE_MOCK === "true"

function _mockData(days = 365) {
  const today = new Date()
  const out = []
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today)
    d.setDate(d.getDate() - i)
    const ds = d.toISOString().slice(0, 10)
    const active = Math.random() < 0.18
    out.push({
      date:               ds,
      packages_generated: active && Math.random() < 0.5 ? 1 : 0,
      cards_read:         active ? Math.floor(Math.random() * 10) + 1 : 0,
    })
  }
  return out
}

export async function getAllProjectsActivity(days = 365) {
  if (USE_MOCK) {
    await new Promise(r => setTimeout(r, 80))
    return _mockData(days)
  }
  try {
    const res = await fetch(
      `${API_URL}/activity/all?days=${days}`,
      { headers: { ...getAuthHeaders() } }
    )
    if (!res.ok) return []
    return res.json()
  } catch {
    return []
  }
}

export async function getProjectActivity(projectId, days = 365) {
  if (USE_MOCK) {
    await new Promise(r => setTimeout(r, 80))
    return _mockData(days)
  }
  try {
    const res = await fetch(
      `${API_URL}/projects/${encodeURIComponent(projectId)}/activity?days=${days}`,
      { headers: { ...getAuthHeaders() } }
    )
    if (!res.ok) return []
    return res.json()
  } catch {
    return []
  }
}
