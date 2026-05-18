export default function PerspectivesPanel({ perspectives }) {
  if (!perspectives) return null

  const { common_themes = [], synthesis, notable_tension } = perspectives

  return (
    <section>
      <p className="text-xs font-semibold uppercase tracking-widest text-slate-500 mb-3 flex items-center gap-2">
        <span>🔍</span> Multi-Source Perspectives
      </p>

      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden divide-y divide-slate-800">

        {/* Synthesis */}
        <div className="p-5">
          <p className="text-xs font-semibold text-violet-400 uppercase tracking-wide mb-2">
            Cross-source synthesis
          </p>
          <p className="text-slate-300 text-sm leading-relaxed">{synthesis}</p>
        </div>

        {/* Notable tension */}
        {notable_tension && (
          <div className="p-5">
            <p className="text-xs font-semibold text-amber-400 uppercase tracking-wide mb-2">
              Notable tension
            </p>
            <p className="text-slate-300 text-sm leading-relaxed">{notable_tension}</p>
          </div>
        )}

        {/* Common themes */}
        {common_themes.length > 0 && (
          <div className="px-5 py-4">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2.5">
              Common themes
            </p>
            <div className="flex flex-wrap gap-2">
              {common_themes.map((theme, i) => (
                <span
                  key={i}
                  className="inline-flex items-center px-2.5 py-1 bg-slate-800 border border-slate-700 rounded-full text-xs text-slate-300"
                >
                  {theme}
                </span>
              ))}
            </div>
          </div>
        )}

      </div>
    </section>
  )
}
