"""
Tests for research-session continuity.

Coverage
--------
  TestRecordConcepts             — upsert, increment, empty-input guards
  TestRecordRecommendations      — persist recs, skip non-stored, dedup
  TestGetContinuityContext       — retrieval, empty topic, cross-session stats
  TestExtractConceptsFromContext — helper that pulls concepts from context dict
  TestContinuityPromptSection    — _build_continuity_section output
  TestContinuityInSystemPrompt   — section appears in build_system_prompt
  TestInjectMemoryIncludesContinuity — inject_memory returns continuity key
  TestChatServiceRecordsContinuity   — chat() calls record_concepts after turn
  TestContinuityIntegration      — integration test (marked, uses in-memory DB)
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
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS concept_memory (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            concept            TEXT    NOT NULL,
            concept_key        TEXT    NOT NULL,
            topic              TEXT,
            topic_key          TEXT,
            session_id         TEXT,
            times_explained    INTEGER NOT NULL DEFAULT 1,
            first_explained_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_explained_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_concept_memory_key
            ON concept_memory (concept_key);

        CREATE TABLE IF NOT EXISTS prior_recommendations (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      TEXT    NOT NULL,
            topic           TEXT    NOT NULL,
            topic_key       TEXT    NOT NULL,
            rec_type        TEXT    NOT NULL,
            recommended     TEXT    NOT NULL,
            recommended_key TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (topic_key, recommended_key)
        );
        CREATE INDEX IF NOT EXISTS idx_prior_recs_topic
            ON prior_recommendations (topic_key);

        CREATE TABLE IF NOT EXISTS chat_messages (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id   TEXT NOT NULL,
            role         TEXT NOT NULL,
            content      TEXT NOT NULL,
            topic_hint   TEXT,
            created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS user_preferences (
            id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT NOT NULL UNIQUE,
            topic_key TEXT NOT NULL UNIQUE, preference_score REAL DEFAULT 0.0,
            times_liked INTEGER DEFAULT 0, times_disliked INTEGER DEFAULT 0,
            difficulty_preference TEXT
        );
        CREATE TABLE IF NOT EXISTS research_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT NOT NULL,
            topic_key TEXT NOT NULL, activity TEXT,
            recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    return conn


@pytest.fixture()
def patch_db(db, monkeypatch):
    import backend.services.continuity_service as _cs
    import backend.services.chat_service as _chat
    import backend.utils.db as _db
    cm = MagicMock(return_value=db)
    monkeypatch.setattr(_cs,   "get_connection", cm)
    monkeypatch.setattr(_chat, "get_connection", cm)
    monkeypatch.setattr(_db,   "get_connection", cm)
    return db


def _base_ctx():
    return {
        "user_profile":        {"top_interests": []},
        "research":            {},
        "session":             {},
        "conversation_memory": {"message_count": 0, "session_turns": 0,
                                "topics_discussed": [], "last_user_messages": []},
        "exploration_breadth": {"total_explored": 0, "all_topics": [],
                                "recently_explored": [], "deep_dived_topics": []},
        "preference_snapshot": {},
        "learner_profile":     {"inferred_level": "intermediate", "directive": ""},
        "continuity":          {},
    }


def _recs(topics: list[str], source: str = "stored") -> dict:
    return {
        "based_on_topic":  "Vector Databases",
        "source":          source,
        "next_topics":     [{"topic": t, "reason": "r"} for t in topics],
        "prerequisites":   [],
        "advanced_topics": [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# TestRecordConcepts
# ─────────────────────────────────────────────────────────────────────────────

class TestRecordConcepts:
    def test_inserts_concepts(self, patch_db):
        from backend.services.continuity_service import record_concepts
        record_concepts("Vector Databases", ["Embeddings", "ANN"], "sess-1")
        rows = patch_db.execute("SELECT concept FROM concept_memory").fetchall()
        concepts = [r["concept"] for r in rows]
        assert "Embeddings" in concepts
        assert "ANN" in concepts

    def test_increments_times_explained_on_conflict(self, patch_db):
        from backend.services.continuity_service import record_concepts
        record_concepts("Vector Databases", ["Embeddings"], "sess-1")
        record_concepts("Vector Databases", ["Embeddings"], "sess-2")
        row = patch_db.execute(
            "SELECT times_explained FROM concept_memory WHERE concept_key = 'embeddings'"
        ).fetchone()
        assert row["times_explained"] == 2

    def test_empty_topic_is_no_op(self, patch_db):
        from backend.services.continuity_service import record_concepts
        record_concepts("", ["Embeddings"], "sess-1")
        count = patch_db.execute("SELECT COUNT(*) AS n FROM concept_memory").fetchone()["n"]
        assert count == 0

    def test_empty_concepts_list_is_no_op(self, patch_db):
        from backend.services.continuity_service import record_concepts
        record_concepts("Vector Databases", [], "sess-1")
        count = patch_db.execute("SELECT COUNT(*) AS n FROM concept_memory").fetchone()["n"]
        assert count == 0

    def test_blank_concept_strings_skipped(self, patch_db):
        from backend.services.continuity_service import record_concepts
        record_concepts("Vector Databases", ["  ", "", "Embeddings"], "sess-1")
        rows = patch_db.execute("SELECT concept FROM concept_memory").fetchall()
        assert len(rows) == 1

    def test_session_id_stored(self, patch_db):
        from backend.services.continuity_service import record_concepts
        record_concepts("Vector Databases", ["HNSW"], "sess-abc")
        row = patch_db.execute("SELECT session_id FROM concept_memory WHERE concept_key='hnsw'").fetchone()
        assert row["session_id"] == "sess-abc"

    def test_db_error_does_not_raise(self, monkeypatch):
        import backend.services.continuity_service as _cs
        monkeypatch.setattr(_cs, "get_connection", MagicMock(side_effect=RuntimeError("db down")))
        from backend.services.continuity_service import record_concepts
        record_concepts("Vector Databases", ["Embeddings"])   # must not raise


# ─────────────────────────────────────────────────────────────────────────────
# TestRecordRecommendations
# ─────────────────────────────────────────────────────────────────────────────

class TestRecordRecommendations:
    def test_inserts_next_topic_recs(self, patch_db):
        from backend.services.continuity_service import record_recommendations
        record_recommendations("sess-1", "Vector Databases", _recs(["RAG Pipelines", "FAISS"]))
        rows = patch_db.execute("SELECT recommended FROM prior_recommendations").fetchall()
        recs = [r["recommended"] for r in rows]
        assert "RAG Pipelines" in recs
        assert "FAISS" in recs

    def test_skips_non_stored_source(self, patch_db):
        from backend.services.continuity_service import record_recommendations
        record_recommendations("sess-1", "Vector Databases", _recs(["RAG Pipelines"], source="empty"))
        count = patch_db.execute("SELECT COUNT(*) AS n FROM prior_recommendations").fetchone()["n"]
        assert count == 0

    def test_deduplicates_same_rec(self, patch_db):
        from backend.services.continuity_service import record_recommendations
        record_recommendations("sess-1", "Vector Databases", _recs(["FAISS"]))
        record_recommendations("sess-1", "Vector Databases", _recs(["FAISS"]))
        count = patch_db.execute("SELECT COUNT(*) AS n FROM prior_recommendations").fetchone()["n"]
        assert count == 1

    def test_empty_topic_is_no_op(self, patch_db):
        from backend.services.continuity_service import record_recommendations
        record_recommendations("sess-1", "", _recs(["FAISS"]))
        count = patch_db.execute("SELECT COUNT(*) AS n FROM prior_recommendations").fetchone()["n"]
        assert count == 0

    def test_empty_session_is_no_op(self, patch_db):
        from backend.services.continuity_service import record_recommendations
        record_recommendations("", "Vector Databases", _recs(["FAISS"]))
        count = patch_db.execute("SELECT COUNT(*) AS n FROM prior_recommendations").fetchone()["n"]
        assert count == 0

    def test_rec_type_stored_correctly(self, patch_db):
        from backend.services.continuity_service import record_recommendations
        recs = {
            "based_on_topic": "VDB", "source": "stored",
            "next_topics":     [{"topic": "RAG", "reason": "r"}],
            "prerequisites":   [{"topic": "Embeddings", "reason": "r"}],
            "advanced_topics": [{"topic": "Hybrid Search", "reason": "r"}],
        }
        record_recommendations("sess-1", "Vector Databases", recs)
        rows = patch_db.execute(
            "SELECT rec_type, recommended FROM prior_recommendations ORDER BY rec_type"
        ).fetchall()
        types = {r["rec_type"] for r in rows}
        assert types == {"next_topic", "prerequisite", "advanced"}

    def test_db_error_does_not_raise(self, monkeypatch):
        import backend.services.continuity_service as _cs
        monkeypatch.setattr(_cs, "get_connection", MagicMock(side_effect=RuntimeError("down")))
        from backend.services.continuity_service import record_recommendations
        record_recommendations("sess-1", "Topic", _recs(["X"]))   # must not raise


# ─────────────────────────────────────────────────────────────────────────────
# TestGetContinuityContext
# ─────────────────────────────────────────────────────────────────────────────

class TestGetContinuityContext:
    def _seed_concepts(self, db, topic, concepts):
        key = topic.strip().lower()
        for c in concepts:
            db.execute(
                "INSERT OR IGNORE INTO concept_memory "
                "(concept, concept_key, topic, topic_key, times_explained) VALUES (?,?,?,?,1)",
                (c, c.lower(), topic, key),
            )
        db.commit()

    def _seed_recs(self, db, topic, recs):
        key = topic.strip().lower()
        for r in recs:
            db.execute(
                "INSERT OR IGNORE INTO prior_recommendations "
                "(session_id, topic, topic_key, rec_type, recommended, recommended_key) "
                "VALUES ('s','"+topic+"','"+key+"','next_topic','"+r+"','"+r.lower()+"')"
            )
        db.commit()

    def _seed_chat(self, db, topic, session_count=2, turns_each=3):
        for s in range(session_count):
            for _ in range(turns_each):
                db.execute(
                    "INSERT INTO chat_messages (session_id, role, content, topic_hint) "
                    "VALUES (?,?,?,?)",
                    (f"sess-{s}", "user", "msg", topic),
                )
        db.commit()

    def test_returns_dict_with_required_keys(self, patch_db):
        from backend.services.continuity_service import get_continuity_context
        result = get_continuity_context("Vector Databases")
        assert set(result.keys()) >= {
            "topic", "explained_concepts", "prior_recommendations",
            "cross_session_turns", "sessions_count"
        }

    def test_empty_topic_returns_empty(self, patch_db):
        from backend.services.continuity_service import get_continuity_context
        result = get_continuity_context("")
        assert result["explained_concepts"] == []
        assert result["prior_recommendations"] == []
        assert result["cross_session_turns"] == 0

    def test_explained_concepts_populated(self, patch_db):
        self._seed_concepts(patch_db, "Vector Databases", ["Embeddings", "HNSW"])
        from backend.services.continuity_service import get_continuity_context
        result = get_continuity_context("Vector Databases")
        assert "Embeddings" in result["explained_concepts"]
        assert "HNSW" in result["explained_concepts"]

    def test_prior_recs_populated(self, patch_db):
        self._seed_recs(patch_db, "Vector Databases", ["RAG Pipelines", "FAISS"])
        from backend.services.continuity_service import get_continuity_context
        result = get_continuity_context("Vector Databases")
        assert "RAG Pipelines" in result["prior_recommendations"]

    def test_cross_session_turns_counted(self, patch_db):
        self._seed_chat(patch_db, "Vector Databases", session_count=2, turns_each=3)
        from backend.services.continuity_service import get_continuity_context
        result = get_continuity_context("Vector Databases")
        assert result["cross_session_turns"] == 6
        assert result["sessions_count"] == 2

    def test_no_data_returns_empty_result(self, patch_db):
        from backend.services.continuity_service import get_continuity_context
        result = get_continuity_context("Unknown Topic XYZ")
        assert result["explained_concepts"] == []
        assert result["prior_recommendations"] == []
        assert result["cross_session_turns"] == 0

    def test_db_error_returns_empty(self, monkeypatch):
        import backend.services.continuity_service as _cs
        monkeypatch.setattr(_cs, "get_connection", MagicMock(side_effect=RuntimeError("down")))
        from backend.services.continuity_service import get_continuity_context
        result = get_continuity_context("Vector Databases")
        assert result["explained_concepts"] == []

    def test_most_explained_concepts_first(self, patch_db):
        key = "vector databases"
        patch_db.execute(
            "INSERT INTO concept_memory (concept, concept_key, topic, topic_key, times_explained) "
            "VALUES ('Rare', 'rare', 'Vector Databases', ?, 1)", (key,)
        )
        patch_db.execute(
            "INSERT INTO concept_memory (concept, concept_key, topic, topic_key, times_explained) "
            "VALUES ('Common', 'common', 'Vector Databases', ?, 5)", (key,)
        )
        patch_db.commit()
        from backend.services.continuity_service import get_continuity_context
        result = get_continuity_context("Vector Databases")
        assert result["explained_concepts"][0] == "Common"


# ─────────────────────────────────────────────────────────────────────────────
# TestExtractConceptsFromContext
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractConceptsFromContext:
    def _extract(self, ctx):
        from backend.services.chat_service import _extract_concepts_from_context
        return _extract_concepts_from_context(ctx)

    def test_extracts_from_deep_research(self):
        ctx = {"research": {"deep_research": {"key_concepts": ["ANN", "HNSW", "Cosine"]}}}
        result = self._extract(ctx)
        assert "ANN" in result and "HNSW" in result

    def test_extracts_from_action_result_data(self):
        ctx = {"research": {}, "action_result": {"data": {"key_concepts": ["PCA", "Reduction"]}}}
        result = self._extract(ctx)
        assert "PCA" in result

    def test_extracts_beginner_steps_from_action(self):
        ctx = {
            "research": {},
            "action_result": {"data": {"beginner_steps": [
                {"concept": "What is a Vector?"},
                {"concept": "Embeddings 101"},
            ]}},
        }
        result = self._extract(ctx)
        assert "What is a Vector?" in result
        assert "Embeddings 101" in result

    def test_deduplicates_case_insensitive(self):
        ctx = {
            "research": {"deep_research": {"key_concepts": ["Embeddings"]}},
            "action_result": {"data": {"key_concepts": ["embeddings"]}},
        }
        result = self._extract(ctx)
        assert result.count("Embeddings") == 1

    def test_caps_at_12(self):
        ctx = {"research": {"deep_research": {"key_concepts": [f"C{i}" for i in range(20)]}}}
        result = self._extract(ctx)
        assert len(result) <= 12

    def test_empty_context_returns_empty_list(self):
        assert self._extract({}) == []

    def test_non_string_concepts_ignored(self):
        ctx = {"research": {"deep_research": {"key_concepts": [123, None, "ValidConcept"]}}}
        result = self._extract(ctx)
        assert result == ["ValidConcept"]


# ─────────────────────────────────────────────────────────────────────────────
# TestContinuityPromptSection
# ─────────────────────────────────────────────────────────────────────────────

class TestContinuityPromptSection:
    def _section(self, continuity):
        from backend.services.chat_prompt_service import _build_continuity_section
        return _build_continuity_section(continuity)

    def test_empty_dict_returns_empty(self):
        assert self._section({}) == ""

    def test_no_topic_returns_empty(self):
        assert self._section({"explained_concepts": ["X"]}) == ""

    def test_no_data_returns_empty(self):
        assert self._section({"topic": "VDB"}) == ""

    def test_explained_concepts_in_output(self):
        result = self._section({
            "topic": "Vector Databases",
            "explained_concepts": ["Embeddings", "ANN"],
            "prior_recommendations": [],
            "cross_session_turns": 0,
            "sessions_count": 1,
        })
        assert "Embeddings" in result
        assert "ANN" in result

    def test_prior_recs_in_output(self):
        result = self._section({
            "topic": "Vector Databases",
            "explained_concepts": [],
            "prior_recommendations": ["RAG Pipelines", "FAISS"],
            "cross_session_turns": 0,
            "sessions_count": 1,
        })
        assert "RAG Pipelines" in result

    def test_multi_session_note_shown(self):
        result = self._section({
            "topic": "VDB",
            "explained_concepts": ["X"],
            "prior_recommendations": [],
            "cross_session_turns": 12,
            "sessions_count": 3,
        })
        assert "3 sessions" in result

    def test_single_session_no_multi_note(self):
        result = self._section({
            "topic": "VDB",
            "explained_concepts": ["X"],
            "prior_recommendations": [],
            "cross_session_turns": 4,
            "sessions_count": 1,
        })
        # The multi-session depth note ("Discussed across N sessions") should not appear
        assert "Discussed across" not in result

    def test_topic_name_in_output(self):
        result = self._section({
            "topic": "Transformer Architecture",
            "explained_concepts": ["Attention"],
            "prior_recommendations": [],
            "cross_session_turns": 0,
            "sessions_count": 0,
        })
        assert "Transformer Architecture" in result

    def test_anti_repetition_instruction_present(self):
        result = self._section({
            "topic": "VDB",
            "explained_concepts": ["Embeddings"],
            "prior_recommendations": [],
            "cross_session_turns": 0,
            "sessions_count": 0,
        })
        assert "re-explain" in result.lower() or "build on" in result.lower()


# ─────────────────────────────────────────────────────────────────────────────
# TestContinuityInSystemPrompt
# ─────────────────────────────────────────────────────────────────────────────

class TestContinuityInSystemPrompt:
    def test_section_appears_in_prompt(self):
        from backend.services.chat_prompt_service import build_system_prompt
        ctx = {
            **_base_ctx(),
            "continuity": {
                "topic": "Vector Databases",
                "explained_concepts": ["Embeddings", "HNSW"],
                "prior_recommendations": ["FAISS"],
                "cross_session_turns": 8,
                "sessions_count": 2,
            },
        }
        prompt = build_system_prompt(ctx)
        assert "Embeddings" in prompt
        assert "FAISS" in prompt

    def test_no_continuity_prompt_clean(self):
        from backend.services.chat_prompt_service import build_system_prompt
        ctx = _base_ctx()
        prompt = build_system_prompt(ctx)
        assert "Cross-session" not in prompt


# ─────────────────────────────────────────────────────────────────────────────
# TestInjectMemoryIncludesContinuity
# ─────────────────────────────────────────────────────────────────────────────

class TestInjectMemoryIncludesContinuity:
    def test_continuity_key_present_with_topic(self):
        fake_continuity = {
            "topic": "RAG",
            "explained_concepts": ["Embeddings"],
            "prior_recommendations": [],
            "cross_session_turns": 4,
            "sessions_count": 1,
        }
        with patch("backend.services.chat_context_service.build_full_context", return_value={}), \
             patch("backend.services.memory_injection_service.build_conversation_memory", return_value={}), \
             patch("backend.services.memory_injection_service.build_exploration_breadth", return_value={}), \
             patch("backend.services.memory_injection_service.build_preference_snapshot", return_value={}), \
             patch("backend.services.adaptive_explanation_service.build_learner_profile", return_value={}), \
             patch("backend.services.continuity_service.get_continuity_context", return_value=fake_continuity):
            from backend.services.memory_injection_service import inject_memory
            result = inject_memory("sess-1", topic_hint="RAG")
        assert "continuity" in result
        assert result["continuity"]["topic"] == "RAG"

    def test_continuity_empty_when_no_topic(self):
        with patch("backend.services.chat_context_service.build_full_context", return_value={}), \
             patch("backend.services.memory_injection_service.build_conversation_memory", return_value={}), \
             patch("backend.services.memory_injection_service.build_exploration_breadth", return_value={}), \
             patch("backend.services.memory_injection_service.build_preference_snapshot", return_value={}), \
             patch("backend.services.adaptive_explanation_service.build_learner_profile", return_value={}):
            from backend.services.memory_injection_service import inject_memory
            result = inject_memory("sess-1", topic_hint=None)
        assert result.get("continuity") == {}


# ─────────────────────────────────────────────────────────────────────────────
# TestChatServiceRecordsContinuity
# ─────────────────────────────────────────────────────────────────────────────

class TestChatServiceRecordsContinuity:
    def test_record_concepts_called_with_topic(self, patch_db):
        from backend.services.chat_service import chat
        ctx = _base_ctx()
        with patch("backend.services.chat_service.inject_memory", return_value=ctx), \
             patch("backend.services.grok_service.ask_grok_chat", return_value="Answer"), \
             patch("backend.services.action_router_service.route", return_value=None), \
             patch("backend.services.topic_expansion_service.get_stored_expansion", return_value=None), \
             patch("backend.services.continuity_service.record_concepts") as mock_rc, \
             patch("backend.services.continuity_service.record_recommendations"):
            chat("sess-1", "Explain HNSW", topic_hint="Vector Databases")
        mock_rc.assert_called_once()
        args = mock_rc.call_args[0]
        assert args[0] == "Vector Databases"   # topic
        assert args[2] == "sess-1"             # session_id

    def test_record_recommendations_called_after_turn(self, patch_db):
        from backend.services.chat_service import chat
        ctx = _base_ctx()
        with patch("backend.services.chat_service.inject_memory", return_value=ctx), \
             patch("backend.services.grok_service.ask_grok_chat", return_value="Answer"), \
             patch("backend.services.action_router_service.route", return_value=None), \
             patch("backend.services.topic_expansion_service.get_stored_expansion", return_value=None), \
             patch("backend.services.continuity_service.record_concepts"), \
             patch("backend.services.continuity_service.record_recommendations") as mock_rr:
            chat("sess-1", "What is RAG?", topic_hint="RAG")
        mock_rr.assert_called_once()

    def test_continuity_not_called_when_no_topic(self, patch_db):
        from backend.services.chat_service import chat
        ctx = _base_ctx()
        with patch("backend.services.chat_service.inject_memory", return_value=ctx), \
             patch("backend.services.grok_service.ask_grok_chat", return_value="Answer"), \
             patch("backend.services.chat_service._detect_topic_hint", return_value=None), \
             patch("backend.services.action_router_service.route", return_value=None), \
             patch("backend.services.topic_expansion_service.get_stored_expansion", return_value=None), \
             patch("backend.services.continuity_service.record_concepts") as mock_rc, \
             patch("backend.services.continuity_service.record_recommendations") as mock_rr:
            chat("sess-1", "Hello!")
        mock_rc.assert_not_called()
        mock_rr.assert_not_called()

    def test_continuity_error_does_not_break_chat(self, patch_db):
        from backend.services.chat_service import chat
        ctx = _base_ctx()
        with patch("backend.services.chat_service.inject_memory", return_value=ctx), \
             patch("backend.services.grok_service.ask_grok_chat", return_value="Answer"), \
             patch("backend.services.action_router_service.route", return_value=None), \
             patch("backend.services.topic_expansion_service.get_stored_expansion", return_value=None), \
             patch("backend.services.continuity_service.record_concepts",
                   side_effect=RuntimeError("db error")), \
             patch("backend.services.continuity_service.record_recommendations"):
            result = chat("sess-1", "Explain HNSW", topic_hint="Vector Databases")
        assert result["response"] == "Answer"


# ─────────────────────────────────────────────────────────────────────────────
# TestContinuityIntegration
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestContinuityIntegration:
    def test_record_and_retrieve_round_trip(self, patch_db):
        from backend.services.continuity_service import (
            record_concepts, record_recommendations, get_continuity_context
        )
        record_concepts("Transformers", ["Attention", "Positional Encoding", "BERT"], "sess-a")
        record_recommendations("sess-a", "Transformers", {
            "based_on_topic": "Transformers", "source": "stored",
            "next_topics": [{"topic": "GPT", "reason": "r"}],
            "prerequisites": [], "advanced_topics": [],
        })
        patch_db.execute(
            "INSERT INTO chat_messages (session_id, role, content, topic_hint) VALUES (?,?,?,?)",
            ("sess-a", "user", "What is attention?", "Transformers"),
        )
        patch_db.commit()

        ctx = get_continuity_context("Transformers", "sess-a")
        assert "Attention" in ctx["explained_concepts"]
        assert "GPT" in ctx["prior_recommendations"]
        assert ctx["cross_session_turns"] == 1

    def test_second_session_sees_prior_explanations(self, patch_db):
        from backend.services.continuity_service import record_concepts, get_continuity_context
        record_concepts("Transformers", ["Self-Attention"], "sess-first")
        ctx = get_continuity_context("Transformers", "sess-second")
        assert "Self-Attention" in ctx["explained_concepts"]
