"""plan_turn is the whole routing decision in one pure function: classifier
answer + user overrides -> what runs. Toggles are overrides, not modes
(design decision A), and a failed classifier must still produce a safe turn."""
from __future__ import annotations

import pytest

from backend.llm import model_provider as mp
from backend.llm.chat_router import RoutingDecision, TurnPlan, classify_message, plan_turn


def _decision(**over) -> RoutingDecision:
    base = dict(needs_web_search=False, search_query="", complexity="simple",
                needs_code_execution=False, wants_simple_explanation=False, crisis=False)
    base.update(over)
    return RoutingDecision(**base)


class TestRouteChoice:
    def test_simple_by_default(self):
        assert plan_turn(_decision(), message="hi").route == "simple"

    def test_complex_when_the_classifier_says_so(self):
        assert plan_turn(_decision(complexity="complex"), message="compare X and Y").route == "complex"

    def test_code_beats_complexity(self):
        plan = plan_turn(_decision(complexity="complex", needs_code_execution=True), message="run this")
        assert plan.route == "code"

    def test_image_beats_everything(self):
        plan = plan_turn(_decision(needs_code_execution=True, complexity="complex"),
                         message="what is in this picture", has_image=True)
        assert plan.route == "image"


class TestSearch:
    def test_classifier_asks_for_a_search(self):
        plan = plan_turn(_decision(needs_web_search=True, search_query="ipl 2026 winner"),
                         message="who won")
        assert plan.search is True and plan.search_query == "ipl 2026 winner"
        assert plan.reason == "classifier"

    def test_toggle_forces_a_search_the_classifier_did_not_want(self):
        plan = plan_turn(_decision(needs_web_search=False), message="explain attention",
                         toggle_web_search=True)
        assert plan.search is True
        assert plan.search_query == "explain attention", "falls back to the message"
        assert plan.reason == "classifier+toggle:web_search"

    def test_feed_action_never_blocks_a_search(self):
        plan = plan_turn(_decision(needs_web_search=True, search_query="q"),
                         message="is this still true?", feed_action="explain_simply")
        assert plan.search is True


class TestSimpleTone:
    def test_toggle_forces_it(self):
        plan = plan_turn(_decision(), message="explain attention", toggle_simple=True)
        assert plan.simple_tone is True and "+toggle:explain_simply" in plan.reason

    def test_feed_explain_simply_forces_it(self):
        plan = plan_turn(_decision(), message="Explain this simply.", feed_action="explain_simply")
        assert plan.simple_tone is True and "+feed:explain_simply" in plan.reason

    def test_sticky_session_keeps_it(self):
        plan = plan_turn(_decision(), message="and what about scaling?", sticky_simple=True)
        assert plan.simple_tone is True and "+sticky:explain_simply" in plan.reason

    def test_classifier_can_ask_for_it_on_a_plain_turn(self):
        plan = plan_turn(_decision(wants_simple_explanation=True), message="eli5 transformers")
        assert plan.simple_tone is True and plan.reason == "classifier"

    def test_off_by_default(self):
        assert plan_turn(_decision(), message="explain attention").simple_tone is False


class TestCrisis:
    def test_classifier_says_yes(self):
        assert plan_turn(_decision(crisis=True), message="i want to die").crisis is True

    def test_classifier_says_no(self):
        assert plan_turn(_decision(crisis=False), message="hi").crisis is False

    def test_classifier_failure_turns_it_on(self):
        assert plan_turn(None, message="hi").crisis is True


class TestClassifierFailure:
    def test_safe_plan(self):
        plan = plan_turn(None, message="what happened at the summit?")
        assert (plan.route, plan.search, plan.complexity) == ("simple", False, "simple")
        assert plan.search_query == "what happened at the summit?"
        assert plan.reason == "classifier_failed"

    def test_toggles_still_apply(self):
        plan = plan_turn(None, message="latest news", has_image=False,
                         toggle_web_search=True, toggle_simple=True)
        assert plan.search is True and plan.simple_tone is True
        assert plan.reason == "classifier_failed+toggle:web_search+toggle:explain_simply"

    def test_image_turn_still_routes_to_image(self):
        assert plan_turn(None, message="what is this", has_image=True).route == "image"


class _FakeStructured:
    def __init__(self, result):
        self._result = result
        self.calls = []

    def invoke(self, messages, config=None):
        self.calls.append((messages, config))
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _FakeModel:
    def __init__(self, result):
        self.structured = _FakeStructured(result)

    def with_structured_output(self, schema, method=None, include_raw=False):
        assert method == "json_schema", "tool calling is what failed on Groq — JSON schema only"
        assert include_raw is True, "parsed=None must be visible, not swallowed"
        return self.structured


class TestClassifyMessage:
    @pytest.fixture(autouse=True)
    def _one_key(self, monkeypatch):
        from backend.llm import rate_limits
        rate_limits.clear()
        monkeypatch.setattr(mp, "_keys_for_provider", lambda provider: ["k"])
        yield
        rate_limits.clear()

    def test_returns_the_parsed_decision(self, monkeypatch):
        decision = _decision(needs_web_search=True, search_query="q")
        model = _FakeModel({"parsed": decision, "raw": None, "parsing_error": None})
        monkeypatch.setattr("backend.llm.chat_router.build_leg", lambda spec, **kw: model)
        assert classify_message("who won?") is decision

    def test_card_title_is_given_to_the_classifier(self, monkeypatch):
        model = _FakeModel({"parsed": _decision(), "raw": None, "parsing_error": None})
        monkeypatch.setattr("backend.llm.chat_router.build_leg", lambda spec, **kw: model)
        classify_message("explain", card_title="Why Audit AI Needs Blueprints")
        sent = "\n".join(m["content"] for m in model.structured.calls[0][0])
        assert "Why Audit AI Needs Blueprints" in sent

    def test_invalid_json_falls_through_to_the_next_model(self, monkeypatch):
        good = _decision(complexity="complex")
        models = [_FakeModel({"parsed": None, "raw": None, "parsing_error": "not json"}),
                  _FakeModel({"parsed": good, "raw": None, "parsing_error": None})]
        used = iter(models)
        monkeypatch.setattr("backend.llm.chat_router.build_leg", lambda spec, **kw: next(used))
        assert classify_message("hi") is good

    def test_every_model_failing_returns_none(self, monkeypatch):
        def boom(spec, **kw):
            raise RuntimeError("Error code: 400 - bad request")
        monkeypatch.setattr("backend.llm.chat_router.build_leg", boom)
        assert classify_message("hi") is None

    def test_image_note_sent_when_has_image(self, monkeypatch):
        model = _FakeModel({"parsed": _decision(), "raw": None, "parsing_error": None})
        monkeypatch.setattr("backend.llm.chat_router.build_leg", lambda spec, **kw: model)
        classify_message("what colour is this?", has_image=True)
        sent = "\n".join(m["content"] for m in model.structured.calls[0][0])
        assert "image is attached" in sent.lower()

    def test_no_image_note_by_default(self, monkeypatch):
        model = _FakeModel({"parsed": _decision(), "raw": None, "parsing_error": None})
        monkeypatch.setattr("backend.llm.chat_router.build_leg", lambda spec, **kw: model)
        classify_message("hello")
        sent = "\n".join(m["content"] for m in model.structured.calls[0][0])
        assert "image is attached" not in sent.lower()

    def test_history_multipart_content_is_flattened_to_text(self, monkeypatch):
        model = _FakeModel({"parsed": _decision(), "raw": None, "parsing_error": None})
        monkeypatch.setattr("backend.llm.chat_router.build_leg", lambda spec, **kw: model)
        classify_message("and this one?", history=[
            {"role": "user", "content": [{"type": "text", "text": "look at this"},
                                         {"type": "media", "file_uri": "gs://x", "mime_type": "image/png"}]},
            {"role": "assistant", "content": "It is a red square."},
        ])
        sent = model.structured.calls[0][0]
        assert all(isinstance(m["content"], str) for m in sent)
        assert any("look at this" in m["content"] for m in sent)


class TestSearchQueryDates:
    """The classifier's training data ends before today, so left alone it
    stamps its own "current" year onto recency queries ("... comparison
    2024" in 2026). It is told today's date, and a year it invented that is
    older than today never reaches the search."""

    @pytest.fixture(autouse=True)
    def _one_key(self, monkeypatch):
        from backend.llm import rate_limits
        rate_limits.clear()
        monkeypatch.setattr(mp, "_keys_for_provider", lambda provider: ["k"])
        yield
        rate_limits.clear()

    def _classify(self, monkeypatch, query, message, history=None):
        model = _FakeModel({"parsed": _decision(needs_web_search=True, search_query=query),
                            "raw": None, "parsing_error": None})
        monkeypatch.setattr("backend.llm.chat_router.build_leg", lambda spec, **kw: model)
        return model, classify_message(message, history=history)

    def test_todays_date_is_given_to_the_classifier(self, monkeypatch):
        from datetime import datetime, timezone
        model, _ = self._classify(monkeypatch, "q", "latest news")
        sent = "\n".join(m["content"] for m in model.structured.calls[0][0])
        assert datetime.now(timezone.utc).strftime("%Y-%m-%d") in sent

    def test_a_stale_year_the_user_never_wrote_is_dropped(self, monkeypatch):
        _, decision = self._classify(
            monkeypatch, "Claude vs ChatGPT comparison 2024 features performance",
            "Tell me comparision of claude vs chatgpt in depth as much as possible.")
        assert decision.search_query == "Claude vs ChatGPT comparison features performance"

    def test_a_year_the_user_wrote_is_kept(self, monkeypatch):
        _, decision = self._classify(monkeypatch, "2022 FIFA World Cup winner",
                                     "who won the 2022 world cup?")
        assert decision.search_query == "2022 FIFA World Cup winner"

    def test_a_year_from_earlier_in_the_chat_is_kept(self, monkeypatch):
        _, decision = self._classify(monkeypatch, "India GDP 2019", "and what was it then?",
                                     history=[{"role": "user", "content": "India GDP in 2019"}])
        assert decision.search_query == "India GDP 2019"

    def test_the_current_year_is_kept(self, monkeypatch):
        from datetime import datetime, timezone
        year = datetime.now(timezone.utc).year
        _, decision = self._classify(monkeypatch, f"best laptops {year}", "best laptops right now")
        assert decision.search_query == f"best laptops {year}"
