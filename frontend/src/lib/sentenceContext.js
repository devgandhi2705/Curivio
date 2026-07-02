/**
 * Extracts the sentence a selection falls in, plus one sentence before/after,
 * from the plain text of its containing block.
 */

const SENTENCE_SPLIT_RE = /(?<=[.!?])\s+(?=[A-Z0-9"'])/

export function extractSentenceContext(containerText, selectedText) {
  const text   = (containerText || "").replace(/\s+/g, " ").trim()
  const needle = (selectedText || "").trim()

  if (!text || !needle) {
    return { sentence: needle, prevSentence: "", nextSentence: "" }
  }

  const idx = text.indexOf(needle)
  const sentences = text.split(SENTENCE_SPLIT_RE)

  if (idx === -1 || sentences.length === 0) {
    return { sentence: needle, prevSentence: "", nextSentence: "" }
  }

  let cursor = 0
  let sentenceIndex = 0
  for (let i = 0; i < sentences.length; i++) {
    const len = sentences[i].length
    if (idx < cursor + len + 1) {
      sentenceIndex = i
      break
    }
    cursor += len + 1
  }

  return {
    sentence:     sentences[sentenceIndex]?.trim() || needle,
    prevSentence: sentences[sentenceIndex - 1]?.trim() || "",
    nextSentence: sentences[sentenceIndex + 1]?.trim() || "",
  }
}
