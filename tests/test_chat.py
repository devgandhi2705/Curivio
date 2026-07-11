"""
Tests for the conversational AI chat system.

Test classes
------------
1.  TestChatContextService     — build_user_profile_context, build_research_context,
                                 build_session_context, build_full_context
2.  TestChatPromptService      — build_system_prompt, build_messages, truncation
3.  TestChatServiceStorage     — get_history, clear_history, list_sessions
4.  TestChatServiceEdgeCases   — _load_history_messages / _save_message directly
5.  TestTopicHintDetection     — _detect_topic_hint with mocked DB
6.  TestChatEndpoints          — GET history, DELETE history, GET sessions

Patching rules
--------------
- Service tests patch backend.services.chat_service.get_connection and related
  service functions directly.
- Endpoint tests patch backend.main.get_chat_history / etc. so TestClient's
  thread is isolated from the DB.

chat()/chat_with_ai (sync /chat, POST /chat, ask_grok_chat) retired — see
their removal notes in chat_service.py / grok_service.py / main.py. Tests
that existed purely to exercise that path were removed with it.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.database.schema import ALL_TABLES
from backend.services.chat_service import (
    _detect_topic_hint,
    _load_history_messages,
    _save_message,
    clear_history,
    get_history,
    list_sessions,
)
from backend.services.chat_prompt_service import (
    MAX_HISTORY_TURNS,
    build_messages,
    build_system_prompt,
)
from backend.services.chat_context_service import (
    build_full_context,
    build_research_context,
    build_session_context,
    build_user_profile_context,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Shared fixtures
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def mem_db(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    for stmt in ALL_TABLES:
        conn.execute(stmt)
    conn.commit()

    @contextmanager
    def _get_conn():
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    monkeypatch.setattr("backend.services.chat_service.get_connection", _get_conn)
    # list_sessions() delegates to chat_title_service.list_sessions_with_titles(),
    # which does a fresh `from ..utils.db import get_connection` at call time —
    # patching chat_service's own already-bound name doesn't reach it, so the
    # true source (backend.utils.db.get_connection) needs patching too.
    monkeypatch.setattr("backend.utils.db.get_connection", _get_conn)
    return conn


def _insert_message(conn, session_id, role, content, topic_hint=None, created_at=None):
    ts = created_at or "2025-01-01 10:00:00"
    conn.execute(
        "INSERT INTO chat_messages (session_id, role, content, topic_hint, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (session_id, role, content, topic_hint, ts),
    )
    conn.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. ChatContextService
# ═══════════════════════════════════════════════════════════════════════════════

class TestChatContextService:

    def test_build_user_profile_context_returns_expected_keys(self):
        with (
            patch("backend.services.recommendation_service.get_top_user_interests",
                  return_value=[{"topic": "RAG Pipelines"}]),
            patch("backend.services.recommendation_service.get_suppressed_topics", return_value=[]),
            patch("backend.services.recommendation_service.get_overall_difficulty_preference", return_value="intermediate"),
            patch("backend.services.recommendation_service.get_learning_stage", return_value="intermediate"),
        ):
            result = build_user_profile_context()
        assert result["learning_stage"] == "intermediate"
        assert result["top_interests"] == ["RAG Pipelines"]
        assert result["suppressed_topics"] == []

    def test_build_user_profile_context_suppressed_topics_are_strings(self):
        # get_suppressed_topics() returns list[str] (topic names already
        # extracted), unlike get_top_user_interests()'s list[dict] — a real
        # suppressed topic used to raise TypeError here and silently wipe the
        # whole profile (top_interests included) via the except-all below.
        with (
            patch("backend.services.recommendation_service.get_top_user_interests",
                  return_value=[{"topic": "RAG Pipelines"}]),
            patch("backend.services.recommendation_service.get_suppressed_topics",
                  return_value=["Crypto Trading"]),
            patch("backend.services.recommendation_service.get_overall_difficulty_preference", return_value=None),
            patch("backend.services.recommendation_service.get_learning_stage", return_value="beginner"),
        ):
            result = build_user_profile_context()
        assert result["suppressed_topics"] == ["Crypto Trading"]
        assert result["top_interests"] == ["RAG Pipelines"]  # profile must not collapse to defaults

    def test_build_user_profile_context_graceful_on_error(self):
        with (
            patch("backend.services.recommendation_service.get_top_user_interests", side_effect=RuntimeError("db error")),
            patch("backend.services.recommendation_service.get_suppressed_topics", return_value=[]),
            patch("backend.services.recommendation_service.get_overall_difficulty_preference", return_value=None),
            patch("backend.services.recommendation_service.get_learning_stage", return_value="beginner"),
        ):
            result = build_user_profile_context()
        assert result["learning_stage"] == "beginner"
        assert result["top_interests"] == []

    def test_build_research_context_none_topic(self):
        result = build_research_context(None)
        assert result["topic"] is None
        assert result["has_deep_research"] is False
        assert result["deep_research"] is None

    def test_build_research_context_empty_topic(self):
        result = build_research_context("   ")
        assert result["topic"] is None

    def test_build_research_context_with_stored_data(self):
        deep = {"summary": "RAG overview", "key_concepts": ["chunking", "embedding"]}
        with (
            patch("backend.services.deep_research_service.get_stored_research", return_value=json.dumps(deep)),
            patch("backend.services.learning_path_service.get_stored_path", return_value=None),
            patch("backend.services.topic_expansion_service.get_stored_expansion", return_value=None),
            patch("backend.services.github_service._get_stored_repos", return_value=None),
        ):
            result = build_research_context("RAG Pipelines")
        assert result["has_deep_research"] is True
        assert result["deep_research"]["summary"] == "RAG overview"
        assert result["has_learning_path"] is False

    def test_build_research_context_no_stored_data(self):
        with (
            patch("backend.services.deep_research_service.get_stored_research", return_value=None),
            patch("backend.services.learning_path_service.get_stored_path", return_value=None),
            patch("backend.services.topic_expansion_service.get_stored_expansion", return_value=None),
            patch("backend.services.github_service._get_stored_repos", return_value=None),
        ):
            result = build_research_context("Unknown Topic")
        assert result["has_deep_research"] is False
        assert result["has_learning_path"] is False
        assert result["has_github_repos"] is False

    def test_build_session_context_none_topic(self):
        result = build_session_context(None)
        assert result["topic"] is None
        assert result["times_explored"] == 0

    def test_build_session_context_with_memory(self):
        memory = {
            "topic": "RAG Pipelines",
            "times_explored": 3,
            "has_deep_research": True,
            "has_learning_path": True,
            "has_topic_expansion": False,
            "has_github_repos": True,
            "last_activity_at": "2025-01-01 10:00:00",
            "recommended_next": ["topic_expansion"],
            "first_explored_at": "2024-12-01",
        }
        with patch("backend.services.session_memory_service.get_research_context", return_value=memory):
            result = build_session_context("RAG Pipelines")
        assert result["times_explored"] == 3
        assert result["has_deep_research"] is True
        assert "first_explored_at" not in result  # only selected keys

    def test_build_session_context_graceful_on_error(self):
        with patch("backend.services.session_memory_service.get_research_context", side_effect=RuntimeError):
            result = build_session_context("SomeTopic")
        assert result["times_explored"] == 0
        assert result["topic"] == "SomeTopic"

    def test_build_full_context_structure(self):
        profile  = {"learning_stage": "beginner", "difficulty_preference": None, "top_interests": [], "suppressed_topics": []}
        research = {"topic": None, "has_deep_research": False, "has_learning_path": False, "has_topic_expansion": False, "has_github_repos": False, "deep_research": None, "learning_path": None, "topic_expansion": None, "github_repos": None}
        session  = {"topic": None, "times_explored": 0, "has_deep_research": False, "has_learning_path": False, "has_topic_expansion": False, "has_github_repos": False, "last_activity_at": None, "recommended_next": []}
        with (
            patch("backend.services.chat_context_service.build_user_profile_context", return_value=profile),
            patch("backend.services.chat_context_service.build_research_context", return_value=research),
            patch("backend.services.chat_context_service.build_session_context", return_value=session),
        ):
            result = build_full_context(None)
        assert "user_profile" in result
        assert "research" in result
        assert "session" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ChatPromptService
# ═══════════════════════════════════════════════════════════════════════════════

class TestChatPromptService:

    def _empty_context(self):
        return {
            "user_profile": {
                "learning_stage": "beginner",
                "difficulty_preference": None,
                "top_interests": [],
                "suppressed_topics": [],
            },
            "research": {
                "topic": None,
                "has_deep_research": False,
                "has_learning_path": False,
                "has_topic_expansion": False,
                "has_github_repos": False,
                "deep_research": None,
                "learning_path": None,
                "topic_expansion": None,
                "github_repos": None,
            },
            "session": {
                "topic": None,
                "times_explored": 0,
                "has_deep_research": False,
                "has_learning_path": False,
                "has_topic_expansion": False,
                "has_github_repos": False,
                "last_activity_at": None,
                "recommended_next": [],
            },
        }

    def test_build_system_prompt_returns_string(self):
        prompt = build_system_prompt(self._empty_context())
        assert isinstance(prompt, str)
        assert len(prompt) > 50

    def test_build_system_prompt_includes_persona(self):
        prompt = build_system_prompt(self._empty_context())
        assert "research" in prompt.lower() or "mentor" in prompt.lower() or "learning" in prompt.lower()

    def test_build_system_prompt_includes_interests(self):
        ctx = self._empty_context()
        ctx["user_profile"]["top_interests"] = ["RAG Pipelines", "LoRA"]
        prompt = build_system_prompt(ctx)
        assert "RAG Pipelines" in prompt

    def test_build_system_prompt_includes_research_summary(self):
        # research/session dumps only render in structured modes (web_search/
        # deep_research/...) — "normal" (the default) is deliberately minimal,
        # see build_system_prompt's docstring.
        ctx = self._empty_context()
        ctx["research"]["topic"] = "RAG Pipelines"
        ctx["research"]["has_deep_research"] = True
        ctx["research"]["deep_research"] = {"summary": "RAG is about retrieval augmented generation"}
        prompt = build_system_prompt(ctx, mode="deep_research")
        assert "RAG" in prompt

    def test_build_system_prompt_includes_session_memory(self):
        ctx = self._empty_context()
        ctx["session"] = {
            "topic": "LoRA",
            "times_explored": 2,
            "has_deep_research": True,
            "has_learning_path": False,
            "has_topic_expansion": False,
            "has_github_repos": False,
            "last_activity_at": "2025-01-01",
            "recommended_next": [],
        }
        prompt = build_system_prompt(ctx, mode="deep_research")
        assert "LoRA" in prompt
        assert "2" in prompt  # times_explored

    def test_build_messages_includes_system_and_user(self):
        ctx = self._empty_context()
        messages = build_messages([], "Hello there", ctx)
        assert messages[0]["role"] == "system"
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "Hello there"

    def test_build_messages_truncates_history(self):
        # 20 turns = 40 messages; MAX_HISTORY_TURNS * 2 = 12 should be kept
        history = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
            for i in range(40)
        ]
        ctx = self._empty_context()
        messages = build_messages(history, "new message", ctx)
        # system + MAX_HISTORY_TURNS*2 history messages + 1 user
        expected_history_count = MAX_HISTORY_TURNS * 2
        assert len(messages) == 1 + expected_history_count + 1

    def test_build_messages_short_history_not_truncated(self):
        history = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
        ]
        ctx = self._empty_context()
        messages = build_messages(history, "second", ctx)
        assert len(messages) == 4  # system + 2 history + user

    def test_build_messages_empty_history(self):
        ctx = self._empty_context()
        messages = build_messages([], "first message", ctx)
        assert len(messages) == 2  # system + user


# ═══════════════════════════════════════════════════════════════════════════════
# 3. ChatServiceStorage
# ═══════════════════════════════════════════════════════════════════════════════

class TestChatServiceStorage:

    def test_get_history_empty(self, mem_db):
        result = get_history("nonexistent", limit=10)
        assert result == []

    def test_get_history_returns_messages_oldest_first(self, mem_db):
        _insert_message(mem_db, "s1", "user",      "hello",   created_at="2025-01-01 09:00:00")
        _insert_message(mem_db, "s1", "assistant", "hi back", created_at="2025-01-01 09:01:00")
        result = get_history("s1")
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"

    def test_get_history_respects_limit(self, mem_db):
        for i in range(10):
            _insert_message(mem_db, "s1", "user", f"msg {i}", created_at=f"2025-01-0{i+1} 10:00:00")
        result = get_history("s1", limit=3)
        assert len(result) == 3

    def test_get_history_isolates_sessions(self, mem_db):
        _insert_message(mem_db, "s1", "user", "s1 message")
        _insert_message(mem_db, "s2", "user", "s2 message")
        assert len(get_history("s1")) == 1
        assert len(get_history("s2")) == 1

    def test_get_history_includes_topic_hint(self, mem_db):
        _insert_message(mem_db, "s1", "user", "question", topic_hint="RAG")
        result = get_history("s1")
        assert result[0]["topic_hint"] == "RAG"

    def test_clear_history_returns_count(self, mem_db):
        _insert_message(mem_db, "s1", "user",      "hello")
        _insert_message(mem_db, "s1", "assistant", "hi")
        deleted = clear_history("s1")
        assert deleted == 2

    def test_clear_history_empty_session_returns_zero(self, mem_db):
        assert clear_history("empty_session") == 0

    def test_clear_history_only_affects_target_session(self, mem_db):
        _insert_message(mem_db, "s1", "user", "keep me")
        _insert_message(mem_db, "s2", "user", "delete me")
        clear_history("s2")
        assert len(get_history("s1")) == 1
        assert len(get_history("s2")) == 0

    def test_list_sessions_empty(self, mem_db):
        assert list_sessions() == []

    def test_list_sessions_returns_summary(self, mem_db):
        # message_count counts user turns, not raw rows (1 user + 1 assistant
        # = 1 turn) — confirmed intentional: the frontend independently computes
        # the same thing via Math.floor(history.length / 2) and a +1-per-turn
        # increment (ChatWorkspace.jsx), matching this SQL's user-only COUNT.
        _insert_message(mem_db, "s1", "user",      "hi",    topic_hint="RAG", created_at="2025-01-01 10:00:00")
        _insert_message(mem_db, "s1", "assistant", "hello",                   created_at="2025-01-01 10:01:00")
        result = list_sessions()
        assert len(result) == 1
        assert result[0]["session_id"] == "s1"
        assert result[0]["message_count"] == 1

    def test_list_sessions_ordered_by_last_active(self, mem_db):
        _insert_message(mem_db, "older", "user", "old", created_at="2025-01-01 10:00:00")
        _insert_message(mem_db, "newer", "user", "new", created_at="2025-01-02 10:00:00")
        result = list_sessions()
        assert result[0]["session_id"] == "newer"

    def test_list_sessions_respects_limit(self, mem_db):
        for i in range(5):
            _insert_message(mem_db, f"s{i}", "user", "hi")
        result = list_sessions(limit=3)
        assert len(result) == 3


# ═══════════════════════════════════════════════════════════════════════════════
# 4. ChatServiceEdgeCases
# ═══════════════════════════════════════════════════════════════════════════════

class TestChatServiceEdgeCases:

    def test_load_history_messages_returns_openai_format(self, mem_db):
        _insert_message(mem_db, "s1", "user",      "hello", created_at="2025-01-01 10:00:00")
        _insert_message(mem_db, "s1", "assistant", "hi",    created_at="2025-01-01 10:01:00")
        msgs = _load_history_messages("s1", limit=10)
        assert all("role" in m and "content" in m for m in msgs)
        assert msgs[0]["role"] == "user"

    def test_save_message_returns_row_id(self, mem_db):
        row_id = _save_message("s1", "user", "hi", None, "2025-01-01 10:00:00")
        assert isinstance(row_id, int)
        assert row_id > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 5. TopicHintDetection
# ═══════════════════════════════════════════════════════════════════════════════

class TestTopicHintDetection:

    def test_detect_known_topic_in_message(self, mem_db):
        mem_db.execute(
            "INSERT INTO user_preferences (topic, preference_score) VALUES (?, ?)",
            ("RAG Pipelines", 1.5),
        )
        mem_db.commit()

        with patch("backend.services.chat_service.get_connection") as mock_gc:
            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn.execute.return_value.fetchall.return_value = [
                type("Row", (), {"__getitem__": lambda self, k: "RAG Pipelines"})()
            ]
            mock_gc.return_value = mock_conn

            result = _detect_topic_hint("I want to learn about RAG Pipelines")
        assert result == "RAG Pipelines"

    def test_detect_returns_none_when_no_match(self):
        with patch("backend.services.chat_service.get_connection") as mock_gc:
            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_gc.return_value = mock_conn

            result = _detect_topic_hint("general question about AI")
        assert result is None

    def test_detect_graceful_on_db_error(self):
        with patch("backend.services.chat_service.get_connection", side_effect=RuntimeError("db down")):
            result = _detect_topic_hint("anything")
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# 6. ChatEndpoints
# ═══════════════════════════════════════════════════════════════════════════════

class TestChatEndpoints:

    @pytest.fixture
    def client(self):
        # These endpoints require Depends(get_current_user) (real, intentional —
        # part of the multi-user auth system). The service layer below it is
        # already fully mocked per-test, so a dependency override is the
        # DB-independent way to authenticate here, rather than minting a real
        # JWT against a real user row.
        from fastapi.testclient import TestClient
        from backend.main import app, get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "test-user", "email": "test@example.com"}
        try:
            yield TestClient(app, raise_server_exceptions=False)
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    def test_get_chat_history_returns_200(self, client):
        with patch("backend.main.get_chat_history", return_value=[
            {"id": 1, "session_id": "s1", "role": "user", "content": "hi", "topic_hint": None, "created_at": "2025-01-01"}
        ]):
            resp = client.get("/chat/history/s1")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_chat_history_empty(self, client):
        with patch("backend.main.get_chat_history", return_value=[]):
            resp = client.get("/chat/history/no-session")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_delete_chat_history_returns_200(self, client):
        with patch("backend.main.clear_chat_history", return_value=4):
            resp = client.delete("/chat/history/s1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["deleted_count"] == 4
        assert body["session_id"] == "s1"

    def test_get_sessions_returns_200(self, client):
        with patch("backend.main.list_chat_sessions", return_value=[
            {"session_id": "s1", "message_count": 4, "last_active_at": "2025-01-01", "first_topic_hint": "RAG"}
        ]):
            resp = client.get("/chat/sessions")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_sessions_empty(self, client):
        with patch("backend.main.list_chat_sessions", return_value=[]):
            resp = client.get("/chat/sessions")
        assert resp.status_code == 200
        assert resp.json() == []

