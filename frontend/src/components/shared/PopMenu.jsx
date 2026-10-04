import { forwardRef } from 'react'
import { m, presets } from '../../lib/motion.jsx'
import { useHoverPill } from '../../hooks/useHoverPill.js'

/**
 * A dropdown / popover panel. Pops from its trigger (give it the Tailwind
 * origin-* class matching where it opens), its items rise in 30ms apart, one
 * highlight glides under the pointer, and it plays an exit when the parent's
 * AnimatePresence drops it. Every other prop reaches the panel unchanged.
 */
const PopMenu = forwardRef(function PopMenu({ className = '', children, ...rest }, outerRef) {
  const pillRef = useHoverPill()
  const setRefs = el => {
    pillRef.current = el
    if (typeof outerRef === 'function') outerRef(el)
    else if (outerRef) outerRef.current = el
  }
  return (
    <m.div {...presets.menu} {...rest} ref={setRefs} className={`u-menu ${className}`}>
      <span className="u-hover-pill" aria-hidden="true" />
      {children}
    </m.div>
  )
})

export default PopMenu
