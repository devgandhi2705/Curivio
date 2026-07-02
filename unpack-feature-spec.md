# Feature Spec: "Unpack" — Select-to-Explain

## Context
This is a **web app** (browser-based), not a native mobile/desktop app. Build the selection-capture using the browser's `window.getSelection()` API (or a text-selection library if the content is inside complex components like iframes/canvas), and the popover as a positioned DOM element anchored to the selection's bounding rect — not a native OS-level overlay.

## What it does
When the user selects text (word, phrase, or sentence) anywhere on the page, show a popover with:
1. **General definition** of the term
2. **Contextual meaning** — what it specifically means/implies in the sentence it was selected from (the core differentiator — not a generic dictionary answer)
3. **Translation** into the user's chosen target language

All three come from a single LLM call so they stay consistent with each other.

## Architecture

```
User selects text
   │
   ▼
Capture: selected text + full sentence it's in + 1 sentence before/after (if available)
   │
   ▼
Cache check: hash(selection + surrounding sentence) → if cached, return instantly
   │
   ▼
Fast path: if selection is a single common English word AND no context/translation
needed → hit dictionary API, return instantly, skip LLM
   │
   ▼
LLM call (structured JSON output) → render in popover → cache the result
```

## LLM provider & model choice

Use free-tier models via **Groq** (primary, fastest inference) with **Gemini** as fallback. Both are OpenAI-SDK-compatible or near-compatible, so build a thin provider-abstraction layer, not a hard dependency on one vendor.

**Primary: Groq**
- Model: `openai/gpt-oss-120b` (Groq's recommended replacement for `llama-3.3-70b-versatile`, deprecated Aug 2026 — better quality, use this) or `openai/gpt-oss-20b` (recommended replacement for `llama-3.1-8b-instant`, if you need a higher free-tier request cap over quality)
- **Note:** Groq announced on June 17, 2026 that `llama-3.1-8b-instant` and `llama-3.3-70b-versatile` are being deprecated — do not build against those model IDs. `openai/gpt-oss-120b` / `openai/gpt-oss-20b` are the current recommended models; re-check `https://console.groq.com/docs/deprecations` before building, since Groq's free-tier lineup has churned multiple times through 2026.
- Free tier: no credit card, but daily/per-minute limits vary and have shrunk over 2026 — check `https://console.groq.com/docs/rate-limits` at build time, don't hardcode assumed numbers
- Base URL: `https://api.groq.com/openai/v1` (drop-in OpenAI SDK compatible)

**Fallback: Gemini**
- Model: `gemini-2.5-flash-lite` (cheapest/fastest) or `gemini-2.5-flash` (better quality, still free-tier eligible)
- Free tier: ~1,500 requests/day, 15 RPM for Flash, no credit card required, but **note**: free-tier prompts may be used by Google to improve their models — flag this if the app handles sensitive user text
- Get key from Google AI Studio; base URL `https://generativelanguage.googleapis.com/v1beta`

**Implementation note:** Build a simple router: try Groq first, on error/429 fall back to Gemini. Both free tiers shift often (Groq cut limits mid-2026), so make model names and rate-limit thresholds config values, not hardcoded constants — expect to need to swap models occasionally.

## Dictionary API (fast path only)

Use **dictionaryapi.dev** (`https://api.dictionaryapi.dev/api/v2/entries/en/<word>`) — free, no key, no signup. Use only for: single common English word, no surrounding-context request, no translation requested. Everything else routes to the LLM.

## LLM prompt & output schema

System prompt (adjust wording, keep the constraints):

```
You are "Unpack," a feature that explains why a specific word or phrase was
used in its exact context — not a generic dictionary.

Given a selected term and the sentence it appears in, return ONLY valid JSON
matching this schema:

{
  "term": string,
  "definition_general": string,       // 1 sentence, plain dictionary-style meaning
  "meaning_in_context": string,       // 2-3 sentences max. Explain specifically
                                        // why this word/phrase was used HERE —
                                        // tone, connotation, which sense of an
                                        // ambiguous word applies, or what it implies.
                                        // Never fall back to a generic definition here.
  "translation": string | null,       // only if target_language is provided
  "confidence": "high" | "medium" | "low"
}

Rules:
- Do not repeat definition_general inside meaning_in_context.
- If the term is unambiguous and context adds nothing, say so briefly rather
  than inventing a distinction.
- Keep total output under 80 words.
- Return raw JSON only, no markdown fences, no commentary.
```

User message template:

```
Selected term: "{selection}"
Sentence: "{full_sentence}"
Surrounding context: "{prev_sentence} ... {next_sentence}"
Target language: {target_language or "none"}
```

Model params: `temperature: 0.3`, `max_tokens: ~200`, JSON mode/structured output if the provider supports it (Gemini supports `response_mime_type: application/json`; for Groq, use JSON mode if the model supports it, otherwise parse defensively).

## Caching

Cache key: `hash(normalized_selection + normalized_surrounding_sentence + target_language)`. Store the full JSON response. This avoids re-calling the LLM when multiple users select the same phrase in the same piece of content (e.g. shared articles/books).

## UI/UX requirements

- Listen for the browser's `selectionchange` / `mouseup` events to detect a text selection, and read it via `window.getSelection()`.
- Position the popover using the selection's `getBoundingClientRect()`, keeping it within the viewport (flip above/below or clamp horizontally near screen edges).
- Dismiss the popover on outside click, `Escape`, scroll, or new selection — standard web popover behavior.
- Show a lightweight loading state immediately on selection (skeleton or spinner) — LLM calls take 1-3s even on fast providers.
- If dictionary fast-path is used, render instantly with no loading state.
- Stream the LLM response if the provider supports streaming, so `meaning_in_context` appears progressively rather than all-at-once.
- If `confidence: "low"`, visually flag it (e.g. small "uncertain" label) rather than presenting it as fact.
- Popover order: definition_general → meaning_in_context (visually emphasized, this is the hook) → translation (if applicable).
- Handle provider fallback and outright failure gracefully — show definition-only (from cache/dictionary API) rather than a blank error state if the LLM call fails entirely.
- Make sure the popover works with keyboard-based selection (Shift+Arrow) and touch-based selection (mobile browsers), not just mouse drag.
- The LLM calls should go through a backend route/API endpoint, not be called directly from the browser — this keeps API keys off the client and out of the page source.

## Error handling / resilience

- Wrap every LLM call in try/catch with a timeout (~5s) and fallback provider switch on failure or 429.
- Validate JSON output before rendering; if parsing fails, retry once with a stricter "return valid JSON only" reminder, then fall back to dictionary-only result.
- Log rate-limit hits so you know when to add a paid tier or another free provider.

## Build order

1. Dictionary fast-path (dictionaryapi.dev) — simplest, ships value immediately
2. LLM path via Groq with the prompt/schema above, no caching yet
3. Add Gemini fallback + provider router
4. Add caching layer
5. Add streaming + confidence flagging in UI
