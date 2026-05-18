"""
Tests for the feed caching layer.

Test levels:
  1. Cache-key unit tests      — pure hashing, no I/O
  2. Cache service unit tests  — isolated in-memory SQLite, no API calls
  3. Curator integration tests — curator_service with mocked Tavily/Groq
  4. Real integration test     — one miss then one hit with live APIs (skip by default)

Run non-integration tests:
    pytest tests/test_feed_cache.py -v

Run the live integration test:
    pytest tests/test_feed_cache.py -v -m integration
"""

import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ── Shared mock data ──────────────────────────────────────────────────────────

SAMPLE_FEED = {
    "news_insight": {
        "title": "Cached Insight",
        "summary": "Summary text.",
        "why_it_matters": "It matters.",
        "sources": ["https://example.com"],
    },
    "learning_topics": [
        {"title": "Topic A", "reason": "R", "difficulty": "beginner"},
        {"title": "Topic B", "reason": "R", "difficulty": "intermediate"},
        {"title": "Topic C", "reason": "R", "difficulty": "intermediate"},
        {"title": "Topic D", "reason": "R", "difficulty": "advanced"},
    ],
    "next_step": "Keep going.",
}

FINGERPRINT_A = json.dumps(
    {"liked": ["LLMs"], "suppressed": [], "difficulty": "intermediate", "stage": "early"},
    sort_keys=True,
)
FINGERPRINT_B = json.dumps(
    {"liked": ["RAG", "LLMs"], "suppressed": [], "difficulty": "intermediate", "stage": "developing"},
    sort_keys=True,
)


# ── In-memory DB fixture ──────────────────────────────────────────────────────

def _build_cache_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS feed_cache (
            cache_key    TEXT      PRIMARY KEY,
            interests    TEXT      NOT NULL,
            feed_json    TEXT      NOT NULL,
            hit_count    INTEGER   NOT NULL DEFAULT 0,
            generated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()


@pytest.fixture()
def mem_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _build_cache_schema(conn)
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def patch_cache_connection(mem_conn, monkeypatch):
    """Redirect all cache service DB calls to the isolated in-memory DB."""
    @contextmanager
    def _fake():
        try:
            yield mem_conn
            mem_conn.commit()
        except Exception:
            mem_conn.rollback()
            raise

    import backend.services.feed_cache_service as svc
    monkeypatch.setattr(svc, "get_connection", _fake)


from backend.services.feed_cache_service import (  # noqa: E402
    build_cache_key,
    cache_feed,
    get_cached_feed,
    purge_expired,
    CACHE_TTL_HOURS,
)


# ── 1. Cache-key unit tests ───────────────────────────────────────────────────

class TestBuildCacheKey:
    def test_returns_64_char_hex_string(self):
        key = build_cache_key("AI agents", FINGERPRINT_A)
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)

    def test_same_inputs_produce_same_key(self):
        assert build_cache_key("AI agents", FINGERPRINT_A) == build_cache_key("AI agents", FINGERPRINT_A)

    def test_different_interests_produce_different_keys(self):
        assert build_cache_key("AI agents", FINGERPRINT_A) != build_cache_key("RAG pipelines", FINGERPRINT_A)

    def test_different_fingerprints_produce_different_keys(self):
        assert build_cache_key("AI agents", FINGERPRINT_A) != build_cache_key("AI agents", FINGERPRINT_B)

    def test_interests_normalised_case_insensitive(self):
        assert build_cache_key("AI Agents", FINGERPRINT_A) == build_cache_key("ai agents", FINGERPRINT_A)

    def test_interests_normalised_strips_whitespace(self):
        assert build_cache_key("  AI agents  ", FINGERPRINT_A) == build_cache_key("AI agents", FINGERPRINT_A)

    def test_key_is_deterministic_across_calls(self):
        k1 = build_cache_key("test", FINGERPRINT_A)
        k2 = build_cache_key("test", FINGERPRINT_A)
        k3 = build_cache_key("test", FINGERPRINT_A)
        assert k1 == k2 == k3


# ── 2. Cache service unit tests ───────────────────────────────────────────────

class TestGetCachedFeed:
    def test_returns_none_when_empty(self):
        assert get_cached_feed("nonexistent") is None

    def test_returns_feed_after_cache_hit(self):
        key = build_cache_key("AI", FINGERPRINT_A)
        cache_feed(key, "AI", SAMPLE_FEED)
        result = get_cached_feed(key)
        assert result is not None
        assert result["news_insight"]["title"] == "Cached Insight"

    def test_deserialized_feed_is_dict(self):
        key = build_cache_key("AI", FINGERPRINT_A)
        cache_feed(key, "AI", SAMPLE_FEED)
        result = get_cached_feed(key)
        assert isinstance(result, dict)

    def test_increments_hit_count_on_access(self, mem_conn):
        key = build_cache_key("AI", FINGERPRINT_A)
        cache_feed(key, "AI", SAMPLE_FEED)
        get_cached_feed(key)
        get_cached_feed(key)
        row = mem_conn.execute("SELECT hit_count FROM feed_cache WHERE cache_key=?", (key,)).fetchone()
        assert row["hit_count"] == 2

    def test_expired_entry_returns_none(self, mem_conn):
        key = build_cache_key("AI", FINGERPRINT_A)
        # Insert with a timestamp older than the TTL
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=CACHE_TTL_HOURS + 1)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        mem_conn.execute(
            "INSERT INTO feed_cache (cache_key, interests, feed_json, generated_at) VALUES (?,?,?,?)",
            (key, "ai", json.dumps(SAMPLE_FEED), old_ts),
        )
        mem_conn.commit()
        assert get_cached_feed(key) is None

    def test_fresh_entry_within_ttl_returned(self, mem_conn):
        key = build_cache_key("ML", FINGERPRINT_A)
        recent_ts = (datetime.now(timezone.utc) - timedelta(hours=CACHE_TTL_HOURS - 1)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        mem_conn.execute(
            "INSERT INTO feed_cache (cache_key, interests, feed_json, generated_at) VALUES (?,?,?,?)",
            (key, "ml", json.dumps(SAMPLE_FEED), recent_ts),
        )
        mem_conn.commit()
        assert get_cached_feed(key) is not None

    def test_expired_entry_does_not_increment_hit_count(self, mem_conn):
        key = build_cache_key("AI", FINGERPRINT_A)
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=CACHE_TTL_HOURS + 1)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        mem_conn.execute(
            "INSERT INTO feed_cache (cache_key, interests, feed_json, hit_count, generated_at) VALUES (?,?,?,0,?)",
            (key, "ai", json.dumps(SAMPLE_FEED), old_ts),
        )
        mem_conn.commit()
        get_cached_feed(key)
        row = mem_conn.execute("SELECT hit_count FROM feed_cache WHERE cache_key=?", (key,)).fetchone()
        assert row["hit_count"] == 0


class TestCacheFeed:
    def test_stores_feed_retrievable_by_key(self):
        key = build_cache_key("deep learning", FINGERPRINT_A)
        cache_feed(key, "deep learning", SAMPLE_FEED)
        assert get_cached_feed(key) is not None

    def test_upsert_resets_hit_count(self, mem_conn):
        key = build_cache_key("AI", FINGERPRINT_A)
        cache_feed(key, "AI", SAMPLE_FEED)
        get_cached_feed(key)  # hit_count = 1
        cache_feed(key, "AI", SAMPLE_FEED)  # upsert → hit_count reset to 0
        row = mem_conn.execute("SELECT hit_count FROM feed_cache WHERE cache_key=?", (key,)).fetchone()
        assert row["hit_count"] == 0

    def test_upsert_refreshes_generated_at(self, mem_conn):
        key = build_cache_key("AI", FINGERPRINT_A)
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=CACHE_TTL_HOURS + 1)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        mem_conn.execute(
            "INSERT INTO feed_cache (cache_key, interests, feed_json, generated_at) VALUES (?,?,?,?)",
            (key, "ai", json.dumps(SAMPLE_FEED), old_ts),
        )
        mem_conn.commit()
        cache_feed(key, "AI", SAMPLE_FEED)  # upsert should refresh ts
        assert get_cached_feed(key) is not None  # now fresh

    def test_interests_stored_normalised(self, mem_conn):
        key = build_cache_key("  AI Agents  ", FINGERPRINT_A)
        cache_feed(key, "  AI Agents  ", SAMPLE_FEED)
        row = mem_conn.execute("SELECT interests FROM feed_cache WHERE cache_key=?", (key,)).fetchone()
        assert row["interests"] == "ai agents"


class TestPurgeExpired:
    def test_removes_expired_rows(self, mem_conn):
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=CACHE_TTL_HOURS + 1)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        for i in range(3):
            mem_conn.execute(
                "INSERT INTO feed_cache (cache_key, interests, feed_json, generated_at) VALUES (?,?,?,?)",
                (f"key_{i}", "ai", json.dumps(SAMPLE_FEED), old_ts),
            )
        mem_conn.commit()
        deleted = purge_expired()
        assert deleted == 3

    def test_keeps_fresh_rows(self, mem_conn):
        key = build_cache_key("AI", FINGERPRINT_A)
        cache_feed(key, "AI", SAMPLE_FEED)  # fresh row
        purge_expired()
        assert get_cached_feed(key) is not None

    def test_returns_zero_when_nothing_expired(self):
        cache_feed(build_cache_key("AI", FINGERPRINT_A), "AI", SAMPLE_FEED)
        assert purge_expired() == 0

    def test_mixed_fresh_and_expired(self, mem_conn):
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=CACHE_TTL_HOURS + 1)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        mem_conn.execute(
            "INSERT INTO feed_cache (cache_key, interests, feed_json, generated_at) VALUES (?,?,?,?)",
            ("old_key", "ai", json.dumps(SAMPLE_FEED), old_ts),
        )
        mem_conn.commit()
        fresh_key = build_cache_key("ML", FINGERPRINT_A)
        cache_feed(fresh_key, "ML", SAMPLE_FEED)
        deleted = purge_expired()
        assert deleted == 1
        assert get_cached_feed(fresh_key) is not None


# ── 3. Curator integration with mocked Tavily / Groq ─────────────────────────

class TestCuratorCacheIntegration:
    """Verifies that curator_service skips API calls on a cache hit."""

    MOCK_ARTICLES = [{"title": "T", "url": "https://x.com", "content": "c"}]

    def _patch_all(self):
        """Return a context-manager stack that mocks all external calls."""
        return (
            patch("backend.services.curator_service.search_articles", return_value=self.MOCK_ARTICLES),
            patch("backend.services.curator_service.ask_grok", return_value=json.dumps(SAMPLE_FEED)),
            patch("backend.services.curator_service.get_cached_feed"),
            patch("backend.services.curator_service.cache_feed"),
            patch("backend.services.curator_service.build_cache_key", return_value="fixed-key"),
            patch("backend.services.curator_service._build_memory_fingerprint", return_value="fp"),
        )

    def test_cache_miss_calls_tavily_and_groq(self):
        from backend.services.curator_service import generate_learning_feed
        with (
            patch("backend.services.curator_service.search_articles", return_value=self.MOCK_ARTICLES) as mock_ta,
            patch("backend.services.curator_service.ask_grok", return_value=json.dumps(SAMPLE_FEED)) as mock_groq,
            patch("backend.services.curator_service.get_cached_feed", return_value=None),
            patch("backend.services.curator_service.cache_feed"),
            patch("backend.services.curator_service.build_cache_key", return_value="k"),
            patch("backend.services.curator_service._build_memory_fingerprint", return_value="fp"),
        ):
            generate_learning_feed("AI agents")
        mock_ta.assert_called_once()
        mock_groq.assert_called_once()

    def test_cache_miss_stores_result(self):
        from backend.services.curator_service import generate_learning_feed
        with (
            patch("backend.services.curator_service.search_articles", return_value=self.MOCK_ARTICLES),
            patch("backend.services.curator_service.ask_grok", return_value=json.dumps(SAMPLE_FEED)),
            patch("backend.services.curator_service.get_cached_feed", return_value=None),
            patch("backend.services.curator_service.cache_feed") as mock_store,
            patch("backend.services.curator_service.build_cache_key", return_value="k"),
            patch("backend.services.curator_service._build_memory_fingerprint", return_value="fp"),
        ):
            generate_learning_feed("AI agents")
        mock_store.assert_called_once()
        _, stored_interests, stored_feed = mock_store.call_args.args
        assert stored_interests == "AI agents"
        assert stored_feed["news_insight"]["title"] == "Cached Insight"

    def test_cache_hit_skips_tavily_and_groq(self):
        from backend.services.curator_service import generate_learning_feed
        with (
            patch("backend.services.curator_service.search_articles") as mock_ta,
            patch("backend.services.curator_service.ask_grok") as mock_groq,
            patch("backend.services.curator_service.get_cached_feed", return_value=SAMPLE_FEED),
            patch("backend.services.curator_service.cache_feed"),
            patch("backend.services.curator_service.build_cache_key", return_value="k"),
            patch("backend.services.curator_service._build_memory_fingerprint", return_value="fp"),
        ):
            result = generate_learning_feed("AI agents")
        mock_ta.assert_not_called()
        mock_groq.assert_not_called()
        assert result["news_insight"]["title"] == "Cached Insight"

    def test_cache_hit_returns_cached_feed_unchanged(self):
        from backend.services.curator_service import generate_learning_feed
        with (
            patch("backend.services.curator_service.search_articles"),
            patch("backend.services.curator_service.ask_grok"),
            patch("backend.services.curator_service.get_cached_feed", return_value=SAMPLE_FEED),
            patch("backend.services.curator_service.cache_feed"),
            patch("backend.services.curator_service.build_cache_key", return_value="k"),
            patch("backend.services.curator_service._build_memory_fingerprint", return_value="fp"),
        ):
            result = generate_learning_feed("AI agents")
        assert result == SAMPLE_FEED

    def test_different_fingerprints_produce_different_keys(self):
        """Changing preferences must bypass the cache (different key)."""
        from backend.services.feed_cache_service import build_cache_key as real_build
        key_a = real_build("AI agents", FINGERPRINT_A)
        key_b = real_build("AI agents", FINGERPRINT_B)
        assert key_a != key_b


# ── 4. Real integration test ──────────────────────────────────────────────────

@pytest.mark.integration
def test_real_cache_miss_then_hit():
    """
    End-to-end: first call hits Groq+Tavily; second call returns cached result.

    Run with:  pytest tests/test_feed_cache.py -v -m integration
    """
    from backend.utils.db import init_db
    from backend.services.curator_service import generate_learning_feed

    init_db()

    interests = "AI agents"

    # First call — cache miss, real API calls
    feed1 = generate_learning_feed(interests)
    assert "news_insight" in feed1
    assert len(feed1.get("learning_topics", [])) == 4

    # Second call with identical inputs — must be a cache hit (same object structure)
    feed2 = generate_learning_feed(interests)
    assert feed2["news_insight"]["title"] == feed1["news_insight"]["title"]
