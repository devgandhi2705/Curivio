"""
Chat mode mapping spec — toggle state machine and backend mode routing.

These tests document the exact semantics the UI toggle logic enforces so
backend behaviour stays consistent with the frontend contract:

  UI state             chatMode sent to API    backend retrieval
  ─────────────────    ──────────────────────   ──────────────────────────────
  off                  "normal"                 none (memory/context only)
  Web Search on        "web_search"             Tavily search

chat_stream() (the only chat path — sync /chat and its backend-orchestrated
chat_modes_service.prepare_mode_context pre-fetch were both retired) drives
this differently since Task 4: chat_mode only supplies the Web Search/Explain
Simply toggles that plan_turn() merges with the classifier's own judgment —
chat_service itself runs the search, not the model — see
TestStreamReflectsThePlan below.

Toggle rules (mirrors ChatInput.jsx logic):
  - Clicking Web Search when mode is "web_search" → "normal"
  - Clicking Web Search otherwise                 → "web_search"

TESTING RULES
─────────────
- All Tavily/Groq calls are mocked
- No real HTTP requests made
"""

import json
import pytest
from unittest.mock import patch


# ─────────────────────────────────────────────────────────────────────────────
# Pure toggle state-machine (mirrors ChatInput.jsx logic, written in Python)
# ─────────────────────────────────────────────────────────────────────────────

def toggle_web_search(current_mode: str) -> str:
    """Mirror of ChatInput toggleWeb."""
    return "normal" if current_mode == "web_search" else "web_search"


class TestToggleWebSearch:
    def test_off_to_on(self):
        assert toggle_web_search("normal") == "web_search"

    def test_on_to_off(self):
        assert toggle_web_search("web_search") == "normal"


class TestVisualToggleState:
    """web_active flag (mirrors ChatInput JSX logic)."""

    @staticmethod
    def web_active(mode):  return mode == "web_search"

    def test_normal_inactive(self):
        assert not self.web_active("normal")

    def test_web_search_active(self):
        assert self.web_active("web_search")


class TestModeTransitionGraph:
    """Full toggle interaction sequences."""

    def test_normal_web_normal(self):
        m = "normal"
        m = toggle_web_search(m)
        assert m == "web_search"
        m = toggle_web_search(m)
        assert m == "normal"


# ─────────────────────────────────────────────────────────────────────────────
# Backend ChatRequest validation — mode field
# ─────────────────────────────────────────────────────────────────────────────

class TestChatRequestValidation:
    """Pydantic model accepts all valid modes and rejects invalid ones."""

    def _make_request(self, mode):
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from backend.main import ChatRequest
        return ChatRequest(session_id="s", message="m", chat_mode=mode)

    def test_normal_mode_accepted(self):
        req = self._make_request("normal")
        assert req.chat_mode == "normal"

    def test_web_search_mode_accepted(self):
        req = self._make_request("web_search")
        assert req.chat_mode == "web_search"

    def test_deep_research_mode_rejected(self):
        # deep_research was removed — no code path can invoke it going forward.
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self._make_request("deep_research")

    def test_invalid_mode_rejected(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self._make_request("turbo_mode")

    def test_default_mode_is_normal(self):
        from backend.main import ChatRequest
        req = ChatRequest(session_id="s", message="m")
        assert req.chat_mode == "normal"


class TestStreamReflectsThePlan:
    """chat_mode/auto_mode/sources in the done event now report what the TURN
    PLAN did: the search is run by chat_service, never by the model."""

    @pytest.fixture(autouse=True)
    def _reset_sticky_simple_mode(self):
        # chat_title_service persists conversation mode against the real DB
        # (no test-isolation layer for it) — every test here shares session_id
        # "sess", so a "layman" run earlier in the file would otherwise leak
        # sticky-simple state into a later "normal" run.
        from backend.services.chat_title_service import set_session_conversation_mode
        set_session_conversation_mode("sess", "normal")
        yield

    def _run(self, message, chat_mode, decision, search=("note", [{"title": "T", "url": "https://example.com"}])):
        from backend.llm.chat_router import RoutingDecision
        from backend.services.chat_service import chat_stream

        def fake_ask_chat_stream(messages, *args, **kwargs):
            yield {"type": "text", "text": "answer"}

        events = []
        with patch("backend.services.chat_service._detect_topic_hint", return_value=None), \
             patch("backend.services.chat_service._load_history_messages", return_value=[]), \
             patch("backend.services.chat_service._save_message", return_value=1), \
             patch("backend.services.memory_injection_service.inject_memory", return_value={}), \
             patch("backend.services.domain_classifier_service.get_domain_context", return_value={}), \
             patch("backend.services.chat_prompt_service.build_messages",
                   return_value=[{"role": "user", "content": message}]), \
             patch("backend.llm.chat_router.classify_message",
                   return_value=None if decision is None else RoutingDecision(**decision)), \
             patch("backend.services.web_search_reasoning_service.run_chat_search",
                   return_value=search), \
             patch("backend.services.follow_up_service.get_recommendations",
                   return_value={"based_on_topic": None, "source": "empty",
                                 "next_topics": [], "prerequisites": [], "advanced_topics": []}), \
             patch("backend.llm.chat_agent.ask_chat_stream", side_effect=fake_ask_chat_stream):
            for line in chat_stream("sess", message, chat_mode=chat_mode):
                if line.strip():
                    events.append(json.loads(line))
        return events, next(e for e in events if e["t"] == "done")

    _NO_SEARCH = dict(needs_web_search=False, search_query="", complexity="simple",
                      needs_code_execution=False, wants_simple_explanation=False, crisis=False)

    def test_classifier_search_marks_the_turn_as_web_search(self):
        events, done = self._run("who won yesterday", "normal",
                                 {**self._NO_SEARCH, "needs_web_search": True, "search_query": "q"})
        assert done["chat_mode"] == "web_search"
        assert done["auto_mode"] is True
        assert done["sources"] == [{"title": "T", "url": "https://example.com"}]
        statuses = [e["v"] for e in events if e["t"] == "status"]
        assert "Searching the web…" in statuses

    def test_toggle_searches_even_when_the_classifier_would_not(self):
        _, done = self._run("explain attention", "web_search", self._NO_SEARCH)
        assert done["chat_mode"] == "web_search"
        assert done["auto_mode"] is False, "the user asked for it, so it is not automatic"

    def test_plain_turn_runs_no_search(self):
        events, done = self._run("what is attention?", "normal", self._NO_SEARCH)
        assert done["chat_mode"] == "normal" and done["sources"] == []
        assert not [e for e in events if e["t"] == "status" and e.get("tool")]

    def test_simple_tone_turn_reports_layman(self):
        _, done = self._run("eli5 attention", "layman", self._NO_SEARCH)
        assert done["chat_mode"] == "layman"

    def test_classifier_failure_still_answers(self):
        _, done = self._run("hello", "normal", None)
        assert done["chat_mode"] == "normal"

    def test_text_only_turn_with_image_in_history_routes_to_image(self):
        # M10: a live "media" part still sits in recent history within 48h of
        # an image turn. If routing missed that, this turn would land on the
        # "simple" list, whose first model is Groq — Groq 400s on media parts.
        history_with_image = [
            {"role": "user", "content": [
                {"type": "text", "text": "look at this"},
                {"type": "media", "file_uri": "gs://x", "mime_type": "image/png"},
            ]},
            {"role": "assistant", "content": "It is a red square."},
        ]
        captured = {}

        def fake_ask_chat_stream(messages, *args, **kwargs):
            captured["route"] = kwargs.get("route")
            yield {"type": "text", "text": "answer"}

        from backend.llm.chat_router import RoutingDecision
        from backend.services.chat_service import chat_stream

        with patch("backend.services.chat_service._detect_topic_hint", return_value=None), \
             patch("backend.services.chat_service._load_history_messages", return_value=history_with_image), \
             patch("backend.services.chat_service._save_message", return_value=1), \
             patch("backend.services.memory_injection_service.inject_memory", return_value={}), \
             patch("backend.services.domain_classifier_service.get_domain_context", return_value={}), \
             patch("backend.services.chat_prompt_service.build_messages",
                   return_value=[{"role": "user", "content": "what colour is it?"}]), \
             patch("backend.llm.chat_router.classify_message",
                   return_value=RoutingDecision(**self._NO_SEARCH)) as mock_classify, \
             patch("backend.services.follow_up_service.get_recommendations",
                   return_value={"based_on_topic": None, "source": "empty",
                                 "next_topics": [], "prerequisites": [], "advanced_topics": []}), \
             patch("backend.llm.chat_agent.ask_chat_stream", side_effect=fake_ask_chat_stream):
            for line in chat_stream("sess", "what colour is it?", chat_mode="normal"):
                pass

        assert captured["route"] == "image"
        assert mock_classify.call_args.kwargs["has_image"] is True

    def test_search_block_and_text_do_not_share_a_block_id(self):
        events, _ = self._run("who won yesterday", "normal",
                              {**self._NO_SEARCH, "needs_web_search": True, "search_query": "q"})
        search_ids = {e["block_id"] for e in events if e["t"] == "status" and e.get("tool")}
        chunk_ids = {e["block_id"] for e in events if e["t"] == "chunk"}
        assert len(search_ids) == 1 and search_ids.isdisjoint(chunk_ids)
