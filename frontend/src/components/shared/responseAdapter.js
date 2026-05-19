const TITLE_RE = /\[TITLE:[^\]]*\]\s*/g

export function cleanContent(text) {
  return text.replace(TITLE_RE, "").trimStart()
}

// Convert a structured response object → clean markdown string.
export function srToMarkdown(sr) {
  if (!sr || typeof sr.response_type !== "string") return null
  const lines = []
  if (sr.title)   lines.push(`## ${sr.title}`, "")
  if (sr.summary) lines.push(sr.summary, "")
  for (const sec of sr.sections || []) {
    if (sec.title)   lines.push(`### ${sec.title}`)
    if (sec.content) lines.push(sec.content)
    lines.push("")
  }
  if (sr.key_takeaways?.length) {
    lines.push("**Key Takeaways**")
    for (const t of sr.key_takeaways) lines.push(`- ${t}`)
    lines.push("")
  }
  if (sr.resources?.length) {
    lines.push("**Resources**")
    for (const r of sr.resources)
      lines.push(r.url ? `- [${r.title}](${r.url})` : `- ${r.title}`)
    lines.push("")
  }
  if (sr.next_topics?.length)
    lines.push(`**Explore Next:** ${sr.next_topics.join(" · ")}`)
  return lines.join("\n").trim() || null
}

// Try to parse streamed JSON text → SR object (used when the object isn't on message).
export function tryParseStructuredResponse(content) {
  if (!content) return null
  try {
    // Strip [TITLE: ...] prefix and any code fences the LLM may have added
    let cleaned = content.replace(TITLE_RE, "").trim()
      .replace(/^```(?:json)?\s*/i, "")
      .replace(/\s*```$/, "")
      .trim()
    // Find the first { so any stray leading text doesn't block parsing
    const start = cleaned.indexOf("{")
    if (start === -1) return null
    cleaned = cleaned.slice(start)
    const parsed = JSON.parse(cleaned)
    if (typeof parsed.response_type !== "string") return null
    return parsed
  } catch {
    return null
  }
}

// Normalize a message object into { srObject, displayContent }.
export function normalizeResponse(message) {
  const srObject = message.structured_response ?? tryParseStructuredResponse(message.content)
  const displayContent = srObject ? null : cleanContent(message.content)
  return { srObject, displayContent }
}
