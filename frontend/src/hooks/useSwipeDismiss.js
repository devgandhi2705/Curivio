import { useEffect, useRef, useState } from 'react'
import { classifyGesture, shouldDismiss } from '../lib/motionMath.js'

/**
 * Touch swipe-to-close for the phone drawer (direction 'left') and bottom
 * sheets ('down'). Follows the finger with the CSS `translate` property —
 * separate from `transform`, so it composes with the drawer's Tailwind
 * translate classes and with Motion's inline transform on sheets.
 *
 * The direction is decided after 8px; a vertical move in the drawer, or a
 * move that starts outside a sheet's handle (`handleOnly`), is left to the
 * page so scrolling is never taken over.
 */
export function useSwipeDismiss({ direction, onDismiss, enabled = true, handleOnly = false }) {
  // A callback ref, not useRef: the hook may live in a parent that mounts long
  // before the sheet does (ProjectsPage's delete dialog), so the listeners are
  // attached whenever the node itself arrives.
  const [el, ref] = useState(null)
  const dismissRef = useRef(onDismiss)
  dismissRef.current = onDismiss

  useEffect(() => {
    if (!el || !enabled) return
    const axis = direction === 'left' ? 'x' : 'y'
    const sign = direction === 'left' ? -1 : 1
    let g = null

    function down(e) {
      if (e.pointerType !== 'touch') return
      if (handleOnly && !e.target.closest('.u-sheet-handle')) return
      g = { x: e.clientX, y: e.clientY, t: e.timeStamp, mode: 'undecided', offset: 0 }
    }
    function move(e) {
      if (!g || g.mode === 'scroll') return
      const dx = e.clientX - g.x
      const dy = e.clientY - g.y
      if (g.mode === 'undecided') g.mode = classifyGesture(dx, dy, axis)
      if (g.mode !== 'swipe') return
      g.offset = Math.max(0, (axis === 'x' ? dx : dy) * sign)
      el.style.transition = 'none'
      el.style.translate = axis === 'x' ? `${-g.offset}px 0` : `0 ${g.offset}px`
    }
    function up(e) {
      if (!g) return
      const { offset, t, mode } = g
      g = null
      el.style.transition = ''
      el.style.translate = ''
      if (mode !== 'swipe') return
      const size = axis === 'x' ? el.offsetWidth : el.offsetHeight
      if (shouldDismiss(offset, offset / Math.max(e.timeStamp - t, 1), size)) dismissRef.current()
    }

    el.addEventListener('pointerdown', down)
    el.addEventListener('pointermove', move, { passive: true })
    el.addEventListener('pointerup', up)
    el.addEventListener('pointercancel', up)
    return () => {
      el.removeEventListener('pointerdown', down)
      el.removeEventListener('pointermove', move)
      el.removeEventListener('pointerup', up)
      el.removeEventListener('pointercancel', up)
    }
  }, [el, direction, enabled, handleOnly])

  return ref
}
