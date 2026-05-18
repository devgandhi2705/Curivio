"""
Intellectual timeline aggregation service.

Merges digest sessions, deep research records, and user preferences into a
unified chronological timeline for the History page.

No AI calls — pure database reads and deterministic transformations.

Event types
-----------
  session    — a learning feed session (from daily_digests)
  deep_dive  — a completed deep research (from deep_research table)
  milestone  — a derived achievement (first session, N topics explored, etc.)

Public API
----------
build_timeline(limit)          → dict  (full timeline payload)
_build_events(digests, research) → list  (pure, testable)
_derive_milestones(digests_asc, research) → list  (pure, testable)
_find_unfinished(digests, researched_keys) → list  (pure, testable)
_compute_stats(digests, research, preferences) → dict  (pure, testable)
_interest_trajectory(preferences) → list  (pure, testable)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Unique-topic milestones to celebrate
_TOPIC_MILESTONES = {5: "5 Topics Explored", 10: "10 Topics Explored",
                     25: "25 Topics Explored", 50: "50 Topics Explored"}
_MAX_UNFINISHED = 6
_MAX_TRAJECTORY = 8


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def build_timeline(limit: int = 50) -> dict:
    """
    Return the full timeline payload for the History page.

    Queries the database once per source, then delegates all logic to pure
    helper functions so callers can test those helpers independently.
    """
    try:
        digests = _fetch_digests(limit=min(limit * 3, 150))
    except Exception:
        logger.warning("[timeline] digest fetch failed")
        digests = []

    try:
        research = _fetch_research()
    except Exception:
        logger.warning("[timeline] research fetch failed")
        research = []

    try:
        preferences = _fetch_preferences()
    except Exception:
        logger.warning("[timeline] preferences fetch failed")
        preferences = []

    researched_keys = {r["topic"].strip().lower() for r in research}

    # Build sorted event list
    digests_asc  = list(reversed(digests))   # oldest first for milestone detection
    session_evts = _build_session_events(digests)
    research_evts = _build_research_events(research)
    milestone_evts = _derive_milestones(digests_asc, research)

    events = sorted(
        session_evts + research_evts + milestone_evts,
        key=lambda e: e["timestamp"],
        reverse=True,
    )

    return {
        "timeline":               events[:limit],
        "stats":                  _compute_stats(digests, research, preferences),
        "unfinished_explorations": _find_unfinished(digests[:10], researched_keys),
        "interest_trajectory":    _interest_trajectory(preferences),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Pure event builders (exposed for testing)
# ═══════════════════════════════════════════════════════════════════════════════

def _build_session_events(digests: list[dict]) -> list[dict]:
    """Convert digest rows into session timeline events."""
    events = []
    for d in digests:
        topics = [t.get("title", "") for t in _parse_json(d.get("learning_topics_json", "[]"), [])]
        events.append({
            "id":        f"session-{d['id']}",
            "type":      "session",
            "timestamp": _normalise_ts(d["generated_at"]),
            "date":      _date_only(d["generated_at"]),
            "title":     d["news_title"],
            "topics":    [t for t in topics if t],
            "next_step": d.get("next_step", ""),
            "source":    d.get("source", "scheduler"),
            "digest_id": d["id"],
        })
    return events


def _build_research_events(research: list[dict]) -> list[dict]:
    """Convert deep_research rows into deep_dive timeline events."""
    events = []
    for r in research:
        data     = _parse_json(r.get("research_json", "{}"), {})
        findings = data.get("key_findings", [])
        events.append({
            "id":               f"deep_dive-{r['id']}",
            "type":             "deep_dive",
            "timestamp":        _normalise_ts(r["generated_at"]),
            "date":             _date_only(r["generated_at"]),
            "title":            r["topic"],
            "confidence_level": data.get("confidence_level", "medium"),
            "key_findings":     findings[:2],
            "research_summary": data.get("research_summary", ""),
        })
    return events


def _derive_milestones(digests_asc: list[dict], research: list[dict]) -> list[dict]:
    """
    Compute milestone events from chronological digest and research data.

    digests_asc must be sorted oldest-first so thresholds are detected at the
    correct historical point.  Returns a list of milestone event dicts.
    """
    milestones: list[dict] = []
    seen_keys: set[str]    = set()
    crossed: set[int]      = set()

    for d in digests_asc:
        topics = _parse_json(d.get("learning_topics_json", "[]"), [])
        prev   = len(seen_keys)
        for t in topics:
            key = t.get("title", "").strip().lower()
            if key:
                seen_keys.add(key)
        after = len(seen_keys)

        for threshold, label in _TOPIC_MILESTONES.items():
            if threshold not in crossed and prev < threshold <= after:
                crossed.add(threshold)
                milestones.append({
                    "id":          f"milestone-topics-{threshold}",
                    "type":        "milestone",
                    "timestamp":   _normalise_ts(d["generated_at"]),
                    "date":        _date_only(d["generated_at"]),
                    "title":       label,
                    "icon":        "🏆",
                    "description": f"You've explored {threshold} unique topics on your learning journey.",
                })

    # First deep research milestone
    if research:
        oldest = min(research, key=lambda r: r["generated_at"])
        milestones.append({
            "id":          "milestone-first-deep-dive",
            "type":        "milestone",
            "timestamp":   _normalise_ts(oldest["generated_at"]),
            "date":        _date_only(oldest["generated_at"]),
            "title":       "First Deep Research",
            "icon":        "🔬",
            "description": f'You completed your first deep dive into "{oldest["topic"]}".',
        })

    return milestones


def _find_unfinished(recent_digests: list[dict], researched_keys: set[str]) -> list[dict]:
    """
    Return topics from recent sessions that haven't been deeply researched.

    Only considers the most recent sessions (caller should slice to ~10) to
    keep suggestions relevant.  Deduplicates by topic key.
    """
    seen: dict[str, dict] = {}

    for d in recent_digests:
        topics = _parse_json(d.get("learning_topics_json", "[]"), [])
        for t in topics:
            title = t.get("title", "").strip()
            key   = title.lower()
            if key and key not in researched_keys and key not in seen:
                seen[key] = {
                    "topic":              title,
                    "last_seen_date":     _date_only(d["generated_at"]),
                    "from_session_title": d.get("news_title", ""),
                }

    return list(seen.values())[:_MAX_UNFINISHED]


def _compute_stats(
    digests:     list[dict],
    research:    list[dict],
    preferences: list[dict],
) -> dict:
    """Derive headline stats from raw DB rows."""
    unique_topics: set[str] = set()
    for d in digests:
        for t in _parse_json(d.get("learning_topics_json", "[]"), []):
            key = t.get("title", "").strip().lower()
            if key:
                unique_topics.add(key)

    active_interests = sum(
        1 for p in preferences if p.get("preference_score", 0) > 0
    )

    return {
        "total_sessions":        len(digests),
        "unique_topics_explored": len(unique_topics),
        "deep_dives_completed":  len(research),
        "active_interests":      active_interests,
    }


def _interest_trajectory(preferences: list[dict]) -> list[str]:
    """
    Return up to _MAX_TRAJECTORY recent positive-interest topics.

    Sorted by last_updated so the trajectory reflects recent activity.
    """
    positive = [p for p in preferences if p.get("preference_score", 0) > 0]
    positive.sort(key=lambda p: p.get("last_updated", ""), reverse=True)
    return [p["topic"] for p in positive[:_MAX_TRAJECTORY]]


# ═══════════════════════════════════════════════════════════════════════════════
# Database fetchers (thin wrappers — easily mocked in tests)
# ═══════════════════════════════════════════════════════════════════════════════

def _fetch_digests(limit: int = 150) -> list[dict]:
    from .digest_storage_service import list_digests
    try:
        return list_digests(limit=limit)
    except Exception:
        logger.warning("[timeline] could not fetch digests")
        return []


def _fetch_research() -> list[dict]:
    from ..utils.db import get_connection
    try:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT id, topic, research_json, generated_at FROM deep_research ORDER BY generated_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        logger.warning("[timeline] could not fetch research records")
        return []


def _fetch_preferences() -> list[dict]:
    from ..utils.db import list_preferences
    try:
        return list_preferences(order_by="last_updated", limit=50)
    except Exception:
        logger.warning("[timeline] could not fetch preferences")
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_json(raw: str | list | None, default):
    if isinstance(raw, list):
        return raw
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


def _normalise_ts(value: str) -> str:
    """Return a sortable ISO timestamp string, padding missing timezone info."""
    if not value:
        return "1970-01-01T00:00:00"
    return value.replace(" ", "T")


def _date_only(value: str) -> str:
    """Extract YYYY-MM-DD from any timestamp string."""
    ts = _normalise_ts(value)
    return ts[:10] if len(ts) >= 10 else "1970-01-01"
