import { useState, useEffect, useRef, useCallback } from "react"
import { useTextSelection, MAX_SELECTION_LENGTH } from "../../hooks/useTextSelection.js"
import { explainStream, translateTerm, readAloudStream } from "../../api/unpack.js"
import UnpackPopover from "./UnpackPopover.jsx"
import { AnimatePresence } from "../../lib/motion.jsx"
import { useChangeCount } from "../../hooks/useChangeCount.js"
import { useHoverPill } from "../../hooks/useHoverPill.js"
import WaveDots from "../shared/WaveDots.jsx"
import { toTtsOptions } from "./voicePrefs.js"

const LANGUAGES = [
  { code: "hi", label: "Hindi" },
  { code: "gu", label: "Gujarati" },
  { code: "fr", label: "French" },
  { code: "de", label: "German" },
]

/** Text that fades in word by word. While it streams, only the words that just
 *  arrived animate: the count committed last render marks where they start. */
function Words({ text }) {
  const parts = (text || "").split(/(\s+)/)
  const committed = useRef(0)
  useEffect(() => { committed.current = parts.length })
  const start = committed.current
  return parts.map((w, i) => (!w.trim() ? w : (
    <span key={i} className="u-word" style={{ "--d": Math.min(Math.max(i - start, 0), 30) * 22 }}>{w}</span>
  )))
}

const ICON = { className: "w-3.5 h-3.5 flex-shrink-0 text-slate-400", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
  strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true }

/** The first step: items rise in turn and one highlight glides under the pointer. */
function UnpackMenu({ onExplain, onTranslate, onReadAloud }) {
  const pillRef = useHoverPill()
  const item = "w-full flex items-center gap-2 text-left px-2.5 py-1.5 rounded-md text-[12px] font-medium text-slate-200"
  return (
    <div ref={pillRef} className="u-menu relative p-1.5 flex flex-col gap-0.5">
      <span className="u-hover-pill" aria-hidden="true" />
      <button onClick={onExplain} className={item}>
        <svg {...ICON}><path d="M9 18h6" /><path d="M10 22h4" /><path d="M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.3 1 2.3h6c0-1 .4-1.8 1-2.3A7 7 0 0 0 12 2Z" /></svg>
        Explain
      </button>
      <button onClick={onTranslate} className={item}>
        <svg {...ICON}><circle cx="12" cy="12" r="10" /><path d="M2 12h20" /><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10Z" /></svg>
        Translate
      </button>
      <button onClick={onReadAloud} className={item}>
        <svg {...ICON}><path d="M11 5 6 9H2v6h4l5 4V5Z" /><path d="M15.5 8.5a5 5 0 0 1 0 7" /><path d="M19 5a10 10 0 0 1 0 14" /></svg>
        Read Aloud
      </button>
    </div>
  )
}

const LOADING = "flex items-center gap-2 text-[12px] text-slate-400"

/**
 * Mounted once near the app root. Listens for text selections anywhere on
 * the page and shows a small Explain/Translate menu — no backend call fires
 * until the user picks one of those two actions.
 */
export default function UnpackListener() {
  const { selection, clear } = useTextSelection()
  // session is a snapshot of `selection` taken when the popover opens. Once open, the
  // popover's lifetime is driven by `session`, not the live `selection` — interacting
  // with the popover itself can legitimately collapse the browser's text selection,
  // and that must not close the popover.
  const [session, setSession] = useState(null)
  const [mode, setMode] = useState("menu") // menu | language | explain | translate | audio

  // Explain state
  const [explainStatus, setExplainStatus] = useState("idle") // idle | loading | done | error
  const [explainResult, setExplainResult] = useState(null)
  const [meaning, setMeaning] = useState("")
  const [explainError, setExplainError] = useState("")

  // Translate state
  const [translateStatus, setTranslateStatus] = useState("idle") // idle | loading | done | error
  const [translation, setTranslation] = useState(null)
  const [translateError, setTranslateError] = useState("")

  // Read Aloud state
  const [audioStatus, setAudioStatus] = useState("idle") // idle | loading | done | error
  const [audioResult, setAudioResult] = useState(null)
  const [audioError, setAudioError] = useState("")
  const [playing, setPlaying] = useState(false)
  // Each step slides in: forward into an option, back when returning to the menu.
  const stepChanges = useChangeCount(mode)

  const abortRef = useRef(null)
  // The live audio download: cancel stops it and frees its URL. readSeqRef
  // drops a stream that only starts after the user has already moved on.
  const audioCancelRef = useRef(null)
  const readSeqRef = useRef(0)
  const stopAudio = () => {
    readSeqRef.current++
    audioCancelRef.current?.()
    audioCancelRef.current = null
  }
  useEffect(() => stopAudio, [])
  const dismissedKeyRef = useRef("")
  // Mirrors the currently open session's identity. Clicking anything inside the
  // popover (Explain, Translate, a language button, Close) can collapse the live
  // browser selection; useTextSelection's deferred mouseup/selectionchange read
  // then re-fires with that *same* selection after our onClick already ran. This
  // ref lets the "open a session" effect recognize and ignore that stray echo
  // instead of treating it as a new selection and resetting mode back to "menu".
  const sessionKeyRef = useRef("")

  const resetResultState = () => {
    setExplainStatus("idle")
    setExplainResult(null)
    setMeaning("")
    setExplainError("")
    setTranslateStatus("idle")
    setTranslation(null)
    setTranslateError("")
    stopAudio()
    setAudioStatus("idle")
    setAudioResult(null)
    setAudioError("")
    setPlaying(false)
  }

  const dismiss = useCallback(() => {
    abortRef.current?.()
    abortRef.current = null
    dismissedKeyRef.current = session ? `${session.text}|${session.sentence}` : ""
    sessionKeyRef.current = ""
    window.getSelection()?.removeAllRanges()
    clear()
    setSession(null)
    setMode("menu")
    resetResultState()
  }, [clear, session])

  // Open a new session whenever a genuinely new text selection appears.
  useEffect(() => {
    if (!selection) return
    const selKey = `${selection.text}|${selection.sentence}`
    // Stray echo of the session that's already open (e.g. clicking Explain/
    // Translate/a language button collapsed the selection, and the deferred
    // read fired after our click handler already switched modes) — ignore.
    if (selKey === sessionKeyRef.current) return
    // One-shot: swallow only the single stray echo that can follow a close click,
    // then stop suppressing so a genuine future reselection (even of the same text)
    // works normally.
    if (selKey === dismissedKeyRef.current) {
      dismissedKeyRef.current = ""
      return
    }
    sessionKeyRef.current = selKey
    setSession(selection)
    setMode("menu")
    resetResultState()
  }, [selection])

  function handleExplain() {
    setMode("explain")
    if (!session) return
    abortRef.current?.()
    setExplainStatus("loading")
    setExplainResult(null)
    setMeaning("")
    setExplainError("")

    abortRef.current = explainStream(
      {
        term: session.text,
        sentence: session.sentence,
        prevSentence: session.prevSentence,
        nextSentence: session.nextSentence,
      },
      {
        onChunk: (v) => setMeaning((m) => m + v),
        onDone: (obj) => {
          setExplainResult(obj)
          setExplainStatus("done")
        },
        onError: (msg) => {
          setExplainError(msg)
          setExplainStatus("error")
        },
      }
    )
  }

  function goBack() {
    abortRef.current?.()
    abortRef.current = null
    stopAudio()
    setMode("menu")
  }

  function handleTranslateMenu() {
    setMode("language")
  }

  async function handleTranslate(langCode) {
    setMode("translate")
    if (!session) return
    setTranslateStatus("loading")
    setTranslation(null)
    setTranslateError("")

    try {
      const result = await translateTerm(session.text, langCode)
      setTranslation(result)
      setTranslateStatus("done")
    } catch (err) {
      setTranslateError(err.message || "Could not load translation.")
      setTranslateStatus("error")
    }
  }

  async function handleReadAloud() {
    setMode("audio")
    if (!session) return
    stopAudio()
    const seq = readSeqRef.current
    setAudioStatus("loading")
    setAudioResult(null)
    setAudioError("")

    try {
      const result = await readAloudStream(session.text, toTtsOptions())
      if (seq !== readSeqRef.current) { result.cancel(); return }
      audioCancelRef.current = result.cancel
      setAudioResult(result)
      setAudioStatus("done")
    } catch (err) {
      if (seq !== readSeqRef.current) return
      setAudioError(err.message || "Could not load audio.")
      setAudioStatus("error")
    }
  }

  useEffect(() => {
    if (!session) return
    function onScroll() {
      dismiss()
    }
    window.addEventListener("scroll", onScroll, true)
    return () => window.removeEventListener("scroll", onScroll, true)
  }, [session, dismiss])

  const stepClass = stepChanges ? (mode === "menu" ? "u-step-back" : "u-step-fwd") : ""

  return (
    <AnimatePresence>
    {session && (
    <UnpackPopover key={sessionKeyRef.current} rect={session.rect} onClose={dismiss} onBack={mode === "menu" ? null : goBack}>
      <div key={mode} className={stepClass}>
      {mode === "menu" && session.tooLong && (
        <p className="px-3 py-2 text-xs text-slate-400">
          That's {session.text.length.toLocaleString()} characters. Select up to {MAX_SELECTION_LENGTH.toLocaleString()} to explain, translate or read aloud.
        </p>
      )}

      {mode === "menu" && !session.tooLong && (
        <UnpackMenu onExplain={handleExplain} onTranslate={handleTranslateMenu} onReadAloud={handleReadAloud} />
      )}

      {mode === "language" && (
        <div className="p-1.5">
          <select
            autoFocus
            defaultValue=""
            onChange={(e) => e.target.value && handleTranslate(e.target.value)}
            className="w-full bg-slate-800 border border-slate-700/60 rounded-md text-[12px] text-slate-200 px-2 py-1.5 focus:outline-none focus:border-blue-500"
          >
            <option value="" disabled>Select language…</option>
            {LANGUAGES.map((l) => (
              <option key={l.code} value={l.code}>
                {l.label}
              </option>
            ))}
          </select>
        </div>
      )}

      {mode === "explain" && (
        <div className="px-3 py-2 space-y-2 max-h-72 overflow-y-auto">
          {explainStatus === "loading" && !meaning && !explainResult ? (
            <p className={LOADING}><WaveDots className="text-blue-300" />Thinking…</p>
          ) : explainStatus === "error" && !explainResult ? (
            <p className="text-xs text-red-400">{explainError || "Could not load explanation."}</p>
          ) : (
            <div className="u-rise space-y-2">
              {explainResult?.definition_general && (
                <p className="text-[13px] text-slate-300 leading-relaxed">
                  <Words text={explainResult.definition_general} />
                </p>
              )}

              {(meaning || explainStatus === "loading") && (
                <div>
                  {explainResult?.confidence === "low" && (
                    <span className="inline-block mb-1 text-[9px] font-medium px-1.5 py-0.5 rounded-full bg-amber-500/15 text-amber-400">
                      uncertain
                    </span>
                  )}
                  <p className="text-[13px] text-slate-100 leading-relaxed font-medium">
                    <Words text={explainResult?.meaning_in_context ?? meaning} />
                    {explainStatus === "loading" && !explainResult && (
                      <span className="inline-block w-1 h-3 ml-0.5 bg-blue-400 animate-pulse align-middle" />
                    )}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {mode === "translate" && (
        <div className="px-3 py-2 max-h-72 overflow-y-auto">
          {translateStatus === "loading" ? (
            <p className={LOADING}><WaveDots className="text-blue-300" />Translating…</p>
          ) : translateStatus === "error" ? (
            <p className="text-xs text-red-400">{translateError || "Could not load translation."}</p>
          ) : (
            <p className="text-[15px] text-slate-100 leading-relaxed font-medium">
              <Words text={translation?.translation} />
            </p>
          )}
        </div>
      )}

      {mode === "audio" && (
        <div className="px-3 py-2">
          {audioStatus === "loading" ? (
            <p className={LOADING}><WaveDots className="text-blue-300" />Preparing audio…</p>
          ) : audioStatus === "error" ? (
            <p className="text-xs text-red-400">{audioError || "Could not load audio."}</p>
          ) : (
            audioResult?.src && (
              <div className="flex items-center gap-2">
                <audio
                  controls
                  autoPlay
                  onPlay={() => setPlaying(true)}
                  onPause={() => setPlaying(false)}
                  onEnded={() => setPlaying(false)}
                  className="w-full h-8 min-w-0"
                  src={audioResult.src}
                />
                {playing && <span className="u-eq text-blue-300" aria-hidden="true"><i /><i /><i /><i /></span>}
              </div>
            )
          )}
        </div>
      )}
      </div>
    </UnpackPopover>
    )}
    </AnimatePresence>
  )
}
