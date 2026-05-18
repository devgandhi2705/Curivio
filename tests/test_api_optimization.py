"""
Tests for API optimization: search caching, usage logging, cost estimation,
and service-level instrumentation.

Test levels
-----------
1. SearchCacheService   — key building, get/set, TTL expiry, purge, upsert
2. ApiUsageService      — log_api_call, get_usage_stats, daily summary, recent calls
3. CostEstimation       — groq / tavily cost math and ordering invariants
4. GrokServiceLogging   — timing, token extraction, log_api_call integration
5. TavilyServiceCaching — cache hit/miss path, result caching, log integration
6. ApiUsageEndpoint     — /api-usage HTTP route shape
7. Integration          — live search cache round-trip (gated with -m integration)

Run:
    pytest tests/test_api_optimization.py -v
    pytest tests/test_api_optimization.py -v -m integration   # live tests
"""

import json
import sqlite3
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.database.schema import ALL_TABLES
from backend.services.api_usage_service import (
    _GROQ_INPUT_COST_PER_TOKEN,
    _GROQ_OUTPUT_COST_PER_TOKEN,
    _TAVILY_COST_PER_SEARCH,
    estimate_groq_cost,
    estimate_tavily_cost,
    get_daily_summary,
    get_recent_calls,
    get_usage_stats,
    log_api_call,
)
from backend.services.search_cache_service import (
    SEARCH_CACHE_TTL_HOURS,
    build_search_key,
    cache_search,
    get_cached_search,
    purge_expired,
)


# ── Shared in-memory DB fixture ────────────────────────────────────────────────

@pytest.fixture
def mem_db(monkeypatch):
    """
    Single in-memory SQLite connection shared across all get_connection() calls
    within one test.  All new tables are created so both search_cache and
    api_usage_log are available.
    """
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

    monkeypatch.setattr("backend.services.api_usage_service.get_connection", _get_conn)
    monkeypatch.setattr("backend.services.search_cache_service.get_connection", _get_conn)

    yield conn
    conn.close()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fake_results(n=3):
    return [{"title": f"Article {i}", "url": f"https://ex.com/{i}", "content": "content"} for i in range(n)]


def _insert_log_row(conn, service="groq", operation="chat_completion",
                    cache_hit=0, input_tokens=100, output_tokens=50,
                    cost=0.0000065, created_at="2026-05-15 10:00:00"):
    conn.execute(
        """INSERT INTO api_usage_log
           (service, operation, cache_hit, input_tokens, output_tokens,
            estimated_cost_usd, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (service, operation, cache_hit, input_tokens, output_tokens, cost, created_at),
    )
    conn.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. SearchCacheService
# ═══════════════════════════════════════════════════════════════════════════════

class TestSearchCacheKeyBuilding:
    def test_build_search_key_is_sha256_hex(self):
        key = build_search_key("RAG pipelines")
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)

    def test_build_search_key_is_deterministic(self):
        assert build_search_key("transformer") == build_search_key("transformer")

    def test_build_search_key_normalises_case(self):
        assert build_search_key("RAG Pipelines") == build_search_key("rag pipelines")

    def test_build_search_key_strips_whitespace(self):
        assert build_search_key("  rag  ") == build_search_key("rag")

    def test_different_queries_produce_different_keys(self):
        assert build_search_key("transformers") != build_search_key("diffusion models")


class TestSearchCacheMissAndHit:
    def test_get_returns_none_on_miss(self, mem_db):
        assert get_cached_search("unknown query") is None

    def test_cache_then_retrieve_returns_same_results(self, mem_db):
        results = _fake_results(3)
        cache_search("RAG pipelines", results)
        retrieved = get_cached_search("RAG pipelines")
        assert retrieved == results

    def test_retrieve_is_case_insensitive(self, mem_db):
        results = _fake_results(2)
        cache_search("RAG Pipelines", results)
        assert get_cached_search("rag pipelines") == results

    def test_cache_hit_increments_hit_count(self, mem_db):
        cache_search("test query", _fake_results(1))
        get_cached_search("test query")
        get_cached_search("test query")
        row = mem_db.execute(
            "SELECT hit_count FROM search_cache WHERE cache_key = ?",
            (build_search_key("test query"),),
        ).fetchone()
        assert row["hit_count"] == 2

    def test_upsert_resets_hit_count(self, mem_db):
        cache_search("query", _fake_results(1))
        get_cached_search("query")   # hit_count → 1
        cache_search("query", _fake_results(2))  # upsert resets to 0
        row = mem_db.execute(
            "SELECT hit_count FROM search_cache WHERE cache_key = ?",
            (build_search_key("query"),),
        ).fetchone()
        assert row["hit_count"] == 0

    def test_upsert_updates_results(self, mem_db):
        cache_search("query", _fake_results(1))
        new_results = _fake_results(5)
        cache_search("query", new_results)
        assert get_cached_search("query") == new_results


class TestSearchCacheTTL:
    def test_expired_entry_returns_none(self, mem_db):
        key = build_search_key("old query")
        mem_db.execute(
            """INSERT INTO search_cache (cache_key, query, results_json, created_at)
               VALUES (?, ?, ?, '2000-01-01 00:00:00')""",
            (key, "old query", json.dumps(_fake_results(1))),
        )
        mem_db.commit()
        assert get_cached_search("old query") is None

    def test_fresh_entry_is_returned(self, mem_db):
        results = _fake_results(2)
        cache_search("fresh query", results)
        assert get_cached_search("fresh query") == results


class TestSearchCachePurge:
    def test_purge_removes_old_rows(self, mem_db):
        key = build_search_key("stale")
        mem_db.execute(
            """INSERT INTO search_cache (cache_key, query, results_json, created_at)
               VALUES (?, ?, ?, '2000-01-01 00:00:00')""",
            (key, "stale", json.dumps([])),
        )
        mem_db.commit()
        purge_expired()
        assert mem_db.execute("SELECT COUNT(*) FROM search_cache").fetchone()[0] == 0

    def test_purge_returns_row_count(self, mem_db):
        for i in range(3):
            key = build_search_key(f"old{i}")
            mem_db.execute(
                """INSERT INTO search_cache (cache_key, query, results_json, created_at)
                   VALUES (?, ?, ?, '2000-01-01 00:00:00')""",
                (key, f"old{i}", json.dumps([])),
            )
        mem_db.commit()
        assert purge_expired() == 3

    def test_purge_preserves_fresh_rows(self, mem_db):
        cache_search("keep me", _fake_results(1))
        deleted = purge_expired()
        assert deleted == 0
        assert get_cached_search("keep me") is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ApiUsageService — logging
# ═══════════════════════════════════════════════════════════════════════════════

class TestApiUsageLogging:
    def test_log_api_call_creates_row(self, mem_db):
        log_api_call(service="groq", operation="chat_completion",
                     model="llama-3.1-8b-instant", input_tokens=500,
                     output_tokens=200, duration_ms=1200,
                     estimated_cost_usd=0.000041)
        row = mem_db.execute("SELECT * FROM api_usage_log").fetchone()
        assert row["service"]   == "groq"
        assert row["operation"] == "chat_completion"
        assert row["model"]     == "llama-3.1-8b-instant"
        assert row["input_tokens"]  == 500
        assert row["output_tokens"] == 200
        assert row["duration_ms"]   == 1200

    def test_log_tavily_call(self, mem_db):
        log_api_call(service="tavily", operation="search", cache_hit=False,
                     estimated_cost_usd=0.001)
        row = mem_db.execute("SELECT * FROM api_usage_log").fetchone()
        assert row["service"]   == "tavily"
        assert row["cache_hit"] == 0

    def test_log_cache_hit_flag(self, mem_db):
        log_api_call(service="tavily", operation="search", cache_hit=True,
                     estimated_cost_usd=0.0)
        row = mem_db.execute("SELECT * FROM api_usage_log").fetchone()
        assert row["cache_hit"] == 1

    def test_log_truncates_long_query_hint(self, mem_db):
        long_hint = "x" * 300
        log_api_call(service="groq", operation="chat_completion", query_hint=long_hint)
        row = mem_db.execute("SELECT query_hint FROM api_usage_log").fetchone()
        assert len(row["query_hint"]) == 120

    def test_log_api_call_never_raises_on_db_error(self, monkeypatch):
        """DB failure must be silently swallowed — callers must not be broken."""
        @contextmanager
        def _boom():
            raise RuntimeError("DB is down")
            yield  # unreachable
        monkeypatch.setattr("backend.services.api_usage_service.get_connection", _boom)
        # Should not raise
        log_api_call(service="groq", operation="chat_completion")

    def test_log_multiple_calls_accumulate(self, mem_db):
        for _ in range(5):
            log_api_call(service="groq", operation="chat_completion")
        count = mem_db.execute("SELECT COUNT(*) FROM api_usage_log").fetchone()[0]
        assert count == 5


# ═══════════════════════════════════════════════════════════════════════════════
# 3. ApiUsageService — stats queries
# ═══════════════════════════════════════════════════════════════════════════════

class TestApiUsageStats:
    def test_empty_db_returns_zeros(self, mem_db):
        stats = get_usage_stats()
        assert stats["total_calls"]   == 0
        assert stats["cache_hits"]    == 0
        assert stats["cache_hit_rate"] == 0.0
        assert stats["total_input_tokens"]  == 0
        assert stats["total_output_tokens"] == 0
        assert stats["estimated_cost_usd"]  == 0.0
        assert stats["by_service"] == {}

    def test_counts_calls_within_window(self, mem_db):
        _insert_log_row(mem_db, created_at="2026-05-15 10:00:00")
        _insert_log_row(mem_db, created_at="2026-05-15 11:00:00")
        with patch("backend.services.api_usage_service._cutoff_ts", return_value="2026-05-14 00:00:00"):
            stats = get_usage_stats(days=7)
        assert stats["total_calls"] == 2

    def test_excludes_calls_outside_window(self, mem_db):
        _insert_log_row(mem_db, created_at="2020-01-01 00:00:00")
        stats = get_usage_stats(days=7)
        assert stats["total_calls"] == 0

    def test_cache_hit_rate_calculation(self, mem_db):
        _insert_log_row(mem_db, cache_hit=1, created_at="2026-05-15 10:00:00")
        _insert_log_row(mem_db, cache_hit=0, created_at="2026-05-15 10:01:00")
        _insert_log_row(mem_db, cache_hit=0, created_at="2026-05-15 10:02:00")
        with patch("backend.services.api_usage_service._cutoff_ts", return_value="2026-05-14 00:00:00"):
            stats = get_usage_stats(days=7)
        assert stats["cache_hits"]     == 1
        assert stats["cache_hit_rate"] == pytest.approx(1 / 3, rel=1e-3)

    def test_by_service_groups_correctly(self, mem_db):
        _insert_log_row(mem_db, service="groq",   operation="chat_completion",
                        input_tokens=100, output_tokens=50, cost=0.000009,
                        created_at="2026-05-15 10:00:00")
        _insert_log_row(mem_db, service="tavily", operation="search",
                        input_tokens=0,   output_tokens=0,  cost=0.001,
                        created_at="2026-05-15 10:01:00")
        with patch("backend.services.api_usage_service._cutoff_ts", return_value="2026-05-14 00:00:00"):
            stats = get_usage_stats()
        assert "groq"   in stats["by_service"]
        assert "tavily" in stats["by_service"]
        assert stats["by_service"]["groq"]["calls"]   == 1
        assert stats["by_service"]["tavily"]["calls"] == 1

    def test_token_totals_summed(self, mem_db):
        _insert_log_row(mem_db, input_tokens=300, output_tokens=100, created_at="2026-05-15 10:00:00")
        _insert_log_row(mem_db, input_tokens=200, output_tokens=80,  created_at="2026-05-15 10:01:00")
        with patch("backend.services.api_usage_service._cutoff_ts", return_value="2026-05-14 00:00:00"):
            stats = get_usage_stats()
        assert stats["total_input_tokens"]  == 500
        assert stats["total_output_tokens"] == 180


class TestApiDailySummary:
    def test_empty_returns_empty_list(self, mem_db):
        assert get_daily_summary() == []

    def test_groups_by_calendar_day(self, mem_db):
        _insert_log_row(mem_db, created_at="2026-05-15 08:00:00")
        _insert_log_row(mem_db, created_at="2026-05-15 20:00:00")
        _insert_log_row(mem_db, created_at="2026-05-14 12:00:00")
        with patch("backend.services.api_usage_service._cutoff_ts", return_value="2026-05-10 00:00:00"):
            rows = get_daily_summary()
        assert len(rows) == 2
        days = [r["day"] for r in rows]
        assert "2026-05-14" in days
        assert "2026-05-15" in days

    def test_rows_ordered_chronologically(self, mem_db):
        _insert_log_row(mem_db, created_at="2026-05-15 10:00:00")
        _insert_log_row(mem_db, created_at="2026-05-13 10:00:00")
        _insert_log_row(mem_db, created_at="2026-05-14 10:00:00")
        with patch("backend.services.api_usage_service._cutoff_ts", return_value="2026-05-10 00:00:00"):
            rows = get_daily_summary()
        assert [r["day"] for r in rows] == ["2026-05-13", "2026-05-14", "2026-05-15"]

    def test_row_has_expected_keys(self, mem_db):
        _insert_log_row(mem_db, created_at="2026-05-15 10:00:00")
        with patch("backend.services.api_usage_service._cutoff_ts", return_value="2026-05-14 00:00:00"):
            rows = get_daily_summary()
        required = {"day", "calls", "cache_hits", "input_tokens", "output_tokens", "estimated_cost_usd"}
        assert required <= set(rows[0].keys())


class TestApiRecentCalls:
    def test_empty_returns_empty_list(self, mem_db):
        assert get_recent_calls() == []

    def test_ordered_newest_first(self, mem_db):
        _insert_log_row(mem_db, service="groq",   created_at="2026-05-15 08:00:00")
        _insert_log_row(mem_db, service="tavily", created_at="2026-05-15 09:00:00")
        rows = get_recent_calls()
        assert rows[0]["service"] == "tavily"
        assert rows[1]["service"] == "groq"

    def test_respects_limit(self, mem_db):
        for _ in range(10):
            _insert_log_row(mem_db)
        assert len(get_recent_calls(limit=3)) == 3

    def test_row_has_expected_keys(self, mem_db):
        _insert_log_row(mem_db)
        row = get_recent_calls(limit=1)[0]
        required = {"id", "service", "operation", "model", "input_tokens",
                    "output_tokens", "duration_ms", "cache_hit", "query_hint",
                    "estimated_cost_usd", "created_at"}
        assert required <= set(row.keys())


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Cost estimation
# ═══════════════════════════════════════════════════════════════════════════════

class TestCostEstimation:
    def test_groq_zero_tokens_is_zero(self):
        assert estimate_groq_cost(0, 0) == 0.0

    def test_groq_known_values(self):
        # 1M input + 1M output
        cost = estimate_groq_cost(1_000_000, 1_000_000)
        assert cost == pytest.approx(0.05 + 0.08, rel=1e-6)

    def test_groq_output_more_expensive_than_input(self):
        assert estimate_groq_cost(0, 1) > estimate_groq_cost(1, 0)

    def test_groq_cost_is_additive(self):
        c1 = estimate_groq_cost(500, 100)
        c2 = estimate_groq_cost(300, 50)
        assert estimate_groq_cost(800, 150) == pytest.approx(c1 + c2, rel=1e-9)

    def test_tavily_live_search_costs_nonzero(self):
        assert estimate_tavily_cost(cache_hit=False) == pytest.approx(_TAVILY_COST_PER_SEARCH)

    def test_tavily_cache_hit_is_free(self):
        assert estimate_tavily_cost(cache_hit=True) == 0.0

    def test_tavily_live_more_expensive_than_cached(self):
        assert estimate_tavily_cost(False) > estimate_tavily_cost(True)

    def test_groq_cost_constants_match_documentation(self):
        assert _GROQ_INPUT_COST_PER_TOKEN  == pytest.approx(5e-8)
        assert _GROQ_OUTPUT_COST_PER_TOKEN == pytest.approx(8e-8)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. GrokService — logging integration
# ═══════════════════════════════════════════════════════════════════════════════

def _mock_openai_response(content="result", input_tokens=100, output_tokens=40):
    usage = MagicMock()
    usage.prompt_tokens     = input_tokens
    usage.completion_tokens = output_tokens
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    response.usage   = usage
    return response


class TestGrokServiceLogging:
    def test_ask_grok_returns_content(self):
        from backend.services.grok_service import ask_grok
        mock_resp = _mock_openai_response("Hello world")
        with patch("backend.services.grok_service.client") as mock_client, \
             patch("backend.services.api_usage_service.log_api_call"):
            mock_client.chat.completions.create.return_value = mock_resp
            result = ask_grok("Say hello")
        assert result == "Hello world"

    def test_ask_grok_calls_log_api_call(self):
        from backend.services.grok_service import ask_grok
        mock_resp = _mock_openai_response(input_tokens=200, output_tokens=80)
        with patch("backend.services.grok_service.client") as mock_client, \
             patch("backend.services.api_usage_service.log_api_call") as mock_log:
            mock_client.chat.completions.create.return_value = mock_resp
            ask_grok("Some prompt")
        mock_log.assert_called_once()
        kwargs = mock_log.call_args.kwargs
        assert kwargs["service"]        == "groq"
        assert kwargs["operation"]      == "chat_completion"
        assert kwargs["input_tokens"]   == 200
        assert kwargs["output_tokens"]  == 80
        assert kwargs["cache_hit"]      is False

    def test_ask_grok_records_positive_duration(self):
        from backend.services.grok_service import ask_grok
        captured = {}
        def capture_log(**kw):
            captured.update(kw)
        with patch("backend.services.grok_service.client") as mock_client, \
             patch("backend.services.api_usage_service.log_api_call", side_effect=capture_log):
            mock_client.chat.completions.create.return_value = _mock_openai_response()
            ask_grok("prompt")
        assert captured.get("duration_ms", -1) >= 0

    def test_ask_grok_computes_cost(self):
        from backend.services.grok_service import ask_grok
        captured = {}
        def capture_log(**kw):
            captured.update(kw)
        with patch("backend.services.grok_service.client") as mock_client, \
             patch("backend.services.api_usage_service.log_api_call", side_effect=capture_log):
            mock_client.chat.completions.create.return_value = _mock_openai_response(
                input_tokens=1_000_000, output_tokens=0
            )
            ask_grok("prompt")
        assert captured["estimated_cost_usd"] == pytest.approx(0.05, rel=1e-4)

    def test_ask_grok_raises_on_api_error(self):
        from backend.services.grok_service import ask_grok
        with patch("backend.services.grok_service.client") as mock_client, \
             patch("backend.services.api_usage_service.log_api_call"):
            mock_client.chat.completions.create.side_effect = Exception("timeout")
            with pytest.raises(RuntimeError, match="API request failed"):
                ask_grok("prompt")

    def test_ask_grok_handles_missing_usage(self):
        from backend.services.grok_service import ask_grok
        response = MagicMock()
        response.usage   = None
        response.choices = [MagicMock()]
        response.choices[0].message.content = "ok"
        captured = {}
        def capture_log(**kw):
            captured.update(kw)
        with patch("backend.services.grok_service.client") as mock_client, \
             patch("backend.services.api_usage_service.log_api_call", side_effect=capture_log):
            mock_client.chat.completions.create.return_value = response
            ask_grok("prompt")
        assert captured["input_tokens"]  is None
        assert captured["output_tokens"] is None

    def test_ask_grok_truncates_query_hint(self):
        from backend.services.grok_service import ask_grok
        captured = {}
        def capture_log(**kw):
            captured.update(kw)
        with patch("backend.services.grok_service.client") as mock_client, \
             patch("backend.services.api_usage_service.log_api_call", side_effect=capture_log):
            mock_client.chat.completions.create.return_value = _mock_openai_response()
            ask_grok("A" * 300)
        assert len(captured["query_hint"]) == 120


# ═══════════════════════════════════════════════════════════════════════════════
# 6. TavilyService — caching integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestTavilyServiceCaching:
    def _make_tavily_response(self, results):
        return {"results": results}

    def test_live_call_made_on_cache_miss(self, mem_db):
        from backend.services.tavily_service import search_articles
        fake = [{"title": "T", "url": "https://x.com", "content": "c"}]
        with patch("backend.services.tavily_service._client") as mock_client:
            mock_client.search.return_value = {"results": fake}
            result = search_articles("live query")
        mock_client.search.assert_called_once()
        assert result == fake

    def test_no_live_call_on_cache_hit(self, mem_db):
        from backend.services.tavily_service import search_articles
        results = _fake_results(2)
        cache_search("cached query", results)
        with patch("backend.services.tavily_service._client") as mock_client:
            retrieved = search_articles("cached query")
        mock_client.search.assert_not_called()
        assert retrieved == results

    def test_results_cached_after_live_call(self, mem_db):
        from backend.services.tavily_service import search_articles
        fake = [{"title": "T", "url": "https://x.com", "content": "c"}]
        with patch("backend.services.tavily_service._client") as mock_client:
            mock_client.search.return_value = {"results": fake}
            search_articles("new query")
        # Second call should hit cache
        with patch("backend.services.tavily_service._client") as mock_client2:
            search_articles("new query")
        mock_client2.search.assert_not_called()

    def test_live_call_logs_cache_miss(self, mem_db):
        from backend.services.tavily_service import search_articles
        with patch("backend.services.tavily_service._client") as mock_client, \
             patch("backend.services.api_usage_service.log_api_call") as mock_log:
            mock_client.search.return_value = {"results": []}
            search_articles("log test query")
        mock_log.assert_called_once()
        kwargs = mock_log.call_args.kwargs
        assert kwargs["service"]   == "tavily"
        assert kwargs["cache_hit"] is False
        assert kwargs["estimated_cost_usd"] == pytest.approx(0.001)

    def test_cache_hit_logs_zero_cost(self, mem_db):
        from backend.services.tavily_service import search_articles
        cache_search("cheap query", _fake_results(1))
        with patch("backend.services.api_usage_service.log_api_call") as mock_log:
            search_articles("cheap query")
        kwargs = mock_log.call_args.kwargs
        assert kwargs["cache_hit"]          is True
        assert kwargs["estimated_cost_usd"] == 0.0

    def test_tavily_api_error_propagates(self, mem_db):
        from backend.services.tavily_service import search_articles
        with patch("backend.services.tavily_service._client") as mock_client:
            mock_client.search.side_effect = Exception("network error")
            with pytest.raises(RuntimeError, match="Tavily search failed"):
                search_articles("bad query")


# ═══════════════════════════════════════════════════════════════════════════════
# 7. /api-usage endpoint
# ═══════════════════════════════════════════════════════════════════════════════

class TestApiUsageEndpoint:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        return TestClient(app)

    def _empty_stats(self):
        return {
            "total_calls": 0, "cache_hits": 0, "cache_hit_rate": 0.0,
            "total_input_tokens": 0, "total_output_tokens": 0,
            "estimated_cost_usd": 0.0, "by_service": {},
        }

    def test_endpoint_returns_200(self, client):
        with patch("backend.main.get_usage_stats", return_value=self._empty_stats()), \
             patch("backend.main.get_daily_summary", return_value=[]), \
             patch("backend.main.get_recent_calls", return_value=[]):
            resp = client.get("/api-usage")
        assert resp.status_code == 200

    def test_endpoint_response_shape(self, client):
        with patch("backend.main.get_usage_stats", return_value=self._empty_stats()), \
             patch("backend.main.get_daily_summary", return_value=[{"day": "2026-05-15", "calls": 1}]), \
             patch("backend.main.get_recent_calls",  return_value=[{"id": 1, "service": "groq"}]):
            resp = client.get("/api-usage")
        body = resp.json()
        for field in ("period_days", "total_calls", "cache_hits", "cache_hit_rate",
                      "total_input_tokens", "total_output_tokens", "estimated_cost_usd",
                      "by_service", "daily", "recent_calls"):
            assert field in body, f"Missing field: {field}"

    def test_endpoint_period_days_defaults_to_7(self, client):
        with patch("backend.main.get_usage_stats", return_value=self._empty_stats()) as mock_stats, \
             patch("backend.main.get_daily_summary", return_value=[]), \
             patch("backend.main.get_recent_calls",  return_value=[]):
            client.get("/api-usage")
        mock_stats.assert_called_once_with(days=7)

    def test_endpoint_period_days_param(self, client):
        with patch("backend.main.get_usage_stats", return_value=self._empty_stats()) as mock_stats, \
             patch("backend.main.get_daily_summary", return_value=[]), \
             patch("backend.main.get_recent_calls",  return_value=[]):
            client.get("/api-usage?days=30")
        mock_stats.assert_called_once_with(days=30)

    def test_endpoint_daily_and_recent_in_response(self, client):
        daily  = [{"day": "2026-05-15", "calls": 3}]
        recent = [{"id": 5, "service": "tavily"}]
        with patch("backend.main.get_usage_stats",  return_value=self._empty_stats()), \
             patch("backend.main.get_daily_summary", return_value=daily), \
             patch("backend.main.get_recent_calls",  return_value=recent):
            resp = client.get("/api-usage")
        body = resp.json()
        assert body["daily"]        == daily
        assert body["recent_calls"] == recent


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Integration test — real search cache round-trip
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.integration
class TestSearchCacheIntegration:
    def test_search_result_cached_and_reused(self, mem_db):
        """
        Store results in the search cache, confirm retrieval without calling
        Tavily.  This exercises the full cache path on a real in-memory DB.
        """
        from backend.services.tavily_service import search_articles

        results = [
            {"title": "RAG paper", "url": "https://arxiv.org/1", "content": "about RAG"},
            {"title": "Embeddings", "url": "https://arxiv.org/2", "content": "about embeddings"},
        ]
        cache_search("rag retrieval augmented generation", results)

        with patch("backend.services.tavily_service._client") as mock_client:
            returned = search_articles("rag retrieval augmented generation")
        mock_client.search.assert_not_called()
        assert returned == results
