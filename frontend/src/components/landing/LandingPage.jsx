import { useRef, useEffect, useLayoutEffect, useState } from "react"
import Plate from "../shared/Plate.jsx"
import "../../landing.css"

/* ═══════════════════════════════════════════════════════════════════════════
   MOTION ENGINE

   One rAF loop, always running. Two layers:

   AMBIENT  CSS keyframes (grain, float, breathe, caret, rule drift) plus the
            pipeline timer. None of it depends on scroll or pointer, so the
            page is never inert.

   EVENT    Every element marked `data-stage` gets `--p` written each frame:
              -1 fully below the viewport   0 centred   +1 fully above
            CSS derives transform/opacity/blur from it. Because staging is a
            pure function of position rather than a fired trigger, scrolling
            back up replays it — there is no once-only state to reset.

   Reads are batched before writes so nothing thrashes layout.
   ═════════════════════════════════════════════════════════════════════════ */

const clamp01 = v => (v < 0 ? 0 : v > 1 ? 1 : v)
const clamp11 = v => (v < -1 ? -1 : v > 1 ? 1 : v)

/* ── Motion preference ────────────────────────────────────────────────────
   On Windows, "Show animations in Windows" (Settings → Accessibility → Visual
   effects) is one OS switch that Chrome and Edge report to the web as
   `prefers-reduced-motion: reduce`. Many people have it off for battery or
   perceived speed rather than motion sensitivity — for them a media-query-only
   rule silently kills the page with no way to get it back.

   So: the OS value is the DEFAULT, and an explicit choice (stored per visitor)
   overrides it. Someone who set reduce deliberately still gets the static page
   and is never overridden without asking.                                   */
const MOTION_KEY = "curivio.motion"

/* Theme is a deliberate choice, never a system reading. The brief is that the
   site opens light for everyone even when the OS is set to dark, so nothing
   here consults prefers-color-scheme — the only way to dark is the switch,
   and that answer is remembered per visitor. */
const THEME_KEY = "curivio.theme"

function resolveTheme() {
  try { return localStorage.getItem(THEME_KEY) === "dark" ? "dark" : "light" }
  catch { return "light" }
}

const osPrefersReduce = () =>
  typeof window !== "undefined" &&
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches

function storedMotion() {
  try { return localStorage.getItem(MOTION_KEY) } catch { return null }
}

/* resolved, synchronously — so the first paint is already correct, no flash */
function resolveMotion() {
  const saved = storedMotion()
  if (saved === "on") return true
  if (saved === "off") return false
  return !osPrefersReduce()
}

/* signed stage position of a rect: -1 below → 0 centred → +1 above */
function stageOf(rect, vh) {
  const center = rect.top + rect.height / 2
  const span = (vh + rect.height) / 2
  return clamp11((vh / 2 - center) / span)
}

function useMotionEngine(refs, setActive, motionOn) {
  useEffect(() => {
    const root = refs.root.current
    if (!root) return
    if (!motionOn) return

    const pointer = { x: 0, y: 0, tx: 0, ty: 0 }
    let raf = 0
    let running = true

    /* Per-element spring state, keyed off the node so it survives re-renders
       and is collected with it. */
    const springs = new WeakMap()
    let last = 0

    const loop = now => {
      const vh = window.innerHeight
      /* Real elapsed time, capped at two frames' worth. A spring integrated
         against an assumed 1/60 drifts on a 120Hz display and explodes after a
         tab has been in the background. */
      const dt = last ? Math.min((now - last) / 1000, 1 / 30) : 1 / 60
      last = now

      /* ── READ PASS — every rect first, no writes interleaved ───────────── */
      const staged = root.querySelectorAll("[data-stage]")
      const stagedRects = []
      for (const el of staged) stagedRects.push(el.getBoundingClientRect())

      const heroRect = refs.hero.current?.getBoundingClientRect()
      const bandRect = refs.band.current?.getBoundingClientRect()
      const blockEls = root.querySelectorAll("[data-block]")
      const blockRects = []
      for (const el of blockEls) blockRects.push(el.getBoundingClientRect())
      const marqueeW = refs.marquee.current?.scrollWidth ?? 0
      const bandW = refs.band.current?.clientWidth ?? 0
      const docH = document.documentElement.scrollHeight

      /* proximity targets */
      const proxEls = root.querySelectorAll("[data-prox]")
      const proxRects = []
      for (const el of proxEls) proxRects.push(el.getBoundingClientRect())

      /* the running section, for the gutter rail */
      const secEls = root.querySelectorAll("[data-sec]")
      const secRects = []
      for (const el of secEls) secRects.push(el.getBoundingClientRect())

      /* objects that tilt toward the pointer, measured from their OWN centre */
      const tiltEls = root.querySelectorAll("[data-tilt]")
      const tiltRects = []
      for (const el of tiltEls) tiltRects.push(el.getBoundingClientRect())

      /* how far a section has been scrolled through, 0 → 1 */
      const progEls = root.querySelectorAll("[data-prog]")
      const progRects = []
      for (const el of progEls) progRects.push(el.getBoundingClientRect())

      /* objects running a real spring toward the pointer */
      const springEls = root.querySelectorAll("[data-spring]")
      const springRects = []
      for (const el of springEls) springRects.push(el.getBoundingClientRect())

      /* ── WRITE PASS ────────────────────────────────────────────────────── */
      const set = (k, v) => root.style.setProperty(k, v)

      staged.forEach((el, i) => {
        el.style.setProperty("--p", stageOf(stagedRects[i], vh).toFixed(4))
      })

      if (heroRect) {
        const total = heroRect.height - vh
        set("--sp", clamp01(total > 0 ? -heroRect.top / total : 0).toFixed(4))
      }

      if (bandRect) {
        set("--bp", clamp01((vh - bandRect.top) / (vh + bandRect.height)).toFixed(4))
        set("--band-shift", `${-Math.max(marqueeW - bandW, 0)}px`)
      }

      /* Active block = whichever is nearest the viewport centre. Derived from
         real positions, so the section needs no artificial scroll runway —
         which is what produced v3's 1412px void. */
      if (blockRects.length) {
        let best = 0, bestD = Infinity
        for (let i = 0; i < blockRects.length; i++) {
          const r = blockRects[i]
          const d = Math.abs(r.top + r.height / 2 - vh / 2)
          if (d < bestD) { bestD = d; best = i }
        }
        setActive.anatomy(best)
      }

      /* Running section = the last one whose top has passed the viewport
         centre. Monotone by construction, so the rail can never flicker
         between two neighbours the way a nearest-distance test does when two
         sections are almost equidistant. */
      if (secRects.length) {
        let cur = 0
        for (let i = 0; i < secRects.length; i++) if (secRects[i].top <= vh * 0.5) cur = i
        setActive.section(cur)
      }

      /* Pointer eased toward its target so depth never snaps. .13 rather than
         .075 — at the slower rate the layers lagged far enough behind the
         cursor that the hero read as drifting on its own rather than
         responding to you. Still eased, so it never feels glued to the mouse. */
      pointer.x += (pointer.tx - pointer.x) * 0.13
      pointer.y += (pointer.ty - pointer.y) * 0.13
      set("--mx", pointer.x.toFixed(4))
      set("--my", pointer.y.toFixed(4))

      proxEls.forEach((el, i) => {
        const r = proxRects[i]
        const dx = pointer.rawX - (r.left + r.width / 2)
        const dy = pointer.rawY - (r.top + r.height / 2)
        if (Number.isNaN(dx)) return
        const near = Math.max(0, 1 - Math.hypot(dx, dy) / 300)
        /* clamped to ±9px so a card never leaves its own hit box */
        el.style.setProperty("--pxo", `${((dx / 300) * near * 9).toFixed(2)}px`)
        el.style.setProperty("--pyo", `${((dy / 300) * near * 9).toFixed(2)}px`)
      })

      /* LOCAL pointer, per object. --mx/--my are normalised across the whole
         viewport, which is right for the hero's depth layers but useless for
         an object parked at the right edge: the armillary spans x 1180-1440,
         so sweeping the cursor all around it moves --mx through roughly
         .64→1.0 — a sliver of the range, which is why its tilt read as barely
         responding. Measuring from the element's own centre gives the full
         -1..1 swing within `reach` px of it, so moving near it drives it hard.
         Raw pointer, not the eased one — the CSS transition does the
         smoothing, and easing twice is what makes a tilt feel like sludge. */
      /* Two kinds of object. A `data-tilt` alone reacts to the pointer anywhere
         within `reach` of its centre — right for the big background pieces you
         move THROUGH (the hero layers, the arc corridor, the package box).
         Adding `data-tilt-hover` restricts it to the pointer actually being
         over the object's own box, which is what a discrete instrument like
         the armillary or the lesson stack wants: reacting from across the page
         made them look like they were responding to nothing. */
      tiltEls.forEach((el, i) => {
        if (pointer.rawX === undefined) return
        const r = tiltRects[i]
        const hoverOnly = el.hasAttribute("data-tilt-hover")
        const over = pointer.rawX >= r.left && pointer.rawX <= r.right &&
                     pointer.rawY >= r.top  && pointer.rawY <= r.bottom
        if (hoverOnly && !over) {
          /* back to rest — the CSS transition eases it home */
          el.style.setProperty("--tx", "0")
          el.style.setProperty("--ty", "0")
          return
        }
        const reach = Number(el.dataset.tilt) || 520
        el.style.setProperty("--tx", clamp11((pointer.rawX - (r.left + r.width / 2)) / reach).toFixed(4))
        el.style.setProperty("--ty", clamp11((pointer.rawY - (r.top + r.height / 2)) / reach).toFixed(4))
      })

      /* SPRING-DRIVEN objects. `data-tilt` writes the pointer straight into a
         variable and lets a CSS transition smooth it — that is a low-pass
         filter, not physics: it always trails the cursor and it can never
         overshoot or settle. This integrates a real second-order spring per
         axis instead, so the object leads toward where the cursor went, passes
         its target slightly and rings down. Semi-implicit Euler, which is
         stable at these constants; dt is clamped so a backgrounded tab cannot
         return with a step big enough to blow the integration up.

         ζ = D / (2·√K) ≈ 21 / (2·√168) ≈ 0.81 — underdamped just enough for
         one visible overshoot and no bounce after it. */
      springEls.forEach((el, i) => {
        const r = springRects[i]
        let s = springs.get(el)
        if (!s) { s = { x: 0, y: 0, vx: 0, vy: 0, sep: 0, vsep: 0 }; springs.set(el, s) }

        let tx = 0, ty = 0
        if (pointer.rawX !== undefined) {
          const reach = Number(el.dataset.spring) || 420
          tx = clamp11((pointer.rawX - (r.left + r.width / 2)) / reach)
          ty = clamp11((pointer.rawY - (r.top + r.height / 2)) / reach)
        }

        const K = 168, D = 21
        s.vx += (K * (tx - s.x) - D * s.vx) * dt
        s.vy += (K * (ty - s.y) - D * s.vy) * dt
        s.x  += s.vx * dt
        s.y  += s.vy * dt

        /* How far the object is turned, on its own softer spring. The cards
           read this to open their spacing as it swings — a stack that fans
           slightly when handled and closes when set down. */
        const turn = Math.min(1, Math.hypot(s.x, s.y))
        s.vsep += (K * .55 * (turn - s.sep) - D * 1.15 * s.vsep) * dt
        s.sep  += s.vsep * dt

        el.style.setProperty("--sx", s.x.toFixed(4))
        el.style.setProperty("--sy", s.y.toFixed(4))
        el.style.setProperty("--sep", Math.max(0, s.sep).toFixed(4))
      })

      /* Section progress, same shape as the hero's --sp: 0 at the moment its
         top reaches the viewport top, 1 when its bottom does. The corridor
         reads this to retreat in z as the day rows come over it. */
      /* Divided by the FULL height, not (height - vh) the way the hero's --sp
         is. The hero is a pinned stage, so its travel really is height minus a
         viewport; this is an ordinary section, and dividing by the remainder
         made --ap hit 1 after 654px of a 1554px section — the corridor had
         finished retreating before Day 7 was even on screen. Over the full
         height it retreats across the whole run of days, which is the point. */
      progEls.forEach((el, i) => {
        const r = progRects[i]
        el.style.setProperty("--ap", clamp01(r.height > 0 ? -r.top / r.height : 0).toFixed(4))
      })

      set("--read", `${clamp01(window.scrollY / Math.max(docH - vh, 1)) * 100}%`)

      if (running) raf = requestAnimationFrame(loop)
    }

    const onPointer = e => {
      pointer.tx = (e.clientX / window.innerWidth) * 2 - 1
      pointer.ty = (e.clientY / window.innerHeight) * 2 - 1
      pointer.rawX = e.clientX
      pointer.rawY = e.clientY
    }

    window.addEventListener("pointermove", onPointer, { passive: true })
    raf = requestAnimationFrame(loop)
    return () => {
      running = false
      cancelAnimationFrame(raf)
      window.removeEventListener("pointermove", onPointer)
    }
  }, [refs, setActive, motionOn])
}

/* ═══════════════════════════════════════════════════════════════════════════
   LOGO SLOT — the real mark. The artwork is a fixed-colour tile with its
   rounded corners baked into the asset's alpha, so the slot paints no
   background of its own and never clips it; see .lp-logo-slot.
   Sizes in use:  nav = 30px  ·  footer = 24px
   ═════════════════════════════════════════════════════════════════════════ */
function LogoSlot({ size = 30 }) {
  return (
    <span className="lp-logo-slot" style={{ width: size, height: size }} aria-hidden="true" data-logo-slot="">
      <img src="/logo.webp" alt="" width={size} height={size} draggable="false"
           style={{ borderRadius: Math.round(size * 0.232) }} />
    </span>
  )
}

function Arrow({ className }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path fillRule="evenodd" d="M6.22 3.22a.75.75 0 0 1 1.06 0l4.25 4.25a.75.75 0 0 1 0 1.06l-4.25 4.25a.75.75 0 0 1-1.06-1.06L9.94 8 6.22 4.28a.75.75 0 0 1 0-1.06Z" clipRule="evenodd" />
    </svg>
  )
}

function IconDoc({ className }) {
  return (
    <svg className={className} viewBox="0 0 14 14" fill="none" stroke="currentColor"
         strokeWidth="1.15" strokeLinejoin="round" aria-hidden="true">
      <path d="M8.1 1.6H4.3a.7.7 0 0 0-.7.7v9.4c0 .39.31.7.7.7h5.4a.7.7 0 0 0 .7-.7V4.2z" />
      <path d="M8.1 1.6v2.6h2.3" />
    </svg>
  )
}

function IconLink({ className }) {
  return (
    <svg className={className} viewBox="0 0 14 14" fill="none" stroke="currentColor"
         strokeWidth="1.15" strokeLinecap="round" aria-hidden="true">
      <path d="M6.1 8.2a2.3 2.3 0 0 0 3.46.25l1.63-1.63A2.3 2.3 0 0 0 7.93 3.56l-.93.93" />
      <path d="M7.9 5.8a2.3 2.3 0 0 0-3.46-.25L2.81 7.18a2.3 2.3 0 0 0 3.26 3.26l.93-.93" />
    </svg>
  )
}

/* ═══════════════════════════════════════════════════════════════════════════
   PLATE — the drawn field that fills the big voids

   Measured: four section boundaries were 240-300px of blank paper, and mean
   ink coverage below the hero ran 0.07-0.38 of the viewport width. A gradient
   would only restate the flatness in two colours, so the fill is a DRAWN
   PLATE: a scatter of graded sources wired to their nearest neighbours —
   the page's own subject, in the language of an engraved figure.

   Geometry is generated once per seed from a deterministic PRNG (never
   Math.random: the layout has to be stable across renders or the plate would
   reshuffle on every beat of the demo timer). Rejection sampling keeps a
   minimum distance so the field reads as evenly scattered rather than clumped.

   AMBIENT throughout — the field drifts, nodes twinkle on their own offsets,
   and edges draw and retract. Nothing here is scroll-triggered.
   ═════════════════════════════════════════════════════════════════════════ */
/* Plate, buildPlate and the seeded rng now live in
   components/shared/Plate.jsx so the auth screen can render the same figure
   without pulling in this whole file. The CSS below is unchanged. */

/* ── THE GUTTER RAIL ──────────────────────────────────────────────────────
   Taken from Shopify Editions Winter '26, which is the one thing on that page
   that transfers cleanly: its left gutter carries a permanent index of all
   twelve sections with roman numerals, the current one in full ink and the
   rest dropped back — so the margin is never decoration, it is always
   navigation. Replaces the four static rotated labels this page had, which
   scrolled past and told you nothing about where you were.

   Under 1400 the gutter can no longer hold the words without touching the
   text column (measured: max-w-6xl leaves (W-1152)/2), so the names drop and
   the numerals carry it alone.                                            */
const SECTIONS = [
  { id: "how",      n: "I",   name: "The arc" },
  { id: "anatomy",  n: "II",  name: "One lesson" },
  { id: "features", n: "III", name: "Everything else" },
  { id: "start",    n: "IV",  name: "Start" },
]

function GutterRail({ active }) {
  return (
    <nav className="lp-rail" aria-label="Sections">
      <ol>
        {SECTIONS.map((s, i) => (
          <li key={s.id} data-on={i === active}>
            <a href={`#${s.id}`}>
              <span className="lp-rail-name">{s.name}</span>
              <span className="lp-rail-n">{s.n}</span>
            </a>
          </li>
        ))}
      </ol>
    </nav>
  )
}

/* ── THE ARMILLARY ───────────────────────────────────────────────────────
   The Editions page hangs a full-bleed WebGL scene behind everything — a
   sticky, zero-height canvas — and fills it with commissioned Renaissance
   painting. The painting is not reproducible here and would not mean
   anything if it were. The transferable half is an object that is genuinely
   three-dimensional, turns as you scroll, and leans with the cursor.

   So: an armillary sphere, the Renaissance instrument for the thing this
   product is actually about. It earns its place semantically — three rings
   for the three weeks the section is describing, a marked node on each for
   day 1, 7 and 21, and the topic at the centre they all turn around. It
   sits across the ARC→ANATOMY boundary, which is the 240px void.

   Scroll drives the spin through `--p`, which the engine already writes to
   the [data-stage] wrapper and which inherits down to the svg. The cursor
   tilt reads --mx/--my, already written every frame for the hero. No new
   engine, no new dependency, no canvas.
   ═══════════════════════════════════════════════════════════════════════ */
/* Every ring is a real CIRCLE standing in its own plane, tilted in space —
   not an ellipse drawn to look tilted. That is the whole difference: a drawn
   ellipse keeps its shape no matter what you do to it, while a circle rotated
   in 3D foreshortens correctly, so the instrument RESHAPES under the cursor
   instead of merely leaning. SVG has no z-axis, so the 3D lives in HTML —
   one absolutely-positioned layer per ring under `transform-style:
   preserve-3d`, each carrying its own fixed orientation, the whole assembly
   turned by the pointer.

   All three pass through the centre, like the real instrument; none is
   offset in z. The depth comes from their orientations disagreeing. */
const ARMIL_RINGS = [
  /* base angles kept well clear of 90°: the pointer now adds up to ±34° of
     pitch and ±52° of yaw on top of these, and any ring whose TOTAL reaches
     90° renders as a hairline and disappears — the same always-visible bug,
     arriving through the interaction instead of the animation. */
  { key: "equator", r: 128, rx: 48, ry:  0, rz:   0 },
  { key: "tropic",  r: 112, rx: 44, ry:  0, rz: -26 },
  { key: "colure",  r: 122, rx: 12, ry: 46, rz:   0 },
]

/* Annotations stay OUT of the 3D box. A label lying in a plane tilted 76° is
   edge-on and unreadable, and counter-rotating it per frame is a lot of
   machinery for three numbers. They sit flat over the instrument instead,
   which is what a printed figure does anyway. */
const ARMIL_NOTES = [
  { day: "01", x: 30, y: 106 },
  { day: "07", x: 22, y: 150 },
  { day: "21", x: 30, y: 194 },
]

function Armillary() {
  return (
    <div className="lp-armil" data-stage data-tilt="235" data-tilt-hover aria-hidden="true">
      <div className="lp-armil-3d">
        {/* ambient turn on its own layer, so it never fights the pointer tilt
            for the transform property */}
        <div className="lp-armil-spin">
          <svg className="lp-armil-layer lp-armil-flat" viewBox="0 0 300 300" fill="none">
            <circle className="lp-armil-mer" cx="150" cy="150" r="128" />
          </svg>
          {ARMIL_RINGS.map(g => (
            <svg key={g.key} className="lp-armil-layer" viewBox="0 0 300 300" fill="none"
                 style={{ "--rx": `${g.rx}deg`, "--ry": `${g.ry}deg`, "--rz": `${g.rz}deg` }}>
              <circle className="lp-armil-ring" cx="150" cy="150" r={g.r} />
            </svg>
          ))}
          <svg className="lp-armil-layer lp-armil-flat" viewBox="0 0 300 300" fill="none">
            <circle className="lp-armil-core" cx="150" cy="150" r="7" />
            <circle className="lp-armil-halo" cx="150" cy="150" r="7" />
          </svg>
        </div>
      </div>

      <svg className="lp-armil-notes" viewBox="0 0 300 300" fill="none">
        {ARMIL_NOTES.map(n => (
          <g key={n.day}>
            <circle className="lp-armil-day" cx={n.x} cy={n.y} r="4" />
            <text className="lp-armil-lab" x={n.x + 11} y={n.y} dy="3.5">{n.day}</text>
          </g>
        ))}
      </svg>
    </div>
  )
}

/* ── THE DAY CORRIDOR ────────────────────────────────────────────────────
   The section's backdrop, and its narrative in one object: every day of the
   topic as a sheet, receding into depth on a path that never reaches an end.
   The far sheets read 21, 30, then N — you can see, before a word of copy
   says it, that this does not stop on a fixed day.

   The behaviour the ask describes: whole at the start, then hidden BY the
   days as they arrive, in 3D. So it is pinned behind the section and pushed
   backward as `--ap` runs 0 → 1 — it does not merely get covered up, it
   retreats and fades while the day rows come forward over it.

   Sticky with `margin-bottom: -100vh`, the trick the Editions page uses for
   its canvas: the layer pins for the whole section while occupying no layout
   height at all, so nothing below it moves.                                */
const CORRIDOR = ["01", "02", "03", "05", "07", "09", "12", "15", "18", "21", "30", "N"]
  .map((label, i) => ({
    label, i,
    /* a walked path, not a stack: alternating left and right of centre and
       rising slightly, so it reads as a way through rather than a pile */
    /* The z-step has to dominate the sideways spread or there is no vanishing
       point and the whole thing reads as a scattered pile rather than a way
       into the distance — which is exactly how the first attempt came out at
       330px of swing against a 230px step. 340 back per page against a gentle
       rightward drift gives a real horizon: the near sheet renders at 0.78
       scale, the last at 0.24. */
    x: +(i * 10 + Math.sin(i * 0.9) * 46).toFixed(1),
    y: -i * 9,
    z: -i * 340,
    ry: +(-8 - i * 1.2).toFixed(1),
  }))

function DayCorridor() {
  return (
    <div className="lp-corr" data-tilt="620" aria-hidden="true">
      <div className="lp-corr-stage">
        {CORRIDOR.map(p => (
          <div key={p.label} className="lp-corr-slot"
               style={{ "--x": `${p.x}px`, "--y": `${p.y}px`, "--z": `${p.z}px`,
                        "--ry": `${p.ry}deg`, "--i": p.i }}>
           {/* the slot holds the position, the page does the floating — one
               element cannot carry a static placement transform and an
               animated one at the same time */}
           <div className="lp-corr-page">
            {/* the near sheets are ~300px on screen, big enough to carry a
                whole lesson in miniature — a day number, a headline, body,
                a highlighted line, its two citations and the source grades.
                Three ruled lines alone read as a blank card. */}
            <span className="lp-corr-n">{p.label}</span>
            <span className="lp-corr-title" />
            <i /><i />
            <span className="lp-corr-hl" />
            <i />
            <span className="lp-corr-foot">
              <span className="lp-corr-cite" />
              <span className="lp-corr-cite" />
              <span className="lp-corr-bars"><u /><u /><u /></span>
            </span>
           </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ── THE PACKAGE ─────────────────────────────────────────────────────────
   This section's eyebrow is "The complete package", so the object is one.

   It was a five-plane open box with four cards dropped in at hand-picked z
   offsets, painted behind the copy at `pointer-events: none` and hidden from
   assistive tech. That had three problems worth naming: the card offsets were
   unrelated numbers so the stack had no readable rhythm, a single
   `.13s ease-out` transition did all the motion so it trailed the cursor and
   never settled, and being inert it could not be clicked or focused at all.

   It is now a card index driven off one coordinate system, a real spring, and
   four independent transform layers. See PackageObject below.              */

/* One glyph per feature, so a card is identifiable before its label is read.
   Deliberately schematic — a diagram of the idea, not a screenshot of the UI.
   All strokes are currentColor, so each card's accent ink drives its art. */
function ArtUnpack() {
  return (
    <svg viewBox="0 0 60 40" fill="none" stroke="currentColor" strokeWidth="1.3"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <rect x="3.5" y="4.5" width="27" height="31" rx="2.5" />
      <path d="M9 12h16M9 18h16M9 24h10" />
      {/* the selected phrase, lifted out of the page and answered beside it */}
      <path d="M15 29.5h8" strokeWidth="3.4" opacity=".3" />
      <path d="M31 26h5" strokeDasharray="1 3" />
      <rect x="36.5" y="13.5" width="20" height="17" rx="2.5" />
      <path d="M41 19h11M41 24h7" />
    </svg>
  )
}
function ArtChat() {
  return (
    <svg viewBox="0 0 60 40" fill="none" stroke="currentColor" strokeWidth="1.3"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      {/* a short question, a longer answer, and the citation it lands on */}
      <path d="M6 5.5h26a2.5 2.5 0 0 1 2.5 2.5v6a2.5 2.5 0 0 1-2.5 2.5H14l-5 4v-4H6a2.5 2.5 0 0 1-2.5-2.5V8A2.5 2.5 0 0 1 6 5.5Z" />
      <path d="M9 11h18" />
      <path d="M54 21.5H28a2.5 2.5 0 0 0-2.5 2.5v6a2.5 2.5 0 0 0 2.5 2.5h18l5 4v-4h3a2.5 2.5 0 0 0 2.5-2.5v-6a2.5 2.5 0 0 0-2.5-2.5Z" />
      <path d="M31 27h13" />
    </svg>
  )
}
function ArtKeep() {
  return (
    <svg viewBox="0 0 60 40" fill="none" stroke="currentColor" strokeWidth="1.3"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <rect x="4.5" y="4.5" width="33" height="31" rx="2.5" />
      <path d="M10 13h20M10 19h14" />
      {/* the kept line, marked */}
      <path d="M10 26.5h15" strokeWidth="3.6" opacity=".32" />
      <path d="M45 4.5h10v24l-5-4.5-5 4.5Z" />
    </svg>
  )
}
function ArtOffline() {
  return (
    <svg viewBox="0 0 60 40" fill="none" stroke="currentColor" strokeWidth="1.3"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      {/* signal struck out, and the lesson already sitting on the device */}
      <path d="M6.5 15.5a13 13 0 0 1 6-6.5M12 21a7 7 0 0 1 3-3.5" opacity=".55" />
      <path d="M5 6.5 20 21.5" />
      <path d="M38 5v14M32.5 14 38 19.5 43.5 14" />
      <rect x="26.5" y="24.5" width="23" height="11" rx="2.5" />
      <path d="M31 30h9" />
    </svg>
  )
}
const PKG_ART = [ArtUnpack, ArtChat, ArtKeep, ArtOffline]
/* "Bookmarks · Read Later · Notes" is the honest name in the list below, but
   it will not sit on a card tab. */
const PKG_SHORT = ["Unpack", "Chat", "Keep", "Offline"]

/* ── THE PACKAGE OBJECT ───────────────────────────────────────────────────
   Four feature cards held in one shallow open volume — a card index, not a
   cube. Everything is derived from four numbers (--cw/--ch/--dz/--dy) and the
   card's own --i, so the four cards sit on one coordinate system instead of
   four unrelated pixel offsets, and the stack stays symmetric about its
   centre plane: i runs 0→3, z runs +1.5·dz → −1.5·dz.

   Four nested elements, four separate jobs, one transform each — the reason
   scroll, pointer, idle and selection can all run at once without any of them
   clobbering another's transform:

     .lp-pkg          perspective host + scroll opacity   ([data-stage])
     └ .lp-pkg-scroll depth/scale entrance                (--near)
       └ .lp-pkg-rot  pointer spring rotation             (--sx/--sy)
         └ .lp-pkg-idle  idle breathing                   (keyframes)
           └ cards       stack geometry + fan             (--i/--sep)
             └ face      selection pop                    (transitioned)          */
function PackageObject({ selected, onSelect }) {
  const rootRef = useRef(null)
  const [hovered, setHovered] = useState(null)
  const [bands, setBands] = useState(null)

  /* THE HIT LAYER.
     The cards themselves cannot be the buttons. They live several
     preserve-3d levels deep and half of them sit at negative Z, and Chrome
     simply does not hit-test them there: probing the centre of each card's own
     label strip returned the CONTAINER for cards 03 and 04, so the clicks were
     passing straight through — nothing to do with one card covering another,
     which is what the geometry fixes were aimed at. Pushing the stack in front
     of the projection plane fixed 03 but not 04, and compensating on the parent
     made card 01's strip report card 04. That is not a bug worth out-guessing
     in one browser, let alone three.

     So the 3D stack is decoration (`pointer-events: none`, aria-hidden) and
     every click, focus and hover lands on four plain rectangles in a flat,
     untransformed overlay. Their positions are MEASURED from where the strips
     actually render, so they stay correct at every breakpoint and in the flat
     mobile layout without a second set of numbers to keep in sync. Measured at
     rest, not per frame: the object only swings ±15°, and re-measuring during
     the idle animation would cost a layout every frame to move a hit box by a
     pixel. */
  useLayoutEffect(() => {
    const root = rootRef.current
    if (!root) return

    const measure = () => {
      const base = root.getBoundingClientRect()
      const cards = [...root.querySelectorAll(".lp-pkg-card")]
      if (cards.length !== FEATURES.length) return
      const rects = cards.map(c => ({
        card: c.getBoundingClientRect(),
        strip: c.querySelector(".lp-pkg-strip").getBoundingClientRect(),
      }))

      /* Visual top-to-bottom, which is NOT DOM order: on desktop the stack
         runs 04→01 down the screen, on mobile it runs 01→04. Sorting means one
         rule covers both. Each card owns from its own strip down to whatever
         sits below it; the lowest owns the rest of its face. */
      const order = rects.map((r, i) => i).sort((a, b) => rects[a].strip.top - rects[b].strip.top)
      const next = {}
      order.forEach((idx, pos) => {
        const below = order[pos + 1]
        next[idx] = below === undefined
          ? rects[idx].card.bottom
          : rects[below].strip.top
      })

      setBands(rects.map((r, i) => ({
        top: r.strip.top - base.top,
        left: r.card.left - base.left,
        width: r.card.width,
        height: Math.max(24, next[i] - r.strip.top),
      })))
    }

    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(root)
    window.addEventListener("resize", measure)
    return () => { ro.disconnect(); window.removeEventListener("resize", measure) }
  }, [])

  return (
    <div className="lp-pkg" data-stage data-spring="380" ref={rootRef}
         data-sel={selected === null ? "false" : "true"}
         role="group" aria-label="What Curivio adds beyond the daily lesson">
      <div className="lp-pkg-scroll">
        <div className="lp-pkg-rot">
          <div className="lp-pkg-idle">

            {/* the volume the cards sit in — floor, back wall and two rails.
                Without it four cards in space read as four loose rectangles;
                with it they read as filed in something. */}
            <div className="lp-pkg-vol" aria-hidden="true">
              <span className="lp-pkg-floor" />
              <span className="lp-pkg-back" />
              <span className="lp-pkg-rail lp-pkg-rail-l" />
              <span className="lp-pkg-rail lp-pkg-rail-r" />
            </div>

            {FEATURES.map((f, i) => {
              const Art = PKG_ART[i]
              const on = selected === i
              return (
                <div
                  key={f.n}
                  className={`lp-pkg-card ${f.ink}`}
                  style={{ "--i": i }}
                  data-on={on ? "true" : "false"}
                  data-hover={hovered === i ? "true" : "false"}
                  data-first={i === 0 ? "true" : undefined}
                  aria-hidden="true"
                >
                  <span className="lp-pkg-face">
                    {/* the strip is the part that stays exposed above the card
                        in front, so it alone has to identify the feature */}
                    <span className="lp-pkg-strip">
                      <span className="lp-pkg-tab">{f.n}</span>
                      <span className="lp-pkg-name">{PKG_SHORT[i]}</span>
                    </span>
                    <span className="lp-pkg-body">
                      <span className="lp-pkg-art"><Art /></span>
                      <span className="lp-pkg-reveal">{f.title}</span>
                    </span>
                  </span>
                </div>
              )
            })}

          </div>
        </div>
      </div>

      {/* the only interactive thing here — see the note on useLayoutEffect */}
      <div className="lp-pkg-hit">
        {FEATURES.map((f, i) => {
          const on = selected === i
          return (
            <button
              key={f.n}
              type="button"
              className="lp-pkg-hit-btn"
              style={bands ? bands[i] : undefined}
              data-on={on ? "true" : "false"}
              aria-pressed={on}
              aria-label={`${f.tag} — ${f.title}`}
              onClick={() => onSelect(on ? null : i)}
              onPointerEnter={() => setHovered(i)}
              onPointerLeave={() => setHovered(h => (h === i ? null : h))}
              onFocus={() => setHovered(i)}
              onBlur={() => setHovered(h => (h === i ? null : h))}
            />
          )
        })}
      </div>
    </div>
  )
}

/* ── THE HANDOFF ─────────────────────────────────────────────────────────
   262px of bare paper sat between the Day N row and the anatomy heading —
   and it is not just a gap, it is the one seam on the page where the
   argument changes scale: from "N days of a topic" to "what a single day is
   made of". So the filler is the transition itself: the last day's sheet,
   one stem out of it, splitting into the five moves waiting underneath.

   The five ends carry the ANATOMY inks in order, so the colours are already
   introduced by the time the list below names them.

   Drawn by `--near` rather than by a keyframe: it is the same pure function
   of scroll position the rest of the page uses, so it draws on the way down
   and un-draws on the way back up instead of firing once.                 */
const HANDOFF_FAN = [
  { x: 120, ink: "lp-i-blue" },    /* Evidence   */
  { x: 280, ink: "lp-i-moss" },    /* Mechanism  */
  { x: 440, ink: "lp-i-yellow" },  /* Comparison */
  { x: 600, ink: "lp-i-pink" },    /* Implication*/
  { x: 760, ink: "lp-i-soft" },    /* Sources    */
]

function ArcHandoff() {
  return (
    <div className="lp-seam" data-stage aria-hidden="true">
      <span className="lp-seam-card"><i /><i /></span>
      <span className="lp-seam-rule" />
      {/* rides the rule at a position that IS the scroll offset, so there is
         nothing to wait for — it moves the whole time you are moving */}
      <span className="lp-seam-bead" />
      <span className="lp-seam-fan">
        {HANDOFF_FAN.map((f, i) => (
          <b key={f.x} className={f.ink} style={{ "--i": i }} />
        ))}
      </span>
    </div>
  )
}

/* ── THE LESSON STACK ────────────────────────────────────────────────────
   The Editions page's interior sections are flat off-white — all their
   richness is one big, real, dimensional object per section. The anatomy
   section had 345px of empty column measured under its rail, and it is the
   one section whose subject IS a structure: five moves layered into one
   lesson. So: an exploded view, the technical-illustration idiom for
   "what this is made of".

   Five planes in isometric, one per move, bottom to top. The plane for the
   move you are reading lifts out of the stack and takes its accent colour —
   driven by the same `anatomyIdx` the rail and the blocks already use, so
   all three say the same thing at once. Cursor tilt via --mx/--my.        */
function LessonStack({ active }) {
  const W = 244, D = 42, STEP = 33, BASE = 214
  const plane = cy => `M8 ${cy} L${8 + W / 2} ${cy - D} L${8 + W} ${cy} L${8 + W / 2} ${cy + D} Z`
  return (
    <div className="lp-stack" data-tilt="300" data-tilt-hover aria-hidden="true">
      <svg viewBox="0 0 260 250" fill="none" focusable="false">
        {/* drawn bottom-first so upper planes overlap lower ones, which is
            what makes five flat rhombuses read as a stack */}
        {ANATOMY.map((a, i) => {
          const cy = BASE - i * STEP
          return (
            <g key={a.key} className={`lp-stack-sheet ${a.ink}`} data-on={i === active} style={{ "--i": i }}>
              <path className="lp-stack-face" d={plane(cy)} />
              {/* two ruled lines per sheet, parallel to its own edge, so each
                  plane reads as a page rather than as a blank tile */}
              <path className="lp-stack-rule" d={`M${8 + W * 0.3} ${cy + D * 0.28} L${8 + W * 0.72} ${cy - D * 0.14}`} />
              <path className="lp-stack-rule" d={`M${8 + W * 0.36} ${cy + D * 0.46} L${8 + W * 0.64} ${cy + D * 0.22}`} />
            </g>
          )
        })}
      </svg>
    </div>
  )
}

/* ── § 3 anatomy icons — one glyph per move, each drawn with a different
   gesture so the motion itself carries a little of the meaning: bars GROW
   (evidence accumulating), circles DRAW together (a mechanism connecting),
   the beam TIPS (a comparison being weighed), the arrow EXTENDS (a forward
   implication), the link DRAWS (a source resolving). All idle at low
   opacity and breathe gently (ambient, never stops); the block's own
   `data-active` — not a scroll trigger — draws them in (event, replays
   every time you return to a block, same model as the rest of the page). */
function IconEvidence({ className }) {
  return (
    <svg className={className} viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <line x1="4" y1="27" x2="28" y2="27" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" opacity=".35" />
      <rect className="lp-an-bar" x="7"  y="17" width="4.5" height="10" rx="1.2" fill="currentColor" style={{ "--bd": "0s" }} />
      <rect className="lp-an-bar" x="14" y="11" width="4.5" height="16" rx="1.2" fill="currentColor" style={{ "--bd": ".09s" }} />
      <rect className="lp-an-bar" x="21" y="6"  width="4.5" height="21" rx="1.2" fill="currentColor" style={{ "--bd": ".18s" }} />
    </svg>
  )
}
function IconMechanism({ className }) {
  return (
    <svg className={className} viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true">
      <circle className="lp-an-draw" cx="13" cy="16" r="9" pathLength="1" />
      <circle className="lp-an-draw" cx="21" cy="16" r="9" pathLength="1" style={{ "--dd": ".12s" }} />
    </svg>
  )
}
function IconComparison({ className }) {
  return (
    <svg className={className} viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" aria-hidden="true">
      <line x1="16" y1="6" x2="16" y2="25" />
      <line x1="10" y1="25" x2="22" y2="25" />
      <g className="lp-an-beam">
        <line x1="6" y1="11" x2="26" y2="11" />
        <path d="M6 11c0 2.5 1.8 4.5 4 4.5s4-2 4-4.5" opacity=".85" />
        <path d="M18 11c0 2.5 1.8 4.5 4 4.5s4-2 4-4.5" opacity=".85" />
      </g>
    </svg>
  )
}
function IconImplication({ className }) {
  return (
    <svg className={className} viewBox="0 0 32 32" fill="none" stroke="currentColor"
         strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path className="lp-an-draw" d="M7 23 23 7" pathLength="1" />
      <path className="lp-an-draw" d="M12 7h11v11" pathLength="1" style={{ "--dd": ".1s" }} />
    </svg>
  )
}
function IconSources({ className }) {
  return (
    <svg className={className} viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" aria-hidden="true">
      <path className="lp-an-draw" pathLength="1" d="M14 18a5.3 5.3 0 0 0 8 .6l3.7-3.7a5.3 5.3 0 0 0-7.5-7.5l-2.1 2.1" />
      <path className="lp-an-draw" pathLength="1" d="M18 14a5.3 5.3 0 0 0-8-.6l-3.7 3.7a5.3 5.3 0 0 0 7.5 7.5l2.1-2.1" style={{ "--dd": ".12s" }} />
    </svg>
  )
}

/* ═══════════════════════════════════════════════════════════════════════════
   HERO PANEL — three states, two transitions, looping.

     ① INPUT   the topic is typed, two files and a link attach, ⏎ is pressed
     ② WORK    the files are read, the web is searched, every source graded
     ③ OUTPUT  the lesson — with the link and the user's own PDF cited inline

   Everything visible is a pure function of `step`. No per-element timers, no
   imperative sequencing: the loop restarts by setting step back to 0, and
   still mode pins step to the last beat, which is a finished ③.

   Beats map to real nodes in feed_v2/graph.py — corpus_researcher reads the
   uploads with page-level provenance, web_researcher searches, source_ranker
   grades 0–1 and cuts, section_writer cites.
   ═════════════════════════════════════════════════════════════════════════ */

/* [scene, hold ms] — the index IS `step` */
const BEATS = [
  [1,  620],  //  0  empty field, caret blinking
  [1, 1150],  //  1  the topic types in
  [1,  470],  //  2  attach the PDF
  [1,  470],  //  3  attach the notes file
  [1,  640],  //  4  paste the link
  [1,  780],  //  5  ⏎
  [2,  900],  //  6  → ②  reading the PDF
  [2,  740],  //  7  reading the notes
  [2,  780],  //  8  web · source 1
  [2,  680],  //  9  web · source 2
  [2,  880],  // 10  web · source 3 → cut
  [2,  820],  // 11  tally
  [3,  950],  // 12  → ③  the headline is written
  [3, 1000],  // 13  ¶1 writes in, cited to the link
  [3, 1050],  // 14  ¶2 writes in, cited to the user's own page
  [3,  850],  // 15  Ask About / Explain Simply become available
  [3, 2200],  // 16  sources, hold before the loop
]
const LAST = BEATS.length - 1
const SCENE_LABEL = { 1: "New topic", 2: "Researching", 3: "Day 1 · ready" }
/* the beat at which the weak source is struck out, in the panel AND the corners */
const CUT_AT = 10

/* ── Ten topics, one picked at random per cycle ────────────────────────────
   The demo runs roughly every sixteen seconds, so a single fixed example goes
   stale within one scroll. Each entry carries its own uploads, its own graded
   web results and its own lesson, so nothing about a cycle is recycled except
   the shape. `pdf` is the file that ends up cited by page — that page number
   is the whole point of the third state.                                    */
const TOPICS = [
  { t: "AI Agents",
    pdf:  { name: "agent-patterns.pdf", meta: "24 pages · 61 chunks", chip: "24 pages", page: 14, score: 0.88 },
    note: { name: "my-notes.md", meta: "12 chunks", chip: "12 KB" },
    link: "arxiv.org/abs/2210.03629",
    web:  [["arxiv.org", 0.93], ["github.com", 0.81], ["agent-tools.blog", 0.31]],
    title: "What Separates an Agent From a Chatbot",
    p1: "An agent doesn't answer and stop — it plans, calls tools, and checks its own work before replying.",
    p2: ["Your own notes already name this the ", "observe–act loop", "."] },

  { t: "CRISPR editing",
    pdf:  { name: "crispr-review.pdf", meta: "31 pages · 78 chunks", chip: "31 pages", page: 9, score: 0.90 },
    note: { name: "lecture-notes.md", meta: "21 chunks", chip: "18 KB" },
    link: "nih.gov/pmc/PMC5478472",
    web:  [["nature.com", 0.94], ["nih.gov", 0.87], ["biohacker-daily.net", 0.29]],
    title: "Why CRISPR Sometimes Cuts Badly",
    p1: "The guide RNA finds the target, but the cell's own repair machinery decides what the edit becomes.",
    p2: ["Your lecture notes call the risky path ", "non-homologous end joining", "."] },

  { t: "Transformers",
    pdf:  { name: "attention-notes.pdf", meta: "16 pages · 44 chunks", chip: "16 pages", page: 6, score: 0.91 },
    note: { name: "reading-log.md", meta: "11 chunks", chip: "9 KB" },
    link: "arxiv.org/abs/1706.03762",
    web:  [["arxiv.org", 0.95], ["distill.pub", 0.88], ["ml-tips.blog", 0.34]],
    title: "Attention Is Just a Weighted Lookup",
    p1: "Every token asks every other how relevant it is, then averages what it hears, weighted by the answer.",
    p2: ["The step your notes flag as expensive is the ", "quadratic score matrix", "."] },

  { t: "Monetary policy",
    pdf:  { name: "macro-primer.pdf", meta: "52 pages · 130 chunks", chip: "52 pages", page: 28, score: 0.86 },
    note: { name: "seminar-notes.md", meta: "17 chunks", chip: "14 KB" },
    link: "federalreserve.gov/monetarypolicy",
    web:  [["federalreserve.gov", 0.92], ["imf.org", 0.84], ["tradingsignals.io", 0.27]],
    title: "Why Rate Hikes Take a Year to Bite",
    p1: "The policy rate moves today, but mortgages, loans and hiring plans reprice on their own slower clocks.",
    p2: ["Economists call that delay the ", "transmission lag", "."] },

  { t: "Battery chemistry",
    pdf:  { name: "cell-teardown.pdf", meta: "19 pages · 47 chunks", chip: "19 pages", page: 11, score: 0.89 },
    note: { name: "lab-notes.md", meta: "9 chunks", chip: "7 KB" },
    link: "nature.com/articles/s41560-023",
    web:  [["nature.com", 0.91], ["energy.gov", 0.86], ["ev-rumors.net", 0.30]],
    title: "What Actually Kills a Lithium Cell",
    p1: "Capacity fades because lithium locks into a growing surface film, not because the cell runs out of charge.",
    p2: ["Your teardown labels that film the ", "solid-electrolyte interphase", "."] },

  { t: "Roman logistics",
    pdf:  { name: "annals-notes.pdf", meta: "77 pages · 164 chunks", chip: "77 pages", page: 41, score: 0.84 },
    note: { name: "source-log.md", meta: "14 chunks", chip: "11 KB" },
    link: "cambridge.org/roman-studies/49",
    web:  [["cambridge.org", 0.90], ["jstor.org", 0.85], ["history-quickfacts.net", 0.33]],
    title: "How Rome Fed an Army 900 Miles Away",
    p1: "Grain moved by sea for a fraction of the cost of road haulage, so the supply map simply followed water.",
    p2: ["Historians call the resulting pattern the ", "tyranny of the cart", "."] },

  { t: "Sleep architecture",
    pdf:  { name: "sleep-lab.pdf", meta: "23 pages · 52 chunks", chip: "23 pages", page: 17, score: 0.87 },
    note: { name: "sleep-diary.md", meta: "8 chunks", chip: "6 KB" },
    link: "nih.gov/pmc/PMC6491852",
    web:  [["nih.gov", 0.93], ["nature.com", 0.88], ["sleep-hacks.blog", 0.28]],
    title: "Why 3am Waking Is Not Insomnia",
    p1: "Sleep runs in roughly ninety-minute cycles, and the seams between them are shallow enough to surface from.",
    p2: ["Your sleep-lab printout marks these as ", "brief cortical arousals", "."] },

  { t: "Rust ownership",
    pdf:  { name: "borrow-checker.pdf", meta: "11 pages · 28 chunks", chip: "11 pages", page: 7, score: 0.90 },
    note: { name: "rust-notes.md", meta: "19 chunks", chip: "15 KB" },
    link: "doc.rust-lang.org/book/ch04-01",
    web:  [["doc.rust-lang.org", 0.94], ["github.com", 0.83], ["rust-shortcuts.dev", 0.35]],
    title: "Ownership Is a Compile-Time Lease",
    p1: "Nothing is checked while the program runs — the compiler proves every borrow ends before the value does.",
    p2: ["The rule your notes keep tripping over is ", "one mutable borrow at a time", "."] },

  { t: "Ocean currents",
    pdf:  { name: "thermohaline.pdf", meta: "44 pages · 96 chunks", chip: "44 pages", page: 23, score: 0.88 },
    note: { name: "field-notes.md", meta: "13 chunks", chip: "10 KB" },
    link: "noaa.gov/education/ocean-currents",
    web:  [["noaa.gov", 0.92], ["nature.com", 0.87], ["climate-takes.net", 0.26]],
    title: "The Conveyor Belt Under the Atlantic",
    p1: "Cold, salty water sinking near Greenland pulls warm surface water north — that pull is what keeps Europe mild.",
    p2: ["The circulation your paper tracks is the ", "thermohaline overturning", "."] },

  { t: "Antibiotic resistance",
    pdf:  { name: "resistance-review.pdf", meta: "36 pages · 84 chunks", chip: "36 pages", page: 19, score: 0.91 },
    note: { name: "ward-notes.md", meta: "10 chunks", chip: "8 KB" },
    link: "who.int/antimicrobial-resistance",
    web:  [["who.int", 0.94], ["nih.gov", 0.89], ["supplement-news.net", 0.24]],
    title: "Resistance Spreads Sideways, Not Down",
    p1: "Bacteria hand resistance genes to unrelated species directly, so it travels far faster than inheritance would.",
    p2: ["The mechanism your review names is ", "horizontal gene transfer", "."] },
]

/* Where the four corner cards sit and how fast they drift. `d` is depth:
   higher = nearer the viewer = moves more on BOTH cursor and scroll. Layout is
   fixed; the labels and scores come from whichever topic is running, so the
   corners and the panel always agree about what was found and what was cut. */
/* The two on the right sit against the photograph and are deliberately at
   opposite depths: 0.45 is nearly ON the photographic plane (--d .3) so it
   drifts with the scene, while 1.7 is well in front of the interface (.95) and
   moves fastest of anything on the stage. Between them the interface reads as
   the middle of a stack rather than the top of one. */
const FLOAT_AT = [
  { d: 0.55, dur: "12s",   delay: "0s",   at: { top: "18%", left: "2%"  } },
  { d: 1.35, dur: "10s",   delay: ".9s",  at: { top: "64%", left: "1%"  } },
  { d: 0.45, dur: "13.5s", delay: "1.7s", at: { top: "70%", right: "7%" } },
  /* above the panel's top edge, not beside it: at 1366 `top: 15%` put this one
     straight across the panel's own header row */
  { d: 1.7,  dur: "11s",   delay: ".4s",  at: { top: "8%", right: "5%" } },
]
const floatersFor = tp => [
  { ...FLOAT_AT[0], id: "w0", label: tp.web[0][0], score: tp.web[0][1].toFixed(2), ink: "lp-i-blue" },
  { ...FLOAT_AT[1], id: "w1", label: tp.web[1][0], score: tp.web[1][1].toFixed(2), ink: "lp-i-blue" },
  { ...FLOAT_AT[2], id: "up", label: tp.pdf.name,  score: tp.pdf.score.toFixed(2), ink: "lp-i-moss" },
  { ...FLOAT_AT[3], id: "w2", label: tp.web[2][0], score: tp.web[2][1].toFixed(2), ink: "lp-i-pink", cut: true },
]

function Cite({ n, on }) {
  return <sup className="lp-cite" style={{ "--on": on }}>{n}</sup>
}

function HeroPanel({ step, tp }) {
  const scene = BEATS[step][0]
  const on = n => (step >= n ? 1 : 0)

  /* The typewriter clips a nowrap span with max-width, so the caret travels
     with the last character. Topics differ in length, so the target width is
     measured rather than estimated — an estimate either clips the last letter
     or parks the caret in empty space. */
  const typedRef = useRef(null)
  const [typedW, setTypedW] = useState(0)
  useEffect(() => {
    const measure = () => typedRef.current && setTypedW(typedRef.current.scrollWidth)
    measure()
    document.fonts?.ready.then(measure)   // re-measure once the serif lands
  }, [tp])

  /* played scenes exit upward, unplayed ones wait below — so the stack always
     travels one direction and the panel reads as one continuous take */
  const sceneProps = n => ({
    className: "lp-scene",
    style: { "--on": n === scene ? 1 : 0, "--dir": n < scene ? "-30px" : "30px" },
  })

  const attach = [
    { name: tp.pdf.name,  meta: tp.pdf.chip,  link: false },
    { name: tp.note.name, meta: tp.note.chip, link: false },
    { name: tp.link,      meta: "",           link: true  },
  ]

  return (
    <div
      className="lp-panel"
      role="img"
      aria-label={`Curivio in three steps. One: you name a topic — ${tp.t} — and attach two files and a link. Two: it reads your files, searches the web, and grades every source, cutting the weak one. Three: it writes the lesson, with each claim cited back to the link or to the exact page of your own PDF, and offers to Ask About or Explain Simply any part of it.`}
    >
      <div className="lp-panel-bar">
        <span className="lp-live" style={{ color: "var(--moss)" }} />
        <span className="lp-panel-title">Curivio</span>
        <span className="lp-panel-scene" key={scene}>{SCENE_LABEL[scene]}</span>
      </div>
      <span className="lp-scrub" style={{ "--v": step / LAST }} />

      <div className="lp-scenes">

        {/* ① INPUT ─────────────────────────────────────────────────────── */}
        <div {...sceneProps(1)}>
          <div className="lp-field">
            <span ref={typedRef} className="lp-typed" data-on={step >= 1}
                  style={{ "--tw": typedW ? `${typedW}px` : "none" }}>{tp.t}</span>
            <span className="lp-caret">▏</span>
          </div>
          <div className="lp-attached">
            {attach.map((a, i) => (
              <span key={a.name} className="lp-attach" style={{ "--on": on(2 + i) }}>
                {a.link ? <IconLink className="lp-ic" /> : <IconDoc className="lp-ic" />}
                <span className="lp-attach-name">{a.name}</span>
                {a.meta && <span className="lp-attach-meta">{a.meta}</span>}
              </span>
            ))}
          </div>
          <div className="lp-enter-row">
            {/* drawn, not typed: U+23CE has no glyph in Atkinson Hyperlegible and
                the fallback renders it as a stray letterform */}
            <span className="lp-key" data-on={step >= 5}>
              Enter
              <svg className="lp-key-ret" viewBox="0 0 12 12" fill="none" stroke="currentColor"
                   strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M10.5 2v3.2a1.3 1.3 0 0 1-1.3 1.3H2.2M4.6 4.1 2.1 6.5l2.5 2.4" />
              </svg>
            </span>
          </div>
        </div>

        {/* ② WORK ──────────────────────────────────────────────────────── */}
        <div {...sceneProps(2)}>
          {/* each head arrives with its own first row, not ahead of it */}
          <p className="lp-scene-head" style={{ "--on": on(6) }}>Your files</p>
          {[tp.pdf, tp.note].map((f, i) => (
            <div key={f.name} className="lp-row lp-i-moss" style={{ "--on": on(6 + i) }}>
              <span className="lp-row-name">{f.name}</span>
              {/* sweeping while this file is being read, solid once it is done */}
              <span className="lp-scan" data-on={step === 6 + i} data-done={step > 6 + i} />
              <span className="lp-row-meta">{f.meta}</span>
            </div>
          ))}

          <p className="lp-scene-head lp-scene-head-2" style={{ "--on": on(8) }}>The live web</p>
          {tp.web.map(([name, score], i) => (
            <div key={name} className={`lp-row ${i === 2 ? "lp-i-pink" : "lp-i-blue"}`}
                 style={{ "--on": on(8 + i) }} data-cut={i === 2 && step >= CUT_AT}>
              <span className="lp-row-name">{name}</span>
              <span className="lp-bar"><i style={{ "--v": score, "--on": on(8 + i) }} /></span>
              <span className="lp-row-score">{score.toFixed(2)}</span>
              <span className="lp-row-verdict">{i === 2 ? "cut" : "kept"}</span>
            </div>
          ))}

          <p className="lp-tally" style={{ "--on": on(11) }}>4 of 5 sources kept</p>
        </div>

        {/* ③ OUTPUT ────────────────────────────────────────────────────── */}
        <div {...sceneProps(3)}>
          <h3 className="lp-lesson-t" style={{ "--on": on(12) }}>{tp.title}</h3>
          <p className="lp-lesson-p" style={{ "--on": on(13) }}>
            {tp.p1}<Cite n="1" on={on(13)} />
          </p>
          <p className="lp-lesson-p" style={{ "--on": on(14) }}>
            {tp.p2[0]}
            <span className={`lp-mark lp-mark-moss ${step >= 14 ? "lp-mark-on" : ""}`}>{tp.p2[1]}</span>
            {tp.p2[2]}<Cite n="2" on={on(14)} />
          </p>

          <div className="lp-lesson-foot" style={{ "--on": on(15) }}>
            {/* the two card actions the app actually ships — every lesson can be
                reopened in chat at either depth */}
            <div className="lp-actions">
              <span className="lp-act" style={{ "--on": on(15) }}>Ask About</span>
              <span className="lp-act" style={{ "--on": on(15), "--i": 1 }}>Explain Simply</span>
            </div>
            <div className="lp-cites">
              <span style={{ "--on": on(16) }}><b>1</b><IconLink className="lp-ic" />{tp.link}</span>
              <span style={{ "--on": on(16) }}><b>2</b><IconDoc className="lp-ic" />{tp.pdf.name} · p.{tp.pdf.page}</span>
            </div>
          </div>
        </div>

      </div>
    </div>
  )
}

/* ── § 3 anatomy: labels only, the blocks carry the meaning ──────────────── */
const ANATOMY = [
  { key: "evidence",   label: "Evidence",    ink: "lp-i-blue",  icon: IconEvidence,
    body: "AI image recognition can now classify material phases and predict toxicity responses, turning static microscopy data into performance models." },
  { key: "mechanism",  label: "Mechanism",   ink: "lp-i-moss",  icon: IconMechanism,
    body: "Feeding dissolution and stability data into generative models creates a language for a drug's physical behaviour." },
  { key: "comparison", label: "Comparison",  ink: "lp-i-yellow", icon: IconComparison,
    body: "Traditional: marketing works from abstract brand messaging.\nIntegrated: models map microscopic behaviour to clinical benefit.",
    mark: "models map microscopic behaviour to clinical benefit" },
  { key: "implication",label: "Implication", ink: "lp-i-pink",  icon: IconImplication,
    body: "Teams that break the wall between R&D and marketing capture a first-mover advantage — if regulatory can validate it." },
  { key: "sources",    label: "Sources",     ink: "lp-i-soft",  icon: IconSources,
    body: "Not a bibliography at the bottom. Every line above is already linked to the page it came from." },
]

/* ── § 4 the arc: the loop and the three-week payoff, one list ─────────────
   These were two sections — a 01-04 mechanism list and a Day 1/7/21 example
   list — with the same heading size and the same rhythm, so the page said one
   thing twice. They are now one row per milestone: the day number is the big
   numeral, `step` is what the loop did that day, and the lesson underneath is
   what it produced. Nothing from either list was dropped; the four steps are
   spread across the three rows in the order they actually happen.          */
const ARC = [
  { n: "01", day: "Day 1", badge: "Foundations", ink: "lp-i-soft", mk: "",
    step: ["You name the topic. It reads your files and the live web, ", "grades every source", ", and writes the lesson."],
    title: "Qubits and Superposition",
    mark: "A qubit isn't just 0 or 1", rest: " — it can be both at once, until measured." },
  { n: "07", day: "Day 7", badge: "Connections", ink: "lp-i-blue", mk: "lp-mark-blue",
    step: ["Fifteen minutes a day. ", "Ask About", " anything, or have it ", "Explain Simply", "."],
    title: "How Quantum Gates Work",
    mark: "Gates manipulate probability", rest: " before collapsing state. Entanglement coordinates at a distance." },
  { n: "21", day: "Day 21", badge: "Real-world lens", ink: "lp-i-moss", mk: "lp-mark-moss",
    step: ["Each day assumes what yesterday established. ", "Nothing resets", "."],
    title: "Why Advantage Is Years Away",
    mark: "Error correction is the unsolved core", rest: ". Noisy qubits can't hold a computation long enough — yet." },
  /* Day N, because nothing ends on 21. The numeral is literally N, so the
     column of 01 / 07 / 21 / N says it before the copy does. */
  { n: "N", day: "Day N", badge: "For as long as you want", ink: "lp-i-yellow", mk: "lp-mark-yellow",
    step: ["Three weeks is not a finish line. ", "Nothing closes", " — keep going, or start a second topic beside it."],
    title: "Wherever You Take It Next",
    mark: "You decide when a topic is done", rest: " — add a paper on day 40 and the arc simply carries on from there." },
]

/* ═══════════════════════════════════════════════════════════════════════════
   § 5  BEYOND THE LESSON — four live feature demos

   Reference: anime.js's docs page (Awwwards Product Honors) makes each
   feature block demonstrate the feature itself rather than describe it, and
   Zentry numbers its product blocks so a long stack still reads as a
   sequence. Both are used here: numbered rows, and every row's panel is a
   working miniature of the thing the row is about.

   ONE 900ms tick drives all four. Each demo takes it modulo its own period
   (14 / 10 / 8 / 12), so they never march in lockstep — four independent-
   looking loops out of one timer. Still mode pins each to a FINISHED phase,
   not phase 0: frozen mid-gesture is the failure mode (same bug the anatomy
   icons had).

   Everything shown is real: the Unpack popover's three actions and its four
   languages are UnpackListener.jsx's; the offline rows are the stores
   backgroundSync.js actually fills.
   ═════════════════════════════════════════════════════════════════════════ */
const FEAT_TICK_MS = 900

/* ── 01 · Unpack ─────────────────────────────────────────────────────────── */
const UNPACK = {
  before: "Capacity fades because lithium locks into a growing surface film — the ",
  term:   "solid-electrolyte interphase",
  after:  " — not because the cell runs out of charge.",
  def:    "A thin film that forms on a battery electrode during its first charges.",
  ctx:    "Here it is the reason for the fade: the film keeps growing and traps lithium for good.",
  hi:     "ठोस-इलेक्ट्रोलाइट अंतरापृष्ठ",
}
const UNPACK_ACTS = ["Explain", "Translate", "Read Aloud"]
const UNPACK_LANGS = ["Hindi", "Gujarati", "French", "German"]

function DemoUnpack({ p }) {
  /* 0 plain · 1 selection · 2 menu · 3-7 explain · 8 menu · 9 languages
     10 translation · 11 menu · 12-13 audio */
  const mode = p <= 2 || p === 8 || p === 11 ? "menu"
             : p <= 7  ? "explain"
             : p === 9 ? "lang"
             : p === 10 ? "translate"
             : "audio"
  /* which action the cursor is on — the press that causes the next phase */
  const armed = p === 2 ? 0 : p === 8 ? 1 : p === 11 ? 2 : -1

  return (
    <div className="lp-fbody lp-up" role="img"
         aria-label="Selecting a term in a lesson opens a small Unpack popover with three actions: Explain gives the general definition and what the term means in this sentence, Translate renders it in Hindi, Gujarati, French or German, and Read Aloud speaks it.">
      <p className="lp-up-para">
        {UNPACK.before}
        <span className={`lp-mark lp-mark-blue ${p >= 1 ? "lp-mark-on" : ""}`}>{UNPACK.term}</span>
        {UNPACK.after}
      </p>

      <div className="lp-pop lp-fx" style={{ "--on": p >= 2 ? 1 : 0 }}>
        <div className="lp-pop-bar"><span>Unpack</span><i aria-hidden>×</i></div>

        {mode === "menu" && (
          <div className="lp-pop-menu">
            {UNPACK_ACTS.map((a, i) => (
              <span key={a} className="lp-pop-btn" data-armed={i === armed}>{a}</span>
            ))}
          </div>
        )}

        {mode === "explain" && (
          <div className="lp-pop-body">
            {p <= 4 ? (
              <span className="lp-skel" aria-hidden><i /><i /><i /></span>
            ) : (
              <>
                <p className="lp-pop-def lp-fx" style={{ "--on": p >= 5 ? 1 : 0 }}>{UNPACK.def}</p>
                {/* the streamed half — caret while it is still arriving */}
                <p className="lp-pop-ctx lp-fx" style={{ "--on": p >= 6 ? 1 : 0 }}>
                  {UNPACK.ctx}{p === 6 && <span className="lp-caret lp-pop-caret">▏</span>}
                </p>
              </>
            )}
          </div>
        )}

        {mode === "lang" && (
          <div className="lp-pop-body lp-lang">
            {UNPACK_LANGS.map((l, i) => (
              <span key={l} className="lp-langc" data-armed={i === 0} style={{ "--i": i }}>{l}</span>
            ))}
          </div>
        )}

        {mode === "translate" && (
          <div className="lp-pop-body">
            <p className="lp-tr">{UNPACK.hi}</p>
            <p className="lp-pop-fine">Hindi</p>
          </div>
        )}

        {mode === "audio" && (
          <div className="lp-pop-body lp-audio">
            <span className="lp-wave" aria-hidden>
              {[...Array(11)].map((_, i) => <i key={i} style={{ "--bd": `${i * 0.07}s` }} />)}
            </span>
            <span className="lp-pop-fine">0:02</span>
          </div>
        )}
      </div>
    </div>
  )
}

/* ── 02 · Chat ───────────────────────────────────────────────────────────── */
function DemoChat({ p }) {
  const on = n => (p >= n ? 1 : 0)
  return (
    <div className="lp-fbody lp-chat" role="img"
         aria-label="A question about a lesson is asked in chat. Curivio searches the live web, shows the two sources it used, answers in two lines with a citation, and a PDF can be attached to the next question.">
      <div className="lp-cbub lp-fx" style={{ "--on": on(1) }}>
        Why is quantum advantage still years away?
      </div>

      <div className="lp-tool lp-fx" style={{ "--on": on(2) }}>
        <span className="lp-spin" data-on={p === 2} aria-hidden />
        {p >= 3 ? "Searched the web" : "Searching the web"}
      </div>
      <div className="lp-srcs">
        {["arxiv.org", "nature.com"].map((s, i) => (
          <span key={s} className="lp-srcchip lp-fx" style={{ "--on": on(3), "--i": i }}>{s}</span>
        ))}
      </div>

      <p className="lp-cline lp-fx" style={{ "--on": on(4) }}>
        Today's machines lose the state faster than a long computation needs it.
      </p>
      <p className="lp-cline lp-fx" style={{ "--on": on(5) }}>
        Correcting that costs roughly a thousand physical qubits per usable{" "}
        {/* the superscript must not be able to wrap onto a line of its own —
            alone on the next line it reads as a stray box, not a citation */}
        <span style={{ whiteSpace: "nowrap" }}>one.<Cite n="1" on={on(5)} /></span>
      </p>

      <div className="lp-comp">
        <span className="lp-comp-att lp-fx" style={{ "--on": on(7) }}>
          <IconDoc className="lp-ic" />lecture-notes.pdf
        </span>
        <span className="lp-comp-row">
          <span className="lp-comp-ph">Ask anything…</span>
          <span className="lp-comp-send" aria-hidden><Arrow className="lp-comp-arrow" /></span>
        </span>
      </div>
    </div>
  )
}

function IconBookmark({ className, on }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="none" stroke="currentColor"
         strokeWidth="1.4" strokeLinejoin="round" aria-hidden="true">
      <path d="M5 3.2h10v13.6l-5-3.6-5 3.6z" fill={on ? "currentColor" : "none"} fillOpacity=".9" />
    </svg>
  )
}

/* ── 03 · Keep ───────────────────────────────────────────────────────────── */
function DemoKeep({ p }) {
  const on = n => (p >= n ? 1 : 0)
  const filled = p >= 4 ? 7 : 6
  return (
    <div className="lp-fbody lp-tiles" role="img"
         aria-label="Four places things you keep end up: a bookmark filed into a named collection, a card pushed to the Read Later queue, a note written on Day 7 and searchable across projects, and a dashboard counting a seven-day streak.">
      <div className="lp-tile lp-i-yellow lp-fx lp-fx-dim" style={{ "--on": on(1) }}>
        <span className="lp-tile-h">Bookmark</span>
        <IconBookmark className="lp-tile-glyph" on={p >= 1} />
        <span className="lp-tile-chip lp-fx" style={{ "--on": on(5) }}>Quantum computing</span>
      </div>

      <div className="lp-tile lp-i-blue lp-fx lp-fx-dim" style={{ "--on": on(2) }}>
        <span className="lp-tile-h">Read Later</span>
        {/* remounted on the change so the new count flips in rather than swapping */}
        <span className="lp-cnt" key={p >= 2 ? "b" : "a"}>{p >= 2 ? 4 : 3}</span>
        <span className="lp-tile-sub">queued for tonight</span>
      </div>

      <div className="lp-tile lp-i-moss lp-fx lp-fx-dim" style={{ "--on": on(3) }}>
        <span className="lp-tile-h">Note</span>
        <span className="lp-notetxt" data-on={p >= 3}>check this against the 2024 review</span>
        <span className="lp-tile-sub">Day 7 · searchable everywhere</span>
      </div>

      <div className="lp-tile lp-i-pink lp-fx lp-fx-dim" style={{ "--on": on(4) }}>
        <span className="lp-tile-h">Dashboard</span>
        <span className="lp-cnt" key={filled}>{filled}<i>d</i></span>
        <span className="lp-sbars" aria-hidden>
          {[...Array(7)].map((_, i) => (
            <i key={i} data-on={i < filled} style={{ "--bd": `${i * 0.05}s` }} />
          ))}
        </span>
      </div>
    </div>
  )
}

/* ── 04 · Offline ────────────────────────────────────────────────────────── */
/* the five stores backgroundSync.js fills, in the order it fills them */
const OFF_ROWS = ["Today's package", "Dashboard", "Bookmarks", "Read Later", "Chats"]

function IconSignal({ off }) {
  return (
    <svg className="lp-sig" viewBox="0 0 22 22" fill="none" stroke="currentColor"
         strokeWidth="1.5" strokeLinecap="round" aria-hidden="true" data-off={off}>
      <path className="lp-sig-arc" d="M2.6 8.4a13 13 0 0 1 16.8 0" style={{ "--ad": ".1s" }} />
      <path className="lp-sig-arc" d="M5.6 12a8.6 8.6 0 0 1 10.8 0" style={{ "--ad": ".05s" }} />
      <path className="lp-sig-arc" d="M8.6 15.5a4.1 4.1 0 0 1 4.8 0" style={{ "--ad": "0s" }} />
      <circle cx="11" cy="18.6" r=".9" fill="currentColor" stroke="none" className="lp-sig-arc" />
      {/* drawn twice: a thick stroke in the panel's own colour first, then the
          real one on top. Without the casing the diagonal merges into the arcs
          and the whole glyph reads as a pen rather than a signal that was cut. */}
      <path className="lp-sig-slash lp-sig-case" d="M4.5 17.5 17.5 4.5" pathLength="1" />
      <path className="lp-sig-slash" d="M4.5 17.5 17.5 4.5" pathLength="1" />
    </svg>
  )
}

function DemoOffline({ p }) {
  /* 0 idle · 1-5 each store written · 6 synced · 7-10 signal gone, still
     readable · 11 back online */
  const offline = p >= 7 && p <= 10
  const state = p === 0 ? "Connecting"
              : p <= 5  ? "Saving to this device"
              : p === 6 ? "Synced"
              : offline ? "Offline — still works"
              : "Back online · re-syncing"

  return (
    <div className="lp-fbody lp-off" role="img" data-offline={offline}
         aria-label="Curivio writes your packages, dashboard, bookmarks, Read Later queue and chats to your device in the background. When the signal drops the app keeps opening lessons from the device, and it re-syncs by itself once you are back online.">
      <div className="lp-off-top">
        <IconSignal off={offline} />
        <span className="lp-off-state" key={state}>{state}</span>
        <span className="lp-off-mark" aria-hidden>
          {p === 6 || p === 11
            ? <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                   strokeLinecap="round" strokeLinejoin="round">
                <path d="M20 16.2A4.5 4.5 0 0 0 17.5 8h-1.8A7 7 0 1 0 4 15" />
                <polyline points="9 15 12 18 16 11" />
              </svg>
            : <span className="lp-live" style={{ color: "currentColor" }} />}
        </span>
      </div>

      <div className="lp-off-rows">
        {OFF_ROWS.map((r, i) => (
          <div key={r} className="lp-orow lp-fx lp-fx-dim" style={{ "--on": p >= 1 + i ? 1 : 0 }}>
            <span className="lp-orow-name">{r}</span>
            <span className="lp-orow-line" />
            <span className="lp-odot" data-on={p >= 1 + i} />
          </div>
        ))}
      </div>

      {/* the point of the whole block: with the signal gone, a lesson still opens */}
      <div className="lp-ocard lp-fx" style={{ "--on": offline ? 1 : 0 }}>
        <span className="lp-ocard-t">Why Advantage Is Years Away</span>
        <span className="lp-ocard-m">Day 21 · opened from this device</span>
      </div>
    </div>
  )
}

const FEATURES = [
  { n: "01", tag: "Unpack", ink: "lp-i-blue", period: 14, still: 6, Demo: DemoUnpack,
    title: "Any word, unpacked where you are",
    body: "Select anything in a lesson and a popover opens on the spot — no new tab, no losing your place.",
    list: [
      ["Explain", " — the plain definition, then what the term means in this exact sentence."],
      ["Translate", " — Hindi, Gujarati, French or German."],
      ["Read Aloud", " — for the words you can read but not say."],
    ] },

  { n: "02", tag: "Chat", ink: "lp-i-moss", period: 10, still: 5, Demo: DemoChat,
    title: "Ask past the lesson",
    body: "Every card opens into a conversation that already knows what you just read.",
    list: [
      ["Ask About", " or ", "Explain Simply", " — the same card, at whichever depth you need."],
      ["Attach a PDF or an image", " and ask about that instead."],
      ["Live web search", " when a question outruns your files, with the sources it used shown."],
    ] },

  { n: "03", tag: "Bookmarks · Read Later · Notes", ink: "lp-i-yellow", period: 8, still: 5, Demo: DemoKeep,
    title: "Nothing you keep goes missing",
    body: "Four small habits, one home each — and a dashboard that quietly keeps count.",
    list: [
      ["Collections", " you name yourself, with a colour and a description."],
      ["Read Later", " for the card you want tonight rather than now."],
      ["Notes", " on any day, searchable across every project at once."],
      ["A dashboard", " — streak, cards read, projects running."],
    ] },

  { n: "04", tag: "Offline", ink: "lp-i-pink", period: 12, still: 8, Demo: DemoOffline,
    title: "Works on the train",
    body: "Everything you have opened is written to your device in the background. No download button, nothing to remember.",
    list: [
      ["Whole lessons", ", not titles — packages, dashboard, bookmarks, Read Later and chats."],
      ["No signal, no difference", " — the app opens and reads exactly the same."],
      ["It re-syncs itself", " the moment you are back."],
    ] },
]

const MARQUEE = [
  "A course that ignores what you already know",
  "Forty tabs and no path through them",
  "A chatbot that forgets by Thursday",
  "Bookmarks you will never reopen",
]

/* ═══════════════════════════════════════════════════════════════════════════ */

export default function LandingPage({ onShowAuth, isAuthenticated = false, onEnterApp }) {
  const root       = useRef(null)
  const hero       = useRef(null)
  const band       = useRef(null)
  const marquee    = useRef(null)

  const [motionOn, setMotionOn] = useState(resolveMotion)
  const [step, setStep] = useState(0)
  const [topicIdx, setTopicIdx] = useState(() => Math.floor(Math.random() * TOPICS.length))
  const [anatomyIdx, setAnatomyIdx] = useState(0)
  const [tick, setTick] = useState(0)
  const [theme, setTheme] = useState(resolveTheme)
  const [secIdx, setSecIdx] = useState(0)
  /* which package card is pulled out of the stack, or null */
  const [pkgSel, setPkgSel] = useState(null)

  const topic = TOPICS[topicIdx]

  /* Click away, or Escape, puts the card back. Without this the only way out
     of a selection is to hit the same card again, which nobody discovers. */
  useEffect(() => {
    if (pkgSel === null) return
    const onDown = e => { if (!e.target.closest?.(".lp-pkg")) setPkgSel(null) }
    const onKey  = e => { if (e.key === "Escape") setPkgSel(null) }
    document.addEventListener("pointerdown", onDown)
    document.addEventListener("keydown", onKey)
    return () => {
      document.removeEventListener("pointerdown", onDown)
      document.removeEventListener("keydown", onKey)
    }
  }, [pkgSel])

  const setActive = useRef({
    anatomy: i => setAnatomyIdx(i),
    section: i => setSecIdx(i),
  }).current

  const refs = useRef({ root, hero, band, marquee }).current

  useMotionEngine(refs, setActive, motionOn)

  /* AMBIENT: the three-state demo never stops, regardless of scroll or pointer.
     Still mode pins it to the last beat — a finished lesson, not a frozen
     half-played animation. */
  useEffect(() => {
    if (!motionOn) { setStep(LAST); return }
    const t = setTimeout(() => {
      if (step < LAST) { setStep(step + 1); return }
      /* +1 + rand(n-1) mod n lands anywhere except where we already are, so no
         topic ever plays twice in a row */
      setTopicIdx(i => (i + 1 + Math.floor(Math.random() * (TOPICS.length - 1))) % TOPICS.length)
      setStep(0)
    }, BEATS[step][1])
    return () => clearTimeout(t)
  }, [step, motionOn])

  /* AMBIENT: one tick for all four § 5 demos. Each takes it modulo its own
     period, so four loops of different lengths come out of one timer and the
     block never falls into a single synchronised rhythm. */
  useEffect(() => {
    if (!motionOn) return
    const id = setInterval(() => setTick(t => t + 1), FEAT_TICK_MS)
    return () => clearInterval(id)
  }, [motionOn])

  /* follow the OS if the visitor has not made an explicit choice */
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-reduced-motion: reduce)")
    if (!mq) return
    const onChange = () => { if (!storedMotion()) setMotionOn(!mq.matches) }
    mq.addEventListener("change", onChange)
    return () => mq.removeEventListener("change", onChange)
  }, [])

  const toggleTheme = () => {
    setTheme(t => {
      const next = t === "dark" ? "light" : "dark"
      try { localStorage.setItem(THEME_KEY, next) } catch {}
      return next
    })
  }

  const toggleMotion = () => {
    setMotionOn(v => {
      const next = !v
      try { localStorage.setItem(MOTION_KEY, next ? "on" : "off") } catch {}
      return next
    })
  }

  const ctaLabel = isAuthenticated ? "Open app" : "Start learning"
  const ctaAction = isAuthenticated ? onEnterApp : onShowAuth

  return (
    <div ref={root} className="lp min-h-screen" data-motion={motionOn ? "on" : "off"} data-theme={theme}>
      <div className="lp-grain" aria-hidden />
      {/* the stock itself — a faint lattice across the whole page, drifting.
          The complaint was that the background read as one flat colour; the
          hero already had ruled paper and nothing below it did. This is the
          same idea at a third of the strength, page-wide, so the paper has a
          weave everywhere instead of only in the first screen. */}
      <div className="lp-weave" aria-hidden />
      {/* trim marks down both gutters — measured 144px of unused margin either
          side at 1440. Registration ticks are what a printed sheet has there. */}
      <GutterRail active={secIdx} />
      <span className="lp-edge lp-edge-l" aria-hidden />
      <span className="lp-edge lp-edge-r" aria-hidden />

      {/* ══ NAV ══ */}
      {/* blur/tint owned by landing.css — Tailwind's backdrop-blur-* would
          overwrite the whole backdrop-filter and drop the saturation */}
      <nav className="lp-nav sticky top-0 z-50">
        <div className="max-w-6xl mx-auto px-5 sm:px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <LogoSlot size={30} />
            <span className="lp-ui select-none" style={{ fontWeight: 700, fontSize: "16px" }}>Curivio</span>
          </div>
          <div className="flex items-center gap-5">
            <a href="#how" className="lp-link hidden sm:block" style={{ fontSize: "14px" }}>How it works</a>
            <button
              type="button"
              onClick={toggleTheme}
              className="lp-theme"
              aria-pressed={theme === "dark"}
              title={theme === "dark" ? "Switch to light" : "Switch to dark"}
              aria-label={theme === "dark" ? "Switch to light" : "Switch to dark"}
            >
              {theme === "dark" ? (
                <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5"
                     strokeLinecap="round" aria-hidden="true">
                  <circle cx="10" cy="10" r="3.6" />
                  <path d="M10 2.2v1.6M10 16.2v1.6M17.8 10h-1.6M3.8 10H2.2M15.5 4.5l-1.1 1.1M5.6 14.4l-1.1 1.1M15.5 15.5l-1.1-1.1M5.6 5.6 4.5 4.5" />
                </svg>
              ) : (
                <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5"
                     strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M16.2 12.3A6.8 6.8 0 0 1 7.7 3.8a6.9 6.9 0 1 0 8.5 8.5z" />
                </svg>
              )}
            </button>
            <button onClick={ctaAction} className="lp-btn flex items-center gap-1.5 px-4 py-2 rounded-md" style={{ fontSize: "14px" }}>
              {ctaLabel}
              <Arrow className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
        <span className="lp-progress" style={{ "--w": "var(--read)" }} aria-hidden />
      </nav>

      {/* ══ § 1 HERO — five depth layers ══ */}
      <section ref={hero} className="lp-hero lp-above">
        <div className="lp-stage">
          <div className="lp-stage-inner">

            {/* L0 — paper rules, slowest, ambient drift */}
            <div className="lp-l lp-rules" style={{ "--d": .12 }} aria-hidden />
            {/* L1 — cursor lamp */}
            <div className="lp-lamp" aria-hidden />

            {/* L2 — floating graded sources, each at its own depth. They cut on
                the same beat the panel cuts, so corners and demo stay in step. */}
            {floatersFor(topic).map(f => (
              <div key={f.id} data-prox
                   className={`lp-l lp-src ${f.ink}`}
                   data-rejected={f.cut && step >= CUT_AT ? "true" : "false"}
                   style={{ ...f.at, "--d": f.d,
                            /* --par-x/y, not literals: the cards and .lp-l layers
                               have to share one parallax reach or they visibly
                               disagree about how far the cursor moved */
                            transform: `translate3d(calc(var(--mx) * ${f.d} * var(--par-x) + var(--pxo, 0px)), calc(var(--my) * ${f.d} * var(--par-y) + var(--sp) * ${f.d} * -150px + var(--pyo, 0px)), 0)` }}
                   aria-hidden>
                <span className={`lp-src-float ${f.cut && step >= CUT_AT ? "lp-src-cut" : ""}`} style={{ color: "var(--ink-soft)" }}>{f.label}</span>
                <span className={`lp-src-score ${f.cut && step >= CUT_AT ? "lp-src-cut" : ""}`}>{f.score}</span>
              </div>
            ))}

            <div className="relative w-full max-w-6xl mx-auto px-5 sm:px-6 grid lg:grid-cols-[minmax(0,1fr)_minmax(0,1.02fr)] gap-10 lg:gap-14 items-center">

              {/* L4 — headline, nearest the viewer, moves most.
                  Three lines, three different jobs: who it is for, the promise,
                  the mechanism. None of them restates another. */}
              <div className="lp-l" style={{ "--d": 1.9 }}>
                <p className="lp-eyebrow lp-fade-up mb-4" style={{ "--i": 0 }}>
                  For the thing you keep meaning to learn properly
                </p>
                <h1 className="lp-display mb-6">
                  <span className="lp-word" style={{ "--i": 0 }}><span>One topic.</span></span><br />
                  <span className="lp-word" style={{ "--i": 1 }}>
                    <span><span className="lp-mark lp-mark-on">One lesson.</span></span>
                  </span><br />
                  <span className="lp-word" style={{ "--i": 2 }}>
                    <span><span className="lp-mark lp-mark-on">Every day.</span></span>
                  </span>
                </h1>
                <p className="lp-lead lp-fade-up max-w-lg" style={{ "--i": 3 }}>
                  Name a topic, tell the agent. It grades every source in front
                  of you, and cites each claim back to its page.
                </p>
                <p className="lp-sub lp-fade-up mt-4 max-w-lg" style={{ "--i": 4 }}>
                  Then <b>Ask About</b> any claim, or have it <b>Explain Simply</b>.
                </p>
              </div>

              {/* L2.5 + L3 — the layered scene. The photograph is the room the
                  interface is standing in; the panel is the object in front of
                  it. Both are ordinary `.lp-l` depth layers, so the parallax
                  engine drives them with no new code — the whole effect is the
                  gap between their two `--d` values.

                  Two elements per layer, deliberately: `.lp-l` owns the
                  translate the engine writes every frame, the child owns the
                  static perspective tilt. One element cannot own `transform`
                  twice, which is the same reason .lp-plate moves on
                  `translate`. */}
              <div className="lp-visual">
                <div className="lp-l lp-photo-layer" aria-hidden="true">
                  {/* the frame is a fixed viewport onto the photograph; the
                      image inside it is what scrolling moves, so the scene is
                      re-cropped rather than slid around as a whole */}
                  <div className="lp-photo-frame">
                    <img className="lp-photo" src="/hero-study.webp" alt=""
                         width="1872" height="1248" decoding="async"
                         fetchpriority="high" draggable="false" />
                    {/* the daylight falling across the desk, as its own plane —
                        it drifts against the photograph on scroll, which is
                        what stops the push-in reading as a flat zoom */}
                    <span className="lp-photo-light" />
                  </div>
                </div>
                <div className="lp-l lp-ui-layer" style={{ "--d": .95 }}>
                  <div className="lp-ui-tilt">
                    <HeroPanel step={step} tp={topic} />
                  </div>
                </div>
              </div>

            </div>
          </div>

          {/* pinned to the stage floor, so the hero's bottom edge is a
              deliberate cue rather than leftover centring slack */}
          <div className="lp-hint">
            {/* two nested opacities: the inner one is the entrance, the outer
                one is the scroll fade. One element cannot carry both — the
                entrance animation's fill would win over the scroll value. */}
            <span className="lp-hint-in lp-fade-up" style={{ "--i": 5 }}>
              <svg className="lp-hint-line w-3.5 h-3.5" viewBox="0 0 14 14" fill="none" stroke="currentColor"
                   strokeWidth="1.4" strokeLinecap="round" style={{ color: "var(--ink-soft)" }} aria-hidden>
                <path d="M7 2v9M3.4 7.6 7 11.2l3.6-3.6" />
              </svg>
              <span className="lp-fine">Scroll</span>
            </span>
          </div>
        </div>
      </section>

      {/* ══ § 2 WEDGE — full-bleed, scroll-linked ══ */}
      <div ref={band} className="lp-band lp-above">
        <div ref={marquee} className="lp-marquee">
          {[0, 1].map(dup => (
            <div className="lp-marquee-row" key={dup} aria-hidden={dup === 1}>
              {MARQUEE.map(s => (
                <span className="lp-marquee-item" key={s + dup}>
                  <span className="lp-marquee-dot" /><s>{s}</s>
                </span>
              ))}
              <span className="lp-marquee-item" style={{ color: "var(--ink)" }}>
                <span className="lp-marquee-dot" />A plan, a memory, and a source for every claim
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* ══ § 3 THE ARC — one list, not two.
         Was two sections (a 01-04 mechanism list, then a Day 1/7/21 example
         list) with matching heading size and matching rhythm, so the page
         said one thing twice. Now a single list of three rows: the day is
         the numeral, the loop step is the line under it, the lesson is the
         payoff. Runs the depth-of-field staging throughout.
         Carries id="how" because it now leads: the nav's "How it works"
         should land on the loop, which is the thing that answers it. ══ */}
      <section id="how" data-sec data-prog data-tilt="900" className="lp-above lp-sec py-24 md:py-32">
        <DayCorridor />
        {/* the left gutter runs the whole height of this section empty — the
            corridor and the armillary both live on the right */}
        <Plate seed={11} count={17} className="lp-plate-arc-a" />
        <Plate seed={37} count={15} className="lp-plate-arc-b" />
        <Plate seed={64} count={15} className="lp-plate-arc-c" />
        {/* the armillary fills the measured 240px ARC→ANATOMY void, and is the
            one asset here that is literally about this section: three rings
            for three weeks, turning as you scroll past them */}
        <Armillary />
        <div className="max-w-5xl mx-auto px-5 sm:px-6">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-2 mb-3" data-stage>
            <p className="lp-eyebrow">One topic, no last day</p>
            <span className="lp-tag lp-i-blue">Quantum computing</span>
          </div>
          <h2 className="lp-h2 mb-6 max-w-lg" data-stage style={{ "--i": 1 }}>
            The same loop.<br />Deeper every time.
          </h2>
          <p className="lp-lead mb-20 md:mb-28 max-w-xl" data-stage style={{ "--i": 2, fontSize: "1.0625rem" }}>
            Every day runs the same four steps, and every day starts where
            yesterday finished. Three weeks on one topic — then as long as you like:
          </p>

          {ARC.map((a, i) => (
            <article key={a.n} className={`lp-day lp-st-dof ${a.ink} grid md:grid-cols-[auto_minmax(0,1fr)] gap-x-10 gap-y-2`}
                     data-stage style={{ "--i": i * 0.5 }}>
              <span className="lp-bignum lp-loop-num">{a.n}</span>
              <div className="lp-loop-body">
                <div className="lp-day-rule mb-4" />
                <div className="flex items-center gap-3 mb-2.5">
                  <span className="lp-day-n">{a.day}</span>
                  <span className="lp-chip" style={{ color: "var(--ink-soft)" }}>{a.badge}</span>
                </div>
                {/* what the loop did on this day — the mechanism, said inline
                    instead of as its own parallel list */}
                <p className="lp-sub mb-3.5">
                  {a.step.map((s, si) => si % 2 ? <b key={si}>{s}</b> : s)}
                </p>
                <h3 className="lp-h3 mb-2.5">{a.title}</h3>
                <p className="lp-body" style={{ fontSize: "1.0625rem" }}>
                  <span className={`lp-mark lp-mark-on ${a.mk}`}>{a.mark}</span>{a.rest}
                </p>
              </div>
            </article>
          ))}
        </div>
        <ArcHandoff />
      </section>

      {/* ══ § 4 ANATOMY — sticky rail, runway derived from content.
         Second now: the arc shows the loop across three weeks, then this
         zooms into what a single lesson in that arc is made of. ══ */}
      <section id="anatomy" data-sec data-tilt="820" className="lp-anatomy lp-above lp-sec lp-rule-t">
        <Plate seed={19} count={16} className="lp-plate-an-l" />
        <Plate seed={73} count={15} className="lp-plate-an-r" />
        <div className="max-w-6xl mx-auto px-5 sm:px-6 pt-20 md:pt-28 pb-20">
          <div className="grid lg:grid-cols-[minmax(0,.62fr)_minmax(0,1fr)] gap-10 lg:gap-16">

            <div>
              <div className="lp-anatomy-rail">
                <p className="lp-eyebrow mb-3" data-stage>Not just a summary</p>
                <h2 className="lp-h2 mb-5" data-stage style={{ "--i": 1 }}>Five moves,<br />every lesson</h2>
                {/* the "why" — pinned alongside the blocks it explains, so it
                    stays in view for the whole section rather than scrolling
                    off after one glance */}
                <p className="lp-lead mb-8" data-stage style={{ "--i": 2, fontSize: "1rem" }}>
                  A one-paragraph AI answer is easy to skim and easier to forget.
                  Every lesson works through the same five moves below, so it
                  sticks instead of sliding past.
                </p>
                <ol className="space-y-2.5">
                  {ANATOMY.map((a, i) => (
                    <li key={a.key} className={`lp-step ${a.ink}`} data-active={i === anatomyIdx}>
                      <span className="lp-step-dot" aria-hidden />
                      <span className="lp-ui" style={{ fontWeight: 700, color: "var(--ink)" }}>{a.label}</span>
                    </li>
                  ))}
                </ol>
                {/* 345px of measured empty column under the list, and it is
                    pinned with the rail, so the exploded view stays beside
                    the blocks it explains for the whole section */}
                <LessonStack active={anatomyIdx} />
              </div>
            </div>

            <div className="space-y-8 md:space-y-10">
              {ANATOMY.map((a, i) => {
                const Icon = a.icon
                /* only Comparison carries `mark` today, but any item can —
                   the wipe is driven by the block's own data-active, so it
                   replays with the icon every time you scroll back to it */
                const body = a.mark
                  ? a.body.split(a.mark).flatMap((chunk, ci, arr) => ci === arr.length - 1
                      ? [chunk]
                      : [chunk, <span key={ci} className="lp-mark lp-mark-yellow lp-an-mark">{a.mark}</span>])
                  : a.body
                return (
                  <div key={a.key} className={`lp-blockrow ${a.ink}`} data-active={i === anatomyIdx} data-block>
                    <span className="lp-an-icon-wrap mb-2.5 inline-flex">
                      <Icon className="lp-an-icon" />
                    </span>
                    <span className="lp-tag mb-3 inline-block">{a.label}</span>
                    <p className="lp-body" style={{ color: "var(--ink)", whiteSpace: "pre-line", fontSize: "1.0625rem" }}>{body}</p>
                  </div>
                )
              })}
            </div>

          </div>
        </div>
      </section>

      {/* ══ § 5 BEYOND THE LESSON — four features, four live demos.
         Deliberately the longest block on the page: it is where the product
         stops being "a daily lesson" and becomes something you live in. Each
         row alternates side so the eye crosses the page rather than running
         down one gutter, and each panel demonstrates its own feature. ══ */}
      <section id="features" data-sec data-tilt="900" className="lp-above lp-sec lp-rule-t py-24 md:py-32">
        {/* the wires take the left flank and the bottom right, which the
            alternating feature rows leave open */}
        <Plate seed={43} count={16} className="lp-plate-feat-l" />
        <Plate seed={88} count={15} className="lp-plate-feat-b" />
        <div className="max-w-6xl mx-auto px-5 sm:px-6">
          {/* Asymmetric by construction: the copy holds a full column, the
              object a slightly narrower one, and they are centred against each
              other rather than top-aligned — so the object reads as the
              counterweight to the headline instead of decoration parked in
              the margin, which is what it was when it floated absolutely at
              `right: -30px` behind the text. */}
          <div className="lp-feat-head grid lg:grid-cols-[minmax(0,1fr)_minmax(0,.88fr)] gap-12 lg:gap-16 items-center mb-20 md:mb-28">
            <div>
              <p className="lp-eyebrow mb-3" data-stage>The complete package</p>
              <h2 className="lp-h2 mb-6 max-w-xl" data-stage style={{ "--i": 1 }}>
                A lesson is where<br />it starts, not ends.
              </h2>
              <p className="lp-lead max-w-2xl" data-stage style={{ "--i": 2, fontSize: "1.0625rem" }}>
                Reading it is one step. Understanding every line of it, asking past
                it, keeping what mattered, and having all of it on a train with no
                signal — that is the rest of the way.
              </p>
              <p className="lp-featindex mt-5" data-stage style={{ "--i": 3 }}>
                {FEATURES.map((f, i) => (
                  <span key={f.n}>
                    {i > 0 && <i aria-hidden>·</i>}
                    <b>{f.n}</b> {f.tag}
                  </span>
                ))}
              </p>
            </div>

            <PackageObject selected={pkgSel} onSelect={setPkgSel} />
          </div>

          {FEATURES.map((f, i) => {
            const Demo = f.Demo
            return (
              <article key={f.n} className={`lp-feat lp-st-dof ${f.ink} ${i % 2 ? "lp-feat-flip" : ""}`}
                       data-stage style={{ "--i": i * 0.35 }}>
                <div className="lp-feat-copy">
                  <div className="lp-day-rule mb-5" />
                  <div className="flex items-center gap-3 mb-3">
                    <span className="lp-feat-n">{f.n}</span>
                    <span className="lp-tag">{f.tag}</span>
                  </div>
                  <h3 className="lp-h3 mb-3">{f.title}</h3>
                  <p className="lp-body mb-5" style={{ fontSize: "1.0625rem" }}>{f.body}</p>
                  <ul className="lp-feat-list">
                    {f.list.map((row, li) => (
                      <li key={li} className="lp-sub">
                        <span className="lp-feat-bullet" aria-hidden />
                        <span>{row.map((s, si) => si % 2 === 0 ? <b key={si}>{s}</b> : s)}</span>
                      </li>
                    ))}
                  </ul>
                </div>

                <div className="lp-feat-demo">
                  <div className="lp-fpanel">
                    <div className="lp-fbar">
                      <span className="lp-live" aria-hidden />
                      <span>{f.tag}</span>
                    </div>
                    <Demo p={motionOn ? tick % f.period : f.still} />
                  </div>
                </div>
              </article>
            )
          })}
        </div>
      </section>

      {/* ══ § 6 CTA ══ */}
      <section id="start" data-sec data-tilt="760" className="lp-above lp-sec lp-rule-t py-24 md:py-32">
        {/* thinnest section on the page at 0.13 coverage — the CTA is a single
            centred button by design, so the plates go either side of it rather
            than behind, and the button keeps its clear field. */}
        <Plate seed={23} count={18} className="lp-plate-cta lp-plate-cta-l" />
        <Plate seed={57} count={18} className="lp-plate-cta lp-plate-cta-r" />
        <div className="max-w-2xl mx-auto px-5 sm:px-6 text-center relative">
          <h2 className="lp-h2 mb-8" data-stage>
            Small consistent curiosity{" "}
            <span className="lp-mark lp-mark-on">becomes real expertise.</span>
          </h2>
          <button onClick={ctaAction} className="lp-btn inline-flex items-center gap-2.5 px-8 py-4 rounded-md"
                  data-stage style={{ "--i": 1, fontSize: "16px" }}>
            <span className="lp-live lp-cta-dot" aria-hidden />
            {ctaLabel}
            <Arrow className="w-4 h-4" />
          </button>
          {!isAuthenticated && <p className="lp-fine mt-5" data-stage style={{ "--i": 2 }}>Free. No credit card.</p>}
        </div>
      </section>

      {/* ══ FOOTER ══ */}
      <footer className="lp-above lp-sec lp-rule-t py-12" data-tilt="620">
        <Plate seed={91} count={16} className="lp-plate-foot" />
        <div className="max-w-6xl mx-auto px-5 sm:px-6">
          <div className="flex flex-col sm:flex-row items-center sm:items-start justify-between gap-7">
            <div className="flex items-center gap-2">
              <LogoSlot size={24} />
              <span className="lp-ui" style={{ fontWeight: 700 }}>Curivio</span>
            </div>
            <div className="flex items-center gap-6">
              <button
                type="button"
                onClick={toggleMotion}
                className="lp-motion-toggle"
                aria-pressed={motionOn}
                title={motionOn
                  ? "Turn off animation on this page"
                  : "Your system has animations turned off. Turn them on for this page."}
              >
                <span className="lp-motion-track" aria-hidden />
                Motion {motionOn ? "on" : "off"}
              </button>
              <a href="#how" className="lp-link" style={{ fontSize: "13px" }}>How it works</a>
              <button onClick={ctaAction} className="lp-link" style={{ fontSize: "13px" }}>
                {isAuthenticated ? "Open app" : "Get started"}
              </button>
            </div>
          </div>
          <div className="mt-9 pt-6 lp-rule-t text-center">
            <p className="lp-fine" style={{ fontSize: "11px" }}>
              © {new Date().getFullYear()} Curivio. AI-curated learning for the curious mind.
            </p>
          </div>
        </div>
      </footer>
    </div>
  )
}
