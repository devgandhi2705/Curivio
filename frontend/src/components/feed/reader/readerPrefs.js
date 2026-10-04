/**
 * Reading-mode preferences: fonts, themes, presets, and the CSS variables
 * they turn into. Saved per browser in localStorage.
 *
 * Themes repaint by redefining the app's own colour variables (--u-slate-*,
 * --u-blue-*, …) on the reader root, so every Tailwind slate/blue utility
 * inside the reader — InsightCard included — follows without new markup.
 * A theme is just { bg, text, accent, dark }; the 11-step ramps are mixed
 * from those three colours.
 */

const KEY = "curivio.reader.v1"

// One family for headings and text. Any Google Fonts family works (the full
// list ships in googleFonts.json, loaded with the settings panel); two system
// faces need no download. `fontCat` is the family's Google category — it
// picks the fallback while the face downloads.
export const SYSTEM_FONTS = {
  "System": "system-ui, -apple-system, 'Segoe UI', sans-serif",
  "Georgia": "Georgia, 'Times New Roman', serif",
}
const FALLBACK = {
  s: "system-ui, sans-serif",           // Sans Serif
  r: "Georgia, serif",                  // Serif
  d: "system-ui, sans-serif",           // Display
  h: "cursive",                         // Handwriting
  m: "ui-monospace, monospace",         // Monospace
}
export const CATEGORY_LABEL = { s: "Sans serif", r: "Serif", d: "Display", h: "Handwriting", m: "Monospace" }

export function fontStack(family, cat = "s") {
  return SYSTEM_FONTS[family] ?? `'${family}', ${FALLBACK[cat] ?? FALLBACK.s}`
}

/** Loads a Google family once. css2 serves whichever of 400/700/italic exist. */
export function ensureFont(family) {
  if (!family || SYSTEM_FONTS[family] || typeof document === "undefined") return
  const linkId = `reader-font-${family.replace(/\W+/g, "-")}`
  if (document.getElementById(linkId)) return
  const link = document.createElement("link")
  link.id = linkId
  link.rel = "stylesheet"
  link.href = `https://fonts.googleapis.com/css2?family=${encodeURIComponent(family).replace(/%20/g, "+")}:ital,wght@0,400;0,700;1,400&display=swap`
  document.head.appendChild(link)
}

// Saved before fonts were Google family names.
const LEGACY_FONT_IDS = {
  inter: ["Inter", "s"], system: ["System", "s"], figtree: ["Figtree", "s"], plex: ["IBM Plex Sans", "s"],
  sourcesans: ["Source Sans 3", "s"], nunito: ["Nunito", "s"], atkinson: ["Atkinson Hyperlegible", "s"],
  atkinsonnext: ["Atkinson Hyperlegible Next", "s"], lexend: ["Lexend", "s"], newsreader: ["Newsreader", "r"],
  literata: ["Literata", "r"], sourceserif: ["Source Serif 4", "r"], merriweather: ["Merriweather", "r"],
  lora: ["Lora", "r"], garamond: ["EB Garamond", "r"], crimson: ["Crimson Pro", "r"],
  baskerville: ["Libre Baskerville", "r"], fraunces: ["Fraunces", "r"], georgia: ["Georgia", "r"],
  mono: ["JetBrains Mono", "m"],
}

// "app" follows the app's own theme. Everything else is bg/text/accent.
export const THEMES = [
  { id: "app",        label: "App theme" },
  { id: "paper",      label: "Paper",          bg: "#F6F4EB", text: "#1D1810", accent: "#3C5A32", dark: false },
  { id: "white",      label: "White",          bg: "#FFFFFF", text: "#1A1A1A", accent: "#2457C5", dark: false },
  { id: "sepia",      label: "Sepia",          bg: "#F4ECD8", text: "#4A3A2A", accent: "#9A5B2E", dark: false },
  { id: "solarlight", label: "Solarized",      bg: "#FDF6E3", text: "#3B4D53", accent: "#1F6FAF", dark: false },
  { id: "mist",       label: "Mist",           bg: "#E8ECEF", text: "#1E262C", accent: "#3D5A80", dark: false },
  { id: "mint",       label: "Mint",           bg: "#E7F1EA", text: "#1D2C23", accent: "#2E7D4F", dark: false },
  { id: "rose",       label: "Rose",           bg: "#F7ECEC", text: "#3A2328", accent: "#A2445A", dark: false },
  { id: "hclight",    label: "High contrast",  bg: "#FFFFFF", text: "#000000", accent: "#0033CC", dark: false },
  { id: "dusk",       label: "Dusk",           bg: "#141210", text: "#E9E0D7", accent: "#A3C68C", dark: true },
  { id: "classic",    label: "Classic",        bg: "#0F1117", text: "#D8E2F0", accent: "#60A5FA", dark: true },
  { id: "night",      label: "Night",          bg: "#000000", text: "#CFCFCF", accent: "#7DB4F7", dark: true },
  { id: "nord",       label: "Nord",           bg: "#2E3440", text: "#E5E9F0", accent: "#88C0D0", dark: true },
  { id: "solardark",  label: "Solarized dark", bg: "#002B36", text: "#C9D3D3", accent: "#2AA198", dark: true },
  { id: "forest",     label: "Forest",         bg: "#0F1A14", text: "#D5E6D9", accent: "#7BC48E", dark: true },
  { id: "plum",       label: "Plum",           bg: "#1C1520", text: "#EADDF0", accent: "#C79BE0", dark: true },
  { id: "hcdark",     label: "High contrast dark", bg: "#000000", text: "#FFFFFF", accent: "#FFD400", dark: true },
  { id: "custom",     label: "Custom" },
]

// Headings keep this ratio to the text size, so one size control moves both.
export const HEADING_RATIO = 1.25

export const DEFAULTS = {
  font: "Inter",
  fontCat: "s",
  size: 18,          // px, body
  lineHeight: 1.7,
  tracking: 0,       // em
  wordSpacing: 0,    // em
  paraSpacing: 0.5,  // em between blocks
  width: 760,        // px, reading column
  align: "left",     // left | justify
  hyphens: false,
  theme: "app",
  custom: { bg: "#F6F4EB", text: "#1D1810", accent: "#3C5A32", dark: false },
  dim: 100,          // % brightness
  transition: "slide", // slide | fade | lift | none
  speed: 1,          // × duration
  autoHide: true,    // tuck the toolbar away while reading
  arrows: true,      // side arrows on wide screens
}

export const PRESETS = [
  { id: "default", label: "Default",     prefs: {} },
  { id: "book",    label: "Book",        prefs: { font: "Literata", fontCat: "r", size: 19, lineHeight: 1.75, width: 680, theme: "paper", align: "justify", hyphens: true, paraSpacing: 0.7 } },
  { id: "large",   label: "Large print", prefs: { font: "Atkinson Hyperlegible", fontCat: "s", size: 24, lineHeight: 1.8, width: 820, paraSpacing: 0.8 } },
  { id: "easy",    label: "Easy reading",prefs: { font: "Lexend", fontCat: "s", size: 19, lineHeight: 2, tracking: 0.03, wordSpacing: 0.12, paraSpacing: 1, width: 700 } },
  { id: "night",   label: "Night",       prefs: { theme: "night", dim: 85, font: "Source Sans 3", fontCat: "s", size: 19 } },
  { id: "compact", label: "Compact",     prefs: { size: 16, lineHeight: 1.55, width: 900, paraSpacing: 0.3 } },
]

const LIMITS = {
  size: [10, 48], lineHeight: [1, 3],
  tracking: [-0.05, 0.2], wordSpacing: [0, 0.6], paraSpacing: [0, 2], width: [480, 1200],
  dim: [40, 100], speed: [0.5, 2],
}
export const RANGE = LIMITS

const HEX = /^#[0-9a-f]{6}$/i

/** Merge stored prefs over defaults, dropping anything malformed. */
export function sanitize(raw) {
  const p = { ...DEFAULTS, custom: { ...DEFAULTS.custom } }
  if (!raw || typeof raw !== "object") return p
  for (const [k, [lo, hi]] of Object.entries(LIMITS)) {
    const v = Number(raw[k])
    if (Number.isFinite(v)) p[k] = Math.min(hi, Math.max(lo, v))
  }
  if (LEGACY_FONT_IDS[raw.font]) [p.font, p.fontCat] = LEGACY_FONT_IDS[raw.font]
  else if (typeof raw.font === "string" && /^[\w ]{1,60}$/.test(raw.font)) {
    p.font = raw.font
    if (FALLBACK[raw.fontCat]) p.fontCat = raw.fontCat
  }
  if (THEMES.some(t => t.id === raw.theme)) p.theme = raw.theme
  if (["left", "justify"].includes(raw.align)) p.align = raw.align
  if (["slide", "fade", "lift", "none"].includes(raw.transition)) p.transition = raw.transition
  for (const k of ["hyphens", "arrows"]) if (typeof raw[k] === "boolean") p[k] = raw[k]
  // Saves before v2 stored autoHide: false as the old default; they get the new default.
  if (raw.v >= 2 && typeof raw.autoHide === "boolean") p.autoHide = raw.autoHide
  const c = raw.custom
  if (c && typeof c === "object") {
    for (const k of ["bg", "text", "accent"]) if (HEX.test(c[k] ?? "")) p.custom[k] = c[k]
    if (typeof c.dark === "boolean") p.custom.dark = c.dark
  }
  return p
}

export function loadPrefs() {
  try { return sanitize(JSON.parse(localStorage.getItem(KEY))) } catch { return sanitize(null) }
}
export function savePrefs(p) {
  try { localStorage.setItem(KEY, JSON.stringify({ ...p, v: 2 })) } catch { /* private mode: prefs last this session */ }
}

// ── colour ramps ──────────────────────────────────────────────────────────────

const rgb = hex => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16))
const mix = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t))
const str = c => c.join(" ")

// How far each slate step sits from the ground (0) toward the ink (1).
// 950–700 are surfaces and rules, 600–50 are text — the app's own convention.
const SLATE_STEPS = { 950: 0, 900: 0.035, 800: 0.08, 700: 0.15, 600: 0.5, 500: 0.58, 400: 0.72, 300: 0.84, 200: 0.93, 100: 1, 50: 1 }

/** CSS variables for a theme, or null to follow the app's theme. */
export function themeVars(prefs) {
  const t = prefs.theme === "custom" ? prefs.custom : THEMES.find(x => x.id === prefs.theme)
  if (!t?.bg) return null
  const bg = rgb(t.bg), ink = rgb(t.text), acc = rgb(t.accent)
  const vars = {}
  for (const [step, k] of Object.entries(SLATE_STEPS)) vars[`--u-slate-${step}`] = str(mix(bg, ink, k))
  // Accent: 100–400 read as text, 500–600 are fills, 700–950 are washes.
  const accent = {
    100: mix(acc, ink, 0.45), 200: mix(acc, ink, 0.3), 300: mix(acc, ink, 0.15), 400: acc,
    500: mix(acc, ink, 0.12), 600: acc, 700: mix(acc, bg, 0.3),
    800: mix(acc, bg, 0.72), 900: mix(acc, bg, 0.84), 950: mix(acc, bg, 0.92),
  }
  for (const [step, c] of Object.entries(accent)) vars[`--u-blue-${step}`] = str(c)
  vars["--u-white"]     = str(ink)          // white films lift toward the ink
  vars["--u-on-accent"] = str(bg)
  vars["--u-accent"]    = t.accent
  vars["--u-track"]     = `rgb(${str(mix(bg, ink, 0.15))})`
  vars["--u-axis"]      = `rgb(${str(mix(bg, ink, 0.55))})`
  vars["--u-surface"]   = t.bg
  return { vars, dark: !!t.dark }
}

/** Typography variables read by the .u-reader rules in index.css. */
export function typeVars(p) {
  return {
    "--r-font": fontStack(p.font, p.fontCat),
    "--r-size": `${p.size}px`,
    "--r-head-scale": HEADING_RATIO,
    "--r-lh": p.lineHeight,
    "--r-tracking": `${p.tracking}em`,
    "--r-words": `${p.wordSpacing}em`,
    "--r-para": `${p.paraSpacing}em`,
    "--r-width": `${p.width}px`,
    "--r-align": p.align,
    "--r-hyphens": p.hyphens ? "auto" : "manual",
  }
}
