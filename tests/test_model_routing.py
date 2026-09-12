"""chat_models.toml is the one file a human edits to change chat models, so a
typo in it must fail loudly at load time rather than at 2am in a chat turn."""
from __future__ import annotations

import pytest

from backend.llm import model_provider as mp
from backend.llm.model_provider import ChatModelsConfigError, load_chat_models

GOOD = """
[classifier]
models     = ["groq/openai/gpt-oss-20b", "gemini/gemini-3.1-flash-lite"]
max_tokens = 400
reasoning  = "low"
[simple]
models     = ["groq/openai/gpt-oss-120b"]
max_tokens = 8192
reasoning  = "low"
[complex]
models     = ["gemini/gemini-2.5-flash"]
max_tokens = 8192
reasoning  = "low"
[code]
models     = ["gemini/gemini-3.1-flash-lite", "groq/openai/gpt-oss-120b"]
max_tokens = 8192
reasoning  = "low"
[image]
models     = ["gemini/gemini-2.5-flash"]
max_tokens = 8192
reasoning  = "low"
[explain]
models          = ["groq/openai/gpt-oss-120b"]
max_tokens      = 200
timeout_seconds = 5
[retry]
retries_per_model          = 1
skip_after_rate_limit_sec  = 30
skip_after_daily_quota_sec = 3600
skip_after_no_credit_sec   = 600
"""


def _write(tmp_path, text):
    path = tmp_path / "chat_models.toml"
    path.write_text(text, encoding="utf-8")
    return path


class TestLoaderAcceptsAGoodFile:
    def test_routes_and_order_survive(self, tmp_path):
        cfg = load_chat_models(_write(tmp_path, GOOD))
        assert [str(m) for m in cfg.routes["classifier"].models] == [
            "groq/openai/gpt-oss-20b", "gemini/gemini-3.1-flash-lite"]
        assert cfg.routes["classifier"].max_tokens == 400
        assert cfg.routes["explain"].timeout_seconds == 5
        assert cfg.routes["simple"].reasoning == "low"
        assert cfg.retry.skip_after_daily_quota_sec == 3600

    def test_reasoning_defaults_to_off_when_absent(self, tmp_path):
        cfg = load_chat_models(_write(tmp_path, GOOD))
        assert cfg.routes["explain"].reasoning == "off"


class TestLoaderRejects:
    @pytest.mark.parametrize("bad,message", [
        (GOOD.replace('"groq/openai/gpt-oss-20b"', '"claude/opus"'), "unknown provider"),
        (GOOD.replace('models     = ["groq/openai/gpt-oss-120b"]\nmax_tokens = 8192\nreasoning  = "low"\n[complex]',
                      'models     = []\nmax_tokens = 8192\nreasoning  = "low"\n[complex]'), "non-empty models"),
        (GOOD.replace('[code]\nmodels     = ["gemini/gemini-3.1-flash-lite"',
                      '[code]\nmodels     = ["gemini/gemini-2.5-flash"'), "Gemini 3"),
        (GOOD.replace('[image]\nmodels     = ["gemini/gemini-2.5-flash"]',
                      '[image]\nmodels     = ["groq/openai/gpt-oss-120b"]'), "Gemini"),
        (GOOD.replace("skip_after_no_credit_sec   = 600", ""), "skip_after_no_credit_sec"),
        (GOOD.replace("max_tokens = 400", "max_tokens = 0"), "positive integer"),
        (GOOD.replace('reasoning  = "low"', 'reasoning  = "high"', 1), "low"),
        (GOOD + '\n[turbo]\nmodels = ["groq/x"]\nmax_tokens = 10\n', "unknown section"),
        (GOOD.replace("[retry]", "[retryy]"), "missing section"),
    ])
    def test_bad_file_fails_loudly(self, tmp_path, bad, message):
        with pytest.raises(ChatModelsConfigError, match=message):
            load_chat_models(_write(tmp_path, bad))

    def test_missing_file_fails_loudly(self, tmp_path):
        with pytest.raises(ChatModelsConfigError, match="missing"):
            load_chat_models(tmp_path / "nope.toml")


class TestShippedFile:
    def test_the_real_file_loads_and_has_no_openrouter_model(self):
        cfg = mp.chat_models()
        listed = [str(m) for route in cfg.routes.values() for m in route.models]
        assert listed, "chat_models.toml lists no models"
        assert not [m for m in listed if m.startswith("openrouter/")], (
            f"OpenRouter is excluded from chat until the account is funded: {listed}")


class TestRouteLegs:
    """Keys within a model before the next model: a model is only dropped once
    every key of its provider has had a turn."""

    @pytest.fixture(autouse=True)
    def _two_keys(self, monkeypatch):
        monkeypatch.setattr(mp, "_keys_for_provider",
                            lambda provider: {"groq": ["g1", "g2"], "gemini": ["k1", "k2"],
                                              "openrouter": ["o1"]}[provider])

    def test_keys_come_before_the_next_model(self):
        legs = mp.route_legs("simple")
        assert [(leg.step, leg.provider, leg.key_index) for leg in legs[:3]] == [
            (1, "groq", 0), (1, "groq", 1), (2, "gemini", 0)]

    def test_step_is_the_position_in_the_configured_list(self):
        steps = {leg.model: leg.step for leg in mp.route_legs("simple")}
        assert steps["openai/gpt-oss-120b"] == 1
        assert steps["gemini-2.5-flash"] == 3

    def test_image_route_uses_the_first_gemini_key_only(self):
        legs = mp.route_legs("image")
        assert {leg.key_index for leg in legs} == {0}, "Files API scopes an upload to one key"


class TestRunRoute:
    """The fallback loop: what falls through, what propagates, what gets parked."""

    @pytest.fixture(autouse=True)
    def _one_key_clean_skips(self, monkeypatch):
        from backend.llm import rate_limits
        rate_limits.clear()
        monkeypatch.setattr(mp, "_keys_for_provider", lambda provider: ["only-key"])
        yield
        rate_limits.clear()

    def _boom(self, exc):
        def attempt(spec):
            raise exc
            yield  # pragma: no cover - makes this a generator
        return attempt

    def test_first_working_leg_wins(self):
        notes = []
        def attempt(spec):
            yield f"answer from {spec.model}"
        spec, items = mp.run_route("simple", attempt, notes=notes)
        assert spec.step == 1 and list(items) == ["answer from openai/gpt-oss-120b"]
        assert notes == []

    def test_failure_before_the_first_item_falls_through(self):
        import groq, httpx
        bad = groq.BadRequestError("Error code: 400 - nope", response=httpx.Response(
            400, request=httpx.Request("POST", "https://api.groq.com/x")), body=None)
        notes, seen = [], []
        def attempt(spec):
            seen.append(spec.model)
            if spec.step == 1:
                raise bad
            yield "second leg answer"
        spec, items = mp.run_route("simple", attempt, notes=notes)
        assert spec.step == 2 and list(items) == ["second leg answer"]
        assert notes == ["skipped groq/openai/gpt-oss-120b (fatal)"]

    def test_failure_after_the_first_item_propagates(self):
        notes = []
        def attempt(spec):
            yield "partial"
            raise RuntimeError("dropped mid-stream")
        spec, items = mp.run_route("simple", attempt, notes=notes)
        with pytest.raises(RuntimeError, match="dropped mid-stream"):
            list(items)
        assert notes == [], "a half-streamed answer must not be replaced by another leg"

    def test_transient_error_is_retried_on_the_same_leg(self):
        import httpx
        attempts = []
        def attempt(spec):
            attempts.append(spec.step)
            if len(attempts) == 1:
                raise httpx.ReadTimeout("The read operation timed out")
            yield "recovered"
        spec, items = mp.run_route("simple", attempt, notes=[])
        assert attempts == [1, 1] and spec.step == 1 and list(items) == ["recovered"]

    def test_rate_limited_leg_is_parked_for_the_next_turn(self):
        import groq, httpx
        limited = groq.RateLimitError(
            "Error code: 429 - tokens per minute (TPM): Limit 8000",
            response=httpx.Response(429, request=httpx.Request("POST", "https://api.groq.com/x")),
            body=None)
        def attempt(spec):
            if spec.provider == "groq":
                raise limited
            yield "gemini answer"
        first_notes = []
        mp.run_route("simple", attempt, notes=first_notes)
        assert first_notes == ["skipped groq/openai/gpt-oss-120b (rate_limit)"]

        called = []
        def attempt2(spec):
            called.append(spec.model)
            yield "gemini answer"
        second_notes = []
        mp.run_route("simple", attempt2, notes=second_notes)
        assert "openai/gpt-oss-120b" not in called, "parked leg must not be called again"
        assert second_notes == ["skipped groq/openai/gpt-oss-120b (rate_limit)"]

    def test_every_leg_failing_raises_with_the_notes(self):
        notes = []
        with pytest.raises(mp.AllLegsFailed) as exc_info:
            mp.run_route("simple", self._boom(RuntimeError("bad request")), notes=notes)
        assert len(notes) == 3
        assert "every model failed" in str(exc_info.value)

    def test_caller_can_resume_at_the_next_leg(self):
        legs = iter(mp.route_legs("simple"))
        def attempt(spec):
            yield spec.model
        first, _ = mp.run_route("simple", attempt, notes=[], legs=legs)
        second, _ = mp.run_route("simple", attempt, notes=[], legs=legs)
        assert first.step == 1 and second.step == 2


class TestRouteLabel:
    def test_plain_label(self):
        assert mp.route_label("simple", "classifier", []) == "simple ← classifier"

    def test_label_carries_what_it_fell_past(self):
        label = mp.route_label("simple", "classifier_failed",
                               ["skipped groq/openai/gpt-oss-120b (rate_limit)"])
        assert label == "simple ← classifier_failed · skipped groq/openai/gpt-oss-120b (rate_limit)"


class TestReasoningMapping:
    @pytest.mark.parametrize("provider,model,reasoning,expected", [
        ("gemini", "gemini-3.1-flash-lite", "low", {"thinking_level": "low"}),
        ("gemini", "gemini-3.1-flash-lite", "off", {"thinking_level": "low"}),
        ("gemini", "gemini-2.5-flash", "low", {"thinking_budget": 1024}),
        ("gemini", "gemini-2.5-flash", "off", {"thinking_budget": 0}),
        ("groq", "openai/gpt-oss-120b", "low", {"reasoning_effort": "low"}),
        ("groq", "llama-3.3-70b", "low", {}),
        ("openrouter", "z-ai/glm-5.3-flash", "low", {"reasoning": {"effort": "low"}}),
        ("openrouter", "z-ai/glm-5.3-flash", "off", {"reasoning": {"enabled": False}}),
    ])
    def test_reasoning_kwargs(self, provider, model, reasoning, expected):
        assert mp.reasoning_kwargs(provider, model, reasoning) == expected


class TestBuildLeg:
    def test_gemini_chat_leg_carries_thinking_and_the_token_ceiling(self, monkeypatch):
        monkeypatch.setattr(mp, "_keys_for_provider", lambda provider: ["k1"])
        spec = mp.LegSpec("complex", 1, "gemini", "gemini-2.5-flash", 0)
        model = mp.build_leg(spec, streaming=True, thinking=True)
        assert model.max_output_tokens == 8192
        assert model.include_thoughts is True
        assert model.thinking_budget == 1024

    def test_explain_leg_gets_the_timeout_and_no_thinking(self, monkeypatch):
        monkeypatch.setattr(mp, "_keys_for_provider", lambda provider: ["k1"])
        spec = mp.LegSpec("explain", 1, "groq", "openai/gpt-oss-120b", 0)
        model = mp.build_leg(spec, streaming=True, temperature=0.3)
        assert model.max_tokens == 200
        assert model.request_timeout == 5
        assert model.temperature == 0.3
