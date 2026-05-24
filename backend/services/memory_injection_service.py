"""
Lightweight conversation memory injection for the AI chat system.

Pulls three memory layers from SQLite and merges them into a single context
dict that the prompt builder consumes:

  conversation_memory  — topics discussed and recent turns for this session
  exploration_breadth  — every topic the user has ever explored in this app
  preference_snapshot  — liked / disliked topics, difficulty signals

No vector databases are used.  All retrieval is plain SQL.

Public API
----------
build_conversation_memory(session_id, limit=10) -> dict
build_exploration_breadth(limit=20) -> dict
build_preference_snapshot() -> dict
inject_memory(session_id, topic_hint=None) -> dict
"""

from __future__ import annotations

import logging
from collections import Counter

logger = logging.getLogger(__name__)

# How many recent user messages to surface verbatim in the prompt.
_RECENT_USER_MSG_COUNT = 3

# Minimum preference_score to be counted as "liked".
_LIKED_THRESHOLD: float = 0.0

# Maximum preference_score to be counted as "disliked".
_DISLIKED_THRESHOLD: float = -0.25

# Topics listed in the breadth section.
_BREADTH_TOPIC_LIMIT = 12


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def build_conversation_memory(session_id: str, limit: int = 20) -> dict:
    """
    Summarise recent chat activity for *session_id*.

    Return shape
    ------------
    {
      "session_id":        str,
      "message_count":     int,      # total messages in this session
      "session_turns":     int,      # complete user+assistant pairs
      "topics_discussed":  list[str],# unique topic_hints, most-frequent first
      "last_user_messages": list[str],# last _RECENT_USER_MSG_COUNT user texts
    }
    """
    empty = {
        "session_id":         session_id,
        "message_count":      0,
        "session_turns":      0,
        "topics_discussed":   [],
        "last_user_messages": [],
    }
    if not session_id or not session_id.strip():
        return empty

    try:
        from ..utils.db import get_connection
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT role, content, topic_hint
                FROM   chat_messages
                WHERE  session_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT  ?
                """,
                (session_id, limit),
            ).fetchall()
    except Exception:
        logger.exception("build_conversation_memory DB error for session %r", session_id)
        return empty

    if not rows:
        return empty

    message_count = len(rows)
    topic_counts  = Counter(r["topic_hint"] for r in rows if r["topic_hint"])
    topics_discussed = [t for t, _ in topic_counts.most_common()]

    last_user_messages = [
        r["content"]
        for r in rows
        if r["role"] == "user"
    ][:_RECENT_USER_MSG_COUNT]

    # rows are in DESC order — count how many user messages there are for turns
    user_count = sum(1 for r in rows if r["role"] == "user")
    session_turns = user_count  # each user message is one turn

    return {
        "session_id":         session_id,
        "message_count":      message_count,
        "session_turns":      session_turns,
        "topics_discussed":   topics_discussed,
        "last_user_messages": last_user_messages,
    }


def build_exploration_breadth(limit: int = _BREADTH_TOPIC_LIMIT) -> dict:
    """
    Return all topics the user has explored in this app, most-recent first.

    Return shape
    ------------
    {
      "total_explored":    int,
      "all_topics":        list[str],              # up to *limit* topic names
      "recently_explored": list[str],              # last 5
      "deep_dived_topics": list[str],              # topics with deep_research
    }
    """
    empty = {
        "total_explored":    0,
        "all_topics":        [],
        "recently_explored": [],
        "deep_dived_topics": [],
    }

    try:
        from ..utils.db import get_connection
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT   topic,
                         MAX(recorded_at)                AS last_activity_at,
                         GROUP_CONCAT(DISTINCT activity) AS activities_done
                FROM     research_sessions
                GROUP BY topic_key
                ORDER BY last_activity_at DESC
                LIMIT    ?
                """,
                (limit,),
            ).fetchall()

            total_row = conn.execute(
                "SELECT COUNT(DISTINCT topic_key) AS n FROM research_sessions"
            ).fetchone()
    except Exception:
        logger.exception("build_exploration_breadth DB error")
        return empty

    if not rows:
        return empty

    total_explored    = total_row["n"] if total_row else len(rows)
    all_topics        = [r["topic"] for r in rows]
    recently_explored = all_topics[:5]
    deep_dived_topics = [
        r["topic"] for r in rows
        if r["activities_done"] and "deep_research" in r["activities_done"]
    ]

    return {
        "total_explored":    total_explored,
        "all_topics":        all_topics,
        "recently_explored": recently_explored,
        "deep_dived_topics": deep_dived_topics,
    }


def build_preference_snapshot() -> dict:
    """
    Return liked / disliked topics and overall difficulty signals.

    Return shape
    ------------
    {
      "liked_topics":    list[str],   # preference_score > 0, sorted by score
      "disliked_topics": list[str],   # preference_score <= DISLIKED_THRESHOLD
      "difficulty_preference": str | None,
      "engagement_level": str,        # "high" | "moderate" | "low" | "new"
    }
    """
    empty = {
        "liked_topics":          [],
        "disliked_topics":       [],
        "difficulty_preference": None,
        "engagement_level":      "new",
    }

    try:
        from ..utils.db import get_connection
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT topic, preference_score, times_liked, times_disliked,
                       difficulty_preference
                FROM   user_preferences
                ORDER  BY preference_score DESC
                LIMIT  40
                """,
            ).fetchall()
    except Exception:
        logger.exception("build_preference_snapshot DB error")
        return empty

    if not rows:
        return empty

    liked    = [r["topic"] for r in rows if r["preference_score"] >  _LIKED_THRESHOLD][:8]
    disliked = [r["topic"] for r in rows if r["preference_score"] <= _DISLIKED_THRESHOLD]

    # Difficulty preference: use the most common non-null value
    difficulty_vals = [r["difficulty_preference"] for r in rows if r["difficulty_preference"]]
    difficulty_pref = Counter(difficulty_vals).most_common(1)[0][0] if difficulty_vals else None

    total_likes    = sum(r["times_liked"]    for r in rows)
    total_dislikes = sum(r["times_disliked"] for r in rows)
    total_signals  = total_likes + total_dislikes

    if total_signals == 0:
        engagement_level = "new"
    elif total_likes / max(total_signals, 1) >= 0.7:
        engagement_level = "high"
    elif total_likes / max(total_signals, 1) >= 0.4:
        engagement_level = "moderate"
    else:
        engagement_level = "low"

    return {
        "liked_topics":          liked,
        "disliked_topics":       disliked,
        "difficulty_preference": difficulty_pref,
        "engagement_level":      engagement_level,
    }


def inject_memory(session_id: str, topic_hint: str | None = None) -> dict:
    """
    Build a memory-injected context dict for one chat turn.

    Combines:
      base context     — user profile + per-topic research + session memory
      conv memory      — this session's discussion history
      breadth          — all topics explored across all sessions
      pref snapshot    — liked/disliked topics and difficulty
      learner profile  — inferred level + explanation-style directive

    This is the primary entry-point used by chat_service.chat().

    Return shape
    ------------
    {
      "user_profile":       {...},   # from build_full_context
      "research":           {...},
      "session":            {...},
      "conversation_memory": {...},  # from build_conversation_memory
      "exploration_breadth": {...},  # from build_exploration_breadth
      "preference_snapshot": {...},  # from build_preference_snapshot
      "learner_profile":    {...},   # from build_learner_profile
    }
    """
    from .chat_context_service import build_full_context
    from .adaptive_explanation_service import build_learner_profile
    from .continuity_service import get_continuity_context
    from .conversation_state_service import get_state as get_knowledge_state

    base       = build_full_context(topic_hint)
    conv       = build_conversation_memory(session_id)
    breadth    = build_exploration_breadth()
    prefs      = build_preference_snapshot()
    learner    = build_learner_profile(session_id)
    continuity = get_continuity_context(topic_hint, session_id) if topic_hint else {}
    knowledge  = get_knowledge_state(session_id)

    return {
        **base,
        "conversation_memory":       conv,
        "exploration_breadth":       breadth,
        "preference_snapshot":       prefs,
        "learner_profile":           learner,
        "continuity":                continuity,
        "conversation_knowledge":    knowledge,
    }
