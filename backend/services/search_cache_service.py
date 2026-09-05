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
content_for_urls(urls)         → dict[str, str]
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


# ── Content lookup by URL ─────────────────────────────────────────────────────
# Rows here are keyed by QUERY, but each cached result already carries the
# retrieved page's extracted `content`. A Feed card stores only its source URLs
# (FeedContext.source_urls) plus a ~1650-char distillation — the article text
# that produced the card is never persisted alongside it. This reads that text
# back out of the cache by URL, which is what lets a Feed chat answer be grounded
# in the real article instead of the card's own summary.
#
# Measured on the real DB at the time this was written: 2165 cached URLs carry
# content, and 49.3% of article_provenance URLs match one exactly (51.4%
# normalised). Per card that is a mean of 8528 chars of real source text against
# the 1650 the card itself holds. Coverage is partial by nature — the cache
# expires on SEARCH_CACHE_TTL_HOURS — so every caller must treat a miss as
# normal and fall back to the card, never as an error.

_MAX_CHARS_PER_SOURCE = 1500
_MAX_CHARS_TOTAL      = 6000


def _norm_url(url: str) -> str:
    """Strip scheme/www/query/fragment/trailing slash so near-identical URLs match."""
    u = (url or "").split("#")[0].split("?")[0].rstrip("/").lower()
    for prefix in ("https://", "http://"):
        if u.startswith(prefix):
            u = u[len(prefix):]
    return u[4:] if u.startswith("www.") else u


def content_for_urls(
    urls: list[str],
    *,
    max_per_source: int = _MAX_CHARS_PER_SOURCE,
    max_total: int = _MAX_CHARS_TOTAL,
) -> dict[str, str]:
    """Extracted article text for whichever of *urls* the cache still holds.

    Returns {original_url: content}, longest-content-wins per URL, truncated to
    max_per_source each and max_total overall (the budget guard — an uncapped
    card ran to 20746 chars). Missing URLs are simply absent from the result.
    Never raises: a cache miss or a malformed row degrades to less grounding,
    never to a failed chat turn.
    """
    wanted = {_norm_url(u): u for u in (urls or []) if u}
    if not wanted:
        return {}

    best: dict[str, str] = {}
    try:
        with get_connection() as conn:
            rows = conn.execute("SELECT results_json FROM search_cache").fetchall()
    except Exception:
        return {}

    for row in rows:
        try:
            articles = json.loads(row["results_json"])
        except Exception:
            continue
        if not isinstance(articles, list):
            continue
        for article in articles:
            if not isinstance(article, dict):
                continue
            key = _norm_url(article.get("url", ""))
            if key not in wanted:
                continue
            text = (article.get("content") or "").strip()
            if len(text) > len(best.get(key, "")):
                best[key] = text

    out: dict[str, str] = {}
    budget = max_total
    for key, original in wanted.items():
        text = best.get(key, "")
        if not text or budget <= 0:
            continue
        clipped = text[:min(max_per_source, budget)]
        out[original] = clipped
        budget -= len(clipped)
    return out
