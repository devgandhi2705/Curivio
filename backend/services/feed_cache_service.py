"""
Feed cache service — SHA-256-keyed, SQLite-backed, TTL-expiring cache for
generated learning feeds.

Cache key
---------
SHA-256( normalize(interests) + "|" + memory_fingerprint )

The memory fingerprint is a deterministic JSON snapshot of the four signals
that actually change the LLM output: liked topics, suppressed topics,
difficulty preference, and learning stage.  If none of these change between
requests, the prompt would be identical, so the cached feed is safe to reuse.

TTL
---
Controlled by the FEED_CACHE_TTL_HOURS env var (default 24).  Expiry is
enforced at read time — stale rows are simply ignored.  Call purge_expired()
from a maintenance job to reclaim space.

Public API
----------
build_cache_key(interests, memory_fingerprint)  → str
get_cached_feed(cache_key)                      → dict | None
cache_feed(cache_key, interests, feed)          → None
purge_expired()                                 → int  (rows deleted)
"""

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

from ..utils.db import get_connection

CACHE_TTL_HOURS: int = int(os.getenv("FEED_CACHE_TTL_HOURS", "24"))


# ── Key building ──────────────────────────────────────────────────────────────

def build_cache_key(interests: str, memory_fingerprint: str) -> str:
    """
    Deterministic SHA-256 key from normalised interests + memory fingerprint.

    Normalisation: strip whitespace, fold to lower-case.  Two interest strings
    that differ only in case or surrounding spaces map to the same cache entry.
    """
    raw = f"{interests.strip().lower()}|{memory_fingerprint}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ── Read ──────────────────────────────────────────────────────────────────────

def get_cached_feed(cache_key: str) -> dict | None:
    """
    Return the cached feed dict if the entry exists and has not expired.

    On a hit the row's hit_count is incremented so callers can observe reuse.
    Returns None on a miss or if the entry is older than CACHE_TTL_HOURS.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=CACHE_TTL_HOURS)

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT feed_json, generated_at FROM feed_cache
            WHERE  cache_key = ?
            """,
            (cache_key,),
        ).fetchone()

        if row is None:
            return None

        # SQLite stores timestamps as text; parse to compare with cutoff
        generated_at = _parse_ts(row["generated_at"])
        if generated_at < cutoff:
            return None  # expired — leave the row for purge_expired()

        conn.execute(
            "UPDATE feed_cache SET hit_count = hit_count + 1 WHERE cache_key = ?",
            (cache_key,),
        )

    return json.loads(row["feed_json"])


# ── Write ─────────────────────────────────────────────────────────────────────

def cache_feed(cache_key: str, interests: str, feed: dict) -> None:
    """
    Insert or replace a cache entry for the given key.

    Upserting resets generated_at so a re-generated feed gets a fresh TTL.
    """
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO feed_cache (cache_key, interests, feed_json, hit_count, generated_at)
            VALUES (?, ?, ?, 0, CURRENT_TIMESTAMP)
            ON CONFLICT(cache_key) DO UPDATE SET
                interests    = excluded.interests,
                feed_json    = excluded.feed_json,
                hit_count    = 0,
                generated_at = CURRENT_TIMESTAMP
            """,
            (cache_key, interests.strip().lower(), json.dumps(feed)),
        )


# ── Maintenance ───────────────────────────────────────────────────────────────

def purge_expired() -> int:
    """
    Delete all cache rows older than CACHE_TTL_HOURS.
    Returns the number of rows removed.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=CACHE_TTL_HOURS)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM feed_cache WHERE generated_at < ?", (cutoff,)
        )
    return cursor.rowcount


# ── Private helpers ───────────────────────────────────────────────────────────

def _parse_ts(value: str) -> datetime:
    """Parse a SQLite CURRENT_TIMESTAMP string to an aware UTC datetime."""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Unrecognised timestamp format: {value!r}")
