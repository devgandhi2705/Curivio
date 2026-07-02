"""
Translate service — Google Cloud Translation API (v2, Basic/NMT) for the
Unpack "Translate" action.

Only 4 target languages are supported: Hindi, Gujarati, French, German. The
source text sent is the selected term/phrase alone — no surrounding sentence
context, since the Translate API doesn't use it the way the LLM does.

Public API
----------
ALLOWED_LANGUAGES: dict[str, str]       code -> label
translate_term(term, target_language) -> dict
    {"term", "target_language", "translation", "source"}
    Cache-checked first (independent of the "explain" cache entries);
    calls Google Translate on a miss.
"""

from __future__ import annotations

import logging
import os

import requests

from .unpack_cache_service import build_unpack_key, get_cached_unpack, cache_unpack

logger = logging.getLogger(__name__)

_TRANSLATE_API_URL = "https://translation.googleapis.com/language/translate/v2"
_ACTION            = "translate"
_TIMEOUT_S         = 5.0

ALLOWED_LANGUAGES = {
    "hi": "Hindi",
    "gu": "Gujarati",
    "fr": "French",
    "de": "German",
}


def _call_google_translate(text: str, target_language: str) -> str:
    api_key = os.getenv("GOOGLE_TRANSLATE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_TRANSLATE_API_KEY environment variable is not set")

    resp = requests.post(
        _TRANSLATE_API_URL,
        params={"key": api_key},
        json={"q": text, "source": "en", "target": target_language, "format": "text"},
        timeout=_TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json()["data"]["translations"][0]["translatedText"]


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

    translation = _call_google_translate(term, target_language)
    result = {"term": term, "target_language": target_language, "translation": translation}
    cache_unpack(key, term, target_language, result)
    return {**result, "source": "google_translate"}
