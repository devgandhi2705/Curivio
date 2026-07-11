"""
writer_provider_router — Gemini-first writer call routing with Groq fallback.

Phase A2 deliverable. Migrated onto the shared backend/llm/model_provider.py
factory (Phase 0 foundation) — see route_writer_call().

Every writer LLM call goes through route_writer_call():
  1. Tries Gemini 3.1-flash-lite via the shared factory (Gemini-pool legs only,
     each retried with backoff, logged to llm_call_log).
  2. On 429 / RESOURCE_EXHAUSTED only (after the pool is exhausted): falls back
     to Groq via the shared factory, using the caller-supplied compressed prompt.
  3. Any other Gemini error: re-raised immediately, no fallback.

Public API
----------
route_writer_call(gemini_prompt, groq_prompt, call_type,
                   json_mode=True, metadata=None) -> (str, str)
format_articles_full(articles, tag, include_full_content=False)
                                                    -> (str, dict[str, dict])
"""

from __future__ import annotations

import logging
import time

from ..utils.text import truncate_at_sentence

logger = logging.getLogger(__name__)

_GEMINI_WRITER_MODEL = "models/gemini-3.1-flash-lite"

# Feed-4.2: per-source cap when attaching full_content (Gemini leg only).
# Headroom check: gemini-3.1-flash-lite is in the 1M-context flash family
# (sibling flash models registered at context_window=1_000_000 in
# model_registry.py); a real batch prompt today runs ~7.5-8.4K tokens, so
# 4 primaries x 12,000 chars (~3K tok each, ~12K tok total) is still <2% of
# window. Picked mid-upper of the 8-15K target range — budget isn't the
# binding constraint, no reason to be stingier.
_FULL_CONTENT_CHAR_BUDGET = 12_000


def _is_quota_error(exc: Exception) -> bool:
    msg = str(exc)
    return "429" in msg or "RESOURCE_EXHAUSTED" in msg


def format_articles_full(
    articles:             list[dict],
    tag:                  str,
    include_full_content: bool = False,
) -> tuple[str, dict[str, dict]]:
    """
    Format articles with ALL raw content and ALL source_intelligence fields — no truncation.
    Used exclusively for the Gemini full-prompt path.

    Fields included: title, url, source_type, main_claim, key_evidence,
    important_numbers, important_entities, important_dates, implications, risks,
    contradictions, signal_density, source_strength, content (full_content when
    include_full_content=True and present, else the existing capped snippet).

    include_full_content: when True, attaches full_content (capped at
    _FULL_CONTENT_CHAR_BUDGET, cut at a sentence boundary) and any
    full_content_images URLs for each article that has them. Falls back to the
    existing capped `content` field per-article when full_content is missing
    (e.g. a Feed-3 fetch failure) — the flag is a caller intent, not a guarantee
    every article gets the richer text.

    Returns (formatted_text, citable_sources) where citable_sources maps each
    emitted Source-ID to {"url": ..., "images": [...]} — used by
    source_grounding_service.ground_package() to validate image blocks and
    source_id attribution against what this batch actually offered the writer.
    """
    citable: dict[str, dict] = {}

    if not articles:
        return f"({tag}: no articles)", citable

    parts: list[str] = []
    for i, a in enumerate(articles, 1):
        src_id = f"{tag}-{i}"
        images = [img for img in (a.get("full_content_images") or []) if img]
        citable[src_id] = {"url": a.get("url", ""), "images": images}

        lines = [
            f"[{tag} {i}]",
            f"Source-ID: {src_id}",
            f"Title: {a.get('title', '')}",
            f"URL:   {a.get('url', '')}",
        ]
        if a.get("source_type"):
            lines.append(f"Source type: {a['source_type']}")
        if a.get("main_claim"):
            lines.append(f"Main claim: {a['main_claim']}")
        for ev in (a.get("key_evidence") or []):
            if ev and isinstance(ev, str):
                lines.append(f"Evidence: {ev}")
        for n in (a.get("important_numbers") or []):
            if n:
                lines.append(f"Number: {n}")
        for e in (a.get("important_entities") or []):
            if e and isinstance(e, str):
                lines.append(f"Entity: {e}")
        for d in (a.get("important_dates") or []):
            if d and isinstance(d, str):
                lines.append(f"Date: {d}")
        for impl in (a.get("implications") or []):
            if impl and isinstance(impl, str):
                lines.append(f"Implication: {impl}")
        for risk in (a.get("risks") or []):
            if risk and isinstance(risk, str):
                lines.append(f"Risk: {risk}")
        for c in (a.get("contradictions") or []):
            if c and isinstance(c, str):
                lines.append(f"Contradiction: {c}")
        if a.get("signal_density") is not None:
            lines.append(f"Signal density: {a['signal_density']}")
        if a.get("source_strength") is not None:
            lines.append(f"Source strength: {a['source_strength']}")

        full_content = (a.get("full_content") or "").strip()
        if include_full_content and full_content:
            content = truncate_at_sentence(full_content, _FULL_CONTENT_CHAR_BUDGET)
        else:
            content = (a.get("content") or "").strip()
        if content:
            lines.append(f"Content:\n{content}")

        if include_full_content and images:
            lines.append(f"Images available for {src_id} (use ONLY these exact URLs if referencing an image, never invent one):")
            for img_url in images[:5]:
                lines.append(f"  - {img_url}")

        parts.append("\n".join(lines))

    return "\n\n".join(parts), citable


def route_writer_call(
    gemini_prompt: str,
    groq_prompt:   str,
    call_type:     str,
    json_mode:     bool = True,
    metadata:      dict | None = None,
) -> tuple[str, str]:
    """
    Route a writer call: Gemini first (shared factory, Gemini legs only), Groq
    fallback on quota failure only (shared factory, Groq leg only).

    Parameters
    ----------
    gemini_prompt   Full uncompressed prompt to send to Gemini.
    groq_prompt     Pre-built, budget-compressed prompt to send to Groq —
                    used only when Gemini returns a 429 / RESOURCE_EXHAUSTED.
                    Gemini and Groq need different prompts because Groq's
                    token budget is far smaller, so the two legs can't share
                    one .with_fallbacks() input — each is invoked separately.
    call_type       Logged to llm_call_log (e.g. "feed_writer", "feed_synthesis").
    json_mode       When True, requests JSON-object response format.
    metadata        Extra llm_call_log fields (user_id/project_id/day_ref).

    Returns
    -------
    (response_text, provider)  where provider is "gemini" or "groq".

    Raises
    ------
    Any non-quota Gemini error is re-raised immediately without falling back.
    """
    from ..llm import get_chat_model, extract_text

    meta = {"call_type": call_type, **(metadata or {})}
    t_start = time.monotonic()

    try:
        model = get_chat_model(model=_GEMINI_WRITER_MODEL, legs="gemini", json_mode=json_mode)
        resp  = model.invoke(gemini_prompt, config={"metadata": meta})
        elapsed_ms = (time.monotonic() - t_start) * 1000
        logger.info(
            "[writer_router] provider=gemini  model=%s  elapsed_ms=%.0f",
            _GEMINI_WRITER_MODEL, elapsed_ms,
        )
        return extract_text(resp), "gemini"

    except Exception as exc:
        if not _is_quota_error(exc):
            logger.error(
                "[writer_router] Gemini non-quota error (model=%s) — raising without fallback: %s",
                _GEMINI_WRITER_MODEL, exc,
            )
            raise
        logger.warning(
            "[writer_router] Gemini quota/rate-limit — falling back to Groq: %s", exc,
        )

    # Same guard ask_grok used to run internally before every Groq call —
    # preserved here since Groq is reached directly via the shared factory now.
    from .grok_service import _preflight_check
    _preflight_check(f"route_writer_call:{call_type}:groq_fallback", prompt=groq_prompt)

    t_fallback = time.monotonic()
    model = get_chat_model(legs="groq", json_mode=json_mode)
    resp  = model.invoke(groq_prompt, config={"metadata": meta})
    logger.info(
        "[writer_router] provider=groq (quota fallback)  elapsed_ms=%.0f",
        (time.monotonic() - t_fallback) * 1000,
    )
    return extract_text(resp), "groq"
