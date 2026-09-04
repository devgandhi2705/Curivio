/**
 * TopicGraph — SVG radial hub-and-spoke diagram.
 *
 * Center node = searched topic.
 * Peripheral nodes colour-coded by type:
 *   amber  = prerequisites
 *   sky    = related topics
 *   violet = advanced follow-ups
 *
 * No external libraries; pure React + SVG.
 */

const W = 600
const H = 320
const CX = W / 2
const CY = H / 2
const RADIUS = 120

const TYPE_COLOR = {
  prerequisite: "var(--u-warn)",
  related:      "var(--u-info)",
  advanced:     "var(--u-secondary)",
}

const TYPE_LABEL = {
  prerequisite: "Prerequisite",
  related:      "Related",
  advanced:     "Advanced",
}

function truncate(str, n) {
  return str.length > n ? str.slice(0, n - 1) + "…" : str
}

function buildNodes(prerequisites, related_topics, advanced_follow_ups) {
  const groups = [
    { items: prerequisites,      type: "prerequisite" },
    { items: related_topics,     type: "related"      },
    { items: advanced_follow_ups, type: "advanced"    },
  ]

  const all = []
  groups.forEach(({ items, type }) => {
    items.forEach((label) => all.push({ label, type }))
  })

  const n = all.length
  return all.map((node, i) => {
    // Start from top (−π/2), distribute evenly clockwise
    const angle = (i / n) * 2 * Math.PI - Math.PI / 2
    return {
      ...node,
      x: CX + RADIUS * Math.cos(angle),
      y: CY + RADIUS * Math.sin(angle),
      angle,
    }
  })
}

function labelAnchor(x) {
  if (x < CX - 20) return "end"
  if (x > CX + 20) return "start"
  return "middle"
}

function labelOffset(node) {
  const anchor = labelAnchor(node.x)
  const dx = anchor === "end" ? -10 : anchor === "start" ? 10 : 0
  const dy = node.y < CY - 20 ? -10 : node.y > CY + 20 ? 10 : 0
  return { lx: node.x + dx, ly: node.y + dy }
}

export default function TopicGraph({ data, loading }) {
  if (loading) {
    return (
      <div className="flex items-center justify-center h-48 rounded-xl bg-slate-900 border border-slate-800">
        <div className="flex gap-1.5 items-center text-slate-500 text-sm">
          <span className="w-1.5 h-1.5 rounded-full bg-slate-500 animate-pulse" />
          <span className="w-1.5 h-1.5 rounded-full bg-slate-500 animate-pulse [animation-delay:150ms]" />
          <span className="w-1.5 h-1.5 rounded-full bg-slate-500 animate-pulse [animation-delay:300ms]" />
          <span className="ml-2">Mapping topic graph</span>
        </div>
      </div>
    )
  }

  if (!data) return null

  const { topic, prerequisites = [], related_topics = [], advanced_follow_ups = [] } = data
  const nodes = buildNodes(prerequisites, related_topics, advanced_follow_ups)

  return (
    <div className="rounded-xl bg-slate-900 border border-slate-800 p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-slate-300 tracking-wide uppercase">
          Topic Graph
        </h2>
        <div className="flex gap-3 text-xs text-slate-500">
          {Object.entries(TYPE_LABEL).map(([type, label]) => (
            <span key={type} className="flex items-center gap-1">
              <span
                className="inline-block w-2 h-2 rounded-full"
                style={{ backgroundColor: TYPE_COLOR[type] }}
              />
              {label}
            </span>
          ))}
        </div>
      </div>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        aria-label={`Topic graph for ${topic}`}
      >
        {/* Spoke lines */}
        {nodes.map((node, i) => (
          <line
            key={i}
            x1={CX}
            y1={CY}
            x2={node.x}
            y2={node.y}
            style={{ stroke: "var(--u-track)" }}
            strokeWidth="1.5"
          />
        ))}

        {/* Peripheral nodes */}
        {nodes.map((node, i) => {
          const color = TYPE_COLOR[node.type]
          const { lx, ly } = labelOffset(node)
          const anchor = labelAnchor(node.x)
          return (
            <g key={i}>
              <circle cx={node.x} cy={node.y} r="5" style={{ fill: color }} opacity="0.85" />
              <text
                x={lx}
                y={ly}
                textAnchor={anchor}
                dominantBaseline="middle"
                style={{ fill: color }}
                fontSize="10"
                fontFamily="ui-monospace, monospace"
                opacity="0.9"
              >
                {truncate(node.label, 16)}
              </text>
            </g>
          )
        })}

        {/* Center node */}
        <circle cx={CX} cy={CY} r="32" style={{ fill: "var(--u-surface)", stroke: "var(--u-accent)" }} strokeWidth="2" />
        <circle cx={CX} cy={CY} r="28" style={{ fill: "var(--u-track)" }} />
        <text
          x={CX}
          y={CY - 5}
          textAnchor="middle"
          dominantBaseline="middle"
          style={{ fill: "var(--u-accent-soft)" }}
          fontSize="10"
          fontWeight="600"
          fontFamily="ui-sans-serif, sans-serif"
        >
          {truncate(topic, 14)}
        </text>
        <text
          x={CX}
          y={CY + 8}
          textAnchor="middle"
          dominantBaseline="middle"
          style={{ fill: "var(--u-axis)" }}
          fontSize="8"
          fontFamily="ui-sans-serif, sans-serif"
        >
          {nodes.length} concepts
        </text>
      </svg>

      {/* Learning progression */}
      {data.learning_progression?.length > 0 && (
        <div className="mt-3 pt-3 border-t border-slate-800">
          <p className="text-xs text-slate-500 mb-2">Learning progression</p>
          <div className="flex flex-wrap items-center gap-1">
            {data.learning_progression.map((step, i) => (
              <span key={i} className="flex items-center gap-1">
                <span
                  className={`px-2 py-0.5 rounded text-xs font-medium ${
                    step === topic
                      ? "bg-blue-500/20 text-blue-300 border border-blue-500/30"
                      : "bg-slate-800 text-slate-400"
                  }`}
                >
                  {step}
                </span>
                {i < data.learning_progression.length - 1 && (
                  <span className="text-slate-600 text-xs">→</span>
                )}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
