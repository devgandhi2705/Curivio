"""
Historical deep-research reader.

The deep-research generation workflow (Tavily multi-angle search -> ranking ->
Groq synthesis -> the /deep-research routes, the chat "Deep Research" toggle,
and the chat deep_research tool) has been removed — nothing can create new
rows in the deep_research table going forward. This module now exists only
to read back rows generated before removal, since other live features
(chat_context_service's per-turn context block, action_router_service's
research_report/explain_simply actions, timeline_service's deep_dive
milestones) depend on that historical data continuing to work.

Public API
----------
is_important_topic(topic)      — True if topic qualifies for autonomous research (still fed by exploration_trigger_service scoring)
get_stored_research(topic)     — retrieve cached result (None if missing/expired)
list_research_topics(limit)    — list stored topics newest-first
"""

import json
import logging
from datetime import datetime, timedelta, timezone

from ..utils.db import get_connection, get_preference

logger = logging.getLogger(__name__)

from ..config import (
    DEEP_RESEARCH_TTL_HOURS,
    DEEP_RESEARCH_LIKE_THRESHOLD      as IMPORTANCE_LIKE_THRESHOLD,
    DEEP_RESEARCH_SCORE_THRESHOLD     as IMPORTANCE_SCORE_THRESHOLD,
    DEEP_RESEARCH_RECOMMEND_THRESHOLD as IMPORTANCE_RECOMMEND_THRESHOLD,
)


def is_important_topic(topic: str) -> bool:
    """
    Return True if a topic qualifies for autonomous deep research.

    A topic is important when the user has:
    - explicitly liked it at least once, OR
    - built up a strong positive preference score, OR
    - been recommended it enough times to warrant deeper coverage.

    Thresholds are configurable via env vars (DEEP_RESEARCH_*_THRESHOLD).
    """
    pref = get_preference(topic)
    if pref is None:
        return False
    return (
        pref["times_liked"]      >= IMPORTANCE_LIKE_THRESHOLD      or
        pref["preference_score"] >= IMPORTANCE_SCORE_THRESHOLD     or
        pref["times_recommended"] >= IMPORTANCE_RECOMMEND_THRESHOLD
    )


def get_stored_research(topic: str) -> dict | None:
    """
    Return stored deep research for a topic if it exists and hasn't expired.

    Expiry is governed by DEEP_RESEARCH_TTL_HOURS (default 48 h).
    Returns None on a miss or if the stored entry is stale.
    """
    topic_key = _topic_key(topic)
    cutoff    = datetime.now(timezone.utc) - timedelta(hours=DEEP_RESEARCH_TTL_HOURS)

    with get_connection() as conn:
        row = conn.execute(
            "SELECT research_json, generated_at FROM deep_research WHERE topic_key = ?",
            (topic_key,),
        ).fetchone()

    if row is None:
        return None
    if _parse_ts(row["generated_at"]) < cutoff:
        return None

    return json.loads(row["research_json"])


def list_research_topics(limit: int = 20) -> list[dict]:
    """Return stored research entries newest-first (id, topic, generated_at)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, topic, generated_at FROM deep_research ORDER BY generated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def _topic_key(topic: str) -> str:
    return topic.strip().lower()


def _parse_ts(value: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Unrecognised timestamp format: {value!r}")
