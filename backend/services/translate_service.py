"""
Translate service — DeepL API for the Unpack "Translate" action.

Only 4 target languages are supported: Hindi, Gujarati, French, German. The
source text sent is the selected term/phrase alone — no surrounding sentence
context, since the Translate API doesn't use it the way the LLM does.

Public API
----------
ALLOWED_LANGUAGES: dict[str, str]       code -> label
translate_term(term, target_language) -> dict
    {"term", "target_language", "translation", "source"}
    Cache-checked first (independent of the "explain" cache entries);
    calls DeepL on a miss.
"""

from __future__ import annotations

import logging
import os

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


def translate_term(term: str, target_language: str) -> dict:
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

    key    = build_unpack_key(term, "", _ACTION, target_language)
    cached = get_cached_unpack(key)
    if cached:
        return {**cached, "source": "cache"}

    translation = _call_deepl(term, target_language)
    result = {"term": term, "target_language": target_language, "translation": translation}
    cache_unpack(key, term, target_language, result)
    return {**result, "source": "deepl"}
