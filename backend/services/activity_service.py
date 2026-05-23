"""
Learning activity service — daily counts per project for the calendar heatmap.

Returns one record per calendar day covering the past `days` days, including
days with zero activity (so the frontend can render a complete 52-week grid).

Each record:
    date               — "YYYY-MM-DD"
    packages_generated — packages created on that day
    cards_read         — feed cards marked as read on that day
"""

from __future__ import annotations

from datetime import date, timedelta


def get_all_projects_activity(user_id: str, days: int = 365) -> list[dict]:
    from ..utils.db import get_connection

    today = date.today()
    start = today - timedelta(days=days - 1)
    start_str = start.isoformat()

    with get_connection() as conn:
        pkg_rows = conn.execute(
            """SELECT DATE(pi.generated_at) AS d, COUNT(*) AS n
               FROM project_insights pi
               JOIN learning_projects lp ON pi.project_id = lp.project_id
               WHERE lp.user_id = ? AND DATE(pi.generated_at) >= ?
               GROUP BY d""",
            (user_id, start_str),
        ).fetchall()

        read_rows = conn.execute(
            """SELECT DATE(far.read_at) AS d, COUNT(*) AS n
               FROM feed_article_reads far
               JOIN learning_projects lp ON far.project_id = lp.project_id
               WHERE lp.user_id = ? AND DATE(far.read_at) >= ?
               GROUP BY d""",
            (user_id, start_str),
        ).fetchall()

    pkg_map  = {r["d"]: r["n"] for r in pkg_rows}
    read_map = {r["d"]: r["n"] for r in read_rows}

    result = []
    cursor = start
    while cursor <= today:
        ds = cursor.isoformat()
        result.append({
            "date":               ds,
            "packages_generated": pkg_map.get(ds, 0),
            "cards_read":         read_map.get(ds, 0),
        })
        cursor += timedelta(days=1)

    return result


def get_project_activity(project_id: str, days: int = 365) -> list[dict]:
    from ..utils.db import get_connection

    today = date.today()
    start = today - timedelta(days=days - 1)
    start_str = start.isoformat()

    with get_connection() as conn:
        pkg_rows = conn.execute(
            """SELECT DATE(generated_at) AS d, COUNT(*) AS n
               FROM project_insights
               WHERE project_id = ? AND DATE(generated_at) >= ?
               GROUP BY d""",
            (project_id, start_str),
        ).fetchall()

        read_rows = conn.execute(
            """SELECT DATE(read_at) AS d, COUNT(*) AS n
               FROM feed_article_reads
               WHERE project_id = ? AND DATE(read_at) >= ?
               GROUP BY d""",
            (project_id, start_str),
        ).fetchall()

    pkg_map  = {r["d"]: r["n"] for r in pkg_rows}
    read_map = {r["d"]: r["n"] for r in read_rows}

    result = []
    cursor = start
    while cursor <= today:
        ds = cursor.isoformat()
        result.append({
            "date":               ds,
            "packages_generated": pkg_map.get(ds, 0),
            "cards_read":         read_map.get(ds, 0),
        })
        cursor += timedelta(days=1)

    return result
