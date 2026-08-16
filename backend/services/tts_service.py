"""
Text-to-Speech service — Deepgram Aura for the Unpack "Read Aloud" action.

English only: read-aloud always synthesizes with a single warm female
English voice (Deepgram Aura is not used for the other Unpack languages).
Output is requested as MP3 so the base64 the frontend plays back
(`data:audio/mp3;base64,...`) stays valid without any client change.

Public API
----------
synthesize_speech(text, user_id) -> dict
    {"term", "language", "audio_base64", "source"}
    Cache-checked first (independent of the "explain"/"translate" cache
    entries); calls Deepgram on a miss.
"""

from __future__ import annotations

import base64
import logging
import os
import time
from datetime import datetime, timezone
from uuid import uuid4

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


def _audio_marker(audio_base64: str) -> str:
    """Design decision (Phase B1 / Admin-6): llm_call_log.output never holds the
    base64 MP3 blob — a short marker instead. Byte count is the real decoded
    size, not an estimate off the base64 string length."""
    return f"[MP3 audio, {len(base64.b64decode(audio_base64))} bytes]"


def _log_tts(input_text: str, t0: float, *, output: str | None, success: bool, user_id: str, error: Exception | None = None) -> None:
    """Non-LLM row (Phase B1 / Admin-6): provider='deepgram', no model/token
    fields — this is a direct speech-synthesis REST call, not an LLM
    completion. Never raises.

    Phase N-fix: user_id threaded from the route's authenticated caller —
    previously never passed here at all (N-recon)."""
    from ..llm.call_logger import write_call_row
    now = datetime.now(timezone.utc).isoformat()
    write_call_row(
        run_id=uuid4().hex,
        parent_run_id=None,
        timestamp_start=now,
        timestamp_end=now,
        latency_ms=int((time.monotonic() - t0) * 1000),
        provider="deepgram",
        call_type="tts",
        user_id=user_id,
        input_text=input_text,
        output=output,
        success=success,
        error_type=type(error).__name__ if error else None,
        error_message=str(error) if error else None,
        trace_id=uuid4().hex,
        agent_name="read_aloud",
        surface="tts",
    )


def synthesize_speech(text: str, user_id: str) -> dict:
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

    t0 = time.monotonic()

    key    = build_unpack_key(text, "", _ACTION, _VOICE_MODEL)
    cached = get_cached_unpack(key)
    if cached:
        marker = _audio_marker(cached["audio_base64"]) if cached.get("audio_base64") else None
        _log_tts(text, t0, output=marker, success=True, user_id=user_id)
        return {**cached, "source": "cache"}

    try:
        audio_base64 = _call_deepgram_tts(text)
    except Exception as exc:
        _log_tts(text, t0, output=None, success=False, user_id=user_id, error=exc)
        raise
    _log_tts(text, t0, output=_audio_marker(audio_base64), success=True, user_id=user_id)

    result = {"term": text, "language": _LANGUAGE, "audio_base64": audio_base64}
    cache_unpack(key, text, _VOICE_MODEL, result)
    return {**result, "source": "deepgram_tts"}
