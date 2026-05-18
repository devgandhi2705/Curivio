"""
Global search service.

Searches across three data sources in one call:
  - project insight cards   (project_insights.insight_json)
  - bookmarks               (bookmarks table)
  - chat messages           (chat_messages + chat_sessions)

Each section returns at most `limit_per_section` results.
Query must be ≥ 2 characters; matching is case-insensitive LIKE.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

_MIN_LEN    = 2
_DB_PREFETCH = 40   # rows fetched from DB before card-level filtering


def global_search(query: str, limit_per_section: int = 5, user_id: str | None = None) -> dict:
    q = (query or "").strip()
    _empty = {
        "query": q,
        "total": 0,
        "results": {"cards": [], "bookmarks": [], "chats": []},
    }
    if len(q) < _MIN_LEN:
        return _empty

    try:
        cards     = _search_cards(q,     limit_per_section, user_id)
        bookmarks = _search_bookmarks(q, limit_per_section, user_id)
        chats     = _search_chats(q,     limit_per_section, user_id)
    except Exception:
        logger.exception("[search_service] global_search failed for %r", q)
        return _empty

    return {
        "query":  q,
        "total":  len(cards) + len(bookmarks) + len(chats),
        "results": {"cards": cards, "bookmarks": bookmarks, "chats": chats},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Section helpers
# ─────────────────────────────────────────────────────────────────────────────

def _search_cards(query: str, limit: int, user_id: str | None = None) -> list[dict]:
    """Search inside project_insights.insight_json at the card level."""
    from ..utils.db import get_connection
    like = f"%{query}%"
    if user_id:
        sql = """SELECT pi.id          AS insight_id,
                        pi.project_id,
                        pi.day_number,
                        pi.generated_at,
                        pi.insight_json,
                        lp.name        AS project_name,
                        lp.color       AS project_color
                 FROM   project_insights pi
                 JOIN   learning_projects lp ON lp.project_id = pi.project_id
                 WHERE  pi.insight_json LIKE ? COLLATE NOCASE
                   AND  lp.user_id = ?
                 ORDER  BY pi.generated_at DESC
                 LIMIT  ?"""
        params = (like, user_id, _DB_PREFETCH)
    else:
        sql = """SELECT pi.id          AS insight_id,
                        pi.project_id,
                        pi.day_number,
                        pi.generated_at,
                        pi.insight_json,
                        lp.name        AS project_name,
                        lp.color       AS project_color
                 FROM   project_insights pi
                 JOIN   learning_projects lp ON lp.project_id = pi.project_id
                 WHERE  pi.insight_json LIKE ? COLLATE NOCASE
                 ORDER  BY pi.generated_at DESC
                 LIMIT  ?"""
        params = (like, _DB_PREFETCH)
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()

    ql      = query.lower()
    results: list[dict] = []

    for row in rows:
        try:
            pkg = json.loads(row["insight_json"])
        except Exception:
            continue

        all_cards = (pkg.get("insights") or []) + (pkg.get("curiosity_insights") or [])
        for card in all_cards:
            title   = card.get("title", "")
            summary = card.get("summary", "")
            expl    = card.get("educational_explanation", "")
            if ql not in title.lower() and ql not in summary.lower() and ql not in expl.lower():
                continue

            results.append({
                "type":         "card",
                "project_id":   row["project_id"],
                "project_name": row["project_name"],
                "project_color": row["project_color"] or "blue",
                "insight_id":   row["insight_id"],
                "day_number":   row["day_number"],
                "generated_at": row["generated_at"],
                "card_id":      card.get("id", ""),
                "card_title":   title,
                "card_summary": (summary or expl)[:180],
                "content_type": card.get("content_type", "news"),
                "category":     card.get("category", ""),
            })
            if len(results) >= limit:
                return results

    return results


def _search_bookmarks(query: str, limit: int, user_id: str | None = None) -> list[dict]:
    from ..utils.db import get_connection
    like = f"%{query}%"
    if user_id:
        sql = """SELECT b.bookmark_id, b.title, b.summary, b.collection_id,
                        b.source_url, b.project_name, b.content_type, b.saved_at, b.tags
                 FROM   bookmarks b
                 JOIN   bookmark_collections bc ON bc.collection_id = b.collection_id
                 WHERE  (b.title   LIKE ? COLLATE NOCASE
                    OR   b.summary LIKE ? COLLATE NOCASE
                    OR   b.tags    LIKE ? COLLATE NOCASE)
                   AND  bc.user_id = ?
                 ORDER  BY b.saved_at DESC
                 LIMIT  ?"""
        params = (like, like, like, user_id, limit)
    else:
        sql = """SELECT bookmark_id, title, summary, collection_id,
                        source_url, project_name, content_type, saved_at, tags
                 FROM   bookmarks
                 WHERE  title   LIKE ? COLLATE NOCASE
                    OR  summary LIKE ? COLLATE NOCASE
                    OR  tags    LIKE ? COLLATE NOCASE
                 ORDER  BY saved_at DESC
                 LIMIT  ?"""
        params = (like, like, like, limit)
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()

    return [
        {
            "type":         "bookmark",
            "bookmark_id":  r["bookmark_id"],
            "title":        r["title"],
            "card_summary": (r["summary"] or "")[:180],
            "collection_id": r["collection_id"],
            "source_url":   r["source_url"] or "",
            "project_name": r["project_name"] or "",
            "content_type": r["content_type"] or "feed_article",
            "saved_at":     r["saved_at"],
        }
        for r in rows
    ]


def _search_chats(query: str, limit: int, user_id: str | None = None) -> list[dict]:
    from ..utils.db import get_connection
    like = f"%{query}%"
    if user_id:
        sql = """SELECT m.session_id, m.role, m.content, m.created_at,
                        s.title AS session_title
                 FROM   chat_messages  m
                 LEFT   JOIN chat_sessions s ON s.session_id = m.session_id
                 WHERE  m.content LIKE ? COLLATE NOCASE
                   AND  s.user_id = ?
                 ORDER  BY m.created_at DESC
                 LIMIT  ?"""
        params = (like, user_id, limit)
    else:
        sql = """SELECT m.session_id, m.role, m.content, m.created_at,
                        s.title AS session_title
                 FROM   chat_messages  m
                 LEFT   JOIN chat_sessions s ON s.session_id = m.session_id
                 WHERE  m.content LIKE ? COLLATE NOCASE
                 ORDER  BY m.created_at DESC
                 LIMIT  ?"""
        params = (like, limit)
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()

    return [
        {
            "type":             "chat",
            "session_id":       r["session_id"],
            "session_title":    r["session_title"] or "Untitled session",
            "message_snippet":  (r["content"] or "")[:200],
            "role":             r["role"],
            "created_at":       r["created_at"],
        }
        for r in rows
    ]
