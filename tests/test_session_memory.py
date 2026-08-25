"""
Tests for research-session memory tracking.

Test levels
-----------
1. RecordActivity         — insertion, ID return, validation
2. GetTopicMemory         — structure, ordering, None-on-miss
3. ListExploredTopics     — ordering, limit, deduplication
4. IsActivityRecorded     — boolean lookups, case insensitivity
5. GetResearchContext     — always-dict shape, recommended_next logic
6. SessionMemoryEndpoints — HTTP shape and status codes
7. MainHooks              — record_activity called from POST endpoints
8. Integration            — full round-trip (gated -m integration)

Patching
--------
Service tests patch backend.services.session_memory_service.get_connection.
Endpoint tests patch backend.main.* (no mem_db passed to client fixture).
"""

import json
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.database.schema import ALL_TABLES, MIGRATIONS
from backend.services.session_memory_service import (
    ACTIVITY_TYPES,
    _topic_key,
    get_research_context,
    get_topic_memory,
    is_activity_recorded,
    list_explored_topics,
    record_activity,
)


# ── In-memory DB fixture ───────────────────────────────────────────────────────

@pytest.fixture
def mem_db(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    for stmt in ALL_TABLES:
        conn.execute(stmt)
    # Chat-R7a: research_sessions only gains its user_id column via
    # MIGRATIONS (matches real init_db()'s behavior).
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
        "backend.services.session_memory_service.get_connection", _get_conn
    )
    yield conn
    conn.close()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _insert_session(conn, topic="RAG", activity="deep_research", hours_ago=1):
    ts = (
        datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    ).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO research_sessions (topic, topic_key, activity, recorded_at) "
        "VALUES (?, ?, ?, ?)",
        (topic, _topic_key(topic), activity, ts),
    )
    conn.commit()
    return ts


def _all_activities():
    return sorted(ACTIVITY_TYPES)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. record_activity
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecordActivity:
    def test_returns_integer_id(self, mem_db):
        row_id = record_activity("RAG", "topic_expansion", "test-user")
        assert isinstance(row_id, int)

    def test_id_is_positive(self, mem_db):
        row_id = record_activity("RAG", "topic_expansion", "test-user")
        assert row_id > 0

    def test_row_exists_in_db(self, mem_db):
        record_activity("RAG", "topic_expansion", "test-user")
        count = mem_db.execute("SELECT COUNT(*) FROM research_sessions").fetchone()[0]
        assert count == 1

    def test_multiple_records_same_topic(self, mem_db):
        record_activity("RAG", "topic_expansion", "test-user")
        record_activity("RAG", "learning_path", "test-user")
        count = mem_db.execute("SELECT COUNT(*) FROM research_sessions").fetchone()[0]
        assert count == 2

    def test_ids_are_unique(self, mem_db):
        id1 = record_activity("RAG", "topic_expansion", "test-user")
        id2 = record_activity("RAG", "learning_path", "test-user")
        assert id1 != id2

    def test_raises_value_error_for_empty_topic(self, mem_db):
        with pytest.raises(ValueError, match="must not be empty"):
            record_activity("", "deep_research", "test-user")

    def test_raises_value_error_for_unknown_activity(self, mem_db):
        with pytest.raises(ValueError, match="unknown activity"):
            record_activity("RAG", "nonexistent_activity", "test-user")

    def test_raises_value_error_for_missing_user_id(self, mem_db):
        # Chat-R7a: user_id is required — no silent fallback to unscoped writes.
        with pytest.raises(ValueError, match="user_id must not be empty"):
            record_activity("RAG", "topic_expansion", "")

    def test_all_activity_types_accepted(self, mem_db):
        for activity in ACTIVITY_TYPES:
            record_activity("RAG", activity, "test-user")
        count = mem_db.execute("SELECT COUNT(*) FROM research_sessions").fetchone()[0]
        assert count == len(ACTIVITY_TYPES)

    def test_topic_case_preserved_in_db(self, mem_db):
        record_activity("RAG Pipelines", "topic_expansion", "test-user")
        row = mem_db.execute("SELECT topic FROM research_sessions").fetchone()
        assert row["topic"] == "RAG Pipelines"

    def test_topic_key_lowercased_in_db(self, mem_db):
        record_activity("RAG Pipelines", "topic_expansion", "test-user")
        row = mem_db.execute("SELECT topic_key FROM research_sessions").fetchone()
        assert row["topic_key"] == "rag pipelines"

    def test_user_id_stored_on_row(self, mem_db):
        record_activity("RAG", "topic_expansion", "test-user")
        row = mem_db.execute("SELECT user_id FROM research_sessions").fetchone()
        assert row["user_id"] == "test-user"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. get_topic_memory
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetTopicMemory:
    def test_returns_none_for_unknown_topic(self, mem_db):
        assert get_topic_memory("never seen topic") is None

    def test_returns_dict_for_known_topic(self, mem_db):
        _insert_session(mem_db, "RAG", "deep_research")
        result = get_topic_memory("RAG")
        assert isinstance(result, dict)

    def test_result_has_all_required_fields(self, mem_db):
        _insert_session(mem_db, "RAG", "deep_research")
        result = get_topic_memory("RAG")
        for field in (
            "topic", "topic_key", "activities",
            "has_deep_research", "has_learning_path",
            "has_topic_expansion", "has_github_repos",
            "times_explored", "first_explored_at", "last_activity_at",
        ):
            assert field in result, f"Missing field: {field}"

    def test_activities_list_contains_dicts(self, mem_db):
        _insert_session(mem_db, "RAG", "deep_research")
        result = get_topic_memory("RAG")
        assert all("activity" in a and "recorded_at" in a for a in result["activities"])

    def test_newest_activity_first(self, mem_db):
        _insert_session(mem_db, "RAG", "deep_research",   hours_ago=10)
        _insert_session(mem_db, "RAG", "learning_path",   hours_ago=1)
        result = get_topic_memory("RAG")
        assert result["activities"][0]["activity"] == "learning_path"

    def test_has_flags_true_when_activity_present(self, mem_db):
        _insert_session(mem_db, "RAG", "deep_research")
        _insert_session(mem_db, "RAG", "learning_path")
        result = get_topic_memory("RAG")
        assert result["has_deep_research"]  is True
        assert result["has_learning_path"]  is True
        assert result["has_topic_expansion"] is False
        assert result["has_github_repos"]    is False

    def test_times_explored_counts_all_events(self, mem_db):
        for _ in range(3):
            _insert_session(mem_db, "RAG", "deep_research")
        result = get_topic_memory("RAG")
        assert result["times_explored"] == 3

    def test_first_explored_at_is_oldest(self, mem_db):
        ts_old = _insert_session(mem_db, "RAG", "deep_research", hours_ago=24)
        _insert_session(mem_db, "RAG", "learning_path",  hours_ago=1)
        result = get_topic_memory("RAG")
        assert result["first_explored_at"] == ts_old

    def test_last_activity_at_is_newest(self, mem_db):
        _insert_session(mem_db, "RAG", "deep_research", hours_ago=24)
        ts_new = _insert_session(mem_db, "RAG", "learning_path", hours_ago=1)
        result = get_topic_memory("RAG")
        assert result["last_activity_at"] == ts_new

    def test_case_insensitive_lookup(self, mem_db):
        _insert_session(mem_db, "RAG", "deep_research")
        assert get_topic_memory("rag")           is not None
        assert get_topic_memory("RAG")           is not None
        assert get_topic_memory("Rag Pipelines") is None  # different topic


# ═══════════════════════════════════════════════════════════════════════════════
# 3. list_explored_topics
# ═══════════════════════════════════════════════════════════════════════════════

class TestListExploredTopics:
    def test_empty_db_returns_empty_list(self, mem_db):
        assert list_explored_topics() == []

    def test_returns_list_of_dicts(self, mem_db):
        _insert_session(mem_db, "RAG", "deep_research")
        result = list_explored_topics()
        assert isinstance(result, list)
        assert isinstance(result[0], dict)

    def test_each_entry_has_required_fields(self, mem_db):
        _insert_session(mem_db, "RAG", "deep_research")
        entry = list_explored_topics()[0]
        for field in ("topic", "last_activity_at", "activity_count", "activities_done"):
            assert field in entry

    def test_most_recently_active_first(self, mem_db):
        _insert_session(mem_db, "RAG",              "deep_research", hours_ago=10)
        _insert_session(mem_db, "Vector Databases", "learning_path", hours_ago=1)
        result = list_explored_topics()
        assert result[0]["topic"] == "Vector Databases"

    def test_limit_respected(self, mem_db):
        for topic in ("RAG", "LLM", "Embeddings", "Transformers"):
            _insert_session(mem_db, topic, "deep_research")
        result = list_explored_topics(limit=2)
        assert len(result) == 2

    def test_activities_done_is_deduplicated(self, mem_db):
        _insert_session(mem_db, "RAG", "deep_research")
        _insert_session(mem_db, "RAG", "deep_research")  # same activity twice
        entry = list_explored_topics()[0]
        assert entry["activities_done"] == ["deep_research"]

    def test_activity_count_includes_duplicates(self, mem_db):
        _insert_session(mem_db, "RAG", "deep_research")
        _insert_session(mem_db, "RAG", "deep_research")
        entry = list_explored_topics()[0]
        assert entry["activity_count"] == 2

    def test_multiple_topics_listed_separately(self, mem_db):
        _insert_session(mem_db, "RAG",    "deep_research")
        _insert_session(mem_db, "LLM",    "learning_path")
        topics = [r["topic"] for r in list_explored_topics()]
        assert "RAG" in topics
        assert "LLM" in topics


# ═══════════════════════════════════════════════════════════════════════════════
# 4. is_activity_recorded
# ═══════════════════════════════════════════════════════════════════════════════

class TestIsActivityRecorded:
    def test_returns_false_for_unknown_topic(self, mem_db):
        assert is_activity_recorded("never seen", "deep_research") is False

    def test_returns_true_when_activity_exists(self, mem_db):
        _insert_session(mem_db, "RAG", "deep_research")
        assert is_activity_recorded("RAG", "deep_research") is True

    def test_returns_false_for_different_activity(self, mem_db):
        _insert_session(mem_db, "RAG", "deep_research")
        assert is_activity_recorded("RAG", "learning_path") is False

    def test_case_insensitive(self, mem_db):
        _insert_session(mem_db, "rag", "deep_research")
        assert is_activity_recorded("RAG",           "deep_research") is True
        assert is_activity_recorded("Rag",           "deep_research") is True
        assert is_activity_recorded("rag pipelines", "deep_research") is False

    def test_true_for_all_four_activity_types(self, mem_db):
        for activity in ACTIVITY_TYPES:
            _insert_session(mem_db, "RAG", activity)
            assert is_activity_recorded("RAG", activity) is True

    def test_multiple_occurrences_still_returns_true(self, mem_db):
        _insert_session(mem_db, "RAG", "deep_research")
        _insert_session(mem_db, "RAG", "deep_research")
        assert is_activity_recorded("RAG", "deep_research") is True


# ═══════════════════════════════════════════════════════════════════════════════
# 5. get_research_context
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetResearchContext:
    def test_never_returns_none(self, mem_db):
        result = get_research_context("never seen topic")
        assert result is not None

    def test_returns_dict(self, mem_db):
        assert isinstance(get_research_context("RAG"), dict)

    def test_all_false_for_unknown_topic(self, mem_db):
        ctx = get_research_context("RAG")
        assert ctx["has_deep_research"]   is False
        assert ctx["has_learning_path"]   is False
        assert ctx["has_topic_expansion"] is False
        assert ctx["has_github_repos"]    is False

    def test_times_explored_zero_for_unknown(self, mem_db):
        ctx = get_research_context("RAG")
        assert ctx["times_explored"] == 0

    def test_recommended_next_has_all_activities_for_unknown(self, mem_db):
        ctx = get_research_context("RAG")
        assert set(ctx["recommended_next"]) == ACTIVITY_TYPES

    def test_has_flags_correct_for_known_topic(self, mem_db):
        _insert_session(mem_db, "RAG", "deep_research")
        _insert_session(mem_db, "RAG", "learning_path")
        ctx = get_research_context("RAG")
        assert ctx["has_deep_research"] is True
        assert ctx["has_learning_path"] is True
        assert ctx["has_topic_expansion"] is False
        assert ctx["has_github_repos"]    is False

    def test_recommended_next_excludes_done_activities(self, mem_db):
        _insert_session(mem_db, "RAG", "deep_research")
        _insert_session(mem_db, "RAG", "learning_path")
        ctx = get_research_context("RAG")
        assert "deep_research"   not in ctx["recommended_next"]
        assert "learning_path"   not in ctx["recommended_next"]
        assert "topic_expansion" in  ctx["recommended_next"]
        assert "github_repos"    in  ctx["recommended_next"]

    def test_recommended_next_empty_when_all_done(self, mem_db):
        for activity in ACTIVITY_TYPES:
            _insert_session(mem_db, "RAG", activity)
        ctx = get_research_context("RAG")
        assert ctx["recommended_next"] == []

    def test_times_explored_matches_event_count(self, mem_db):
        for _ in range(4):
            _insert_session(mem_db, "RAG", "deep_research")
        ctx = get_research_context("RAG")
        assert ctx["times_explored"] == 4

    def test_nulls_for_timestamps_on_unknown_topic(self, mem_db):
        ctx = get_research_context("RAG")
        assert ctx["first_explored_at"] is None
        assert ctx["last_activity_at"]  is None

    def test_topic_preserved(self, mem_db):
        ctx = get_research_context("RAG Pipelines")
        assert ctx["topic"] == "RAG Pipelines"

    def test_has_all_required_keys(self, mem_db):
        ctx = get_research_context("RAG")
        for key in (
            "topic", "times_explored",
            "has_deep_research", "has_learning_path",
            "has_topic_expansion", "has_github_repos",
            "first_explored_at", "last_activity_at",
            "recommended_next",
        ):
            assert key in ctx, f"Missing key: {key}"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. HTTP endpoints
# ═══════════════════════════════════════════════════════════════════════════════

class TestSessionMemoryEndpoints:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        return TestClient(app)

    def _memory(self, topic="RAG"):
        return {
            "topic":               topic,
            "topic_key":           topic.lower(),
            "activities":          [{"activity": "deep_research", "recorded_at": "2026-05-15 10:00:00"}],
            "has_deep_research":   True,
            "has_learning_path":   False,
            "has_topic_expansion": False,
            "has_github_repos":    False,
            "times_explored":      1,
            "first_explored_at":   "2026-05-15 10:00:00",
            "last_activity_at":    "2026-05-15 10:00:00",
        }

    def _context(self, topic="RAG"):
        return {
            "topic":               topic,
            "times_explored":      1,
            "has_deep_research":   True,
            "has_learning_path":   False,
            "has_topic_expansion": False,
            "has_github_repos":    False,
            "first_explored_at":   "2026-05-15 10:00:00",
            "last_activity_at":    "2026-05-15 10:00:00",
            "recommended_next":    ["github_repos", "learning_path", "topic_expansion"],
        }

    # GET /session-memory

    def test_list_returns_200(self, client):
        with patch("backend.main.list_explored_topics", return_value=[]):
            resp = client.get("/session-memory")
        assert resp.status_code == 200

    def test_list_returns_list(self, client):
        summary = {
            "topic": "RAG", "last_activity_at": "2026-05-15 10:00:00",
            "activity_count": 1, "activities_done": ["deep_research"],
        }
        with patch("backend.main.list_explored_topics", return_value=[summary]):
            resp = client.get("/session-memory")
        assert isinstance(resp.json(), list)

    def test_list_empty_db_returns_empty(self, client):
        with patch("backend.main.list_explored_topics", return_value=[]):
            resp = client.get("/session-memory")
        assert resp.json() == []

    def test_list_passes_limit_param(self, client):
        with patch("backend.main.list_explored_topics", return_value=[]) as mock_list:
            client.get("/session-memory?limit=10")
        mock_list.assert_called_once_with(limit=10)

    # GET /session-memory/{topic}

    def test_get_topic_returns_200_on_hit(self, client):
        with patch("backend.main.get_topic_memory", return_value=self._memory()):
            resp = client.get("/session-memory/RAG")
        assert resp.status_code == 200

    def test_get_topic_returns_404_on_miss(self, client):
        with patch("backend.main.get_topic_memory", return_value=None):
            resp = client.get("/session-memory/unknown")
        assert resp.status_code == 404

    def test_get_topic_has_all_fields(self, client):
        with patch("backend.main.get_topic_memory", return_value=self._memory()):
            resp = client.get("/session-memory/RAG")
        body = resp.json()
        for field in (
            "topic", "topic_key", "activities",
            "has_deep_research", "has_learning_path",
            "has_topic_expansion", "has_github_repos",
            "times_explored", "first_explored_at", "last_activity_at",
        ):
            assert field in body, f"Missing field: {field}"

    def test_get_topic_activities_is_list(self, client):
        with patch("backend.main.get_topic_memory", return_value=self._memory()):
            resp = client.get("/session-memory/RAG")
        assert isinstance(resp.json()["activities"], list)

    # GET /session-memory/{topic}/context

    def test_context_returns_200(self, client):
        with patch("backend.main.get_research_context", return_value=self._context()):
            resp = client.get("/session-memory/RAG/context")
        assert resp.status_code == 200

    def test_context_has_recommended_next(self, client):
        with patch("backend.main.get_research_context", return_value=self._context()):
            resp = client.get("/session-memory/RAG/context")
        assert "recommended_next" in resp.json()

    def test_context_returns_dict_even_for_unknown(self, client):
        ctx = {
            "topic": "unknown", "times_explored": 0,
            "has_deep_research": False, "has_learning_path": False,
            "has_topic_expansion": False, "has_github_repos": False,
            "first_explored_at": None, "last_activity_at": None,
            "recommended_next": sorted(ACTIVITY_TYPES),
        }
        with patch("backend.main.get_research_context", return_value=ctx):
            resp = client.get("/session-memory/unknown/context")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# 7. record_activity hooks wired into POST endpoints
# ═══════════════════════════════════════════════════════════════════════════════

class TestMainHooks:
    @pytest.fixture
    def client(self):
        # Chat-R7a: these endpoints now require Depends(get_current_user) —
        # they write to research_sessions, which record_activity scopes by
        # user_id (the fix for the cross-user personalization leak). Same
        # dependency-override pattern as test_chat.py's authenticated client.
        from fastapi.testclient import TestClient
        from backend.main import app, get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "test-user", "email": "test@example.com"}
        try:
            yield TestClient(app)
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    def _good_path(self):
        return {
            "topic": "RAG", "learning_stage": "beginner",
            "beginner": [], "intermediate": [], "advanced": [],
            "repositories": [],
            "generated_at": "2026-05-15T10:00:00",
        }

    def _good_expansion(self):
        return {
            "topic": "RAG",
            "prerequisites": [], "related_topics": [],
            "advanced_follow_ups": [], "learning_progression": ["RAG"],
            "progression_rationale": "rationale",
            "generated_at": "2026-05-15T10:00:00",
        }

    def test_learning_path_post_records_activity(self, client):
        with patch("backend.main.get_learning_path", return_value=self._good_path()), \
             patch("backend.main.get_topic_repos", return_value=[]), \
             patch("backend.main.record_activity") as mock_record:
            client.post("/learning-path", json={"topic": "RAG"})
        mock_record.assert_called_once_with("RAG", "learning_path", "test-user")

    def test_topic_expansion_post_records_activity(self, client):
        with patch("backend.main.expand_topic", return_value=self._good_expansion()), \
             patch("backend.main.record_activity") as mock_record:
            client.post("/topic-expansion", json={"topic": "RAG"})
        mock_record.assert_called_once_with("RAG", "topic_expansion", "test-user")

    def test_repos_post_records_activity(self, client):
        with patch("backend.main.get_topic_repos", return_value=[]), \
             patch("backend.main.record_activity") as mock_record:
            client.post("/repos", json={"topic": "RAG"})
        mock_record.assert_called_once_with("RAG", "github_repos", "test-user")

    def test_record_failure_does_not_break_endpoint(self, client):
        with patch("backend.main.get_topic_repos", return_value=[]), \
             patch("backend.main.record_activity", side_effect=RuntimeError("db error")):
            resp = client.post("/repos", json={"topic": "RAG"})
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Integration — real DB round-trips (gated -m integration)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.integration
class TestSessionMemoryIntegration:
    def test_full_record_and_retrieve(self, mem_db):
        record_activity("RAG Pipelines", "topic_expansion", "test-user")
        record_activity("RAG Pipelines", "learning_path", "test-user")
        memory = get_topic_memory("RAG Pipelines")
        assert memory is not None
        assert memory["times_explored"] == 2
        assert memory["has_topic_expansion"] is True
        assert memory["has_learning_path"] is True

    def test_redundancy_check_via_is_activity_recorded(self, mem_db):
        assert is_activity_recorded("RAG", "topic_expansion") is False
        record_activity("RAG", "topic_expansion", "test-user")
        assert is_activity_recorded("RAG", "topic_expansion") is True

    def test_list_explored_topics_ordering(self, mem_db):
        # Use explicit timestamps so ordering is deterministic regardless of wall-clock speed
        _insert_session(mem_db, "Embeddings",   "deep_research", hours_ago=10)
        _insert_session(mem_db, "Transformers", "learning_path", hours_ago=1)
        topics = [r["topic"] for r in list_explored_topics()]
        # Transformers was recorded more recently — must appear first
        assert topics.index("Transformers") < topics.index("Embeddings")

    def test_research_context_recommended_next_updates(self, mem_db):
        ctx_before = get_research_context("RAG")
        assert "github_repos" in ctx_before["recommended_next"]

        record_activity("RAG", "github_repos", "test-user")
        record_activity("RAG", "learning_path", "test-user")
        ctx_after = get_research_context("RAG")
        assert "github_repos"    not in ctx_after["recommended_next"]
        assert "learning_path"   not in ctx_after["recommended_next"]
        assert "topic_expansion" in     ctx_after["recommended_next"]
