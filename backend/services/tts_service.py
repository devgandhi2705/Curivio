"""
Text-to-Speech service — Deepgram Aura for the Unpack "Read Aloud" action.

English only: read-aloud always synthesizes with a single warm female
English voice (Deepgram Aura is not used for the other Unpack languages).
Output is requested as MP3 so the base64 the frontend plays back
(`data:audio/mp3;base64,...`) stays valid without any client change.

Public API
----------
synthesize_speech(text) -> dict
    {"term", "language", "audio_base64", "source"}
    Cache-checked first (independent of the "explain"/"translate" cache
    entries); calls Deepgram on a miss.
"""

from __future__ import annotations

import base64
import logging
import os

import requests

from .unpack_cache_service import build_unpack_key, get_cached_unpack, cache_unpack

logger = logging.getLogger(__name__)

_SPEAK_API_URL = "https://api.deepgram.com/v1/speak"
_ACTION        = "read_aloud"
_TIMEOUT_S     = 8.0

# Warm, natural female English voice (Deepgram's newest Aura-2 tier). MP3 so
# the existing `data:audio/mp3` player keeps working unchanged.
_VOICE_MODEL = "aura-2-thalia-en"
_ENCODING    = "mp3"
_LANGUAGE    = "en"


def _get_deepgram_key() -> str:
    api_key = os.getenv("DEEPGRAM_TTS_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPGRAM_TTS_API_KEY environment variable is not set")
    return api_key


def _call_deepgram_tts(text: str) -> str:
    """Synthesize `text` and return base64-encoded MP3 (Deepgram returns raw bytes)."""
    resp = requests.post(
        _SPEAK_API_URL,
        params={"model": _VOICE_MODEL, "encoding": _ENCODING},
        headers={
            "Authorization": f"Token {_get_deepgram_key()}",
            "Content-Type": "application/json",
        },
        json={"text": text},
        timeout=_TIMEOUT_S,
    )
    resp.raise_for_status()
    return base64.b64encode(resp.content).decode("ascii")


def synthesize_speech(text: str) -> dict:
    """
    Synthesize English speech for `text` via Deepgram Aura.

    Raises ValueError for empty input; raises RuntimeError/requests
    exceptions on API failure — the caller (the /unpack/read-aloud route)
    turns these into an HTTP error so the popover can show an inline
    message instead of a blank state.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("text must not be empty")

    key    = build_unpack_key(text, "", _ACTION, _VOICE_MODEL)
    cached = get_cached_unpack(key)
    if cached:
        return {**cached, "source": "cache"}

    audio_base64 = _call_deepgram_tts(text)
    result = {"term": text, "language": _LANGUAGE, "audio_base64": audio_base64}
    cache_unpack(key, text, _VOICE_MODEL, result)
    return {**result, "source": "deepgram_tts"}
