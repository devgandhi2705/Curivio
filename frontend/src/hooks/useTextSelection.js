import { useState, useEffect, useCallback, useRef } from "react"
import { extractSentenceContext } from "../lib/sentenceContext.js"

const MAX_SELECTION_LENGTH = 300
const TOUCH_READ_DELAY_MS = 60 // mobile browsers can finalize a touch selection slightly after touchend

function findBlockContainer(node) {
  let el = node.nodeType === 1 ? node : node.parentElement
  while (el && el.parentElement) {
    const display = window.getComputedStyle(el).display
    if (display === "block" || display === "list-item" || el.tagName === "BODY") return el
    el = el.parentElement
  }
  return el
}

/**
 * Tracks the current browser text selection (mouse, keyboard Shift+Arrow,
 * or touch) and derives the sentence it falls in plus one sentence of
 * surrounding context, ready for the Unpack API.
 */
export function useTextSelection() {
  const [selection, setSelection] = useState(null) // { text, sentence, prevSentence, nextSentence, rect }
  const rafRef = useRef(null)
  const touchTimeoutRef = useRef(null)

  const readSelection = useCallback(() => {
    const sel = window.getSelection()
    if (!sel || sel.isCollapsed || sel.rangeCount === 0) {
      setSelection(null)
      return
    }

    const text = sel.toString().trim()
    if (!text || text.length > MAX_SELECTION_LENGTH) {
      setSelection(null)
      return
    }

    const anchorNode = sel.anchorNode
    if (!anchorNode) { setSelection(null); return }
    const anchorEl = anchorNode.nodeType === 1 ? anchorNode : anchorNode.parentElement
    // [data-unpack-popover] excludes selecting the popover's own explanation text
    // from re-triggering a new lookup on itself.
    if (anchorEl?.closest?.("input, textarea, [contenteditable='true'], [data-unpack-popover]")) {
      setSelection(null)
      return
    }

    const range = sel.getRangeAt(0)
    const rect = range.getBoundingClientRect()
    if (!rect || (rect.width === 0 && rect.height === 0)) {
      setSelection(null)
      return
    }

    const container = findBlockContainer(range.commonAncestorContainer)
    const containerText = container?.innerText || container?.textContent || text
    const { sentence, prevSentence, nextSentence } = extractSentenceContext(containerText, text)

    setSelection({ text, sentence, prevSentence, nextSentence, rect })
  }, [])

  const handle = useCallback(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current)
    rafRef.current = requestAnimationFrame(readSelection)
  }, [readSelection])

  const handleTouchEnd = useCallback(() => {
    // iOS/Android can finalize the touch selection a beat after touchend fires —
    // reading immediately (even via rAF) sometimes catches the pre-adjustment range.
    if (touchTimeoutRef.current) clearTimeout(touchTimeoutRef.current)
    touchTimeoutRef.current = setTimeout(readSelection, TOUCH_READ_DELAY_MS)
  }, [readSelection])

  useEffect(() => {
    document.addEventListener("selectionchange", handle)
    document.addEventListener("mouseup", handle)
    document.addEventListener("touchend", handleTouchEnd)
    return () => {
      document.removeEventListener("selectionchange", handle)
      document.removeEventListener("mouseup", handle)
      document.removeEventListener("touchend", handleTouchEnd)
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
      if (touchTimeoutRef.current) clearTimeout(touchTimeoutRef.current)
    }
  }, [handle, handleTouchEnd])

  const clear = useCallback(() => {
    setSelection(null)
  }, [])

  return { selection, clear }
}
