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

export async function createProject({ name, description, keywords, difficulty, focus_areas, color, preferred_sources = [], ignored_sources = [], daily_core_article_count = 4 }) {
  if (USE_MOCK) {
    await delay(400)
    const project = {
      project_id:               `proj-${Date.now()}`,
      name,
      description:              description || "",
      keywords:                 keywords || [],
      difficulty:               difficulty || "intermediate",
      focus_areas:              focus_areas || [],
      color:                    color || "blue",
      preferred_sources:        preferred_sources || [],
      ignored_sources:          ignored_sources || [],
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
    body: JSON.stringify({ name, description, keywords, difficulty, focus_areas, color, preferred_sources, ignored_sources, daily_core_article_count }),
  })
}

export async function checkSourceRelevance(domain, projectName, keywords) {
  if (USE_MOCK) {
    await delay(600)
    return { relevant: true, reason: "Mock: defaulting to relevant" }
  }
  return apiFetch("/projects/check-source-relevance", {
    method: "POST",
    body: JSON.stringify({ domain, project_name: projectName, keywords }),
  })
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

export async function generateProjectInsight(projectId) {
  if (USE_MOCK) {
    await delay(1400)
    const existing = _mockInsightStore[projectId] || []
    const dayNumber = (existing[0]?.day_number ?? 0) + 1
    const project   = _mockProjects.find(p => p.project_id === projectId)
    const diff      = project?.difficulty || "intermediate"
    const name      = project?.name ?? "Your Project"
    const areas     = project?.focus_areas || []

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
          category: areas[0] || "industry trends",
          title: `Shifting Dynamics Reshape ${name} Landscape`,
          summary: "Recent announcements signal a meaningful inflection point as leading practitioners and institutions adjust their strategic approaches. The changes reflect accumulating pressure from multiple directions.",
          educational_explanation: "Inflection points in an industry typically emerge when several slower-moving forces — technology maturation, regulatory pressure, and talent redistribution — align simultaneously. Recognizing this pattern early lets you position your learning ahead of the mainstream shift rather than reacting after it has occurred. The key signal to watch is when incumbents change behaviour, because they tend to move only when the cost of inaction exceeds the cost of change.",
          why_it_matters: `For someone building expertise in ${name}, understanding these structural shifts separates practitioners who lead from those who follow.`,
          source_links: [],
          difficulty: diff,
          estimated_read_time: "3 min",
        },
        {
          id: "card-2",
          content_type: "news",
          category: areas[1] || "technology",
          title: "New Tools and Methodologies Accelerate Adoption",
          summary: "Practitioners report accelerating uptake of newer analytical and operational methods, with early results demonstrating measurable improvements over baseline approaches.",
          educational_explanation: "Adoption curves in technical fields follow a predictable S-curve: slow early adoption as pioneers work out the kinks, rapid mainstream adoption once the value is demonstrated, and then a plateau as the approach becomes standard. Currently visible in this space is the transition from early to mainstream adoption — meaning the cost of not learning these methods is rising rapidly. Identifying which phase a methodology is in helps you calibrate investment: too early wastes effort on immature tools, too late means catching up on core competency.",
          why_it_matters: "Tracking adoption trends lets you front-run the skills market and develop expertise before demand peaks.",
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
          educational_explanation: "Regulatory signals typically lag industry practice by 2–5 years, but they carry significant weight once formalized. The smart practitioner response is to track the trajectory of emerging guidance and build systems that will be compliant before mandated — this converts a compliance cost into a competitive advantage. Understanding the feedback loop between voluntary best practice and eventual regulation is a core meta-skill in any fast-evolving domain.",
          why_it_matters: "Anticipating regulatory direction protects your work from sudden compliance costs and signals domain maturity to stakeholders.",
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
          educational_explanation: "A system is any collection of interrelated components whose interactions produce emergent behaviour — behaviour that cannot be predicted by studying components in isolation. In practical terms, this means that improving one metric in isolation often degrades another: optimising for speed may harm quality, cutting costs may reduce resilience. The key concepts are: stocks (accumulated quantities), flows (rates of change), and feedback loops (self-reinforcing or balancing). To apply systems thinking, draw the causal loop diagram of your problem before proposing a solution. This surfaces hidden second-order effects that straightforward analysis misses. Example: in supply chains, reducing inventory buffers (stock) speeds up flow but amplifies volatility — the 'bullwhip effect'.",
          why_it_matters: `Systems thinking is foundational for anyone working on complex ${name} problems where optimising locally produces sub-optimal global outcomes.`,
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
          educational_explanation: "Every dataset contains both signal (the pattern you care about) and noise (random variation that obscures it). The fundamental mistake practitioners make is over-fitting: treating noise as signal by building models that explain past data perfectly but predict future data poorly. The antidote is a structured analytical process: define your hypothesis before looking at the data, determine what evidence would change your mind, apply consistent evaluation criteria, and document your reasoning chain. This last step — the reasoning log — is what makes your analysis auditable and improvable. In high-stakes domains, the discipline of the process matters more than the sophistication of the tool.",
          why_it_matters: "Mastering this discipline converts you from a practitioner who reacts to data to one who extracts reliable, defensible insights from it.",
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
