"""
Feed article read-tracking service.

Tracks which insight cards a user has marked as read/unread.
Article identity is based on a stable key derived from the title.

Public API
----------
article_key_from_title(title)  -> str   (shared helper — must match frontend)
mark_read(project_id, insight_id, article_key, article_title) -> dict
mark_unread(project_id, insight_id, article_key)              -> bool
get_read_keys(project_id, insight_id)                         -> set[str]
get_reads_for_insight(project_id, insight_id)                 -> list[dict]
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def article_key_from_title(title: str) -> str:
    """Stable, URL-safe key derived from the article title.
    Must produce identical output to the frontend's articleKeyFromTitle()."""
    key = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return key[:60]


# ─────────────────────────────────────────────────────────────────────────────

def mark_read(
    project_id: str,
    insight_id: int,
    article_key: str,
    article_title: str = "",
) -> dict:
    """Mark an article as read (idempotent — returns existing row if already read)."""
    from ..utils.db import get_connection
    now = _now()
    with get_connection() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO feed_article_reads
               (project_id, insight_id, article_key, article_title, read_at)
               VALUES (?, ?, ?, ?, ?)""",
            (project_id, insight_id, article_key, article_title, now),
        )
        row = conn.execute(
            """SELECT id, project_id, insight_id, article_key, article_title, read_at
               FROM feed_article_reads
               WHERE project_id = ? AND insight_id = ? AND article_key = ?""",
            (project_id, insight_id, article_key),
        ).fetchone()
    return dict(row) if row else {}


def mark_unread(project_id: str, insight_id: int, article_key: str) -> bool:
    """Remove a read record. Returns True if a row was deleted."""
    from ..utils.db import get_connection
    with get_connection() as conn:
        r = conn.execute(
            """DELETE FROM feed_article_reads
               WHERE project_id = ? AND insight_id = ? AND article_key = ?""",
            (project_id, insight_id, article_key),
        )
    return r.rowcount > 0


def get_read_keys(project_id: str, insight_id: int) -> set[str]:
    """Return the set of article_keys that have been read for this package."""
    from ..utils.db import get_connection
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT article_key FROM feed_article_reads
               WHERE project_id = ? AND insight_id = ?""",
            (project_id, insight_id),
        ).fetchall()
    return {r["article_key"] for r in rows}


def get_reads_for_insight(project_id: str, insight_id: int) -> list[dict]:
    """Return full read records for all read articles in a package."""
    from ..utils.db import get_connection
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT id, project_id, insight_id, article_key, article_title, read_at
               FROM feed_article_reads
               WHERE project_id = ? AND insight_id = ?
               ORDER BY read_at DESC""",
            (project_id, insight_id),
        ).fetchall()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Reading stats
# ─────────────────────────────────────────────────────────────────────────────

def get_reading_stats(user_id: str | None = None) -> dict:
    """
    Compute reading stats from the feed_article_reads, project_insights,
    and learning_projects tables.

    Returns:
        total_cards_read   — all-time read count
        today_cards_read   — reads on today's UTC date
        current_streak     — consecutive days ending today (or yesterday)
        longest_streak     — max consecutive-day run ever
        active_projects    — total projects that exist
        total_packages     — total daily packages generated
        total_days_active  — distinct calendar days with at least 1 read
    """
    from ..utils.db import get_connection

    user_join  = "JOIN learning_projects lp ON lp.project_id = far.project_id" if user_id else ""
    user_where = "AND lp.user_id = ?" if user_id else ""
    uid_param  = (user_id,) if user_id else ()

    with get_connection() as conn:
        total_cards_read = conn.execute(
            f"""SELECT COUNT(*) AS n FROM feed_article_reads far
                {user_join}
                WHERE 1=1 {user_where}""",
            uid_param,
        ).fetchone()["n"]

        today_str = date.today().isoformat()
        today_cards_read = conn.execute(
            f"""SELECT COUNT(*) AS n FROM feed_article_reads far
                {user_join}
                WHERE DATE(far.read_at) = ? {user_where}""",
            (today_str,) + uid_param,
        ).fetchone()["n"]

        # All distinct dates that had at least one read — newest first
        date_rows = conn.execute(
            f"""SELECT DISTINCT DATE(far.read_at) AS d
                FROM feed_article_reads far
                {user_join}
                WHERE 1=1 {user_where}
                ORDER BY d DESC""",
            uid_param,
        ).fetchall()

        active_projects = conn.execute(
            "SELECT COUNT(*) AS n FROM learning_projects" + (" WHERE user_id = ?" if user_id else ""),
            uid_param,
        ).fetchone()["n"]

        total_packages = conn.execute(
            """SELECT COUNT(*) AS n FROM project_insights pi""" + (
                " JOIN learning_projects lp ON lp.project_id = pi.project_id WHERE lp.user_id = ?" if user_id else ""
            ),
            uid_param,
        ).fetchone()["n"]

    date_strs = [r["d"] for r in date_rows]
    current_streak, longest_streak = _compute_streaks(date_strs)

    return {
        "total_cards_read":  total_cards_read,
        "today_cards_read":  today_cards_read,
        "current_streak":    current_streak,
        "longest_streak":    longest_streak,
        "active_projects":   active_projects,
        "total_packages":    total_packages,
        "total_days_active": len(date_strs),
    }


def _compute_streaks(dates_desc: list[str]) -> tuple[int, int]:
    """
    Given a DESC-sorted list of unique date strings ('YYYY-MM-DD'),
    return (current_streak, longest_streak).

    current_streak: consecutive days ending today or yesterday (still "active").
    longest_streak: longest consecutive-day run in the entire history.
    """
    if not dates_desc:
        return 0, 0

    dates = sorted({date.fromisoformat(d) for d in dates_desc}, reverse=True)
    today = date.today()

    # ── Current streak ──────────────────────────────────────────────────────
    current = 0
    # Only count if there's a read today or yesterday (streak isn't broken)
    if dates[0] >= today - timedelta(days=1):
        current = 1
        prev = dates[0]
        for d in dates[1:]:
            if prev - d == timedelta(days=1):
                current += 1
                prev = d
            else:
                break

    # ── Longest streak ──────────────────────────────────────────────────────
    longest = 1
    run = 1
    for i in range(1, len(dates)):
        if dates[i - 1] - dates[i] == timedelta(days=1):
            run += 1
            longest = max(longest, run)
        else:
            run = 1

    return current, longest
