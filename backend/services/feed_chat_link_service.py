"""
Feed → Chat relationship service.

Persists and retrieves the link between a feed article and a chat session,
enabling "Related Discussions" to surface on feed cards.

Public API
----------
create_link(session_id, project_id, insight_id, article_key,
            article_title, interaction_type)  -> dict
get_links_for_article(project_id, article_key) -> list[dict]
get_link_for_session(session_id)               -> dict | None
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

# Must stay in sync with feed_chat_links.interaction_type's CHECK constraint
# (schema.py MIGRATE_FEED_CHAT_LINKS_EXPLAIN_SIMPLY). "explain_simply" was
# missing here long after the migration added it, so every Explain Simply
# link was silently coerced to "ask_about" and mislabeled in the UI.
_INTERACTION_TYPES = {"ask_about", "explain_simply", "continue_research", "deep_research"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_link(
    session_id: str,
    project_id: str,
    article_key: str,
    article_title: str,
    interaction_type: str = "ask_about",
    insight_id: int | None = None,
) -> dict:
    """
    Persist a feed → chat relationship.

    Idempotent per (session_id, article_key): if a link already exists for
    this session it is returned unchanged rather than duplicated.
    """
    if interaction_type not in _INTERACTION_TYPES:
        interaction_type = "ask_about"

    from ..utils.db import get_connection
    now = _now()
    with get_connection() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO feed_chat_links
               (session_id, project_id, insight_id, article_key,
                article_title, interaction_type, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (session_id, project_id, insight_id, article_key,
             article_title, interaction_type, now),
        )
        row = conn.execute(
            """SELECT id, session_id, project_id, insight_id, article_key,
                      article_title, interaction_type, created_at
               FROM feed_chat_links
               WHERE session_id = ? AND article_key = ?
               LIMIT 1""",
            (session_id, article_key),
        ).fetchone()
    return dict(row) if row else {}


def get_links_for_article(project_id: str, article_key: str) -> list[dict]:
    """
    Return all chat sessions linked to a specific feed article, enriched
    with the session title so the UI can display it.

    Title resolution mirrors list_sessions_with_titles():
      1. chat_sessions.title  (AI-generated or manually renamed)
      2. first non-empty topic_hint from chat_messages  (topic sent with the first message)
      3. NULL  (falls back to "Untitled session" in the UI)
    """
    from ..utils.db import get_connection
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT fl.id, fl.session_id, fl.project_id, fl.insight_id,
                      fl.article_key, fl.article_title,
                      fl.interaction_type, fl.created_at,
                      COALESCE(cs.title, th.first_topic_hint) AS session_title
               FROM feed_chat_links fl
               LEFT JOIN chat_sessions cs
                      ON cs.session_id = fl.session_id
               LEFT JOIN (
                      SELECT session_id, MIN(topic_hint) AS first_topic_hint
                      FROM   chat_messages
                      WHERE  topic_hint IS NOT NULL AND topic_hint != ''
                      GROUP  BY session_id
               ) th ON th.session_id = fl.session_id
               WHERE fl.project_id = ? AND fl.article_key = ?
               ORDER BY fl.created_at DESC""",
            (project_id, article_key),
        ).fetchall()
    return [dict(r) for r in rows]


def get_link_for_session(session_id: str) -> dict | None:
    """Return the feed context that originated a chat session, if any."""
    from ..utils.db import get_connection
    with get_connection() as conn:
        row = conn.execute(
            """SELECT id, session_id, project_id, insight_id, article_key,
                      article_title, interaction_type, created_at
               FROM feed_chat_links
               WHERE session_id = ?
               LIMIT 1""",
            (session_id,),
        ).fetchone()
    return dict(row) if row else None
