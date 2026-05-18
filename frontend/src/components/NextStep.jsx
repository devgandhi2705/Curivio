export default function NextStep({ text }) {
  return (
    <section>
      <p className="text-xs font-semibold uppercase tracking-widest text-slate-500 mb-3 flex items-center gap-2">
        <span>🚀</span> Your Next Move
      </p>
      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
        <div className="border-l-4 border-emerald-500 p-6">
          <p className="text-slate-200 text-sm leading-relaxed">{text}</p>
        </div>
      </div>
    </section>
  )
}
