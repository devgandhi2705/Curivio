"""
Feed storage service — persists and retrieves generated learning feeds.

All writes go through save_feed(); reads through get_latest_feed() / list_feeds().
The JSON blob keeps the full feed intact; denormalized columns (insight_title,
learning_stage, difficulty) allow cheap queries without deserializing.
"""

import json

from ..utils.db import get_connection


# ── Write ─────────────────────────────────────────────────────────────────────

def save_feed(
    interests: str,
    feed: dict,
    source: str = "scheduler",
    learning_stage: str | None = None,
    difficulty: str | None = None,
) -> int:
    """
    Persist a generated feed and return the new row ID.

    Args:
        interests:      The interest string used to generate the feed.
        feed:           The full feed dict (news_insight, learning_topics, next_step).
        source:         "scheduler" (automated) or "user" (on-demand via API).
        learning_stage: Stage snapshot at generation time (early/developing/proficient).
        difficulty:     Difficulty preference snapshot at generation time.

    Returns:
        The integer primary key of the inserted row.
    """
    insight_title = feed.get("news_insight", {}).get("title")

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO generated_feeds
                (interests, feed_json, insight_title, learning_stage, difficulty, source)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (interests, json.dumps(feed), insight_title, learning_stage, difficulty, source),
        )
    return cursor.lastrowid


# ── Read ──────────────────────────────────────────────────────────────────────

def get_latest_feed() -> dict | None:
    """
    Return the most recently generated feed as a dict, or None if none exist.

    The returned dict has all DB columns plus a top-level "feed" key containing
    the deserialized feed dict (news_insight, learning_topics, next_step).
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM generated_feeds ORDER BY generated_at DESC LIMIT 1"
        ).fetchone()

    if row is None:
        return None

    result = dict(row)
    result["feed"] = json.loads(result.pop("feed_json"))
    return result


def get_feed_by_id(feed_id: int) -> dict | None:
    """Return a specific feed by its primary key, or None if not found."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM generated_feeds WHERE id = ?", (feed_id,)
        ).fetchone()

    if row is None:
        return None

    result = dict(row)
    result["feed"] = json.loads(result.pop("feed_json"))
    return result


def list_feeds(limit: int = 10) -> list[dict]:
    """
    Return the N most recent feed summaries (no JSON blob — fast for list views).

    Each entry contains: id, interests, insight_title, learning_stage,
                         difficulty, source, generated_at.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, interests, insight_title, learning_stage,
                   difficulty, source, generated_at
            FROM   generated_feeds
            ORDER  BY generated_at DESC
            LIMIT  ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
