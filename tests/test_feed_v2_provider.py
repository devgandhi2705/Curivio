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
