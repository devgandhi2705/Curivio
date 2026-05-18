"""
Tests for chat_modes_service — mode-specific context preparation.

Covers
------
- prepare_mode_context: normal, web_search, deep_research
- prepare_mode_context: graceful failure when retrieval errors
- prepare_mode_context: unknown mode falls back to {}
- build_mode_system_note: each mode variant
- stream_status_event: correct events for each mode

TESTING RULES
-------------
- Tavily is always mocked — no real API calls
- Deep research is always mocked — no real network calls
"""

import pytest
from unittest.mock import patch, MagicMock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MOCK_ARTICLES = [
    {"title": "Article One", "url": "https://example.com/1", "content": "Content of article one about AI systems."},
    {"title": "Article Two", "url": "https://example.com/2", "content": "Content of article two about neural nets."},
]

MOCK_RESEARCH = {
    "topic":            "Transformers",
    "research_summary": "Transformers use self-attention for parallel sequence processing.",
    "key_findings": [
        "Self-attention scales better than RNNs.",
        "Scaling laws predict capability improvements.",
        "Inference cost is the main production barrier.",
    ],
    "viewpoints": [
        {"angle": "Practitioner",  "summary": "Fast to deploy with HuggingFace."},
        {"angle": "Researcher",    "summary": "Theoretical limits not yet understood."},
    ],
    "confidence_level": "high",
}


# ---------------------------------------------------------------------------
# prepare_mode_context
# ---------------------------------------------------------------------------

class TestPrepareModeContextNormal:
    def test_returns_empty_dict(self):
        from backend.services.chat_modes_service import prepare_mode_context
        result = prepare_mode_context("normal", "What is AI?", None)
        assert result == {}

    def test_returns_empty_dict_with_topic(self):
        from backend.services.chat_modes_service import prepare_mode_context
        result = prepare_mode_context("normal", "Tell me about transformers", "Transformers")
        assert result == {}


class TestPrepareModeContextWebSearch:
    def test_calls_tavily_and_returns_articles(self):
        from backend.services.chat_modes_service import prepare_mode_context
        with patch("backend.services.chat_modes_service._fetch_web_context") as mock_fetch:
            mock_fetch.return_value = {"mode": "web_search", "web_search_results": MOCK_ARTICLES}
            result = prepare_mode_context("web_search", "Latest AI news", None)

        assert result["mode"] == "web_search"
        assert result["web_search_results"] == MOCK_ARTICLES
        mock_fetch.assert_called_once()

    def test_uses_topic_as_query_when_provided(self):
        from backend.services.chat_modes_service import _fetch_web_context
        with patch("backend.services.tavily_service.search_articles") as mock_search:
            mock_search.return_value = MOCK_ARTICLES
            with patch("backend.services.chat_modes_service.logger"):
                result = _fetch_web_context("tell me about it", "Transformers")

        mock_search.assert_called_once_with("Transformers")
        assert result["web_search_results"] == MOCK_ARTICLES

    def test_uses_message_when_no_topic(self):
        from backend.services.chat_modes_service import _fetch_web_context
        with patch("backend.services.tavily_service.search_articles") as mock_search:
            mock_search.return_value = MOCK_ARTICLES
            result = _fetch_web_context("What is attention mechanism?", None)

        mock_search.assert_called_once_with("What is attention mechanism?")

    def test_returns_empty_list_on_tavily_error(self):
        from backend.services.chat_modes_service import _fetch_web_context
        with patch("backend.services.tavily_service.search_articles", side_effect=RuntimeError("API error")):
            result = _fetch_web_context("query", "topic")

        assert result["mode"] == "web_search"
        assert result["web_search_results"] == []

    def test_truncates_long_message_query(self):
        from backend.services.chat_modes_service import _fetch_web_context
        long_message = "x" * 300
        with patch("backend.services.tavily_service.search_articles") as mock_search:
            mock_search.return_value = []
            _fetch_web_context(long_message, None)

        called_query = mock_search.call_args[0][0]
        assert len(called_query) <= 200


class TestPrepareModeContextDeepResearch:
    def test_calls_deep_research_and_returns_result(self):
        from backend.services.chat_modes_service import prepare_mode_context
        with patch("backend.services.chat_modes_service._fetch_deep_research_context") as mock_fetch:
            mock_fetch.return_value = {"mode": "deep_research", "deep_research_result": MOCK_RESEARCH}
            result = prepare_mode_context("deep_research", "Research transformers", "Transformers")

        assert result["mode"] == "deep_research"
        assert result["deep_research_result"] == MOCK_RESEARCH
        mock_fetch.assert_called_once()

    def test_uses_topic_as_query(self):
        from backend.services.chat_modes_service import _fetch_deep_research_context
        with patch("backend.services.deep_research_service.run_deep_research") as mock_dr:
            mock_dr.return_value = MOCK_RESEARCH
            result = _fetch_deep_research_context("tell me about it", "Transformers")

        mock_dr.assert_called_once_with("Transformers")
        assert result["deep_research_result"] == MOCK_RESEARCH

    def test_returns_none_result_on_error(self):
        from backend.services.chat_modes_service import _fetch_deep_research_context
        with patch("backend.services.deep_research_service.run_deep_research", side_effect=Exception("failed")):
            result = _fetch_deep_research_context("query", "topic")

        assert result["mode"] == "deep_research"
        assert result["deep_research_result"] is None


class TestPrepareModeContextUnknownMode:
    def test_unknown_mode_returns_empty_dict(self):
        from backend.services.chat_modes_service import prepare_mode_context
        result = prepare_mode_context("turbo_mode", "query", None)
        assert result == {}

    def test_empty_string_mode_returns_empty_dict(self):
        from backend.services.chat_modes_service import prepare_mode_context
        result = prepare_mode_context("", "query", None)
        assert result == {}


# ---------------------------------------------------------------------------
# build_mode_system_note
# ---------------------------------------------------------------------------

class TestBuildModeSystemNoteNormal:
    def test_returns_empty_string_for_normal_mode(self):
        from backend.services.chat_modes_service import build_mode_system_note
        result = build_mode_system_note({})
        assert result == ""

    def test_returns_empty_string_when_mode_key_absent(self):
        from backend.services.chat_modes_service import build_mode_system_note
        result = build_mode_system_note({"other_key": "value"})
        assert result == ""


class TestBuildModeSystemNoteWebSearch:
    def test_renders_article_titles_and_snippets(self):
        from backend.services.chat_modes_service import build_mode_system_note
        ctx = {"mode": "web_search", "web_search_results": MOCK_ARTICLES}
        note = build_mode_system_note(ctx)
        assert "WEB SEARCH" in note
        assert "Article One" in note
        assert "Article Two" in note

    def test_includes_urls(self):
        from backend.services.chat_modes_service import build_mode_system_note
        ctx = {"mode": "web_search", "web_search_results": MOCK_ARTICLES}
        note = build_mode_system_note(ctx)
        assert "example.com" in note

    def test_empty_articles_gives_no_results_message(self):
        from backend.services.chat_modes_service import build_mode_system_note
        ctx = {"mode": "web_search", "web_search_results": []}
        note = build_mode_system_note(ctx)
        assert "No results" in note

    def test_limits_to_max_articles(self):
        from backend.services.chat_modes_service import build_mode_system_note, _WEB_SEARCH_MAX_ARTICLES
        many_articles = [
            {"title": f"Article {i}", "url": f"https://x.com/{i}", "content": "text"}
            for i in range(10)
        ]
        ctx = {"mode": "web_search", "web_search_results": many_articles}
        note = build_mode_system_note(ctx)
        # Count bullet points
        bullet_count = note.count("•")
        assert bullet_count <= _WEB_SEARCH_MAX_ARTICLES

    def test_content_is_truncated_in_snippet(self):
        from backend.services.chat_modes_service import build_mode_system_note
        long_article = {"title": "Long", "url": "https://x.com", "content": "A" * 500}
        ctx = {"mode": "web_search", "web_search_results": [long_article]}
        note = build_mode_system_note(ctx)
        # Full 500-char content should not appear verbatim
        assert "A" * 400 not in note


class TestBuildModeSystemNoteDeepResearch:
    def test_renders_topic_and_summary(self):
        from backend.services.chat_modes_service import build_mode_system_note
        ctx = {"mode": "deep_research", "deep_research_result": MOCK_RESEARCH}
        note = build_mode_system_note(ctx)
        assert "Transformers" in note
        assert "self-attention" in note.lower() or "parallel" in note.lower()

    def test_renders_key_findings(self):
        from backend.services.chat_modes_service import build_mode_system_note
        ctx = {"mode": "deep_research", "deep_research_result": MOCK_RESEARCH}
        note = build_mode_system_note(ctx)
        assert "Self-attention" in note or "Scaling laws" in note

    def test_renders_viewpoints(self):
        from backend.services.chat_modes_service import build_mode_system_note
        ctx = {"mode": "deep_research", "deep_research_result": MOCK_RESEARCH}
        note = build_mode_system_note(ctx)
        assert "Practitioner" in note or "Researcher" in note

    def test_none_result_gives_no_data_message(self):
        from backend.services.chat_modes_service import build_mode_system_note
        ctx = {"mode": "deep_research", "deep_research_result": None}
        note = build_mode_system_note(ctx)
        assert "No research data" in note

    def test_missing_result_key_gives_no_data_message(self):
        from backend.services.chat_modes_service import build_mode_system_note
        ctx = {"mode": "deep_research"}
        note = build_mode_system_note(ctx)
        assert "No research data" in note

    def test_summary_is_truncated(self):
        from backend.services.chat_modes_service import build_mode_system_note, _DEEP_RESEARCH_SUMMARY_LEN
        long_research = {**MOCK_RESEARCH, "research_summary": "S" * 1000}
        ctx = {"mode": "deep_research", "deep_research_result": long_research}
        note = build_mode_system_note(ctx)
        assert "S" * 700 not in note  # definitely truncated beyond _DEEP_RESEARCH_SUMMARY_LEN

    def test_uses_executive_summary_fallback(self):
        from backend.services.chat_modes_service import build_mode_system_note
        research_without_summary = {
            "topic":             "RAG",
            "executive_summary": "RAG combines retrieval with generation.",
            "key_findings":      [],
        }
        ctx = {"mode": "deep_research", "deep_research_result": research_without_summary}
        note = build_mode_system_note(ctx)
        assert "RAG" in note
        assert "retrieval" in note.lower() or "combines" in note.lower()


# ---------------------------------------------------------------------------
# stream_status_event
# ---------------------------------------------------------------------------

class TestStreamStatusEvent:
    def test_normal_mode_returns_none(self):
        from backend.services.chat_modes_service import stream_status_event
        assert stream_status_event("normal") is None

    def test_web_search_returns_ndjson_line(self):
        import json
        from backend.services.chat_modes_service import stream_status_event
        line = stream_status_event("web_search")
        assert line is not None
        assert line.endswith("\n")
        obj = json.loads(line.strip())
        assert obj["t"] == "status"
        assert "search" in obj["v"].lower() or "web" in obj["v"].lower()

    def test_deep_research_returns_ndjson_line(self):
        import json
        from backend.services.chat_modes_service import stream_status_event
        line = stream_status_event("deep_research")
        assert line is not None
        assert line.endswith("\n")
        obj = json.loads(line.strip())
        assert obj["t"] == "status"
        assert "research" in obj["v"].lower()

    def test_unknown_mode_returns_none(self):
        from backend.services.chat_modes_service import stream_status_event
        assert stream_status_event("turbo") is None


# ---------------------------------------------------------------------------
# VALID_MODES constant
# ---------------------------------------------------------------------------

class TestValidModes:
    def test_all_three_modes_present(self):
        from backend.services.chat_modes_service import VALID_MODES
        assert "normal"        in VALID_MODES
        assert "web_search"    in VALID_MODES
        assert "deep_research" in VALID_MODES

    def test_no_extra_modes(self):
        from backend.services.chat_modes_service import VALID_MODES
        assert len(VALID_MODES) == 3
