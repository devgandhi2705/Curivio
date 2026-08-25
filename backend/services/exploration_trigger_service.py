"""
Autonomous exploration trigger logic for the AI learning agent.

Evaluates three modular signals to decide whether a topic warrants deeper
autonomous research:

  1. user_engagement        — likes and preference score from user_preferences
  2. news_frequency         — recent appearances in daily_digests
  3. educational_importance — references in learning_paths / topic_expansions

A weighted score is computed and checked against TRIGGER_THRESHOLD.
A cooldown guard prevents re-triggering within COOLDOWN_HOURS of recent research.

Public API
----------
evaluate_exploration(topic) -> ExplorationDecision
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ..utils.db import get_connection

# ── Configuration ──────────────────────────────────────────────────────────────

TRIGGER_THRESHOLD   = 0.50   # weighted score must reach this to trigger exploration
COOLDOWN_HOURS      = 72     # suppress re-exploration if research exists this recently
COOLDOWN_SCORE_MULT = 0.3    # dampening factor applied when cooldown is active
NEWS_LOOKBACK_DAYS  = 14     # days back to scan daily_digests for topic mentions

SIGNAL_WEIGHTS: dict[str, float] = {
    "user_engagement":        0.40,
    "news_frequency":         0.30,
    "educational_importance": 0.30,
}

# Actions recommended when each signal fires
_ACTION_MAP: dict[str, list[str]] = {
    "user_engagement":        ["learning_path"],
    "news_frequency":         ["learning_path"],
    "educational_importance": ["topic_expansion", "learning_path", "github_repos"],
}


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class TriggerSignal:
    name:   str
    score:  float   # 0.0–1.0
    fired:  bool    # True when this signal alone crosses its activation threshold
    reason: str


@dataclass
class ExplorationDecision:
    topic:               str
    should_explore:      bool
    total_score:         float
    signals:             list[TriggerSignal]
    recommended_actions: list[str]
    cooldown_active:     bool
    reason:              str


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def evaluate_exploration(topic: str) -> ExplorationDecision:
    """
    Decide whether autonomous deep exploration should run for *topic*.

    Returns an ExplorationDecision with full signal breakdown and reasoning.
    """
    topic = (topic or "").strip()
    if not topic:
        return ExplorationDecision(
            topic=topic,
            should_explore=False,
            total_score=0.0,
            signals=[],
            recommended_actions=[],
            cooldown_active=False,
            reason="empty topic",
        )

    signals = [
        _evaluate_user_engagement(topic),
        _evaluate_news_frequency(topic),
        _evaluate_educational_importance(topic),
    ]

    raw_score = sum(SIGNAL_WEIGHTS[s.name] * s.score for s in signals)

    cooldown = _is_in_cooldown(topic)
    total_score = raw_score * COOLDOWN_SCORE_MULT if cooldown else raw_score

    # Only explore when score is high enough AND not in cooldown
    should = total_score >= TRIGGER_THRESHOLD and not cooldown

    actions = _recommend_actions([s for s in signals if s.fired])

    if cooldown:
        reason = (
            f"cooldown active — raw score {raw_score:.2f} dampened to {total_score:.2f}"
        )
    elif should:
        fired = [s.name for s in signals if s.fired]
        reason = f"triggered by: {', '.join(fired) or 'combined signal'}"
    else:
        reason = f"score {total_score:.2f} below threshold {TRIGGER_THRESHOLD}"

    return ExplorationDecision(
        topic=topic,
        should_explore=should,
        total_score=round(total_score, 4),
        signals=signals,
        recommended_actions=actions,
        cooldown_active=cooldown,
        reason=reason,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Signal evaluators
# ═══════════════════════════════════════════════════════════════════════════════

def _evaluate_user_engagement(topic: str) -> TriggerSignal:
    """
    Score = 0.6 * min(1, likes/3) + 0.4 * min(1, pref_score/2.0)
    Fires when score >= 0.33 (roughly one like, or meaningful preference score).
    """
    FIRE_THRESHOLD = 0.33

    with get_connection() as conn:
        row = conn.execute(
            "SELECT times_liked, preference_score "
            "FROM user_preferences WHERE LOWER(topic) = LOWER(?)",
            (topic,),
        ).fetchone()

    if row is None:
        return TriggerSignal(
            name="user_engagement",
            score=0.0,
            fired=False,
            reason="no preference record found",
        )

    likes      = row["times_liked"]
    pref_score = row["preference_score"]
    score = 0.6 * min(1.0, likes / 3) + 0.4 * min(1.0, max(0.0, pref_score) / 2.0)

    return TriggerSignal(
        name="user_engagement",
        score=round(score, 4),
        fired=score >= FIRE_THRESHOLD,
        reason=f"likes={likes}, pref_score={pref_score:.2f}",
    )


def _evaluate_news_frequency(topic: str) -> TriggerSignal:
    """
    Counts how many recent digests mention the topic keyword.
    Score = min(1, count/3).  Fires when count >= 1.
    """
    FIRE_THRESHOLD = 1

    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=NEWS_LOOKBACK_DAYS)
    ).strftime("%Y-%m-%d %H:%M:%S")

    keyword = topic.strip().lower()

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT news_title, news_summary FROM daily_digests WHERE generated_at >= ?",
            (cutoff,),
        ).fetchall()

    count = sum(
        1 for r in rows
        if keyword in (r["news_title"]   or "").lower()
        or keyword in (r["news_summary"] or "").lower()
    )

    score = min(1.0, count / 3)
    return TriggerSignal(
        name="news_frequency",
        score=round(score, 4),
        fired=count >= FIRE_THRESHOLD,
        reason=f"{count} mention(s) in last {NEWS_LOOKBACK_DAYS} days",
    )


def _evaluate_educational_importance(topic: str) -> TriggerSignal:
    """
    Checks how many learning artifacts already reference this topic.
    Searches learning_paths.path_json and topic_expansions.expansion_json.
    Score = min(1, refs/3).  Fires when refs >= 1.
    """
    FIRE_THRESHOLD = 1

    keyword = f"%{topic.strip().lower()}%"

    with get_connection() as conn:
        lp_count = conn.execute(
            "SELECT COUNT(*) FROM learning_paths WHERE LOWER(path_json) LIKE ?",
            (keyword,),
        ).fetchone()[0]
        te_count = conn.execute(
            "SELECT COUNT(*) FROM topic_expansions WHERE LOWER(expansion_json) LIKE ?",
            (keyword,),
        ).fetchone()[0]

    total_refs = lp_count + te_count
    score = min(1.0, total_refs / 3)
    return TriggerSignal(
        name="educational_importance",
        score=round(score, 4),
        fired=total_refs >= FIRE_THRESHOLD,
        reason=f"{total_refs} ref(s) across learning_paths and topic_expansions",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Cooldown guard
# ═══════════════════════════════════════════════════════════════════════════════

def _is_in_cooldown(topic: str) -> bool:
    """Return True if deep_research for this topic exists within COOLDOWN_HOURS."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=COOLDOWN_HOURS)
    ).strftime("%Y-%m-%d %H:%M:%S")

    topic_key = topic.strip().lower()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM deep_research "
            "WHERE topic_key = ? AND generated_at >= ? LIMIT 1",
            (topic_key, cutoff),
        ).fetchone()

    return row is not None


# ═══════════════════════════════════════════════════════════════════════════════
# Action dispatcher
# ═══════════════════════════════════════════════════════════════════════════════

def _recommend_actions(fired_signals: list[TriggerSignal]) -> list[str]:
    """Return a deduplicated, insertion-ordered list of actions for fired signals."""
    seen:    set[str]  = set()
    actions: list[str] = []
    for signal in fired_signals:
        for action in _ACTION_MAP.get(signal.name, []):
            if action not in seen:
                seen.add(action)
                actions.append(action)
    return actions
