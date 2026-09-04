import colors from 'tailwindcss/colors'

/* ────────────────────────────────────────────────────────────────────────────
   VARIABLE-BACKED PALETTE

   Every colour utility the app uses resolves through a CSS custom property
   instead of a literal hex, so a theme can repaint the entire product by
   redefining ~110 variables (see src/theme.css) without a single JSX edit.

   Two properties make this safe:

   1. `<alpha-value>` is preserved, so `bg-slate-900/60`, `border-white/[0.08]`
      and every other alpha modifier keep working exactly as before.

   2. Each var carries Tailwind's own colour as its fallback. A theme that
      defines nothing renders as stock Tailwind, and any shade a theme forgets
      degrades to the stock value rather than to `transparent`. That is what
      lets the Legacy theme be tiny: it only overrides the slate spine, and
      inherits today's accent colours for free.
   ──────────────────────────────────────────────────────────────────────────── */

const FAMILIES = [
  'slate', 'gray', 'zinc', 'neutral', 'stone',
  'red', 'orange', 'amber', 'yellow', 'lime', 'green', 'emerald', 'teal',
  'cyan', 'sky', 'blue', 'indigo', 'violet', 'purple', 'fuchsia', 'pink', 'rose',
]

const channels = hex => {
  const h = hex.replace('#', '')
  return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16)).join(' ')
}

const themedFamilies = Object.fromEntries(
  FAMILIES.map(family => [
    family,
    Object.fromEntries(
      Object.entries(colors[family])
        .filter(([shade]) => /^\d+$/.test(shade))
        .map(([shade, hex]) => [
          shade,
          `rgb(var(--u-${family}-${shade}, ${channels(hex)}) / <alpha-value>)`,
        ]),
    ),
  ]),
)

export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        ...themedFamilies,
        /* `white` is used almost exclusively as a low-alpha overlay
           (bg-white/[0.04], border-white/[0.08]) — a dark-UI idiom that has to
           become an INK overlay on a light ground or it disappears. Solid
           `text-white` is handled separately in theme.css, because there it
           means "text on an accent fill", not "the colour white". */
        white: 'rgb(var(--u-white, 255 255 255) / <alpha-value>)',
      },
    },
  },
  plugins: [],
}
