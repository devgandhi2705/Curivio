/**
 * API service for learning projects and project insights.
 * Set VITE_USE_MOCK=true in .env to use mock data.
 */

import {
  MOCK_PROJECTS,
  MOCK_PACKAGES_BY_PROJECT,
} from "../mocks/projectMocks.js"
import { MOCK_PROGRESSIONS } from "../mocks/progressionMocks.js"
import { getAuthHeaders } from "./auth.js"

const API_URL = import.meta.env.VITE_API_URL ?? ""
const USE_MOCK = import.meta.env.VITE_USE_MOCK === "true"

const delay = (ms = 400) => new Promise(r => setTimeout(r, ms))

async function apiFetch(path, options = {}) {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Request failed: ${res.status}`)
  }
  return res.json()
}

// ─────────────────────────────────────────────────────────────────────────────
// Projects CRUD
// ─────────────────────────────────────────────────────────────────────────────

let _mockProjects = [...MOCK_PROJECTS]

export async function listProjects() {
  if (USE_MOCK) {
    await delay(300)
    return _mockProjects.map(p => {
      const latestPkg = (_mockInsightStore[p.project_id] || [])[0]
      return {
        ...p,
        last_package_headline: latestPkg?.package_headline ?? null,
      }
    })
  }
  return apiFetch("/projects")
}

// Batch-fetch all progressions in parallel (mock: single delay pass-through)
export async function listAllProgressions(projectIds) {
  if (USE_MOCK) {
    await delay(250)
    return Object.fromEntries(
      projectIds.map(pid => [pid, _mockProgressionStore[pid] ?? _emptyProgression(pid)])
    )
  }
  const results = await Promise.allSettled(
    projectIds.map(pid => apiFetch(`/projects/${encodeURIComponent(pid)}/progression`))
  )
  return Object.fromEntries(
    projectIds.map((pid, i) => [pid, results[i].status === "fulfilled" ? results[i].value : null])
  )
}

export async function getProject(projectId) {
  if (USE_MOCK) {
    await delay(200)
    return _mockProjects.find(p => p.project_id === projectId) ?? null
  }
  return apiFetch(`/projects/${encodeURIComponent(projectId)}`)
}

export async function createProject({ name, description, keywords, difficulty, color, daily_core_article_count = 4 }) {
  if (USE_MOCK) {
    await delay(400)
    const project = {
      project_id:               `proj-${Date.now()}`,
      name,
      description:              description || "",
      keywords:                 keywords || [],
      difficulty:               difficulty || "intermediate",
      color:                    color || "blue",
      daily_core_article_count: daily_core_article_count || 4,
      insight_count:            0,
      last_insight_at:          null,
      created_at:               new Date().toISOString(),
      updated_at:               new Date().toISOString(),
    }
    _mockProjects = [project, ..._mockProjects]
    return project
  }
  return apiFetch("/projects", {
    method: "POST",
    body: JSON.stringify({ name, description, keywords, difficulty, color, daily_core_article_count }),
  })
}

export async function updateIntentProfile(projectId, profile) {
  if (USE_MOCK) {
    await delay(350)
    return { ok: true, intent_profile: profile }
  }
  return apiFetch(`/projects/${encodeURIComponent(projectId)}/intent-profile`, {
    method: "PUT",
    body: JSON.stringify(profile),
  })
}

export async function confirmIntent(projectId) {
  if (USE_MOCK) {
    await delay(200)
    _mockProjects = _mockProjects.map(p =>
      p.project_id === projectId ? { ...p, intent_confirmed: 1 } : p
    )
    return _mockProjects.find(p => p.project_id === projectId) ?? null
  }
  return apiFetch(`/projects/${encodeURIComponent(projectId)}/confirm-intent`, { method: "POST" })
}

export async function updateProject(projectId, fields) {
  if (USE_MOCK) {
    await delay(300)
    _mockProjects = _mockProjects.map(p =>
      p.project_id === projectId
        ? { ...p, ...fields, updated_at: new Date().toISOString() }
        : p
    )
    return _mockProjects.find(p => p.project_id === projectId)
  }
  return apiFetch(`/projects/${encodeURIComponent(projectId)}`, {
    method: "PUT",
    body: JSON.stringify(fields),
  })
}

export async function suggestKeywords(name, description, difficulty = "intermediate") {
  if (USE_MOCK) {
    await delay(1100)
    const text = `${name} ${description}`.toLowerCase()
    const adv  = difficulty === "advanced"
    const beg  = difficulty === "beginner"
    if (text.includes("ai") || text.includes("machine learning") || text.includes("llm") || text.includes("agent"))
      return { keywords: adv
        ? ["transformer architecture", "RLHF", "agentic workflows", "inference optimization", "multi-modal LLMs", "AI safety 2025", "foundation model evaluation"]
        : beg
        ? ["what is AI", "ChatGPT explained", "AI tools for beginners", "machine learning basics", "real-world AI applications 2025"]
        : ["LLMs", "AI Agents", "RAG", "Enterprise AI", "MLOps", "Foundation Models", "AI deployment 2025"] }
    if (text.includes("pharma") || text.includes("drug") || text.includes("medicine"))
      return { keywords: ["USFDA", "generic drugs", "API manufacturing", "clinical trials", "pharma exports 2025", "drug pricing", "biosimilars"] }
    if (text.includes("supply chain") || text.includes("logistics"))
      return { keywords: ["demand forecasting", "logistics AI", "nearshoring 2025", "inventory optimization", "3PL", "cold chain"] }
    if (text.includes("finance") || text.includes("invest") || text.includes("trading") || text.includes("quant"))
      return { keywords: adv
        ? ["factor model alpha decay", "vol surface arbitrage", "alternative data signals", "execution algorithms", "portfolio attribution 2025"]
        : ["algorithmic trading", "factor models", "derivatives", "risk management 2025", "quantitative finance"] }
    return { keywords: ["market analysis", "industry dynamics", "regulatory trends 2025", "competitive landscape", "emerging players"] }
  }
  return apiFetch("/projects/suggest-keywords", {
    method: "POST",
    body: JSON.stringify({ name, description, difficulty }),
  })
}

export async function deleteProject(projectId) {
  if (USE_MOCK) {
    await delay(300)
    _mockProjects = _mockProjects.filter(p => p.project_id !== projectId)
    delete _mockInsightStore[projectId]
    return { project_id: projectId, deleted: true }
  }
  return apiFetch(`/projects/${encodeURIComponent(projectId)}`, { method: "DELETE" })
}

// ─────────────────────────────────────────────────────────────────────────────
// Project Insights (daily packages)
// ─────────────────────────────────────────────────────────────────────────────

// In-memory store — starts from mock data, grows when generating
let _mockInsightStore = Object.fromEntries(
  Object.entries(MOCK_PACKAGES_BY_PROJECT).map(([pid, pkgs]) => [pid, [...pkgs]])
)

export async function listProjectInsights(projectId, limit = 20) {
  if (USE_MOCK) {
    await delay(350)
    return (_mockInsightStore[projectId] || []).slice(0, limit)
  }
  return apiFetch(`/projects/${encodeURIComponent(projectId)}/insights?limit=${limit}`)
}

export async function getInsightStatus(projectId, insightId) {
  if (USE_MOCK) {
    await delay(200)
    return { status: 'done' }
  }
  return apiFetch(`/projects/${encodeURIComponent(projectId)}/insights/${insightId}/status`)
}

export async function generateProjectInsight(projectId) {
  if (USE_MOCK) {
    await delay(1400)
    const existing = _mockInsightStore[projectId] || []
    const dayNumber = (existing[0]?.day_number ?? 0) + 1
    const project   = _mockProjects.find(p => p.project_id === projectId)
    const diff      = project?.difficulty || "intermediate"
    const name      = project?.name ?? "Your Project"

    const newPkg = {
      id:               `pkg-mock-${Date.now()}`,
      project_id:       projectId,
      day_number:       dayNumber,
      generated_at:     new Date().toISOString(),
      package_headline: `Day ${dayNumber} — Key Developments in ${name}`,
      content_mix:      "3 news · 2 educational",
      learning_thread:  `Day ${dayNumber} connects emerging news to foundational concepts, deepening your practical understanding of ${name}.`,
      action_item:      `Spend 30 minutes applying one concept from today's educational cards to a real scenario or dataset related to ${name}.`,
      insights: [
        {
          id: "card-1",
          content_type: "news",
          category: "industry trends",
          title: `Shifting Dynamics Reshape ${name} Landscape`,
          summary: "Recent announcements signal a meaningful inflection point as leading practitioners and institutions adjust their strategic approaches. The changes reflect accumulating pressure from multiple directions.",
          blocks: [
            { type: "evidence",    content: `Multiple reports indicate that ${name} practitioners are accelerating structural changes — driven by technology maturation, regulatory pressure, and talent redistribution aligning simultaneously.` },
            { type: "explanation", content: "Inflection points emerge when slower-moving forces align. The key signal: incumbents change behaviour only when the cost of inaction exceeds the cost of change — a pattern visible across every major industry transition." },
            { type: "mechanism",   content: `For someone building expertise in ${name}, this structural shift creates a narrow window: the practitioners who recognise the inflection early can position their learning ahead of the mainstream, capturing the compounding advantage of early depth. Once the shift becomes obvious to everyone, the differentiation collapses.` },
          ],
          source_links: [],
          difficulty: diff,
          estimated_read_time: "3 min",
        },
        {
          id: "card-2",
          content_type: "news",
          category: "technology",
          title: "New Tools and Methodologies Accelerate Adoption",
          summary: "Practitioners report accelerating uptake of newer analytical and operational methods, with early results demonstrating measurable improvements over baseline approaches.",
          blocks: [
            { type: "evidence",    content: "Adoption data shows this methodology moving from the early-majority into mainstream phase — measurable improvements over baseline approaches are now documented across multiple independent case studies." },
            { type: "key_takeaway", content: "Identifying which phase a methodology occupies lets you calibrate investment: too early wastes effort on immature tools, too late means catching up on core competency." },
            { type: "implication", content: "The cost of not learning these methods is rising rapidly. Practitioners who front-run mainstream adoption build the rarest asset in any field: a head start that cannot be bought later." },
          ],
          source_links: [],
          difficulty: diff,
          estimated_read_time: "3 min",
        },
        {
          id: "card-3",
          content_type: "news",
          category: "market",
          title: "Regulatory and Competitive Signals Demand Attention",
          summary: "Regulatory bodies and major market participants have released guidance that reshapes operating expectations. The changes affect compliance timelines and create new differentiation opportunities.",
          blocks: [
            { type: "evidence",      content: "Regulatory bodies have released formal guidance affecting compliance timelines. Major market participants have begun pre-compliance positioning ahead of the enforcement date." },
            { type: "counterpoint",  content: "Sceptics argue regulatory signals in this domain consistently lag practice by 2–5 years and should not drive near-term investment. Historical precedent supports this — but ignores the asymmetric cost of being caught non-compliant at enforcement." },
            { type: "warning",       content: "Compliance timing risk is real: organizations that delay until enforcement typically face compacted delivery windows, premium vendor pricing, and reduced negotiating leverage with regulators." },
          ],
          source_links: [],
          difficulty: diff,
          estimated_read_time: "2 min",
        },
        {
          id: "card-4",
          content_type: "educational",
          category: "fundamentals",
          title: `Concept: Systems Thinking — How to Reason About ${name} Holistically`,
          summary: "Systems thinking is the meta-skill that lets practitioners understand why isolated interventions often fail and how to design durable solutions that account for feedback effects.",
          blocks: [
            { type: "key_takeaway", content: "A system's behaviour emerges from component interactions, not components in isolation — optimising one metric in isolation often degrades another." },
            { type: "evidence",     content: "The canonical example: in supply chains, reducing inventory buffers (stock) speeds up flow but amplifies demand volatility downstream — the documented 'bullwhip effect', studied across thousands of supply networks." },
            { type: "example",      content: `In ${name}, this manifests when practitioners optimise for speed, only to discover that quality or resilience has silently degraded. The causal loop diagram surfaces these second-order effects before the intervention.` },
            { type: "step_list",    content: "Apply systems thinking:\n1. Define stocks (what accumulates) and flows (rates of change)\n2. Map feedback loops: reinforcing (amplifying) vs balancing (stabilising)\n3. Draw the causal loop diagram before proposing a solution\n4. Identify second-order effects on adjacent metrics" },
          ],
          source_links: [],
          difficulty: diff,
          estimated_read_time: "6 min",
        },
        {
          id: "card-5",
          content_type: "educational",
          category: "methodology",
          title: "Concept: Signal vs Noise — Extracting Actionable Insight from Data",
          summary: "The analytical discipline of separating meaningful patterns from statistical noise is one of the most transferable and underrated skills in any data-rich domain.",
          blocks: [
            { type: "evidence",    content: "Studies on practitioner error in data-rich fields consistently find the same root cause: over-fitting — treating noise as signal by building models that explain past data perfectly but predict future data poorly." },
            { type: "explanation", content: "The antidote is a structured analytical process: define the hypothesis before looking at the data, determine what evidence would change your mind, apply consistent evaluation criteria, and document the reasoning chain. The reasoning log is what makes analysis auditable and improvable." },
            { type: "reflection",  content: "In high-stakes domains, the discipline of the process matters more than the sophistication of the tool. Mastering this converts you from a practitioner who reacts to data to one who extracts reliable, defensible insights from it." },
          ],
          source_links: [],
          difficulty: diff,
          estimated_read_time: "5 min",
        },
      ],
    }

    _mockInsightStore = {
      ..._mockInsightStore,
      [projectId]: [newPkg, ...existing],
    }
    _mockProjects = _mockProjects.map(p =>
      p.project_id === projectId
        ? { ...p, insight_count: (p.insight_count || 0) + 1, last_insight_at: newPkg.generated_at }
        : p
    )
    // Auto-advance mock progression
    const newConcepts = newPkg.insights
      .map(c => c.category)
      .filter(Boolean)
    const prog = _mockProgressionStore[projectId] ?? _emptyProgression(projectId)
    const alreadyNorm = new Set(prog.explored_concepts.map(s => s.toLowerCase()))
    const toAdd = newConcepts.filter(c => !alreadyNorm.has(c.toLowerCase()))
    _mockProgressionStore[projectId] = {
      ...prog,
      current_focus:    newPkg.package_headline,
      days_completed:   dayNumber,
      explored_concepts: [...prog.explored_concepts, ...toAdd],
      updated_at:       newPkg.generated_at,
    }
    return newPkg
  }
  return apiFetch(`/projects/${encodeURIComponent(projectId)}/insights/generate`, { method: "POST" })
}

export async function deleteProjectInsight(projectId, insightId) {
  if (USE_MOCK) {
    await delay(100)
    const store = _mockInsightStore[projectId] || []
    _mockInsightStore[projectId] = store.filter(p => String(p.id) !== String(insightId))
    return
  }
  return apiFetch(
    `/projects/${encodeURIComponent(projectId)}/insights/${encodeURIComponent(insightId)}`,
    { method: "DELETE" }
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Learning Progression
// ─────────────────────────────────────────────────────────────────────────────

let _mockProgressionStore = Object.fromEntries(
  Object.entries(MOCK_PROGRESSIONS).map(([pid, prog]) => [pid, { ...prog }])
)

const _emptyProgression = (projectId) => ({
  project_id:            projectId,
  current_level:         "beginner",
  current_focus:         null,
  explored_concepts:     [],
  completed_topics:      [],
  suggested_next_topics: [],
  days_completed:        0,
  updated_at:            new Date().toISOString(),
})

export async function getProgression(projectId) {
  if (USE_MOCK) {
    await delay(200)
    return _mockProgressionStore[projectId] ?? _emptyProgression(projectId)
  }
  return apiFetch(`/projects/${encodeURIComponent(projectId)}/progression`)
}

export async function updateProgression(projectId, fields) {
  if (USE_MOCK) {
    await delay(250)
    const existing = _mockProgressionStore[projectId] ?? _emptyProgression(projectId)
    _mockProgressionStore[projectId] = {
      ...existing,
      ...fields,
      updated_at: new Date().toISOString(),
    }
    return _mockProgressionStore[projectId]
  }
  return apiFetch(`/projects/${encodeURIComponent(projectId)}/progression`, {
    method: "PUT",
    body: JSON.stringify(fields),
  })
}

// ─────────────────────────────────────────────────────────────────────────────
// Batch generation (scheduler / manual trigger)
// ─────────────────────────────────────────────────────────────────────────────

export async function getJourneyPreview(projectId) {
  if (USE_MOCK) {
    await delay(150)
    return { planned: false }
  }
  return apiFetch(`/projects/${encodeURIComponent(projectId)}/journey-preview`)
}

export async function triggerAllProjectsGeneration(force = false) {
  if (USE_MOCK) {
    await delay(600)
    return {
      total:     _mockProjects.length,
      generated: _mockProjects.length,
      skipped:   0,
      failed:    0,
      errors:    [],
    }
  }
  return apiFetch(`/projects/generate-all${force ? "?force=true" : ""}`, { method: "POST" })
}
