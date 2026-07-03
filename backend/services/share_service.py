"""
Shareable link resolution and creation for feed packages and chat threads.

Public API
----------
create_share_link(type_, resource_id, created_by, scheme, netloc) -> dict
resolve_share_link(token) -> dict | None
fork_chat(token, new_owner_id) -> str | None
"""

from __future__ import annotations

import secrets
import uuid


def _dashboard_snapshot(user_id: str) -> dict:
    """Public dashboard data for user_id — same shape as the authenticated
    GET /stats/reading + GET /activity/all responses, so the frontend can
    render it with the exact same components as the owner's own dashboard."""
    from .feed_read_service import get_reading_stats
    from .activity_service import get_all_projects_activity

    return {
        "stats":    get_reading_stats(user_id=user_id),
        "activity": get_all_projects_activity(user_id, days=365),
    }


def create_share_link(type_: str, resource_id: str, created_by: str, scheme: str, netloc: str) -> dict:
    from ..utils.db import get_connection

    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM share_links WHERE type = ? AND resource_id = ? AND created_by = ?",
            (type_, resource_id, created_by),
        ).fetchone()
        if row:
            token = row["id"]
        else:
            token = secrets.token_urlsafe(9)
            conn.execute(
                "INSERT INTO share_links (id, type, resource_id, created_by) VALUES (?, ?, ?, ?)",
                (token, type_, resource_id, created_by),
            )
    return {"token": token, "share_url": f"{scheme}://{netloc}/share/{token}"}


def resolve_share_link(token: str) -> dict | None:
    from ..utils.db import get_connection

    with get_connection() as conn:
        row = conn.execute(
            "SELECT type, resource_id FROM share_links WHERE id = ?", (token,)
        ).fetchone()
    if not row:
        return None

    if row["type"] == "chat":
        session_id = row["resource_id"]
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT role, content, created_at FROM chat_messages WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        messages = [{"role": r["role"], "content": r["content"], "created_at": r["created_at"]} for r in rows]
        return {"type": "chat", "messages": messages, "resource_id": session_id}

    if row["type"] == "dashboard":
        user_id = row["resource_id"]
        with get_connection() as conn:
            user_row = conn.execute("SELECT name FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not user_row:
            return None
        snapshot = _dashboard_snapshot(user_id)
        return {"type": "dashboard", "username": user_row["name"], **snapshot}

    # type == "feed"; resource_id is "{projectId}/{day}" or "{projectId}/{day}/{articleIdx}"
    resource_id = row["resource_id"]
    parts = resource_id.split("/")
    project_id, insight_id = parts[0], parts[1]

    from .project_service import get_project_insight

    package = get_project_insight(int(insight_id))
    if not package or package.get("project_id") != project_id:
        return None
    return {"type": "feed", "package": package, "resource_id": resource_id}


def fork_chat(token: str, new_owner_id: str) -> str | None:
    from ..utils.db import get_connection

    with get_connection() as conn:
        row = conn.execute(
            "SELECT resource_id FROM share_links WHERE id = ? AND type = 'chat'", (token,)
        ).fetchone()
        if not row:
            return None
        original_chat_id = row["resource_id"]

        messages = conn.execute(
            "SELECT role, content, topic_hint FROM chat_messages WHERE session_id = ? ORDER BY id ASC",
            (original_chat_id,),
        ).fetchall()

        new_chat_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO chat_sessions (session_id, user_id, forked_from) VALUES (?, ?, ?)",
            (new_chat_id, new_owner_id, original_chat_id),
        )
        for m in messages:
            conn.execute(
                "INSERT INTO chat_messages (session_id, role, content, topic_hint) VALUES (?, ?, ?, ?)",
                (new_chat_id, m["role"], m["content"], m["topic_hint"]),
            )
    return new_chat_id
