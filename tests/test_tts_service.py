"""Read Aloud: the user picks a Flux voice, speed and expressivity; format and
the training opt-out are fixed server-side. Audio streams through as Deepgram
produces it; Flux failures fall back to Aura-2 before the first byte."""
from __future__ import annotations

import base64

import pytest

from backend.services import tts_service
from backend.services.unpack_cache_service import build_unpack_key

FIXED = {"encoding": "mp3", "bit_rate": 48000, "mip_opt_out": "true"}
FLUX_URL = "https://api.deepgram.com/v2/speak"
AURA_URL = "https://api.deepgram.com/v1/speak"


class _Resp:
    def __init__(self, status=200, chunks=(b"au", b"dio"), ctype="audio/mpeg", body=None):
        self.status_code = status
        self.chunks = list(chunks)
        self.headers = {"content-type": ctype}
        self._body = body or {}
        self.closed = False

    def json(self):
        return self._body

    def iter_content(self, chunk_size=None):
        yield from self.chunks

    def close(self):
        self.closed = True

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture
def calls(monkeypatch):
    seen = {"post": [], "cached": [], "resp": _Resp()}
    monkeypatch.setenv("DEEPGRAM_TTS_API_KEY", "k")
    monkeypatch.setattr(tts_service, "get_cached_unpack", lambda key: None)
    monkeypatch.setattr(tts_service, "cache_unpack", lambda key, term, variant, result: seen["cached"].append((key, result)))
    monkeypatch.setattr(tts_service, "_log_tts", lambda *a, **kw: None)

    def post(url, params, **kw):
        assert kw.get("stream") is True
        seen["post"].append((url, params))
        resp = seen["resp"].get(url, _Resp()) if isinstance(seen["resp"], dict) else seen["resp"]
        if isinstance(resp, Exception):
            raise resp
        return resp
    monkeypatch.setattr(tts_service.requests, "post", post)
    return seen


def _play(text="hello", options=None):
    chunks, mime, source = tts_service.open_speech_stream(text, "u1", options)
    return b"".join(chunks), mime, source


def test_default_voice_streams_chunks_then_caches_whole_audio(calls):
    chunks, mime, source = tts_service.open_speech_stream("hello", "u1")
    assert calls["post"] == [(FLUX_URL, {"model": "flux-sienna-en", **FIXED})]
    assert (mime, source) == ("audio/mpeg", "deepgram_tts")
    assert calls["cached"] == []          # nothing cached until the stream is done
    assert list(chunks) == [b"au", b"dio"]
    key, result = calls["cached"][0]
    assert key == build_unpack_key("hello", "", "read_aloud", "flux-sienna-en")
    assert base64.b64decode(result["audio_base64"]) == b"audio"
    assert calls["resp"].closed


def test_listener_leaving_early_caches_nothing(calls):
    chunks, _, _ = tts_service.open_speech_stream("hello", "u1")
    next(chunks)
    chunks.close()                        # client disconnected mid-stream
    assert calls["cached"] == []
    assert calls["resp"].closed


def test_cache_hit_streams_stored_audio_without_calling_deepgram(calls, monkeypatch):
    stored = {"audio_base64": base64.b64encode(b"old").decode(), "mime_type": "audio/mpeg"}
    monkeypatch.setattr(tts_service, "get_cached_unpack", lambda key: stored)
    assert _play() == (b"old", "audio/mpeg", "cache")
    assert calls["post"] == []


def test_choices_pass_through_but_never_override_fixed(calls):
    _play(options={"model": "flux-cole-en", "speed": 1.25, "expressivity": -1,
                   "encoding": "linear16", "mip_opt_out": False})
    assert calls["post"][0][1] == {"model": "flux-cole-en", "speed": 1.25, "expressivity": -1, **FIXED}


def test_option_order_does_not_change_cache_key(calls):
    _play("hi", {"model": "flux-cole-en", "speed": 1.1, "expressivity": 2})
    calls["resp"] = _Resp()
    _play("hi", {"expressivity": 2, "speed": 1.1, "model": "flux-cole-en"})
    assert calls["cached"][0][0] == calls["cached"][1][0]
    assert calls["cached"][0][0] != build_unpack_key("hi", "", "read_aloud", "flux-cole-en")


def test_400_from_both_becomes_value_error_with_deepgrams_message(calls):
    calls["resp"] = _Resp(status=400, ctype="application/json", body={"err_msg": "Unknown model."})
    with pytest.raises(ValueError, match="Unknown model"):
        tts_service.open_speech_stream("hi", "u1", {"model": "flux-nobody-en"})
    assert calls["cached"] == []


def test_flux_failure_falls_back_to_aura_2_and_is_not_cached(calls):
    calls["resp"] = {FLUX_URL: tts_service.requests.Timeout("slow"), AURA_URL: _Resp(chunks=[b"aura"])}
    audio, _, source = _play("hi", {"model": "flux-cole-en", "speed": 0.5, "expressivity": 2})
    assert [u for u, _ in calls["post"]] == [FLUX_URL, AURA_URL]
    # Aura-2 keeps the user's pace (clamped to its 0.7 floor) but has no expressivity.
    assert calls["post"][1][1] == {"model": "aura-2-thalia-en", "speed": 0.7, **FIXED}
    assert (audio, source) == (b"aura", "deepgram_tts_fallback")
    assert calls["cached"] == []          # Flux is tried again once it recovers


def test_flux_400_also_falls_back(calls):
    calls["resp"] = {FLUX_URL: _Resp(status=400, ctype="application/json", body={"err_msg": "Unknown model."})}
    _, _, source = _play("hi", {"model": "flux-retired-en"})
    assert calls["post"][1] == (AURA_URL, {"model": "aura-2-thalia-en", **FIXED})
    assert source == "deepgram_tts_fallback"


def test_both_failing_raises(calls):
    calls["resp"] = {FLUX_URL: _Resp(status=503), AURA_URL: _Resp(status=503)}
    with pytest.raises(RuntimeError):
        tts_service.open_speech_stream("hi", "u1")
    assert len(calls["post"]) == 2


def test_empty_text_is_rejected(calls):
    with pytest.raises(ValueError):
        tts_service.open_speech_stream("   ", "u1")


def test_list_voices_is_flux_only(monkeypatch):
    monkeypatch.setenv("DEEPGRAM_TTS_API_KEY", "k")
    tts_service.list_voices.cache_clear()
    meta = {"accent": "American", "display_name": "Sienna", "sample": "s.wav",
            "tags": ["feminine", "clear"], "use_cases": ["IVR"], "age": "Adult"}
    body = {"tts": [
        {"canonical_name": "flux-sienna-en", "architecture": "flux-tts", "languages": ["en", "en-US"], "metadata": meta},
        {"canonical_name": "flux-general-en", "architecture": "flux", "languages": ["en", "en-US"], "metadata": meta},
    ]}
    seen = []
    monkeypatch.setattr(tts_service.requests, "get", lambda url, **kw: seen.append(url) or _Resp(body=body))
    voices = tts_service.list_voices()
    tts_service.list_voices.cache_clear()
    assert seen == ["https://api.deepgram.com/v2/models"]
    assert voices == [{"model": "flux-sienna-en", "name": "Sienna", "language": "en-US",
                       "accent": "American", "age": "Adult", "tags": ["feminine", "clear"],
                       "use_cases": ["IVR"], "sample": "s.wav"}]
