"""
writer_provider_router — Gemini-first writer call routing with Groq fallback.

Phase A2 deliverable.

Every writer LLM call goes through route_writer_call():
  1. Tries Gemini 3.1-flash-lite (GEMINI_WRITER_API_KEY — separate from journey planner).
  2. On 429 / RESOURCE_EXHAUSTED only: falls back to caller-supplied groq_fallback().
  3. Any other Gemini error: re-raised immediately, no fallback.

Groq path is unchanged — groq_fallback() runs the exact existing pipeline.

Public API
----------
route_writer_call(gemini_prompt, groq_fallback, json_mode=True) -> (str, str)
format_articles_full(articles, tag)                             -> str
"""

from __future__ import annotations

import logging
import os
import time
from typing import Callable

logger = logging.getLogger(__name__)

_GEMINI_WRITER_MODEL = "models/gemini-3.1-flash-lite"
_GEMINI_API_URL      = "https://generativelanguage.googleapis.com/v1beta/openai/"

_gemini_writer_client = None


def _get_gemini_writer_client():
    global _gemini_writer_client
    if _gemini_writer_client is None:
        from openai import OpenAI
        api_key = os.getenv("GEMINI_WRITER_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_WRITER_API_KEY environment variable is not set")
        _gemini_writer_client = OpenAI(api_key=api_key, base_url=_GEMINI_API_URL, timeout=180.0)
    return _gemini_writer_client


def _is_quota_error(exc: Exception) -> bool:
    msg = str(exc)
    return "429" in msg or "RESOURCE_EXHAUSTED" in msg


def format_articles_full(articles: list[dict], tag: str) -> str:
    """
    Format articles with ALL raw content and ALL source_intelligence fields — no truncation.
    Used exclusively for the Gemini full-prompt path.

    Fields included: title, url, source_type, main_claim, key_evidence,
    important_numbers, important_entities, important_dates, implications, risks,
    contradictions, signal_density, source_strength, full content.
    """
    if not articles:
        return f"({tag}: no articles)"

    parts: list[str] = []
    for i, a in enumerate(articles, 1):
        src_id = f"{tag}-{i}"
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
        content = (a.get("content") or "").strip()
        if content:
            lines.append(f"Content:\n{content}")
        parts.append("\n".join(lines))

    return "\n\n".join(parts)


def route_writer_call(
    gemini_prompt: str,
    groq_fallback: Callable[[], str],
    json_mode: bool = True,
) -> tuple[str, str]:
    """
    Route a writer call: Gemini first, Groq fallback on quota failure only.

    Parameters
    ----------
    gemini_prompt   Full uncompressed prompt to send to Gemini.
    groq_fallback   Callable that builds and sends the Groq-compressed prompt.
                    Called only when Gemini returns a 429 / RESOURCE_EXHAUSTED.
    json_mode       When True, requests JSON-object response format from Gemini.

    Returns
    -------
    (response_text, provider)  where provider is "gemini" or "groq".

    Raises
    ------
    Any non-quota Gemini error is re-raised immediately without calling groq_fallback.
    """
    _tok_est = len(gemini_prompt) // 4
    t_start  = time.monotonic()

    try:
        client = _get_gemini_writer_client()
        kwargs: dict = dict(
            model    = _GEMINI_WRITER_MODEL,
            messages = [{"role": "user", "content": gemini_prompt}],
        )
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        resp  = client.chat.completions.create(**kwargs)
        text  = resp.choices[0].message.content
        elapsed_ms = (time.monotonic() - t_start) * 1000

        usage      = getattr(resp, "usage", None)
        actual_in  = getattr(usage, "prompt_tokens",     None) if usage else None
        actual_out = getattr(usage, "completion_tokens", None) if usage else None

        logger.info(
            "[writer_router] provider=gemini  model=%s  "
            "prompt_tokens=%s (local_est=%d)  completion_tokens=%s  elapsed_ms=%.0f",
            _GEMINI_WRITER_MODEL,
            actual_in  if actual_in  is not None else "?",
            _tok_est,
            actual_out if actual_out is not None else "?",
            elapsed_ms,
        )
        return text, "gemini"

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

    # Groq fallback — runs the exact existing pipeline unchanged
    t_fallback = time.monotonic()
    text = groq_fallback()
    logger.info(
        "[writer_router] provider=groq (quota fallback)  elapsed_ms=%.0f",
        (time.monotonic() - t_fallback) * 1000,
    )
    return text, "groq"
