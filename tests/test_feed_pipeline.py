"""
Tests for the automated daily feed pipeline.

Test levels (in order of API cost):
  1. Storage layer  — pure SQLite, zero API calls
  2. Pipeline mock  — scheduler job with generate_learning_feed mocked
  3. Integration    — one real end-to-end run (skipped unless -m integration)

Run all non-integration tests:
    pytest tests/test_feed_pipeline.py -v

Run the single integration test (uses real Groq + Tavily):
    pytest tests/test_feed_pipeline.py -v -m integration
"""

import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Make sure the project root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Point at a temp DB so tests never touch the real data file
os.environ.setdefault("DB_PATH", ":memory:")


# ── Helpers ───────────────────────────────────────────────────────────────────

SAMPLE_FEED = {
    "news_insight": {
        "title": "Test Insight",
        "summary": "A summary.",
        "why_it_matters": "It matters.",
        "sources": ["https://example.com"],
    },
    "learning_topics": [
        {"title": "Topic A", "reason": "Reason A", "difficulty": "beginner"},
        {"title": "Topic B", "reason": "Reason B", "difficulty": "intermediate"},
        {"title": "Topic C", "reason": "Reason C", "difficulty": "intermediate"},
        {"title": "Topic D", "reason": "Reason D", "difficulty": "advanced"},
    ],
    "next_step": "Keep learning.",
}

# Minimal shape returned by the new generate_intelligence_feed
SAMPLE_INTELLIGENCE_FEED = {
    "intelligence_brief": {
        "headline":          "Test Headline",
        "executive_summary": "A summary.",
        "key_signals":       [],
    },
    "sections":      [],
    "learning_track": [],
    "action_items":  [],
}


def _make_in_memory_db():
    """Return a sqlite3 connection using an isolated in-memory DB."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE generated_feeds (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            interests      TEXT    NOT NULL,
            feed_json      TEXT    NOT NULL,
            insight_title  TEXT,
            learning_stage TEXT,
            difficulty     TEXT,
            source         TEXT    NOT NULL DEFAULT 'scheduler',
            generated_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    return conn


# ── 1. Storage layer unit tests ───────────────────────────────────────────────

class TestFeedStorage:
    """Pure SQLite tests — no API calls, no file DB."""

    def setup_method(self):
        self.conn = _make_in_memory_db()

    def _save(self, interests, feed, source="scheduler", stage=None, diff=None):
        insight_title = feed.get("news_insight", {}).get("title")
        cur = self.conn.execute(
            """
            INSERT INTO generated_feeds
                (interests, feed_json, insight_title, learning_stage, difficulty, source)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (interests, json.dumps(feed), insight_title, stage, diff, source),
        )
        self.conn.commit()
        return cur.lastrowid

    def _latest(self):
        row = self.conn.execute(
            "SELECT * FROM generated_feeds ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["feed"] = json.loads(result.pop("feed_json"))
        return result

    def test_save_returns_positive_id(self):
        feed_id = self._save("AI", SAMPLE_FEED)
        assert isinstance(feed_id, int) and feed_id > 0

    def test_get_latest_returns_correct_title(self):
        self._save("AI", SAMPLE_FEED, stage="early", diff="beginner")
        result = self._latest()
        assert result is not None
        assert result["feed"]["news_insight"]["title"] == "Test Insight"
        assert result["learning_stage"] == "early"
        assert result["difficulty"] == "beginner"

    def test_get_latest_returns_none_when_empty(self):
        assert self._latest() is None

    def test_multiple_saves_latest_is_most_recent(self):
        self._save("AI", SAMPLE_FEED)
        feed2 = dict(SAMPLE_FEED)
        feed2["news_insight"] = dict(SAMPLE_FEED["news_insight"], title="Second Feed")
        self._save("ML", feed2)
        latest = self._latest()
        assert latest["feed"]["news_insight"]["title"] == "Second Feed"

    def test_source_field_stored_correctly(self):
        self._save("AI", SAMPLE_FEED, source="user")
        result = self._latest()
        assert result["source"] == "user"

    def test_four_learning_topics_round_trip(self):
        self._save("AI", SAMPLE_FEED)
        result = self._latest()
        topics = result["feed"]["learning_topics"]
        assert len(topics) == 4
        assert topics[0]["title"] == "Topic A"

    def teardown_method(self):
        self.conn.close()


# ── 2. Scheduler pipeline with mocked feed generation ────────────────────────

class TestSchedulerPipeline:
    """
    Verifies daily_feed_job logic without any real API calls.

    The scheduler was rewritten to call generate_intelligence_feed (deferred
    import — patched at the source module per project convention) instead of
    the old generate_learning_feed.  Run/save tracking now goes through
    _save_run / _update_run instead of feed_storage_service.save_feed.
    """

    def _run_job(self):
        from backend.services.scheduler_service import daily_feed_job
        asyncio.run(daily_feed_job())

    def _conn_mock(self, feed_row=None):
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__  = MagicMock(return_value=False)
        conn.execute.return_value.fetchone.return_value = feed_row
        conn.execute.return_value.lastrowid = 1
        return conn

    def test_job_calls_generate_with_correct_interests(self):
        """generate_intelligence_feed is called with the interests derived from liked topics."""
        conn = self._conn_mock(feed_row={"id": 42})
        with (
            patch("backend.services.scheduler_service._already_ran_today", return_value=False),
            patch("backend.services.scheduler_service._build_interests", return_value="AI agents, LLMs"),
            patch("backend.services.scheduler_service._save_run",   return_value=1),
            patch("backend.services.scheduler_service._update_run"),
            patch("backend.services.scheduler_service.get_learning_stage", return_value="early"),
            patch("backend.services.scheduler_service.get_overall_difficulty_preference", return_value="beginner"),
            patch(
                "backend.services.intelligence_service.generate_intelligence_feed",
                return_value=SAMPLE_INTELLIGENCE_FEED,
            ) as mock_gen,
            patch("backend.utils.db.get_connection", return_value=conn),
        ):
            self._run_job()

        mock_gen.assert_called_once_with("AI agents, LLMs")

    def test_job_uses_default_interests_when_no_history(self, monkeypatch):
        monkeypatch.setenv("SCHEDULER_DEFAULT_INTERESTS", "AI and machine learning")
        conn = self._conn_mock(feed_row={"id": 1})
        with (
            patch("backend.services.scheduler_service._already_ran_today", return_value=False),
            patch("backend.services.scheduler_service.get_top_user_interests", return_value=[]),
            patch("backend.services.scheduler_service._save_run",   return_value=1),
            patch("backend.services.scheduler_service._update_run"),
            patch("backend.services.scheduler_service.get_learning_stage", return_value="early"),
            patch("backend.services.scheduler_service.get_overall_difficulty_preference", return_value="intermediate"),
            patch(
                "backend.services.intelligence_service.generate_intelligence_feed",
                return_value=SAMPLE_INTELLIGENCE_FEED,
            ) as mock_gen,
            patch("backend.utils.db.get_connection", return_value=conn),
        ):
            self._run_job()

        assert mock_gen.call_args[0][0] == "AI and machine learning"

    def test_job_does_not_crash_on_generate_error(self):
        """A generation failure must be swallowed — scheduler must keep running."""
        with (
            patch("backend.services.scheduler_service._already_ran_today", return_value=False),
            patch("backend.services.scheduler_service._build_interests", return_value="AI"),
            patch("backend.services.scheduler_service._save_run",   return_value=1),
            patch("backend.services.scheduler_service._update_run") as mock_update,
            patch("backend.services.scheduler_service.get_learning_stage", return_value="early"),
            patch("backend.services.scheduler_service.get_overall_difficulty_preference", return_value="intermediate"),
            patch(
                "backend.services.intelligence_service.generate_intelligence_feed",
                side_effect=RuntimeError("Groq down"),
            ),
        ):
            self._run_job()   # must not raise

        assert mock_update.call_args[0][1] == "failed"

    def test_job_does_not_crash_on_save_error(self):
        """
        A DB connection error inside _save_run must be swallowed — the
        scheduler catches it internally and run_id becomes None, but the job
        still generates the feed and completes without raising.
        """
        # Conn that raises on first call (for _save_run) but succeeds on later
        # calls (for _latest_scheduler_feed_id used in the success path).
        success_conn = self._conn_mock(feed_row={"id": 1})
        call_count = {"n": 0}

        def failing_then_succeeding():
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise sqlite3.OperationalError("disk full")
            return success_conn

        with (
            patch("backend.services.scheduler_service._already_ran_today", return_value=False),
            patch("backend.services.scheduler_service._build_interests", return_value="AI"),
            patch("backend.services.scheduler_service.get_learning_stage", return_value="early"),
            patch("backend.services.scheduler_service.get_overall_difficulty_preference", return_value="intermediate"),
            patch(
                "backend.services.intelligence_service.generate_intelligence_feed",
                return_value=SAMPLE_INTELLIGENCE_FEED,
            ),
            patch("backend.utils.db.get_connection", side_effect=failing_then_succeeding),
        ):
            self._run_job()   # must not raise even when first DB write fails


# ── 3. One real integration test ──────────────────────────────────────────────

@pytest.mark.integration
def test_real_feed_generation_and_storage():
    """
    End-to-end: real Groq + Tavily calls → saved to the project DB.

    Run with:  pytest tests/test_feed_pipeline.py -v -m integration
    """
    from backend.utils.db import init_db
    from backend.services.curator_service import generate_learning_feed
    from backend.services.feed_storage_service import save_feed, get_feed_by_id

    init_db()

    interests = "AI agents"
    feed = generate_learning_feed(interests)

    assert "news_insight" in feed
    assert len(feed.get("learning_topics", [])) == 4

    feed_id = save_feed(interests=interests, feed=feed, source="user")
    assert feed_id and feed_id > 0

    stored = get_feed_by_id(feed_id)
    assert stored is not None
    assert stored["feed"]["news_insight"]["title"] == feed["news_insight"]["title"]
    assert stored["source"] == "user"
