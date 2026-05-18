"""
Recommendation scoring for the AI learning agent.

These three functions translate raw feedback counters into actionable signals:
which topics to surface next, and at what difficulty level.

Scoring model (simple, no ML):
    preference_score = (times_liked - times_disliked) / max(1, times_recommended)

    > 0   → user responded positively → prioritise
    = 0   → neutral or unseen         → include normally
    < 0   → user responded negatively → suppress below SUPPRESS_THRESHOLD
    ≤ -1  → strongly disliked         → never recommend again
"""

from ..utils.db import record_feedback, list_preferences, get_preference

# Topics scoring below this are excluded from recommendations.
# -0.25 means the user has been more negative than positive 25% of the time.
# Edit this constant to tune how aggressively disliked topics are suppressed.
SUPPRESS_THRESHOLD: float = -0.25

# Ordered from easiest to hardest — used for stepping logic.
DIFFICULTY_LEVELS = ["beginner", "intermediate", "advanced"]


# ── Public API ────────────────────────────────────────────────────────────────

def update_preference_score(topic: str, feedback: str) -> dict:
    """
    Apply a feedback signal to a topic and return the updated scoring state.

    Feedback effects on score and difficulty:
    ┌──────────────┬──────────────────────────────┬───────────────────────────┐
    │ Feedback     │ Score effect                 │ Difficulty effect         │
    ├──────────────┼──────────────────────────────┼───────────────────────────┤
    │ liked        │ +1 liked → score rises       │ unchanged                 │
    │ disliked     │ +1 disliked → score falls    │ unchanged                 │
    │ too_advanced │ unchanged                    │ step down one level       │
    │ too_basic    │ unchanged                    │ step up one level         │
    └──────────────┴──────────────────────────────┴───────────────────────────┘

    Returns scoring-relevant fields only (not a full preference row).
    """
    row = record_feedback(topic, feedback)
    return _score_fields(row)


def get_top_user_interests(limit: int = 5) -> list[dict]:
    """
    Return the highest-scoring topics to prioritise in the next feed.

    Rules:
    - Topics below SUPPRESS_THRESHOLD are excluded (user actively disliked them).
    - Remaining topics are sorted by preference_score descending.
    - Topics with score = 0 (neutral/unseen) are included — they haven't been
      penalised and are fair candidates for recommendation.

    Each entry contains: topic, preference_score, difficulty_preference,
                         times_recommended.
    """
    rows = list_preferences(order_by="preference_score", limit=100)

    filtered = [
        _interest_fields(r)
        for r in rows
        if r["preference_score"] > SUPPRESS_THRESHOLD
    ]

    return filtered[:limit]


def get_suppressed_topics(limit: int = 10) -> list[str]:
    """
    Return topic names the user has negatively rated (score <= SUPPRESS_THRESHOLD).
    Used to tell the AI what to avoid recommending.
    """
    rows = list_preferences(order_by="preference_score", limit=100)
    return [
        r["topic"]
        for r in rows
        if r["preference_score"] <= SUPPRESS_THRESHOLD
    ][:limit]


def get_overall_difficulty_preference() -> str:
    """
    Return the user's general preferred difficulty inferred from all liked topics.
    Falls back to 'intermediate' when no history exists yet.
    """
    all_rows = list_preferences(order_by="preference_score", limit=100)
    liked_diffs = [
        r["difficulty_preference"]
        for r in all_rows
        if r["difficulty_preference"] and r["preference_score"] > 0
    ]

    if not liked_diffs:
        return "intermediate"

    counts = {d: liked_diffs.count(d) for d in DIFFICULTY_LEVELS}
    return max(counts, key=lambda d: counts[d])


def get_learning_stage() -> str:
    """
    Infer how far the user has progressed based on distinct positively-rated topics.

    Stage thresholds (edit to recalibrate):
      "early"      0–3  liked topics  → needs more foundational coverage
      "developing" 4–10 liked topics  → ready to push into intermediate/advanced
      "proficient" 11+  liked topics  → challenge them; anchor with one beginner refresher

    Used by the prompt to set the 4-topic difficulty distribution.
    """
    rows = list_preferences(order_by="preference_score", limit=100)
    liked_count = sum(1 for r in rows if r["preference_score"] > 0)

    if liked_count <= 3:
        return "early"
    if liked_count <= 10:
        return "developing"
    return "proficient"


def get_frequently_seen_topics(threshold: int = 3) -> list[str]:
    """
    Return topic names the user has explicitly reacted to >= `threshold` times
    (likes + dislikes combined).

    These are already familiar — recommending them again adds no value.
    The prompt uses this list to enforce freshness: don't repeat, but
    you may reference them as prerequisite context.

    Uses total feedback interactions rather than times_recommended because
    the feed pipeline tracks explicit reactions, not passive impressions.
    `threshold` defaults to 3; raise it to be less strict about repetition.
    """
    rows = list_preferences(order_by="preference_score", limit=100)
    return [
        r["topic"]
        for r in rows
        if (r["times_liked"] + r["times_disliked"]) >= threshold
    ]


def get_recommended_difficulty(topic: str) -> str:
    """
    Return the recommended difficulty level for a topic.

    Resolution order:
    1. Explicit difficulty_preference stored for this exact topic  →  use it.
    2. Most common difficulty among topics the user has liked       →  use it.
    3. Fallback                                                     →  "intermediate".

    This means difficulty adapts per-topic but also respects the user's
    overall comfort level when no per-topic signal exists yet.
    """
    row = get_preference(topic)

    # 1. Per-topic explicit preference
    if row and row["difficulty_preference"]:
        return row["difficulty_preference"]

    # 2. Infer from liked topics across the whole history
    all_rows = list_preferences(order_by="preference_score", limit=100)
    liked_difficulties = [
        r["difficulty_preference"]
        for r in all_rows
        if r["difficulty_preference"] and r["preference_score"] > 0
    ]

    if liked_difficulties:
        counts = {d: liked_difficulties.count(d) for d in DIFFICULTY_LEVELS}
        return max(counts, key=lambda d: counts[d])

    # 3. Default
    return "intermediate"


# ── Private helpers ───────────────────────────────────────────────────────────

def _score_fields(row: dict) -> dict:
    return {
        "topic":                 row["topic"],
        "preference_score":      row["preference_score"],
        "difficulty_preference": row["difficulty_preference"],
        "times_liked":           row["times_liked"],
        "times_disliked":        row["times_disliked"],
        "times_recommended":     row["times_recommended"],
    }


def _interest_fields(row: dict) -> dict:
    return {
        "topic":                 row["topic"],
        "preference_score":      row["preference_score"],
        "difficulty_preference": row["difficulty_preference"],
        "times_recommended":     row["times_recommended"],
    }
