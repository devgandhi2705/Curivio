import { useEffect, useRef } from 'react'

/**
 * One highlight that glides under the pointer instead of each row lighting up
 * on its own. Attach the ref to a `u-menu` container whose first child is
 * `<span className="u-hover-pill" aria-hidden="true" />`; motion.css does the
 * rest from --pill-y / --pill-h / data-pill.
 */
export function useHoverPill() {
  const ref = useRef(null)
  useEffect(() => {
    const menu = ref.current
    if (!menu) return
    function over(e) {
      let row = e.target
      while (row && row.parentElement !== menu) row = row.parentElement
      if (!row || row.classList.contains('u-hover-pill')) return
      menu.style.setProperty('--pill-y', `${row.offsetTop}px`)
      menu.style.setProperty('--pill-h', `${row.offsetHeight}px`)
      menu.dataset.pill = 'on'
    }
    function leave() { menu.dataset.pill = 'off' }
    menu.addEventListener('pointerover', over)
    menu.addEventListener('pointerleave', leave)
    return () => {
      menu.removeEventListener('pointerover', over)
      menu.removeEventListener('pointerleave', leave)
    }
  }, [])
  return ref
}
