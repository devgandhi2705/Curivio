"""The explain popover on the shared provider layer: same NDJSON contract, same
5s budget, but the [explain] model list, the shared skip policy and a route on
every row instead of two hand-rolled OpenAI clients."""
from __future__ import annotations

import json

import pytest

from backend.llm import model_provider as mp
from backend.llm import rate_limits
from backend.services import unpack_service

VALID = json.dumps({"term": "latency", "definition_general": "delay before a transfer begins",
                    "meaning_in_context": "the wait before the first token arrives",
                    "confidence": "high"})


class _Chunk:
    def __init__(self, content):
        self.content = content


class _FakeModel:
    def __init__(self, script):
        self._script = script
        self.configs = []

    def bind(self, **kwargs):
        return self

    def stream(self, messages, config=None):
        self.configs.append(config)
        for item in self._script:
            if isinstance(item, Exception):
                raise item
            yield _Chunk(item)

    def invoke(self, messages, config=None):
        self.configs.append(config)
        item = self._script[-1]
        if isinstance(item, Exception):
            raise item
        return _Chunk(item)


@pytest.fixture(autouse=True)
def _no_cache_no_skips(monkeypatch):
    rate_limits.clear()
    monkeypatch.setattr(mp, "_keys_for_provider", lambda provider: ["k"])
    monkeypatch.setattr(unpack_service, "get_cached_unpack", lambda key: None)
    monkeypatch.setattr(unpack_service, "cache_unpack", lambda *a, **kw: None)
    monkeypatch.setattr(unpack_service, "_log_explain", lambda *a, **kw: None)
    yield
    rate_limits.clear()


def _events(term="latency", **kwargs):
    return [json.loads(line) for line in unpack_service.explain_stream(term, "user-1", **kwargs)]


def _legs(monkeypatch, scripts):
    built = []
    def _build(spec, **kw):
        model = _FakeModel(scripts[spec.step - 1])
        built.append((spec, model))
        return model
    monkeypatch.setattr(mp, "build_leg", _build)
    return built


class TestExplainStream:
    def test_streams_the_meaning_then_a_done_event(self, monkeypatch):
        _legs(monkeypatch, [[VALID[:60], VALID[60:]]])
        events = _events()
        assert events[-1]["t"] == "done"
        assert events[-1]["meaning_in_context"] == "the wait before the first token arrives"
        assert events[-1]["provider"] == "groq"
        assert any(e["t"] == "chunk" for e in events)

    def test_route_is_logged_on_the_call(self, monkeypatch):
        built = _legs(monkeypatch, [[VALID]])
        _events()
        meta = built[0][1].configs[0]["metadata"]
        assert meta["route"].startswith("explain") and meta["route_step"] == 1
        assert meta["call_type"] == "explain" and meta["surface"] == "explain"

    def test_unparseable_answer_retries_strictly_then_moves_on(self, monkeypatch):
        built = _legs(monkeypatch, [["not json at all", "still not json"], [VALID]])
        events = _events()
        assert events[-1]["t"] == "done" and events[-1]["provider"] == "gemini"
        assert len(built) == 2

    def test_a_rate_limited_leg_falls_through(self, monkeypatch):
        import groq, httpx
        limited = groq.RateLimitError(
            "Error code: 429 - tokens per minute (TPM): Limit 8000",
            response=httpx.Response(429, request=httpx.Request("POST", "https://api.groq.com/x")),
            body=None)
        _legs(monkeypatch, [[limited], [VALID]])
        events = _events()
        assert events[-1]["t"] == "done" and events[-1]["provider"] == "gemini"
        assert rate_limits.is_skipped("groq", "openai/gpt-oss-120b", 0) == "rate_limit"

    def test_total_failure_degrades_to_the_dictionary(self, monkeypatch):
        _legs(monkeypatch, [[RuntimeError("Error code: 400 - nope")],
                            [RuntimeError("Error code: 400 - nope")]])
        monkeypatch.setattr(unpack_service, "is_dictionary_fast_path_eligible", lambda term: True)
        monkeypatch.setattr(unpack_service, "dictionary_lookup", lambda term: {
            "term": term, "definition_general": "a delay", "meaning_in_context": None,
            "confidence": "low"})
        events = _events()
        assert events[-1]["t"] == "done" and events[-1]["source"] == "dictionary_fallback"

    def test_no_dictionary_entry_still_answers_honestly(self, monkeypatch):
        _legs(monkeypatch, [[RuntimeError("Error code: 400 - nope")],
                            [RuntimeError("Error code: 400 - nope")]])
        monkeypatch.setattr(unpack_service, "is_dictionary_fast_path_eligible", lambda term: False)
        events = _events()
        assert events[-1]["t"] == "done" and events[-1]["source"] == "unavailable"

    def test_empty_term_is_an_error(self):
        assert _events(term="  ")[0]["t"] == "error"
