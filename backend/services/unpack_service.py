"""
Unpack "Explain" service — select-to-explain popover backend.

Pipeline: cache check -> LLM (Groq primary, Gemini fallback) with streaming +
one retry on JSON-parse failure -> dictionary-only degrade if the LLM path
fails entirely. Words, phrases, and sentences all go through the same LLM
path with full surrounding context — no separate word-only fast path.

Translation is a separate action/path (translate_service.py, Google Cloud
Translation API) — not part of this module.

Public API
----------
explain_stream(term, sentence, prev_sentence, next_sentence) -> generator[str]
    Yields NDJSON lines:
      {"t":"chunk","v":"<text>"}                        — incremental meaning_in_context text
      {"t":"done", term, definition_general,
       meaning_in_context, confidence,
       source, provider}                                 — final result
      {"t":"error","message":"<reason>"}                  — unrecoverable error
"""

from __future__ import annotations

import json
import logging
import os
import re

from ..config import GROQ_BASE_URL, GROQ_UNPACK_MODEL, GEMINI_UNPACK_MODEL
from .unpack_cache_service import build_unpack_key, get_cached_unpack, cache_unpack
from .dictionary_service import is_dictionary_fast_path_eligible, dictionary_lookup
from ..prompts.unpack_prompt import build_unpack_messages

logger = logging.getLogger(__name__)

_GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
_LLM_TIMEOUT_S  = 5.0
_ACTION         = "explain"

_groq_client   = None
_gemini_client = None


def _get_groq_client():
    global _groq_client
    if _groq_client is None:
        from openai import OpenAI
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY environment variable is not set")
        # max_retries=0: the fallback chain below already retries/switches providers —
        # the SDK's own retries would silently triple each call's wall-clock time
        # against the ~5s budget this feature needs to feel instant.
        _groq_client = OpenAI(api_key=api_key, base_url=GROQ_BASE_URL, timeout=_LLM_TIMEOUT_S, max_retries=0)
    return _groq_client


def _get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        from openai import OpenAI
        # Accept GEMINI_API_KEY or first key of the GEMINI_API_KEYS pool —
        # same secret name works for chat, embeddings, and unpack.
        raw = os.getenv("GEMINI_API_KEYS", "") or os.getenv("GEMINI_API_KEY", "")
        api_key = next((k.strip() for k in raw.split(",") if k.strip()), None)
        if not api_key:
            raise RuntimeError("GEMINI_API_KEYS or GEMINI_API_KEY environment variable is not set")
        _gemini_client = OpenAI(api_key=api_key, base_url=_GEMINI_API_URL, timeout=_LLM_TIMEOUT_S, max_retries=0)
    return _gemini_client


def _is_quota_error(exc: Exception) -> bool:
    msg = str(exc)
    return "429" in msg or "RESOURCE_EXHAUSTED" in msg or "rate_limit" in msg.lower()


_REQUIRED_KEYS    = ("term", "definition_general", "meaning_in_context", "confidence")
_VALID_CONFIDENCE = {"high", "medium", "low"}


def _parse_response(raw: str | None) -> dict | None:
    """Validate + defensively parse the model's JSON output. None on any failure."""
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or not all(k in data for k in _REQUIRED_KEYS):
        return None
    if data.get("confidence") not in _VALID_CONFIDENCE:
        data["confidence"] = "medium"
    return data


_MEANING_KEY = '"meaning_in_context"'


def _extract_partial_meaning(buffer: str) -> str | None:
    """
    Best-effort incremental extraction of meaning_in_context's string value
    while the JSON is still streaming in (the closing quote may not have
    arrived yet) — lets the popover reveal the explanation progressively
    without a full streaming-JSON parser.
    """
    idx = buffer.find(_MEANING_KEY)
    if idx == -1:
        return None
    rest = buffer[idx + len(_MEANING_KEY):]
    colon = rest.find(":")
    if colon == -1:
        return None
    rest = rest[colon + 1:].lstrip()
    if not rest.startswith('"'):
        return None
    rest = rest[1:]

    end = -1
    i = 0
    while i < len(rest):
        if rest[i] == "\\":
            i += 2
            continue
        if rest[i] == '"':
            end = i
            break
        i += 1

    text = rest[:end] if end != -1 else rest
    return text.replace('\\"', '"').replace("\\n", "\n")


def _stream_groq(messages: list[dict]):
    """Yield raw text chunks from Groq. Raises on error/quota."""
    stream = _get_groq_client().chat.completions.create(
        model=GROQ_UNPACK_MODEL,
        messages=messages,
        temperature=0.3,
        max_tokens=200,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta and delta.content:
            yield delta.content


def _call_groq_once(messages: list[dict]) -> str:
    resp = _get_groq_client().chat.completions.create(
        model=GROQ_UNPACK_MODEL, messages=messages, temperature=0.3, max_tokens=200,
    )
    return resp.choices[0].message.content


def _call_gemini(messages: list[dict]) -> str:
    resp = _get_gemini_client().chat.completions.create(
        model=GEMINI_UNPACK_MODEL,
        messages=messages,
        temperature=0.3,
        max_tokens=200,
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content


def _line(t: str, **fields) -> str:
    return json.dumps({"t": t, **fields}) + "\n"


def _done_line(result: dict, source: str, provider: str | None = None) -> str:
    return _line(
        "done",
        term=result.get("term", ""),
        definition_general=result.get("definition_general", ""),
        meaning_in_context=result.get("meaning_in_context"),
        confidence=result.get("confidence", "low"),
        source=source,
        provider=provider,
    )


def explain_stream(
    term: str,
    sentence: str = "",
    prev_sentence: str = "",
    next_sentence: str = "",
):
    term     = (term or "").strip()
    sentence = (sentence or "").strip()

    if not term:
        yield _line("error", message="term must not be empty")
        return

    key    = build_unpack_key(term, sentence, _ACTION, None)
    cached = get_cached_unpack(key)
    if cached:
        yield _done_line(cached, source="cache")
        return

    # ── LLM path: Groq (streaming) -> Gemini (fallback) ────────────────────
    # Every selection — single word, phrase, or sentence — goes through the LLM
    # with full surrounding context; no word-only dictionary fast path.
    messages = build_unpack_messages(term, sentence, prev_sentence, next_sentence)

    result: dict | None       = None
    provider_used: str | None = None

    try:
        buffer   = ""
        sent_len = 0
        for text_chunk in _stream_groq(messages):
            buffer += text_chunk
            partial = _extract_partial_meaning(buffer)
            if partial and len(partial) > sent_len:
                yield _line("chunk", v=partial[sent_len:])
                sent_len = len(partial)

        parsed = _parse_response(buffer)
        if parsed is None:
            # One retry with a stricter reminder, same provider, no streaming.
            strict_messages = build_unpack_messages(
                term, sentence, prev_sentence, next_sentence, strict=True
            )
            parsed = _parse_response(_call_groq_once(strict_messages))
        if parsed:
            result, provider_used = parsed, "groq"
    except Exception as exc:
        if _is_quota_error(exc):
            logger.warning("[unpack] Groq quota/rate-limit — falling back to Gemini: %s", exc)
        else:
            logger.warning("[unpack] Groq call failed — falling back to Gemini: %s", exc)

    if result is None:
        try:
            parsed = _parse_response(_call_gemini(messages))
            if parsed is None:
                strict_messages = build_unpack_messages(
                    term, sentence, prev_sentence, next_sentence, strict=True
                )
                parsed = _parse_response(_call_gemini(strict_messages))
            if parsed:
                result, provider_used = parsed, "gemini"
        except Exception as exc:
            logger.warning("[unpack] Gemini call failed: %s", exc)

    if result:
        cache_unpack(key, term, None, result)
        yield _done_line(result, source="llm", provider=provider_used)
        return

    # ── Total LLM failure: degrade to dictionary-only, never a blank error ──
    fallback = dictionary_lookup(term) if is_dictionary_fast_path_eligible(term) else None
    if fallback:
        yield _done_line(fallback, source="dictionary_fallback")
    else:
        yield _done_line(
            {"term": term, "definition_general": "", "meaning_in_context": None, "confidence": "low"},
            source="unavailable",
        )
