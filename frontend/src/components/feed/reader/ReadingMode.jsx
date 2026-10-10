/**
 * ReadingMode — one day's articles as slides, over the whole app.
 *
 * Rendered by DailyPackageView into a portal on <body>, above the sidebar.
 * It reuses InsightCard (bare, no Share) so every reading action from the
 * feed — bookmark, note, read later, ask/explain, mark read, related chats —
 * works here unchanged. It opens with a circular reveal from the button that
 * launched it and closes back into it.
 *
 * Props:
 *   pkg, cards, coreCount — the day and its cards in page order
 *   startIndex            — slide to open on (the card that was in view)
 *   origin {x, y}         — where the reveal starts
 *   dayLabel              — e.g. "Day 2"
 *   daySwitcher           — the feed's Day menu, without Generate
 *   cardProps(card)       — InsightCard props for a card
 *   readKeys              — Set<articleKey> (newest day only)
 *   onExit(articleKey)    — leave; the feed scrolls to that card
 */
import { useState, useEffect, useRef, useCallback } from "react"
import { m, AnimatePresence } from "../../../lib/motion.jsx"
import InsightCard from "../InsightCard.jsx"
import ReaderSettings from "./ReaderSettings.jsx"
import { useAuth } from "../../../contexts/AuthContext.jsx"
import { articleKeyFromTitle } from "../../../api/feed.js"
import { loadPrefs, savePrefs, ensureFont, themeVars, typeVars, slideVariants, SLIDE_TRANSITION } from "./readerPrefs.js"

const keyOf = c => articleKeyFromTitle(c.title || "")
const EASE = SLIDE_TRANSITION.ease

// Arrow keys belong to whatever control has focus (a note, a slider) before the slides.
function ownsKeys(el) {
  return el && (el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable ||
    (el.tagName === "INPUT" && !["checkbox", "button"].includes(el.type)))
}

function Icon({ d, className = "w-4 h-4" }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d={d} />
    </svg>
  )
}

function SettingsIcon({ className = "w-4 h-4" }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="8" cy="8" r="2.3" />
      <path d="M8 1.9v1.2M8 12.9v1.2M4.5 4.5l-.9-.9M12.4 12.4l-.9-.9M1.9 8h1.2M12.9 8h1.2M4.5 11.5l-.9.9M12.4 3.6l-.9.9" />
    </svg>
  )
}

const BTN = "h-9 min-w-9 px-2.5 inline-flex items-center justify-center gap-1.5 rounded-lg text-[13px] text-slate-400 hover:text-slate-100 hover:bg-white/[0.06] active:scale-95 transition-[color,background-color,transform]"
const DOCK_BTN = "h-full px-3.5 inline-flex items-center gap-1.5 text-[13px] font-medium text-slate-200 hover:text-slate-100 hover:bg-white/[0.06] active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed transition-[color,background-color,transform]"

export default function ReadingMode({ pkg, cards, coreCount, startIndex = 0, origin, dayLabel, daySwitcher, cardProps, readKeys, onExit, onSlide }) {
  const { user } = useAuth()
  const [prefs, setPrefs] = useState(loadPrefs)
  const [index, setIndex] = useState(Math.min(startIndex, cards.length))
  const [dir, setDir] = useState(1)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [listOpen, setListOpen] = useState(false)
  const [fullscreen, setFullscreen] = useState(() => !!document.fullscreenElement)
  const [toolbarHidden, setToolbarHidden] = useState(false)
  const scrollerRef = useRef(null)
  const contentsTriggerRef = useRef(null)
  const contentsMenuRef = useRef(null)
  const touch = useRef(null)
  const wheelGesture = useRef({ deltaX: 0, locked: false, resetTimer: null })
  const firstPkg = useRef(pkg.id)

  // cards + one closing slide
  const total = cards.length + 1
  const atEnd = index >= cards.length
  const card = atEnd ? null : cards[index]
  const props = card ? cardProps(card) : null
  // Phones: Ask / Explain sit in the bottom bar, in thumb reach (the card drops them).
  const dock = props && !props.readOnly && (props.onAskAbout || props.onExplainSimply) ? props : null

  const set = useCallback(patch => setPrefs(p => { const next = { ...p, ...patch }; savePrefs(next); return next }), [])
  useEffect(() => { ensureFont(prefs.font) }, [prefs.font])

  // Another day picked from the Day menu starts at its first article.
  useEffect(() => {
    if (pkg.id === firstPkg.current) return
    firstPkg.current = pkg.id
    setDir(1); setIndex(0)
  }, [pkg.id])

  // The page behind stays put while reading.
  useEffect(() => {
    const html = document.documentElement
    const prev = html.style.overflow
    html.style.overflow = "hidden"
    return () => { html.style.overflow = prev }
  }, [])

  const go = useCallback(to => {
    const next = Math.max(0, Math.min(total - 1, to))
    if (next === index) return
    setDir(next > index ? 1 : -1)
    setIndex(next)
    setListOpen(false)
  }, [index, total])

  const exit = useCallback(() => {
    if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {})
    onExit(card ? keyOf(card) : cards.length ? keyOf(cards[cards.length - 1]) : null)
  }, [card, cards, onExit])

  // New slide: start at its top and take keyboard focus, so ↑ ↓ Space scroll
  // it — and tell the feed, whose URL follows the slide (null: closing slide).
  useEffect(() => {
    onSlide?.(card)
    const el = scrollerRef.current
    if (!el) return
    el.scrollTop = 0
    el.focus({ preventScroll: true })
  }, [index, pkg.id]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    function onKey(e) {
      if (e.key === "Escape") {
        if (settingsOpen) setSettingsOpen(false)
        else if (listOpen) setListOpen(false)
        else exit()
        return
      }
      if (settingsOpen || ownsKeys(e.target) || e.metaKey || e.ctrlKey || e.altKey) return
      if (e.key === "ArrowRight") { go(index + 1); e.preventDefault() }
      else if (e.key === "ArrowLeft") { go(index - 1); e.preventDefault() }
      else if (e.key === "f" || e.key === "F") toggleFullscreen()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [go, index, exit, settingsOpen, listOpen])

  useEffect(() => {
    if (!listOpen) return
    function onPointerDown(e) {
      if (contentsTriggerRef.current?.contains(e.target) || contentsMenuRef.current?.contains(e.target)) return
      setListOpen(false)
    }
    document.addEventListener("pointerdown", onPointerDown)
    return () => document.removeEventListener("pointerdown", onPointerDown)
  }, [listOpen])

  useEffect(() => {
    const onChange = () => setFullscreen(!!document.fullscreenElement)
    document.addEventListener("fullscreenchange", onChange)
    return () => document.removeEventListener("fullscreenchange", onChange)
  }, [])
  function toggleFullscreen() {
    if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {})
    else document.documentElement.requestFullscreen?.().catch(() => {})
  }
  const canFullscreen = typeof document !== "undefined" && !!document.documentElement.requestFullscreen

  // Optional: the toolbar tucks away after a few still seconds and returns on any movement.
  useEffect(() => {
    if (!prefs.autoHide || settingsOpen || listOpen) { setToolbarHidden(false); return }
    let t
    const wake = () => { setToolbarHidden(false); clearTimeout(t); t = setTimeout(() => setToolbarHidden(true), 2500) }
    wake()
    const evs = ["mousemove", "touchstart", "keydown"]
    evs.forEach(ev => window.addEventListener(ev, wake, { passive: true }))
    return () => { clearTimeout(t); evs.forEach(ev => window.removeEventListener(ev, wake)) }
  }, [prefs.autoHide, settingsOpen, listOpen])

  // Trackpad horizontal scrolling represents a two-finger swipe on laptops.
  function onWheel(e) {
    const gesture = wheelGesture.current
    if (settingsOpen || listOpen || !e.deltaX || Math.abs(e.deltaX) <= Math.abs(e.deltaY)) return

    if (gesture.resetTimer) clearTimeout(gesture.resetTimer)
    gesture.resetTimer = setTimeout(() => {
      gesture.deltaX = 0
      gesture.locked = false
      gesture.resetTimer = null
    }, 300)
    if (gesture.locked) return
    if (gesture.deltaX && Math.sign(gesture.deltaX) !== Math.sign(e.deltaX)) gesture.deltaX = 0
    gesture.deltaX += e.deltaX
    if (Math.abs(gesture.deltaX) < 80) return

    const direction = gesture.deltaX > 0 ? 1 : -1
    gesture.deltaX = 0
    gesture.locked = true
    go(index + direction)
  }

  // Touchscreens navigate with one finger; ignore multi-touch and canceled gestures.
  function onTouchStart(e) {
    if (e.touches.length !== 1) { touch.current = null; return }
    const t = e.touches[0]
    touch.current = { x: t.clientX, y: t.clientY, identifier: t.identifier }
  }
  function onTouchMove(e) {
    if (e.touches.length !== 1 || e.touches[0].identifier !== touch.current?.identifier) touch.current = null
  }
  function onTouchEnd(e) {
    const s = touch.current; touch.current = null
    if (!s) return
    const t = Array.from(e.changedTouches).find(touchPoint => touchPoint.identifier === s.identifier)
    if (!t) return
    const dx = t.clientX - s.x, dy = t.clientY - s.y
    if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) go(index + (dx < 0 ? 1 : -1))
  }
  function onTouchCancel() { touch.current = null }

  useEffect(() => () => {
    if (wheelGesture.current.resetTimer) clearTimeout(wheelGesture.current.resetTimer)
  }, [])

  const theme = themeVars(prefs)
  const style = { ...typeVars(prefs), ...(theme?.vars ?? {}) }
  const variants = slideVariants(prefs.transition)
  // Same units at both ends (px), or Motion can't interpolate and jumps.
  const ox = origin?.x ?? window.innerWidth / 2, oy = origin?.y ?? 24
  const reach = Math.hypot(Math.max(ox, window.innerWidth - ox), Math.max(oy, window.innerHeight - oy))
  const circle = r => `circle(${r}px at ${ox}px ${oy}px)`
  const readCount = cards.slice(0, coreCount).filter(c => readKeys?.has(keyOf(c))).length

  return (
    <m.div
      data-ui={theme ? (theme.dark ? "dark" : "light") : undefined}
      className="u-reader fixed inset-0 z-[58] flex flex-col bg-slate-950 text-slate-300"
      style={style}
      initial={{ clipPath: circle(0) }}
      animate={{ clipPath: circle(reach), transition: { duration: 0.6, ease: EASE } }}
      exit={{ clipPath: circle(0), transition: { duration: 0.45, ease: EASE } }}
      role="dialog" aria-modal="true" aria-label={`Reading mode, ${dayLabel}`}
    >
      {/* Toolbar */}
      <m.header
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: toolbarHidden ? 0 : 1, y: toolbarHidden ? -8 : 0, transition: { duration: 0.3, delay: toolbarHidden ? 0 : 0.15 } }}
        className="absolute inset-x-0 top-0 z-10 grid grid-cols-[1fr_auto_1fr] items-center gap-1 px-2 sm:px-3 h-14 pt-safe bg-transparent"
        style={{ pointerEvents: toolbarHidden ? "none" : undefined }}
      >
        <div className="flex items-center">
          <button type="button" onClick={exit} className={BTN} title="Exit reading mode (Esc)">
            <Icon d="M10 3 5 8l5 5" /><span className="hidden sm:inline">Exit</span>
          </button>
        </div>

        {/* The day and its contents, together in the middle */}
        <div className="relative flex items-center justify-center gap-1.5">
          {daySwitcher}
          <button
            ref={contentsTriggerRef}
            type="button" onClick={() => setListOpen(o => !o)} aria-expanded={listOpen} aria-haspopup="true"
            className="h-9 px-3 inline-flex items-center gap-2 rounded-lg text-[13px] text-slate-400 hover:text-slate-100 hover:bg-white/[0.06] active:scale-95 transition-[color,background-color,transform]"
          >
            <Icon d="M3 4.5h10M3 8h10M3 11.5h10" />
            <span>Contents</span>
          </button>
          <AnimatePresence>
            {listOpen && (
              <m.ol
                ref={contentsMenuRef}
                key="list"
                initial={{ opacity: 0, y: -6, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -4, scale: 0.98 }}
                transition={{ duration: 0.18 }}
                className="absolute top-full mt-1.5 w-[min(420px,calc(100vw-24px))] max-h-[60vh] overflow-y-auto py-1.5 rounded-xl bg-slate-900 border border-slate-800"
                style={{ boxShadow: "var(--u-modal-shadow)" }}
              >
                {cards.map((c, i) => {
                  const read = readKeys?.has(keyOf(c))
                  return (
                    <li key={keyOf(c)}>
                      <button type="button" onClick={() => go(i)} aria-current={i === index ? "true" : undefined}
                        className={`w-full flex items-start gap-3 px-3.5 py-2 text-left text-[13px] leading-snug transition-colors ${i === index ? "bg-white/[0.06] text-slate-100" : "text-slate-400 hover:text-slate-100 hover:bg-white/[0.03]"}`}>
                        <span className="w-5 flex-shrink-0 tabular-nums text-slate-500">{i < coreCount ? i + 1 : "+"}</span>
                        <span className="flex-1">{c.title}</span>
                        {read && <span className="text-emerald-400 flex-shrink-0">✓</span>}
                      </button>
                    </li>
                  )
                })}
                <li>
                  <button type="button" onClick={() => go(cards.length)} className="w-full flex gap-3 px-3.5 py-2 text-left text-[13px] text-slate-500 hover:text-slate-100 hover:bg-white/[0.03] transition-colors">
                    <span className="w-5" />End of {dayLabel}
                  </button>
                </li>
              </m.ol>
            )}
          </AnimatePresence>
        </div>

        <div className="flex items-center justify-end gap-1">
        <button type="button" onClick={() => setSettingsOpen(o => !o)} aria-expanded={settingsOpen} className={BTN} title="Reading settings">
          <SettingsIcon className="w-4 h-4" />
        </button>
        {canFullscreen && (
          <button type="button" onClick={toggleFullscreen} className={BTN} title={fullscreen ? "Exit full screen (F)" : "Full screen (F)"} aria-pressed={fullscreen}>
            {fullscreen
              ? <Icon d="M6 2.5V6H2.5M10 2.5V6h3.5M6 13.5V10H2.5M10 13.5V10h3.5" />
              : <Icon d="M2.5 6V2.5H6M10 2.5h3.5V6M2.5 10v3.5H6M13.5 10v3.5H10" />}
          </button>
        )}
        </div>
      </m.header>

      {/* Slides */}
      <div
        className="absolute inset-0 overflow-hidden bg-transparent"
        style={{ filter: prefs.dim < 100 ? `brightness(${prefs.dim / 100})` : undefined }}
        onWheel={onWheel}
        onTouchStart={onTouchStart} onTouchMove={onTouchMove} onTouchEnd={onTouchEnd} onTouchCancel={onTouchCancel}
      >
        <AnimatePresence initial={false} custom={dir}>
          <m.div
            key={`${pkg.id}:${index}`}
            ref={scrollerRef}
            tabIndex={-1}
            custom={dir}
            variants={variants}
            initial="enter" animate="center" exit="exit"
            transition={prefs.transition === "none" ? { duration: 0 } : SLIDE_TRANSITION}
            className="absolute inset-0 overflow-y-auto outline-none"
          >
            <m.div
              initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45, delay: 0.18 }}
              className="u-rc-wrap mx-auto px-4 sm:px-8"
              style={{
                paddingTop: "calc(3.5rem + env(safe-area-inset-top) + 1rem)",
                paddingBottom: "calc(5rem + env(safe-area-inset-bottom))",   /* clears the phone dock */
              }}
            >
              {card ? (
                <InsightCard key={keyOf(card)} {...props} bare hideShare
                  eyebrow={index < coreCount ? `Article ${index + 1} of ${coreCount}` : "Curiosity pick"} />
              ) : (
                <div className="mx-auto" style={{ maxWidth: "var(--r-width)" }}>
                  <EndSlide dayLabel={dayLabel} actionItem={pkg.action_item} readCount={readCount} coreCount={coreCount} showRead={!!readKeys}
                    onRestart={() => go(0)} onExit={exit} />
                </div>
              )}
            </m.div>
          </m.div>
        </AnimatePresence>

        {/* Side arrows — from 1600px, where they clear the three-column spread */}
        {prefs.arrows && (
          <>
            <button type="button" onClick={() => go(index - 1)} disabled={index === 0} aria-label="Previous article"
              className="hidden min-[1600px]:grid absolute left-4 top-1/2 -translate-y-1/2 w-11 h-11 place-items-center rounded-full text-slate-500 hover:text-slate-100 hover:bg-white/[0.06] disabled:opacity-0 transition-all active:scale-95">
              <Icon d="M10 3 5 8l5 5" className="w-5 h-5" />
            </button>
            <button type="button" onClick={() => go(index + 1)} disabled={index >= total - 1} aria-label="Next article"
              className="hidden min-[1600px]:grid absolute right-4 top-1/2 -translate-y-1/2 w-11 h-11 place-items-center rounded-full text-slate-500 hover:text-slate-100 hover:bg-white/[0.06] disabled:opacity-0 transition-all active:scale-95">
              <Icon d="m6 3 5 5-5 5" className="w-5 h-5" />
            </button>
          </>
        )}
      </div>

      {/* Previous / Next — where there are no side arrows (phones, tablets, or arrows turned off) */}
      <m.footer
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: toolbarHidden ? 0 : 1, y: toolbarHidden ? 8 : 0, transition: { duration: 0.3, delay: toolbarHidden ? 0 : 0.2 } }}
        className={`absolute inset-x-0 bottom-0 z-10 flex items-center justify-between px-3 sm:px-5 pb-safe pt-1 bg-transparent ${prefs.arrows ? "min-[1600px]:hidden" : ""}`}
        style={{ pointerEvents: toolbarHidden ? "none" : undefined }}
      >
        <button type="button" onClick={() => go(index - 1)} disabled={index === 0} className={`${BTN} disabled:opacity-30`} aria-label="Previous article">
          <Icon d="M10 3 5 8l5 5" /><span className="hidden sm:inline">Previous</span>
        </button>
        {dock && (
          <div className="lg:hidden flex items-center h-10 rounded-full border border-slate-800 bg-slate-900/90 backdrop-blur-md overflow-hidden"
            style={{ boxShadow: "var(--u-modal-shadow)" }}>
            {dock.onAskAbout && (
              <button type="button" onClick={() => dock.onAskAbout(card)} disabled={dock.offlineDisabled} className={DOCK_BTN}
                title={dock.offlineDisabled ? "Requires an internet connection" : "Ask about this"}>
                <Icon d="M2.5 3.5h11v7.5H7l-3 2.5V11H2.5z" />Ask
              </button>
            )}
            {dock.onAskAbout && dock.onExplainSimply && <span className="w-px h-5 bg-slate-800" aria-hidden="true" />}
            {dock.onExplainSimply && (
              <button type="button" onClick={() => dock.onExplainSimply(card)} disabled={dock.offlineDisabled} className={DOCK_BTN}
                title={dock.offlineDisabled ? "Requires an internet connection" : undefined}>
                <Icon d="M6 13.5h4M6.5 11.5h3M8 2a3.5 3.5 0 0 0-2 6.4v1.6h4V8.4A3.5 3.5 0 0 0 8 2z" />Explain simply
              </button>
            )}
          </div>
        )}
        <button type="button" onClick={() => go(index + 1)} disabled={index >= total - 1} className={`${BTN} disabled:opacity-30`} aria-label="Next article">
          <span className="hidden sm:inline">Next</span><Icon d="m6 3 5 5-5 5" />
        </button>
      </m.footer>

      <AnimatePresence>
        {settingsOpen && (
          <>
            <m.div key="scrim" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="absolute inset-0 z-[15] bg-black/20" onClick={() => setSettingsOpen(false)} />
            <ReaderSettings
              key="settings"
              prefs={prefs}
              set={set}
              onClose={() => setSettingsOpen(false)}
              userKey={String(user?.id ?? user?.user_id ?? user?.email ?? "anonymous")}
            />
          </>
        )}
      </AnimatePresence>
    </m.div>
  )
}

function EndSlide({ dayLabel, actionItem, readCount, coreCount, showRead, onRestart, onExit }) {
  return (
    <div className="px-3 md:px-5 pt-[8vh] text-center">
      <p className="u-read-label text-slate-500">{dayLabel}</p>
      <h2 className="u-read-title text-slate-100 mt-3">That's the end of {dayLabel}.</h2>
      {showRead && coreCount > 0 && (
        <p className="u-read-body text-slate-400 mt-2">{readCount} of {coreCount} articles marked read.</p>
      )}
      {actionItem && (
        <div className="mt-8 text-left px-4 md:px-5 py-4 bg-white/[0.04] rounded-2xl">
          <p className="u-read-label text-blue-400/80 mb-1">Today's Action</p>
          <p className="u-read-body text-slate-200">{actionItem}</p>
        </div>
      )}
      <div className="mt-8 flex flex-wrap justify-center gap-2">
        <button type="button" onClick={onRestart} className="h-10 px-4 rounded-xl text-[13px] text-slate-300 bg-white/[0.05] hover:bg-white/[0.09] border border-white/[0.07] transition-colors">Back to the first article</button>
        <button type="button" onClick={onExit} className="h-10 px-4 rounded-xl text-[13px] text-slate-300 bg-white/[0.05] hover:bg-white/[0.09] border border-white/[0.07] transition-colors">Exit reading mode</button>
      </div>
    </div>
  )
}
