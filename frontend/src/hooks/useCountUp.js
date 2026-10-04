import { useEffect, useRef, useState } from 'react'
import { easeOutCubic } from '../lib/motionMath.js'

/** Counts from the last shown value (0 on mount) to `target`. */
export function useCountUp(target, duration = 900) {
  const [shown, setShown] = useState(0)
  const shownRef = useRef(shown)

  useEffect(() => {
    const from = shownRef.current
    const t0 = performance.now()
    let raf
    const tick = now => {
      const k = Math.min(1, (now - t0) / duration)
      shownRef.current = from + (target - from) * easeOutCubic(k)
      setShown(shownRef.current)
      if (k < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [target, duration])

  return shown
}
