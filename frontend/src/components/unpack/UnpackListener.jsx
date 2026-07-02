import { useState, useEffect, useRef, useCallback } from "react"
import { useTextSelection } from "../../hooks/useTextSelection.js"
import { explainStream, translateTerm, readAloudTerm } from "../../api/unpack.js"
import UnpackPopover from "./UnpackPopover.jsx"

const LANGUAGES = [
  { code: "hi", label: "Hindi" },
  { code: "gu", label: "Gujarati" },
  { code: "fr", label: "French" },
  { code: "de", label: "German" },
]

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

  const abortRef = useRef(null)
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
    setAudioStatus("idle")
    setAudioResult(null)
    setAudioError("")
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
    setAudioStatus("loading")
    setAudioResult(null)
    setAudioError("")

    try {
      const result = await readAloudTerm(session.text)
      setAudioResult(result)
      setAudioStatus("done")
    } catch (err) {
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

  if (!session) return null

  return (
    <UnpackPopover rect={session.rect} onClose={dismiss}>
      {mode === "menu" && (
        <div className="p-1.5 flex flex-col gap-1">
          <button
            onClick={handleExplain}
            className="w-full text-left px-2.5 py-1.5 rounded-md text-[12px] font-medium text-slate-200 bg-slate-800 hover:bg-slate-700 transition-colors"
          >
            Explain
          </button>
          <button
            onClick={handleTranslateMenu}
            className="w-full text-left px-2.5 py-1.5 rounded-md text-[12px] font-medium text-slate-200 bg-slate-800 hover:bg-slate-700 transition-colors"
          >
            Translate
          </button>
          <button
            onClick={handleReadAloud}
            className="w-full text-left px-2.5 py-1.5 rounded-md text-[12px] font-medium text-slate-200 bg-slate-800 hover:bg-slate-700 transition-colors"
          >
            Read Aloud
          </button>
        </div>
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
            <div className="space-y-1.5 animate-pulse">
              <div className="h-2.5 bg-slate-800 rounded w-3/4" />
              <div className="h-2.5 bg-slate-800 rounded w-full" />
              <div className="h-2.5 bg-slate-800 rounded w-5/6" />
            </div>
          ) : explainStatus === "error" && !explainResult ? (
            <p className="text-xs text-red-400">{explainError || "Could not load explanation."}</p>
          ) : (
            <>
              {explainResult?.definition_general && (
                <p className="text-[13px] text-slate-300 leading-relaxed">
                  {explainResult.definition_general}
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
                    {explainResult?.meaning_in_context ?? meaning}
                    {explainStatus === "loading" && !explainResult && (
                      <span className="inline-block w-1 h-3 ml-0.5 bg-blue-400 animate-pulse align-middle" />
                    )}
                  </p>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {mode === "translate" && (
        <div className="px-3 py-2 max-h-72 overflow-y-auto">
          {translateStatus === "loading" ? (
            <div className="h-2.5 bg-slate-800 rounded w-2/3 animate-pulse" />
          ) : translateStatus === "error" ? (
            <p className="text-xs text-red-400">{translateError || "Could not load translation."}</p>
          ) : (
            <p className="text-[15px] text-slate-100 leading-relaxed font-medium">
              {translation?.translation}
            </p>
          )}
        </div>
      )}

      {mode === "audio" && (
        <div className="px-3 py-2">
          {audioStatus === "loading" ? (
            <div className="h-2.5 bg-slate-800 rounded w-2/3 animate-pulse" />
          ) : audioStatus === "error" ? (
            <p className="text-xs text-red-400">{audioError || "Could not load audio."}</p>
          ) : (
            audioResult?.audio_base64 && (
              <audio
                controls
                autoPlay
                className="w-full h-8"
                src={`data:audio/mp3;base64,${audioResult.audio_base64}`}
              />
            )
          )}
        </div>
      )}
    </UnpackPopover>
  )
}
