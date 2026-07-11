from backend.utils.db import get_connection


def _row_to_item(row) -> dict:
    return {
        "articleKey":   row["article_key"],
        "title":        row["title"],
        "summary":      row["summary"] or "",
        "category":     row["category"],
        "content_type": row["content_type"] or "news",
        "projectId":    row["project_id"] or "",
        "projectName":  row["project_name"] or "",
        "insightId":    row["insight_id"] or None,
        "queuedAt":     row["queued_at"],
    }


def list_queue(user_id: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM read_later_items WHERE user_id=? ORDER BY queued_at DESC",
            (user_id,),
        ).fetchall()
    return [_row_to_item(r) for r in rows]


def add_item(
    user_id: str,
    article_key: str,
    title: str = "",
    summary: str = "",
    category: str | None = None,
    content_type: str = "news",
    project_id: str = "",
    project_name: str = "",
    insight_id=None,
) -> dict:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO read_later_items
                (user_id, article_key, title, summary, category, content_type, project_id, project_name, insight_id, queued_at)
            VALUES (?,?,?,?,?,?,?,?,?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, article_key) DO UPDATE SET
                title=excluded.title, summary=excluded.summary, category=excluded.category,
                content_type=excluded.content_type, project_id=excluded.project_id,
                project_name=excluded.project_name, insight_id=excluded.insight_id,
                queued_at=CURRENT_TIMESTAMP
            """,
            (user_id, article_key, title, summary, category, content_type,
             project_id, project_name, str(insight_id) if insight_id is not None else ""),
        )
        row = conn.execute(
            "SELECT * FROM read_later_items WHERE user_id=? AND article_key=?",
            (user_id, article_key),
        ).fetchone()
    return _row_to_item(row)


def remove_item(user_id: str, article_key: str) -> bool:
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM read_later_items WHERE user_id=? AND article_key=?",
            (user_id, article_key),
        )
    return cur.rowcount > 0


def clear_queue(user_id: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM read_later_items WHERE user_id=?", (user_id,))
