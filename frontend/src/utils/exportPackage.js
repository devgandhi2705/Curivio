/**
 * Client-side package export — pure templating, no network calls.
 *
 * exportAsPdf(pkg, opts)       — prints via hidden iframe → browser Save as PDF
 * downloadMarkdown(pkg, opts)  — downloads a .md file (iOS-safe)
 *
 * opts: { projectName?: string, dayLabel?: string }
 */

// ─── Shared helpers ───────────────────────────────────────────────────────────

const TYPE_EMOJI = { news: "📰", educational: "📚", curiosity: "💡" }

function fmtDate(ts) {
  if (!ts) return ""
  const d = new Date(ts)
  return d.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })
}

function escHtml(str) {
  if (!str) return ""
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
}

function resolveSource(link) {
  if (!link) return { url: "", title: "Source" }
  if (typeof link === "string") return { url: link, title: "Source" }
  return { url: link.url || "", title: link.title || "Source" }
}

function allCards(pkg) {
  return [...(pkg.insights || []), ...(pkg.curiosity_insights || [])]
}

// ─── Block renderers ──────────────────────────────────────────────────────────

function _blockMd(btype, content) {
  const text = (content || "").trim()
  if (!text) return []
  if (btype === "step_list") {
    const steps = text.split("\n").map(s => s.replace(/^\d+\.\s*/, "").trim()).filter(Boolean)
    return [...steps.map((s, i) => `${i + 1}. ${s}`), ""]
  }
  if (btype === "warning")      return [`> ⚠️ ${text}`, ""]
  if (btype === "evidence")     return [`> ${text}`, ""]
  if (btype === "key_takeaway") return [`**${text}**`, ""]
  const label = btype ? btype.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()) : "Note"
  return [`**${label}**`, "", text, ""]
}

function _blockHtml(btype, content) {
  const text = (content || "").trim()
  if (!text) return ""
  if (btype === "step_list") {
    const steps = text.split("\n").map(s => s.replace(/^\d+\.\s*/, "").trim()).filter(Boolean)
    return `<div class="block"><div class="section-label">Steps</div><ol class="steps">${steps.map(s => `<li>${escHtml(s)}</li>`).join("")}</ol></div>`
  }
  if (btype === "warning")
    return `<div class="block block-warning"><span class="block-label">⚠️ Caution</span><p>${escHtml(text)}</p></div>`
  if (btype === "evidence")
    return `<blockquote class="block-evidence"><p>${escHtml(text)}</p></blockquote>`
  if (btype === "key_takeaway")
    return `<div class="block block-takeaway"><p>${escHtml(text)}</p></div>`
  const label = btype ? btype.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()) : "Note"
  return `<div class="block block-generic"><div class="section-label">${escHtml(label)}</div><p>${escHtml(text)}</p></div>`
}

// ─── Markdown builder ─────────────────────────────────────────────────────────

function buildMarkdown(pkg, { projectName = "", dayLabel = "", nextDayTitle = "" } = {}) {
  const label = dayLabel || `Day ${pkg.day_number}`
  const date  = fmtDate(pkg.generated_at)
  const lines = []

  lines.push(`# ${pkg.package_headline || "Daily Package"}`, "")
  const meta = [label, date, projectName].filter(Boolean).join("  ·  ")
  lines.push(`**${meta}**`, "")

  if (pkg.learning_thread) {
    lines.push(`> ${pkg.learning_thread}`, "")
  }

  for (const card of allCards(pkg)) {
    const emoji = TYPE_EMOJI[card.content_type] || "📄"
    lines.push("---", "", `## ${emoji} ${card.title || ""}`, "")

    if (card.category)  lines.push(`*${card.category}*`, "")
    if (card.summary)   lines.push(card.summary, "")

    if ((card.blocks || []).length > 0) {
      for (const b of card.blocks) lines.push(..._blockMd(b.type || "", b.content || ""))
    } else {
      if (card.educational_explanation) {
        const h = card.content_type === "educational" ? "Deep Dive" : "Why This Works"
        lines.push(`### ${h}`, "", card.educational_explanation, "")
      }
      if (card.why_it_matters) {
        lines.push("### Why It Matters", "", card.why_it_matters, "")
      }
    }

    const sources = (card.source_links || []).map(resolveSource).filter(s => s.url)
    if (sources.length) {
      lines.push("### Sources", "")
      sources.forEach(s => lines.push(`- [${s.title}](${s.url})`))
      lines.push("")
    }
  }

  if (pkg.action_item) {
    lines.push("---", "", "## ✅ Today's Action", "", pkg.action_item, "")
  }

  const today = new Date().toISOString().slice(0, 10)
  lines.push("---", "", `*Exported from Curivio · ${today}*`)
  if (nextDayTitle) lines.push("", `*Next up: ${nextDayTitle}*`)

  return lines.join("\n")
}

// ─── Markdown download (iOS-safe) ─────────────────────────────────────────────

function _isIOS() {
  return /iP(hone|ad|od)/i.test(navigator.userAgent) && !window.MSStream
}

function _blobDownload(content, filename, mimeType) {
  const blob = new Blob([content], { type: mimeType })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement("a")
  a.href     = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export function downloadMarkdown(pkg, opts = {}) {
  const md   = buildMarkdown(pkg, opts)
  const slug = (pkg.package_headline || "package")
    .toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 50)
  const filename = `${slug}.md`

  if (_isIOS()) {
    // iOS Safari ignores a.download on blob: URLs — the file opens in-browser instead.
    // Open as a data URL so the native share sheet appears and the user can
    // "Save to Files" or AirDrop. text/plain ensures it previews cleanly.
    const dataUrl = "data:text/plain;charset=utf-8," + encodeURIComponent(md)
    const win = window.open(dataUrl, "_blank")
    if (!win) _blobDownload(md, filename, "text/markdown;charset=utf-8")
    return
  }

  _blobDownload(md, filename, "text/markdown;charset=utf-8")
}

// ─── PDF via browser print ────────────────────────────────────────────────────

const TYPE_COLOR = {
  news:        { text: "#2563eb", bg: "#eff6ff", border: "#bfdbfe" },
  educational: { text: "#059669", bg: "#f0fdf4", border: "#a7f3d0" },
  curiosity:   { text: "#d97706", bg: "#fffbeb", border: "#fde68a" },
}

function cardHtml(card) {
  const tc      = TYPE_COLOR[card.content_type] || { text: "#64748b", bg: "#f8fafc", border: "#e2e8f0" }
  const typeLabel = { news: "Current Events", educational: "Deep Learning", curiosity: "Curiosity Pick" }[card.content_type] || "Insight"

  const sources = (card.source_links || []).map(resolveSource).filter(s => s.url)
  const sourcesBlock = sources.length
    ? `<div class="sources">
        <div class="section-label">Sources</div>
        ${sources.map(s => `<a href="${escHtml(s.url)}" class="src-link">${escHtml(s.title)}</a>`).join("\n        ")}
      </div>`
    : ""

  let contentHtml = ""
  if ((card.blocks || []).length > 0) {
    contentHtml = card.blocks.map(b => _blockHtml(b.type || "", b.content || "")).join("\n")
  } else {
    const eduLabel = card.content_type === "educational" ? "Deep Dive" : "Why This Works"
    if (card.educational_explanation)
      contentHtml += `<div class="inset"><div class="section-label">${eduLabel}</div><p>${escHtml(card.educational_explanation)}</p></div>`
    if (card.why_it_matters)
      contentHtml += `<div class="inset why"><div class="section-label">Why It Matters</div><p>${escHtml(card.why_it_matters)}</p></div>`
  }

  const catBadge = card.category
    ? `<span class="cat">${escHtml(card.category)}</span>`
    : ""

  return `
    <div class="card" style="border-color:${tc.border}">
      <div class="type-badge" style="color:${tc.text};background:${tc.bg};border-color:${tc.border}">${typeLabel}</div>
      <h2 class="card-title">${escHtml(card.title)}</h2>
      ${catBadge}
      <p class="summary">${escHtml(card.summary || "")}</p>
      ${contentHtml}
      ${sourcesBlock}
    </div>`
}

function _buildPrintHtml(pkg, { projectName = "", dayLabel = "", nextDayTitle = "" } = {}) {
  const label = dayLabel || `Day ${pkg.day_number}`
  const date  = fmtDate(pkg.generated_at)
  const meta  = [label, date, projectName].filter(Boolean).join(" · ")
  const today = new Date().toISOString().slice(0, 10)

  const threadHtml = pkg.learning_thread
    ? `<blockquote class="thread">${escHtml(pkg.learning_thread)}</blockquote>`
    : ""

  const actionHtml = pkg.action_item
    ? `<div class="action">
        <div class="action-label">Today's Action</div>
        <p>${escHtml(pkg.action_item)}</p>
      </div>`
    : ""

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>${escHtml(pkg.package_headline || "Daily Package")}</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
    font-size:13px;line-height:1.65;color:#1a1a1a;background:#fff;
    padding:48px 56px;max-width:780px;margin:0 auto
  }
  .meta{
    font-size:10px;font-weight:700;letter-spacing:.07em;
    text-transform:uppercase;color:#64748b;margin-bottom:10px
  }
  h1{font-size:22px;font-weight:800;line-height:1.25;color:#0f172a;margin-bottom:14px}
  .thread{
    border-left:3px solid #94a3b8;padding:8px 14px;
    color:#475569;font-size:12px;font-style:italic;margin-bottom:28px
  }
  .card{
    border:1px solid #e2e8f0;border-radius:10px;
    padding:18px 20px;margin-bottom:16px;break-inside:avoid
  }
  .type-badge{
    display:inline-block;font-size:9px;font-weight:700;
    letter-spacing:.07em;text-transform:uppercase;
    border:1px solid;border-radius:4px;padding:2px 7px;margin-bottom:9px
  }
  .card-title{font-size:15px;font-weight:700;color:#0f172a;line-height:1.35;margin-bottom:5px}
  .cat{
    display:inline-block;font-size:10px;color:#64748b;
    background:#f1f5f9;border-radius:4px;padding:1px 6px;margin-bottom:9px
  }
  .summary{color:#374151;font-size:13px;margin-bottom:12px}
  .inset{
    background:#f8fafc;border-radius:6px;
    padding:10px 13px;margin-bottom:10px
  }
  .why{background:#fafaf5}
  .section-label{
    font-size:9px;font-weight:700;text-transform:uppercase;
    letter-spacing:.06em;color:#94a3b8;margin-bottom:5px
  }
  .inset p{font-size:12px;color:#475569;line-height:1.6}
  .sources{margin-top:10px}
  .src-link{
    display:block;font-size:11px;color:#2563eb;
    text-decoration:none;word-break:break-all;margin-top:3px
  }
  .src-link:hover{text-decoration:underline}
  .action{
    border:1px solid #bfdbfe;border-radius:10px;
    padding:14px 18px;background:#eff6ff;
    margin-bottom:16px;break-inside:avoid
  }
  .action-label{
    font-size:9px;font-weight:700;text-transform:uppercase;
    letter-spacing:.06em;color:#2563eb;margin-bottom:7px
  }
  .action p{color:#1e3a5f;font-size:13px}
  .footer{
    margin-top:32px;padding-top:12px;border-top:1px solid #e2e8f0;
    font-size:10px;color:#94a3b8
  }
  .next-up{display:block;margin-top:6px;font-size:10px;color:#64748b;font-style:italic}
  .block{margin-bottom:10px}
  .block-warning{border-left:3px solid #f59e0b;padding:8px 12px;background:#fffbeb;border-radius:0 4px 4px 0;margin-bottom:10px}
  .block-label{display:block;font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:#b45309;margin-bottom:4px}
  .block-warning p{font-size:12px;color:#92400e;line-height:1.6;margin:0}
  .block-evidence{border-left:3px solid #94a3b8;margin:0 0 10px;padding:6px 12px}
  .block-evidence p{font-size:12px;color:#64748b;font-style:italic;margin:0;line-height:1.6}
  .block-takeaway{background:#eff6ff;border:1px solid #bfdbfe;border-radius:5px;padding:8px 12px;margin-bottom:10px}
  .block-takeaway p{font-size:12px;color:#1e40af;margin:0;line-height:1.6}
  .block-generic{margin-bottom:10px}
  .block-generic p{font-size:12px;color:#475569;margin:0;line-height:1.6}
  .steps{padding-left:18px;margin:4px 0 0}
  .steps li{font-size:12px;color:#374151;line-height:1.6;margin-bottom:3px}
  @media print{
    body{padding:20px 24px}
    .card{break-inside:avoid;page-break-inside:avoid}
    .src-link{color:#2563eb!important}
    @page{margin:1.5cm}
  }
</style>
</head>
<body>
  <div class="meta">${escHtml(meta)}</div>
  <h1>${escHtml(pkg.package_headline || "Daily Package")}</h1>
  ${threadHtml}
  ${allCards(pkg).map(cardHtml).join("\n")}
  ${actionHtml}
  <div class="footer">Exported from Curivio · ${today}${nextDayTitle ? `<span class="next-up">Next up: ${escHtml(nextDayTitle)}</span>` : ""}</div>
</body>
</html>`
}

/**
 * Primary strategy: hidden iframe — no popup permission required, works on mobile.
 * Fallback: window.open popup.
 * Last resort: markdown download.
 */
export function exportAsPdf(pkg, opts = {}) {
  const html = _buildPrintHtml(pkg, opts)

  // Hidden iframe — no popup blocker issues
  const iframe = document.createElement("iframe")
  iframe.setAttribute("title", "Print preview")
  iframe.style.cssText = "position:fixed;left:-9999px;top:-9999px;width:1px;height:1px;opacity:0"
  document.body.appendChild(iframe)

  function cleanup() {
    if (iframe.parentNode) document.body.removeChild(iframe)
  }

  iframe.onload = function () {
    try {
      // Wire up afterprint cleanup so the iframe is removed once the dialog closes
      iframe.contentWindow.onafterprint = cleanup
      // Safety: always remove after 30s in case onafterprint doesn't fire
      const safeguard = setTimeout(cleanup, 30_000)
      iframe.contentWindow.onafterprint = () => { clearTimeout(safeguard); cleanup() }

      iframe.contentWindow.focus()
      iframe.contentWindow.print()
    } catch (_err) {
      // Some environments block iframe printing — try popup fallback
      cleanup()
      _popupPdf(html, pkg, opts)
    }
  }

  // srcdoc avoids deprecated document.write() and doesn't trigger popup blockers
  iframe.srcdoc = html
}

function _popupPdf(html, pkg, opts) {
  // Inject auto-print script for the popup window
  const htmlWithPrint = html.replace(
    "</body>",
    "<script>window.onload=function(){window.print()}<\/script></body>"
  )
  const win = window.open("", "_blank")
  if (!win) {
    // Popup blocked — last resort: markdown file
    downloadMarkdown(pkg, opts)
    return
  }
  win.document.open()
  win.document.write(htmlWithPrint)
  win.document.close()
}
