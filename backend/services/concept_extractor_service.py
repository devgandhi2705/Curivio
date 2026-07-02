"""
Concept Extractor Service

LLM-assisted extraction of learning metadata from a generated feed package.
Called by knowledge_state_service after every feed generation.

Public API
----------
extract(package) -> dict
    Returns {new_topics, new_entities, new_keywords, new_gaps}
    All values are list[str]. Falls back to regex extraction on LLM failure.
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

_SCHEMA = """{
  "new_topics":   ["broad topic area covered", "another area"],
  "new_entities": ["OpenAI", "Transformer architecture", "FDA"],
  "new_keywords": ["RLHF", "yield curve inversion", "RAG pipeline"],
  "new_gaps":     ["How do attention heads specialise?", "Impact on emerging markets"]
}"""


def extract(package: dict) -> dict:
    """
    Use an LLM to extract structured learning metadata from a feed package.
    Returns the four-field dict. Falls back to regex if the LLM call fails.
    """
    try:
        return _llm_extract(package)
    except Exception as e:
        logger.warning(
            "[concept_extractor] LLM extraction failed for project=%s day=%s (%s) — using regex fallback",
            package.get("project_id"), package.get("day_number"), e,
        )
        return _regex_fallback(package)


# ── LLM path ───────────────────────────────────────────────────────────────────

def _build_card_block(package: dict) -> str:
    all_cards = (package.get("insights") or []) + (package.get("curiosity_insights") or [])
    parts = []
    for card in all_cards:
        title   = (card.get("title")                   or "").strip()
        cat     = (card.get("category")                or "").strip()
        summary = (card.get("summary")                 or "")[:300].strip()
        edu     = (card.get("educational_explanation") or "")[:400].strip()
        if not title:
            continue
        parts.append(
            f"[{cat.upper() or 'CARD'}] {title}\n"
            f"Summary: {summary}\n"
            f"Explanation: {edu}"
        )
    return "\n\n".join(parts) if parts else "(no cards)"


def _llm_extract(package: dict) -> dict:
    card_block = _build_card_block(package)
    prompt = f"""You are analysing a learning package just delivered to a student.
Extract structured metadata so the system knows what has been taught and what to explore next.

PACKAGE CARDS:
{card_block}

Return a JSON object with exactly these four keys:

new_topics   — 3–8 broad subject areas covered in this package (e.g. "Regulatory Compliance", "Model Training Techniques")
new_entities — 5–15 specific named things: companies, technologies, frameworks, tools, organisations, notable people
               (e.g. "OpenAI", "Transformer", "Federal Reserve", "FDA", "React")
new_keywords — 5–15 precise technical or domain terms worth tracking as concept anchors
               (e.g. "RLHF", "yield curve inversion", "monoclonal antibodies", "RAG pipeline")
new_gaps     — 2–6 topics or questions raised but NOT fully resolved in this package —
               areas the learner should go deeper on in future sessions
               (e.g. "Long-term effects of quantitative easing", "How attention heads specialise")

Rules:
- Strings only; no nested objects or arrays within values
- No duplicates within any list
- new_entities: proper nouns only (capitalised); skip common nouns
- new_keywords: specific terms, not generic words like "data" or "system"
- new_gaps: phrase as short learning questions or "X in more depth"

Return ONLY valid JSON matching this schema:
{_SCHEMA}"""

    from .grok_service import ask_grok
    raw  = ask_grok(prompt, json_mode=True)
    data = _parse_json(raw)
    return {
        "new_topics":   _ensure_str_list(data.get("new_topics")),
        "new_entities": _ensure_str_list(data.get("new_entities")),
        "new_keywords": _ensure_str_list(data.get("new_keywords")),
        "new_gaps":     _ensure_str_list(data.get("new_gaps")),
    }


# ── Regex fallback ─────────────────────────────────────────────────────────────

_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "how", "why", "what", "when", "where", "who", "is", "are",
    "was", "were", "has", "have", "had", "its", "as", "by", "from", "this",
    "that", "they", "their", "into", "not", "does", "did",
})


def _regex_fallback(package: dict) -> dict:
    all_cards = (package.get("insights") or []) + (package.get("curiosity_insights") or [])
    topics:   list[str] = []
    entities: list[str] = []
    keywords: list[str] = []

    for card in all_cards:
        cat   = (card.get("category") or "").strip()
        title = (card.get("title")    or "").strip()
        if cat:
            topics.append(cat)
        if title:
            entities.extend(_regex_entities(title))
            keywords.extend(_regex_keywords(title))

    return {
        "new_topics":   _dedup(topics),
        "new_entities": _dedup(entities),
        "new_keywords": _dedup(keywords),
        "new_gaps":     [],
    }


def _regex_entities(title: str) -> list[str]:
    words  = title.split()
    run    = []
    result = []
    for word in words:
        clean = re.sub(r"[^a-zA-Z]", "", word)
        if clean and clean[0].isupper() and len(clean) > 2:
            run.append(word.rstrip(".,;:"))
        else:
            if len(run) >= 2:
                result.append(" ".join(run))
            elif run:
                result.append(run[0])
            run = []
    if run:
        result.append(" ".join(run) if len(run) >= 2 else run[0])
    return result


def _regex_keywords(title: str) -> list[str]:
    words = [w.strip(".,;:?!\"'()") for w in title.split()]
    return [w for w in words if len(w) > 3 and w.lower() not in _STOPWORDS][:3]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_json(text: str) -> dict:
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start : end + 1])
    return json.loads(text.strip())


def _ensure_str_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if v and str(v).strip()]
    return []


def _dedup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out:  list[str] = []
    for v in items:
        k = v.lower()
        if k not in seen:
            seen.add(k)
            out.append(v)
    return out
