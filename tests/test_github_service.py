"""
Tests for the GitHub repository discovery service.

Test levels
-----------
1.  TopicKey          — _topic_key normalisation
2.  ParseTs           — timestamp format variants and error handling
3.  BuildQuery        — GitHub search query construction
4.  RankRepos         — scoring, filtering, ordering
5.  FetchFromGitHub   — mock requests.get: success, auth header, HTTP errors
6.  StoreAndRetrieve  — _store_repos + _get_stored_repos TTL and upsert
7.  GetTopicRepos     — cache-first logic; generation on miss
8.  ListRepoTopics    — ordering, limit, returned columns
9.  EndpointPost      — POST /repos shape and 422 validation
10. EndpointGetByTopic— GET /repos/{topic} 200 and 404
11. EndpointList      — GET /repos list shape
12. Integration       — live GitHub API round-trip (gated -m integration)

Patching note
-------------
_fetch_from_github calls requests.get at module level:
  patch target → "requests.get"

get_connection is imported at module level in github_service:
  patch target → "backend.services.github_service.get_connection"

Run:
    pytest tests/test_github_service.py -v
    pytest tests/test_github_service.py -v -m integration
"""

import json
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.database.schema import ALL_TABLES
from backend.services.github_service import (
    GITHUB_MIN_STARS,
    GITHUB_TTL_HOURS,
    _build_query,
    _fetch_from_github,
    _get_stored_repos,
    _parse_ts,
    _rank_repos,
    _store_repos,
    _topic_key,
    get_topic_repos,
    list_repo_topics,
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

    monkeypatch.setattr("backend.services.github_service.get_connection", _get_conn)
    monkeypatch.setattr("backend.utils.db.get_connection", _get_conn)
    yield conn
    conn.close()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fake_repo(
    full_name="facebookresearch/faiss",
    description="Efficient similarity search and clustering of dense vectors.",
    stars=25000,
    url="https://github.com/facebookresearch/faiss",
    language="C++",
    topics=("vector-database", "similarity-search", "machine-learning"),
    updated_at="2026-04-01T00:00:00Z",
    archived=False,
):
    return {
        "name":             full_name.split("/")[-1],
        "full_name":        full_name,
        "description":      description,
        "stargazers_count": stars,
        "html_url":         url,
        "language":         language,
        "topics":           list(topics),
        "updated_at":       updated_at,
        "archived":         archived,
    }


def _ranked_repo(
    name="facebookresearch/faiss",
    description="Efficient similarity search.",
    stars=25000,
    url="https://github.com/facebookresearch/faiss",
    language="C++",
    topics=None,
):
    return {
        "name":        name,
        "description": description,
        "stars":       stars,
        "url":         url,
        "language":    language,
        "topics":      topics or [],
    }


def _mock_github_response(items=None):
    """Create a mock requests.Response for the GitHub search API."""
    m = MagicMock()
    m.json.return_value = {"total_count": len(items or []), "items": items or []}
    m.raise_for_status.return_value = None
    return m


def _insert_repos(conn, topic="Vector Databases", fetched_at="2026-05-15 10:00:00"):
    key   = _topic_key(topic)
    repos = [_ranked_repo()]
    conn.execute(
        "INSERT INTO github_repos (topic, topic_key, repos_json, fetched_at) "
        "VALUES (?, ?, ?, ?)",
        (topic, key, json.dumps(repos), fetched_at),
    )
    conn.commit()
    return repos


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


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ParseTs
# ═══════════════════════════════════════════════════════════════════════════════

class TestParseTs:
    def test_sqlite_format(self):
        dt = _parse_ts("2026-05-15 10:00:00")
        assert dt.year == 2026

    def test_iso_format(self):
        dt = _parse_ts("2026-05-15T10:00:00")
        assert dt.tzinfo is not None

    def test_iso_with_microseconds(self):
        assert _parse_ts("2026-05-15T10:00:00.123456").microsecond == 123456

    def test_raises_on_unknown_format(self):
        with pytest.raises(ValueError, match="Unrecognised timestamp"):
            _parse_ts("15/05/2026")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. BuildQuery
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildQuery:
    def test_contains_topic(self):
        q = _build_query("Vector Databases")
        assert "Vector Databases" in q

    def test_contains_search_fields(self):
        q = _build_query("RAG Pipelines")
        assert "in:name,description,topics" in q

    def test_contains_star_filter(self):
        q = _build_query("Embeddings")
        assert f"stars:>{GITHUB_MIN_STARS}" in q

    def test_strips_whitespace_in_topic(self):
        q = _build_query("  Vector Databases  ")
        assert "Vector Databases" in q


# ═══════════════════════════════════════════════════════════════════════════════
# 4. RankRepos
# ═══════════════════════════════════════════════════════════════════════════════

class TestRankRepos:
    def test_filters_archived_repos(self):
        items = [_fake_repo(archived=True), _fake_repo(archived=False)]
        result = _rank_repos(items, "vector database")
        assert all(r["name"] != "facebookresearch/faiss" or True for r in result)
        assert len(result) == 1  # only non-archived

    def test_filters_repos_with_no_description(self):
        items = [_fake_repo(description=""), _fake_repo(description="Valid description.")]
        result = _rank_repos(items, "vector database")
        assert len(result) == 1
        assert result[0]["description"] == "Valid description."

    def test_filters_repos_below_min_stars(self):
        items = [
            _fake_repo(stars=GITHUB_MIN_STARS - 1, full_name="user/low"),
            _fake_repo(stars=GITHUB_MIN_STARS + 100, full_name="user/high"),
        ]
        result = _rank_repos(items, "vector database")
        assert len(result) == 1
        assert result[0]["name"] == "user/high"

    def test_returns_normalised_dict_fields(self):
        items = [_fake_repo()]
        result = _rank_repos(items, "vector database")
        assert len(result) == 1
        repo = result[0]
        assert "name" in repo and "description" in repo
        assert "stars" in repo and "url" in repo
        assert "language" in repo and "topics" in repo

    def test_higher_stars_ranks_first(self):
        items = [
            _fake_repo(full_name="user/low",  stars=500),
            _fake_repo(full_name="user/high", stars=25000),
        ]
        result = _rank_repos(items, "irrelevant")
        assert result[0]["name"] == "user/high"

    def test_recent_activity_bonus_applied(self):
        # Two repos with same stars; recently updated one should rank higher
        old_date    = "2020-01-01T00:00:00Z"
        recent_date = "2026-04-01T00:00:00Z"
        items = [
            _fake_repo(full_name="user/old",    stars=1000, updated_at=old_date),
            _fake_repo(full_name="user/recent", stars=1000, updated_at=recent_date),
        ]
        result = _rank_repos(items, "irrelevant")
        assert result[0]["name"] == "user/recent"

    def test_topic_overlap_bonus_applied(self):
        # Both repos old (no recency bonus) — topic match is the tiebreaker
        old = "2020-01-01T00:00:00Z"
        items = [
            _fake_repo(full_name="user/unrelated", stars=1000, topics=[],
                       updated_at=old),
            _fake_repo(full_name="user/matched",   stars=1000,
                       topics=["vector-database"], updated_at=old),
        ]
        result = _rank_repos(items, "vector database")
        assert result[0]["name"] == "user/matched"

    def test_empty_input_returns_empty(self):
        assert _rank_repos([], "any topic") == []

    def test_uses_full_name(self):
        items = [_fake_repo(full_name="org/repo-name")]
        result = _rank_repos(items, "topic")
        assert result[0]["name"] == "org/repo-name"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. FetchFromGitHub
# ═══════════════════════════════════════════════════════════════════════════════

class TestFetchFromGitHub:
    def test_calls_requests_get(self):
        with patch("requests.get", return_value=_mock_github_response()) as mock_get:
            _fetch_from_github("vector database")
        mock_get.assert_called_once()

    def test_passes_query_param(self):
        with patch("requests.get", return_value=_mock_github_response()) as mock_get:
            _fetch_from_github("vector database")
        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs.args[1] if len(call_kwargs.args) > 1 else call_kwargs.kwargs.get("params", {})
        assert "q" in str(mock_get.call_args)

    def test_returns_items(self):
        fake_items = [_fake_repo()]
        with patch("requests.get", return_value=_mock_github_response(fake_items)):
            result = _fetch_from_github("vector database")
        assert result["items"] == fake_items

    def test_includes_auth_header_when_token_set(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "mytoken123")
        with patch("requests.get", return_value=_mock_github_response()) as mock_get:
            _fetch_from_github("vector database")
        headers = mock_get.call_args.kwargs.get("headers", {})
        assert "Authorization" in headers
        assert "mytoken123" in headers["Authorization"]

    def test_no_auth_header_without_token(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with patch("requests.get", return_value=_mock_github_response()) as mock_get:
            _fetch_from_github("vector database")
        headers = mock_get.call_args.kwargs.get("headers", {})
        assert "Authorization" not in headers

    def test_raises_on_http_error(self):
        m = MagicMock()
        m.raise_for_status.side_effect = Exception("HTTP 403")
        with patch("requests.get", return_value=m), pytest.raises(Exception, match="403"):
            _fetch_from_github("vector database")


# ═══════════════════════════════════════════════════════════════════════════════
# 6. StoreAndRetrieve
# ═══════════════════════════════════════════════════════════════════════════════

class TestStoreAndRetrieve:
    def test_store_creates_row(self, mem_db):
        _store_repos("Vector Databases", [_ranked_repo()])
        row = mem_db.execute(
            "SELECT * FROM github_repos WHERE topic_key = 'vector databases'"
        ).fetchone()
        assert row is not None

    def test_retrieve_returns_stored_repos(self, mem_db):
        _insert_repos(mem_db, "Vector Databases")
        result = _get_stored_repos("Vector Databases")
        assert result is not None and len(result) == 1

    def test_retrieve_is_case_insensitive(self, mem_db):
        _insert_repos(mem_db, "Vector Databases")
        assert _get_stored_repos("vector databases") is not None
        assert _get_stored_repos("VECTOR DATABASES") is not None

    def test_retrieve_returns_none_on_miss(self, mem_db):
        assert _get_stored_repos("Unknown Topic") is None

    def test_expired_returns_none(self, mem_db):
        stale = (
            datetime.now(timezone.utc) - timedelta(hours=GITHUB_TTL_HOURS + 1)
        ).strftime("%Y-%m-%d %H:%M:%S")
        _insert_repos(mem_db, "Stale Topic", fetched_at=stale)
        assert _get_stored_repos("Stale Topic") is None

    def test_fresh_within_ttl_returns_repos(self, mem_db):
        fresh = (
            datetime.now(timezone.utc) - timedelta(hours=GITHUB_TTL_HOURS - 1)
        ).strftime("%Y-%m-%d %H:%M:%S")
        _insert_repos(mem_db, "Fresh Topic", fetched_at=fresh)
        assert _get_stored_repos("Fresh Topic") is not None

    def test_upsert_overwrites_existing(self, mem_db):
        _insert_repos(mem_db, "Embeddings")
        updated = [_ranked_repo(name="new/repo", stars=99999)]
        _store_repos("Embeddings", updated)
        result = _get_stored_repos("Embeddings")
        assert result[0]["name"] == "new/repo"


# ═══════════════════════════════════════════════════════════════════════════════
# 7. GetTopicRepos
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetTopicRepos:
    def test_returns_cached_without_github_call(self, mem_db):
        _insert_repos(mem_db, "Vector Databases")
        with patch("requests.get") as mock_get:
            get_topic_repos("Vector Databases")
        mock_get.assert_not_called()

    def test_fetches_from_github_on_miss(self, mem_db):
        items = [_fake_repo()]
        with patch("requests.get", return_value=_mock_github_response(items)):
            result = get_topic_repos("RAG Pipelines")
        assert isinstance(result, list)

    def test_persists_result_after_fetch(self, mem_db):
        items = [_fake_repo()]
        with patch("requests.get", return_value=_mock_github_response(items)):
            get_topic_repos("RAG Pipelines")
        row = mem_db.execute(
            "SELECT * FROM github_repos WHERE topic_key = 'rag pipelines'"
        ).fetchone()
        assert row is not None

    def test_second_call_uses_cache(self, mem_db):
        items = [_fake_repo()]
        with patch("requests.get", return_value=_mock_github_response(items)) as mock_get:
            get_topic_repos("Embeddings")
            get_topic_repos("Embeddings")
        assert mock_get.call_count == 1

    def test_empty_github_response_stores_empty_list(self, mem_db):
        with patch("requests.get", return_value=_mock_github_response([])):
            result = get_topic_repos("Obscure Topic")
        assert result == []


# ═══════════════════════════════════════════════════════════════════════════════
# 8. ListRepoTopics
# ═══════════════════════════════════════════════════════════════════════════════

class TestListRepoTopics:
    def test_empty_returns_empty(self, mem_db):
        assert list_repo_topics() == []

    def test_returns_stored_entries(self, mem_db):
        _insert_repos(mem_db, "Vector Databases")
        rows = list_repo_topics()
        assert len(rows) == 1 and rows[0]["topic"] == "Vector Databases"

    def test_ordered_newest_first(self, mem_db):
        _insert_repos(mem_db, "Vector Databases", "2026-05-14 10:00:00")
        _insert_repos(mem_db, "RAG Pipelines",    "2026-05-15 10:00:00")
        rows = list_repo_topics()
        assert rows[0]["topic"] == "RAG Pipelines"

    def test_limit_respected(self, mem_db):
        _insert_repos(mem_db, "Topic A", "2026-05-13 10:00:00")
        _insert_repos(mem_db, "Topic B", "2026-05-14 10:00:00")
        _insert_repos(mem_db, "Topic C", "2026-05-15 10:00:00")
        assert len(list_repo_topics(limit=2)) == 2

    def test_rows_have_required_fields(self, mem_db):
        _insert_repos(mem_db, "Embeddings")
        row = list_repo_topics()[0]
        assert "id" in row and "topic" in row and "fetched_at" in row


# ═══════════════════════════════════════════════════════════════════════════════
# 9. EndpointPost
# Patches at backend.main.* to avoid thread-boundary issues with in-memory DB.
# ═══════════════════════════════════════════════════════════════════════════════

class TestEndpointPost:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        return TestClient(app)

    def _repos(self, topic="Vector Databases"):
        return [_ranked_repo()]

    def test_returns_200(self, client):
        with patch("backend.main.get_topic_repos", side_effect=self._repos):
            resp = client.post("/repos", json={"topic": "Vector Databases"})
        assert resp.status_code == 200

    def test_blank_topic_returns_422(self, client):
        resp = client.post("/repos", json={"topic": "   "})
        assert resp.status_code == 422

    def test_missing_topic_returns_422(self, client):
        resp = client.post("/repos", json={})
        assert resp.status_code == 422

    def test_response_has_topic_and_repositories(self, client):
        with patch("backend.main.get_topic_repos", side_effect=self._repos):
            resp = client.post("/repos", json={"topic": "Vector Databases"})
        body = resp.json()
        assert "topic" in body and "repositories" in body

    def test_repositories_is_list(self, client):
        with patch("backend.main.get_topic_repos", side_effect=self._repos):
            resp = client.post("/repos", json={"topic": "Vector Databases"})
        assert isinstance(resp.json()["repositories"], list)

    def test_repo_entry_has_required_fields(self, client):
        with patch("backend.main.get_topic_repos", side_effect=self._repos):
            resp = client.post("/repos", json={"topic": "Vector Databases"})
        repo = resp.json()["repositories"][0]
        for field in ("name", "description", "stars", "url"):
            assert field in repo, f"missing field: {field}"

    def test_empty_repo_list_returns_200(self, client):
        with patch("backend.main.get_topic_repos", return_value=[]):
            resp = client.post("/repos", json={"topic": "Obscure Topic"})
        assert resp.status_code == 200
        assert resp.json()["repositories"] == []

    def test_topic_echoed_in_response(self, client):
        with patch("backend.main.get_topic_repos", return_value=[]):
            resp = client.post("/repos", json={"topic": "Embeddings"})
        assert resp.json()["topic"] == "Embeddings"


# ═══════════════════════════════════════════════════════════════════════════════
# 10. EndpointGetByTopic
# ═══════════════════════════════════════════════════════════════════════════════

class TestEndpointGetByTopic:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        return TestClient(app)

    def test_returns_200_on_hit(self, client):
        repos = [_ranked_repo()]
        with patch("backend.main._get_stored_repos", return_value=repos):
            resp = client.get("/repos/Vector Databases")
        assert resp.status_code == 200

    def test_returns_404_on_miss(self, client):
        with patch("backend.main._get_stored_repos", return_value=None):
            resp = client.get("/repos/Unknown Topic")
        assert resp.status_code == 404

    def test_response_has_repositories(self, client):
        with patch("backend.main._get_stored_repos", return_value=[_ranked_repo()]):
            resp = client.get("/repos/Vector Databases")
        assert "repositories" in resp.json()

    def test_response_topic_matches_path(self, client):
        with patch("backend.main._get_stored_repos", return_value=[]):
            resp = client.get("/repos/Embeddings")
        assert resp.json()["topic"] == "Embeddings"


# ═══════════════════════════════════════════════════════════════════════════════
# 11. EndpointList
# ═══════════════════════════════════════════════════════════════════════════════

class TestEndpointList:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        return TestClient(app)

    def test_returns_200(self, client):
        with patch("backend.main.list_repo_topics", return_value=[]):
            resp = client.get("/repos")
        assert resp.status_code == 200

    def test_returns_list(self, client):
        with patch("backend.main.list_repo_topics", return_value=[]):
            assert isinstance(client.get("/repos").json(), list)

    def test_empty_when_none_stored(self, client):
        with patch("backend.main.list_repo_topics", return_value=[]):
            assert client.get("/repos").json() == []

    def test_returns_stored_topics(self, client):
        rows = [{"id": 1, "topic": "Vector Databases", "fetched_at": "2026-05-15 10:00:00"}]
        with patch("backend.main.list_repo_topics", return_value=rows):
            body = client.get("/repos").json()
        assert body[0]["topic"] == "Vector Databases"

    def test_entries_have_summary_fields(self, client):
        rows = [{"id": 1, "topic": "Embeddings", "fetched_at": "2026-05-15 10:00:00"}]
        with patch("backend.main.list_repo_topics", return_value=rows):
            row = client.get("/repos").json()[0]
        assert "id" in row and "topic" in row and "fetched_at" in row


# ═══════════════════════════════════════════════════════════════════════════════
# 12. Integration (live GitHub API — gated)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.integration
class TestGitHubIntegration:
    def test_full_repo_discovery_round_trip(self, mem_db):
        """Live GitHub call: fetch → persist → cache hit."""
        topic  = "Vector Databases"
        result = get_topic_repos(topic)

        assert isinstance(result, list)
        if result:  # GitHub may return 0 results during CI
            repo = result[0]
            assert "name" in repo and repo["name"]
            assert "description" in repo
            assert isinstance(repo["stars"], int)
            assert repo["url"].startswith("https://github.com/")

        # Second call must use cache
        with patch("requests.get") as mock_get:
            cached = get_topic_repos(topic)
        mock_get.assert_not_called()
        assert cached == result
