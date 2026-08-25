import { useLayoutEffect, useRef, useState, useEffect } from "react"
import { createPortal } from "react-dom"

const POPOVER_WIDTH = 288
const MARGIN = 8
// Matches the app's existing md: breakpoint (Tailwind default 768px) used
// elsewhere for mobile/desktop layout splits.
const MOBILE_BREAKPOINT = 768

function useIsMobile() {
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== "undefined" && window.innerWidth < MOBILE_BREAKPOINT
  )
  useEffect(() => {
    function onResize() {
      setIsMobile(window.innerWidth < MOBILE_BREAKPOINT)
    }
    window.addEventListener("resize", onResize)
    return () => window.removeEventListener("resize", onResize)
  }, [])
  return isMobile
}

/**
 * Positioned popover shell — a compact floating popover clamped to the
 * viewport near the selection rect. Outside-click and Escape both dismiss.
 * Content is passed in as children.
 */
export default function UnpackPopover({ rect, onClose, children }) {
  const ref = useRef(null)
  const isMobile = useIsMobile()
  const [style, setStyle] = useState({ top: -9999, left: -9999, opacity: 0 })

  useLayoutEffect(() => {
    const el = ref.current
    if (!el || !rect) return

    // Content height changes as the mode switches (menu -> explain/translate)
    // and as the explain result streams in. A ResizeObserver repositions in
    // response to those actual size changes, instead of an effect that reruns
    // on every render (which — since it always calls setStyle — would loop).
    function reposition() {
      const height = el.offsetHeight

      let left = rect.left + rect.width / 2 - POPOVER_WIDTH / 2
      left = Math.min(Math.max(left, MARGIN), window.innerWidth - POPOVER_WIDTH - MARGIN)

      let top = rect.bottom + MARGIN
      if (top + height > window.innerHeight - MARGIN) {
        const above = rect.top - height - MARGIN
        if (above >= MARGIN) top = above
      }

      setStyle({ top, left, opacity: 1 })
    }

    reposition()
    const observer = new ResizeObserver(reposition)
    observer.observe(el)
    return () => observer.disconnect()
  }, [rect, isMobile])

  useEffect(() => {
    function onMouseDown(e) {
      if (ref.current && !ref.current.contains(e.target)) onClose()
    }
    function onKeyDown(e) {
      if (e.key === "Escape") onClose()
    }
    document.addEventListener("mousedown", onMouseDown)
    document.addEventListener("keydown", onKeyDown)
    return () => {
      document.removeEventListener("mousedown", onMouseDown)
      document.removeEventListener("keydown", onKeyDown)
    }
  }, [onClose])

  const positionStyle = { top: style.top, left: style.left, width: POPOVER_WIDTH, opacity: style.opacity }

  return createPortal(
    <div
      ref={ref}
      data-unpack-popover
      style={{ position: "fixed", ...positionStyle, zIndex: 1000 }}
      className={[
        "bg-slate-900 border border-slate-700/60 shadow-2xl shadow-black/60 overflow-hidden transition-opacity duration-100",
        "rounded-xl",
      ].join(" ")}
    >
      <div className="px-3 py-1.5 border-b border-slate-800 flex items-center justify-between">
        <span className="text-[11px] font-semibold text-slate-400">Unpack</span>
        <button
          onClick={onClose}
          aria-label="Close"
          className="text-slate-500 hover:text-slate-300 transition-colors flex-shrink-0"
        >
          <svg className="w-3 h-3" viewBox="0 0 16 16" fill="currentColor">
            <path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.749.749 0 0 1 1.275.326.749.749 0 0 1-.215.734L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z" />
          </svg>
        </button>
      </div>

      {children}
    </div>,
    document.body
  )
}
