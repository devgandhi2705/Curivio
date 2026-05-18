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
