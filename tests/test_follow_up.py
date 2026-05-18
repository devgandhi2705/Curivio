"""
Tests for the follow-up learning recommendations feature.

Coverage
--------
  TestGetRecommendations       — core function, level prioritisation, filtering
  TestEmptyAndEdgeCases        — empty topic, no expansion, DB errors
  TestLevelLimits              — cap enforcement per learner level
  TestExploredFiltering        — already-explored topics removed
  TestBuildItems               — reason string formatting
  TestChatServiceRecommends    — chat() returns recommendations key
  TestChatEndpointRecommends   — POST /chat response includes recommendations
  TestRecommendationIntegration — integration test with real DB (marked)
"""

from __future__ import annotations

import json
import sqlite3
import pytest
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def db():
    """In-memory SQLite with tables needed by follow-up and chat services."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS topic_expansions (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            topic          TEXT    NOT NULL,
            topic_key      TEXT    NOT NULL UNIQUE,
            expansion_json TEXT    NOT NULL,
            generated_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS research_sessions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            topic       TEXT NOT NULL,
            topic_key   TEXT NOT NULL,
            activity    TEXT,
            recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS user_preferences (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            topic                 TEXT NOT NULL UNIQUE,
            topic_key             TEXT NOT NULL UNIQUE,
            preference_score      REAL NOT NULL DEFAULT 0.0,
            times_liked           INTEGER NOT NULL DEFAULT 0,
            times_disliked        INTEGER NOT NULL DEFAULT 0,
            difficulty_preference TEXT
        );
        CREATE TABLE IF NOT EXISTS chat_messages (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id   TEXT NOT NULL,
            role         TEXT NOT NULL,
            content      TEXT NOT NULL,
            topic_hint   TEXT,
            created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    return conn


@pytest.fixture()
def patch_db(db, monkeypatch):
    import backend.utils.db as _db
    import backend.services.topic_expansion_service as _tes
    import backend.services.chat_service as _cs
    cm = MagicMock(return_value=db)
    monkeypatch.setattr(_db,  "get_connection", cm)
    monkeypatch.setattr(_tes, "get_connection", cm)
    monkeypatch.setattr(_cs,  "get_connection", cm)
    return db


def _insert_expansion(db, topic: str, expansion: dict):
    key = topic.strip().lower()
    db.execute(
        "INSERT INTO topic_expansions (topic, topic_key, expansion_json, generated_at) "
        "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
        (topic, key, json.dumps(expansion)),
    )
    db.commit()


def _make_expansion(
    topic="Vector Databases",
    prerequisites=None,
    related=None,
    advanced=None,
) -> dict:
    return {
        "topic":               topic,
        "prerequisites":       prerequisites if prerequisites is not None else ["Embeddings", "Linear Algebra"],
        "related_topics":      related       if related       is not None else ["RAG Pipelines", "Retrieval Optimization", "FAISS"],
        "advanced_follow_ups": advanced      if advanced      is not None else ["Hybrid Search", "Sparse-Dense Fusion"],
        "learning_progression": [topic],
        "progression_rationale": "",
        "generated_at":        "2026-01-01T00:00:00",
    }


# ─────────────────────────────────────────────────────────────────────────────
# TestGetRecommendations
# ─────────────────────────────────────────────────────────────────────────────

class TestGetRecommendations:
    def test_returns_dict_with_required_keys(self, patch_db):
        _insert_expansion(patch_db, "Vector Databases", _make_expansion())
        from backend.services.follow_up_service import get_recommendations
        result = get_recommendations("Vector Databases")
        assert set(result.keys()) == {
            "based_on_topic", "source", "next_topics", "prerequisites", "advanced_topics"
        }

    def test_stored_source_when_expansion_exists(self, patch_db):
        _insert_expansion(patch_db, "Vector Databases", _make_expansion())
        from backend.services.follow_up_service import get_recommendations
        result = get_recommendations("Vector Databases")
        assert result["source"] == "stored"

    def test_based_on_topic_set(self, patch_db):
        _insert_expansion(patch_db, "Vector Databases", _make_expansion())
        from backend.services.follow_up_service import get_recommendations
        result = get_recommendations("Vector Databases")
        assert result["based_on_topic"] == "Vector Databases"

    def test_next_topics_populated(self, patch_db):
        _insert_expansion(patch_db, "Vector Databases", _make_expansion())
        from backend.services.follow_up_service import get_recommendations
        result = get_recommendations("Vector Databases")
        assert len(result["next_topics"]) > 0

    def test_items_have_topic_and_reason(self, patch_db):
        _insert_expansion(patch_db, "Vector Databases", _make_expansion())
        from backend.services.follow_up_service import get_recommendations
        result = get_recommendations("Vector Databases")
        for item in result["next_topics"]:
            assert "topic" in item and "reason" in item
            assert item["topic"]
            assert item["reason"]

    def test_reason_contains_base_topic(self, patch_db):
        _insert_expansion(patch_db, "Vector Databases", _make_expansion())
        from backend.services.follow_up_service import get_recommendations
        result = get_recommendations("Vector Databases")
        for item in result["next_topics"]:
            assert "Vector Databases" in item["reason"]


# ─────────────────────────────────────────────────────────────────────────────
# TestEmptyAndEdgeCases
# ─────────────────────────────────────────────────────────────────────────────

class TestEmptyAndEdgeCases:
    def test_empty_topic_returns_empty(self):
        from backend.services.follow_up_service import get_recommendations
        result = get_recommendations("")
        assert result["source"] == "empty"
        assert result["next_topics"] == []
        assert result["prerequisites"] == []
        assert result["advanced_topics"] == []

    def test_whitespace_topic_returns_empty(self):
        from backend.services.follow_up_service import get_recommendations
        result = get_recommendations("   ")
        assert result["source"] == "empty"

    def test_no_expansion_returns_empty(self, patch_db):
        from backend.services.follow_up_service import get_recommendations
        result = get_recommendations("Unknown Topic XYZ")
        assert result["source"] == "empty"
        assert result["next_topics"] == []

    def test_db_error_returns_empty(self, monkeypatch):
        import backend.utils.db as _db
        monkeypatch.setattr(_db, "get_connection", MagicMock(side_effect=RuntimeError("db down")))
        from backend.services.follow_up_service import get_recommendations
        result = get_recommendations("Vector Databases")
        assert result["source"] == "empty"

    def test_expansion_with_empty_lists_returns_empty(self, patch_db):
        _insert_expansion(patch_db, "Empty Topic", _make_expansion(
            topic="Empty Topic", prerequisites=[], related=[], advanced=[]
        ))
        from backend.services.follow_up_service import get_recommendations
        result = get_recommendations("Empty Topic")
        assert result["source"] == "empty"
        assert result["next_topics"] == []

    def test_none_explored_topics_accepted(self, patch_db):
        _insert_expansion(patch_db, "Vector Databases", _make_expansion())
        from backend.services.follow_up_service import get_recommendations
        result = get_recommendations("Vector Databases", explored_topics=None)
        assert result["source"] == "stored"


# ─────────────────────────────────────────────────────────────────────────────
# TestLevelLimits
# ─────────────────────────────────────────────────────────────────────────────

class TestLevelLimits:
    def _setup(self, db):
        expansion = _make_expansion(
            prerequisites=["A", "B", "C"],
            related=["R1", "R2", "R3", "R4"],
            advanced=["Adv1", "Adv2", "Adv3", "Adv4"],
        )
        _insert_expansion(db, "Vector Databases", expansion)

    def test_beginner_no_advanced_topics(self, patch_db):
        self._setup(patch_db)
        from backend.services.follow_up_service import get_recommendations
        result = get_recommendations("Vector Databases", learner_level="beginner")
        assert result["advanced_topics"] == []

    def test_beginner_max_2_next_topics(self, patch_db):
        self._setup(patch_db)
        from backend.services.follow_up_service import get_recommendations
        result = get_recommendations("Vector Databases", learner_level="beginner")
        assert len(result["next_topics"]) <= 2

    def test_beginner_max_2_prerequisites(self, patch_db):
        self._setup(patch_db)
        from backend.services.follow_up_service import get_recommendations
        result = get_recommendations("Vector Databases", learner_level="beginner")
        assert len(result["prerequisites"]) <= 2

    def test_advanced_no_prerequisites(self, patch_db):
        self._setup(patch_db)
        from backend.services.follow_up_service import get_recommendations
        result = get_recommendations("Vector Databases", learner_level="advanced")
        assert result["prerequisites"] == []

    def test_advanced_max_3_advanced_topics(self, patch_db):
        self._setup(patch_db)
        from backend.services.follow_up_service import get_recommendations
        result = get_recommendations("Vector Databases", learner_level="advanced")
        assert len(result["advanced_topics"]) <= 3

    def test_intermediate_has_all_categories(self, patch_db):
        self._setup(patch_db)
        from backend.services.follow_up_service import get_recommendations
        result = get_recommendations("Vector Databases", learner_level="intermediate")
        assert len(result["next_topics"]) > 0
        assert len(result["prerequisites"]) > 0
        assert len(result["advanced_topics"]) > 0

    def test_intermediate_max_3_next(self, patch_db):
        self._setup(patch_db)
        from backend.services.follow_up_service import get_recommendations
        result = get_recommendations("Vector Databases", learner_level="intermediate")
        assert len(result["next_topics"]) <= 3

    def test_intermediate_max_1_prerequisite(self, patch_db):
        self._setup(patch_db)
        from backend.services.follow_up_service import get_recommendations
        result = get_recommendations("Vector Databases", learner_level="intermediate")
        assert len(result["prerequisites"]) <= 1

    def test_intermediate_max_2_advanced(self, patch_db):
        self._setup(patch_db)
        from backend.services.follow_up_service import get_recommendations
        result = get_recommendations("Vector Databases", learner_level="intermediate")
        assert len(result["advanced_topics"]) <= 2

    def test_unknown_level_defaults_to_intermediate(self, patch_db):
        self._setup(patch_db)
        from backend.services.follow_up_service import get_recommendations
        result_unknown = get_recommendations("Vector Databases", learner_level="expert")
        result_inter   = get_recommendations("Vector Databases", learner_level="intermediate")
        assert len(result_unknown["next_topics"])     == len(result_inter["next_topics"])
        assert len(result_unknown["prerequisites"])   == len(result_inter["prerequisites"])
        assert len(result_unknown["advanced_topics"]) == len(result_inter["advanced_topics"])


# ─────────────────────────────────────────────────────────────────────────────
# TestExploredFiltering
# ─────────────────────────────────────────────────────────────────────────────

class TestExploredFiltering:
    def test_explored_next_topics_filtered_out(self, patch_db):
        expansion = _make_expansion(related=["RAG Pipelines", "FAISS", "Pinecone"])
        _insert_expansion(patch_db, "Vector Databases", expansion)
        from backend.services.follow_up_service import get_recommendations
        result = get_recommendations(
            "Vector Databases",
            explored_topics=["RAG Pipelines", "FAISS"],
        )
        topics = [i["topic"] for i in result["next_topics"]]
        assert "RAG Pipelines" not in topics
        assert "FAISS" not in topics
        assert "Pinecone" in topics

    def test_explored_prerequisites_filtered_out(self, patch_db):
        expansion = _make_expansion(prerequisites=["Embeddings", "Linear Algebra"])
        _insert_expansion(patch_db, "Vector Databases", expansion)
        from backend.services.follow_up_service import get_recommendations
        result = get_recommendations(
            "Vector Databases",
            explored_topics=["Embeddings"],
        )
        prereq_topics = [i["topic"] for i in result["prerequisites"]]
        assert "Embeddings" not in prereq_topics

    def test_explored_advanced_filtered_out(self, patch_db):
        expansion = _make_expansion(advanced=["Hybrid Search", "Sparse-Dense Fusion"])
        _insert_expansion(patch_db, "Vector Databases", expansion)
        from backend.services.follow_up_service import get_recommendations
        result = get_recommendations(
            "Vector Databases",
            explored_topics=["Hybrid Search"],
            learner_level="advanced",
        )
        adv_topics = [i["topic"] for i in result["advanced_topics"]]
        assert "Hybrid Search" not in adv_topics

    def test_case_insensitive_filtering(self, patch_db):
        expansion = _make_expansion(related=["RAG Pipelines"])
        _insert_expansion(patch_db, "Vector Databases", expansion)
        from backend.services.follow_up_service import get_recommendations
        result = get_recommendations(
            "Vector Databases",
            explored_topics=["rag pipelines"],   # lower-case
        )
        topics = [i["topic"] for i in result["next_topics"]]
        assert "RAG Pipelines" not in topics

    def test_all_filtered_returns_empty_source(self, patch_db):
        expansion = _make_expansion(
            prerequisites=["Embeddings"],
            related=["RAG Pipelines"],
            advanced=["Hybrid Search"],
        )
        _insert_expansion(patch_db, "Vector Databases", expansion)
        from backend.services.follow_up_service import get_recommendations
        result = get_recommendations(
            "Vector Databases",
            explored_topics=["Embeddings", "RAG Pipelines", "Hybrid Search"],
            learner_level="intermediate",
        )
        assert result["source"] == "empty"


# ─────────────────────────────────────────────────────────────────────────────
# TestBuildItems
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildItems:
    def test_build_items_returns_correct_shape(self):
        from backend.services.follow_up_service import _build_items
        items = _build_items(["RAG Pipelines", "FAISS"], "Related to {topic}.", "Vector Databases")
        assert len(items) == 2
        assert items[0] == {"topic": "RAG Pipelines", "reason": "Related to Vector Databases."}

    def test_build_items_empty_list(self):
        from backend.services.follow_up_service import _build_items
        assert _build_items([], "Reason {topic}.", "Topic") == []

    def test_normalise_set_lowercases(self):
        from backend.services.follow_up_service import _normalise_set
        result = _normalise_set(["RAG Pipelines", "FAISS", "  Embeddings  "])
        assert "rag pipelines" in result
        assert "faiss" in result
        assert "embeddings" in result

    def test_filter_explored_removes_matched(self):
        from backend.services.follow_up_service import _filter_explored, _normalise_set
        items    = ["RAG Pipelines", "FAISS", "Pinecone"]
        explored = _normalise_set(["rag pipelines"])
        result   = _filter_explored(items, explored)
        assert result == ["FAISS", "Pinecone"]

    def test_limits_for_beginner(self):
        from backend.services.follow_up_service import _limits_for_level
        next_l, prereq_l, adv_l = _limits_for_level("beginner")
        assert adv_l == 0
        assert next_l <= 2 and prereq_l <= 2

    def test_limits_for_advanced(self):
        from backend.services.follow_up_service import _limits_for_level
        next_l, prereq_l, adv_l = _limits_for_level("advanced")
        assert prereq_l == 0
        assert adv_l >= 3

    def test_limits_for_intermediate(self):
        from backend.services.follow_up_service import _limits_for_level
        next_l, prereq_l, adv_l = _limits_for_level("intermediate")
        assert next_l >= 3
        assert prereq_l >= 1
        assert adv_l >= 2


# ─────────────────────────────────────────────────────────────────────────────
# TestChatServiceRecommends
# ─────────────────────────────────────────────────────────────────────────────

class TestChatServiceRecommends:
    """chat() returns a recommendations key with correct structure."""

    def _make_context(self):
        return {
            "user_profile":       {"top_interests": []},
            "research":           {},
            "session":            {},
            "conversation_memory": {"message_count": 0, "session_turns": 0,
                                    "topics_discussed": [], "last_user_messages": []},
            "exploration_breadth": {"total_explored": 0, "all_topics": [],
                                    "recently_explored": [], "deep_dived_topics": []},
            "preference_snapshot": {},
            "learner_profile":    {"inferred_level": "intermediate", "directive": ""},
        }

    def test_recommendations_key_present(self, patch_db):
        from backend.services.chat_service import chat
        ctx = self._make_context()
        with patch("backend.services.chat_service.inject_memory", return_value=ctx), \
             patch("backend.services.grok_service.ask_grok_chat", return_value="Hello"), \
             patch("backend.services.topic_expansion_service.get_stored_expansion", return_value=None):
            result = chat("sess-1", "What is machine learning?")
        assert "recommendations" in result

    def test_recommendations_has_expected_keys(self, patch_db):
        from backend.services.chat_service import chat
        ctx = self._make_context()
        with patch("backend.services.chat_service.inject_memory", return_value=ctx), \
             patch("backend.services.grok_service.ask_grok_chat", return_value="Hi"), \
             patch("backend.services.topic_expansion_service.get_stored_expansion", return_value=None):
            result = chat("sess-2", "Tell me about transformers")
        rec = result["recommendations"]
        assert "source" in rec
        assert "next_topics" in rec
        assert "prerequisites" in rec
        assert "advanced_topics" in rec

    def test_recommendations_populated_when_expansion_exists(self, patch_db):
        _insert_expansion(patch_db, "Transformers", _make_expansion(
            topic="Transformers",
            prerequisites=["Attention Mechanism"],
            related=["BERT", "GPT"],
            advanced=["Mixture of Experts"],
        ))
        from backend.services.chat_service import chat
        ctx = self._make_context()
        ctx["learner_profile"]["inferred_level"] = "intermediate"
        with patch("backend.services.chat_service.inject_memory", return_value=ctx), \
             patch("backend.services.grok_service.ask_grok_chat", return_value="Transformers are..."):
            result = chat("sess-3", "Explain transformers", topic_hint="Transformers")
        rec = result["recommendations"]
        assert rec["source"] == "stored"
        assert len(rec["next_topics"]) > 0

    def test_chat_error_in_recommendations_does_not_fail_chat(self, patch_db):
        from backend.services.chat_service import chat
        ctx = self._make_context()
        with patch("backend.services.chat_service.inject_memory", return_value=ctx), \
             patch("backend.services.grok_service.ask_grok_chat", return_value="Response"), \
             patch("backend.services.topic_expansion_service.get_stored_expansion",
                   side_effect=RuntimeError("oops")):
            result = chat("sess-4", "What is RAG?")
        # chat() must succeed even when recommendations fail
        assert result["response"] == "Response"
        assert result["recommendations"]["source"] == "empty"

    def test_explored_topics_from_context_passed_to_recommendations(self, patch_db):
        _insert_expansion(patch_db, "RAG", _make_expansion(
            topic="RAG",
            related=["Pinecone", "FAISS"],
        ))
        from backend.services.chat_service import chat
        ctx = self._make_context()
        ctx["exploration_breadth"]["all_topics"] = ["Pinecone"]
        with patch("backend.services.chat_service.inject_memory", return_value=ctx), \
             patch("backend.services.grok_service.ask_grok_chat", return_value="RAG is..."):
            result = chat("sess-5", "Explain RAG", topic_hint="RAG")
        next_topics = [i["topic"] for i in result["recommendations"]["next_topics"]]
        assert "Pinecone" not in next_topics


# ─────────────────────────────────────────────────────────────────────────────
# TestChatEndpointRecommends
# ─────────────────────────────────────────────────────────────────────────────

class TestChatEndpointRecommends:
    """POST /chat endpoint returns recommendations in the JSON response."""

    def _chat_result(self, recommendations_source="empty"):
        return {
            "session_id":  "sess-ep",
            "message_id":  1,
            "response":    "Great question!",
            "topic_hint":  "Machine Learning",
            "recommendations": {
                "based_on_topic":  "Machine Learning",
                "source":          recommendations_source,
                "next_topics":     [{"topic": "Deep Learning", "reason": "Next step."}],
                "prerequisites":   [],
                "advanced_topics": [],
            },
            "context_used": {
                "has_deep_research":   False,
                "has_learning_path":   False,
                "has_topic_expansion": False,
                "has_github_repos":    False,
                "interests_count":     0,
                "history_turns":       0,
                "topics_in_session":   0,
                "total_topics_explored": 0,
            },
            "created_at": "2026-01-01 00:00:00",
        }

    def test_recommendations_field_in_response(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        client = TestClient(app)
        with patch("backend.main.chat_with_ai", return_value=self._chat_result()):
            resp = client.post("/chat", json={"session_id": "s1", "message": "What is ML?"})
        assert resp.status_code == 200
        data = resp.json()
        assert "recommendations" in data

    def test_recommendations_next_topics_serialised(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        client = TestClient(app)
        with patch("backend.main.chat_with_ai", return_value=self._chat_result("stored")):
            resp = client.post("/chat", json={"session_id": "s1", "message": "What is ML?"})
        rec = resp.json()["recommendations"]
        assert rec["source"] == "stored"
        assert rec["next_topics"][0]["topic"] == "Deep Learning"

    def test_null_recommendations_accepted(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        client = TestClient(app)
        result = self._chat_result()
        result["recommendations"] = None
        with patch("backend.main.chat_with_ai", return_value=result):
            resp = client.post("/chat", json={"session_id": "s1", "message": "What is ML?"})
        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# TestRecommendationIntegration
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestRecommendationIntegration:
    """Single real-DB integration test. Skipped unless -m integration is passed."""

    def test_recommendations_end_to_end(self, patch_db):
        _insert_expansion(patch_db, "Vector Databases", _make_expansion())
        from backend.services.follow_up_service import get_recommendations
        result = get_recommendations("Vector Databases", learner_level="intermediate")
        assert result["source"] == "stored"
        assert len(result["next_topics"]) > 0
        for item in result["next_topics"] + result["prerequisites"] + result["advanced_topics"]:
            assert item["topic"] and item["reason"]
