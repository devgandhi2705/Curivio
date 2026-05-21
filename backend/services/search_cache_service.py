"""
Search result cache — SHA-256-keyed, SQLite-backed, TTL-expiring cache for
Tavily search results.

Separate from feed_cache_service, which caches complete LLM-generated feeds.
This cache operates one level earlier: it stores raw Tavily results so that
repeating the same query within the TTL window costs zero additional API calls.

TTL
---
Controlled by the SEARCH_CACHE_TTL_HOURS env var (default: 6).
Expiry is checked at read time.  Call purge_expired() from a maintenance job
to reclaim disk space.

Public API
----------
build_search_key(query)        → str
get_cached_search(query)       → list[dict] | None
cache_search(query, results)   → None
purge_expired()                → int   (rows deleted)
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone

from ..utils.db import get_connection

from ..config import SEARCH_CACHE_TTL_HOURS


# ── Key building ───────────────────────────────────────────────────────────────

def build_search_key(query: str) -> str:
    """SHA-256 of the normalised query (stripped + lower-cased)."""
    return hashlib.sha256(query.strip().lower().encode()).hexdigest()


# ── Read ───────────────────────────────────────────────────────────────────────

def get_cached_search(query: str) -> list[dict] | None:
    """
    Return cached results if they exist and have not expired.
    Increments hit_count on a cache hit.
    Returns None on a miss or if the entry is older than SEARCH_CACHE_TTL_HOURS.
    """
    key    = build_search_key(query)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=SEARCH_CACHE_TTL_HOURS)

    with get_connection() as conn:
        row = conn.execute(
            "SELECT results_json, created_at FROM search_cache WHERE cache_key = ?",
            (key,),
        ).fetchone()

        if row is None:
            return None

        if _parse_ts(row["created_at"]) < cutoff:
            return None  # expired — leave the row for purge_expired()

        conn.execute(
            "UPDATE search_cache SET hit_count = hit_count + 1 WHERE cache_key = ?",
            (key,),
        )

    return json.loads(row["results_json"])


# ── Write ──────────────────────────────────────────────────────────────────────

def cache_search(query: str, results: list[dict]) -> None:
    """Upsert a search result cache entry, resetting the TTL and hit_count."""
    key = build_search_key(query)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO search_cache (cache_key, query, results_json, hit_count, created_at)
            VALUES (?, ?, ?, 0, CURRENT_TIMESTAMP)
            ON CONFLICT(cache_key) DO UPDATE SET
                query        = excluded.query,
                results_json = excluded.results_json,
                hit_count    = 0,
                created_at   = CURRENT_TIMESTAMP
            """,
            (key, query.strip().lower(), json.dumps(results)),
        )


# ── Maintenance ────────────────────────────────────────────────────────────────

def purge_expired() -> int:
    """Delete all cache rows older than SEARCH_CACHE_TTL_HOURS. Returns row count."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=SEARCH_CACHE_TTL_HOURS)
    ).strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM search_cache WHERE created_at < ?", (cutoff,)
        )
    return cursor.rowcount


# ── Private helpers ────────────────────────────────────────────────────────────

def _parse_ts(value: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Unrecognised timestamp format: {value!r}")
