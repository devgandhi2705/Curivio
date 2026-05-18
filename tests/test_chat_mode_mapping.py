"""
Chat mode mapping spec — toggle state machine and backend mode routing.

These tests document the exact semantics the UI toggle logic enforces so
backend behaviour stays consistent with the frontend contract:

  UI state             chatMode sent to API    backend retrieval
  ─────────────────    ──────────────────────   ──────────────────────────────
  both off             "normal"                 none (memory/context only)
  Web Search on        "web_search"             Tavily search, no deep pipeline
  Deep Research on     "deep_research"          Tavily + full research workflow

Toggle rules (mirrors ChatInput.jsx logic):
  - Clicking Web Search when mode is "web_search"     → "normal"
  - Clicking Web Search otherwise                     → "web_search"
  - Clicking Deep Research when mode is "deep_research" → "normal"
  - Clicking Deep Research otherwise                  → "deep_research"
  - Deep Research visually activates both toggles    (deep ⊃ web)
  - Web Search alone does NOT activate deep research

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
    """Mirror of ChatInput toggleWebSearch."""
    return "normal" if current_mode == "web_search" else "web_search"


def toggle_deep_research(current_mode: str) -> str:
    """Mirror of ChatInput toggleDeepResearch."""
    return "normal" if current_mode == "deep_research" else "deep_research"


class TestToggleWebSearch:
    def test_off_to_on(self):
        assert toggle_web_search("normal") == "web_search"

    def test_on_to_off(self):
        assert toggle_web_search("web_search") == "normal"

    def test_from_deep_research_downgrades(self):
        # Clicking Web Search while in deep_research → downgrade to web_search
        assert toggle_web_search("deep_research") == "web_search"


class TestToggleDeepResearch:
    def test_off_to_on(self):
        assert toggle_deep_research("normal") == "deep_research"

    def test_on_to_off(self):
        assert toggle_deep_research("deep_research") == "normal"

    def test_from_web_search_upgrades(self):
        # Clicking Deep Research while in web_search → upgrade to deep_research
        assert toggle_deep_research("web_search") == "deep_research"


class TestVisualToggleState:
    """web_active and deep_active flags (mirrors ChatInput JSX logic)."""

    @staticmethod
    def web_active(mode):  return mode in ("web_search", "deep_research")

    @staticmethod
    def deep_active(mode): return mode == "deep_research"

    def test_normal_both_inactive(self):
        assert not self.web_active("normal")
        assert not self.deep_active("normal")

    def test_web_search_only_web_active(self):
        assert     self.web_active("web_search")
        assert not self.deep_active("web_search")

    def test_deep_research_both_active(self):
        # Deep Research visually activates the Web toggle too (deep ⊃ web)
        assert self.web_active("deep_research")
        assert self.deep_active("deep_research")


class TestModeTransitionGraph:
    """Full toggle interaction sequences."""

    def test_normal_web_normal(self):
        m = "normal"
        m = toggle_web_search(m)
        assert m == "web_search"
        m = toggle_web_search(m)
        assert m == "normal"

    def test_normal_deep_normal(self):
        m = "normal"
        m = toggle_deep_research(m)
        assert m == "deep_research"
        m = toggle_deep_research(m)
        assert m == "normal"

    def test_normal_web_then_deep(self):
        m = "normal"
        m = toggle_web_search(m)
        assert m == "web_search"
        m = toggle_deep_research(m)
        assert m == "deep_research"

    def test_normal_deep_then_web_downgrades(self):
        m = "normal"
        m = toggle_deep_research(m)
        assert m == "deep_research"
        m = toggle_web_search(m)    # Web click while in deep → downgrade
        assert m == "web_search"

    def test_deep_to_off(self):
        m = "deep_research"
        m = toggle_deep_research(m)
        assert m == "normal"


# ─────────────────────────────────────────────────────────────────────────────
# Backend mode routing — chat_modes_service
# ─────────────────────────────────────────────────────────────────────────────

class TestBackendModeRouting:
    """Verify that each chatMode drives the correct retrieval path."""

    MOCK_ARTICLES  = [{"title": "T", "url": "u", "content": "c"}]
    MOCK_RESEARCH  = {"topic": "X", "research_summary": "S", "key_findings": []}

    def test_normal_mode_skips_retrieval(self):
        from backend.services.chat_modes_service import prepare_mode_context
        result = prepare_mode_context("normal", "What is AI?", None)
        assert result == {}

    def test_web_search_calls_tavily(self):
        from backend.services.chat_modes_service import prepare_mode_context
        with patch("backend.services.tavily_service.search_articles",
                   return_value=self.MOCK_ARTICLES) as mock_search:
            result = prepare_mode_context("web_search", "AI news", "AI")
        mock_search.assert_called_once()
        assert result["mode"] == "web_search"
        assert result["web_search_results"] == self.MOCK_ARTICLES

    def test_web_search_does_not_call_deep_research(self):
        from backend.services.chat_modes_service import prepare_mode_context
        with patch("backend.services.tavily_service.search_articles",
                   return_value=self.MOCK_ARTICLES), \
             patch("backend.services.deep_research_service.run_deep_research") as mock_dr:
            prepare_mode_context("web_search", "AI news", "AI")
        mock_dr.assert_not_called()

    def test_deep_research_calls_pipeline(self):
        from backend.services.chat_modes_service import prepare_mode_context
        with patch("backend.services.deep_research_service.run_deep_research",
                   return_value=self.MOCK_RESEARCH) as mock_dr:
            result = prepare_mode_context("deep_research", "Transformers", "Transformers")
        mock_dr.assert_called_once()
        assert result["mode"] == "deep_research"
        assert result["deep_research_result"] == self.MOCK_RESEARCH

    def test_deep_research_does_not_separately_call_tavily(self):
        # The deep research pipeline itself may use Tavily internally,
        # but chat_modes_service should not make an additional separate Tavily call
        from backend.services.chat_modes_service import prepare_mode_context
        with patch("backend.services.deep_research_service.run_deep_research",
                   return_value=self.MOCK_RESEARCH), \
             patch("backend.services.tavily_service.search_articles") as mock_tavily:
            prepare_mode_context("deep_research", "Transformers", "Transformers")
        mock_tavily.assert_not_called()


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

    def test_deep_research_mode_accepted(self):
        req = self._make_request("deep_research")
        assert req.chat_mode == "deep_research"

    def test_invalid_mode_rejected(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self._make_request("turbo_mode")

    def test_default_mode_is_normal(self):
        from backend.main import ChatRequest
        req = ChatRequest(session_id="s", message="m")
        assert req.chat_mode == "normal"


# ─────────────────────────────────────────────────────────────────────────────
# Auto-mode: explicit mode selection prevents auto-upgrade
# ─────────────────────────────────────────────────────────────────────────────

class TestAutoModeDoesNotOverrideExplicit:
    """
    When the user explicitly sets a non-normal mode, the backend must NOT
    auto-detect and override it.
    """

    def _collect_done_event(self, message, chat_mode):
        from backend.services.chat_service import chat_stream
        events = []
        with patch("backend.services.chat_service._detect_topic_hint", return_value=None), \
             patch("backend.services.chat_service._load_history_messages", return_value=[]), \
             patch("backend.services.chat_service._save_message", return_value=1), \
             patch("backend.services.memory_injection_service.inject_memory", return_value={}), \
             patch("backend.services.domain_classifier_service.get_domain_context", return_value={}), \
             patch("backend.services.action_router_service.route", return_value=None), \
             patch("backend.services.chat_prompt_service.build_messages",
                   return_value=[{"role": "user", "content": message}]), \
             patch("backend.services.grok_service.ask_grok_chat_stream",
                   return_value=["ok"]), \
             patch("backend.services.follow_up_service.get_recommendations",
                   return_value={"based_on_topic": None, "source": "empty",
                                 "next_topics": [], "prerequisites": [], "advanced_topics": []}), \
             patch("backend.services.chat_modes_service._fetch_web_context",
                   return_value={"mode": "web_search", "query_type": "default",
                                 "subjects": [], "web_search_results": []}), \
             patch("backend.services.chat_modes_service._fetch_deep_research_context",
                   return_value={"mode": "deep_research", "query_type": "default",
                                 "deep_research_result": None}):
            for line in chat_stream("sess", message, chat_mode=chat_mode):
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return next(e for e in events if e["t"] == "done")

    def test_explicit_web_search_stays_web_search(self):
        # "Research X" would normally trigger deep_research auto-mode,
        # but the user explicitly set web_search → must stay web_search
        done = self._collect_done_event("Research AI manufacturing", "web_search")
        assert done["chat_mode"] == "web_search"
        assert done["auto_mode"] is False

    def test_explicit_normal_with_compare_triggers_auto(self):
        # User on "normal" mode sends a compare message → auto-upgrades to web_search
        done = self._collect_done_event("Compare Python vs JavaScript", "normal")
        assert done["chat_mode"] == "web_search"
        assert done["auto_mode"] is True

    def test_explicit_normal_with_plain_message_stays_normal(self):
        done = self._collect_done_event("What is attention?", "normal")
        assert done["chat_mode"] == "normal"
        assert done["auto_mode"] is False
