/**
 * API service for research workspace endpoints.
 *
 * Set VITE_USE_MOCK=true in .env to bypass live API calls and return
 * static mock data — useful during frontend development and testing.
 */

import {
  MOCK_CATEGORIZED_RESOURCES,
  MOCK_DEEP_RESEARCH,
  MOCK_LEARNING_PATH,
  MOCK_SESSION_CONTEXT,
  MOCK_TOPIC_EXPANSION,
} from "../mocks/researchMocks.js"
import { getAuthHeaders } from "./auth.js"

const API_URL = import.meta.env.VITE_API_URL ?? ""
const USE_MOCK = import.meta.env.VITE_USE_MOCK === "true"

// Simulate network latency in mock mode so loading states are visible
const mockDelay = (ms = 600) =>
  new Promise((resolve) => setTimeout(resolve, ms))

async function post(path, body) {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Request failed: ${res.status}`)
  }
  return res.json()
}

async function get(path) {
  const res = await fetch(`${API_URL}${path}`, { headers: { ...getAuthHeaders() } })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Request failed: ${res.status}`)
  }
  return res.json()
}

export async function fetchTopicExpansion(topic) {
  if (USE_MOCK) {
    await mockDelay(500)
    return { ...MOCK_TOPIC_EXPANSION, topic }
  }
  return post("/topic-expansion", { topic })
}

export async function fetchDeepResearch(topic) {
  if (USE_MOCK) {
    await mockDelay(800)
    return { ...MOCK_DEEP_RESEARCH, topic }
  }
  return post("/deep-research", { topic })
}

export async function fetchLearningPath(topic) {
  if (USE_MOCK) {
    await mockDelay(900)
    return { ...MOCK_LEARNING_PATH, topic }
  }
  return post("/learning-path", { topic })
}

export async function fetchCategorize(resources) {
  if (USE_MOCK) {
    await mockDelay(400)
    return MOCK_CATEGORIZED_RESOURCES
  }
  return post("/categorize", { resources })
}

export async function fetchSessionContext(topic) {
  if (USE_MOCK) {
    await mockDelay(200)
    return { ...MOCK_SESSION_CONTEXT, topic }
  }
  return get(`/session-memory/${encodeURIComponent(topic)}/context`)
}
