"""
Digest storage service — persists and retrieves daily learning digests.

Schema rationale
----------------
Unlike generated_feeds (which stores a raw JSON blob), daily_digests
denormalizes every field so queries never need to deserialize JSON for
filtering.  Only the structured list fields (learning_topics, source_links)
stay as JSON because their shape varies.

Public API
----------
save_digest(feed, source)           → int  (new row id)
get_latest_digest()                 → dict | None
get_digest_by_id(id)                → dict | None
get_digests_by_date(date_str)       → list[dict]
list_digests(limit)                 → list[dict]
"""

import json
from datetime import date, datetime

from ..utils.db import get_connection


# ── Internal helpers ──────────────────────────────────────────────────────────

def _row_to_dict(row) -> dict:
    """Deserialize JSON columns and return a plain dict."""
    result = dict(row)
    result["learning_topics"] = json.loads(result.pop("learning_topics_json"))
    result["source_links"]    = json.loads(result.pop("source_links_json"))
    return result


def _extract_fields(feed: dict) -> tuple:
    """
    Pull the six scalar/list fields out of a feed dict.
    Returns (news_title, news_summary, why_it_matters,
             learning_topics_json, next_step, source_links_json).
    """
    insight  = feed.get("news_insight", {})
    topics   = feed.get("learning_topics", [])
    sources  = insight.get("sources", [])

    return (
        insight.get("title", ""),
        insight.get("summary", ""),
        insight.get("why_it_matters", ""),
        json.dumps(topics),
        feed.get("next_step", ""),
        json.dumps(sources),
    )


# ── Write ─────────────────────────────────────────────────────────────────────

def save_digest(feed: dict, source: str = "scheduler") -> int:
    """
    Persist a learning feed as a daily digest row and return the new row id.

    Args:
        feed:   Full feed dict with keys news_insight, learning_topics, next_step.
        source: "scheduler" (automated) or "user" (on-demand).

    Returns:
        Integer primary key of the inserted row.
    """
    (
        news_title, news_summary, why_it_matters,
        learning_topics_json, next_step, source_links_json,
    ) = _extract_fields(feed)

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO daily_digests
                (news_title, news_summary, why_it_matters,
                 learning_topics_json, next_step, source_links_json, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                news_title, news_summary, why_it_matters,
                learning_topics_json, next_step, source_links_json, source,
            ),
        )
    return cursor.lastrowid


# ── Read ──────────────────────────────────────────────────────────────────────

def get_latest_digest() -> dict | None:
    """
    Return the most recently generated digest, or None if the table is empty.

    The returned dict has all DB columns plus deserialized
    ``learning_topics`` (list) and ``source_links`` (list) keys.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM daily_digests ORDER BY generated_at DESC, id DESC LIMIT 1"
        ).fetchone()
    return _row_to_dict(row) if row else None


def get_digest_by_id(digest_id: int) -> dict | None:
    """Return a specific digest by primary key, or None if not found."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM daily_digests WHERE id = ?", (digest_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def get_digests_by_date(date_str: str) -> list[dict]:
    """
    Return all digests whose ``generated_at`` falls on the given calendar date.

    Args:
        date_str: ISO-8601 date string, e.g. ``"2025-05-14"``.
                  Also accepts a ``datetime.date`` object.

    Returns:
        List of digest dicts (may be empty), newest first.
    """
    if isinstance(date_str, (date, datetime)):
        date_str = date_str.strftime("%Y-%m-%d")

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM daily_digests
            WHERE  DATE(generated_at) = DATE(?)
            ORDER  BY generated_at DESC, id DESC
            """,
            (date_str,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def list_digests(limit: int = 10) -> list[dict]:
    """
    Return the N most recent digests with all fields deserialized.

    Args:
        limit: Maximum number of rows to return (default 10).
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM daily_digests
            ORDER  BY generated_at DESC, id DESC
            LIMIT  ?
            """,
            (limit,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]
