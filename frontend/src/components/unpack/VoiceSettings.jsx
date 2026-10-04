/**
 * Settings → Read Aloud: pick any Deepgram Flux voice (fetched live), a speed
 * and an expressivity. Format, bit rate and the training opt-out are fixed by
 * the backend. Changes save instantly, like Appearance.
 */
import { useEffect, useMemo, useRef, useState } from "react"
import { listVoices, readAloudStream } from "../../api/unpack.js"
import WaveDots from "../shared/WaveDots.jsx"
import { SPEED_RANGE, loadVoicePrefs, saveVoicePrefs, toTtsOptions } from "./voicePrefs.js"

const TEST_LINE = "This is how Read Aloud will sound when you select text in a lesson."
const EXPRESSIVITY = { "-2": "Very calm", "-1": "Calm", "0": "Neutral", "1": "Animated", "2": "Very animated" }

let langNames
function languageLabel(code) {
  try { langNames ??= new Intl.DisplayNames(["en"], { type: "language" }); return langNames.of(code) } catch { return code }
}

function gender(v) {
  return v.tags.includes("feminine") ? "Feminine" : v.tags.includes("masculine") ? "Masculine" : ""
}

const selectCls = "w-full bg-slate-950 border border-slate-700 rounded-lg px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-blue-500"
const label = "flex justify-between text-[11px] font-medium text-slate-400 mb-1"
const slider = "w-full accent-blue-500 cursor-pointer"
const note = "text-[11px] text-slate-500 leading-snug mt-1"

function PlayIcon({ playing }) {
  return playing
    ? <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><rect x="4" y="4" width="8" height="8" rx="1" /></svg>
    : <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M5 3.5v9l7.5-4.5L5 3.5Z" /></svg>
}

export default function VoiceSettings({ inputCls }) {
  const [prefs, setPrefs] = useState(loadVoicePrefs)
  function set(patch) {
    const next = { ...prefs, ...patch }
    setPrefs(next); saveVoicePrefs(next)
  }
  const opts = toTtsOptions(prefs)
  const model = opts.model

  const [voices, setVoices] = useState(null)
  const [loadErr, setLoadErr] = useState("")
  useEffect(() => {
    listVoices().then(d => setVoices(d.voices)).catch(e => setLoadErr(e.message || "Could not load voices."))
  }, [])

  // One player for samples and the test line: starting one stops the other.
  const audioRef = useRef(null)
  const [playing, setPlaying] = useState(null)
  useEffect(() => () => audioRef.current?.pause(), [])
  // Cancels the test clip's download, if one is streaming.
  const testCancelRef = useRef(null)
  useEffect(() => () => testCancelRef.current?.(), [])
  function stop() {
    audioRef.current?.pause(); setPlaying(null)
    testCancelRef.current?.(); testCancelRef.current = null
  }
  function play(id, src) {
    audioRef.current?.pause()
    const a = new Audio(src)
    audioRef.current = a
    a.onended = () => setPlaying(p => (p === id ? null : p))
    a.onerror = () => { setPlaying(p => (p === id ? null : p)); if (id === "test") setTestErr("Could not play the test.") }
    a.play().catch(() => {})
    setPlaying(id)
  }

  const [q, setQ] = useState("")
  const [lang, setLang] = useState("")
  const [sex, setSex] = useState("")

  const languages = useMemo(
    () => [...new Set((voices || []).map(v => v.language))].sort((a, b) => languageLabel(a).localeCompare(languageLabel(b))),
    [voices],
  )
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return (voices || []).filter(v =>
      (!lang || v.language === lang) && (!sex || gender(v) === sex) &&
      (!needle || [v.name, v.accent, ...v.tags, ...v.use_cases].join(" ").toLowerCase().includes(needle)))
  }, [voices, q, lang, sex])
  const current = voices?.find(v => v.model === model)

  const [testing, setTesting] = useState(false)
  const [testErr, setTestErr] = useState("")
  const [usedBackup, setUsedBackup] = useState(false)
  async function test() {
    setTesting(true); setTestErr(""); setUsedBackup(false); stop()
    try {
      const r = await readAloudStream(TEST_LINE, toTtsOptions(prefs))
      testCancelRef.current = r.cancel
      setUsedBackup(r.source === "deepgram_tts_fallback")
      play("test", r.src)
    } catch (e) {
      setTestErr(e.message || "Could not play the test.")
    } finally {
      setTesting(false)
    }
  }


  return (
    <div className="max-h-[min(72vh,620px)] overflow-y-auto px-4 py-3 space-y-4">
      {/* Voice */}
      <section>
        <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-600 mb-1.5">Voice</p>
        <p className="text-xs text-slate-300 mb-2">
          <span className="font-medium text-slate-100">{current?.name || model}</span>
          {current && <span className="text-slate-500"> · {languageLabel(current.language)}</span>}
        </p>

        <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search name, accent, style…"
          aria-label="Search voices" className={inputCls + " !py-1.5 text-xs mb-1.5"} />
        <div className="grid grid-cols-2 gap-1.5 mb-1.5">
          <select value={lang} onChange={e => setLang(e.target.value)} aria-label="Language" className={selectCls}>
            <option value="">All languages</option>
            {languages.map(l => <option key={l} value={l}>{languageLabel(l)}</option>)}
          </select>
          <select value={sex} onChange={e => setSex(e.target.value)} aria-label="Voice gender" className={selectCls}>
            <option value="">Any voice</option>
            <option value="Feminine">Feminine</option>
            <option value="Masculine">Masculine</option>
          </select>
        </div>

        <div role="radiogroup" aria-label="Voices" className="max-h-52 overflow-y-auto rounded-lg border border-slate-800 divide-y divide-slate-800/60">
          {!voices && !loadErr && <p className="flex items-center gap-2 px-2.5 py-2 text-xs text-slate-400"><WaveDots className="text-blue-300" />Loading voices…</p>}
          {loadErr && <p className="px-2.5 py-2 text-xs text-red-400">{loadErr}</p>}
          {voices && !shown.length && <p className="px-2.5 py-2 text-xs text-slate-500">No voices match.</p>}
          {shown.map(v => {
            const selected = v.model === model
            return (
              <div key={v.model} className={`flex items-center gap-1 pr-1 ${selected ? "bg-blue-600/15" : "hover:bg-slate-800/50"}`}>
                <button type="button" role="radio" aria-checked={selected} onClick={() => set({ model: v.model })}
                  title={[...v.tags, ...v.use_cases].join(", ")}
                  className="flex-1 min-w-0 text-left px-2.5 py-1.5">
                  <span className={`block text-xs font-medium truncate ${selected ? "text-blue-300" : "text-slate-200"}`}>
                    {v.name}{selected && " ✓"}
                  </span>
                  <span className="block text-[10.5px] text-slate-500 truncate">
                    {[v.accent || languageLabel(v.language), gender(v)].filter(Boolean).join(" · ")}
                  </span>
                </button>
                {v.sample && (
                  <button type="button" onClick={() => (playing === v.model ? stop() : play(v.model, v.sample))}
                    aria-label={`${playing === v.model ? "Stop" : "Play"} ${v.name} sample`}
                    className="w-7 h-7 grid place-items-center rounded-md text-slate-400 hover:text-slate-100 hover:bg-slate-700/60 flex-shrink-0">
                    <PlayIcon playing={playing === v.model} />
                  </button>
                )}
              </div>
            )
          })}
        </div>
        {voices && <p className={note}>{shown.length} of {voices.length} voices</p>}
      </section>

      <section className="space-y-3">
        <div>
          <label htmlFor="tts-speed" className={label}>
            Speed <span className="tabular-nums text-slate-300">{(opts.speed ?? 1).toFixed(2)}×</span>
          </label>
          <input id="tts-speed" type="range" min={SPEED_RANGE[0]} max={SPEED_RANGE[1]} step="0.05" value={opts.speed ?? 1}
            onChange={e => set({ speed: Number(e.target.value) })} className={slider} />
        </div>
        <div>
          <label htmlFor="tts-expr" className={label}>
            Expressivity <span className="text-slate-300">{EXPRESSIVITY[opts.expressivity ?? 0]}</span>
          </label>
          <input id="tts-expr" type="range" min="-2" max="2" step="1" value={opts.expressivity ?? 0}
            onChange={e => set({ expressivity: Number(e.target.value) })} className={slider} />
        </div>
      </section>

      <div className="space-y-2 pb-1">
        <button type="button" onClick={playing === "test" ? stop : test} disabled={testing}
          className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-sm font-medium py-2 rounded-lg transition-colors">
          {testing ? <><WaveDots />Preparing…</> : playing === "test" ? "Stop" : "Try these settings"}
        </button>
        {testErr && <p className="text-xs text-red-400">{testErr}</p>}
        {usedBackup && <p className="text-xs text-amber-400">Flux couldn't speak just now, so you heard the backup voice (Aura-2 Thalia).</p>}
        <button type="button" onClick={() => { stop(); setTestErr(""); setPrefs({}); saveVoicePrefs({}) }}
          className="w-full text-center text-xs text-slate-500 hover:text-slate-300 transition-colors">
          Reset to default voice
        </button>
      </div>
    </div>
  )
}
