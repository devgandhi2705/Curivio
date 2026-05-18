"""
Tests for digest_storage_service.

All tests use an isolated in-memory SQLite database injected via monkeypatching
get_connection — no file I/O, no API calls.

Run:
    pytest tests/test_digest_storage.py -v
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import pytest

# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_FEED = {
    "news_insight": {
        "title": "LLMs Are Reshaping Code Review",
        "summary": "New research shows AI pair-programmers cut review time by 40%.",
        "why_it_matters": "Faster reviews mean faster shipping for every team.",
        "sources": ["https://example.com/article1", "https://example.com/article2"],
    },
    "learning_topics": [
        {"title": "Prompt Engineering", "reason": "Foundational skill", "difficulty": "beginner"},
        {"title": "RAG Pipelines",      "reason": "Practical retrieval",  "difficulty": "intermediate"},
        {"title": "Fine-tuning LLMs",   "reason": "Customise base models", "difficulty": "intermediate"},
        {"title": "Agent Frameworks",   "reason": "Stretch goal",          "difficulty": "advanced"},
    ],
    "next_step": "Build a small RAG demo with LangChain.",
}


def _build_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS daily_digests (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            generated_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            news_title           TEXT      NOT NULL,
            news_summary         TEXT      NOT NULL,
            why_it_matters       TEXT      NOT NULL,
            learning_topics_json TEXT      NOT NULL,
            next_step            TEXT      NOT NULL,
            source_links_json    TEXT      NOT NULL DEFAULT '[]',
            source               TEXT      NOT NULL DEFAULT 'scheduler'
        );
        CREATE INDEX IF NOT EXISTS idx_daily_digests_date
            ON daily_digests (DATE(generated_at));
        """
    )
    conn.commit()


@pytest.fixture()
def mem_conn():
    """Isolated in-memory SQLite connection, closed after each test."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _build_schema(conn)
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def patch_get_connection(mem_conn, monkeypatch):
    """
    Replace get_connection in the service module with one that always returns
    the shared in-memory connection for this test.
    """
    @contextmanager
    def _fake_conn():
        try:
            yield mem_conn
            mem_conn.commit()
        except Exception:
            mem_conn.rollback()
            raise

    import backend.services.digest_storage_service as svc
    monkeypatch.setattr(svc, "get_connection", _fake_conn)


# ── Import after patching ─────────────────────────────────────────────────────

from backend.services.digest_storage_service import (  # noqa: E402
    get_digest_by_id,
    get_digests_by_date,
    get_latest_digest,
    list_digests,
    save_digest,
)


# ── save_digest ───────────────────────────────────────────────────────────────

class TestSaveDigest:
    def test_returns_positive_integer_id(self):
        fid = save_digest(SAMPLE_FEED)
        assert isinstance(fid, int) and fid > 0

    def test_sequential_ids_increment(self):
        id1 = save_digest(SAMPLE_FEED)
        id2 = save_digest(SAMPLE_FEED)
        assert id2 > id1

    def test_default_source_is_scheduler(self, mem_conn):
        fid = save_digest(SAMPLE_FEED)
        row = dict(mem_conn.execute("SELECT source FROM daily_digests WHERE id=?", (fid,)).fetchone())
        assert row["source"] == "scheduler"

    def test_user_source_stored(self, mem_conn):
        fid = save_digest(SAMPLE_FEED, source="user")
        row = dict(mem_conn.execute("SELECT source FROM daily_digests WHERE id=?", (fid,)).fetchone())
        assert row["source"] == "user"

    def test_news_title_stored(self, mem_conn):
        fid = save_digest(SAMPLE_FEED)
        row = dict(mem_conn.execute("SELECT news_title FROM daily_digests WHERE id=?", (fid,)).fetchone())
        assert row["news_title"] == "LLMs Are Reshaping Code Review"

    def test_learning_topics_stored_as_json_array(self, mem_conn):
        fid = save_digest(SAMPLE_FEED)
        raw = mem_conn.execute(
            "SELECT learning_topics_json FROM daily_digests WHERE id=?", (fid,)
        ).fetchone()[0]
        topics = json.loads(raw)
        assert len(topics) == 4
        assert topics[0]["title"] == "Prompt Engineering"

    def test_source_links_stored_as_json_array(self, mem_conn):
        fid = save_digest(SAMPLE_FEED)
        raw = mem_conn.execute(
            "SELECT source_links_json FROM daily_digests WHERE id=?", (fid,)
        ).fetchone()[0]
        links = json.loads(raw)
        assert links == SAMPLE_FEED["news_insight"]["sources"]

    def test_empty_sources_stored_as_empty_array(self, mem_conn):
        feed = {**SAMPLE_FEED, "news_insight": {**SAMPLE_FEED["news_insight"], "sources": []}}
        fid = save_digest(feed)
        raw = mem_conn.execute(
            "SELECT source_links_json FROM daily_digests WHERE id=?", (fid,)
        ).fetchone()[0]
        assert json.loads(raw) == []


# ── get_latest_digest ─────────────────────────────────────────────────────────

class TestGetLatestDigest:
    def test_returns_none_when_empty(self):
        assert get_latest_digest() is None

    def test_returns_dict_after_save(self):
        save_digest(SAMPLE_FEED)
        result = get_latest_digest()
        assert isinstance(result, dict)

    def test_json_columns_deserialized(self):
        save_digest(SAMPLE_FEED)
        result = get_latest_digest()
        assert isinstance(result["learning_topics"], list)
        assert isinstance(result["source_links"], list)

    def test_returns_most_recent_row(self, mem_conn):
        save_digest(SAMPLE_FEED)
        later_feed = {**SAMPLE_FEED, "news_insight": {**SAMPLE_FEED["news_insight"], "title": "Second Insight"}}
        # Force a later timestamp so ORDER BY works in-memory
        mem_conn.execute(
            """
            INSERT INTO daily_digests
                (news_title, news_summary, why_it_matters,
                 learning_topics_json, next_step, source_links_json,
                 generated_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now', '+1 second'))
            """,
            (
                "Second Insight",
                later_feed["news_insight"]["summary"],
                later_feed["news_insight"]["why_it_matters"],
                json.dumps(later_feed["learning_topics"]),
                later_feed["next_step"],
                json.dumps(later_feed["news_insight"]["sources"]),
            ),
        )
        mem_conn.commit()
        result = get_latest_digest()
        assert result["news_title"] == "Second Insight"

    def test_contains_all_expected_keys(self):
        save_digest(SAMPLE_FEED)
        result = get_latest_digest()
        for key in ("id", "generated_at", "news_title", "news_summary",
                    "why_it_matters", "learning_topics", "next_step", "source_links"):
            assert key in result, f"missing key: {key}"


# ── get_digest_by_id ──────────────────────────────────────────────────────────

class TestGetDigestById:
    def test_returns_none_for_missing_id(self):
        assert get_digest_by_id(9999) is None

    def test_returns_correct_row(self):
        fid = save_digest(SAMPLE_FEED)
        result = get_digest_by_id(fid)
        assert result is not None
        assert result["id"] == fid
        assert result["news_title"] == "LLMs Are Reshaping Code Review"

    def test_json_columns_deserialized(self):
        fid = save_digest(SAMPLE_FEED)
        result = get_digest_by_id(fid)
        assert isinstance(result["learning_topics"], list)
        assert len(result["learning_topics"]) == 4

    def test_different_ids_return_different_rows(self):
        feed2 = {**SAMPLE_FEED, "news_insight": {**SAMPLE_FEED["news_insight"], "title": "Different"}}
        id1 = save_digest(SAMPLE_FEED)
        id2 = save_digest(feed2)
        assert get_digest_by_id(id1)["news_title"] != get_digest_by_id(id2)["news_title"]


# ── get_digests_by_date ───────────────────────────────────────────────────────

class TestGetDigestsByDate:
    def _insert_with_timestamp(self, mem_conn, title: str, ts: str) -> int:
        cur = mem_conn.execute(
            """
            INSERT INTO daily_digests
                (news_title, news_summary, why_it_matters,
                 learning_topics_json, next_step, source_links_json, generated_at)
            VALUES (?, 'summary', 'matters', '[]', 'next', '[]', ?)
            """,
            (title, ts),
        )
        mem_conn.commit()
        return cur.lastrowid

    def test_returns_empty_list_for_unknown_date(self):
        assert get_digests_by_date("2000-01-01") == []

    def test_finds_row_by_date_string(self, mem_conn):
        self._insert_with_timestamp(mem_conn, "Today's Digest", "2025-05-14 08:00:00")
        results = get_digests_by_date("2025-05-14")
        assert len(results) == 1
        assert results[0]["news_title"] == "Today's Digest"

    def test_accepts_date_object(self, mem_conn):
        self._insert_with_timestamp(mem_conn, "Date Object Digest", "2025-06-01 10:00:00")
        results = get_digests_by_date(date(2025, 6, 1))
        assert len(results) == 1

    def test_accepts_datetime_object(self, mem_conn):
        self._insert_with_timestamp(mem_conn, "DateTime Digest", "2025-07-04 12:00:00")
        results = get_digests_by_date(datetime(2025, 7, 4, 0, 0, 0))
        assert len(results) == 1

    def test_multiple_on_same_date(self, mem_conn):
        self._insert_with_timestamp(mem_conn, "Morning",   "2025-05-14 08:00:00")
        self._insert_with_timestamp(mem_conn, "Afternoon", "2025-05-14 14:00:00")
        results = get_digests_by_date("2025-05-14")
        assert len(results) == 2

    def test_excludes_other_dates(self, mem_conn):
        self._insert_with_timestamp(mem_conn, "Yesterday", "2025-05-13 08:00:00")
        self._insert_with_timestamp(mem_conn, "Today",     "2025-05-14 08:00:00")
        self._insert_with_timestamp(mem_conn, "Tomorrow",  "2025-05-15 08:00:00")
        results = get_digests_by_date("2025-05-14")
        assert len(results) == 1
        assert results[0]["news_title"] == "Today"

    def test_returns_newest_first(self, mem_conn):
        self._insert_with_timestamp(mem_conn, "First",  "2025-05-14 08:00:00")
        self._insert_with_timestamp(mem_conn, "Second", "2025-05-14 12:00:00")
        results = get_digests_by_date("2025-05-14")
        assert results[0]["news_title"] == "Second"


# ── list_digests ──────────────────────────────────────────────────────────────

class TestListDigests:
    def test_empty_table_returns_empty_list(self):
        assert list_digests() == []

    def test_returns_all_when_under_limit(self):
        save_digest(SAMPLE_FEED)
        save_digest(SAMPLE_FEED)
        assert len(list_digests()) == 2

    def test_respects_limit(self):
        for _ in range(5):
            save_digest(SAMPLE_FEED)
        assert len(list_digests(limit=3)) == 3

    def test_default_limit_is_ten(self):
        for _ in range(12):
            save_digest(SAMPLE_FEED)
        assert len(list_digests()) == 10

    def test_json_columns_deserialized_in_list(self):
        save_digest(SAMPLE_FEED)
        rows = list_digests()
        assert isinstance(rows[0]["learning_topics"], list)
        assert isinstance(rows[0]["source_links"], list)
