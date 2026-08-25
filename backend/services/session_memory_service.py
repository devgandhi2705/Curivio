"""
Research-session memory tracking for the AI learning agent.

Maintains an append-only log of all research activities performed on topics,
enabling long-term learning continuity and redundancy avoidance.

Tracked activities
------------------
  learning_path     — structured learning path generation
  topic_expansion   — prerequisite / related-topic tree
  github_repos      — GitHub repository discovery

Historical note: "deep_research" rows also exist from before the deep-research
feature was removed — no longer a writable activity type, but get_topic_memory/
get_research_context still surface has_deep_research from those old rows.

Public API
----------
record_activity(topic, activity, user_id) -> int
    Append one activity event for *topic* and return the new row ID.

get_topic_memory(topic) -> dict | None
    Full activity log for *topic*, or None if never explored.

list_explored_topics(limit) -> list[dict]
    All topics that have been explored, most-recently-active first.

is_activity_recorded(topic, activity) -> bool
    Return True if *activity* has ever been performed for *topic*.

get_research_context(topic) -> dict
    Derived context dict summarising what is known about *topic*,
    suitable for feeding into recommendation logic.  Always returns a dict.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..utils.db import get_connection

ACTIVITY_TYPES: frozenset[str] = frozenset(
    {"learning_path", "topic_expansion", "github_repos"}
)


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def record_activity(topic: str, activity: str, user_id: str) -> int:
    """
    Append an activity event for *topic* and return the new row ID.
    Raises ValueError for an empty topic, unknown activity type, or missing user_id.

    Chat-R7a: user_id is required and stored on the row — this is the write
    side of build_exploration_breadth's personal-signal query (COUNT DISTINCT
    topic_key WHERE user_id=?). Topic-keyed lookups elsewhere in this module
    (get_topic_memory, is_activity_recorded, get_research_context) stay
    unscoped by design — a shared "has this topic been researched" cache,
    not the personalization leak this fix targets.
    """
    topic = (topic or "").strip()
    if not topic:
        raise ValueError("topic must not be empty")
    if activity not in ACTIVITY_TYPES:
        raise ValueError(
            f"unknown activity {activity!r}; must be one of {sorted(ACTIVITY_TYPES)}"
        )
    if not user_id:
        raise ValueError("user_id must not be empty")

    topic_key = _topic_key(topic)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO research_sessions (topic, topic_key, activity, recorded_at, user_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (topic, topic_key, activity, now, user_id),
        )
        return cur.lastrowid


def get_topic_memory(topic: str) -> dict | None:
    """
    Return the full activity log for *topic*, or None if never explored.

    Result shape
    ------------
    {
      "topic":               str,
      "topic_key":           str,
      "activities":          [{"activity": str, "recorded_at": str}, ...],  # newest first
      "has_deep_research":   bool,
      "has_learning_path":   bool,
      "has_topic_expansion": bool,
      "has_github_repos":    bool,
      "times_explored":      int,
      "first_explored_at":   str | None,
      "last_activity_at":    str | None,
    }
    """
    topic_key = _topic_key(topic)

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT activity, recorded_at FROM research_sessions "
            "WHERE topic_key = ? ORDER BY recorded_at DESC",
            (topic_key,),
        ).fetchall()

    if not rows:
        return None

    activities = [{"activity": r["activity"], "recorded_at": r["recorded_at"]} for r in rows]
    done = {r["activity"] for r in rows}

    return {
        "topic":               topic,
        "topic_key":           topic_key,
        "activities":          activities,
        "has_deep_research":   "deep_research"   in done,
        "has_learning_path":   "learning_path"   in done,
        "has_topic_expansion": "topic_expansion" in done,
        "has_github_repos":    "github_repos"    in done,
        "times_explored":      len(activities),
        "first_explored_at":   activities[-1]["recorded_at"],
        "last_activity_at":    activities[0]["recorded_at"],
    }


def list_explored_topics(limit: int = 50) -> list[dict]:
    """
    Return topics that have been explored, most-recently-active first.

    Each entry
    ----------
    {
      "topic":            str,
      "last_activity_at": str,
      "activity_count":   int,   # total events (including repeats)
      "activities_done":  list[str],  # unique activity types, sorted
    }
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT   topic,
                     MAX(recorded_at)               AS last_activity_at,
                     COUNT(*)                        AS activity_count,
                     GROUP_CONCAT(DISTINCT activity) AS activities_done
            FROM     research_sessions
            GROUP BY topic_key
            ORDER BY last_activity_at DESC
            LIMIT    ?
            """,
            (limit,),
        ).fetchall()

    return [
        {
            "topic":            r["topic"],
            "last_activity_at": r["last_activity_at"],
            "activity_count":   r["activity_count"],
            "activities_done":  sorted(r["activities_done"].split(","))
                                if r["activities_done"] else [],
        }
        for r in rows
    ]


def is_activity_recorded(topic: str, activity: str) -> bool:
    """Return True if *activity* has ever been performed for *topic*."""
    topic_key = _topic_key(topic)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM research_sessions "
            "WHERE topic_key = ? AND activity = ? LIMIT 1",
            (topic_key, activity),
        ).fetchone()
    return row is not None


def get_research_context(topic: str) -> dict:
    """
    Return a context summary for *topic*, always as a dict (never None).
    Includes which activities remain to be done as ``recommended_next``.

    {
      "topic":               str,
      "times_explored":      int,
      "has_deep_research":   bool,
      "has_learning_path":   bool,
      "has_topic_expansion": bool,
      "has_github_repos":    bool,
      "first_explored_at":   str | None,
      "last_activity_at":    str | None,
      "recommended_next":    list[str],
    }
    """
    memory = get_topic_memory(topic)

    if memory is None:
        return {
            "topic":               topic,
            "times_explored":      0,
            "has_deep_research":   False,
            "has_learning_path":   False,
            "has_topic_expansion": False,
            "has_github_repos":    False,
            "first_explored_at":   None,
            "last_activity_at":    None,
            "recommended_next":    sorted(ACTIVITY_TYPES),
        }

    done = {a["activity"] for a in memory["activities"]}
    return {
        "topic":               memory["topic"],
        "times_explored":      memory["times_explored"],
        "has_deep_research":   memory["has_deep_research"],
        "has_learning_path":   memory["has_learning_path"],
        "has_topic_expansion": memory["has_topic_expansion"],
        "has_github_repos":    memory["has_github_repos"],
        "first_explored_at":   memory["first_explored_at"],
        "last_activity_at":    memory["last_activity_at"],
        "recommended_next":    sorted(ACTIVITY_TYPES - done),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _topic_key(topic: str) -> str:
    return topic.strip().lower()
