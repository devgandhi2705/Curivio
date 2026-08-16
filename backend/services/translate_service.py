"""
Translate service — DeepL API for the Unpack "Translate" action.

Only 4 target languages are supported: Hindi, Gujarati, French, German. The
source text sent is the selected term/phrase alone — no surrounding sentence
context, since the Translate API doesn't use it the way the LLM does.

Public API
----------
ALLOWED_LANGUAGES: dict[str, str]       code -> label
translate_term(term, target_language, user_id) -> dict
    {"term", "target_language", "translation", "source"}
    Cache-checked first (independent of the "explain" cache entries);
    calls DeepL on a miss.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from uuid import uuid4

import requests

from .unpack_cache_service import build_unpack_key, get_cached_unpack, cache_unpack

logger = logging.getLogger(__name__)

_ACTION    = "translate"
_TIMEOUT_S = 5.0

ALLOWED_LANGUAGES = {
    "hi": "Hindi",
    "gu": "Gujarati",
    "fr": "French",
    "de": "German",
}


def _deepl_endpoint(api_key: str) -> str:
    # DeepL Free keys carry a ":fx" suffix and must hit api-free; Pro keys hit api.
    host = "api-free.deepl.com" if api_key.endswith(":fx") else "api.deepl.com"
    return f"https://{host}/v2/translate"


def _call_deepl(text: str, target_language: str) -> str:
    api_key = os.getenv("DEEPL_TRANSLATE_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPL_TRANSLATE_API_KEY environment variable is not set")

    resp = requests.post(
        _deepl_endpoint(api_key),
        headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
        json={
            "text": [text],
            "source_lang": "EN",
            "target_lang": target_language.upper(),  # DeepL expects uppercase codes
        },
        timeout=_TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json()["translations"][0]["text"]


def _log_translate(
    input_text: str, t0: float, *, output: str | None, success: bool,
    target_language: str, user_id: str, error: Exception | None = None,
) -> None:
    """Non-LLM row (Phase B1 / Admin-6): provider='deepl', no model/token
    fields — this is a REST translation call, not a completion. Never raises.

    Phase B2: target_language is also written to its own column (not just
    embedded in input_text) so the admin filter API can query it directly.

    Phase N-fix: user_id threaded from the route's authenticated caller —
    previously never passed here at all (N-recon), so every translate row
    was unattributable regardless of admin_service.py's user resolution,
    which already handled a populated user_id correctly."""
    from ..llm.call_logger import write_call_row
    now = datetime.now(timezone.utc).isoformat()
    write_call_row(
        run_id=uuid4().hex,
        parent_run_id=None,
        timestamp_start=now,
        timestamp_end=now,
        latency_ms=int((time.monotonic() - t0) * 1000),
        provider="deepl",
        call_type="translate",
        user_id=user_id,
        input_text=input_text,
        output=output,
        success=success,
        error_type=type(error).__name__ if error else None,
        error_message=str(error) if error else None,
        trace_id=uuid4().hex,
        agent_name="translate",
        surface="translate",
        target_language=target_language,
    )


def translate_term(term: str, target_language: str, user_id: str) -> dict:
    """
    Translate a selected term/phrase.

    Raises ValueError for empty input or an unsupported target language;
    raises RuntimeError/requests exceptions on API failure — the caller
    (the /unpack/translate route) turns these into an HTTP error so the
    popover can show an inline message instead of a blank state.
    """
    term = (term or "").strip()
    if not term:
        raise ValueError("term must not be empty")
    if target_language not in ALLOWED_LANGUAGES:
        raise ValueError(f"Unsupported target language: {target_language!r}")

    t0         = time.monotonic()
    input_text = f"term={term!r} target_language={target_language!r}"

    key    = build_unpack_key(term, "", _ACTION, target_language)
    cached = get_cached_unpack(key)
    if cached:
        _log_translate(input_text, t0, output=cached.get("translation"), success=True, target_language=target_language, user_id=user_id)
        return {**cached, "source": "cache"}

    try:
        translation = _call_deepl(term, target_language)
    except Exception as exc:
        _log_translate(input_text, t0, output=None, success=False, target_language=target_language, user_id=user_id, error=exc)
        raise
    _log_translate(input_text, t0, output=translation, success=True, target_language=target_language, user_id=user_id)

    result = {"term": term, "target_language": target_language, "translation": translation}
    cache_unpack(key, term, target_language, result)
    return {**result, "source": "deepl"}
