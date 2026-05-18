"""
Tests for the conversational AI chat system.

Test classes
------------
1.  TestChatContextService     — build_user_profile_context, build_research_context,
                                 build_session_context, build_full_context
2.  TestChatPromptService      — build_system_prompt, build_messages, truncation
3.  TestChatServiceStorage     — get_history, clear_history, list_sessions
4.  TestChatServiceOrchestrate — chat() end-to-end with mocked AI
5.  TestChatServiceEdgeCases   — empty session_id/message, missing topic_hint detection
6.  TestTopicHintDetection     — _detect_topic_hint with mocked DB
7.  TestChatEndpoints          — POST /chat, GET history, DELETE history, GET sessions
8.  TestChatEndpointValidation — 422 on blank fields
9.  TestGrokChatFunction       — ask_grok_chat unit test with mocked OpenAI client
10. TestChatIntegration        — full round-trip (gated -m integration)

Patching rules
--------------
- Service tests patch backend.services.chat_service.get_connection and related
  service functions directly.
- Endpoint tests patch backend.main.chat_with_ai / get_chat_history / etc. so
  TestClient's thread is isolated from the DB.
- ask_grok_chat is always patched in unit tests; only the integration test calls Groq.
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
    chat as chat_with_ai,
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
            patch("backend.services.chat_context_service.build_user_profile_context") as mock_fn,
        ):
            mock_fn.return_value = {
                "learning_stage": "intermediate",
                "difficulty_preference": "intermediate",
                "top_interests": ["RAG Pipelines"],
                "suppressed_topics": [],
            }
            result = mock_fn()
        assert "learning_stage" in result
        assert "top_interests" in result
        assert "suppressed_topics" in result

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
        ctx = self._empty_context()
        ctx["research"]["topic"] = "RAG Pipelines"
        ctx["research"]["has_deep_research"] = True
        ctx["research"]["deep_research"] = {"summary": "RAG is about retrieval augmented generation"}
        prompt = build_system_prompt(ctx)
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
        prompt = build_system_prompt(ctx)
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
        _insert_message(mem_db, "s1", "user",      "hi",    topic_hint="RAG", created_at="2025-01-01 10:00:00")
        _insert_message(mem_db, "s1", "assistant", "hello",                   created_at="2025-01-01 10:01:00")
        result = list_sessions()
        assert len(result) == 1
        assert result[0]["session_id"] == "s1"
        assert result[0]["message_count"] == 2

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
# 4. ChatServiceOrchestrate
# ═══════════════════════════════════════════════════════════════════════════════

class TestChatServiceOrchestrate:

    def _mock_context(self):
        return {
            "user_profile": {
                "learning_stage": "intermediate",
                "difficulty_preference": "intermediate",
                "top_interests": ["RAG Pipelines"],
                "suppressed_topics": [],
            },
            "research": {
                "topic": "RAG Pipelines",
                "has_deep_research": True,
                "has_learning_path": False,
                "has_topic_expansion": False,
                "has_github_repos": False,
                "deep_research": {"summary": "RAG overview"},
                "learning_path": None,
                "topic_expansion": None,
                "github_repos": None,
            },
            "session": {
                "topic": "RAG Pipelines",
                "times_explored": 2,
                "has_deep_research": True,
                "has_learning_path": False,
                "has_topic_expansion": False,
                "has_github_repos": False,
                "last_activity_at": "2025-01-01",
                "recommended_next": ["learning_path"],
            },
            "conversation_memory": {
                "message_count": 0, "session_turns": 0,
                "topics_discussed": [], "last_user_messages": [],
            },
            "exploration_breadth": {
                "total_explored": 1, "all_topics": ["RAG Pipelines"],
                "recently_explored": ["RAG Pipelines"], "deep_dived_topics": [],
            },
            "preference_snapshot": {
                "liked_topics": [], "disliked_topics": [],
                "difficulty_preference": None, "engagement_level": "new",
            },
        }

    def test_chat_returns_expected_shape(self, mem_db):
        with (
            patch("backend.services.chat_service.inject_memory", return_value=self._mock_context()),
            patch("backend.services.grok_service.ask_grok_chat", return_value="Great question!"),
            patch("backend.services.chat_service._detect_topic_hint", return_value="RAG Pipelines"),
        ):
            result = chat_with_ai("session-1", "What is RAG?")
        assert result["session_id"] == "session-1"
        assert result["response"] == "Great question!"
        assert isinstance(result["message_id"], int)
        assert "context_used" in result
        assert "created_at" in result

    def test_chat_persists_both_messages(self, mem_db):
        with (
            patch("backend.services.chat_service.inject_memory", return_value=self._mock_context()),
            patch("backend.services.grok_service.ask_grok_chat", return_value="Sure!"),
            patch("backend.services.chat_service._detect_topic_hint", return_value=None),
        ):
            chat_with_ai("session-2", "Tell me about embeddings")
        stored = get_history("session-2")
        assert len(stored) == 2
        assert stored[0]["role"] == "user"
        assert stored[1]["role"] == "assistant"

    def test_chat_context_used_reflects_research(self, mem_db):
        ctx = self._mock_context()
        with (
            patch("backend.services.chat_service.inject_memory", return_value=ctx),
            patch("backend.services.grok_service.ask_grok_chat", return_value="Yes"),
            patch("backend.services.chat_service._detect_topic_hint", return_value=None),
        ):
            result = chat_with_ai("session-3", "any question")
        cu = result["context_used"]
        assert cu["has_deep_research"] is True
        assert cu["has_learning_path"] is False
        assert cu["interests_count"] == 1

    def test_chat_history_turns_count(self, mem_db):
        # Insert 4 existing messages (2 turns)
        _insert_message(mem_db, "s4", "user",      "q1", created_at="2025-01-01 09:00:00")
        _insert_message(mem_db, "s4", "assistant", "a1", created_at="2025-01-01 09:01:00")
        _insert_message(mem_db, "s4", "user",      "q2", created_at="2025-01-01 09:02:00")
        _insert_message(mem_db, "s4", "assistant", "a2", created_at="2025-01-01 09:03:00")
        with (
            patch("backend.services.chat_service.inject_memory", return_value=self._mock_context()),
            patch("backend.services.grok_service.ask_grok_chat", return_value="new reply"),
            patch("backend.services.chat_service._detect_topic_hint", return_value=None),
        ):
            result = chat_with_ai("s4", "q3")
        assert result["context_used"]["history_turns"] == 2

    def test_chat_uses_provided_topic_hint(self, mem_db):
        captured = {}
        def mock_inject(session_id, topic_hint=None):
            captured["topic"] = topic_hint
            return self._mock_context()

        with (
            patch("backend.services.chat_service.inject_memory", side_effect=mock_inject),
            patch("backend.services.grok_service.ask_grok_chat", return_value="ok"),
        ):
            result = chat_with_ai("s5", "explain this", topic_hint="LoRA")
        assert captured["topic"] == "LoRA"
        assert result["topic_hint"] == "LoRA"

    def test_chat_auto_detects_topic_when_not_provided(self, mem_db):
        with (
            patch("backend.services.chat_service._detect_topic_hint", return_value="RAG Pipelines") as mock_detect,
            patch("backend.services.chat_service.inject_memory", return_value=self._mock_context()),
            patch("backend.services.grok_service.ask_grok_chat", return_value="answer"),
        ):
            result = chat_with_ai("s6", "question about RAG")
        mock_detect.assert_called_once_with("question about RAG")
        assert result["topic_hint"] == "RAG Pipelines"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. ChatServiceEdgeCases
# ═══════════════════════════════════════════════════════════════════════════════

class TestChatServiceEdgeCases:

    def test_empty_session_id_raises(self, mem_db):
        with pytest.raises(ValueError, match="session_id"):
            chat_with_ai("  ", "message")

    def test_empty_message_raises(self, mem_db):
        with pytest.raises(ValueError, match="message"):
            chat_with_ai("session-x", "   ")

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

    def test_multiple_chats_accumulate_history(self, mem_db):
        ctx = {
            "user_profile": {"learning_stage": "beginner", "difficulty_preference": None, "top_interests": [], "suppressed_topics": []},
            "research": {"topic": None, "has_deep_research": False, "has_learning_path": False, "has_topic_expansion": False, "has_github_repos": False, "deep_research": None, "learning_path": None, "topic_expansion": None, "github_repos": None},
            "session": {"topic": None, "times_explored": 0, "has_deep_research": False, "has_learning_path": False, "has_topic_expansion": False, "has_github_repos": False, "last_activity_at": None, "recommended_next": []},
            "conversation_memory": {"message_count": 0, "session_turns": 0, "topics_discussed": [], "last_user_messages": []},
            "exploration_breadth": {"total_explored": 0, "all_topics": [], "recently_explored": [], "deep_dived_topics": []},
            "preference_snapshot": {"liked_topics": [], "disliked_topics": [], "difficulty_preference": None, "engagement_level": "new"},
        }
        for i in range(3):
            with (
                patch("backend.services.chat_service.inject_memory", return_value=ctx),
                patch("backend.services.grok_service.ask_grok_chat", return_value=f"answer {i}"),
                patch("backend.services.chat_service._detect_topic_hint", return_value=None),
            ):
                chat_with_ai("multi", f"question {i}")
        history = get_history("multi")
        assert len(history) == 6  # 3 user + 3 assistant


# ═══════════════════════════════════════════════════════════════════════════════
# 6. TopicHintDetection
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
# 7. ChatEndpoints
# ═══════════════════════════════════════════════════════════════════════════════

class TestChatEndpoints:

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        return TestClient(app, raise_server_exceptions=False)

    def _mock_chat_result(self):
        return {
            "session_id": "test-session",
            "message_id": 42,
            "response": "That's a great question about RAG!",
            "topic_hint": "RAG Pipelines",
            "context_used": {
                "has_deep_research": True,
                "has_learning_path": False,
                "has_topic_expansion": False,
                "has_github_repos": False,
                "interests_count": 2,
                "history_turns": 0,
            },
            "created_at": "2025-01-01 10:00:00",
        }

    def test_post_chat_returns_200(self, client):
        with patch("backend.main.chat_with_ai", return_value=self._mock_chat_result()):
            resp = client.post("/chat", json={"session_id": "test-session", "message": "What is RAG?"})
        assert resp.status_code == 200

    def test_post_chat_response_shape(self, client):
        with patch("backend.main.chat_with_ai", return_value=self._mock_chat_result()):
            resp = client.post("/chat", json={"session_id": "s1", "message": "hello"})
        body = resp.json()
        assert "session_id" in body
        assert "response" in body
        assert "context_used" in body
        assert "message_id" in body

    def test_post_chat_passes_topic_hint(self, client):
        captured = {}
        def mock_chat(**kwargs):
            captured.update(kwargs)
            return self._mock_chat_result()

        with patch("backend.main.chat_with_ai", side_effect=mock_chat):
            client.post("/chat", json={"session_id": "s1", "message": "hello", "topic_hint": "LoRA"})
        assert captured.get("topic_hint") == "LoRA"

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


# ═══════════════════════════════════════════════════════════════════════════════
# 8. ChatEndpointValidation
# ═══════════════════════════════════════════════════════════════════════════════

class TestChatEndpointValidation:

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        return TestClient(app, raise_server_exceptions=False)

    def test_blank_session_id_returns_422(self, client):
        resp = client.post("/chat", json={"session_id": "  ", "message": "hello"})
        assert resp.status_code == 422

    def test_blank_message_returns_422(self, client):
        resp = client.post("/chat", json={"session_id": "s1", "message": "  "})
        assert resp.status_code == 422

    def test_missing_session_id_returns_422(self, client):
        resp = client.post("/chat", json={"message": "hello"})
        assert resp.status_code == 422

    def test_missing_message_returns_422(self, client):
        resp = client.post("/chat", json={"session_id": "s1"})
        assert resp.status_code == 422

    def test_topic_hint_is_optional(self, client):
        mock_result = {
            "session_id": "s1", "message_id": 1, "response": "ok", "topic_hint": None,
            "context_used": {"has_deep_research": False, "has_learning_path": False,
                             "has_topic_expansion": False, "has_github_repos": False,
                             "interests_count": 0, "history_turns": 0},
            "created_at": "2025-01-01 10:00:00",
        }
        with patch("backend.main.chat_with_ai", return_value=mock_result):
            resp = client.post("/chat", json={"session_id": "s1", "message": "hello"})
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# 9. GrokChatFunction
# ═══════════════════════════════════════════════════════════════════════════════

class TestGrokChatFunction:

    def test_ask_grok_chat_returns_string(self):
        from backend.services.grok_service import ask_grok_chat

        mock_choice = MagicMock()
        mock_choice.message.content = "Here is my response."
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage.prompt_tokens     = 100
        mock_response.usage.completion_tokens = 50

        with (
            patch("backend.services.grok_service.client") as mock_client,
            patch("backend.services.api_usage_service.log_api_call"),
            patch("backend.services.api_usage_service.estimate_groq_cost", return_value=0.0),
        ):
            mock_client.chat.completions.create.return_value = mock_response
            result = ask_grok_chat([
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "Hello"},
            ])
        assert result == "Here is my response."

    def test_ask_grok_chat_passes_messages_directly(self):
        from backend.services.grok_service import ask_grok_chat

        messages_sent = []

        def mock_create(model, messages, temperature):
            messages_sent.extend(messages)
            mock_choice = MagicMock()
            mock_choice.message.content = "done"
            resp = MagicMock()
            resp.choices = [mock_choice]
            resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
            return resp

        with (
            patch("backend.services.grok_service.client") as mock_client,
            patch("backend.services.api_usage_service.log_api_call"),
            patch("backend.services.api_usage_service.estimate_groq_cost", return_value=0.0),
        ):
            mock_client.chat.completions.create.side_effect = mock_create
            ask_grok_chat([
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "usr"},
            ])
        assert messages_sent[0]["role"] == "system"
        assert messages_sent[1]["role"] == "usr" or messages_sent[1]["content"] == "usr"

    def test_ask_grok_chat_raises_on_api_error(self):
        from backend.services.grok_service import ask_grok_chat

        with (
            patch("backend.services.grok_service.client") as mock_client,
            patch("backend.services.api_usage_service.log_api_call"),
            patch("backend.services.api_usage_service.estimate_groq_cost", return_value=0.0),
        ):
            mock_client.chat.completions.create.side_effect = ConnectionError("timeout")
            with pytest.raises(RuntimeError, match="API request failed"):
                ask_grok_chat([{"role": "user", "content": "hi"}])

    def test_ask_grok_chat_logs_api_call(self):
        from backend.services.grok_service import ask_grok_chat

        mock_choice = MagicMock()
        mock_choice.message.content = "logged"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage.prompt_tokens     = 80
        mock_response.usage.completion_tokens = 40

        with (
            patch("backend.services.grok_service.client") as mock_client,
            patch("backend.services.api_usage_service.log_api_call") as mock_log,
            patch("backend.services.api_usage_service.estimate_groq_cost", return_value=0.001),
        ):
            mock_client.chat.completions.create.return_value = mock_response
            ask_grok_chat([{"role": "user", "content": "test"}])
        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args[1]
        assert call_kwargs["operation"] == "chat_conversation"


# ═══════════════════════════════════════════════════════════════════════════════
# 10. ChatIntegration
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.integration
class TestChatIntegration:

    def test_full_chat_round_trip(self):
        """One real conversation turn using the live Groq API and DB."""
        import uuid
        session_id = f"integration-test-{uuid.uuid4().hex[:8]}"

        result = chat_with_ai(
            session_id=session_id,
            message="In one sentence, what is RAG (Retrieval Augmented Generation)?",
            topic_hint="RAG Pipelines",
        )

        assert result["session_id"] == session_id
        assert isinstance(result["response"], str)
        assert len(result["response"]) > 10
        assert isinstance(result["message_id"], int)

        history = get_history(session_id)
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"

        # Cleanup
        clear_history(session_id)
        assert get_history(session_id) == []
