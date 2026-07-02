"""
Text-to-Speech service — Google Cloud TTS for the Unpack "Read Aloud" action.

Detects the language of the selected text (Google Cloud Translation API's
detect endpoint) then synthesizes speech in that language using a warm,
higher-quality-tier female voice. Falls back to English (en-IN) for any
detected language outside the small set of locales/voices below.

Public API
----------
synthesize_speech(text) -> dict
    {"term", "language", "audio_base64", "source"}
    Cache-checked first (independent of the "explain"/"translate" cache
    entries); calls Google Cloud TTS on a miss.
"""

from __future__ import annotations

import logging
import os

import requests

from .unpack_cache_service import build_unpack_key, get_cached_unpack, cache_unpack

logger = logging.getLogger(__name__)

_DETECT_API_URL      = "https://translation.googleapis.com/language/translate/v2/detect"
_SYNTHESIZE_API_URL  = "https://texttospeech.googleapis.com/v1/text:synthesize"
_ACTION              = "read_aloud"
_TIMEOUT_S           = 8.0

# Warm, light, natural delivery — moderate positive pitch, unhurried pace.
_PITCH         = 3.0
_SPEAKING_RATE = 0.95

# One female voice per supported language, from the highest quality tier that
# actually supports pitch/rate tuning. Chirp3-HD (Google's newest/highest
# tier, available for all 5 languages below) rejects any request with a
# non-zero pitch outright (HTTP 400), so it's unusable here — verified live
# against text:synthesize. Neural2 is the next tier down and does support
# pitch/rate; used wherever a female Neural2 voice exists for the language.
_VOICES = {
    "en": ("en-IN", "en-IN-Neural2-A"),   # English -> English (India), per spec
    "hi": ("hi-IN", "hi-IN-Neural2-A"),
    "fr": ("fr-FR", "fr-FR-Neural2-F"),
    "de": ("de-DE", "de-DE-Neural2-G"),
    # Gujarati has no Neural2 tier — Wavenet is the best available female
    # voice that still supports pitch/rate tuning.
    "gu": ("gu-IN", "gu-IN-Wavenet-A"),
}
_DEFAULT_LANG = "en"


def _get_translate_key() -> str:
    api_key = os.getenv("GOOGLE_TRANSLATE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_TRANSLATE_API_KEY environment variable is not set")
    return api_key


def _get_tts_key() -> str:
    api_key = os.getenv("GOOGLE_TTS_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_TTS_API_KEY environment variable is not set")
    return api_key


def _detect_language(text: str) -> str:
    """Return a language code from _VOICES, defaulting to English on any miss/failure."""
    try:
        resp = requests.post(
            _DETECT_API_URL,
            params={"key": _get_translate_key()},
            json={"q": text},
            timeout=_TIMEOUT_S,
        )
        resp.raise_for_status()
        lang = resp.json()["data"]["detections"][0][0]["language"]
        return lang if lang in _VOICES else _DEFAULT_LANG
    except Exception as exc:
        logger.warning("[tts] language detection failed, defaulting to English: %s", exc)
        return _DEFAULT_LANG


def _call_google_tts(text: str, language_code: str, voice_name: str) -> str:
    resp = requests.post(
        _SYNTHESIZE_API_URL,
        params={"key": _get_tts_key()},
        json={
            "input": {"text": text},
            "voice": {"languageCode": language_code, "name": voice_name, "ssmlGender": "FEMALE"},
            "audioConfig": {
                "audioEncoding": "MP3",
                "pitch": _PITCH,
                "speakingRate": _SPEAKING_RATE,
            },
        },
        timeout=_TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json()["audioContent"]  # base64-encoded MP3


def synthesize_speech(text: str) -> dict:
    """
    Detect the language of `text` and synthesize speech for it.

    Raises ValueError for empty input; raises RuntimeError/requests
    exceptions on API failure — the caller (the /unpack/read-aloud route)
    turns these into an HTTP error so the popover can show an inline
    message instead of a blank state.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("text must not be empty")

    lang = _detect_language(text)
    language_code, voice_name = _VOICES[lang]

    key    = build_unpack_key(text, "", _ACTION, f"{language_code}:{voice_name}")
    cached = get_cached_unpack(key)
    if cached:
        return {**cached, "source": "cache"}

    audio_base64 = _call_google_tts(text, language_code, voice_name)
    result = {"term": text, "language": language_code, "audio_base64": audio_base64}
    cache_unpack(key, text, f"{language_code}:{voice_name}", result)
    return {**result, "source": "google_tts"}
