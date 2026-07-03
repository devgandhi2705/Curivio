"""
Per-card notes service.

Each note is keyed by (project_id, insight_id, card_id) where card_id is the
article_key derived from the card title (same slug as feed read-tracking).

Public API
----------
upsert_note(project_id, insight_id, card_id, content) -> dict
delete_note(project_id, insight_id, card_id)          -> bool
get_notes_for_insight(project_id, insight_id)          -> dict[card_id, content]
"""

from __future__ import annotations

from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def upsert_note(
    project_id: str,
    insight_id: int,
    card_id: str,
    content: str,
) -> dict:
    """Create or update a note. Returns the saved record."""
    from ..utils.db import get_connection

    now = _now()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO card_notes (project_id, insight_id, card_id, content, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(project_id, insight_id, card_id)
               DO UPDATE SET content = excluded.content, updated_at = excluded.updated_at""",
            (project_id, insight_id, card_id, content, now),
        )
        row = conn.execute(
            """SELECT id, project_id, insight_id, card_id, content, updated_at
               FROM card_notes
               WHERE project_id = ? AND insight_id = ? AND card_id = ?""",
            (project_id, insight_id, card_id),
        ).fetchone()
    return dict(row) if row else {}


def delete_note(project_id: str, insight_id: int, card_id: str) -> bool:
    """Delete a note. Returns True if a row was removed."""
    from ..utils.db import get_connection

    with get_connection() as conn:
        r = conn.execute(
            """DELETE FROM card_notes
               WHERE project_id = ? AND insight_id = ? AND card_id = ?""",
            (project_id, insight_id, card_id),
        )
    return r.rowcount > 0


def get_notes_for_insight(project_id: str, insight_id: int) -> dict[str, str]:
    """Return {card_id: content} for all notes belonging to this package."""
    from ..utils.db import get_connection

    with get_connection() as conn:
        rows = conn.execute(
            """SELECT card_id, content FROM card_notes
               WHERE project_id = ? AND insight_id = ?""",
            (project_id, insight_id),
        ).fetchall()
    return {r["card_id"]: r["content"] for r in rows}


def get_all_notes_for_user(user_id: str) -> list[dict]:
    """
    All notes across every project owned by user_id, for the Dashboard notes
    module. Sorted project_id ASC, day_number DESC (matches the module's
    per-project grouping order).

    card_notes has no article_id/title/category columns of its own — those
    live inside project_insights.insight_json (a JSON blob per day), keyed
    by card_id via article_key_from_title(). Each distinct insight_json blob
    is parsed once and cached to avoid re-parsing per note row.
    """
    import json
    from ..utils.db import get_connection
    from .feed_read_service import article_key_from_title

    with get_connection() as conn:
        rows = conn.execute(
            """SELECT cn.id, cn.project_id, cn.insight_id, cn.card_id,
                      cn.content, cn.updated_at,
                      pi.day_number, pi.insight_json,
                      lp.name AS project_name
               FROM card_notes cn
               JOIN learning_projects lp ON lp.project_id = cn.project_id
               JOIN project_insights pi ON pi.project_id = cn.project_id
                                       AND pi.id = cn.insight_id
               WHERE lp.user_id = ?
               ORDER BY cn.project_id ASC, pi.day_number DESC""",
            (user_id,),
        ).fetchall()

    card_lookup_cache: dict[int, dict[str, dict]] = {}

    def _card_lookup(insight_id: int, insight_json: str) -> dict[str, dict]:
        if insight_id in card_lookup_cache:
            return card_lookup_cache[insight_id]
        try:
            parsed = json.loads(insight_json or "{}")
        except Exception:
            parsed = {}
        cards = (parsed.get("insights") or []) + (parsed.get("curiosity_insights") or [])
        lookup = {
            article_key_from_title(c.get("title") or ""): c
            for c in cards
            if isinstance(c, dict)
        }
        card_lookup_cache[insight_id] = lookup
        return lookup

    result = []
    for r in rows:
        card = _card_lookup(r["insight_id"], r["insight_json"]).get(r["card_id"], {})
        result.append({
            "id":            r["id"],
            "project_id":    r["project_id"],
            "insight_id":    r["insight_id"],
            "card_id":       r["card_id"],
            "content":       r["content"],
            "updated_at":    r["updated_at"],
            "article_title": card.get("title", ""),
            "category":      card.get("category"),
            "project_name":  r["project_name"],
            "day_number":    r["day_number"],
        })
    return result
