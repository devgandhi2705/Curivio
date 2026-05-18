"""
Tests for structured learning path generation.

Test levels
-----------
1. TopicKey             — _topic_key normalisation
2. ParseJson            — fence stripping, embedded JSON, error cases
3. ParseTs              — timestamp format variants and error
4. GenerateLearningPath — mocked Groq + recommendation service; field defaults;
                          personalization args passed to prompt
5. StoreAndRetrieve     — _store_path + get_stored_path TTL and upsert
6. GetLearningPath      — cache-first logic and generation on miss
7. ListLearningPaths    — ordering, limit, returned columns
8. EndpointPost         — POST /learning-path shape, 422 validation
9. EndpointGetByTopic   — GET /learning-path/{topic} 200 and 404
10. EndpointList        — GET /learning-path list shape
11. Integration         — live Groq round-trip (gated -m integration)

Patching note
-------------
All external calls use deferred imports inside functions. Patch the SOURCE module:

  ask_grok                          → backend.services.grok_service.ask_grok
  get_learning_stage                → backend.services.recommendation_service.get_learning_stage
  get_overall_difficulty_preference → backend.services.recommendation_service.get_overall_difficulty_preference
  get_connection (service)          → backend.services.learning_path_service.get_connection

NOT backend.services.learning_path_service.<name> (those names don't exist there).

Run:
    pytest tests/test_learning_path.py -v
    pytest tests/test_learning_path.py -v -m integration   # live tests
"""

import json
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.database.schema import ALL_TABLES
from backend.services.learning_path_service import (
    LEARNING_PATH_TTL_HOURS,
    _generate_learning_path,
    _parse_json_response,
    _parse_ts,
    _store_path,
    _topic_key,
    get_learning_path,
    get_stored_path,
    list_learning_paths,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def mem_db(monkeypatch):
    """Isolated in-memory SQLite with all tables; patches get_connection."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
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

    monkeypatch.setattr("backend.services.learning_path_service.get_connection", _get_conn)
    monkeypatch.setattr("backend.utils.db.get_connection", _get_conn)
    yield conn
    conn.close()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _step(concept="Cosine Similarity", explanation="Dot product over norms.",
          why_it_matters="Used in every retrieval system.", resources=None):
    return {
        "concept":        concept,
        "explanation":    explanation,
        "why_it_matters": why_it_matters,
        "resources":      resources or ["Book: Mathematics for ML by Deisenroth (2020)"],
    }


def _good_path():
    return {
        "beginner":     [_step("What is a Vector"), _step("Dot Product")],
        "intermediate": [_step("FAISS Indexing"), _step("ANN Search")],
        "advanced":     [_step("HNSW Graph Structure"), _step("Product Quantization")],
    }


def _stored_path(topic="Vector Databases", stage="intermediate"):
    return {
        **_good_path(),
        "topic":          topic,
        "learning_stage": stage,
        "generated_at":   "2026-05-15T10:00:00",
    }


def _insert_path(conn, topic="Vector Databases", stage="intermediate",
                 generated_at="2026-05-15 10:00:00"):
    key  = _topic_key(topic)
    data = _stored_path(topic, stage)
    data["generated_at"] = generated_at
    conn.execute(
        "INSERT INTO learning_paths "
        "(topic, topic_key, learning_stage, path_json, generated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (topic, key, stage, json.dumps(data), generated_at),
    )
    conn.commit()
    return data


def _mock_grok(path_dict=None):
    """Patch ask_grok to return given dict as JSON (defaults to _good_path)."""
    return patch(
        "backend.services.grok_service.ask_grok",
        return_value=json.dumps(path_dict or _good_path()),
    )


def _mock_recommendation(stage="intermediate", difficulty=None):
    """Patch recommendation service helpers."""
    return (
        patch("backend.services.recommendation_service.get_learning_stage",
              return_value=stage),
        patch("backend.services.recommendation_service.get_overall_difficulty_preference",
              return_value=difficulty),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 1. TopicKey
# ═══════════════════════════════════════════════════════════════════════════════

class TestTopicKey:
    def test_lowercases(self):
        assert _topic_key("Vector Databases") == "vector databases"

    def test_strips_whitespace(self):
        assert _topic_key("  RAG Pipelines  ") == "rag pipelines"

    def test_already_normalised(self):
        assert _topic_key("embeddings") == "embeddings"

    def test_mixed_case_and_spaces(self):
        assert _topic_key("  Model Context Protocol  ") == "model context protocol"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ParseJson
# ═══════════════════════════════════════════════════════════════════════════════

class TestParseJson:
    def test_plain_json(self):
        raw = '{"beginner": [], "intermediate": [], "advanced": []}'
        result = _parse_json_response(raw)
        assert result["beginner"] == []

    def test_strips_json_fence(self):
        raw = '```json\n{"beginner": [{"concept": "X"}]}\n```'
        result = _parse_json_response(raw)
        assert result["beginner"][0]["concept"] == "X"

    def test_strips_plain_fence(self):
        raw = '```\n{"advanced": []}\n```'
        assert _parse_json_response(raw)["advanced"] == []

    def test_extracts_embedded_json(self):
        raw = 'Here: {"intermediate": []} done.'
        assert _parse_json_response(raw)["intermediate"] == []

    def test_raises_on_garbage(self):
        with pytest.raises(ValueError, match="could not be parsed"):
            _parse_json_response("not json at all")

    def test_raises_on_broken_embedded(self):
        with pytest.raises(ValueError):
            _parse_json_response("prefix {broken json here} suffix")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. ParseTs
# ═══════════════════════════════════════════════════════════════════════════════

class TestParseTs:
    def test_sqlite_format(self):
        dt = _parse_ts("2026-05-15 10:00:00")
        assert dt.year == 2026

    def test_iso_format(self):
        dt = _parse_ts("2026-05-15T10:00:00")
        assert dt.tzinfo is not None

    def test_iso_with_microseconds(self):
        dt = _parse_ts("2026-05-15T10:00:00.123456")
        assert dt.microsecond == 123456

    def test_raises_on_unknown_format(self):
        with pytest.raises(ValueError, match="Unrecognised timestamp"):
            _parse_ts("15/05/2026")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. GenerateLearningPath
# ═══════════════════════════════════════════════════════════════════════════════

class TestGenerateLearningPath:
    def test_returns_all_tiers(self, mem_db):
        stage_patch, diff_patch = _mock_recommendation()
        with _mock_grok(), stage_patch, diff_patch:
            result = _generate_learning_path("Vector Databases")
        for tier in ("beginner", "intermediate", "advanced"):
            assert tier in result

    def test_injects_topic_metadata(self, mem_db):
        stage_patch, diff_patch = _mock_recommendation()
        with _mock_grok(), stage_patch, diff_patch:
            result = _generate_learning_path("Vector Databases")
        assert result["topic"] == "Vector Databases"

    def test_injects_learning_stage(self, mem_db):
        stage_patch, diff_patch = _mock_recommendation("advanced")
        with _mock_grok(), stage_patch, diff_patch:
            result = _generate_learning_path("Vector Databases")
        assert result["learning_stage"] == "advanced"

    def test_injects_generated_at(self, mem_db):
        stage_patch, diff_patch = _mock_recommendation()
        with _mock_grok(), stage_patch, diff_patch:
            result = _generate_learning_path("Vector Databases")
        dt = datetime.fromisoformat(result["generated_at"])
        assert (datetime.now(timezone.utc) - dt).total_seconds() < 5

    def test_defaults_missing_tiers(self, mem_db):
        stage_patch, diff_patch = _mock_recommendation()
        with patch("backend.services.grok_service.ask_grok",
                   return_value='{"beginner": []}'), stage_patch, diff_patch:
            result = _generate_learning_path("Embeddings")
        assert result["intermediate"] == []
        assert result["advanced"] == []

    def test_defaults_missing_step_fields(self, mem_db):
        partial_path = {"beginner": [{"concept": "Vectors"}], "intermediate": [], "advanced": []}
        stage_patch, diff_patch = _mock_recommendation()
        with patch("backend.services.grok_service.ask_grok",
                   return_value=json.dumps(partial_path)), stage_patch, diff_patch:
            result = _generate_learning_path("Math")
        step = result["beginner"][0]
        assert step["explanation"] == ""
        assert step["why_it_matters"] == ""
        assert step["resources"] == []

    def test_strips_topic_whitespace(self, mem_db):
        stage_patch, diff_patch = _mock_recommendation()
        with _mock_grok(), stage_patch, diff_patch:
            result = _generate_learning_path("  Vector Databases  ")
        assert result["topic"] == "Vector Databases"

    def test_raises_on_unparseable_json(self, mem_db):
        stage_patch, diff_patch = _mock_recommendation()
        with patch("backend.services.grok_service.ask_grok", return_value="not json"), \
             stage_patch, diff_patch, \
             pytest.raises(ValueError, match="could not be parsed"):
            _generate_learning_path("Some Topic")

    def test_passes_stage_to_recommendation_service(self, mem_db):
        stage_mock = patch("backend.services.recommendation_service.get_learning_stage",
                           return_value="beginner")
        diff_mock  = patch("backend.services.recommendation_service.get_overall_difficulty_preference",
                           return_value=None)
        with _mock_grok(), stage_mock as m_stage, diff_mock:
            _generate_learning_path("RAG")
        m_stage.assert_called_once()

    def test_handles_json_in_markdown_fence(self, mem_db):
        raw = "```json\n" + json.dumps(_good_path()) + "\n```"
        stage_patch, diff_patch = _mock_recommendation()
        with patch("backend.services.grok_service.ask_grok", return_value=raw), \
             stage_patch, diff_patch:
            result = _generate_learning_path("Vector Databases")
        assert len(result["beginner"]) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 5. StoreAndRetrieve
# ═══════════════════════════════════════════════════════════════════════════════

class TestStoreAndRetrieve:
    def test_store_creates_row(self, mem_db):
        _store_path("Embeddings", _stored_path("Embeddings"))
        row = mem_db.execute(
            "SELECT * FROM learning_paths WHERE topic_key = 'embeddings'"
        ).fetchone()
        assert row is not None

    def test_store_returns_integer_id(self, mem_db):
        row_id = _store_path("Embeddings", _stored_path("Embeddings"))
        assert isinstance(row_id, int) and row_id > 0

    def test_store_saves_learning_stage_column(self, mem_db):
        _store_path("Embeddings", _stored_path("Embeddings", stage="advanced"))
        row = mem_db.execute(
            "SELECT learning_stage FROM learning_paths WHERE topic_key = 'embeddings'"
        ).fetchone()
        assert row["learning_stage"] == "advanced"

    def test_retrieve_returns_stored_result(self, mem_db):
        _insert_path(mem_db, "Vector Databases")
        result = get_stored_path("Vector Databases")
        assert result is not None
        assert len(result["beginner"]) == 2

    def test_retrieve_is_case_insensitive(self, mem_db):
        _insert_path(mem_db, "Vector Databases")
        assert get_stored_path("vector databases") is not None
        assert get_stored_path("VECTOR DATABASES") is not None

    def test_retrieve_strips_whitespace(self, mem_db):
        _insert_path(mem_db, "Vector Databases")
        assert get_stored_path("  Vector Databases  ") is not None

    def test_retrieve_returns_none_on_miss(self, mem_db):
        assert get_stored_path("Unknown Topic") is None

    def test_expired_entry_returns_none(self, mem_db):
        stale_ts = (
            datetime.now(timezone.utc) - timedelta(hours=LEARNING_PATH_TTL_HOURS + 1)
        ).strftime("%Y-%m-%d %H:%M:%S")
        _insert_path(mem_db, "Stale Topic", generated_at=stale_ts)
        assert get_stored_path("Stale Topic") is None

    def test_fresh_entry_within_ttl_returns_result(self, mem_db):
        fresh_ts = (
            datetime.now(timezone.utc) - timedelta(hours=LEARNING_PATH_TTL_HOURS - 1)
        ).strftime("%Y-%m-%d %H:%M:%S")
        _insert_path(mem_db, "Fresh Topic", generated_at=fresh_ts)
        assert get_stored_path("Fresh Topic") is not None

    def test_upsert_updates_existing_entry(self, mem_db):
        _insert_path(mem_db, "Embeddings")
        updated = _stored_path("Embeddings")
        updated["beginner"] = [_step("New Concept")]
        _store_path("Embeddings", updated)
        result = get_stored_path("Embeddings")
        assert result["beginner"][0]["concept"] == "New Concept"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. GetLearningPath
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetLearningPath:
    def test_returns_cached_without_calling_grok(self, mem_db):
        _insert_path(mem_db, "Vector Databases")
        with patch("backend.services.grok_service.ask_grok") as mock_grok:
            get_learning_path("Vector Databases")
        mock_grok.assert_not_called()

    def test_runs_generation_on_cache_miss(self, mem_db):
        stage_patch, diff_patch = _mock_recommendation()
        with _mock_grok() as mock_grok, stage_patch, diff_patch:
            result = get_learning_path("RAG Pipelines")
        mock_grok.assert_called_once()
        assert result["topic"] == "RAG Pipelines"

    def test_result_persisted_after_generation(self, mem_db):
        stage_patch, diff_patch = _mock_recommendation()
        with _mock_grok(), stage_patch, diff_patch:
            get_learning_path("RAG Pipelines")
        row = mem_db.execute(
            "SELECT * FROM learning_paths WHERE topic_key = 'rag pipelines'"
        ).fetchone()
        assert row is not None

    def test_second_call_uses_cache(self, mem_db):
        stage_patch, diff_patch = _mock_recommendation()
        with _mock_grok() as mock_grok, stage_patch, diff_patch:
            get_learning_path("RAG Pipelines")
            get_learning_path("RAG Pipelines")
        assert mock_grok.call_count == 1

    def test_strips_topic_whitespace(self, mem_db):
        stage_patch, diff_patch = _mock_recommendation()
        with _mock_grok(), stage_patch, diff_patch:
            result = get_learning_path("  Vector Databases  ")
        assert result["topic"] == "Vector Databases"


# ═══════════════════════════════════════════════════════════════════════════════
# 7. ListLearningPaths
# ═══════════════════════════════════════════════════════════════════════════════

class TestListLearningPaths:
    def test_empty_returns_empty_list(self, mem_db):
        assert list_learning_paths() == []

    def test_returns_stored_entries(self, mem_db):
        _insert_path(mem_db, "Vector Databases")
        rows = list_learning_paths()
        assert len(rows) == 1 and rows[0]["topic"] == "Vector Databases"

    def test_ordered_newest_first(self, mem_db):
        _insert_path(mem_db, "Vector Databases", generated_at="2026-05-14 10:00:00")
        _insert_path(mem_db, "RAG Pipelines",    generated_at="2026-05-15 10:00:00")
        rows = list_learning_paths()
        assert rows[0]["topic"] == "RAG Pipelines"

    def test_limit_is_respected(self, mem_db):
        _insert_path(mem_db, "Topic A", generated_at="2026-05-13 10:00:00")
        _insert_path(mem_db, "Topic B", generated_at="2026-05-14 10:00:00")
        _insert_path(mem_db, "Topic C", generated_at="2026-05-15 10:00:00")
        assert len(list_learning_paths(limit=2)) == 2

    def test_rows_have_required_columns(self, mem_db):
        _insert_path(mem_db, "Embeddings", stage="advanced")
        row = list_learning_paths()[0]
        assert "id" in row and "topic" in row
        assert "learning_stage" in row and "generated_at" in row

    def test_learning_stage_column_correct(self, mem_db):
        _insert_path(mem_db, "Embeddings", stage="advanced")
        assert list_learning_paths()[0]["learning_stage"] == "advanced"


# ═══════════════════════════════════════════════════════════════════════════════
# 8. EndpointPost
# Patches at backend.main.* to avoid SQLite thread-boundary issues.
# ═══════════════════════════════════════════════════════════════════════════════

class TestEndpointPost:
    @pytest.fixture(autouse=True)
    def no_github_calls(self):
        """Suppress real GitHub API calls for all tests in this class."""
        with patch("backend.main.get_topic_repos", return_value=[]):
            yield

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        return TestClient(app)

    def _stored(self, topic="Vector Databases"):
        return _stored_path(topic)

    def test_returns_200(self, client):
        with patch("backend.main.get_learning_path", side_effect=self._stored):
            resp = client.post("/learning-path", json={"topic": "Vector Databases"})
        assert resp.status_code == 200

    def test_blank_topic_returns_422(self, client):
        resp = client.post("/learning-path", json={"topic": "   "})
        assert resp.status_code == 422

    def test_missing_topic_returns_422(self, client):
        resp = client.post("/learning-path", json={})
        assert resp.status_code == 422

    def test_response_has_all_fields(self, client):
        with patch("backend.main.get_learning_path", side_effect=self._stored):
            resp = client.post("/learning-path", json={"topic": "Embeddings"})
        body = resp.json()
        for field in ("topic", "learning_stage", "beginner", "intermediate",
                      "advanced", "repositories", "generated_at"):
            assert field in body, f"missing field: {field}"

    def test_repositories_is_list(self, client):
        with patch("backend.main.get_learning_path", side_effect=self._stored):
            resp = client.post("/learning-path", json={"topic": "Embeddings"})
        assert isinstance(resp.json()["repositories"], list)

    def test_beginner_tier_is_list(self, client):
        with patch("backend.main.get_learning_path", side_effect=self._stored):
            resp = client.post("/learning-path", json={"topic": "Embeddings"})
        assert isinstance(resp.json()["beginner"], list)

    def test_step_has_concept_field(self, client):
        with patch("backend.main.get_learning_path", side_effect=self._stored):
            resp = client.post("/learning-path", json={"topic": "Embeddings"})
        step = resp.json()["beginner"][0]
        assert "concept" in step and "explanation" in step
        assert "why_it_matters" in step and "resources" in step

    def test_resources_is_list(self, client):
        with patch("backend.main.get_learning_path", side_effect=self._stored):
            resp = client.post("/learning-path", json={"topic": "Embeddings"})
        assert isinstance(resp.json()["beginner"][0]["resources"], list)

    def test_topic_trimmed_before_lookup(self, client):
        with patch("backend.main.get_learning_path", side_effect=self._stored) as mock_get:
            client.post("/learning-path", json={"topic": "  Embeddings  "})
        mock_get.assert_called_once_with("Embeddings")

    def test_repos_included_in_response(self, client):
        """Repos returned by get_topic_repos appear in the repositories field."""
        fake_repo = {"name": "org/repo", "description": "A repo", "stars": 1000,
                     "url": "https://github.com/org/repo", "language": "Python", "topics": []}
        with patch("backend.main.get_learning_path", side_effect=self._stored), \
             patch("backend.main.get_topic_repos", return_value=[fake_repo]):
            resp = client.post("/learning-path", json={"topic": "Vector Databases"})
        assert len(resp.json()["repositories"]) == 1
        assert resp.json()["repositories"][0]["name"] == "org/repo"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. EndpointGetByTopic
# ═══════════════════════════════════════════════════════════════════════════════

class TestEndpointGetByTopic:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        return TestClient(app)

    def test_returns_200_on_hit(self, client):
        with patch("backend.main.get_stored_path", return_value=_stored_path()):
            resp = client.get("/learning-path/Vector Databases")
        assert resp.status_code == 200

    def test_returns_404_on_miss(self, client):
        with patch("backend.main.get_stored_path", return_value=None):
            resp = client.get("/learning-path/Unknown Topic")
        assert resp.status_code == 404

    def test_response_has_topic_field(self, client):
        with patch("backend.main.get_stored_path", return_value=_stored_path("Embeddings")):
            resp = client.get("/learning-path/Embeddings")
        assert resp.json()["topic"] == "Embeddings"

    def test_response_has_learning_stage(self, client):
        with patch("backend.main.get_stored_path",
                   return_value=_stored_path(stage="advanced")):
            resp = client.get("/learning-path/Vector Databases")
        assert resp.json()["learning_stage"] == "advanced"


# ═══════════════════════════════════════════════════════════════════════════════
# 10. EndpointList
# ═══════════════════════════════════════════════════════════════════════════════

class TestEndpointList:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        return TestClient(app)

    def test_returns_200(self, client):
        with patch("backend.main.list_learning_paths", return_value=[]):
            resp = client.get("/learning-path")
        assert resp.status_code == 200

    def test_returns_list(self, client):
        with patch("backend.main.list_learning_paths", return_value=[]):
            assert isinstance(client.get("/learning-path").json(), list)

    def test_empty_when_none_stored(self, client):
        with patch("backend.main.list_learning_paths", return_value=[]):
            assert client.get("/learning-path").json() == []

    def test_returns_stored_entries(self, client):
        rows = [{"id": 1, "topic": "Vector Databases",
                 "learning_stage": "intermediate", "generated_at": "2026-05-15 10:00:00"}]
        with patch("backend.main.list_learning_paths", return_value=rows):
            body = client.get("/learning-path").json()
        assert body[0]["topic"] == "Vector Databases"

    def test_entries_have_summary_fields(self, client):
        rows = [{"id": 1, "topic": "Embeddings",
                 "learning_stage": "beginner", "generated_at": "2026-05-15 10:00:00"}]
        with patch("backend.main.list_learning_paths", return_value=rows):
            row = client.get("/learning-path").json()[0]
        for field in ("id", "topic", "learning_stage", "generated_at"):
            assert field in row, f"missing summary field: {field}"


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Integration (live Groq — gated)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.integration
class TestLearningPathIntegration:
    def test_full_path_round_trip(self, mem_db):
        """Live Groq + recommendation service call: generate → persist → cache hit."""
        topic  = "Vector Databases"
        result = get_learning_path(topic)

        assert result["topic"] == topic
        assert isinstance(result["learning_stage"], str)
        for tier in ("beginner", "intermediate", "advanced"):
            assert isinstance(result[tier], list)
            for step in result[tier]:
                assert "concept" in step
                assert "explanation" in step
                assert "why_it_matters" in step
                assert isinstance(step["resources"], list)

        # Second call must come from cache
        with patch("backend.services.grok_service.ask_grok") as mock_grok:
            cached = get_learning_path(topic)
        mock_grok.assert_not_called()
        assert cached["beginner"] == result["beginner"]
