"""
Context retrieval layer for the conversational chat system.

Pulls together user profile, research data, and session memory into a single
context dict that the prompt builder can consume.

Public API
----------
build_user_profile_context() -> dict
build_research_context(topic: str | None) -> dict
build_session_context(topic: str | None) -> dict
build_full_context(topic: str | None) -> dict
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def build_user_profile_context(user_id: str | None = None) -> dict:
    """
    Return a snapshot of what the agent knows about the user's learning profile.

    {
      "learning_stage":         str,           # "beginner" | "intermediate" | "advanced"
      "difficulty_preference":  str | None,
      "top_interests":          list[str],      # up to 5 topic names
      "suppressed_topics":      list[str],
    }

    Chat-R7a: user_id scopes every signal to this user only — None returns an
    empty/neutral profile rather than falling back to global data (no other
    caller of this function exists repo-wide, confirmed).
    """
    from .recommendation_service import (
        get_top_user_interests,
        get_suppressed_topics,
        get_overall_difficulty_preference,
        get_learning_stage,
    )

    if not user_id:
        return {
            "learning_stage":        "beginner",
            "difficulty_preference": None,
            "top_interests":         [],
            "suppressed_topics":     [],
        }

    try:
        top_interests    = [t["topic"] for t in get_top_user_interests(limit=5, user_id=user_id)]
        # get_suppressed_topics() already returns list[str] (topic names extracted
        # internally) — unlike get_top_user_interests()'s list[dict]. Re-indexing
        # with ["topic"] here raised on every turn with any suppressed topic
        # (TypeError: string indices must be integers), which the except below
        # silently caught and collapsed the WHOLE profile to defaults — including
        # top_interests, which does reach the system prompt.
        suppressed       = get_suppressed_topics(user_id=user_id)
        difficulty_pref  = get_overall_difficulty_preference(user_id=user_id)
        stage            = get_learning_stage(user_id=user_id)
    except Exception:
        logger.exception("build_user_profile_context failed; returning empty profile")
        top_interests   = []
        suppressed      = []
        difficulty_pref = None
        stage           = "beginner"

    return {
        "learning_stage":        stage,
        "difficulty_preference": difficulty_pref,
        "top_interests":         top_interests,
        "suppressed_topics":     suppressed,
    }


def build_research_context(topic: str | None) -> dict:
    """
    Return any stored research data for *topic*.

    {
      "topic":               str | None,
      "has_deep_research":   bool,
      "has_learning_path":   bool,
      "has_topic_expansion": bool,
      "has_github_repos":    bool,
      "deep_research":       dict | None,   # parsed JSON or None
      "learning_path":       dict | None,
      "topic_expansion":     dict | None,
      "github_repos":        list | None,
    }
    }
    """
    if not topic or not topic.strip():
        return {
            "topic": None,
            "has_deep_research": False,
            "has_learning_path": False,
            "has_topic_expansion": False,
            "has_github_repos": False,
            "deep_research": None,
            "learning_path": None,
            "topic_expansion": None,
            "github_repos": None,
        }

    from .deep_research_service import get_stored_research
    from .learning_path_service import get_stored_path
    from .topic_expansion_service import get_stored_expansion
    from .github_service import _get_stored_repos

    deep       = _safe_json(get_stored_research(topic))
    path       = _safe_json(get_stored_path(topic))
    expansion  = _safe_json(get_stored_expansion(topic))
    repos_raw  = _get_stored_repos(topic)
    repos      = _safe_json(repos_raw) if repos_raw else None

    return {
        "topic":               topic,
        "has_deep_research":   deep is not None,
        "has_learning_path":   path is not None,
        "has_topic_expansion": expansion is not None,
        "has_github_repos":    repos is not None,
        "deep_research":       deep,
        "learning_path":       path,
        "topic_expansion":     expansion,
        "github_repos":        repos,
    }


def build_session_context(topic: str | None) -> dict:
    """
    Return session-memory data for *topic* (always a dict, never None).

    {
      "topic":               str | None,
      "times_explored":      int,
      "has_deep_research":   bool,
      "has_learning_path":   bool,
      "has_topic_expansion": bool,
      "has_github_repos":    bool,
      "last_activity_at":    str | None,
      "recommended_next":    list[str],
    }
    """
    if not topic or not topic.strip():
        return {
            "topic": None,
            "times_explored": 0,
            "has_deep_research": False,
            "has_learning_path": False,
            "has_topic_expansion": False,
            "has_github_repos": False,
            "last_activity_at": None,
            "recommended_next": [],
        }

    from .session_memory_service import get_research_context
    try:
        ctx = get_research_context(topic)
        return {k: ctx.get(k) for k in (
            "topic", "times_explored",
            "has_deep_research", "has_learning_path",
            "has_topic_expansion", "has_github_repos",
            "last_activity_at", "recommended_next",
        )}
    except Exception:
        logger.exception("build_session_context failed for %r", topic)
        return {
            "topic": topic,
            "times_explored": 0,
            "has_deep_research": False,
            "has_learning_path": False,
            "has_topic_expansion": False,
            "has_github_repos": False,
            "last_activity_at": None,
            "recommended_next": [],
        }


def build_full_context(topic: str | None, user_id: str | None = None) -> dict:
    """
    Combine user profile + research + session context into one dict.

    {
      "user_profile":    {...},
      "research":        {...},
      "session":         {...},
    }

    Chat-R7a: user_id scopes user_profile only (the personal-signal leak).
    research/session stay topic-keyed and unscoped by design — a shared
    "has this topic been researched" cache, same category as deep_research/
    learning_paths content, not the personalization leak this fix targets.
    """
    return {
        "user_profile": build_user_profile_context(user_id),
        "research":     build_research_context(topic),
        "session":      build_session_context(topic),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _safe_json(value) -> dict | list | None:
    """Parse a JSON string to Python object; return None on any failure."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return None
