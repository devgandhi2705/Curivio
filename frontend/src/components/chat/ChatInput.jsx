import { useRef, useState, useEffect, useCallback } from "react"
import { uploadAttachment } from "../../api/chat.js"

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

function ThinkHarderIcon() {
  return (
    <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 20V14M12 20V8M18 20V4" />
    </svg>
  )
}

function ArrowUpIcon() {
  return (
    <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none"
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

function PaperclipIcon() {
  return (
    <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21.44 11.05l-9.19 9.19a5 5 0 0 1-7.07-7.07l9.19-9.19a3.5 3.5 0 0 1 4.95 4.95l-9.2 9.19a1.5 1.5 0 0 1-2.12-2.12l8.49-8.48" />
    </svg>
  )
}

function FileIcon() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <path d="M14 2v6h6" />
    </svg>
  )
}

function XIcon() {
  return (
    <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 6L6 18M6 6l12 12" />
    </svg>
  )
}

// ── Attachment chip ───────────────────────────────────────────────────────────

const MAX_ATTACHMENTS = 4
const ACCEPTED_TYPES = "image/png,image/jpeg,image/webp,image/gif,application/pdf"

function AttachmentChip({ attachment, onRemove }) {
  const { file, previewUrl, status, error } = attachment
  const isImage = file.type.startsWith("image/")

  return (
    <div
      className={`
        relative flex items-center gap-2 pl-1.5 pr-2 py-1.5 rounded-xl border text-xs
        ${status === "error" ? "bg-red-950/40 border-red-800/50" : "bg-white/[0.04] border-white/[0.08]"}
      `}
      title={status === "error" ? error : file.name}
    >
      {isImage && previewUrl ? (
        <img src={previewUrl} alt="" className="w-7 h-7 rounded-lg object-cover flex-shrink-0" />
      ) : (
        <span className="w-7 h-7 rounded-lg bg-white/[0.06] flex items-center justify-center flex-shrink-0 text-slate-400">
          <FileIcon />
        </span>
      )}
      <span className="max-w-[110px] truncate text-slate-300">{file.name}</span>
      {status === "uploading" && <SpinnerIcon />}
      {status === "error" && <span className="text-red-400 text-[10px]">failed</span>}
      <button
        type="button"
        onClick={() => onRemove(attachment.id)}
        className="ml-0.5 w-4 h-4 rounded-full flex items-center justify-center text-slate-500 hover:text-slate-200 hover:bg-white/[0.08] transition-colors flex-shrink-0"
        aria-label="Remove attachment"
      >
        <XIcon />
      </button>
    </div>
  )
}

// ── Sub-components ────────────────────────────────────────────────────────────

function ModeToggle({ active, onClick, disabled, icon, label, variant }) {
  const activeColors = variant === "violet"
    ? "bg-violet-950/60 border-violet-700/50 text-violet-300"
    : variant === "amber"
      ? "bg-amber-950/60 border-amber-700/50 text-amber-300"
      : variant === "emerald"
        ? "bg-emerald-950/60 border-emerald-700/50 text-emerald-300"
        : "bg-blue-950/60 border-blue-700/50 text-blue-300"

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={label}
      className={`
        inline-flex items-center gap-1 px-2 py-0.5 rounded-md
        text-xs font-medium border transition-colors select-none
        disabled:opacity-40 disabled:cursor-not-allowed
        ${active
          ? activeColors
          : "border-transparent text-slate-500 hover:text-slate-300 hover:bg-white/[0.05]"
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
 * onSend(text, attachments)  — fire when user submits a message; attachments
 *                               is [{uri, mime_type, filename, size_bytes,
 *                               expires_at, previewUrl}] or []
 * disabled            — true while AI is responding
 * chatMode            — "normal" | "web_search" | "deep_research" | "layman"
 * onModeChange(mode)  — called when user clicks a mode toggle
 * autoMode            — string | null — last backend-detected auto-mode
 * extendedThinking            — bool — "think harder" toggle state (Chat-6), off by default
 * onToggleExtendedThinking(v) — called with the new bool when the toggle is clicked
 */
export default function ChatInput({
  onSend,
  disabled,
  chatMode = "normal",
  onModeChange,
  autoMode,
  extendedThinking = false,
  onToggleExtendedThinking,
}) {
  const textareaRef = useRef(null)
  const fileInputRef = useRef(null)

  const [hasText,   setHasText]   = useState(false)
  const [charCount, setCharCount] = useState(0)
  const [attachments, setAttachments] = useState([]) // [{id, file, previewUrl, status, uploaded, error}]

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

  // ── Attachments ───────────────────────────────────────────────────────────

  function handleFilePick(e) {
    const files = Array.from(e.target.files || [])
    e.target.value = "" // allow re-picking the same file later
    const room = MAX_ATTACHMENTS - attachments.length
    for (const file of files.slice(0, room)) {
      const id = `att-${Date.now()}-${Math.random().toString(36).slice(2)}`
      const previewUrl = file.type.startsWith("image/") ? URL.createObjectURL(file) : null
      setAttachments(prev => [...prev, { id, file, previewUrl, status: "uploading", uploaded: null, error: null }])

      uploadAttachment(file)
        .then(uploaded => {
          setAttachments(prev => prev.map(a => a.id === id ? { ...a, status: "done", uploaded } : a))
        })
        .catch(err => {
          setAttachments(prev => prev.map(a => a.id === id ? { ...a, status: "error", error: err.message } : a))
        })
    }
  }

  function removeAttachment(id) {
    setAttachments(prev => {
      const target = prev.find(a => a.id === id)
      if (target?.previewUrl) URL.revokeObjectURL(target.previewUrl)
      return prev.filter(a => a.id !== id)
    })
  }

  const uploadingCount = attachments.filter(a => a.status === "uploading").length
  const readyAttachments = attachments.filter(a => a.status === "done")

  function submit() {
    const value = textareaRef.current?.value.trim() || ""
    if (disabled || uploadingCount > 0) return
    if (!value && readyAttachments.length === 0) return

    onSend(value, readyAttachments.map(a => ({ ...a.uploaded, previewUrl: a.previewUrl })))

    const el = textareaRef.current
    el.value = ""
    el.style.height = "auto"
    setHasText(false)
    setCharCount(0)
    setAttachments([])

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
  function toggleThinkHarder() {
    if (disabled) return
    onToggleExtendedThinking?.(!extendedThinking)
  }

  // ── Render ────────────────────────────────────────────────────────────────

  const modeHint = chatMode === "web_search"
    ? "Live web search active"
    : chatMode === "deep_research"
      ? "Deep research + web retrieval active"
      : chatMode === "layman"
        ? "Explain Simply mode active"
        : extendedThinking
          ? "Think Harder active — deeper reasoning"
          : null

  return (
    <div className="px-3 sm:px-4 pb-3 pb-safe pt-1">
      <div className="max-w-3xl mx-auto relative">

        {/* Unified input card */}
        <div
          className={`
            flex flex-col rounded-2xl border
            bg-white/[0.04] shadow-sm shadow-black/20
            transition-all duration-150
            ${disabled
              ? "border-white/[0.06]"
              : "border-white/[0.07] focus-within:border-white/[0.12]"
            }
          `}
        >
          {/* Attachment chips */}
          {attachments.length > 0 && (
            <div className="flex flex-wrap gap-1.5 px-3 pt-2.5">
              {attachments.map(a => (
                <AttachmentChip key={a.id} attachment={a} onRemove={removeAttachment} />
              ))}
            </div>
          )}

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
              px-4 pt-3 pb-2 text-sm text-slate-100
              placeholder-slate-500 focus:outline-none
              disabled:cursor-not-allowed leading-relaxed
            "
            style={{ minHeight: "44px" }}
          />

          {/* Footer row */}
          <div className="flex items-center justify-between px-2.5 pb-2 pt-0 gap-2">

            {/* Left: attach + mode toggles — Explain Simply · Web Search · Deep Research */}
            <div className="flex items-center gap-0.5">
              <input
                ref={fileInputRef}
                type="file"
                accept={ACCEPTED_TYPES}
                multiple
                onChange={handleFilePick}
                className="hidden"
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={disabled || attachments.length >= MAX_ATTACHMENTS}
                title="Attach image or PDF"
                aria-label="Attach image or PDF"
                className="
                  inline-flex items-center justify-center w-6 h-6 rounded-md
                  text-slate-500 hover:text-slate-300 hover:bg-white/[0.05]
                  disabled:opacity-40 disabled:cursor-not-allowed transition-colors
                "
              >
                <PaperclipIcon />
              </button>
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
              <ModeToggle
                active={extendedThinking}
                onClick={toggleThinkHarder}
                disabled={disabled}
                icon={<ThinkHarderIcon />}
                label="Think Harder"
                variant="emerald"
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
                disabled={disabled || uploadingCount > 0 || (!hasText && readyAttachments.length === 0)}
                title={uploadingCount > 0 ? "Waiting for upload to finish…" : "Send (Enter)"}
                aria-label="Send message"
                className={`
                  w-7 h-7 rounded-lg flex items-center justify-center
                  transition-all duration-150 flex-shrink-0
                  ${disabled
                    ? "bg-white/[0.05] text-slate-500 cursor-not-allowed"
                    : (hasText || readyAttachments.length > 0) && uploadingCount === 0
                      ? "bg-slate-100 text-slate-900 hover:bg-white shadow-sm active:scale-95"
                      : "bg-white/[0.05] text-slate-600 cursor-default"
                  }
                `}
              >
                {disabled || uploadingCount > 0 ? <SpinnerIcon /> : <ArrowUpIcon />}
              </button>
            </div>
          </div>
        </div>

        {/* Mode hint + keyboard hint */}
        <div className="flex items-center justify-between mt-1 px-1">
          <span className={`text-[10px] transition-opacity duration-200 select-none ${modeHint ? "text-slate-600 opacity-100" : "opacity-0"}`}>
            {modeHint ?? "placeholder"}
          </span>
          <span className="text-[10px] text-slate-700 select-none hidden sm:block">
            ↵ send · ⇧↵ newline
          </span>
        </div>
      </div>
    </div>
  )
}
