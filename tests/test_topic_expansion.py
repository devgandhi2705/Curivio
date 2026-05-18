"""
Tests for the related-topic expansion engine.

Test levels
-----------
1. TopicKey            — _topic_key normalisation
2. ParseJson           — _parse_json_response fence stripping, embedded JSON, errors
3. ParseTs             — _parse_ts format variants and error
4. GenerateExpansion   — _generate_expansion field defaults and metadata injection
5. StoreAndRetrieve    — _store_expansion + get_stored_expansion TTL and upsert
6. ExpandTopic         — expand_topic cache-first path and generation on miss
7. ListExpansions      — list_expansions ordering and limit
8. EndpointPost        — POST /topic-expansion shape, cache hits, blank validation
9. EndpointGetByTopic  — GET /topic-expansion/{topic} 200 and 404 paths
10. EndpointList       — GET /topic-expansion list shape
11. Integration        — live end-to-end round-trip (gated -m integration)

Patching note
-------------
ask_grok uses a deferred import inside _generate_expansion — patch the source:
  ask_grok → backend.services.grok_service.ask_grok
NOT backend.services.topic_expansion_service.ask_grok (that name doesn't exist there).

Run:
    pytest tests/test_topic_expansion.py -v
    pytest tests/test_topic_expansion.py -v -m integration   # live tests
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
from backend.services.topic_expansion_service import (
    TOPIC_EXPANSION_TTL_HOURS,
    _generate_expansion,
    _parse_json_response,
    _parse_ts,
    _store_expansion,
    _topic_key,
    expand_topic,
    get_stored_expansion,
    list_expansions,
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

    monkeypatch.setattr("backend.services.topic_expansion_service.get_connection", _get_conn)
    monkeypatch.setattr("backend.utils.db.get_connection", _get_conn)
    yield conn
    conn.close()



# ── Helpers ────────────────────────────────────────────────────────────────────

def _good_expansion():
    return {
        "prerequisites":       ["Linear Algebra", "Python NumPy"],
        "related_topics":      ["Graph Databases", "Similarity Search", "Column Stores"],
        "advanced_follow_ups": ["RAG Pipelines", "Hybrid Retrieval", "Multi-modal Search"],
        "learning_progression": [
            "Linear Algebra",
            "Python NumPy",
            "Embeddings",
            "Vector Databases",
            "RAG Pipelines",
            "Hybrid Retrieval",
        ],
        "progression_rationale": "Linear algebra enables embeddings, which power vector databases.",
    }


def _insert_expansion(conn, topic="Vector Databases", generated_at="2026-05-15 10:00:00"):
    key = _topic_key(topic)
    data = {**_good_expansion(), "topic": topic, "generated_at": generated_at}
    conn.execute(
        "INSERT INTO topic_expansions (topic, topic_key, expansion_json, generated_at) "
        "VALUES (?, ?, ?, ?)",
        (topic, key, json.dumps(data), generated_at),
    )
    conn.commit()
    return data


def _mock_grok_with(expansion: dict):
    """Return a patcher that makes ask_grok return the given expansion as JSON."""
    return patch(
        "backend.services.grok_service.ask_grok",
        return_value=json.dumps(expansion),
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
        raw = '{"prerequisites": ["A"], "related_topics": []}'
        result = _parse_json_response(raw)
        assert result["prerequisites"] == ["A"]

    def test_strips_json_fence(self):
        raw = '```json\n{"related_topics": ["X"]}\n```'
        result = _parse_json_response(raw)
        assert result["related_topics"] == ["X"]

    def test_strips_plain_fence(self):
        raw = '```\n{"prerequisites": ["B"]}\n```'
        result = _parse_json_response(raw)
        assert result["prerequisites"] == ["B"]

    def test_extracts_embedded_json(self):
        raw = 'Here is the result: {"advanced_follow_ups": ["C"]} end.'
        result = _parse_json_response(raw)
        assert result["advanced_follow_ups"] == ["C"]

    def test_raises_on_garbage(self):
        with pytest.raises(ValueError, match="could not be parsed"):
            _parse_json_response("not json at all")

    def test_raises_on_invalid_embedded(self):
        with pytest.raises(ValueError):
            _parse_json_response("prefix {broken json} suffix")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. ParseTs
# ═══════════════════════════════════════════════════════════════════════════════

class TestParseTs:
    def test_sqlite_format(self):
        dt = _parse_ts("2026-05-15 10:00:00")
        assert dt.year == 2026 and dt.month == 5 and dt.day == 15

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
# 4. GenerateExpansion
# ═══════════════════════════════════════════════════════════════════════════════

class TestGenerateExpansion:
    def test_returns_all_required_fields(self, mem_db):
        with _mock_grok_with(_good_expansion()):
            result = _generate_expansion("Vector Databases")
        for field in ("prerequisites", "related_topics", "advanced_follow_ups",
                      "learning_progression", "progression_rationale", "topic", "generated_at"):
            assert field in result

    def test_injects_topic_metadata(self, mem_db):
        with _mock_grok_with(_good_expansion()):
            result = _generate_expansion("Vector Databases")
        assert result["topic"] == "Vector Databases"

    def test_injects_generated_at(self, mem_db):
        with _mock_grok_with(_good_expansion()):
            result = _generate_expansion("Vector Databases")
        dt = datetime.fromisoformat(result["generated_at"])
        assert (datetime.now(timezone.utc) - dt).total_seconds() < 5

    def test_defaults_missing_list_fields(self, mem_db):
        partial = {"progression_rationale": "Some rationale."}
        with _mock_grok_with(partial):
            result = _generate_expansion("Embeddings")
        assert result["prerequisites"] == []
        assert result["related_topics"] == []
        assert result["advanced_follow_ups"] == []
        assert result["learning_progression"] == []

    def test_defaults_missing_rationale(self, mem_db):
        partial = {"prerequisites": ["Math"]}
        with _mock_grok_with(partial):
            result = _generate_expansion("Embeddings")
        assert result["progression_rationale"] == ""

    def test_raises_on_unparseable_json(self, mem_db):
        with patch("backend.services.grok_service.ask_grok", return_value="not json"), \
             pytest.raises(ValueError, match="could not be parsed"):
            _generate_expansion("Some Topic")

    def test_extracts_json_from_fence(self, mem_db):
        raw = "```json\n" + json.dumps(_good_expansion()) + "\n```"
        with patch("backend.services.grok_service.ask_grok", return_value=raw):
            result = _generate_expansion("Vector Databases")
        assert result["prerequisites"] == _good_expansion()["prerequisites"]

    def test_strips_topic_whitespace(self, mem_db):
        with _mock_grok_with(_good_expansion()):
            result = _generate_expansion("  Vector Databases  ")
        assert result["topic"] == "Vector Databases"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. StoreAndRetrieve
# ═══════════════════════════════════════════════════════════════════════════════

class TestStoreAndRetrieve:
    def test_store_creates_row(self, mem_db):
        data = {**_good_expansion(), "topic": "Embeddings", "generated_at": "2026-05-15T10:00:00"}
        _store_expansion("Embeddings", data)
        row = mem_db.execute(
            "SELECT * FROM topic_expansions WHERE topic_key = 'embeddings'"
        ).fetchone()
        assert row is not None

    def test_store_returns_integer_id(self, mem_db):
        data = {**_good_expansion(), "topic": "Embeddings", "generated_at": "2026-05-15T10:00:00"}
        row_id = _store_expansion("Embeddings", data)
        assert isinstance(row_id, int) and row_id > 0

    def test_retrieve_returns_stored_result(self, mem_db):
        stored = _insert_expansion(mem_db, "Vector Databases")
        result = get_stored_expansion("Vector Databases")
        assert result is not None
        assert result["prerequisites"] == stored["prerequisites"]

    def test_retrieve_is_case_insensitive(self, mem_db):
        _insert_expansion(mem_db, "Vector Databases")
        assert get_stored_expansion("vector databases") is not None
        assert get_stored_expansion("VECTOR DATABASES") is not None

    def test_retrieve_strips_whitespace(self, mem_db):
        _insert_expansion(mem_db, "Vector Databases")
        assert get_stored_expansion("  Vector Databases  ") is not None

    def test_retrieve_returns_none_on_miss(self, mem_db):
        assert get_stored_expansion("Unknown Topic") is None

    def test_expired_entry_returns_none(self, mem_db):
        stale_ts = (
            datetime.now(timezone.utc) - timedelta(hours=TOPIC_EXPANSION_TTL_HOURS + 1)
        ).strftime("%Y-%m-%d %H:%M:%S")
        _insert_expansion(mem_db, "Stale Topic", generated_at=stale_ts)
        assert get_stored_expansion("Stale Topic") is None

    def test_fresh_entry_within_ttl_returns_result(self, mem_db):
        fresh_ts = (
            datetime.now(timezone.utc) - timedelta(hours=TOPIC_EXPANSION_TTL_HOURS - 1)
        ).strftime("%Y-%m-%d %H:%M:%S")
        _insert_expansion(mem_db, "Fresh Topic", generated_at=fresh_ts)
        assert get_stored_expansion("Fresh Topic") is not None

    def test_upsert_updates_existing_entry(self, mem_db):
        _insert_expansion(mem_db, "Embeddings")
        updated = {**_good_expansion(), "topic": "Embeddings",
                   "prerequisites": ["Updated Prereq"],
                   "generated_at": "2026-05-15T12:00:00"}
        _store_expansion("Embeddings", updated)
        result = get_stored_expansion("Embeddings")
        assert result["prerequisites"] == ["Updated Prereq"]


# ═══════════════════════════════════════════════════════════════════════════════
# 6. ExpandTopic
# ═══════════════════════════════════════════════════════════════════════════════

class TestExpandTopic:
    def test_returns_cached_result_without_calling_grok(self, mem_db):
        _insert_expansion(mem_db, "Vector Databases")
        with patch("backend.services.grok_service.ask_grok") as mock_grok:
            result = expand_topic("Vector Databases")
        mock_grok.assert_not_called()
        assert result["prerequisites"] == _good_expansion()["prerequisites"]

    def test_runs_generation_on_cache_miss(self, mem_db):
        with _mock_grok_with(_good_expansion()) as mock_grok:
            result = expand_topic("RAG Pipelines")
        mock_grok.assert_called_once()
        assert result["topic"] == "RAG Pipelines"

    def test_result_is_persisted_after_generation(self, mem_db):
        with _mock_grok_with(_good_expansion()):
            expand_topic("RAG Pipelines")
        row = mem_db.execute(
            "SELECT * FROM topic_expansions WHERE topic_key = 'rag pipelines'"
        ).fetchone()
        assert row is not None

    def test_second_call_uses_cache(self, mem_db):
        with _mock_grok_with(_good_expansion()) as mock_grok:
            expand_topic("RAG Pipelines")
            expand_topic("RAG Pipelines")
        assert mock_grok.call_count == 1

    def test_strips_topic_whitespace(self, mem_db):
        with _mock_grok_with(_good_expansion()):
            result = expand_topic("  Vector Databases  ")
        assert result["topic"] == "Vector Databases"


# ═══════════════════════════════════════════════════════════════════════════════
# 7. ListExpansions
# ═══════════════════════════════════════════════════════════════════════════════

class TestListExpansions:
    def test_empty_returns_empty_list(self, mem_db):
        assert list_expansions() == []

    def test_returns_stored_entries(self, mem_db):
        _insert_expansion(mem_db, "Vector Databases")
        rows = list_expansions()
        assert len(rows) == 1
        assert rows[0]["topic"] == "Vector Databases"

    def test_ordered_newest_first(self, mem_db):
        _insert_expansion(mem_db, "Vector Databases", "2026-05-14 10:00:00")
        _insert_expansion(mem_db, "RAG Pipelines",    "2026-05-15 10:00:00")
        rows = list_expansions()
        assert rows[0]["topic"] == "RAG Pipelines"
        assert rows[1]["topic"] == "Vector Databases"

    def test_limit_is_respected(self, mem_db):
        _insert_expansion(mem_db, "Topic A", "2026-05-13 10:00:00")
        _insert_expansion(mem_db, "Topic B", "2026-05-14 10:00:00")
        _insert_expansion(mem_db, "Topic C", "2026-05-15 10:00:00")
        rows = list_expansions(limit=2)
        assert len(rows) == 2

    def test_rows_have_id_topic_generated_at(self, mem_db):
        _insert_expansion(mem_db, "Embeddings")
        row = list_expansions()[0]
        assert "id" in row and "topic" in row and "generated_at" in row


# ═══════════════════════════════════════════════════════════════════════════════
# 8. EndpointPost
# Endpoint tests patch at backend.main.* level — never cross the thread boundary
# into the real SQLite connection (matches the pattern in test_deep_research.py).
# ═══════════════════════════════════════════════════════════════════════════════

class TestEndpointPost:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        return TestClient(app)

    def _stored(self, topic="Vector Databases"):
        return {**_good_expansion(), "topic": topic, "generated_at": "2026-05-15T10:00:00"}

    def test_returns_200_on_cache_hit(self, client):
        with patch("backend.main.expand_topic", side_effect=self._stored):
            resp = client.post("/topic-expansion", json={"topic": "Vector Databases"})
        assert resp.status_code == 200

    def test_returns_200_on_cache_miss(self, client):
        with patch("backend.main.expand_topic", side_effect=self._stored):
            resp = client.post("/topic-expansion", json={"topic": "RAG Pipelines"})
        assert resp.status_code == 200

    def test_response_has_all_required_fields(self, client):
        with patch("backend.main.expand_topic", side_effect=self._stored):
            resp = client.post("/topic-expansion", json={"topic": "Embeddings"})
        body = resp.json()
        for field in ("topic", "prerequisites", "related_topics", "advanced_follow_ups",
                      "learning_progression", "progression_rationale", "generated_at"):
            assert field in body, f"missing field: {field}"

    def test_blank_topic_returns_422(self, client):
        resp = client.post("/topic-expansion", json={"topic": "   "})
        assert resp.status_code == 422

    def test_missing_topic_returns_422(self, client):
        resp = client.post("/topic-expansion", json={})
        assert resp.status_code == 422

    def test_prerequisites_is_list(self, client):
        with patch("backend.main.expand_topic", side_effect=self._stored):
            resp = client.post("/topic-expansion", json={"topic": "Embeddings"})
        assert isinstance(resp.json()["prerequisites"], list)

    def test_learning_progression_is_list(self, client):
        with patch("backend.main.expand_topic", side_effect=self._stored):
            resp = client.post("/topic-expansion", json={"topic": "Embeddings"})
        assert isinstance(resp.json()["learning_progression"], list)

    def test_cached_result_returned_directly(self, client):
        stored = self._stored("Embeddings")
        with patch("backend.main.expand_topic", return_value=stored) as mock_expand:
            client.post("/topic-expansion", json={"topic": "Embeddings"})
        mock_expand.assert_called_once_with("Embeddings")


# ═══════════════════════════════════════════════════════════════════════════════
# 9. EndpointGetByTopic
# ═══════════════════════════════════════════════════════════════════════════════

class TestEndpointGetByTopic:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        return TestClient(app)

    def _stored(self, topic="Vector Databases"):
        return {**_good_expansion(), "topic": topic, "generated_at": "2026-05-15T10:00:00"}

    def test_returns_200_on_hit(self, client):
        with patch("backend.main.get_stored_expansion", return_value=self._stored()):
            resp = client.get("/topic-expansion/Vector Databases")
        assert resp.status_code == 200

    def test_returns_404_on_miss(self, client):
        with patch("backend.main.get_stored_expansion", return_value=None):
            resp = client.get("/topic-expansion/Unknown Topic")
        assert resp.status_code == 404

    def test_response_has_topic_field(self, client):
        with patch("backend.main.get_stored_expansion", return_value=self._stored("Embeddings")):
            resp = client.get("/topic-expansion/Embeddings")
        assert resp.json()["topic"] == "Embeddings"

    def test_response_has_all_fields(self, client):
        with patch("backend.main.get_stored_expansion", return_value=self._stored()):
            resp = client.get("/topic-expansion/Vector Databases")
        body = resp.json()
        for field in ("topic", "prerequisites", "related_topics", "advanced_follow_ups",
                      "learning_progression", "progression_rationale", "generated_at"):
            assert field in body, f"missing field: {field}"


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
        with patch("backend.main.list_expansions", return_value=[]):
            resp = client.get("/topic-expansion")
        assert resp.status_code == 200

    def test_returns_list(self, client):
        with patch("backend.main.list_expansions", return_value=[]):
            resp = client.get("/topic-expansion")
        assert isinstance(resp.json(), list)

    def test_empty_when_no_expansions(self, client):
        with patch("backend.main.list_expansions", return_value=[]):
            resp = client.get("/topic-expansion")
        assert resp.json() == []

    def test_returns_stored_entries(self, client):
        rows = [{"id": 1, "topic": "Vector Databases", "generated_at": "2026-05-15 10:00:00"}]
        with patch("backend.main.list_expansions", return_value=rows):
            resp = client.get("/topic-expansion")
        assert resp.json()[0]["topic"] == "Vector Databases"

    def test_entries_have_summary_fields(self, client):
        rows = [{"id": 1, "topic": "Embeddings", "generated_at": "2026-05-15 10:00:00"}]
        with patch("backend.main.list_expansions", return_value=rows):
            row = client.get("/topic-expansion").json()[0]
        assert "id" in row and "topic" in row and "generated_at" in row


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Integration (live Groq — gated)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.integration
class TestTopicExpansionIntegration:
    def test_full_expansion_round_trip(self, mem_db):
        """Live Groq call: expand → persist → retrieve from cache."""
        topic = "Vector Databases"
        result = expand_topic(topic)

        assert result["topic"] == topic
        assert isinstance(result["prerequisites"], list) and len(result["prerequisites"]) >= 2
        assert isinstance(result["related_topics"], list) and len(result["related_topics"]) >= 3
        assert isinstance(result["advanced_follow_ups"], list)
        assert isinstance(result["learning_progression"], list)
        assert isinstance(result["progression_rationale"], str)

        # Second call must come from cache
        with patch("backend.services.grok_service.ask_grok") as mock_grok:
            cached = expand_topic(topic)
        mock_grok.assert_not_called()
        assert cached["prerequisites"] == result["prerequisites"]
