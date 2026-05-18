const COLOR_GRAD = {
  blue:    "from-blue-500 to-blue-600",
  emerald: "from-emerald-500 to-emerald-600",
  violet:  "from-violet-500 to-violet-600",
  amber:   "from-amber-500 to-amber-600",
  rose:    "from-rose-500 to-rose-600",
}

const LEVEL_LABEL = {
  beginner:     { label: "Beginner",     color: "text-emerald-500" },
  intermediate: { label: "Intermediate", color: "text-blue-400"    },
  advanced:     { label: "Advanced",     color: "text-violet-400"  },
}

function intensityLabel(count) {
  if (!count || count <= 3) return "Light"
  if (count <= 5)           return "Standard"
  return "Intensive"
}

export default function ProjectCard({ project, progression, isActive, onSelect, onDelete, onEdit }) {
  const grad      = COLOR_GRAD[project.color] || COLOR_GRAD.blue
  const level     = progression?.current_level || project.difficulty || "beginner"
  const lvl       = LEVEL_LABEL[level] || LEVEL_LABEL.beginner
  const dayCount  = project.insight_count || 0
  const intensity = intensityLabel(project.daily_core_article_count)

  function handleDelete(e) {
    e.stopPropagation()
    onDelete?.(project.project_id)
  }

  function handleEdit(e) {
    e.stopPropagation()
    onEdit?.(project.project_id)
  }

  return (
    <div
      onClick={() => onSelect(project)}
      className={`
        group relative flex items-center gap-3 px-3 py-2.5 rounded-xl cursor-pointer transition-all select-none
        ${isActive
          ? "bg-slate-800/80 border border-slate-700/50"
          : "border border-transparent hover:bg-slate-800/40 hover:border-slate-800"
        }
      `}
    >
      {/* Color accent bar */}
      <div className={`flex-shrink-0 w-[3px] h-9 rounded-full bg-gradient-to-b ${grad} opacity-90`} />

      {/* Name + meta */}
      <div className="flex-1 min-w-0">
        <p className={`text-[13px] font-semibold leading-snug truncate ${isActive ? "text-slate-100" : "text-slate-300 group-hover:text-slate-100"}`}>
          {project.name}
        </p>
        <p className="text-[10px] mt-0.5 flex items-center gap-1.5">
          <span className={lvl.color}>{lvl.label}</span>
          <span className="text-slate-700">·</span>
          <span className="text-slate-600">Day {dayCount}</span>
          <span className="text-slate-700">·</span>
          <span className="text-slate-600">{intensity}</span>
        </p>
      </div>

      {/* Edit / Delete — appear on hover, overlay day count */}
      <div className="project-card-actions absolute right-2 top-1/2 -translate-y-1/2 hidden group-hover:flex items-center gap-0.5 bg-slate-800/90 rounded-md px-0.5 py-0.5">
        <button
          onClick={handleEdit}
          title="Edit"
          className="p-1 rounded text-slate-500 hover:text-slate-200 transition-colors"
        >
          <svg className="w-3 h-3" viewBox="0 0 16 16" fill="currentColor">
            <path d="M11.013 1.427a1.75 1.75 0 0 1 2.474 0l1.086 1.086a1.75 1.75 0 0 1 0 2.474l-8.61 8.61c-.21.21-.47.364-.756.445l-3.251.93a.75.75 0 0 1-.927-.928l.929-3.25c.081-.286.235-.547.445-.758l8.61-8.61Zm.176 4.823L9.75 4.81l-6.286 6.287a.25.25 0 0 0-.064.108l-.558 1.953 1.953-.558a.249.249 0 0 0 .108-.064Zm1.238-3.763a.25.25 0 0 0-.354 0L10.811 3.75l1.439 1.44 1.263-1.263a.25.25 0 0 0 0-.354Z" />
          </svg>
        </button>
        <button
          onClick={handleDelete}
          title="Delete"
          className="p-1 rounded text-slate-500 hover:text-red-400 transition-colors"
        >
          <svg className="w-3 h-3" viewBox="0 0 16 16" fill="currentColor">
            <path d="M11 1.75V3h2.25a.75.75 0 0 1 0 1.5H2.75a.75.75 0 0 1 0-1.5H5V1.75C5 .784 5.784 0 6.75 0h2.5C10.216 0 11 .784 11 1.75ZM4.496 6.675l.66 6.6a.25.25 0 0 0 .249.225h5.19a.25.25 0 0 0 .249-.225l.66-6.6a.75.75 0 0 1 1.492.149l-.66 6.6A1.748 1.748 0 0 1 10.595 15h-5.19a1.75 1.75 0 0 1-1.741-1.575l-.66-6.6a.75.75 0 1 1 1.492-.15ZM6.5 1.75V3h3V1.75a.25.25 0 0 0-.25-.25h-2.5a.25.25 0 0 0-.25.25Z" />
          </svg>
        </button>
      </div>
    </div>
  )
}
