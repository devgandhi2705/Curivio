"""
Intelligent follow-up learning recommendations for the AI research companion.

After each chat response, surfaces contextual next steps drawn from stored
topic expansion data (prerequisites, related topics, advanced follow-ups).
No AI calls are made — all recommendations are derived from cached SQLite data.

Prioritisation rules
--------------------
  beginner      → prerequisites first (up to 2), then next_topics (up to 2),
                   advanced_topics suppressed
  intermediate  → next_topics (up to 3), prerequisites (up to 1), advanced (up to 2)
  advanced      → advanced_topics first (up to 3), next_topics (up to 2),
                   prerequisites suppressed

Already-explored topics are always filtered out.

Public API
----------
get_recommendations(topic, explored_topics, learner_level) -> dict
"""

from __future__ import annotations

import logging
from typing import Sequence

logger = logging.getLogger(__name__)

# Maximum items returned per recommendation category.
_MAX_PER_CATEGORY = 3


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def get_recommendations(
    topic: str,
    explored_topics: Sequence[str] | None = None,
    learner_level: str = "intermediate",
) -> dict:
    """
    Return contextual learning recommendations for *topic*.

    Parameters
    ----------
    topic           : The topic the user just asked about.
    explored_topics : Topics the user has already explored (filtered out).
    learner_level   : "beginner" | "intermediate" | "advanced"

    Return shape
    ------------
    {
      "based_on_topic":  str | None,
      "source":          "stored" | "empty",
      "next_topics":     [{"topic": str, "reason": str}, ...],
      "prerequisites":   [{"topic": str, "reason": str}, ...],
      "advanced_topics": [{"topic": str, "reason": str}, ...],
    }
    """
    empty = _empty_result(topic)

    if not topic or not topic.strip():
        return empty

    topic = topic.strip()
    explored_set = _normalise_set(explored_topics or [])

    expansion = _load_expansion(topic)
    if expansion is None:
        return empty

    related   = expansion.get("related_topics",    [])
    prereqs   = expansion.get("prerequisites",      [])
    advanced  = expansion.get("advanced_follow_ups", [])

    # Filter already-explored topics
    related  = _filter_explored(related,  explored_set)
    prereqs  = _filter_explored(prereqs,  explored_set)
    advanced = _filter_explored(advanced, explored_set)

    # Apply learner-level caps and suppression
    next_limit, prereq_limit, adv_limit = _limits_for_level(learner_level)

    next_topics     = _build_items(related[:next_limit],   "next",     topic)
    prerequisites   = _build_items(prereqs[:prereq_limit], "prereq",   topic)
    advanced_topics = _build_items(advanced[:adv_limit],   "advanced", topic)

    if not next_topics and not prerequisites and not advanced_topics:
        return empty

    return {
        "based_on_topic":  topic,
        "source":          "stored",
        "next_topics":     next_topics,
        "prerequisites":   prerequisites,
        "advanced_topics": advanced_topics,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _load_expansion(topic: str) -> dict | None:
    """Return stored topic expansion or None (no DB write, cache-read only)."""
    try:
        from .topic_expansion_service import get_stored_expansion
        return get_stored_expansion(topic)
    except Exception:
        logger.exception("follow_up_service: failed to load expansion for %r", topic)
        return None


def _filter_explored(items: list, explored_set: set[str]) -> list:
    """Remove items whose normalised names are in *explored_set*."""
    return [t for t in items if isinstance(t, str) and _normalise(t) not in explored_set]


def _normalise(topic: str) -> str:
    return topic.strip().lower()


def _normalise_set(topics: Sequence[str]) -> set[str]:
    return {_normalise(t) for t in topics if isinstance(t, str)}


def _limits_for_level(level: str) -> tuple[int, int, int]:
    """Return (next_limit, prereq_limit, adv_limit) for a learner level."""
    if level == "beginner":
        return 2, 2, 0
    if level == "advanced":
        return 2, 0, 3
    # intermediate (default)
    return 3, 1, 2


_REASON_TEMPLATES: dict[str, list[str]] = {
    "next": [
        "What specifically does {item} change about how {topic} works?",
        "How does {item} extend or complicate the mechanism behind {topic}?",
        "Where does {item} fit in the causal chain that {topic} sits in?",
    ],
    "prereq": [
        "Without {item}, what part of {topic} stops making sense?",
        "How does {item} constrain the space of possible outcomes in {topic}?",
        "{item} is the structural foundation — which part of {topic} depends on it most?",
    ],
    "advanced": [
        "What does {item} reveal about {topic} that the standard framing misses?",
        "At the {item} level, which assumption behind {topic} starts to break?",
        "How does {item} change the strategic calculus of {topic}?",
    ],
}

# Simple rotation index per reason type, shared across calls in one process
_reason_rotation: dict[str, int] = {}


def _build_items(topics: list[str], category: str, base_topic: str) -> list[dict]:
    templates = _REASON_TEMPLATES.get(category, _REASON_TEMPLATES["next"])
    items = []
    for t in topics:
        idx     = _reason_rotation.get(category, 0) % len(templates)
        reason  = templates[idx].format(topic=base_topic, item=t)
        _reason_rotation[category] = idx + 1
        items.append({"topic": t, "reason": reason})
    return items


def _empty_result(topic: str | None) -> dict:
    return {
        "based_on_topic":  topic or None,
        "source":          "empty",
        "next_topics":     [],
        "prerequisites":   [],
        "advanced_topics": [],
    }
