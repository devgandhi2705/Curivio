"""
Tests for the conversation memory injection layer.

Test classes
------------
1.  TestBuildConversationMemory  — session summary, topic extraction, message counts
2.  TestBuildExplorationBreadth  — topic breadth from research_sessions
3.  TestBuildPreferenceSnapshot  — liked/disliked topics and engagement level
4.  TestInjectMemory             — orchestrator merges all layers correctly
5.  TestConversationMemoryPrompt — prompt builder uses conversation memory section
6.  TestExplorationBreadthPrompt — prompt builder uses breadth section
7.  TestPreferenceSnapshotPrompt — prompt builder uses preference snapshot section
8.  TestChatUsesInjectMemory     — chat() calls inject_memory, not build_full_context

Patching rules
--------------
- Service-layer tests use a shared in-memory SQLite fixture (mem_db)
  that monkeypatches backend.services.memory_injection_service.get_connection
  inside build_conversation_memory / build_exploration_breadth / build_preference_snapshot.
- Prompt tests call the builders directly with handcrafted dicts.
- chat() tests patch backend.services.chat_service.inject_memory to avoid DB + AI.
"""

from __future__ import annotations

import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.database.schema import ALL_TABLES, MIGRATIONS
from backend.services.memory_injection_service import (
    build_conversation_memory,
    build_exploration_breadth,
    build_preference_snapshot,
    inject_memory,
)
from backend.services.chat_prompt_service import (
    build_system_prompt,
    _build_conversation_memory_section,
    _build_exploration_breadth_section,
    _build_preference_snapshot_section,
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
    # Chat-R7a: user_preferences/research_sessions only gain their user_id
    # column via MIGRATIONS (matches real init_db()'s behavior — same
    # pattern every other user_id-scoped table in this codebase already uses).
    for migration in MIGRATIONS:
        try:
            if isinstance(migration, (list, tuple)):
                for stmt in migration:
                    conn.execute(stmt)
            else:
                conn.execute(migration)
        except sqlite3.OperationalError:
            pass
    conn.commit()

    @contextmanager
    def _get_conn():
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    monkeypatch.setattr(
        "backend.services.memory_injection_service.get_connection", _get_conn,
        raising=False,
    )
    # Also patch db import path used inside the functions
    import backend.utils.db as _db_module
    monkeypatch.setattr(_db_module, "get_connection", _get_conn)
    return conn


def _insert_chat(conn, session_id, role, content, topic_hint=None, ts="2025-01-01 10:00:00"):
    conn.execute(
        "INSERT INTO chat_messages (session_id, role, content, topic_hint, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (session_id, role, content, topic_hint, ts),
    )
    conn.commit()


_TEST_USER = "test-user-1"


def _insert_session(conn, topic, activity, ts="2025-01-01 10:00:00", user_id=_TEST_USER):
    conn.execute(
        "INSERT INTO research_sessions (topic, topic_key, activity, recorded_at, user_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (topic, topic.lower().strip(), activity, ts, user_id),
    )
    conn.commit()


def _insert_pref(conn, topic, score, liked=0, disliked=0, difficulty=None, user_id=_TEST_USER):
    conn.execute(
        """INSERT OR REPLACE INTO user_preferences
           (topic, user_id, preference_score, times_liked, times_disliked, difficulty_preference)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (topic, user_id, score, liked, disliked, difficulty),
    )
    conn.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. TestBuildConversationMemory
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildConversationMemory:

    def test_empty_session_returns_zeros(self, mem_db):
        result = build_conversation_memory("no-messages")
        assert result["message_count"] == 0
        assert result["session_turns"] == 0
        assert result["topics_discussed"] == []
        assert result["last_user_messages"] == []

    def test_blank_session_id_returns_empty(self, mem_db):
        result = build_conversation_memory("  ")
        assert result["message_count"] == 0

    def test_message_count_correct(self, mem_db):
        _insert_chat(mem_db, "s1", "user",      "q1", ts="2025-01-01 10:00:00")
        _insert_chat(mem_db, "s1", "assistant", "a1", ts="2025-01-01 10:01:00")
        result = build_conversation_memory("s1")
        assert result["message_count"] == 2

    def test_session_turns_counts_user_messages(self, mem_db):
        _insert_chat(mem_db, "s1", "user",      "q1", ts="2025-01-01 10:00:00")
        _insert_chat(mem_db, "s1", "assistant", "a1", ts="2025-01-01 10:01:00")
        _insert_chat(mem_db, "s1", "user",      "q2", ts="2025-01-01 10:02:00")
        _insert_chat(mem_db, "s1", "assistant", "a2", ts="2025-01-01 10:03:00")
        result = build_conversation_memory("s1")
        assert result["session_turns"] == 2

    def test_topics_discussed_extracted_from_hints(self, mem_db):
        _insert_chat(mem_db, "s1", "user",      "q",  topic_hint="RAG",  ts="2025-01-01 10:00:00")
        _insert_chat(mem_db, "s1", "assistant", "a",  topic_hint="RAG",  ts="2025-01-01 10:01:00")
        _insert_chat(mem_db, "s1", "user",      "q2", topic_hint="LoRA", ts="2025-01-01 10:02:00")
        result = build_conversation_memory("s1")
        assert "RAG" in result["topics_discussed"]
        assert "LoRA" in result["topics_discussed"]

    def test_topics_discussed_most_frequent_first(self, mem_db):
        for i in range(3):
            _insert_chat(mem_db, "s1", "user", f"q{i}", topic_hint="RAG",  ts=f"2025-01-01 10:0{i}:00")
        _insert_chat(mem_db, "s1", "user", "q4", topic_hint="LoRA", ts="2025-01-01 10:04:00")
        result = build_conversation_memory("s1")
        assert result["topics_discussed"][0] == "RAG"

    def test_last_user_messages_most_recent_first(self, mem_db):
        _insert_chat(mem_db, "s1", "user", "first",  ts="2025-01-01 09:00:00")
        _insert_chat(mem_db, "s1", "user", "second", ts="2025-01-01 10:00:00")
        _insert_chat(mem_db, "s1", "user", "third",  ts="2025-01-01 11:00:00")
        result = build_conversation_memory("s1")
        assert result["last_user_messages"][0] == "third"

    def test_last_user_messages_capped_at_three(self, mem_db):
        for i in range(6):
            _insert_chat(mem_db, "s1", "user", f"q{i}", ts=f"2025-01-0{i+1} 10:00:00")
        result = build_conversation_memory("s1")
        assert len(result["last_user_messages"]) == 3

    def test_session_isolation(self, mem_db):
        _insert_chat(mem_db, "s1", "user", "s1-question", topic_hint="RAG")
        _insert_chat(mem_db, "s2", "user", "s2-question", topic_hint="LoRA")
        r1 = build_conversation_memory("s1")
        r2 = build_conversation_memory("s2")
        assert r1["topics_discussed"] == ["RAG"]
        assert r2["topics_discussed"] == ["LoRA"]

    def test_messages_without_topic_hint_still_counted(self, mem_db):
        _insert_chat(mem_db, "s1", "user",      "no hint", topic_hint=None)
        _insert_chat(mem_db, "s1", "assistant", "reply",   topic_hint=None)
        result = build_conversation_memory("s1")
        assert result["message_count"] == 2
        assert result["topics_discussed"] == []

    def test_graceful_on_db_error(self, monkeypatch):
        import backend.utils.db as _db
        monkeypatch.setattr(_db, "get_connection", MagicMock(side_effect=RuntimeError("db down")))
        result = build_conversation_memory("s1")
        assert result["message_count"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 2. TestBuildExplorationBreadth
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildExplorationBreadth:

    def test_empty_db_returns_zeros(self, mem_db):
        result = build_exploration_breadth(user_id=_TEST_USER)
        assert result["total_explored"] == 0
        assert result["all_topics"] == []
        assert result["recently_explored"] == []

    def test_missing_user_id_returns_zeros_even_with_data(self, mem_db):
        # Chat-R7a: no user_id must never fall back to global/other-user data.
        _insert_session(mem_db, "RAG Pipelines", "deep_research")
        result = build_exploration_breadth()
        assert result["total_explored"] == 0
        assert result["all_topics"] == []

    def test_single_topic_appears(self, mem_db):
        _insert_session(mem_db, "RAG Pipelines", "deep_research")
        result = build_exploration_breadth(user_id=_TEST_USER)
        assert "RAG Pipelines" in result["all_topics"]
        assert result["total_explored"] == 1

    def test_multiple_topics_all_returned(self, mem_db):
        _insert_session(mem_db, "RAG Pipelines", "deep_research",  "2025-01-03 10:00:00")
        _insert_session(mem_db, "LoRA",           "topic_expansion","2025-01-02 10:00:00")
        _insert_session(mem_db, "Diffusion",      "learning_path",  "2025-01-01 10:00:00")
        result = build_exploration_breadth(user_id=_TEST_USER)
        assert result["total_explored"] == 3
        assert len(result["all_topics"]) == 3

    def test_recently_explored_is_last_five(self, mem_db):
        topics = ["T1", "T2", "T3", "T4", "T5", "T6"]
        for i, t in enumerate(topics):
            _insert_session(mem_db, t, "deep_research", f"2025-01-0{i+1} 10:00:00")
        result = build_exploration_breadth(user_id=_TEST_USER)
        assert len(result["recently_explored"]) == 5
        assert result["recently_explored"][0] == "T6"

    def test_deep_dived_topics_filtered(self, mem_db):
        _insert_session(mem_db, "RAG", "deep_research",  "2025-01-02")
        _insert_session(mem_db, "LoRA", "topic_expansion","2025-01-01")
        result = build_exploration_breadth(user_id=_TEST_USER)
        assert "RAG" in result["deep_dived_topics"]
        assert "LoRA" not in result["deep_dived_topics"]

    def test_limit_respected(self, mem_db):
        for i in range(10):
            _insert_session(mem_db, f"Topic{i}", "deep_research", f"2025-01-1{i} 10:00:00")
        result = build_exploration_breadth(limit=5, user_id=_TEST_USER)
        assert len(result["all_topics"]) <= 5

    def test_other_user_activity_not_visible(self, mem_db):
        _insert_session(mem_db, "Other User Topic", "deep_research", user_id="other-user")
        result = build_exploration_breadth(user_id=_TEST_USER)
        assert result["total_explored"] == 0
        assert "Other User Topic" not in result["all_topics"]

    def test_graceful_on_db_error(self, monkeypatch):
        import backend.utils.db as _db
        monkeypatch.setattr(_db, "get_connection", MagicMock(side_effect=RuntimeError))
        result = build_exploration_breadth(user_id=_TEST_USER)
        assert result["total_explored"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 3. TestBuildPreferenceSnapshot
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildPreferenceSnapshot:

    def test_empty_db_returns_empty_lists(self, mem_db):
        result = build_preference_snapshot(user_id=_TEST_USER)
        assert result["liked_topics"] == []
        assert result["disliked_topics"] == []
        assert result["engagement_level"] == "new"

    def test_missing_user_id_returns_empty_even_with_data(self, mem_db):
        # Chat-R7a: no user_id must never fall back to global/other-user data.
        _insert_pref(mem_db, "RAG", 1.5, liked=3)
        result = build_preference_snapshot()
        assert result["liked_topics"] == []

    def test_liked_topics_extracted(self, mem_db):
        _insert_pref(mem_db, "RAG",  1.5, liked=3)
        _insert_pref(mem_db, "LoRA", 0.5, liked=1)
        result = build_preference_snapshot(user_id=_TEST_USER)
        assert "RAG"  in result["liked_topics"]
        assert "LoRA" in result["liked_topics"]

    def test_disliked_topics_extracted(self, mem_db):
        _insert_pref(mem_db, "Boring Topic", -0.5, disliked=2)
        result = build_preference_snapshot(user_id=_TEST_USER)
        assert "Boring Topic" in result["disliked_topics"]

    def test_neutral_topics_not_in_disliked(self, mem_db):
        _insert_pref(mem_db, "Neutral", 0.0)
        result = build_preference_snapshot(user_id=_TEST_USER)
        assert "Neutral" not in result["disliked_topics"]

    def test_liked_capped_at_eight(self, mem_db):
        for i in range(12):
            _insert_pref(mem_db, f"Topic{i}", float(i), liked=i)
        result = build_preference_snapshot(user_id=_TEST_USER)
        assert len(result["liked_topics"]) <= 8

    def test_difficulty_preference_from_most_common(self, mem_db):
        _insert_pref(mem_db, "T1", 1.0, difficulty="intermediate")
        _insert_pref(mem_db, "T2", 0.5, difficulty="intermediate")
        _insert_pref(mem_db, "T3", 0.2, difficulty="beginner")
        result = build_preference_snapshot(user_id=_TEST_USER)
        assert result["difficulty_preference"] == "intermediate"

    def test_engagement_level_high(self, mem_db):
        _insert_pref(mem_db, "T1", 1.0, liked=8, disliked=1)
        _insert_pref(mem_db, "T2", 0.5, liked=5, disliked=0)
        result = build_preference_snapshot(user_id=_TEST_USER)
        assert result["engagement_level"] == "high"

    def test_engagement_level_low(self, mem_db):
        _insert_pref(mem_db, "T1", -0.8, liked=1, disliked=10)
        result = build_preference_snapshot(user_id=_TEST_USER)
        assert result["engagement_level"] == "low"

    def test_engagement_level_new_with_no_signals(self, mem_db):
        _insert_pref(mem_db, "T1", 0.0, liked=0, disliked=0)
        result = build_preference_snapshot(user_id=_TEST_USER)
        assert result["engagement_level"] == "new"

    def test_other_user_preferences_not_visible(self, mem_db):
        _insert_pref(mem_db, "Other User Topic", 2.0, liked=5, user_id="other-user")
        result = build_preference_snapshot(user_id=_TEST_USER)
        assert result["liked_topics"] == []

    def test_graceful_on_db_error(self, monkeypatch):
        import backend.utils.db as _db
        monkeypatch.setattr(_db, "get_connection", MagicMock(side_effect=RuntimeError))
        result = build_preference_snapshot(user_id=_TEST_USER)
        assert result["liked_topics"] == []


# ═══════════════════════════════════════════════════════════════════════════════
# 4. TestInjectMemory
# ═══════════════════════════════════════════════════════════════════════════════

class TestInjectMemory:

    def _mock_base(self):
        return {
            "user_profile": {"learning_stage": "intermediate", "difficulty_preference": None,
                             "top_interests": ["RAG"], "suppressed_topics": []},
            "research":     {"topic": "RAG", "has_deep_research": True, "has_learning_path": False,
                             "has_topic_expansion": False, "has_github_repos": False,
                             "deep_research": None, "learning_path": None,
                             "topic_expansion": None, "github_repos": None},
            "session":      {"topic": "RAG", "times_explored": 1, "has_deep_research": True,
                             "has_learning_path": False, "has_topic_expansion": False,
                             "has_github_repos": False, "last_activity_at": "2025-01-01",
                             "recommended_next": []},
        }

    def test_inject_memory_has_all_keys(self):
        with (
            patch("backend.services.chat_context_service.build_full_context", return_value=self._mock_base()),
            patch("backend.services.memory_injection_service.build_conversation_memory", return_value={"message_count": 0}),
            patch("backend.services.memory_injection_service.build_exploration_breadth", return_value={"total_explored": 0}),
            patch("backend.services.memory_injection_service.build_preference_snapshot", return_value={"liked_topics": []}),
        ):
            result = inject_memory("session-1", "RAG")
        for key in ("user_profile", "research", "session",
                    "conversation_memory", "exploration_breadth", "preference_snapshot"):
            assert key in result

    def test_inject_memory_passes_topic_hint_to_base(self):
        captured = {}
        def mock_base(topic, user_id=None):
            captured["topic"] = topic
            return self._mock_base()

        with (
            patch("backend.services.chat_context_service.build_full_context", side_effect=mock_base),
            patch("backend.services.memory_injection_service.build_conversation_memory", return_value={}),
            patch("backend.services.memory_injection_service.build_exploration_breadth", return_value={}),
            patch("backend.services.memory_injection_service.build_preference_snapshot", return_value={}),
        ):
            inject_memory("session-1", "LoRA")
        assert captured["topic"] == "LoRA"

    def test_inject_memory_passes_session_id_to_conv_memory(self):
        captured = {}
        def mock_conv(session_id, **kwargs):
            captured["session_id"] = session_id
            return {"message_count": 0}

        with (
            patch("backend.services.chat_context_service.build_full_context", return_value=self._mock_base()),
            patch("backend.services.memory_injection_service.build_conversation_memory", side_effect=mock_conv),
            patch("backend.services.memory_injection_service.build_exploration_breadth", return_value={}),
            patch("backend.services.memory_injection_service.build_preference_snapshot", return_value={}),
        ):
            inject_memory("my-session", "RAG")
        assert captured["session_id"] == "my-session"

    def test_inject_memory_none_topic_hint(self):
        with (
            patch("backend.services.chat_context_service.build_full_context", return_value=self._mock_base()),
            patch("backend.services.memory_injection_service.build_conversation_memory", return_value={}),
            patch("backend.services.memory_injection_service.build_exploration_breadth", return_value={}),
            patch("backend.services.memory_injection_service.build_preference_snapshot", return_value={}),
        ):
            result = inject_memory("session-1", None)
        assert "user_profile" in result

    def test_inject_memory_merges_without_overwriting_base(self):
        base = self._mock_base()
        with (
            patch("backend.services.chat_context_service.build_full_context", return_value=base),
            patch("backend.services.memory_injection_service.build_conversation_memory", return_value={"message_count": 5}),
            patch("backend.services.memory_injection_service.build_exploration_breadth", return_value={"total_explored": 3}),
            patch("backend.services.memory_injection_service.build_preference_snapshot", return_value={"liked_topics": ["RAG"]}),
        ):
            result = inject_memory("session-1", "RAG")
        assert result["user_profile"]["learning_stage"] == "intermediate"
        assert result["conversation_memory"]["message_count"] == 5
        assert result["exploration_breadth"]["total_explored"] == 3
        assert result["preference_snapshot"]["liked_topics"] == ["RAG"]


# ═══════════════════════════════════════════════════════════════════════════════
# 5. TestConversationMemoryPrompt
# ═══════════════════════════════════════════════════════════════════════════════

class TestConversationMemoryPrompt:

    def test_empty_conv_memory_returns_empty_string(self):
        assert _build_conversation_memory_section({}) == ""

    def test_zero_message_count_returns_empty(self):
        assert _build_conversation_memory_section({"message_count": 0}) == ""

    def test_topics_discussed_appear_in_section(self):
        conv = {"message_count": 4, "session_turns": 2,
                "topics_discussed": ["RAG Pipelines", "LoRA"],
                "last_user_messages": ["What is RAG?"]}
        section = _build_conversation_memory_section(conv)
        assert "RAG Pipelines" in section
        assert "LoRA" in section

    def test_anti_repetition_instruction_included(self):
        conv = {"message_count": 2, "session_turns": 1,
                "topics_discussed": ["RAG"],
                "last_user_messages": []}
        section = _build_conversation_memory_section(conv)
        assert "re-explain" in section.lower() or "covered" in section.lower()

    def test_most_recent_question_shown(self):
        conv = {"message_count": 2, "session_turns": 1,
                "topics_discussed": [],
                "last_user_messages": ["Tell me about attention mechanisms"]}
        section = _build_conversation_memory_section(conv)
        assert "Tell me about attention" in section

    def test_long_question_truncated_in_section(self):
        long_q = "x" * 200
        conv = {"message_count": 2, "session_turns": 1,
                "topics_discussed": [],
                "last_user_messages": [long_q]}
        section = _build_conversation_memory_section(conv)
        assert len(section) < 500  # should be truncated, not bloated

    def test_full_system_prompt_includes_conv_section(self):
        context = {
            "user_profile": {"learning_stage": "beginner", "difficulty_preference": None,
                             "top_interests": [], "suppressed_topics": []},
            "research":  {"topic": None},
            "session":   {"topic": None},
            "conversation_memory": {
                "message_count": 4, "session_turns": 2,
                "topics_discussed": ["RAG Pipelines"],
                "last_user_messages": ["What is chunking?"],
            },
            "exploration_breadth":  {},
            "preference_snapshot":  {},
        }
        prompt = build_system_prompt(context)
        assert "RAG Pipelines" in prompt


# ═══════════════════════════════════════════════════════════════════════════════
# 6. TestExplorationBreadthPrompt
# ═══════════════════════════════════════════════════════════════════════════════

class TestExplorationBreadthPrompt:

    def test_empty_breadth_returns_empty(self):
        assert _build_exploration_breadth_section({}) == ""

    def test_zero_explored_returns_empty(self):
        assert _build_exploration_breadth_section({"total_explored": 0}) == ""

    def test_recently_explored_in_section(self):
        breadth = {"total_explored": 3,
                   "recently_explored": ["RAG Pipelines", "LoRA", "Diffusion"],
                   "deep_dived_topics": ["RAG Pipelines"]}
        section = _build_exploration_breadth_section(breadth)
        assert "RAG Pipelines" in section

    def test_deep_dived_topics_in_section(self):
        breadth = {"total_explored": 2,
                   "recently_explored": ["RAG"],
                   "deep_dived_topics": ["RAG"]}
        section = _build_exploration_breadth_section(breadth)
        assert "deep" in section.lower() or "RAG" in section

    def test_connection_instruction_included_when_multiple_topics(self):
        breadth = {"total_explored": 3,
                   "recently_explored": ["T1", "T2"],
                   "deep_dived_topics": []}
        section = _build_exploration_breadth_section(breadth)
        assert "connect" in section.lower() or "studied" in section.lower()

    def test_full_prompt_includes_breadth_section(self):
        # Chat-R7b: structured rendering now gates on a genuine Feed link
        # (context["feed_linked"]), not mode — exploration_breadth only
        # renders in the structured prompt, so feed_linked must be set here.
        context = {
            "feed_linked": True,
            "user_profile": {"learning_stage": "beginner", "difficulty_preference": None,
                             "top_interests": [], "suppressed_topics": []},
            "research": {"topic": None}, "session": {"topic": None},
            "conversation_memory": {},
            "exploration_breadth": {
                "total_explored": 5,
                "recently_explored": ["LoRA", "RAG"],
                "deep_dived_topics": ["LoRA"],
            },
            "preference_snapshot": {},
        }
        prompt = build_system_prompt(context, mode="web_search")
        assert "LoRA" in prompt


# ═══════════════════════════════════════════════════════════════════════════════
# 7. TestPreferenceSnapshotPrompt
# ═══════════════════════════════════════════════════════════════════════════════

class TestPreferenceSnapshotPrompt:

    def test_empty_prefs_returns_empty(self):
        assert _build_preference_snapshot_section({}) == ""

    def test_no_liked_or_disliked_returns_empty(self):
        assert _build_preference_snapshot_section({
            "liked_topics": [], "disliked_topics": [],
            "difficulty_preference": None, "engagement_level": "new",
        }) == ""

    def test_liked_topics_in_section(self):
        prefs = {"liked_topics": ["RAG", "transformers"],
                 "disliked_topics": [],
                 "difficulty_preference": None,
                 "engagement_level": "high"}
        section = _build_preference_snapshot_section(prefs)
        assert "RAG" in section
        assert "transformers" in section

    def test_disliked_topics_in_section(self):
        prefs = {"liked_topics": [],
                 "disliked_topics": ["Boring Stuff"],
                 "difficulty_preference": None,
                 "engagement_level": "low"}
        section = _build_preference_snapshot_section(prefs)
        assert "Boring Stuff" in section

    def test_difficulty_preference_in_section(self):
        prefs = {"liked_topics": ["T1"],
                 "disliked_topics": [],
                 "difficulty_preference": "advanced",
                 "engagement_level": "high"}
        section = _build_preference_snapshot_section(prefs)
        assert "advanced" in section

    def test_high_engagement_note_included(self):
        prefs = {"liked_topics": ["T1"],
                 "disliked_topics": [],
                 "difficulty_preference": None,
                 "engagement_level": "high"}
        section = _build_preference_snapshot_section(prefs)
        assert "depth" in section.lower() or "detail" in section.lower()

    def test_low_engagement_note_included(self):
        prefs = {"liked_topics": [],
                 "disliked_topics": ["T1"],
                 "difficulty_preference": None,
                 "engagement_level": "low"}
        section = _build_preference_snapshot_section(prefs)
        assert "focused" in section.lower() or "practical" in section.lower()

    def test_full_prompt_includes_pref_section(self):
        # Chat-R7b: structured rendering now gates on a genuine Feed link
        # (context["feed_linked"]), not mode — preference_snapshot only
        # renders in the structured prompt, so feed_linked must be set here.
        context = {
            "feed_linked": True,
            "user_profile": {"learning_stage": "beginner", "difficulty_preference": None,
                             "top_interests": [], "suppressed_topics": []},
            "research": {"topic": None}, "session": {"topic": None},
            "conversation_memory": {}, "exploration_breadth": {},
            "preference_snapshot": {
                "liked_topics": ["RAG Pipelines"],
                "disliked_topics": [],
                "difficulty_preference": "intermediate",
                "engagement_level": "high",
            },
        }
        prompt = build_system_prompt(context, mode="web_search")
        assert "RAG Pipelines" in prompt
        assert "intermediate" in prompt

