/**
 * App colour mode — light / dark / legacy.
 *
 * The mode is a `data-ui` attribute on <html> (not on a React root) for two
 * reasons: every portal, modal and dropdown in the app is a child of <body>
 * rather than of the layout tree, and index.html can set it before first paint
 * so a reload never flashes the wrong palette. The palettes themselves live in
 * src/theme.css.
 *
 * Deliberately not tied to `prefers-color-scheme`. The landing page made the
 * same call: the mode is a choice the user made, and a laptop that flips to
 * dark at sunset should not silently repaint an app they set to light.
 */

export const UI_MODES = ['light', 'dark', 'legacy']

export const UI_MODE_LABELS = {
  light:  'Light',
  dark:   'Dark',
  legacy: 'Legacy',
}

const KEY = 'curivio.ui'
const DEFAULT = 'light'

const THEME_COLOR = {
  light:  '#EFEDDC',
  dark:   '#211D17',
  legacy: '#0f1117',
}

const listeners = new Set()

export function getUiTheme() {
  const attr = document.documentElement.dataset.ui
  if (UI_MODES.includes(attr)) return attr
  try {
    const stored = localStorage.getItem(KEY)
    if (UI_MODES.includes(stored)) return stored
  } catch { /* storage unavailable — fall through to the default */ }
  return DEFAULT
}

function paint(mode) {
  document.documentElement.dataset.ui = mode
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', THEME_COLOR[mode])
  try { localStorage.setItem(KEY, mode) } catch { /* storage unavailable */ }
  listeners.forEach(fn => fn())
}

/**
 * @param {string} mode   one of UI_MODES
 * @param {{x:number,y:number}} [origin]  viewport point the change radiates
 *   from — normally the centre of the control that was clicked.
 */
export function setUiTheme(mode, origin) {
  if (!UI_MODES.includes(mode) || mode === getUiTheme()) return

  const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  if (reduced) { paint(mode); return }

  const root = document.documentElement
  if (origin) {
    root.style.setProperty('--u-swap-x', `${origin.x}px`)
    root.style.setProperty('--u-swap-y', `${origin.y}px`)
  } else {
    root.style.setProperty('--u-swap-x', '50%')
    root.style.setProperty('--u-swap-y', '50%')
  }

  // Where the browser can hold the old frame for us, the new palette wipes in
  // over it from the control that was clicked — one surface replacing another,
  // rather than every colour in the app changing its mind at once.
  if (typeof document.startViewTransition === 'function') {
    document.startViewTransition(() => paint(mode))
    return
  }

  // Otherwise crossfade every colour property at once. The class is temporary:
  // a standing `transition` on `*` would tax every hover in the app for the
  // sake of an interaction that happens a handful of times.
  root.classList.add('u-swapping')
  paint(mode)
  window.setTimeout(() => root.classList.remove('u-swapping'), 480)
}

export function subscribeUiTheme(fn) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}
