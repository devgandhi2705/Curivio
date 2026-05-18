import { useRef, useState, useEffect, useCallback } from "react"

// ── Icons ─────────────────────────────────────────────────────────────────────

function GlobeIcon() {
  return (
    <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
    </svg>
  )
}

function FlaskIcon() {
  return (
    <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 3h6M9 3v7l-5 9a1 1 0 0 0 .9 1.5h14.2a1 1 0 0 0 .9-1.5L15 10V3" />
    </svg>
  )
}

function LightbulbIcon() {
  return (
    <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 21h6M12 3a6 6 0 0 1 6 6c0 2.22-1.2 4.16-3 5.2V17a1 1 0 0 1-1 1H10a1 1 0 0 1-1-1v-2.8A6 6 0 0 1 6 9a6 6 0 0 1 6-6z" />
    </svg>
  )
}

function ArrowUpIcon() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 19V5M5 12l7-7 7 7" />
    </svg>
  )
}

function SpinnerIcon() {
  return (
    <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
      <circle className="opacity-20" cx="12" cy="12" r="10"
        stroke="currentColor" strokeWidth="3" />
      <path className="opacity-80" fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  )
}

// ── Sub-components ────────────────────────────────────────────────────────────

function ModeToggle({ active, onClick, disabled, icon, label, variant }) {
  const activeColors = variant === "violet"
    ? "bg-violet-950/60 border-violet-700/50 text-violet-300"
    : variant === "amber"
      ? "bg-amber-950/60 border-amber-700/50 text-amber-300"
      : "bg-blue-950/60 border-blue-700/50 text-blue-300"

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={label}
      className={`
        inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg
        text-xs font-medium border transition-colors select-none
        disabled:opacity-40 disabled:cursor-not-allowed
        ${active
          ? activeColors
          : "border-transparent text-slate-500 hover:text-slate-300 hover:bg-slate-800/40"
        }
      `}
    >
      {icon}
      <span className="hidden sm:inline">{label}</span>
    </button>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

/**
 * Props
 * ─────
 * onSend(text)        — fire when user submits a message
 * disabled            — true while AI is responding
 * chatMode            — "normal" | "web_search" | "deep_research" | "layman"
 * onModeChange(mode)  — called when user clicks a mode toggle
 * autoMode            — string | null — last backend-detected auto-mode
 */
export default function ChatInput({
  onSend,
  disabled,
  chatMode = "normal",
  onModeChange,
  autoMode,
}) {
  const textareaRef = useRef(null)

  const [hasText,   setHasText]   = useState(false)
  const [charCount, setCharCount] = useState(0)

  // ── Resize helper ─────────────────────────────────────────────────────────

  function resize(el) {
    if (!el) return
    el.style.height = "auto"
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }

  // ── Event handlers ────────────────────────────────────────────────────────

  function handleInput(e) {
    resize(e.target)
    const len = e.target.value.trim().length
    setHasText(len > 0)
    setCharCount(e.target.value.length)
  }

  function handleKeyDown(e) {
    // ⌘↵ or Ctrl+↵ → send (in addition to bare Enter)
    const cmdEnter  = (e.metaKey || e.ctrlKey) && e.key === "Enter"
    const bareEnter = e.key === "Enter" && !e.shiftKey
    if (cmdEnter || bareEnter) {
      e.preventDefault()
      submit()
    }
  }

  function submit() {
    const value = textareaRef.current?.value.trim()
    if (!value || disabled) return
    onSend(value)

    const el = textareaRef.current
    el.value = ""
    el.style.height = "auto"
    setHasText(false)
    setCharCount(0)

    // Restore focus immediately after React flushes the state update
    requestAnimationFrame(() => el?.focus())
  }

  // ── Mode toggles ──────────────────────────────────────────────────────────
  // deep_research visually activates the Web toggle too (deep ⊃ web)

  const webActive    = chatMode === "web_search" || chatMode === "deep_research"
  const deepActive   = chatMode === "deep_research"
  const laymanActive = chatMode === "layman"

  function toggleLayman() {
    if (disabled) return
    onModeChange?.(chatMode === "layman" ? "normal" : "layman")
  }
  function toggleWeb() {
    if (disabled) return
    onModeChange?.(chatMode === "web_search" ? "normal" : "web_search")
  }
  function toggleDeep() {
    if (disabled) return
    onModeChange?.(chatMode === "deep_research" ? "normal" : "deep_research")
  }

  // ── Render ────────────────────────────────────────────────────────────────

  const modeHint = chatMode === "web_search"
    ? "Live web search active"
    : chatMode === "deep_research"
      ? "Deep research + web retrieval active"
      : chatMode === "layman"
        ? "Explain Simply mode active"
        : null

  return (
    <div className="px-3 sm:px-4 pb-2 pb-safe pt-1">
      <div className="max-w-3xl mx-auto relative">

        {/* Unified input card */}
        <div
          className={`
            flex flex-col rounded-2xl border bg-slate-900
            shadow-lg shadow-black/20 transition-all duration-150
            ${disabled
              ? "border-slate-800/80"
              : "border-slate-700/60 focus-within:border-slate-600/80"
            }
          `}
        >
          {/* Textarea */}
          <textarea
            ref={textareaRef}
            rows={1}
            disabled={disabled}
            placeholder="Ask anything…"
            onKeyDown={handleKeyDown}
            onInput={handleInput}
            className="
              w-full resize-none bg-transparent
              px-4 pt-4 pb-2 text-sm text-slate-100
              placeholder-slate-600 focus:outline-none
              disabled:cursor-not-allowed leading-relaxed
            "
            style={{ minHeight: "58px" }}
          />

          {/* Footer row */}
          <div className="flex items-center justify-between px-2.5 pb-2.5 pt-1 gap-2">

            {/* Left: mode toggles — Explain Simply · Web Search · Deep Research */}
            <div className="flex items-center gap-0.5">
              <ModeToggle
                active={laymanActive}
                onClick={toggleLayman}
                disabled={disabled}
                icon={<LightbulbIcon />}
                label="Explain Simply"
                variant="amber"
              />
              <ModeToggle
                active={webActive}
                onClick={toggleWeb}
                disabled={disabled}
                icon={<GlobeIcon />}
                label="Web Search"
                variant="blue"
              />
              <ModeToggle
                active={deepActive}
                onClick={toggleDeep}
                disabled={disabled}
                icon={<FlaskIcon />}
                label="Deep Research"
                variant="violet"
              />

              {autoMode && (
                <span className="text-[10px] text-slate-600 ml-1 select-none" title={`Auto-detected: ${autoMode.replace("_", " ")}`}>
                  auto
                </span>
              )}
            </div>

            {/* Right: char count + send */}
            <div className="flex items-center gap-2 flex-shrink-0">
              {charCount > 200 && (
                <span className={`text-[10px] tabular-nums select-none ${charCount > 1000 ? "text-amber-500" : "text-slate-600"}`}>
                  {charCount}
                </span>
              )}
              <button
                type="button"
                onClick={submit}
                disabled={disabled || !hasText}
                title="Send (Enter)"
                aria-label="Send message"
                className={`
                  w-8 h-8 rounded-xl flex items-center justify-center
                  transition-all duration-150 flex-shrink-0
                  ${disabled
                    ? "bg-slate-800 text-slate-500 cursor-not-allowed"
                    : hasText
                      ? "bg-slate-100 text-slate-900 hover:bg-white shadow-sm hover:shadow-md active:scale-95"
                      : "bg-slate-800/60 text-slate-600 cursor-default"
                  }
                `}
              >
                {disabled ? <SpinnerIcon /> : <ArrowUpIcon />}
              </button>
            </div>
          </div>
        </div>

        {/* Mode hint + keyboard hint */}
        <div className="flex items-center justify-between mt-1.5 px-1">
          <span className={`text-[11px] transition-opacity duration-200 select-none ${modeHint ? "text-slate-600 opacity-100" : "opacity-0"}`}>
            {modeHint ?? "placeholder"}
          </span>
          <span className="text-[11px] text-slate-700 select-none hidden sm:block">
            ↵ send · ⇧↵ newline
          </span>
        </div>
      </div>
    </div>
  )
}
