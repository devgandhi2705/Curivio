"""
API usage logging and monitoring service.

Tracks every Groq and Tavily API call — recording service, operation, timing,
token counts, cache hit/miss, and a simple cost estimate.  All data is
persisted to the api_usage_log table in SQLite.

Cost constants (May 2025 public pricing)
-----------------------------------------
Groq  llama-3.1-8b-instant:
  Input:  $0.05 / 1M tokens  →  5e-8 USD per token
  Output: $0.08 / 1M tokens  →  8e-8 USD per token

Tavily Basic plan:
  ~$0.001 per live search;  cache hits cost $0.00

Public API
----------
log_api_call(...)                          → None  (never raises)
get_usage_stats(days)                      → dict  totals + cache hit rate + by-service
get_daily_summary(days)                    → list[dict]  per-calendar-day rows
get_recent_calls(limit)                    → list[dict]  most-recent log entries
estimate_groq_cost(input_tokens, output)   → float
estimate_tavily_cost(cache_hit)            → float
"""

import logging
from datetime import datetime, timedelta, timezone

from ..utils.db import get_connection

logger = logging.getLogger(__name__)

# ── Cost constants ─────────────────────────────────────────────────────────────

_GROQ_INPUT_COST_PER_TOKEN:  float = 5e-8   # $0.05 / 1M tokens
_GROQ_OUTPUT_COST_PER_TOKEN: float = 8e-8   # $0.08 / 1M tokens
_TAVILY_COST_PER_SEARCH:     float = 0.001  # ~$0.001 / live search


# ── Cost helpers ───────────────────────────────────────────────────────────────

def estimate_groq_cost(input_tokens: int, output_tokens: int) -> float:
    """Return estimated USD cost for one Groq chat completion."""
    return round(
        input_tokens  * _GROQ_INPUT_COST_PER_TOKEN +
        output_tokens * _GROQ_OUTPUT_COST_PER_TOKEN,
        8,
    )


def estimate_tavily_cost(cache_hit: bool = False) -> float:
    """Return estimated USD cost for one Tavily search (0.0 on cache hit)."""
    return 0.0 if cache_hit else _TAVILY_COST_PER_SEARCH


# ── Write ──────────────────────────────────────────────────────────────────────

def log_api_call(
    service: str,
    operation: str,
    model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    duration_ms: int | None = None,
    cache_hit: bool = False,
    query_hint: str | None = None,
    estimated_cost_usd: float | None = None,
) -> None:
    """
    Persist one API call record to api_usage_log.

    Silently swallows DB errors — a logging failure must never propagate to
    the caller or break the service that triggered the API call.
    """
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO api_usage_log
                    (service, operation, model, input_tokens, output_tokens,
                     duration_ms, cache_hit, query_hint, estimated_cost_usd)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    service,
                    operation,
                    model,
                    input_tokens,
                    output_tokens,
                    duration_ms,
                    1 if cache_hit else 0,
                    query_hint[:120] if query_hint else None,
                    estimated_cost_usd,
                ),
            )
    except Exception:
        logger.exception("api_usage_service: failed to log API call (suppressed)")


# ── Read ───────────────────────────────────────────────────────────────────────

def get_usage_stats(days: int = 7) -> dict:
    """
    Aggregate totals for the last ``days`` calendar days.

    Returns
    -------
    {
        total_calls:         int,
        cache_hits:          int,
        cache_hit_rate:      float,   # 0.0 – 1.0
        total_input_tokens:  int,
        total_output_tokens: int,
        estimated_cost_usd:  float,
        by_service: {
            "<service>": {
                calls: int, cache_hits: int,
                input_tokens: int, output_tokens: int,
                estimated_cost_usd: float,
            }
        }
    }
    """
    cutoff = _cutoff_ts(days)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT service, input_tokens, output_tokens,
                   cache_hit, estimated_cost_usd
            FROM   api_usage_log
            WHERE  created_at >= ?
            """,
            (cutoff,),
        ).fetchall()

    total_calls = len(rows)
    cache_hits  = sum(r["cache_hit"]               for r in rows)
    in_tokens   = sum(r["input_tokens"]  or 0      for r in rows)
    out_tokens  = sum(r["output_tokens"] or 0      for r in rows)
    total_cost  = round(sum(r["estimated_cost_usd"] or 0.0 for r in rows), 6)

    by_service: dict[str, dict] = {}
    for r in rows:
        svc = r["service"]
        if svc not in by_service:
            by_service[svc] = {
                "calls": 0, "cache_hits": 0,
                "input_tokens": 0, "output_tokens": 0,
                "estimated_cost_usd": 0.0,
            }
        s = by_service[svc]
        s["calls"]              += 1
        s["cache_hits"]         += r["cache_hit"]
        s["input_tokens"]       += r["input_tokens"]  or 0
        s["output_tokens"]      += r["output_tokens"] or 0
        s["estimated_cost_usd"]  = round(
            s["estimated_cost_usd"] + (r["estimated_cost_usd"] or 0.0), 6
        )

    return {
        "total_calls":         total_calls,
        "cache_hits":          cache_hits,
        "cache_hit_rate":      round(cache_hits / total_calls, 4) if total_calls else 0.0,
        "total_input_tokens":  in_tokens,
        "total_output_tokens": out_tokens,
        "estimated_cost_usd":  total_cost,
        "by_service":          by_service,
    }


def get_daily_summary(days: int = 7) -> list[dict]:
    """
    Per-calendar-day breakdown (UTC) for the last ``days`` days.
    Ordered chronologically (oldest first).
    """
    cutoff = _cutoff_ts(days)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT DATE(created_at)                          AS day,
                   COUNT(*)                                  AS calls,
                   SUM(cache_hit)                            AS cache_hits,
                   SUM(COALESCE(input_tokens,  0))           AS input_tokens,
                   SUM(COALESCE(output_tokens, 0))           AS output_tokens,
                   SUM(COALESCE(estimated_cost_usd, 0.0))    AS estimated_cost_usd
            FROM   api_usage_log
            WHERE  created_at >= ?
            GROUP  BY DATE(created_at)
            ORDER  BY day ASC
            """,
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_recent_calls(limit: int = 20) -> list[dict]:
    """Return the most recent ``limit`` log entries, newest first."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, service, operation, model, input_tokens, output_tokens,
                   duration_ms, cache_hit, query_hint, estimated_cost_usd, created_at
            FROM   api_usage_log
            ORDER  BY id DESC
            LIMIT  ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Private helpers ────────────────────────────────────────────────────────────

def _cutoff_ts(days: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.strftime("%Y-%m-%d %H:%M:%S")
