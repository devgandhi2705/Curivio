/**
 * ReaderSettings — the Aa panel inside Reading mode. Every change applies
 * live and is saved by the parent; nothing here touches the normal feed.
 *
 * Numbers use a Word-style box: type any value, or pick one from its list.
 * The font list is the whole Google Fonts catalogue (googleFonts.json),
 * loaded the first time the font dropdown opens.
 */
import { useEffect, useMemo, useRef, useState } from "react"
import { m, presets, useIsPhone } from "../../../lib/motion.jsx"
import { THEMES, PRESETS, DEFAULTS, RANGE, SYSTEM_FONTS, CATEGORY_LABEL, ensureFont, fontStack } from "./readerPrefs.js"

const SECTION_IDS = ["presets", "theme", "layout", "text", "spacing", "slides"]
const SECTION_STATE_KEY = "curivio.reader-settings-sections.v1"

const SIZE_OPTIONS  = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 22, 24, 26, 28, 32, 36, 40, 48]
const LINE_OPTIONS  = [1, 1.15, 1.3, 1.5, 1.6, 1.7, 1.8, 2, 2.2, 2.5, 3]
const TRACK_OPTIONS = [-0.05, -0.02, 0, 0.01, 0.02, 0.03, 0.05, 0.08, 0.1, 0.15, 0.2]
const WORD_OPTIONS  = [0, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.6]
const BLOCK_OPTIONS = [0, 0.25, 0.5, 0.75, 1, 1.25, 1.5, 2]
const DIM_OPTIONS   = [100, 95, 90, 85, 80, 75, 70, 60, 50, 40]
const SPEED_OPTIONS = [0.5, 0.75, 1, 1.25, 1.5, 2]

function loadOpenSections(userKey) {
  try {
    const saved = JSON.parse(localStorage.getItem(`${SECTION_STATE_KEY}.${userKey}`))
    if (!saved || typeof saved !== "object") return Object.fromEntries(SECTION_IDS.map(id => [id, true]))
    return Object.fromEntries(SECTION_IDS.map(id => [id, typeof saved[id] === "boolean" ? saved[id] : true]))
  } catch {
    return Object.fromEntries(SECTION_IDS.map(id => [id, true]))
  }
}

function Chevron({ open, className = "w-3 h-3" }) {
  return (
    <svg className={`${className} transition-transform ${open ? "rotate-180" : ""}`} viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
      <path fillRule="evenodd" d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z" clipRule="evenodd" />
    </svg>
  )
}

/** Calls `close` on a press outside `ref` while `open`. */
function useOutside(ref, open, close) {
  useEffect(() => {
    if (!open) return
    const onDown = e => { if (!ref.current?.contains(e.target)) close() }
    document.addEventListener("mousedown", onDown)
    return () => document.removeEventListener("mousedown", onDown)
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps
}

function Section({ id, title, open, onToggle, children }) {
  return (
    <section className="px-5 py-4 border-t border-slate-800 first:border-t-0">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={`reader-settings-${id}`}
        onClick={onToggle}
        className="w-full flex items-center justify-between text-left"
      >
        <span className="u-read-label text-slate-500">{title}</span>
        <Chevron open={open} className="w-3.5 h-3.5 text-slate-500" />
      </button>
      {open && <div id={`reader-settings-${id}`} className="space-y-3.5 mt-3">{children}</div>}
    </section>
  )
}

// Word-style number box: an editable value plus a list of common ones.
// ↑/↓ step through the list; Enter or leaving the box applies a typed value.
function NumberCombo({ id, label, value, options, min, max, unit = "", decimals = 0, onChange }) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(null)
  const ref = useRef(null)
  useOutside(ref, open, () => setOpen(false))

  const fmt = v => String(decimals ? Number(v.toFixed(decimals)) : Math.round(v))
  const apply = v => onChange(Math.min(max, Math.max(min, v)))

  function commit() {
    if (draft == null) return
    const v = parseFloat(draft.replace(",", "."))
    if (Number.isFinite(v)) apply(v)
    setDraft(null)
  }
  function step(dir) {
    const sorted = [...options].sort((a, b) => a - b)
    const next = dir > 0 ? sorted.find(o => o > value + 1e-9) : sorted.reverse().find(o => o < value - 1e-9)
    if (next != null) apply(next)
  }
  function onKeyDown(e) {
    if (e.key === "Enter") { commit(); setOpen(false) }
    else if (e.key === "ArrowUp") { e.preventDefault(); setDraft(null); step(1) }
    else if (e.key === "ArrowDown") { e.preventDefault(); setDraft(null); step(-1) }
    else if (e.key === "Escape" && (open || draft != null)) {
      // Close the list (or drop the edit) without closing the panel.
      e.stopPropagation(); setOpen(false); setDraft(null)
    }
  }

  return (
    <div className="flex items-center justify-between gap-3">
      <label htmlFor={id} className="text-[12.5px] text-slate-300">{label}</label>
      <div ref={ref} onKeyDown={onKeyDown}
        className="relative flex items-stretch w-24 h-8 rounded-md border border-slate-700 bg-slate-950/60 focus-within:border-blue-500/70 transition-colors">
        <input
          id={id} inputMode="decimal" autoComplete="off"
          value={draft ?? fmt(value)}
          onChange={e => setDraft(e.target.value)}
          onBlur={commit}
          onFocus={e => e.target.select()}
          className="flex-1 min-w-0 bg-transparent pl-2 text-[12.5px] text-slate-100 tabular-nums outline-none"
        />
        {unit && <span className="self-center pr-1.5 text-[11px] text-slate-500">{unit}</span>}
        <button
          type="button" tabIndex={-1} aria-label={`${label} values`} aria-expanded={open}
          onClick={() => setOpen(o => !o)}
          className="w-7 grid place-items-center border-l border-slate-700 text-slate-400 hover:text-slate-100 hover:bg-white/[0.05] rounded-r-md"
        >
          <Chevron open={open} />
        </button>
        {open && (
          <ul role="listbox" aria-label={label}
            className="absolute right-0 top-full mt-1 z-30 min-w-full w-28 max-h-56 overflow-y-auto py-1 rounded-lg bg-slate-900 border border-slate-700 shadow-xl">
            {options.map(o => {
              const sel = Math.abs(o - value) < 1e-9
              return (
                <li key={o}>
                  <button type="button" role="option" aria-selected={sel}
                    onClick={() => { apply(o); setDraft(null); setOpen(false) }}
                    className={`w-full px-3 py-1 text-left text-[12.5px] tabular-nums transition-colors ${sel ? "bg-white/[0.07] text-slate-100" : "text-slate-400 hover:text-slate-100 hover:bg-white/[0.04]"}`}>
                    {fmt(o)}{unit && <span className="text-slate-500"> {unit}</span>}
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}

// One searchable dropdown over every Google Fonts family, plus two system faces.
function FontPicker({ family, fontCat, onChange }) {
  const [open, setOpen] = useState(false)
  const [fonts, setFonts] = useState(null)
  const [query, setQuery] = useState("")
  const [active, setActive] = useState(0)
  const ref = useRef(null)
  const listRef = useRef(null)
  useOutside(ref, open, () => setOpen(false))

  useEffect(() => {
    if (open && !fonts) import("./googleFonts.json").then(mod => setFonts(mod.default)).catch(() => setFonts([]))
  }, [open, fonts])

  const all = useMemo(
    () => [...Object.keys(SYSTEM_FONTS).map(n => [n, n === "Georgia" ? "r" : "s", true]), ...(fonts ?? [])],
    [fonts],
  )
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    return q ? all.filter(([n]) => n.toLowerCase().includes(q)) : all
  }, [all, query])

  useEffect(() => { setActive(0) }, [query])
  useEffect(() => { listRef.current?.children[active]?.scrollIntoView({ block: "nearest" }) }, [active])

  function pick([name, cat]) {
    ensureFont(name)
    onChange(name, cat)
    setOpen(false); setQuery("")
  }
  function onKeyDown(e) {
    if (!open) return
    if (e.key === "ArrowDown") { e.preventDefault(); setActive(a => Math.min(shown.length - 1, a + 1)) }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive(a => Math.max(0, a - 1)) }
    else if (e.key === "Enter" && shown[active]) { e.preventDefault(); pick(shown[active]) }
    else if (e.key === "Escape") { e.stopPropagation(); setOpen(false) }
  }

  return (
    <div ref={ref} className="relative" onKeyDown={onKeyDown}>
      <p className="text-[12.5px] text-slate-300 mb-1.5">Font</p>
      <button
        type="button" aria-haspopup="listbox" aria-expanded={open}
        onClick={() => setOpen(o => !o)}
        className="w-full h-10 px-3 flex items-center justify-between gap-2 rounded-lg border border-slate-700 bg-slate-950/60 hover:border-slate-600 text-left transition-colors"
      >
        <span className="truncate text-[15px] text-slate-100" style={{ fontFamily: fontStack(family, fontCat) }}>{family}</span>
        <span className="flex items-center gap-2 flex-shrink-0 text-slate-500">
          <span className="text-[11px]">{SYSTEM_FONTS[family] ? "System" : CATEGORY_LABEL[fontCat]}</span>
          <Chevron open={open} />
        </span>
      </button>
      {open && (
        <div className="absolute left-0 right-0 top-full mt-1 z-30 rounded-lg bg-slate-900 border border-slate-700 shadow-xl overflow-hidden">
          <div className="p-2 border-b border-slate-800">
            <input
              autoFocus value={query} onChange={e => setQuery(e.target.value)}
              placeholder={fonts ? `Search ${fonts.length.toLocaleString()} fonts` : "Loading fonts…"}
              aria-label="Search fonts"
              className="w-full h-8 px-2.5 rounded-md bg-slate-950/70 border border-slate-800 text-[12.5px] text-slate-100 placeholder-slate-600 outline-none focus:border-blue-500/60"
            />
          </div>
          <ul ref={listRef} role="listbox" aria-label="Fonts" className="max-h-64 overflow-y-auto py-1">
            {shown.map(([name, cat, system], i) => (
              <li key={name}>
                <button
                  type="button" role="option" aria-selected={name === family}
                  onClick={() => pick([name, cat])}
                  onMouseEnter={() => setActive(i)}
                  className={`w-full flex items-center justify-between gap-3 px-3 py-1.5 text-left text-[13px] transition-colors ${
                    i === active ? "bg-white/[0.06] text-slate-100" : name === family ? "text-slate-100" : "text-slate-400"
                  }`}
                >
                  <span className="truncate">{name}</span>
                  <span className="flex-shrink-0 text-[11px] text-slate-600">{system ? "System" : CATEGORY_LABEL[cat]}</span>
                </button>
              </li>
            ))}
            {fonts && shown.length === 0 && <li className="px-3 py-2 text-[12.5px] text-slate-500">No font matches “{query}”.</li>}
          </ul>
        </div>
      )}
    </div>
  )
}

function Slider({ id, label, value, min, max, step, format, onChange }) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <label htmlFor={id} className="text-[12.5px] text-slate-300">{label}</label>
        <span className="text-[12px] text-slate-500 tabular-nums">{format ? format(value) : value}</span>
      </div>
      <input
        id={id} type="range" min={min} max={max} step={step} value={value}
        onChange={e => onChange(Number(e.target.value))}
        className="w-full cursor-pointer"
        style={{ accentColor: "var(--u-accent)" }}
      />
    </div>
  )
}

function Segmented({ label, value, options, onChange }) {
  return (
    <div>
      <p className="text-[12.5px] text-slate-300 mb-1.5">{label}</p>
      <div role="radiogroup" aria-label={label} className="grid grid-flow-col auto-cols-fr gap-1 p-1 rounded-lg bg-slate-950/60 border border-slate-800">
        {options.map(([v, text]) => (
          <button
            key={String(v)} type="button" role="radio" aria-checked={value === v}
            onClick={() => onChange(v)}
            className={`h-8 rounded-md text-[12px] transition-colors ${value === v ? "bg-slate-800 text-slate-100 shadow-sm" : "text-slate-500 hover:text-slate-200"}`}
          >
            {text}
          </button>
        ))}
      </div>
    </div>
  )
}

function Toggle({ label, checked, onChange }) {
  return (
    <label className="flex items-center justify-between gap-3 cursor-pointer">
      <span className="text-[12.5px] text-slate-300">{label}</span>
      <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} className="w-4 h-4 cursor-pointer" style={{ accentColor: "var(--u-accent)" }} />
    </label>
  )
}

function ThemeGrid({ prefs, set }) {
  return (
    <div className="grid grid-cols-3 gap-1.5">
      {THEMES.map(t => {
        const sel = prefs.theme === t.id
        const sw = t.id === "custom" ? prefs.custom : t
        return (
          <button
            key={t.id} type="button" aria-pressed={sel}
            onClick={() => set({ theme: t.id })}
            className={`relative h-14 rounded-lg border overflow-hidden text-left transition-colors ${sel ? "border-blue-500 ring-1 ring-blue-500/50" : "border-slate-800 hover:border-slate-700"}`}
            style={sw?.bg ? { background: sw.bg, color: sw.text } : undefined}
          >
            <span className={`absolute left-2 bottom-1.5 text-[11px] leading-tight ${sw?.bg ? "" : "text-slate-300"}`}>{t.label}</span>
            {sw?.accent && <span className="absolute right-2 top-2 w-2.5 h-2.5 rounded-full" style={{ background: sw.accent }} />}
            {!sw?.bg && <span className="absolute right-2 top-2 text-[10px] text-slate-500">auto</span>}
          </button>
        )
      })}
    </div>
  )
}

function ColorField({ id, label, value, onChange }) {
  return (
    <label htmlFor={id} className="flex items-center justify-between gap-3">
      <span className="text-[12.5px] text-slate-300">{label}</span>
      <span className="flex items-center gap-2">
        <span className="text-[11.5px] text-slate-500 tabular-nums uppercase">{value}</span>
        <input id={id} type="color" value={value} onChange={e => onChange(e.target.value)} className="w-9 h-7 rounded border border-slate-700 bg-transparent cursor-pointer" />
      </span>
    </label>
  )
}

export default function ReaderSettings({ prefs, set, onClose, userKey = "anonymous" }) {
  const phone = useIsPhone()
  const closeRef = useRef(null)
  const [savedSections, setSavedSections] = useState(() => ({ userKey, open: loadOpenSections(userKey) }))
  const openSections = savedSections.userKey === userKey ? savedSections.open : loadOpenSections(userKey)

  useEffect(() => { closeRef.current?.focus() }, [])

  useEffect(() => {
    if (savedSections.userKey !== userKey) setSavedSections({ userKey, open: loadOpenSections(userKey) })
  }, [savedSections.userKey, userKey])

  useEffect(() => {
    if (savedSections.userKey !== userKey) return
    try {
      localStorage.setItem(`${SECTION_STATE_KEY}.${userKey}`, JSON.stringify(savedSections.open))
    } catch {
      // Keep the in-memory state if browser storage is unavailable.
    }
  }, [savedSections, userKey])

  function toggleSection(id) {
    setSavedSections({
      userKey,
      open: { ...openSections, [id]: !openSections[id] },
    })
  }

  return (
    <m.div
      {...(phone ? presets.sheet : presets.panel)}
      role="dialog" aria-label="Reading settings"
      data-no-unpack
      className={[
        "absolute z-20 flex flex-col bg-slate-900 border-slate-800 shadow-2xl",
        phone ? "inset-x-0 bottom-0 max-h-[82%] rounded-t-2xl border-t" : "top-2 right-2 bottom-2 w-[380px] rounded-2xl border",
      ].join(" ")}
      style={{ boxShadow: "var(--u-modal-shadow)" }}
    >
      <div className="flex items-center justify-between px-5 pt-4 pb-3">
        <h2 className="text-[15px] font-semibold text-slate-100">Reading settings</h2>
        <div className="flex items-center gap-1">
          <button type="button" onClick={() => set({ ...DEFAULTS, custom: { ...DEFAULTS.custom } })} className="h-8 px-2.5 rounded-lg text-[12px] text-slate-400 hover:text-slate-100 hover:bg-white/[0.06] transition-colors">Reset</button>
          <button ref={closeRef} type="button" onClick={onClose} aria-label="Close settings" className="w-8 h-8 rounded-lg grid place-items-center text-slate-400 hover:text-slate-100 hover:bg-white/[0.06] transition-colors">
            <svg className="w-4 h-4" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"><path d="m4 4 8 8M12 4l-8 8" /></svg>
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto pb-4">
        <Section id="presets" title="Presets" open={openSections.presets} onToggle={() => toggleSection("presets")}>
          <div className="flex flex-wrap gap-1.5">
            {PRESETS.map(p => (
              <button key={p.id} type="button" onClick={() => set({ ...DEFAULTS, custom: prefs.custom, ...p.prefs })}
                className="h-8 px-3 rounded-full border border-slate-800 text-[12px] text-slate-300 hover:text-slate-100 hover:border-slate-600 transition-colors">
                {p.label}
              </button>
            ))}
          </div>
        </Section>

        <Section id="theme" title="Theme" open={openSections.theme} onToggle={() => toggleSection("theme")}>
          <ThemeGrid prefs={prefs} set={set} />
          {prefs.theme === "custom" && (
            <div className="space-y-2.5 pt-1">
              <ColorField id="r-bg" label="Background" value={prefs.custom.bg} onChange={v => set({ custom: { ...prefs.custom, bg: v } })} />
              <ColorField id="r-text" label="Text" value={prefs.custom.text} onChange={v => set({ custom: { ...prefs.custom, text: v } })} />
              <ColorField id="r-accent" label="Accent" value={prefs.custom.accent} onChange={v => set({ custom: { ...prefs.custom, accent: v } })} />
              <Toggle label="Dark background" checked={prefs.custom.dark} onChange={v => set({ custom: { ...prefs.custom, dark: v } })} />
            </div>
          )}
          <NumberCombo id="r-dim" label="Brightness" value={prefs.dim} options={DIM_OPTIONS} min={RANGE.dim[0]} max={RANGE.dim[1]} unit="%" onChange={v => set({ dim: v })} />
        </Section>

        <Section id="layout" title="Layout" open={openSections.layout} onToggle={() => toggleSection("layout")}>
          <Slider id="r-width" label="Column width" value={prefs.width} min={RANGE.width[0]} max={RANGE.width[1]} step={10} format={v => `${v}px`} onChange={v => set({ width: v })} />
          <Segmented label="Alignment" value={prefs.align} options={[["left", "Left"], ["justify", "Justified"]]} onChange={v => set({ align: v })} />
          <Toggle label="Hyphenate long words" checked={prefs.hyphens} onChange={v => set({ hyphens: v })} />
        </Section>

        <Section id="text" title="Text" open={openSections.text} onToggle={() => toggleSection("text")}>
          <FontPicker family={prefs.font} fontCat={prefs.fontCat} onChange={(font, fontCat) => set({ font, fontCat })} />
          <NumberCombo id="r-size" label="Text size" value={prefs.size} options={SIZE_OPTIONS} min={RANGE.size[0]} max={RANGE.size[1]} unit="px" decimals={1} onChange={v => set({ size: v })} />
        </Section>

        <Section id="spacing" title="Spacing" open={openSections.spacing} onToggle={() => toggleSection("spacing")}>
          <NumberCombo id="r-lh" label="Line height" value={prefs.lineHeight} options={LINE_OPTIONS} min={RANGE.lineHeight[0]} max={RANGE.lineHeight[1]} decimals={2} onChange={v => set({ lineHeight: v })} />
          <NumberCombo id="r-track" label="Letter spacing" value={prefs.tracking} options={TRACK_OPTIONS} min={RANGE.tracking[0]} max={RANGE.tracking[1]} unit="em" decimals={2} onChange={v => set({ tracking: v })} />
          <NumberCombo id="r-words" label="Word spacing" value={prefs.wordSpacing} options={WORD_OPTIONS} min={RANGE.wordSpacing[0]} max={RANGE.wordSpacing[1]} unit="em" decimals={2} onChange={v => set({ wordSpacing: v })} />
          <NumberCombo id="r-para" label="Space between blocks" value={prefs.paraSpacing} options={BLOCK_OPTIONS} min={RANGE.paraSpacing[0]} max={RANGE.paraSpacing[1]} unit="em" decimals={2} onChange={v => set({ paraSpacing: v })} />
        </Section>

        <Section id="slides" title="Slides" open={openSections.slides} onToggle={() => toggleSection("slides")}>
          <Segmented label="Transition" value={prefs.transition} options={[["slide", "Slide"], ["fade", "Fade"], ["lift", "Lift"], ["none", "None"]]} onChange={v => set({ transition: v })} />
          <NumberCombo id="r-speed" label="Transition time" value={prefs.speed} options={SPEED_OPTIONS} min={RANGE.speed[0]} max={RANGE.speed[1]} unit="×" decimals={2} onChange={v => set({ speed: v })} />
          <Toggle label="Hide toolbar while reading" checked={prefs.autoHide} onChange={v => set({ autoHide: v })} />
          <Toggle label="Side arrows" checked={prefs.arrows} onChange={v => set({ arrows: v })} />
        </Section>
      </div>
    </m.div>
  )
}
