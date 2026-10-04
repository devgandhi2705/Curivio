/**
 * An uploaded document's text, shown the way the document looks — used by the
 * chat attachments.
 *
 * Word and PowerPoint files are stored as Markdown (backend/utils/office_markdown.py),
 * so both render as Markdown (MarkdownDocument: CommonMark + GFM): headings, lists, bold, tables.
 * A deck is shown one card per slide ("## Slide N: title" sections), its speaker
 * notes under the card. Markdown files render as Markdown. PDF text, plain text and
 * code stay as they are — PDF extraction has no reliable structure to render, and
 * the original PDF is shown natively where it's stored.
 */
import { lazy, Suspense } from "react"

// Full CommonMark + GFM renderer, loaded when a document is first previewed.
const MarkdownDocument = lazy(() => import("./MarkdownDocument.jsx"))

function Md({ text }) {
  return (
    <Suspense fallback={<p className="text-xs text-slate-500">Loading…</p>}>
      <MarkdownDocument text={text} />
    </Suspense>
  )
}

// "**Title**" -> "Title": slide titles are shown as a heading already.
const plainTitle = (t) => t.replace(/(\*\*\*|\*\*|\*|__|_)(.+?)\1/g, "$2").trim()

const CODE_EXT = /\.(py|js|jsx|ts|tsx|java|go|rs|c|cpp|h|hpp|cs|rb|php|sh|sql|json|ya?ml|html|css|xml|csv)$/i

export function documentKind(filename = "") {
  const f = filename.toLowerCase()
  if (f.endsWith(".pptx")) return "slides"
  if (f.endsWith(".docx")) return "word"
  if (f.endsWith(".md")) return "markdown"
  if (f.endsWith(".pdf")) return "pdf"
  if (CODE_EXT.test(f)) return "code"
  return "text"
}

const SLIDE_RE = /^## Slide (\d+)(?::\s*(.*))?$/

export function splitSlides(text) {
  const slides = []
  let current = null
  for (const line of text.split("\n")) {
    const m = line.match(SLIDE_RE)
    if (m) {
      current = { n: Number(m[1]), title: m[2] || "", body: [], notes: "" }
      slides.push(current)
      continue
    }
    if (!current) continue
    const note = line.match(/^>\s*\*\*Speaker notes:\*\*\s*(.*)$/)
    if (note) current.notes = note[1]
    else current.body.push(line)
  }
  return slides.map(s => ({ ...s, body: s.body.join("\n").trim() }))
}

function Slides({ text }) {
  const slides = splitSlides(text)
  if (!slides.length) return <Md text={text} />
  return (
    <ol className="space-y-4" aria-label="Slides">
      {slides.map(s => (
        <li key={s.n}>
          <div className="rounded-xl border border-slate-700/60 bg-slate-950/40 overflow-hidden">
            <div className="flex items-center gap-2 px-4 pt-3">
              <span className="text-[10px] font-semibold tracking-widest text-slate-500">SLIDE {s.n}</span>
            </div>
            <div className="px-5 pb-5 pt-1.5 min-h-[9rem]">
              {s.title && <h3 className="text-[17px] font-semibold text-slate-100 leading-snug mb-2">{plainTitle(s.title)}</h3>}
              {s.body ? <Md text={s.body} />
                : !s.title && <p className="text-[12px] text-slate-600">No text on this slide.</p>}
            </div>
          </div>
          {s.notes && (
            <p className="mt-1.5 px-1 text-[12px] leading-relaxed text-slate-500">
              <span className="text-slate-400 font-medium">Speaker notes: </span>{s.notes}
            </p>
          )}
        </li>
      ))}
    </ol>
  )
}

export default function DocumentPreview({ text, filename }) {
  if (!text) return <p className="text-xs text-slate-500">No text was read from this file.</p>
  const kind = documentKind(filename)
  if (kind === "slides") return <Slides text={text} />
  if (kind === "word" || kind === "markdown") return <Md text={text} />
  return (
    <pre className={`whitespace-pre-wrap break-words text-[13px] leading-relaxed text-slate-300 ${kind === "code" ? "font-mono text-[12.5px]" : "font-sans"}`}>
      {text}
    </pre>
  )
}
