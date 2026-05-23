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

export default function ProjectCard({ project, progression, isActive, onSelect }) {
  const grad      = COLOR_GRAD[project.color] || COLOR_GRAD.blue
  const level     = progression?.current_level || project.difficulty || "beginner"
  const lvl       = LEVEL_LABEL[level] || LEVEL_LABEL.beginner
  const intensity = intensityLabel(project.daily_core_article_count)

  return (
    <div
      onClick={() => onSelect(project)}
      className={`
        group relative flex items-center gap-2.5 px-3 py-2 rounded-xl cursor-pointer transition-colors select-none
        ${isActive ? "bg-white/[0.07]" : "hover:bg-white/[0.04]"}
      `}
    >
      <div className={`flex-shrink-0 w-[3px] h-7 rounded-full bg-gradient-to-b ${grad} opacity-90`} />
      <div className="flex-1 min-w-0">
        <p className={`text-[13px] font-medium leading-snug truncate ${isActive ? "text-white" : "text-slate-300 group-hover:text-white"}`}>
          {project.name}
        </p>
        <p className="text-[10px] flex items-center gap-1.5">
          <span className={lvl.color}>{lvl.label}</span>
          <span className="text-slate-600">·</span>
          <span className="text-slate-500">{intensity}</span>
        </p>
      </div>
    </div>
  )
}
