"""
Tests for chat_title_service — pure helpers and DB operations.

TESTING RULES
─────────────
- Pure helpers (extract_title, strip_title_prefix, advance_stream_state) need no mocks.
- DB operations use mocked get_connection.
- No live AI calls.
"""

import pytest
from unittest.mock import patch, MagicMock

from backend.services.chat_title_service import (
    extract_title,
    strip_title_prefix,
    make_title_system_note,
    stream_extract_state,
    advance_stream_state,
)


# ─────────────────────────────────────────────────────────────────────────────
# extract_title
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractTitle:
    def test_basic_extraction(self):
        assert extract_title("[TITLE: AI in Manufacturing]") == "AI in Manufacturing"

    def test_with_surrounding_text(self):
        text = "[TITLE: Deep Learning Basics]\nHere is my answer..."
        assert extract_title(text) == "Deep Learning Basics"

    def test_strips_whitespace(self):
        assert extract_title("[TITLE:   Quantum Computing Overview   ]") == "Quantum Computing Overview"

    def test_returns_none_when_absent(self):
        assert extract_title("Just a normal response with no title") is None

    def test_truncates_long_title(self):
        long_title = "A" * 100
        result = extract_title(f"[TITLE: {long_title}]")
        assert len(result) == 80

    def test_empty_title_returns_none(self):
        assert extract_title("[TITLE: ]") is None
        assert extract_title("[TITLE:   ]") is None

    def test_case_sensitive_marker(self):
        # Must be uppercase TITLE
        assert extract_title("[title: lowercase]") is None

    def test_multiword_title(self):
        result = extract_title("[TITLE: Semiconductor Supply Chain Analysis]")
        assert result == "Semiconductor Supply Chain Analysis"


# ─────────────────────────────────────────────────────────────────────────────
# strip_title_prefix
# ─────────────────────────────────────────────────────────────────────────────

class TestStripTitlePrefix:
    def test_removes_title_line(self):
        text = "[TITLE: AI Overview]\nThis is the actual answer."
        assert strip_title_prefix(text) == "This is the actual answer."

    def test_removes_leading_newlines(self):
        text = "[TITLE: Topic]\n\n\nAnswer starts here."
        assert strip_title_prefix(text) == "Answer starts here."

    def test_no_title_unchanged(self):
        text = "Just a normal response."
        assert strip_title_prefix(text) == "Just a normal response."

    def test_title_mid_text_removed(self):
        # Regex replaces wherever it appears
        text = "Intro [TITLE: Something] rest of text"
        result = strip_title_prefix(text)
        assert "[TITLE:" not in result

    def test_empty_string(self):
        assert strip_title_prefix("") == ""


# ─────────────────────────────────────────────────────────────────────────────
# make_title_system_note
# ─────────────────────────────────────────────────────────────────────────────

class TestMakeTitleSystemNote:
    def test_contains_format_instruction(self):
        note = make_title_system_note()
        assert "[TITLE:" in note

    def test_mentions_first_message(self):
        note = make_title_system_note()
        assert "first message" in note.lower()

    def test_returns_string(self):
        assert isinstance(make_title_system_note(), str)


# ─────────────────────────────────────────────────────────────────────────────
# stream_extract_state / advance_stream_state
# ─────────────────────────────────────────────────────────────────────────────

class TestStreamStateMachine:
    def test_initial_state(self):
        state = stream_extract_state()
        assert state["phase"] == "buffering"
        assert state["buf"] == ""
        assert state["title"] is None

    def test_passthrough_when_no_title_prefix(self):
        state = stream_extract_state()
        result = advance_stream_state(state, "Hello, ")
        # Content doesn't start with [TITLE: — flushed immediately to passthrough
        assert result["phase"] == "passthrough"
        assert result["forward"] == "Hello, "

    def test_title_extracted_and_forwarded(self):
        state = stream_extract_state()
        chunk = "[TITLE: My Topic]\nHere is the answer."
        result = advance_stream_state(state, chunk)
        assert result["title"] == "My Topic"
        assert result["phase"] == "passthrough"
        assert "Here is the answer." in (result["forward"] or "")

    def test_title_strips_from_forward(self):
        state = stream_extract_state()
        chunk = "[TITLE: AI Basics]\nActual content here."
        result = advance_stream_state(state, chunk)
        assert "[TITLE:" not in (result["forward"] or "")

    def test_passthrough_after_title_found(self):
        state = stream_extract_state()
        advance_stream_state(state, "[TITLE: Topic]\nFirst part.")
        result = advance_stream_state(state, " Second part.")
        assert result["forward"] == " Second part."
        assert result["phase"] == "passthrough"
        assert result["title"] is None  # title only reported once

    def test_buffer_flushed_on_limit(self):
        state = stream_extract_state()
        # Feed data that starts with [TITLE: but never closes
        advance_stream_state(state, "[TITLE: unclosed")
        # Feed enough to exceed BUFFER_LIMIT (250 chars)
        big = "x" * 240
        result = advance_stream_state(state, big)
        assert result["phase"] == "passthrough"
        assert result["forward"] is not None

    def test_non_title_prefix_flushed(self):
        state = stream_extract_state()
        # Feed content that doesn't start with [TITLE:
        # After BUFFER_LIMIT is reached it flushes
        big_chunk = "Hello world " * 25  # ~300 chars
        result = advance_stream_state(state, big_chunk)
        assert result["phase"] == "passthrough"
        assert result["forward"] == big_chunk

    def test_multipart_title_across_chunks(self):
        state = stream_extract_state()
        r1 = advance_stream_state(state, "[TITLE: Semicon")
        assert r1["phase"] == "buffering"
        assert r1["forward"] is None
        r2 = advance_stream_state(state, "ductors]\nContent here.")
        assert r2["title"] == "Semiconductors"
        assert r2["phase"] == "passthrough"

    def test_title_with_leading_whitespace(self):
        state = stream_extract_state()
        result = advance_stream_state(state, "  [TITLE: Pharma Trends]\nAnswer.")
        assert result["title"] == "Pharma Trends"

    def test_empty_remainder_yields_none_forward(self):
        state = stream_extract_state()
        result = advance_stream_state(state, "[TITLE: Only Title]")
        # No content after the title
        assert result["forward"] is None
        assert result["title"] == "Only Title"


# ─────────────────────────────────────────────────────────────────────────────
# DB operations — mocked connection
# ─────────────────────────────────────────────────────────────────────────────

def _make_conn(rows=None, rowcount=1):
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = rows[0] if rows else None
    cursor.fetchall.return_value = rows or []
    conn.execute.return_value = cursor
    conn.__enter__ = lambda s: conn
    conn.__exit__ = MagicMock(return_value=False)
    return conn


class TestSaveSessionTitle:
    def test_saves_new_title(self):
        from backend.services.chat_title_service import save_session_title
        conn = _make_conn()
        with patch("backend.utils.db.get_connection", return_value=conn):
            save_session_title("sess-1", "My Cool Title")
        conn.execute.assert_called_once()

    def test_skips_blank_title(self):
        from backend.services.chat_title_service import save_session_title
        conn = _make_conn()
        with patch("backend.utils.db.get_connection", return_value=conn):
            save_session_title("sess-1", "   ")
        conn.execute.assert_not_called()

    def test_skips_empty_title(self):
        from backend.services.chat_title_service import save_session_title
        conn = _make_conn()
        with patch("backend.utils.db.get_connection", return_value=conn):
            save_session_title("sess-1", "")
        conn.execute.assert_not_called()

    def test_silently_ignores_duplicate(self):
        from backend.services.chat_title_service import save_session_title
        conn = _make_conn()
        conn.execute.side_effect = Exception("UNIQUE constraint failed")
        with patch("backend.utils.db.get_connection", return_value=conn):
            save_session_title("sess-1", "Some Title")  # should not raise


class TestRenameSession:
    def test_renames_existing(self):
        from backend.services.chat_title_service import rename_session
        conn = _make_conn()
        with patch("backend.utils.db.get_connection", return_value=conn):
            rename_session("sess-1", "New Name")
        conn.execute.assert_called_once()

    def test_raises_on_blank_title(self):
        from backend.services.chat_title_service import rename_session
        with pytest.raises(ValueError):
            rename_session("sess-1", "")

    def test_raises_on_whitespace_title(self):
        from backend.services.chat_title_service import rename_session
        with pytest.raises(ValueError):
            rename_session("sess-1", "   ")


class TestGetSessionTitle:
    def test_returns_title_when_found(self):
        from backend.services.chat_title_service import get_session_title
        row = MagicMock()
        row.__getitem__ = lambda s, k: "My Title" if k == "title" else None
        conn = _make_conn(rows=[row])
        with patch("backend.utils.db.get_connection", return_value=conn):
            result = get_session_title("sess-1")
        assert result == "My Title"

    def test_returns_none_when_not_found(self):
        from backend.services.chat_title_service import get_session_title
        conn = _make_conn(rows=[])
        with patch("backend.utils.db.get_connection", return_value=conn):
            result = get_session_title("missing-sess")
        assert result is None

    def test_returns_none_on_exception(self):
        from backend.services.chat_title_service import get_session_title
        with patch("backend.utils.db.get_connection", side_effect=Exception("db error")):
            result = get_session_title("sess-1")
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# Stream integration — auto-title only on first message (history empty)
# ─────────────────────────────────────────────────────────────────────────────

class TestAutoTitleIntegration:
    """Verify title extraction wires into chat_stream correctly."""

    def _collect_events(self, message, history, grok_chunks):
        # chat_stream() calls chat_agent.ask_chat_stream() (not
        # grok_service.ask_grok_chat_stream, retired from this path in an
        # earlier phase) — it yields {"type": "text", "text": ...} event dicts,
        # not plain string chunks.
        import json
        from backend.services.chat_service import chat_stream

        def fake_ask_chat_stream(messages, metadata=None, tools_enabled=True, has_attachments=False):
            for chunk in grok_chunks:
                yield {"type": "text", "text": chunk}

        with patch("backend.services.chat_service._detect_topic_hint", return_value=None), \
             patch("backend.services.chat_service._load_history_messages", return_value=history), \
             patch("backend.services.chat_service._save_message", return_value=1), \
             patch("backend.services.memory_injection_service.inject_memory", return_value={}), \
             patch("backend.services.domain_classifier_service.get_domain_context", return_value={}), \
             patch("backend.services.action_router_service.route", return_value=None), \
             patch("backend.services.chat_prompt_service.build_messages",
                   return_value=[{"role": "user", "content": message}]), \
             patch("backend.llm.chat_agent.ask_chat_stream", side_effect=fake_ask_chat_stream), \
             patch("backend.services.follow_up_service.get_recommendations",
                   return_value={"based_on_topic": None, "source": "empty",
                                 "next_topics": [], "prerequisites": [], "advanced_topics": []}), \
             patch("backend.services.chat_title_service.save_session_title"):
            return [
                json.loads(line.strip())
                for line in chat_stream("s1", message)
                if line.strip()
            ]

    def test_title_event_emitted_for_new_session(self):
        chunks = ["[TITLE: AI Basics]\n", "Here is the answer."]
        events = self._collect_events("What is AI?", history=[], grok_chunks=chunks)
        title_events = [e for e in events if e["t"] == "title"]
        assert len(title_events) == 1
        assert title_events[0]["v"] == "AI Basics"

    def test_title_not_in_chunk_events(self):
        chunks = ["[TITLE: My Topic]\n", "Actual response content."]
        events = self._collect_events("Tell me about AI", history=[], grok_chunks=chunks)
        chunk_text = "".join(e["v"] for e in events if e["t"] == "chunk")
        assert "[TITLE:" not in chunk_text

    def test_title_in_done_event(self):
        chunks = ["[TITLE: Pharma Trends]\n", "Here is the answer."]
        events = self._collect_events("Pharma news", history=[], grok_chunks=chunks)
        done = next(e for e in events if e["t"] == "done")
        assert done["title"] == "Pharma Trends"

    def test_no_title_event_for_existing_session(self):
        history = [
            {"role": "user",      "content": "prev question"},
            {"role": "assistant", "content": "prev answer"},
        ]
        chunks = ["[TITLE: Should Not Appear]\n", "Follow-up answer."]
        events = self._collect_events("Follow up", history=history, grok_chunks=chunks)
        title_events = [e for e in events if e["t"] == "title"]
        assert len(title_events) == 0

    def test_title_prefix_not_shown_to_user_on_new_session(self):
        chunks = ["[TITLE: Topic Name]\n", "Content starts here."]
        events = self._collect_events("What is X?", history=[], grok_chunks=chunks)
        chunk_text = "".join(e["v"] for e in events if e["t"] == "chunk")
        assert "Topic Name" not in chunk_text or "[TITLE:" not in chunk_text
