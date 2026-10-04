/**
 * The Motion library, loaded the cheap way.
 *
 * `LazyMotion` + `m` costs ~4.6 KB up front; the features chunk
 * (motionFeatures.js) arrives after first paint. `strict` makes any stray
 * `motion.div` throw, so nobody pulls the full bundle back in by accident.
 *
 * Motion does four jobs in this app — exit animations, list reflow (layout),
 * the shared nav pill (layoutId), and collapsibles (height). Everything else
 * is CSS (motion.css). Presets below are the only animation values
 * components use; the numbers mirror the CSS tokens.
 */
import { useSyncExternalStore } from 'react'
import { LazyMotion } from 'motion/react'
import { useSwipeDismiss } from '../hooks/useSwipeDismiss.js'

export { m, AnimatePresence } from 'motion/react'

const loadFeatures = () => import('./motionFeatures.js').then(mod => mod.default)

export const SPRING      = { type: 'spring', stiffness: 400, damping: 20 }
export const SPRING_SOFT = { type: 'spring', stiffness: 300, damping: 26 }
export const EXIT        = { duration: 0.2, ease: [0.7, 0, 0.84, 0] }

export const presets = {
  scrim:    { initial: { opacity: 0 }, animate: { opacity: 1, transition: { duration: 0.18 } }, exit: { opacity: 0, pointerEvents: 'none', transition: { duration: 0.16 } } },
  dialog:   { initial: { opacity: 0, y: 18, scale: 0.96 }, animate: { opacity: 1, y: 0, scale: 1, transition: SPRING_SOFT }, exit: { opacity: 0, y: 8, scale: 0.98, pointerEvents: 'none', transition: EXIT } },
  sheet:    { initial: { y: '100%' }, animate: { y: 0, transition: SPRING_SOFT }, exit: { y: '100%', pointerEvents: 'none', transition: EXIT } },
  panel:    { initial: { x: 28, opacity: 0 }, animate: { x: 0, opacity: 1, transition: SPRING_SOFT }, exit: { x: 28, opacity: 0, pointerEvents: 'none', transition: EXIT } },
  palette:  { initial: { opacity: 0, y: -14, scale: 0.98 }, animate: { opacity: 1, y: 0, scale: 1, transition: SPRING_SOFT }, exit: { opacity: 0, y: -8, scale: 0.98, pointerEvents: 'none', transition: EXIT } },
  menu:     { initial: { opacity: 0, scale: 0.92, y: -6 }, animate: { opacity: 1, scale: 1, y: 0, transition: { type: 'spring', stiffness: 520, damping: 26 } }, exit: { opacity: 0, scale: 0.96, y: -4, pointerEvents: 'none', transition: { duration: 0.14, ease: [0.7, 0, 0.84, 0] } } },
  listItem: { layout: true, initial: { opacity: 0, scale: 0.96 }, animate: { opacity: 1, scale: 1 }, exit: { opacity: 0, scale: 0.92, pointerEvents: 'none', transition: EXIT }, transition: SPRING },
  collapse: { initial: { height: 0, opacity: 0 }, animate: { height: 'auto', opacity: 1, transition: SPRING_SOFT }, exit: { height: 0, opacity: 0, transition: EXIT }, style: { overflow: 'hidden' } },
}

const phoneQuery = typeof window !== 'undefined' ? window.matchMedia('(max-width: 767px)') : null
function subscribePhone(fn) {
  phoneQuery?.addEventListener('change', fn)
  return () => phoneQuery?.removeEventListener('change', fn)
}

/** Dialogs pick `presets.sheet` on phones and `presets.dialog` elsewhere. */
export function useIsPhone() {
  return useSyncExternalStore(subscribePhone, () => phoneQuery?.matches ?? false, () => false)
}

// No MotionConfig: its reducedMotion default is 'never', and the app always animates.
export function MotionProvider({ children }) {
  return (
    <LazyMotion features={loadFeatures} strict>
      {children}
    </LazyMotion>
  )
}

/**
 * Motion props for a dialog's backdrop root and its card. On phones a
 * `sheet` dialog rises from the bottom (its markup carries u-sheet-root /
 * u-sheet and renders the handle when `phone` is true) and dragging the
 * handle down calls onDismiss. Long forms pass { sheet: false }: centred
 * everywhere, nothing to swipe away.
 */
export function useDialogMotion(onDismiss, { sheet = true, swipe = true } = {}) {
  const phone = useIsPhone() && sheet
  const ref = useSwipeDismiss({ direction: 'down', onDismiss, enabled: phone && swipe, handleOnly: true })
  return {
    root: presets.scrim,
    card: { ...(phone ? presets.sheet : presets.dialog), ref },
    phone,
  }
}
