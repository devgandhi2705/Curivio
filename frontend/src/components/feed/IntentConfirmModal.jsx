/**
 * IntentConfirmModal — editable intent profile review.
 *
 * mode="confirm"  post-creation: "Review & Confirm" flow
 * mode="edit"     from settings: "Edit Persona" flow
 *
 * Props:
 *   project     — project object (must include intent_profile)
 *   mode        — "confirm" | "edit"
 *   onSave(profile) — called with the edited profile object
 *   onCancel()  — close without saving
 *   saving      — boolean, true while save API call is in flight
 */
import { useState } from "react"

const LENS_OPTIONS = [
  "Educational",
  "Business Strategy",
  "Technical",
  "Policy & Regulation",
  "Investment & Markets",
  "Scientific Research",
  "Investigative",
]

function Field({ label, hint, children }) {
  return (
    <div>
      <div className="flex items-baseline gap-2 mb-1">
        <label className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">{label}</label>
        {hint && <span className="text-[10px] text-slate-600">{hint}</span>}
      </div>
      {children}
    </div>
  )
}

const INPUT_CLS = "w-full px-3 py-2 bg-slate-800 border border-slate-700/60 rounded-lg text-xs text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-blue-500/40 focus:border-blue-500/40 transition-colors"
const TEXTAREA_CLS = INPUT_CLS + " resize-none leading-relaxed"

export default function IntentConfirmModal({ project, mode = "confirm", onSave, onCancel, saving }) {
  const src = project?.intent_profile ?? {}

  const [fields, setFields] = useState({
    learning_subject: src.learning_subject || project?.name || "",
    persona:          src.persona          || "",
    goal:             src.goal             || "",
    industry_context: src.industry_context || "",
    primary_focus:    src.primary_focus    || "",
    search_lens:      src.search_lens      || "Educational",
    intent_summary:   src.intent_summary   || "",
  })

  function set(key) {
    return e => setFields(prev => ({ ...prev, [key]: e.target.value }))
  }

  function handleBackdrop(e) {
    if (e.target === e.currentTarget && !saving) onCancel()
  }

  const isConfirm = mode === "confirm"
  const hasProfile = !!project?.intent_profile

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm px-4 py-6"
      onClick={handleBackdrop}
    >
      <div className="w-full max-w-lg bg-slate-900 border border-slate-700/60 rounded-2xl shadow-2xl flex flex-col max-h-[90vh]">

        {/* Header */}
        <div className="flex items-start justify-between px-5 pt-5 pb-4 flex-shrink-0">
          <div className="flex items-start gap-3">
            <div className="w-8 h-8 rounded-xl bg-blue-950/60 border border-blue-800/40 flex items-center justify-center flex-shrink-0 mt-0.5">
              <svg className="w-3.5 h-3.5 text-blue-400" viewBox="0 0 16 16" fill="currentColor">
                <path d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0ZM1.5 8a6.5 6.5 0 1 0 13 0 6.5 6.5 0 0 0-13 0Zm4.879-2.773 4.264 2.559a.25.25 0 0 1 0 .428l-4.264 2.559A.25.25 0 0 1 6 10.559V5.442a.25.25 0 0 1 .379-.215Z" />
              </svg>
            </div>
            <div>
              <h2 className="font-semibold text-slate-100 text-sm leading-tight">
                {isConfirm ? "Review your learning persona" : "Edit learning persona"}
              </h2>
              <p className="text-[11px] text-slate-500 mt-0.5 leading-snug">
                {isConfirm
                  ? hasProfile
                    ? "AI inferred this from your project — edit any field before confirming."
                    : "Review your project before your first feed generates."
                  : "Changes take effect on the next feed generation."}
              </p>
            </div>
          </div>
          <button
            onClick={onCancel}
            disabled={saving}
            className="p-1.5 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors flex-shrink-0 disabled:opacity-40"
          >
            <svg className="w-4 h-4" viewBox="0 0 16 16" fill="currentColor">
              <path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.75.75 0 1 1 1.06 1.06L9.06 8l3.22 3.22a.75.75 0 1 1-1.06 1.06L8 9.06l-3.22 3.22a.75.75 0 0 1-1.06-1.06L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z" />
            </svg>
          </button>
        </div>

        {/* Scrollable fields */}
        <div className="overflow-y-auto flex-1 px-5 pb-2 space-y-3.5">

          <Field label="Learning Subject" hint="What is being learned — from project title">
            <input
              value={fields.learning_subject}
              onChange={set("learning_subject")}
              placeholder="e.g. AI Agents & Marketing Automation"
              className={INPUT_CLS}
            />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Persona" hint="Your role">
              <input
                value={fields.persona}
                onChange={set("persona")}
                placeholder="e.g. Pharma Marketing Lead"
                className={INPUT_CLS}
              />
            </Field>
            <Field label="Industry Context" hint="Your sector">
              <input
                value={fields.industry_context}
                onChange={set("industry_context")}
                placeholder="e.g. Pharmaceutical"
                className={INPUT_CLS}
              />
            </Field>
          </div>

          <Field label="Goal" hint="Action-oriented, what you want to achieve">
            <textarea
              value={fields.goal}
              onChange={set("goal")}
              rows={2}
              placeholder="e.g. Apply AI agent systems to automate marketing workflows for pharma products"
              className={TEXTAREA_CLS}
            />
          </Field>

          <Field label="Primary Focus" hint="Specific sub-area from the title — not your industry">
            <textarea
              value={fields.primary_focus}
              onChange={set("primary_focus")}
              rows={2}
              placeholder="e.g. Agentic marketing workflows, campaign automation, AI-driven outreach"
              className={TEXTAREA_CLS}
            />
          </Field>

          <Field label="Search Lens" hint="Editorial angle for content retrieval">
            <select
              value={fields.search_lens}
              onChange={set("search_lens")}
              className={INPUT_CLS + " cursor-pointer"}
            >
              {LENS_OPTIONS.map(l => (
                <option key={l} value={l}>{l}</option>
              ))}
            </select>
          </Field>

          <Field label="Intent Summary" hint="1–2 sentence editorial brief">
            <textarea
              value={fields.intent_summary}
              onChange={set("intent_summary")}
              rows={3}
              placeholder="e.g. A pharma marketing lead learning AI agents and automation — needs agentic systems and campaign workflow content with pharmaceutical application examples."
              className={TEXTAREA_CLS}
            />
          </Field>

          <p className="text-[10px] text-slate-600 pb-1">
            Version history is preserved — edits are additive and tracked.
          </p>
        </div>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-slate-800/60 flex gap-3 flex-shrink-0">
          <button
            type="button"
            onClick={onCancel}
            disabled={saving}
            className="flex-1 px-4 py-2.5 rounded-xl text-sm text-slate-400 hover:text-slate-200 hover:bg-slate-800 border border-slate-700/50 transition-colors disabled:opacity-40"
          >
            {isConfirm ? "Edit project settings" : "Cancel"}
          </button>
          <button
            type="button"
            onClick={() => onSave(fields)}
            disabled={saving}
            className="flex-1 px-4 py-2.5 rounded-xl text-sm font-medium bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
          >
            {saving ? (
              <>
                <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-20" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                  <path className="opacity-80" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Saving…
              </>
            ) : isConfirm ? "Confirm & Continue →" : "Save Persona"}
          </button>
        </div>
      </div>
    </div>
  )
}
