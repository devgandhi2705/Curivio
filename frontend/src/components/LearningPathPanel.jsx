/**
 * LearningPathPanel — tabbed beginner / intermediate / advanced learning path.
 *
 * Each tier shows an ordered list of steps. Each step contains:
 *   concept, explanation, why_it_matters, resources
 *
 * Resources that look like URLs are rendered as links.
 */

import { useState } from "react"

const TIERS = ["beginner", "intermediate", "advanced"]

const TIER_STYLE = {
  beginner: {
    active:   "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
    inactive: "text-slate-500 hover:text-slate-300 border-transparent",
    dot:      "bg-emerald-400",
    badge:    "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20",
    number:   "bg-emerald-500/15 text-emerald-400",
  },
  intermediate: {
    active:   "bg-blue-500/15 text-blue-300 border-blue-500/30",
    inactive: "text-slate-500 hover:text-slate-300 border-transparent",
    dot:      "bg-blue-400",
    badge:    "bg-blue-500/10 text-blue-400 border border-blue-500/20",
    number:   "bg-blue-500/15 text-blue-400",
  },
  advanced: {
    active:   "bg-violet-500/15 text-violet-300 border-violet-500/30",
    inactive: "text-slate-500 hover:text-slate-300 border-transparent",
    dot:      "bg-violet-400",
    badge:    "bg-violet-500/10 text-violet-400 border border-violet-500/20",
    number:   "bg-violet-500/15 text-violet-400",
  },
}

function isUrl(str) {
  return /^https?:\/\//i.test(str)
}

function ResourceLink({ resource }) {
  // Resources can be bare URLs or prefixed: "Book: ...", "Docs: https://..."
  const prefixMatch = resource.match(/^([A-Za-z ]+):\s*(.+)$/)
  const prefix = prefixMatch ? prefixMatch[1].trim() : null
  const rest   = prefixMatch ? prefixMatch[2].trim() : resource

  if (isUrl(rest)) {
    return (
      <a
        href={rest}
        target="_blank"
        rel="noopener noreferrer"
        className="flex items-center gap-1.5 text-xs text-blue-400/80 hover:text-blue-300 transition-colors"
      >
        {prefix && (
          <span className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 font-mono text-[10px] shrink-0">
            {prefix}
          </span>
        )}
        <span className="truncate">{rest}</span>
      </a>
    )
  }

  return (
    <span className="flex items-center gap-1.5 text-xs text-slate-400">
      {prefix && (
        <span className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-500 font-mono text-[10px] shrink-0">
          {prefix}
        </span>
      )}
      {rest}
    </span>
  )
}

function StepCard({ step, index, tier }) {
  const style = TIER_STYLE[tier]
  return (
    <div className="flex gap-4 py-4 border-b border-slate-800 last:border-0">
      {/* Step number */}
      <div
        className={`shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold mt-0.5 ${style.number}`}
      >
        {index + 1}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0 space-y-2">
        <h3 className="text-sm font-semibold text-slate-100">{step.concept}</h3>

        <p className="text-sm text-slate-400 leading-relaxed">{step.explanation}</p>

        {step.why_it_matters && (
          <div className="flex gap-2 text-xs text-slate-500 bg-slate-800/50 rounded-md px-3 py-2 border border-slate-700/50">
            <span className="shrink-0 text-slate-600 mt-px">Why it matters:</span>
            <span className="text-slate-400">{step.why_it_matters}</span>
          </div>
        )}

        {step.resources?.length > 0 && (
          <div className="space-y-1 pt-1">
            {step.resources.map((r, i) => (
              <ResourceLink key={i} resource={r} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function SkeletonStep() {
  return (
    <div className="flex gap-4 py-4 border-b border-slate-800 animate-pulse">
      <div className="shrink-0 w-7 h-7 rounded-full bg-slate-800 mt-0.5" />
      <div className="flex-1 space-y-2">
        <div className="h-4 w-40 rounded bg-slate-800" />
        <div className="h-3 w-full rounded bg-slate-800/60" />
        <div className="h-3 w-5/6 rounded bg-slate-800/60" />
        <div className="h-8 rounded-md bg-slate-800/40" />
      </div>
    </div>
  )
}

export default function LearningPathPanel({ data, loading }) {
  const [activeTier, setActiveTier] = useState("beginner")

  if (loading) {
    return (
      <div className="rounded-xl bg-slate-900 border border-slate-800 p-5">
        <div className="flex gap-2 mb-4">
          {TIERS.map((t) => (
            <div key={t} className="h-8 w-24 rounded-lg bg-slate-800 animate-pulse" />
          ))}
        </div>
        {[1, 2, 3].map((i) => <SkeletonStep key={i} />)}
      </div>
    )
  }

  if (!data) return null

  const steps = data[activeTier] || []
  const style = TIER_STYLE[activeTier]
  const stepCounts = TIERS.map((t) => ({ tier: t, count: (data[t] || []).length }))

  return (
    <div className="rounded-xl bg-slate-900 border border-slate-800 p-5">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-slate-300 tracking-wide uppercase">
          Learning Path
        </h2>
        {data.learning_stage && (
          <span className="text-xs text-slate-500">
            Profile:{" "}
            <span className="text-slate-400 font-medium">{data.learning_stage}</span>
          </span>
        )}
      </div>

      {/* Tier tabs */}
      <div className="flex gap-1.5 mb-5">
        {stepCounts.map(({ tier, count }) => (
          <button
            key={tier}
            onClick={() => setActiveTier(tier)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
              activeTier === tier
                ? TIER_STYLE[tier].active
                : TIER_STYLE[tier].inactive + " border-transparent"
            }`}
          >
            <span className="capitalize">{tier}</span>
            <span
              className={`px-1.5 py-0.5 rounded text-[10px] ${
                activeTier === tier
                  ? TIER_STYLE[tier].badge
                  : "bg-slate-800 text-slate-600"
              }`}
            >
              {count}
            </span>
          </button>
        ))}
      </div>

      {/* Steps */}
      {steps.length === 0 ? (
        <p className="text-sm text-slate-600 py-4">No steps for this level.</p>
      ) : (
        <div>
          {steps.map((step, i) => (
            <StepCard key={i} step={step} index={i} tier={activeTier} />
          ))}
        </div>
      )}
    </div>
  )
}
