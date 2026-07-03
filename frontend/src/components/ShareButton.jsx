import { useState, useEffect, useLayoutEffect, useRef } from "react"
import { createPortal } from "react-dom"
import { createShareLink } from "../api/share.js"

const webShareSupported = typeof navigator !== "undefined" && typeof navigator.share === "function"

const POPOVER_WIDTH = 256 // w-64
const MARGIN = 8

const PLATFORMS = [
  {
    id: 'twitter',
    label: 'X / Twitter',
    buildUrl: (url, title) => {
      const t = title.length > 200 ? `${title.slice(0, 197)}...` : title
      return `https://twitter.com/intent/tweet?text=${encodeURIComponent(t + ' — ')}&url=${encodeURIComponent(url)}`
    },
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.744l7.736-8.84L1.254 2.25H8.08l4.258 5.63zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>
      </svg>
    ),
  },
  {
    id: 'whatsapp',
    label: 'WhatsApp',
    buildUrl: (url, title) => `https://wa.me/?text=${encodeURIComponent(title + '\n' + url)}`,
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z"/>
        <path d="M12 0C5.373 0 0 5.373 0 12c0 2.117.554 4.103 1.523 5.827L.057 23.882l6.22-1.633A11.954 11.954 0 0 0 12 24c6.627 0 12-5.373 12-12S18.627 0 12 0zm0 21.818a9.818 9.818 0 0 1-5.017-1.374l-.36-.214-3.732.979.996-3.638-.234-.374A9.818 9.818 0 0 1 2.182 12c0-5.422 4.396-9.818 9.818-9.818 5.422 0 9.818 4.396 9.818 9.818 0 5.422-4.396 9.818-9.818 9.818z"/>
      </svg>
    ),
  },
  {
    id: 'telegram',
    label: 'Telegram',
    buildUrl: (url, title) => `https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(title)}`,
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"/>
      </svg>
    ),
  },
  {
    id: 'reddit',
    label: 'Reddit',
    buildUrl: (url, title) => `https://www.reddit.com/submit?url=${encodeURIComponent(url)}&title=${encodeURIComponent(title)}`,
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M12 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0zm5.01 4.744c.688 0 1.25.561 1.25 1.249a1.25 1.25 0 0 1-2.498.056l-2.597-.547-.8 3.747c1.824.07 3.48.632 4.674 1.488.308-.309.73-.491 1.207-.491.968 0 1.754.786 1.754 1.754 0 .716-.435 1.333-1.01 1.614a3.111 3.111 0 0 1 .042.52c0 2.694-3.13 4.87-7.004 4.87-3.874 0-7.004-2.176-7.004-4.87 0-.183.015-.366.043-.534A1.748 1.748 0 0 1 4.028 12c0-.968.786-1.754 1.754-1.754.463 0 .898.196 1.207.49 1.207-.883 2.878-1.43 4.744-1.487l.885-4.182a.342.342 0 0 1 .14-.197.35.35 0 0 1 .238-.042l2.906.617a1.214 1.214 0 0 1 1.108-.701zM9.25 12C8.561 12 8 12.562 8 13.25c0 .687.561 1.248 1.25 1.248.687 0 1.248-.561 1.248-1.249 0-.688-.561-1.249-1.249-1.249zm5.5 0c-.687 0-1.248.561-1.248 1.25 0 .687.561 1.248 1.249 1.248.688 0 1.249-.561 1.249-1.249 0-.687-.562-1.249-1.25-1.249zm-5.466 3.99a.327.327 0 0 0-.231.094.33.33 0 0 0 0 .463c.842.842 2.484.913 2.961.913.477 0 2.105-.056 2.961-.913a.361.361 0 0 0 .029-.463.33.33 0 0 0-.464 0c-.547.533-1.684.73-2.512.73-.828 0-1.979-.196-2.512-.73a.326.326 0 0 0-.232-.095z"/>
      </svg>
    ),
  },
  {
    id: 'linkedin',
    label: 'LinkedIn',
    buildUrl: (url) => `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(url)}`,
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 0 1-2.063-2.065 2.064 2.064 0 1 1 2.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/>
      </svg>
    ),
  },
  {
    id: 'facebook',
    label: 'Facebook',
    buildUrl: (url) => `https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(url)}`,
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"/>
      </svg>
    ),
  },
  {
    id: 'email',
    label: 'Email',
    buildUrl: (url, title, text) =>
      `mailto:?subject=${encodeURIComponent(title)}&body=${encodeURIComponent((text ? text + '\n\n' : '') + url)}`,
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
           strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <rect x="2" y="4" width="20" height="16" rx="2"/>
        <polyline points="2,4 12,13 22,4"/>
      </svg>
    ),
  },
]

const ACTION_BTN_CLASS = "inline-flex items-center gap-1 md:gap-1.5 px-2 py-0.5 md:px-2.5 md:py-1 rounded-lg text-[11px] font-medium text-slate-400 hover:text-blue-300 bg-slate-800/20 hover:bg-blue-500/10 border border-slate-700/20 hover:border-blue-500/30 md:bg-slate-800/40 md:border-slate-700/40 transition-all"

export default function ShareButton({ type, resourceId, shareTitle = "", shareText = "", className = "" }) {
  const [isOpen, setIsOpen]     = useState(false)
  const [shareUrl, setShareUrl] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [copied, setCopied]     = useState(false)
  const [error, setError]       = useState("")

  const wrapperRef    = useRef(null)
  const popoverRef    = useRef(null)
  const copyTimerRef  = useRef(null)
  const errorTimerRef = useRef(null)
  const [popoverStyle, setPopoverStyle] = useState({ top: -9999, left: -9999, opacity: 0 })

  useEffect(() => () => {
    clearTimeout(copyTimerRef.current)
    clearTimeout(errorTimerRef.current)
  }, [])

  async function handleTriggerClick(e) {
    e.stopPropagation()
    if (shareUrl) {
      setIsOpen(true)
      return
    }
    setIsLoading(true)
    try {
      const data = await createShareLink(type, resourceId)
      setShareUrl(`${window.location.origin}/share/${data.token}`)
      setIsOpen(true)
    } catch {
      setError("Could not generate link. Try again.")
      clearTimeout(errorTimerRef.current)
      errorTimerRef.current = setTimeout(() => setError(""), 3000)
    } finally {
      setIsLoading(false)
    }
  }

  // Fixed-position + portal to <body> so the popover can't be clipped by a
  // scrolling ancestor (the feed/chat panes are all overflow-y-auto), and
  // flips above the trigger when there isn't room below.
  useLayoutEffect(() => {
    const btn = wrapperRef.current
    const el  = popoverRef.current
    if (!isOpen || !btn || !el) return

    function reposition() {
      const btnRect = btn.getBoundingClientRect()
      const height  = el.offsetHeight

      let left = btnRect.right - POPOVER_WIDTH
      left = Math.min(Math.max(left, MARGIN), window.innerWidth - POPOVER_WIDTH - MARGIN)

      let top = btnRect.bottom + MARGIN
      if (top + height > window.innerHeight - MARGIN) {
        const above = btnRect.top - height - MARGIN
        top = above >= MARGIN ? above : Math.max(MARGIN, window.innerHeight - height - MARGIN)
      }

      setPopoverStyle({ top, left, opacity: 1 })
    }

    reposition()
    const observer = new ResizeObserver(reposition)
    observer.observe(el)
    window.addEventListener("scroll", reposition, true)
    window.addEventListener("resize", reposition)
    return () => {
      observer.disconnect()
      window.removeEventListener("scroll", reposition, true)
      window.removeEventListener("resize", reposition)
    }
  }, [isOpen])

  useEffect(() => {
    if (!isOpen) return
    function onMouseDown(e) {
      if (wrapperRef.current?.contains(e.target)) return
      if (popoverRef.current?.contains(e.target)) return
      setIsOpen(false)
    }
    function onKeyDown(e) {
      if (e.key === "Escape") setIsOpen(false)
    }
    document.addEventListener("mousedown", onMouseDown)
    document.addEventListener("keydown", onKeyDown)
    return () => {
      document.removeEventListener("mousedown", onMouseDown)
      document.removeEventListener("keydown", onKeyDown)
    }
  }, [isOpen])

  function handleCopy(e) {
    e.stopPropagation()
    navigator.clipboard.writeText(shareUrl)
    setCopied(true)
    clearTimeout(copyTimerRef.current)
    copyTimerRef.current = setTimeout(() => setCopied(false), 2000)
  }

  function handleWebShare(e) {
    e.stopPropagation()
    navigator.share({
      title: shareTitle || "Curivio",
      text:  shareText || shareTitle || "Check this out on Curivio",
      url:   shareUrl,
    }).catch(() => {})
  }

  return (
    <div ref={wrapperRef} className={`relative inline-block ${className}`}>
      <button onClick={handleTriggerClick} className={ACTION_BTN_CLASS}>
        {isLoading ? (
          <span className="share-spinner" />
        ) : (
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" strokeWidth="2"
               strokeLinecap="round" strokeLinejoin="round"
               aria-hidden="true">
            <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
            <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
          </svg>
        )}
      </button>

      {error && (
        <span className="absolute top-full right-0 mt-1 text-[10px] text-red-400 whitespace-nowrap z-50">{error}</span>
      )}

      {isOpen && createPortal(
        <div
          ref={popoverRef}
          style={{ position: "fixed", top: popoverStyle.top, left: popoverStyle.left, opacity: popoverStyle.opacity }}
          className="z-50 w-64 rounded-xl bg-slate-900 border border-slate-700/60 shadow-2xl shadow-black/60 overflow-hidden transition-opacity duration-100"
        >
          <div className="px-3 py-2 border-b border-slate-800 flex items-center justify-between">
            <span className="text-[11px] font-semibold text-slate-400">Share</span>
            <button onClick={() => setIsOpen(false)} aria-label="Close" className="text-slate-500 hover:text-slate-300 transition-colors">
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
                <line x1="1" y1="1" x2="13" y2="13"/>
                <line x1="13" y1="1" x2="1" y2="13"/>
              </svg>
            </button>
          </div>

          <div className="px-3 py-3">
            <div className="grid grid-cols-4 gap-2">
              {PLATFORMS.map(p => (
                <a
                  key={p.id}
                  href={p.buildUrl(shareUrl, shareTitle, shareText)}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={p.label}
                  title={p.label}
                  className="w-10 h-10 flex items-center justify-center rounded-lg text-slate-400 hover:text-blue-300 bg-slate-800/40 hover:bg-blue-500/10 border border-slate-700/40 hover:border-blue-500/30 transition-all"
                >
                  {p.icon}
                </a>
              ))}
            </div>

            <button onClick={handleCopy} className={`mt-3 w-full justify-between ${ACTION_BTN_CLASS}`}>
              <span className="inline-flex items-center gap-1.5">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                     strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
                  <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
                </svg>
                Copy link
              </span>
              {copied && <span>Copied!</span>}
            </button>

            {webShareSupported && (
              <button onClick={handleWebShare} className={`mt-2 w-full justify-center ${ACTION_BTN_CLASS}`}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                     strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/>
                  <circle cx="18" cy="19" r="3"/>
                  <line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/>
                  <line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>
                </svg>
                Share via...
              </button>
            )}
          </div>
        </div>,
        document.body
      )}

      <style>{`
        .share-spinner {
          display: inline-block;
          width: 14px;
          height: 14px;
          border: 2px solid currentColor;
          border-top-color: transparent;
          border-radius: 50%;
          animation: share-spin 0.6s linear infinite;
        }
        @keyframes share-spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  )
}
