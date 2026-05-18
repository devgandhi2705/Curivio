/**
 * ResourceCatalog — groups categorized resources by type.
 *
 * Categories: tutorial, research_paper, github_repository,
 *             documentation, blog_post, video
 *
 * Resources are clickable when they contain a URL.
 */

const CATEGORY_META = {
  documentation: {
    label:   "Documentation",
    color:   "text-blue-400",
    bg:      "bg-blue-500/8",
    border:  "border-blue-500/15",
    badge:   "bg-blue-500/15 text-blue-300",
    dot:     "bg-blue-400",
    order:   1,
  },
  tutorial: {
    label:   "Tutorials & Courses",
    color:   "text-emerald-400",
    bg:      "bg-emerald-500/8",
    border:  "border-emerald-500/15",
    badge:   "bg-emerald-500/15 text-emerald-300",
    dot:     "bg-emerald-400",
    order:   2,
  },
  research_paper: {
    label:   "Research Papers",
    color:   "text-amber-400",
    bg:      "bg-amber-500/8",
    border:  "border-amber-500/15",
    badge:   "bg-amber-500/15 text-amber-300",
    dot:     "bg-amber-400",
    order:   3,
  },
  github_repository: {
    label:   "Repositories",
    color:   "text-slate-300",
    bg:      "bg-slate-700/20",
    border:  "border-slate-700/40",
    badge:   "bg-slate-700/40 text-slate-300",
    dot:     "bg-slate-400",
    order:   4,
  },
  blog_post: {
    label:   "Blog Posts",
    color:   "text-violet-400",
    bg:      "bg-violet-500/8",
    border:  "border-violet-500/15",
    badge:   "bg-violet-500/15 text-violet-300",
    dot:     "bg-violet-400",
    order:   5,
  },
  video: {
    label:   "Videos",
    color:   "text-red-400",
    bg:      "bg-red-500/8",
    border:  "border-red-500/15",
    badge:   "bg-red-500/15 text-red-300",
    dot:     "bg-red-400",
    order:   6,
  },
}

const URL_RE = /https?:\/\/[^\s]+/

function parseResource(resource) {
  const urlMatch = resource.match(URL_RE)
  const url = urlMatch ? urlMatch[0] : null

  // Strip prefix like "Docs: ", "Paper: ", etc.
  const prefixMatch = resource.match(/^([A-Za-z ]+):\s*/)
  const label = prefixMatch
    ? resource.slice(prefixMatch[0].length)
    : resource

  return { url, label: label.trim() }
}

function ResourceItem({ item, dotColor }) {
  const { url, label } = parseResource(item.resource)

  const inner = (
    <div className="flex items-start gap-2 py-1.5">
      <span className={`mt-1.5 shrink-0 w-1.5 h-1.5 rounded-full ${dotColor}`} />
      <span className="text-xs text-slate-400 leading-relaxed break-all">{label}</span>
    </div>
  )

  if (url) {
    return (
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="block hover:text-slate-200 group transition-colors"
        title={label}
      >
        <div className="flex items-start gap-2 py-1.5">
          <span className={`mt-1.5 shrink-0 w-1.5 h-1.5 rounded-full ${dotColor}`} />
          <span className="text-xs text-slate-400 group-hover:text-slate-300 leading-relaxed break-all transition-colors">
            {label}
          </span>
        </div>
      </a>
    )
  }

  return inner
}

function CategorySection({ category, items }) {
  const meta = CATEGORY_META[category] || {
    label: category, color: "text-slate-400", bg: "bg-slate-800",
    border: "border-slate-700", badge: "bg-slate-700 text-slate-300",
    dot: "bg-slate-400",
  }

  return (
    <div className={`rounded-lg border p-3 ${meta.bg} ${meta.border}`}>
      <div className="flex items-center justify-between mb-1">
        <span className={`text-xs font-semibold ${meta.color}`}>{meta.label}</span>
        <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${meta.badge}`}>
          {items.length}
        </span>
      </div>
      <div className="divide-y divide-slate-800/60">
        {items.map((item, i) => (
          <ResourceItem key={i} item={item} dotColor={meta.dot} />
        ))}
      </div>
    </div>
  )
}

function SkeletonSection() {
  return (
    <div className="rounded-lg border border-slate-800 p-3 animate-pulse space-y-2">
      <div className="flex justify-between">
        <div className="h-3 w-24 rounded bg-slate-800" />
        <div className="h-3 w-6 rounded bg-slate-800" />
      </div>
      {[1, 2, 3].map((i) => (
        <div key={i} className="flex gap-2">
          <div className="w-1.5 h-1.5 rounded-full bg-slate-700 mt-1 shrink-0" />
          <div className="h-3 rounded bg-slate-800/60" style={{ width: `${60 + i * 10}%` }} />
        </div>
      ))}
    </div>
  )
}

export default function ResourceCatalog({ data, loading }) {
  if (loading) {
    return (
      <div className="rounded-xl bg-slate-900 border border-slate-800 p-5">
        <div className="h-4 w-40 rounded bg-slate-800 animate-pulse mb-4" />
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {[1, 2, 3, 4].map((i) => <SkeletonSection key={i} />)}
        </div>
      </div>
    )
  }

  if (!data?.results?.length) return null

  // Group results by category
  const grouped = {}
  for (const item of data.results) {
    if (!grouped[item.category]) grouped[item.category] = []
    grouped[item.category].push(item)
  }

  // Sort categories by predefined order
  const sortedCategories = Object.keys(grouped).sort(
    (a, b) =>
      (CATEGORY_META[a]?.order ?? 99) - (CATEGORY_META[b]?.order ?? 99)
  )

  const totalCount = data.results.length

  return (
    <div className="rounded-xl bg-slate-900 border border-slate-800 p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-slate-300 tracking-wide uppercase">
          Categorized Resources
        </h2>
        <span className="text-xs text-slate-600">{totalCount} resources</span>
      </div>

      {/* Summary pills */}
      <div className="flex flex-wrap gap-1.5 mb-4">
        {sortedCategories.map((cat) => {
          const meta = CATEGORY_META[cat]
          return (
            <span
              key={cat}
              className={`px-2 py-0.5 rounded-full text-[11px] font-medium border ${
                meta?.badge ?? "bg-slate-700 text-slate-300"
              } ${meta?.border ?? ""}`}
            >
              {meta?.label ?? cat} · {grouped[cat].length}
            </span>
          )
        })}
      </div>

      {/* Category sections */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {sortedCategories.map((cat) => (
          <CategorySection key={cat} category={cat} items={grouped[cat]} />
        ))}
      </div>
    </div>
  )
}
