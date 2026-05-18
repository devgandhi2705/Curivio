"""
Adaptive explanation engine for the AI learning companion.

Synthesises multiple user signals into a single inferred learner level and
produces explanation-style directives that are injected into the AI system
prompt.  No vectors, no ML — plain SQL + deterministic scoring.

Signals (weighted, all from SQLite):
  1. explicit_difficulty  — most-common non-null difficulty_preference
                            from user_preferences  (strongest signal)
  2. exploration_breadth  — COUNT(DISTINCT topic_key) in research_sessions
  3. avg_preference_score — AVG(preference_score) across user_preferences
  4. session_depth        — user-role message count for the active session

Level thresholds
----------------
  level_score < BEGINNER_CAP         → "beginner"
  BEGINNER_CAP ≤ score < ADVANCED_FLOOR → "intermediate"
  score ≥ ADVANCED_FLOOR             → "advanced"

Public API
----------
build_learner_profile(session_id=None) -> dict
get_explanation_directive(session_id=None) -> str
"""

from __future__ import annotations

import logging
from collections import Counter

logger = logging.getLogger(__name__)

# ── Scoring constants ──────────────────────────────────────────────────────────

BEGINNER_CAP:    float = 0.35
ADVANCED_FLOOR:  float = 0.65
BASE_SCORE:      float = 0.50   # no signals → intermediate

_DIFFICULTY_MODIFIERS = {"beginner": -0.30, "intermediate": 0.0, "advanced": +0.30}
_BREADTH_THRESHOLDS = [(20, +0.10), (10, +0.05), (3, 0.0), (1, -0.05)]
_SESSION_DEPTH_PROGRESSIVE = 3   # turns before progressive-depth note is added

# ── Explanation style templates ────────────────────────────────────────────────

EXPLANATION_STYLES: dict[str, dict] = {
    "beginner": {
        "depth":             "surface",
        "use_analogies":     True,
        "use_code_examples": False,
        "use_jargon":        False,
        "pace":              "slow",
    },
    "intermediate": {
        "depth":             "moderate",
        "use_analogies":     True,
        "use_code_examples": True,
        "use_jargon":        True,
        "pace":              "normal",
    },
    "advanced": {
        "depth":             "deep",
        "use_analogies":     False,
        "use_code_examples": True,
        "use_jargon":        True,
        "pace":              "fast",
    },
}

_DIRECTIVE_BASE: dict[str, str] = {
    "beginner": (
        "Explanation style: BEGINNER — prioritise clarity over completeness.\n"
        "- Use simple, accessible language. Define every technical term you introduce.\n"
        "- Ground abstract concepts in real-world analogies.\n"
        "- Build ideas step-by-step from first principles.\n"
        "- One idea at a time; avoid information overload."
    ),
    "intermediate": (
        "Explanation style: INTERMEDIATE — balance depth with accessibility.\n"
        "- Use standard technical vocabulary; briefly define niche or field-specific terms.\n"
        "- Include practical examples or short code snippets where they aid understanding.\n"
        "- Assume familiarity with core ML/programming concepts; skip basics.\n"
        "- Cover the \"why\" not just the \"what\"."
    ),
    "advanced": (
        "Explanation style: ADVANCED — full technical depth.\n"
        "- Use precise terminology without simplification.\n"
        "- Cover implementation details, edge cases, and trade-offs.\n"
        "- Assume expert-level foundations; do not explain basics.\n"
        "- Highlight non-obvious insights, subtleties, and current best practices."
    ),
}


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def build_learner_profile(session_id: str | None = None) -> dict:
    """
    Synthesise all available signals into a learner profile.

    Return shape
    ------------
    {
      "inferred_level":    str,         # "beginner" | "intermediate" | "advanced"
      "level_score":       float,       # 0.0–1.0 (higher → more advanced)
      "confidence":        float,       # 0.0–1.0 (how many signals contributed)
      "signals": {
        "explicit_difficulty":      str | None,
        "difficulty_distribution":  dict,       # {level: count}
        "exploration_breadth":      int,
        "avg_preference_score":     float,
        "session_depth":            int,
      },
      "style": {                        # from EXPLANATION_STYLES[inferred_level]
        "depth":             str,
        "use_analogies":     bool,
        "use_code_examples": bool,
        "use_jargon":        bool,
        "pace":              str,
      },
      "directive":         str,         # ready-to-inject instruction for Groq
      "topic_connections": list[str],   # recently-explored topics for grounding
    }
    """
    signals         = _gather_signals(session_id)
    level_score     = _compute_level_score(signals)
    inferred_level  = _score_to_level(level_score)
    confidence      = _compute_confidence(signals)
    topic_conns     = _get_topic_connections()
    directive       = _build_directive(inferred_level, signals, topic_conns)

    return {
        "inferred_level":    inferred_level,
        "level_score":       round(level_score, 3),
        "confidence":        round(confidence, 3),
        "signals":           signals,
        "style":             EXPLANATION_STYLES[inferred_level].copy(),
        "directive":         directive,
        "topic_connections": topic_conns,
    }


def get_explanation_directive(session_id: str | None = None) -> str:
    """Convenience wrapper — returns only the directive string."""
    return build_learner_profile(session_id)["directive"]


# ═══════════════════════════════════════════════════════════════════════════════
# Signal gathering
# ═══════════════════════════════════════════════════════════════════════════════

def _gather_signals(session_id: str | None) -> dict:
    signals: dict = {
        "explicit_difficulty":     None,
        "difficulty_distribution": {},
        "exploration_breadth":     0,
        "avg_preference_score":    0.0,
        "session_depth":           0,
    }

    try:
        from ..utils.db import get_connection
        with get_connection() as conn:
            pref_rows = conn.execute(
                "SELECT difficulty_preference, preference_score "
                "FROM user_preferences"
            ).fetchall()

            breadth_row = conn.execute(
                "SELECT COUNT(DISTINCT topic_key) AS n FROM research_sessions"
            ).fetchone()

            if session_id and session_id.strip():
                depth_row = conn.execute(
                    "SELECT COUNT(*) AS n FROM chat_messages "
                    "WHERE session_id = ? AND role = 'user'",
                    (session_id.strip(),),
                ).fetchone()
                signals["session_depth"] = depth_row["n"] if depth_row else 0

    except Exception:
        logger.exception("_gather_signals DB error")
        return signals

    if pref_rows:
        diff_vals = [r["difficulty_preference"] for r in pref_rows if r["difficulty_preference"]]
        if diff_vals:
            dist = dict(Counter(diff_vals))
            signals["difficulty_distribution"] = dist
            signals["explicit_difficulty"] = Counter(diff_vals).most_common(1)[0][0]

        scores = [r["preference_score"] for r in pref_rows]
        signals["avg_preference_score"] = sum(scores) / len(scores) if scores else 0.0

    if breadth_row:
        signals["exploration_breadth"] = breadth_row["n"] or 0

    return signals


def _get_topic_connections(limit: int = 4) -> list[str]:
    """Return the most-recently-explored topic names for grounding examples."""
    try:
        from ..utils.db import get_connection
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT   topic
                FROM     research_sessions
                GROUP BY topic_key
                ORDER BY MAX(recorded_at) DESC
                LIMIT    ?
                """,
                (limit,),
            ).fetchall()
        return [r["topic"] for r in rows]
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# Score computation
# ═══════════════════════════════════════════════════════════════════════════════

def _compute_level_score(signals: dict) -> float:
    score = BASE_SCORE

    # Strongest signal: explicit difficulty preference
    diff = signals.get("explicit_difficulty")
    if diff in _DIFFICULTY_MODIFIERS:
        score += _DIFFICULTY_MODIFIERS[diff]

    # Exploration breadth
    breadth = signals.get("exploration_breadth", 0)
    for threshold, modifier in _BREADTH_THRESHOLDS:
        if breadth >= threshold:
            score += modifier
            break

    # Average engagement score — proxy for challenge fit
    avg_score = signals.get("avg_preference_score", 0.0)
    if avg_score > 1.0:
        score += 0.05
    elif avg_score < 0.0:
        score -= 0.05

    return max(0.05, min(0.95, score))


def _score_to_level(score: float) -> str:
    if score < BEGINNER_CAP:
        return "beginner"
    if score >= ADVANCED_FLOOR:
        return "advanced"
    return "intermediate"


def _compute_confidence(signals: dict) -> float:
    """Return a 0–1 confidence score based on how many non-default signals exist."""
    signal_count = 0

    if signals.get("explicit_difficulty") is not None:
        signal_count += 2   # explicit feedback is high-value

    if signals.get("exploration_breadth", 0) > 0:
        signal_count += 1

    if signals.get("avg_preference_score", 0.0) != 0.0:
        signal_count += 1

    if signals.get("session_depth", 0) > 0:
        signal_count += 1

    # Map signal_count → confidence
    return min(0.9, 0.2 + signal_count * 0.15)


# ═══════════════════════════════════════════════════════════════════════════════
# Directive construction
# ═══════════════════════════════════════════════════════════════════════════════

def _build_directive(
    level: str,
    signals: dict,
    topic_connections: list[str],
) -> str:
    parts = [_DIRECTIVE_BASE[level]]

    # Topic grounding: anchor new explanations in prior knowledge
    if topic_connections:
        topics_str = ", ".join(topic_connections[:3])
        parts.append(
            f"- When helpful, ground explanations in topics the user already "
            f"knows: {topics_str}."
        )

    # Progressive depth: longer sessions signal an engaged, deepening learner
    session_depth = signals.get("session_depth", 0)
    if session_depth >= _SESSION_DEPTH_PROGRESSIVE:
        if level == "beginner":
            parts.append(
                f"- User is {session_depth} turns into this session — they are "
                f"engaged. Gradually introduce slightly more complex ideas."
            )
        else:
            parts.append(
                f"- User is {session_depth} turns into this session — they are "
                f"in a flow state. Increase technical depth progressively."
            )

    # Low confidence fallback note (for prompt transparency)
    confidence = _compute_confidence(signals)
    if confidence < 0.4:
        parts.append(
            "- (Limited user data available — adjust depth based on the user's "
            "responses in this conversation.)"
        )

    return "\n".join(parts)
