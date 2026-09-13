"""The answer loop: which leg answers, what falls through, what reaches the user.

No agent, no middleware — a failure before the first chunk tries the next
model, a failure after it is the user's problem to see rather than a second
answer silently replacing a half-written one."""
from __future__ import annotations

import pytest

from backend.llm import chat_agent, model_provider as mp
from backend.llm import rate_limits


class _Chunk:
    def __init__(self, content):
        self.content = content


class _FakeModel:
    """Stands in for a built leg: records the config it was streamed with."""

    def __init__(self, script, spec):
        self._script, self.spec = script, spec
        self.configs = []
        self.bound_tools = None

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    def stream(self, messages, config=None):
        self.configs.append(config)
        for item in self._script:
            if isinstance(item, Exception):
                raise item
            yield _Chunk(item)


def _legs(monkeypatch, script_by_step, route="simple"):
    """Build a fake leg per step; returns the models actually constructed."""
    rate_limits.clear()
    monkeypatch.setattr(mp, "_keys_for_provider", lambda provider: ["only-key"])
    built = []

    def _build(spec, **kwargs):
        model = _FakeModel(script_by_step.get(spec.step, ["text"]), spec)
        built.append(model)
        return model

    monkeypatch.setattr(chat_agent, "build_leg", _build)
    monkeypatch.setattr(chat_agent, "_check_budget", lambda spec, messages: None)
    return built


MESSAGES = [{"role": "user", "content": "hi"}]


class TestHappyPath:
    def test_text_chunks_reach_the_caller(self, monkeypatch):
        _legs(monkeypatch, {1: ["Hel", "lo"]})
        events = list(chat_agent.ask_chat_stream(MESSAGES, route="simple", route_reason="classifier"))
        assert [e["text"] for e in events if e["type"] == "text"] == ["Hel", "lo"]

    def test_route_and_step_are_logged_on_the_call(self, monkeypatch):
        built = _legs(monkeypatch, {1: ["ok"]})
        list(chat_agent.ask_chat_stream(MESSAGES, route="simple", route_reason="classifier",
                                        metadata={"call_type": "chat_turn"}))
        meta = built[0].configs[0]["metadata"]
        assert meta["route"] == "simple ← classifier"
        assert meta["route_step"] == 1
        assert meta["call_type"] == "chat_turn"
        assert built[0].configs[0]["callbacks"], "logger must be passed per call, not baked on"

    def test_gemini_thinking_and_code_parts_are_split_out(self, monkeypatch):
        _legs(monkeypatch, {1: [[
            {"type": "thinking", "thinking": "weighing it up"},
            {"type": "text", "text": "answer"},
            {"type": "executable_code", "executable_code": "print(2)", "language": "PYTHON"},
            {"type": "code_execution_result", "code_execution_result": "2", "outcome": 1},
        ]]})
        events = list(chat_agent.ask_chat_stream(MESSAGES, route="simple"))
        kinds = [e["type"] for e in events]
        assert kinds == ["thinking", "text", "code", "code_output"]
        assert events[2]["language"] == "python"
        assert events[3]["success"] is True


class TestFallback:
    def test_failure_before_the_first_chunk_tries_the_next_model(self, monkeypatch):
        built = _legs(monkeypatch, {1: [RuntimeError("Error code: 400 - bad request")], 2: ["second"]})
        events = list(chat_agent.ask_chat_stream(MESSAGES, route="simple", route_reason="classifier"))
        assert [e["text"] for e in events if e["type"] == "text"] == ["second"]
        assert built[1].configs[0]["metadata"]["route"] == (
            "simple ← classifier · skipped groq/openai/gpt-oss-120b (fatal)")
        assert built[1].configs[0]["metadata"]["route_step"] == 2

    def test_failure_after_the_first_chunk_reaches_the_user(self, monkeypatch):
        _legs(monkeypatch, {1: ["half an ", RuntimeError("connection dropped")], 2: ["never used"]})
        stream = chat_agent.ask_chat_stream(MESSAGES, route="simple")
        assert next(stream)["text"] == "half an "
        with pytest.raises(RuntimeError, match="connection dropped"):
            list(stream)

    def test_over_budget_leg_is_skipped_without_being_called(self, monkeypatch):
        built = _legs(monkeypatch, {1: ["never"], 2: ["fits"]})
        monkeypatch.setattr(chat_agent, "_check_budget", lambda spec, messages: (
            (_ for _ in ()).throw(mp.PromptTooLargeError("9000 > 7000")) if spec.step == 1 else None))
        events = list(chat_agent.ask_chat_stream(MESSAGES, route="simple", route_reason="classifier"))
        assert [e["text"] for e in events if e["type"] == "text"] == ["fits"]
        assert "(budget)" in built[1].configs[0]["metadata"]["route"]

    def test_every_leg_failing_raises(self, monkeypatch):
        _legs(monkeypatch, {step: [RuntimeError("Error code: 400 - nope")] for step in (1, 2, 3)})
        with pytest.raises(mp.AllLegsFailed):
            list(chat_agent.ask_chat_stream(MESSAGES, route="simple"))


class TestRouteSpecificBehaviour:
    def test_code_route_binds_gemini_code_execution_on_a_gemini_3_leg(self, monkeypatch):
        built = _legs(monkeypatch, {1: ["ok"]}, route="code")
        list(chat_agent.ask_chat_stream(MESSAGES, route="code"))
        assert built[0].bound_tools == [{"code_execution": {}}]

    def test_code_route_warns_once_when_the_answering_leg_cannot_run_code(self, monkeypatch):
        built = _legs(monkeypatch, {1: [RuntimeError("Error code: 400 - nope")],
                                    2: [RuntimeError("Error code: 400 - nope")], 3: ["prose"]},
                      route="code")
        events = list(chat_agent.ask_chat_stream(MESSAGES, route="code"))
        assert events[0]["type"] == "code_execution_gap"
        assert built[2].bound_tools is None

    def test_gemini_3_leg_says_thinking_will_not_stream(self, monkeypatch):
        _legs(monkeypatch, {1: ["ok"]}, route="code")   # code's first leg is gemini 3.1-flash-lite
        events = list(chat_agent.ask_chat_stream(MESSAGES, route="code"))
        assert events[0]["type"] == "thinking_gap"

    def test_image_route_announces_itself_and_fails_clearly(self, monkeypatch):
        _legs(monkeypatch, {step: [RuntimeError("Error code: 400 - nope")] for step in (1, 2)},
              route="image")
        stream = chat_agent.ask_chat_stream(MESSAGES, route="image")
        assert next(stream) == {"type": "status", "text": "Reading attachment…"}
        with pytest.raises(chat_agent.VisionUnavailableError, match="temporarily unavailable"):
            list(stream)

    def test_parked_leg_is_not_called_at_all(self, monkeypatch):
        built = _legs(monkeypatch, {1: ["never"], 2: ["used"]})
        rate_limits.record_failure("groq", "openai/gpt-oss-120b", 0, "daily_quota")
        events = list(chat_agent.ask_chat_stream(MESSAGES, route="simple", route_reason="classifier"))
        assert [e["text"] for e in events if e["type"] == "text"] == ["used"]
        assert "(daily_quota)" in built[0].configs[0]["metadata"]["route"]
        rate_limits.clear()
