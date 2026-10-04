"""
Text-to-Speech service — Deepgram for the Unpack "Read Aloud" action.

Uses Flux TTS (/v2/speak, Early Access). With no options it speaks with one
warm female English voice. The user can pick any Flux voice, a speed and an
expressivity in Settings; everything else is fixed here: MP3 at its best bit
rate, and every request opts out of Deepgram's Model Improvement Program so
users' text is never used for training.

Audio streams: Deepgram produces speech at roughly playback pace (a long
paragraph takes ~20s in full but its first bytes arrive in ~2.5s), so chunks
are relayed to the browser as they arrive and playback starts right away.

If Flux fails before sending audio (outage, timeout, a retired Early Access
voice), the same text is retried once on Aura-2 (/v1/speak) with a fixed
voice, so the user still hears something. Once audio is flowing there is no
switching; a mid-stream failure just ends the clip early. Fallback audio is
not cached, so Flux is used again as soon as it recovers. Only if both fail
does the error reach the user.

Public API
----------
open_speech_stream(text, user_id, options=None) -> (chunks, mime_type, source)
    Cache-checked first (independent of the "explain"/"translate" cache
    entries). Opens the Deepgram stream eagerly, so failures raise here,
    before any audio is sent; `chunks` then yields the audio. A complete
    Flux stream is cached once fully consumed.
list_voices() -> list[dict]
    Every Flux TTS voice Deepgram lists for this key.
"""

from __future__ import annotations

import base64
import logging
import os
import time
from datetime import datetime, timezone
from functools import lru_cache
from urllib.parse import urlencode
from uuid import uuid4

import requests

from .unpack_cache_service import build_unpack_key, get_cached_unpack, cache_unpack

logger = logging.getLogger(__name__)

_SPEAK_API_URL          = "https://api.deepgram.com/v2/speak"
_FALLBACK_SPEAK_API_URL = "https://api.deepgram.com/v1/speak"
_MODELS_API_URL         = "https://api.deepgram.com/v2/models"
_ACTION                 = "read_aloud"
# Per read (time to first byte, then any gap between chunks), not the whole
# clip. Flux + the Aura-2 fallback must both start inside the popover's 15s
# wait for the response (frontend/src/api/unpack.js).
_TIMEOUT_S              = 6.0

# Default: warm, calm female American English voice.
_VOICE_MODEL = "flux-sienna-en"
# Backup when Flux fails: Aura-2's warm female English voice. Aura-2 English
# takes a speed (0.7–1.5) but no expressivity.
_FALLBACK_MODEL       = "aura-2-thalia-en"
_FALLBACK_SPEED_RANGE = (0.7, 1.5)

# Sent on every request and never user-settable. MP3's sample rate is fixed
# by Deepgram (22.05 kHz); 48 kbps is the highest bit rate Flux allows for MP3.
_FIXED_PARAMS = {"encoding": "mp3", "bit_rate": 48000, "mip_opt_out": True}


def _get_deepgram_key() -> str:
    api_key = os.getenv("DEEPGRAM_TTS_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPGRAM_TTS_API_KEY environment variable is not set")
    return api_key


def _open_deepgram_stream(text: str, params: dict, url: str) -> requests.Response:
    """Start synthesizing `text` and return the open streaming response, once
    Deepgram has accepted the request. A 400 (unknown voice, bad option)
    becomes a ValueError carrying Deepgram's own explanation; other errors
    raise. The caller must close the response."""
    resp = requests.post(
        url,
        # requests would send True as "True"; Deepgram wants "true".
        params={k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()},
        headers={
            "Authorization": f"Token {_get_deepgram_key()}",
            "Content-Type": "application/json",
        },
        json={"text": text},
        timeout=_TIMEOUT_S,
        stream=True,
    )
    if resp.status_code == 200:
        return resp
    try:
        if resp.status_code == 400:
            try:
                msg = resp.json().get("err_msg")
            except ValueError:
                msg = None
            raise ValueError(msg or "Deepgram rejected these voice settings.")
        resp.raise_for_status()
        raise RuntimeError(f"Deepgram returned HTTP {resp.status_code}")
    finally:
        resp.close()


@lru_cache(maxsize=1)
def list_voices() -> list[dict]:
    """Every Flux TTS voice from Deepgram's model listing, trimmed to what the
    voice picker shows.

    ponytail: cached for the process lifetime; a restart picks up newly
    released voices."""
    headers = {"Authorization": f"Token {_get_deepgram_key()}"}
    resp = requests.get(_MODELS_API_URL, headers=headers, timeout=_TIMEOUT_S)
    resp.raise_for_status()
    voices = []
    for m in resp.json().get("tts", []):
        if m.get("architecture") != "flux-tts":
            continue
        meta = m.get("metadata") or {}
        voices.append({
            "model":     m["canonical_name"],
            "name":      meta.get("display_name") or m.get("name") or m["canonical_name"],
            "language":  (m.get("languages") or [""])[-1],
            "accent":    meta.get("accent"),
            "age":       meta.get("age"),
            "tags":      meta.get("tags") or [],
            "use_cases": meta.get("use_cases") or [],
            "sample":    meta.get("sample"),
        })
    return voices


def _audio_marker(audio_base64: str, mime_type: str = "audio/mpeg") -> str:
    """Design decision (Phase B1 / Admin-6): llm_call_log.output never holds the
    base64 audio blob — a short marker instead. Byte count is the real decoded
    size, not an estimate off the base64 string length."""
    return f"[{mime_type} audio, {len(base64.b64decode(audio_base64))} bytes]"


def _log_tts(input_text: str, t0: float, *, output: str | None, success: bool, user_id: str, model: str, error: Exception | None = None) -> None:
    """Non-LLM row (Phase B1 / Admin-6): provider='deepgram', no token
    fields — this is a direct speech-synthesis REST call, not an LLM
    completion. model_requested is the voice. Never raises.

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
        model_requested=model,
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


def open_speech_stream(text: str, user_id: str, options: dict | None = None):
    """
    Open a speech stream for `text` via Deepgram, with the user's voice
    settings. Returns (chunks, mime_type, source).

    `options` holds the user's choices (model, speed, expressivity), already
    type-checked by the route; the fixed format and opt-out always win over
    anything in it. A missing model falls back to the default voice. A Flux
    failure is retried once on Aura-2 (see module docstring). Raises
    ValueError for empty input or a 400 from both; raises RuntimeError/
    requests exceptions on other failures of both — the caller (the
    /unpack/read-aloud route) turns these into an HTTP error so the popover
    can show an inline message instead of a blank state.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("text must not be empty")

    t0 = time.monotonic()

    options = {k: v for k, v in (options or {}).items() if v is not None}
    model   = options.pop("model", None) or _VOICE_MODEL
    params  = {**options, "model": model, **_FIXED_PARAMS}
    # Default settings key on the bare model name.
    variant = model + (f"?{urlencode(sorted(options.items()))}" if options else "")

    key    = build_unpack_key(text, "", _ACTION, variant)
    cached = get_cached_unpack(key)
    if cached and cached.get("audio_base64"):
        mime = cached.get("mime_type", "audio/mpeg")
        _log_tts(text, t0, output=_audio_marker(cached["audio_base64"], mime), success=True, user_id=user_id, model=model)
        return iter([base64.b64decode(cached["audio_base64"])]), mime, "cache"

    try:
        resp = _open_deepgram_stream(text, params, _SPEAK_API_URL)
    except Exception as exc:
        _log_tts(text, t0, output=None, success=False, user_id=user_id, model=model, error=exc)
        logger.warning("[tts] Flux failed (%s), falling back to %s", exc, _FALLBACK_MODEL)
        return _open_fallback(text, user_id, options.get("speed"))

    cache = (key, variant, {"term": text, "language": model.rsplit("-", 1)[-1]})
    mime  = resp.headers.get("content-type", "audio/mpeg")
    return _relay(resp, text, user_id, model, t0, mime, cache), mime, "deepgram_tts"


def _open_fallback(text: str, user_id: str, speed: float | None):
    """Aura-2 backup for a failed Flux call. Keeps the user's pace where
    Aura-2 can (clamped to its range), drops expressivity. Not cached."""
    t0 = time.monotonic()
    params = {"model": _FALLBACK_MODEL, **_FIXED_PARAMS}
    if speed is not None:
        params = {"speed": min(_FALLBACK_SPEED_RANGE[1], max(_FALLBACK_SPEED_RANGE[0], speed)), **params}
    try:
        resp = _open_deepgram_stream(text, params, _FALLBACK_SPEAK_API_URL)
    except Exception as exc:
        _log_tts(text, t0, output=None, success=False, user_id=user_id, model=_FALLBACK_MODEL, error=exc)
        raise
    mime = resp.headers.get("content-type", "audio/mpeg")
    return _relay(resp, text, user_id, _FALLBACK_MODEL, t0, mime, None), mime, "deepgram_tts_fallback"


def _relay(resp, text: str, user_id: str, model: str, t0: float, mime: str, cache: tuple | None):
    """Yield Deepgram's audio chunks as they arrive. When the stream completes,
    log it and (for Flux) cache the whole clip. A listener who leaves early
    (GeneratorExit) or a mid-stream failure caches nothing: half a clip must
    never be replayed as the full one."""
    audio = bytearray()
    try:
        for chunk in resp.iter_content(chunk_size=None):
            audio += chunk
            yield chunk
    except Exception as exc:
        _log_tts(text, t0, output=None, success=False, user_id=user_id, model=model, error=exc)
        logger.warning("[tts] %s stream broke off after %d bytes: %s", model, len(audio), exc)
        return
    finally:
        resp.close()

    audio_base64 = base64.b64encode(bytes(audio)).decode("ascii")
    _log_tts(text, t0, output=_audio_marker(audio_base64, mime), success=True, user_id=user_id, model=model)
    if cache:
        key, variant, result = cache
        cache_unpack(key, text, variant, {**result, "audio_base64": audio_base64, "mime_type": mime})
