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
this differently since Chat-4.1: chat_mode only gates tool availability and
supplies an optional bias hint (chat_agent.resolve_tools_and_hint) — web_search
is a real tool the model calls itself, not a pre-fetch — see
TestResolveToolsAndHint / TestStreamReflectsActualToolUse below.

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


# ─────────────────────────────────────────────────────────────────────────────
# Chat-4.1: resolve_tools_and_hint — pure chat_mode -> (tools_enabled, hint)
# ─────────────────────────────────────────────────────────────────────────────

class TestResolveToolsAndHint:
    """
    chat_agent.resolve_tools_and_hint, the single place chat_mode gets
    translated into tool availability + an optional bias.
    """

    def test_layman_hard_gates_tools(self):
        from backend.llm.chat_agent import resolve_tools_and_hint
        tools_enabled, hint = resolve_tools_and_hint("layman")
        assert tools_enabled is False
        assert hint is None

    def test_normal_has_tools_and_no_hint(self):
        from backend.llm.chat_agent import resolve_tools_and_hint
        tools_enabled, hint = resolve_tools_and_hint("normal")
        assert tools_enabled is True
        assert hint is None

    def test_web_search_has_tools_and_a_hint(self):
        from backend.llm.chat_agent import resolve_tools_and_hint
        tools_enabled, hint = resolve_tools_and_hint("web_search")
        assert tools_enabled is True
        assert hint and "web_search" in hint

    def test_unknown_mode_falls_back_to_tools_no_hint(self):
        from backend.llm.chat_agent import resolve_tools_and_hint
        tools_enabled, hint = resolve_tools_and_hint("turbo_mode")
        assert tools_enabled is True
        assert hint is None


# ─────────────────────────────────────────────────────────────────────────────
# Chat-4.1: chat_stream's chat_mode/auto_mode/sources reflect which tool the
# model actually called, not which mode was pre-selected. The regex
# auto-upgrade is retired — chat_agent.ask_chat_stream (the model's decision)
# is mocked here so the test is fast/deterministic; whether the model
# genuinely chooses to call a tool live is verified separately, not here.
# ─────────────────────────────────────────────────────────────────────────────

class TestStreamReflectsActualToolUse:

    def _collect_done_event(self, message, chat_mode, agent_events):
        from backend.services.chat_service import chat_stream

        def fake_ask_chat_stream(messages, metadata=None, tools_enabled=True, has_attachments=False, task_type=None):
            yield from agent_events

        events = []
        with patch("backend.services.chat_service._detect_topic_hint", return_value=None), \
             patch("backend.services.chat_service._load_history_messages", return_value=[]), \
             patch("backend.services.chat_service._save_message", return_value=1), \
             patch("backend.services.memory_injection_service.inject_memory", return_value={}), \
             patch("backend.services.domain_classifier_service.get_domain_context", return_value={}), \
             patch("backend.services.action_router_service.route", return_value=None), \
             patch("backend.services.chat_prompt_service.build_messages",
                   return_value=[{"role": "user", "content": message}]), \
             patch("backend.services.follow_up_service.get_recommendations",
                   return_value={"based_on_topic": None, "source": "empty",
                                 "next_topics": [], "prerequisites": [], "advanced_topics": []}), \
             patch("backend.llm.chat_agent.ask_chat_stream", side_effect=fake_ask_chat_stream):
            for line in chat_stream("sess", message, chat_mode=chat_mode):
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events, next(e for e in events if e["t"] == "done")

    def test_explicit_web_search_stays_web_search_when_no_tool_called(self):
        # Explicit web_search mode, but the model answers without calling a
        # tool this turn (already answerable) — chat_mode still reports
        # "web_search" (what was requested), auto_mode False (not model-initiated).
        _, done = self._collect_done_event(
            "Research AI manufacturing", "web_search",
            [{"type": "text", "text": "ok"}],
        )
        assert done["chat_mode"] == "web_search"
        assert done["auto_mode"] is False

    def test_normal_mode_model_calls_web_search_marks_auto(self):
        # chat_mode left on "normal", model decides on its own to call
        # web_search — done event surfaces the tool actually used and flags
        # auto_mode True, mirroring the old regex-auto-upgrade UX signal.
        agent_events = [
            {"type": "tool_start", "tool": "web_search"},
            {"type": "tool_end", "tool": "web_search",
             "sources": [{"title": "T", "url": "https://example.com"}]},
            {"type": "text", "text": "Python vs JavaScript..."},
        ]
        events, done = self._collect_done_event("Compare Python vs JavaScript", "normal", agent_events)
        assert done["chat_mode"] == "web_search"
        assert done["auto_mode"] is True
        assert done["sources"] == [{"title": "T", "url": "https://example.com"}]
        statuses = [e["v"] for e in events if e["t"] == "status"]
        assert "Searching the web…" in statuses

    def test_normal_mode_no_tool_called_stays_normal(self):
        _, done = self._collect_done_event(
            "What is attention?", "normal",
            [{"type": "text", "text": "Attention is..."}],
        )
        assert done["chat_mode"] == "normal"
        assert done["auto_mode"] is False
        assert done["sources"] == []
