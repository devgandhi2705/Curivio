"""
Research-session continuity for the AI learning companion.

Persists what has been explained to the user and what recommendations have been
given across all sessions, then surfaces this as cross-session context that the
prompt builder injects before each AI response.

Two lightweight SQLite tables:
  concept_memory         — concepts explained per topic (with frequency counts)
  prior_recommendations  — follow-up topics recommended to the user per session

No LLM calls.  All writes are non-blocking fire-and-forget (errors logged only).

Public API
----------
record_concepts(topic, concepts, session_id=None)
record_recommendations(session_id, topic, recommendations)
get_continuity_context(topic, session_id=None) -> dict
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..utils.db import get_connection

logger = logging.getLogger(__name__)

# Max items surfaced in the prompt section to keep token count bounded.
_MAX_CONCEPTS_IN_PROMPT       = 12
_MAX_PRIOR_RECS_IN_PROMPT     = 8


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def record_concepts(
    topic: str,
    concepts: list[str],
    session_id: str | None = None,
) -> None:
    """
    Upsert each concept into concept_memory for *topic*.

    On conflict (same concept_key) increment times_explained and update
    last_explained_at.  Silently ignores empty inputs and DB errors.
    """
    if not topic or not concepts:
        return

    topic_key = _key(topic)
    now       = _now()

    try:
        with get_connection() as conn:
            for concept in concepts:
                if not concept or not concept.strip():
                    continue
                conn.execute(
                    """
                    INSERT INTO concept_memory
                        (concept, concept_key, topic, topic_key, session_id,
                         times_explained, first_explained_at, last_explained_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                    ON CONFLICT(concept_key) DO UPDATE SET
                        times_explained   = times_explained + 1,
                        last_explained_at = excluded.last_explained_at
                    """,
                    (
                        concept.strip(), _key(concept),
                        topic.strip(),   topic_key,
                        session_id,
                        now, now,
                    ),
                )
    except Exception:
        logger.exception("continuity_service: record_concepts failed for topic=%r", topic)


def record_recommendations(
    session_id: str,
    topic: str,
    recommendations: dict,
) -> None:
    """
    Persist the follow-up recommendations that were shown to the user.

    *recommendations* is the dict produced by follow_up_service.get_recommendations:
      {"next_topics": [...], "prerequisites": [...], "advanced_topics": [...]}

    Already-stored duplicates (same topic_key × recommended_key) are ignored
    via INSERT OR IGNORE to avoid bloating the table.
    """
    if not session_id or not topic or not recommendations:
        return
    if recommendations.get("source") != "stored":
        return  # only persist recommendations backed by real data

    topic_key = _key(topic)
    now       = _now()

    _REC_TYPE_MAP = {
        "next_topics":     "next_topic",
        "prerequisites":   "prerequisite",
        "advanced_topics": "advanced",
    }

    try:
        with get_connection() as conn:
            for field, rec_type in _REC_TYPE_MAP.items():
                for item in recommendations.get(field, []):
                    recommended = item.get("topic", "")
                    if not recommended:
                        continue
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO prior_recommendations
                            (session_id, topic, topic_key, rec_type,
                             recommended, recommended_key, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            session_id,
                            topic.strip(), topic_key,
                            rec_type,
                            recommended.strip(), _key(recommended),
                            now,
                        ),
                    )
    except Exception:
        logger.exception(
            "continuity_service: record_recommendations failed for topic=%r", topic
        )


def get_continuity_context(
    topic: str,
    session_id: str | None = None,
) -> dict:
    """
    Return cross-session learning history for *topic*.

    Return shape
    ------------
    {
      "topic":                str,
      "explained_concepts":   list[str],   # most-explained first
      "prior_recommendations": list[str],  # distinct recommended topics, recent first
      "cross_session_turns":  int,         # total chat turns that touched this topic
      "sessions_count":       int,         # distinct sessions
    }
    """
    empty = {
        "topic":                 topic,
        "explained_concepts":    [],
        "prior_recommendations": [],
        "cross_session_turns":   0,
        "sessions_count":        0,
    }

    if not topic or not topic.strip():
        return empty

    topic_key = _key(topic)

    try:
        with get_connection() as conn:
            concept_rows = conn.execute(
                """
                SELECT concept, times_explained
                FROM   concept_memory
                WHERE  topic_key = ?
                ORDER  BY times_explained DESC, last_explained_at DESC
                LIMIT  ?
                """,
                (topic_key, _MAX_CONCEPTS_IN_PROMPT),
            ).fetchall()

            rec_rows = conn.execute(
                """
                SELECT DISTINCT recommended
                FROM   prior_recommendations
                WHERE  topic_key = ?
                ORDER  BY created_at DESC
                LIMIT  ?
                """,
                (topic_key, _MAX_PRIOR_RECS_IN_PROMPT),
            ).fetchall()

            turn_row = conn.execute(
                """
                SELECT COUNT(*)              AS turns,
                       COUNT(DISTINCT session_id) AS sessions
                FROM   chat_messages
                WHERE  topic_hint = ? AND role = 'user'
                """,
                (topic.strip(),),
            ).fetchone()

    except Exception:
        logger.exception(
            "continuity_service: get_continuity_context failed for topic=%r", topic
        )
        return empty

    explained   = [r["concept"] for r in concept_rows]
    prior_recs  = [r["recommended"] for r in rec_rows]
    turns       = turn_row["turns"]    if turn_row else 0
    sessions    = turn_row["sessions"] if turn_row else 0

    if not explained and not prior_recs and turns == 0:
        return empty

    return {
        "topic":                 topic.strip(),
        "explained_concepts":    explained,
        "prior_recommendations": prior_recs,
        "cross_session_turns":   turns,
        "sessions_count":        sessions,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _key(value: str) -> str:
    return value.strip().lower()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
