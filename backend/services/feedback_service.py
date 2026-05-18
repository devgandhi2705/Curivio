from ..utils.db import record_feedback

# Maps each feedback value to a human-readable description returned in the response.
FEEDBACK_LABELS = {
    "liked":        "Marked as helpful",
    "disliked":     "Marked as not helpful",
    "too_advanced": "Difficulty adjusted down",
    "too_basic":    "Difficulty adjusted up",
}


def process_feedback(topic: str, feedback: str) -> dict:
    """
    Apply a feedback signal to a topic and return the updated preference state.

    Returns a dict with keys:
        topic, feedback, message,
        preference_score, difficulty_preference,
        times_liked, times_disliked, times_recommended, last_updated
    """
    updated = record_feedback(topic, feedback)

    return {
        "topic":                updated["topic"],
        "feedback":             feedback,
        "message":              FEEDBACK_LABELS[feedback],
        "preference_score":     updated["preference_score"],
        "difficulty_preference": updated["difficulty_preference"],
        "times_liked":          updated["times_liked"],
        "times_disliked":       updated["times_disliked"],
        "times_recommended":    updated["times_recommended"],
        "last_updated":         updated["last_updated"],
    }
