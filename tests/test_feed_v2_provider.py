"""
Phase 3 provider tests: round-robin key rotation with a stateful per-key
cooldown on 429. After key 1 rate-limits, key 2 serves; the NEXT call must skip
key 1 entirely (cooldown) rather than failing through it again.
"""
import pytest

from backend.services.feed_v2.llm import provider


class FakeRateLimit(Exception):
    """Name matches provider._is_rate_limit's type-name check."""
    def __init__(self):
        super().__init__("429 Too Many Requests")
    # rename so type(exc).__name__ is one the detector recognizes
FakeRateLimit.__name__ = "RateLimitError"


@pytest.fixture(autouse=True)
def _clear_cooldowns():
    provider._cooldowns.clear()
    yield
    provider._cooldowns.clear()


def test_429_on_key1_rotates_to_key2_and_parks_key1():
    keys = ["k1", "k2"]
    calls = {"k1": 0, "k2": 0}

    def make_call(key):
        calls[key] += 1
        if key == "k1":
            raise FakeRateLimit()
        return {"ok": key}

    # Call 1: k1 429s (parked) -> rotate -> k2 serves.
    result, served, attempt = provider._rotate_call(keys, make_call)
    assert result == {"ok": "k2"}
    assert served == "k2"
    assert calls == {"k1": 1, "k2": 1}
    assert provider._in_cooldown("k1", __import__("time").monotonic())

    # Call 2: k1 still cooled down -> skipped entirely -> k2 serves first.
    result2, served2, _ = provider._rotate_call(keys, make_call)
    assert result2 == {"ok": "k2"}
    assert served2 == "k2"
    assert calls["k1"] == 1, "key 1 was re-hit despite being in cooldown"
    assert calls["k2"] == 2


def test_non_rate_limit_error_propagates_immediately():
    def make_call(key):
        raise ValueError("bad model id")

    with pytest.raises(ValueError):
        provider._rotate_call(["k1", "k2"], make_call)


def test_all_cooled_down_falls_back_to_full_pool():
    import time
    provider._park("k1", time.monotonic())
    provider._park("k2", time.monotonic())
    served_keys = []

    def make_call(key):
        served_keys.append(key)
        return {"ok": key}

    # Both parked -> _rotate_call tries the full pool rather than serving nothing.
    result, served, _ = provider._rotate_call(["k1", "k2"], make_call)
    assert result == {"ok": served}
    assert served_keys[0] == "k1"


def test_routing_fallback_always_different_provider():
    # image_ingestor (vision) is the documented same-provider exception — no
    # OpenRouter model in the registry is vision-capable.
    for agent, (primary, fallback) in provider.AGENT_ROUTING.items():
        if agent in provider._SAME_PROVIDER_OK:
            continue
        pp = provider.MODEL_REGISTRY[primary][0]
        fp = provider.MODEL_REGISTRY[fallback][0]
        assert pp != fp, f"{agent}: primary and fallback share provider {pp}"


def test_vision_agent_is_same_provider_by_design():
    p, f = provider.AGENT_ROUTING["image_ingestor"]
    assert provider.MODEL_REGISTRY[p][0] == provider.MODEL_REGISTRY[f][0] == "google"
    assert "image_ingestor" in provider._SAME_PROVIDER_OK


def test_tolerant_parser_handles_fenced_and_bare_json():
    assert provider.parse_json_tolerant('```json\n{"a": 1}\n```') == {"a": 1}
    assert provider.parse_json_tolerant('prose {"b": 2} trailing') == {"b": 2}
    with pytest.raises(ValueError):
        provider.parse_json_tolerant("no json here")


# ── Phase 12b: visual_director's OpenRouter fallback ─────────────────────────
def test_visual_director_fallback_is_the_free_openrouter_model():
    """The paid nemotron leg 402s on an unfunded account (can afford ~200 tokens); the
    :free variant is what actually serves. Still cross-provider."""
    _, fallback = provider.AGENT_ROUTING["visual_director"]
    assert provider.MODEL_REGISTRY[fallback] == ("openrouter", "nvidia/nemotron-3-super-120b-a12b:free")


def _capture_openrouter_kwargs(monkeypatch, agent):
    sent = {}

    class _Completions:
        def create(self, **kw):
            sent.update(kw)
            raise RuntimeError("stop after capture")

    class _Client:
        def __init__(self, **kw):
            self.chat = type("C", (), {"completions": _Completions()})()

    import openai
    monkeypatch.setattr(openai, "OpenAI", _Client)
    monkeypatch.setattr(provider, "_openrouter_keys", lambda: ["k"])
    monkeypatch.setattr(provider, "_gemini_keys", lambda: (_ for _ in ()).throw(provider.ProviderKeyMissing("no")))
    monkeypatch.setattr(provider.call_logger, "write_call_row", lambda **kw: None)
    with pytest.raises(provider.AllLegsFailed):
        provider.call_agent(agent, [{"role": "user", "content": "x"}], meta={"is_test": True})
    return sent


def test_visual_director_openrouter_leg_sends_max_tokens_ceiling(monkeypatch):
    sent = _capture_openrouter_kwargs(monkeypatch, "visual_director")
    assert sent["max_tokens"] == provider.OPENROUTER_MAX_TOKENS["visual_director"]


# ── Phase 12c: every feed_v2 OpenRouter leg is the :free fallback, Gemini primary ──
FREE = ("openrouter", "nvidia/nemotron-3-super-120b-a12b:free")


def test_every_text_agent_is_gemini_primary_free_fallback():
    """Both paid nemotron models 402 on this unfunded account, so every OpenRouter leg is
    the :free model, and always as the FALLBACK: the 50/day free quota is spent only when
    Gemini fails. The 4 former OpenRouter primaries (journey_planner, web_researcher,
    source_ranker, claim_validator) are flipped."""
    for agent, (primary, fallback) in provider.AGENT_ROUTING.items():
        if agent in provider._SAME_PROVIDER_OK:
            continue
        assert provider.MODEL_REGISTRY[primary][0] == "google", agent
        assert provider.MODEL_REGISTRY[fallback] == FREE, agent


def test_no_route_uses_a_paid_openrouter_model():
    for agent, legs in provider.AGENT_ROUTING.items():
        for leg in legs:
            prov, model_id = provider.MODEL_REGISTRY[leg]
            assert prov != "openrouter" or model_id.endswith(":free"), (agent, model_id)


@pytest.mark.parametrize("agent", sorted(provider.OPENROUTER_MAX_TOKENS))
def test_each_agent_sends_its_own_ceiling(monkeypatch, agent):
    sent = _capture_openrouter_kwargs(monkeypatch, agent)
    assert sent["max_tokens"] == provider.OPENROUTER_MAX_TOKENS[agent]


def test_ceilings_cover_every_agent_that_makes_llm_calls():
    """claim_validator is still a graph stub (no LLM call, nothing to size);
    image_ingestor has no OpenRouter leg."""
    assert set(provider.OPENROUTER_MAX_TOKENS) == set(provider.AGENT_ROUTING) - {"claim_validator", "image_ingestor"}


def test_claim_validator_sends_no_ceiling(monkeypatch):
    sent = _capture_openrouter_kwargs(monkeypatch, "claim_validator")
    assert "max_tokens" not in sent


def test_openrouter_200_with_embedded_upstream_error_is_reported_as_that_error(monkeypatch):
    """Real response seen 2026-09-18 from the :free model: HTTP 200, choices=None, and an
    `error` body ('Upstream error from Nvidia: Service temporarily overloaded', 503). It
    was logged as 'empty response'; it must surface as the upstream error it is."""
    class _Resp:
        choices = None
        usage = None
        model_extra = {"error": {"message": "Upstream error from Nvidia: Service temporarily overloaded",
                                 "code": 503, "metadata": {"error_type": "provider_overloaded"}}}

    class _Client:
        def __init__(self, **kw):
            self.chat = type("C", (), {"completions": type("X", (), {"create": staticmethod(lambda **k: _Resp())})()})()

    import openai
    monkeypatch.setattr(openai, "OpenAI", _Client)
    with pytest.raises(RuntimeError, match=r"503.*overloaded"):
        provider._call_openrouter("nvidia/nemotron-3-super-120b-a12b:free",
                                  [{"role": "user", "content": "x"}], "", {}, "k")


# ── Phase 12c: bounded retry on the :free upstream's 503 overload ─────────────
_OVERLOAD = "OpenRouter upstream error 503: Upstream error from Nvidia: Service temporarily overloaded (provider_overloaded)"


def _route_to_openrouter_only(monkeypatch, sdk):
    monkeypatch.setattr(provider, "_openrouter_keys", lambda: ["k"])
    monkeypatch.setattr(provider, "_gemini_keys", lambda: (_ for _ in ()).throw(provider.ProviderKeyMissing("no")))
    monkeypatch.setattr(provider.call_logger, "write_call_row", lambda **kw: None)
    monkeypatch.setitem(provider._SDK_FOR_PROVIDER, "openrouter", sdk)
    slept = []
    monkeypatch.setattr(provider, "_sleep", slept.append)
    return slept


def _ok(api_model_id):
    return {"text": '{"objectives": ["x"]}', "in_tokens": 1, "out_tokens": 1, "latency_ms": 1, "model_used": api_model_id}


def test_upstream_overload_is_retried_twice_with_backoff(monkeypatch):
    calls = []

    def sdk(api_model_id, *a, **k):
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError(_OVERLOAD)
        return _ok(api_model_id)
    slept = _route_to_openrouter_only(monkeypatch, sdk)
    out = provider.call_agent("lesson_planner", [{"role": "user", "content": "x"}],
                              schema={"required": ["objectives"]}, meta={"is_test": True})
    assert out == {"objectives": ["x"]}
    assert len(calls) == 3 and slept == [2.0, 6.0]


def test_upstream_overload_gives_up_after_two_retries(monkeypatch):
    calls = []

    def sdk(api_model_id, *a, **k):
        calls.append(1)
        raise RuntimeError(_OVERLOAD)
    slept = _route_to_openrouter_only(monkeypatch, sdk)
    with pytest.raises(provider.AllLegsFailed, match="overloaded"):
        provider.call_agent("lesson_planner", [{"role": "user", "content": "x"}], meta={"is_test": True})
    assert len(calls) == 3 and slept == [2.0, 6.0]


def test_other_openrouter_errors_are_not_retried(monkeypatch):
    calls = []

    def sdk(api_model_id, *a, **k):
        calls.append(1)
        raise RuntimeError("Error code: 400 - bad request")
    slept = _route_to_openrouter_only(monkeypatch, sdk)
    with pytest.raises(provider.AllLegsFailed):
        provider.call_agent("lesson_planner", [{"role": "user", "content": "x"}], meta={"is_test": True})
    assert len(calls) == 1 and slept == []
