"""
Feed-entry persistent anchor — Chat-3.

Resolves project_id + specific day (project_insights.id) via feed_chat_links,
completely independent of feed_context/shared_learning_context (the latter is
per-request only, gated on FeedContext.project_id). This anchor is resolved
fresh every turn from session_id alone, so it persists across the whole
conversation without feed_context being re-sent, and without being subject to
the 6-turn sliding history window — it lives in the system prompt, not history.

Content: the project's intent_profile.intent_summary (already a compact 1-2
sentence editorial brief — no separate formatter needed) + that exact day's
full project_insights package rendered via export_service.insight_to_markdown()
(reused verbatim). Capped via truncate_at_sentence as a safety net — real
sizes (~320 + ~4,000-4,500 tokens for one day) sit well under the cap.

Public API
----------
get_anchor_for_session(session_id) -> str    "" if session has no feed link
"""
from __future__ import annotations

import json
import logging

from ..utils.db import get_connection
from ..utils.text import truncate_at_sentence

logger = logging.getLogger(__name__)

_MAX_ANCHOR_CHARS = 20_000  # safety net — real single-day packages sit well under this


def _resolve_project_day(session_id: str) -> tuple[str, int] | None:
    """Most recent feed_chat_links row for this session -> (project_id, insight_id)."""
    with get_connection() as conn:
        row = conn.execute(
            """SELECT project_id, insight_id FROM feed_chat_links
               WHERE session_id = ? AND insight_id IS NOT NULL
               ORDER BY created_at DESC LIMIT 1""",
            (session_id,),
        ).fetchone()
    if not row:
        return None
    return row["project_id"], row["insight_id"]


def _project_summary(project_id: str) -> str:
    """Compact project summary from intent_profile's existing intent_summary field."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT name, intent_profile FROM learning_projects WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    if not row:
        return ""
    name = row["name"] or ""
    try:
        profile = json.loads(row["intent_profile"]) if row["intent_profile"] else {}
    except Exception:
        profile = {}
    summary = (profile.get("intent_summary") or "").strip()
    if not summary:
        return f"PROJECT: {name}" if name else ""
    return f"PROJECT: {name}\n{summary}" if name else summary


def get_anchor_for_session(session_id: str) -> str:
    """
    Build the Feed-entry anchor for this session, or "" if the session has no
    feed_chat_links row (not a Feed-linked conversation). Non-fatal — returns
    "" on any error rather than raising.
    """
    if not session_id:
        return ""
    try:
        resolved = _resolve_project_day(session_id)
        if not resolved:
            return ""
        project_id, insight_id = resolved

        from .export_service import insight_to_markdown
        package_md = insight_to_markdown(project_id, insight_id)
        if not package_md:
            return ""

        summary = _project_summary(project_id)

        parts = ["FEED ENTRY ANCHOR — background from the project this conversation started from:"]
        if summary:
            parts.append(summary)
        parts.append(package_md)
        anchor = "\n\n".join(parts)

        return truncate_at_sentence(anchor, _MAX_ANCHOR_CHARS)
    except Exception:
        logger.exception(
            "feed_entry_anchor_service: failed for session %r (non-fatal)", session_id
        )
        return ""
