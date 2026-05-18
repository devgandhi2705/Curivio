/**
 * RepoGrid — display ranked GitHub repositories as clickable cards.
 *
 * Shows: name, description, star count, language, topic tags.
 */

const LANG_COLOR = {
  Python:     "#3B82F6",
  JavaScript: "#F59E0B",
  TypeScript: "#818CF8",
  "C++":      "#EF4444",
  Rust:       "#F97316",
  Go:         "#34D399",
  Java:       "#FB923C",
}

function StarIcon() {
  return (
    <svg className="w-3 h-3" viewBox="0 0 16 16" fill="currentColor">
      <path d="M8 .25a.75.75 0 0 1 .673.418l1.882 3.815 4.21.612a.75.75 0 0 1 .416 1.279l-3.046 2.97.719 4.192a.751.751 0 0 1-1.088.791L8 12.347l-3.766 1.98a.75.75 0 0 1-1.088-.79l.72-4.194L.818 6.374a.75.75 0 0 1 .416-1.28l4.21-.611L7.327.668A.75.75 0 0 1 8 .25Z" />
    </svg>
  )
}

function ForkIcon() {
  return (
    <svg className="w-3 h-3" viewBox="0 0 16 16" fill="currentColor">
      <path d="M5 5.372v.878c0 .414.336.75.75.75h4.5a.75.75 0 0 0 .75-.75v-.878a2.25 2.25 0 1 1 1.5 0v.878a2.25 2.25 0 0 1-2.25 2.25h-1.5v2.128a2.251 2.251 0 1 1-1.5 0V8.5h-1.5A2.25 2.25 0 0 1 3.5 6.25v-.878a2.25 2.25 0 1 1 1.5 0ZM5 3.25a.75.75 0 1 0-1.5 0 .75.75 0 0 0 1.5 0Zm6.75.75a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Zm-3 8.75a.75.75 0 1 0-1.5 0 .75.75 0 0 0 1.5 0Z" />
    </svg>
  )
}

function ExternalLinkIcon() {
  return (
    <svg className="w-3 h-3" viewBox="0 0 16 16" fill="currentColor">
      <path d="M3.75 2h3.5a.75.75 0 0 1 0 1.5h-3.5a.25.25 0 0 0-.25.25v8.5c0 .138.112.25.25.25h8.5a.25.25 0 0 0 .25-.25v-3.5a.75.75 0 0 1 1.5 0v3.5A1.75 1.75 0 0 1 12.25 14h-8.5A1.75 1.75 0 0 1 2 12.25v-8.5C2 2.784 2.784 2 3.75 2Zm6.854-1h4.146a.25.25 0 0 1 .25.25v4.146a.25.25 0 0 1-.427.177L13.03 4.03 9.28 7.78a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042l3.75-3.75-1.543-1.543A.25.25 0 0 1 10.604 1Z" />
    </svg>
  )
}

function formatStars(n) {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return n.toString()
}

function RepoCard({ repo }) {
  const langColor = LANG_COLOR[repo.language] || "#64748B"

  return (
    <a
      href={repo.url}
      target="_blank"
      rel="noopener noreferrer"
      className="group block rounded-lg bg-slate-800/60 border border-slate-700/50 p-4 hover:border-slate-600 hover:bg-slate-800 transition-colors"
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-2 mb-2">
        <span className="text-sm font-mono font-medium text-blue-400 group-hover:text-blue-300 transition-colors truncate">
          {repo.name}
        </span>
        <div className="flex items-center gap-2 shrink-0 text-slate-500">
          <span className="flex items-center gap-1 text-amber-400/80 text-xs font-medium">
            <StarIcon />
            {formatStars(repo.stars)}
          </span>
          <ExternalLinkIcon />
        </div>
      </div>

      {/* Description */}
      <p className="text-xs text-slate-400 leading-relaxed line-clamp-2 mb-3">
        {repo.description || "No description."}
      </p>

      {/* Footer */}
      <div className="flex flex-wrap items-center gap-1.5">
        {repo.language && (
          <span className="flex items-center gap-1 text-[11px] text-slate-400">
            <span
              className="w-2 h-2 rounded-full"
              style={{ backgroundColor: langColor }}
            />
            {repo.language}
          </span>
        )}
        {repo.topics?.slice(0, 3).map((t) => (
          <span
            key={t}
            className="px-1.5 py-0.5 rounded bg-slate-700/60 text-slate-500 text-[10px] font-mono"
          >
            {t}
          </span>
        ))}
      </div>
    </a>
  )
}

function SkeletonCard() {
  return (
    <div className="rounded-lg bg-slate-800/60 border border-slate-700/50 p-4 animate-pulse space-y-2">
      <div className="flex justify-between">
        <div className="h-4 w-36 rounded bg-slate-700" />
        <div className="h-4 w-12 rounded bg-slate-700" />
      </div>
      <div className="h-3 w-full rounded bg-slate-700/60" />
      <div className="h-3 w-4/5 rounded bg-slate-700/60" />
      <div className="flex gap-1.5 pt-1">
        <div className="h-3 w-12 rounded bg-slate-700/40" />
        <div className="h-3 w-10 rounded bg-slate-700/40" />
      </div>
    </div>
  )
}

export default function RepoGrid({ repos, loading }) {
  if (loading) {
    return (
      <div className="rounded-xl bg-slate-900 border border-slate-800 p-5">
        <div className="h-4 w-40 rounded bg-slate-800 animate-pulse mb-4" />
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {[1, 2, 3, 4].map((i) => <SkeletonCard key={i} />)}
        </div>
      </div>
    )
  }

  if (!repos?.length) return null

  return (
    <div className="rounded-xl bg-slate-900 border border-slate-800 p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-slate-300 tracking-wide uppercase">
          GitHub Repositories
        </h2>
        <span className="text-xs text-slate-600">{repos.length} repos</span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {repos.map((repo) => (
          <RepoCard key={repo.url} repo={repo} />
        ))}
      </div>
    </div>
  )
}
