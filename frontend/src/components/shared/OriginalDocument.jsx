/**
 * An uploaded file shown as itself — the way PDF already is (the browser's own
 * viewer) — for the formats a browser can't open natively:
 *   - PowerPoint: each slide drawn as laid out (positions, colours, images, tables)
 *     by pptx-preview;
 *   - Word: pages as Word lays them out, by docx-preview;
 *   - Markdown: the file rendered as Markdown (GitHub-flavoured: tables, task lists,
 *     code blocks), from the original bytes rather than the chunked text.
 *
 * The renderers are loaded only when a file of that kind is opened, so they add
 * nothing to the app's main bundle. They're client-side approximations: unusual
 * fonts, SmartArt, charts and animations may not look exactly like Office. The
 * "text Curivio read" view next to it is what the agents actually use.
 */
import { lazy, Suspense, useEffect, useRef, useState } from "react"

const MarkdownDocument = lazy(() => import("./MarkdownDocument.jsx"))

export const ORIGINAL_KINDS = new Set(["slides", "word", "markdown"])

function Loading() {
  return <p className="text-xs text-slate-500">Loading…</p>
}

function Failed({ message }) {
  return (
    <p className="text-xs text-slate-500">
      {message || "This file couldn't be drawn here."} The text Curivio read is in the other tab.
    </p>
  )
}

function Slides({ url }) {
  const host = useRef(null)
  const [state, setState] = useState("loading")
  useEffect(() => {
    let previewer = null
    let cancelled = false
    ;(async () => {
      try {
        const [{ init }, buf] = await Promise.all([
          import("pptx-preview"),
          fetch(url).then(r => r.arrayBuffer()),
        ])
        if (cancelled || !host.current) return
        const width = Math.max(320, Math.floor(host.current.clientWidth))
        previewer = init(host.current, { width, height: Math.round(width * 9 / 16), mode: "list" })
        await previewer.preview(buf)
        if (!cancelled) setState("done")
      } catch (e) {
        console.warn("[preview] pptx render failed", e)
        if (!cancelled) setState("failed")
      }
    })()
    return () => {
      cancelled = true
      try { previewer?.destroy() } catch { /* already gone */ }
      if (host.current) host.current.innerHTML = ""
    }
  }, [url])
  return (
    <>
      {state === "loading" && <Loading />}
      {state === "failed" && <Failed />}
      <div ref={host} className="pptx-original w-full" aria-label="Slides" />
    </>
  )
}

function Word({ url }) {
  const host = useRef(null)
  const [state, setState] = useState("loading")
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const [{ renderAsync }, blob] = await Promise.all([
          import("docx-preview"),
          fetch(url).then(r => r.blob()),
        ])
        if (cancelled || !host.current) return
        await renderAsync(blob, host.current, undefined, {
          className: "docx", inWrapper: true, breakPages: true,
          ignoreLastRenderedPageBreak: true, renderHeaders: true, renderFooters: true,
          renderFootnotes: true, useBase64URL: true,
        })
        if (!cancelled) setState("done")
      } catch (e) {
        console.warn("[preview] docx render failed", e)
        if (!cancelled) setState("failed")
      }
    })()
    return () => { cancelled = true; if (host.current) host.current.innerHTML = "" }
  }, [url])
  return (
    <>
      {state === "loading" && <Loading />}
      {state === "failed" && <Failed />}
      <div ref={host} className="docx-original w-full overflow-x-auto rounded-lg" />
    </>
  )
}

function Markdown({ url }) {
  const [text, setText] = useState(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let cancelled = false
    fetch(url).then(r => r.text())
      .then(t => { if (!cancelled) setText(t) })
      .catch(() => { if (!cancelled) setFailed(true) })
    return () => { cancelled = true }
  }, [url])
  if (failed) return <Failed />
  if (text == null) return <Loading />
  return (
    <Suspense fallback={<Loading />}>
      <MarkdownDocument text={text} />
    </Suspense>
  )
}

/** kind: "slides" | "word" | "markdown"; url: an object URL of the original bytes. */
export default function OriginalDocument({ kind, url }) {
  if (kind === "slides") return <Slides url={url} />
  if (kind === "word") return <Word url={url} />
  if (kind === "markdown") return <Markdown url={url} />
  return null
}
