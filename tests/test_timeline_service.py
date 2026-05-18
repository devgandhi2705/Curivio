"""
Tests for timeline_service.

All tests use mocked history datasets; no database, no AI calls.

Coverage
--------
  TestBuildSessionEvents      — digest rows → session event shape
  TestBuildResearchEvents     — deep_research rows → deep_dive event shape
  TestDeriveMilestones        — topic thresholds, first deep dive milestone
  TestFindUnfinished          — topics not yet researched
  TestComputeStats            — derived headline numbers
  TestInterestTrajectory      — preference ordering
  TestBuildTimeline           — end-to-end with mocked DB fetchers
  TestHelpers                 — _parse_json, _normalise_ts, _date_only
"""

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from backend.services.timeline_service import (
    _build_research_events,
    _build_session_events,
    _compute_stats,
    _date_only,
    _derive_milestones,
    _find_unfinished,
    _interest_trajectory,
    _normalise_ts,
    _parse_json,
    build_timeline,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Shared fixtures
# ═══════════════════════════════════════════════════════════════════════════════

def _digest(id, title, topics, ts="2026-05-10T09:00:00", source="scheduler", next_step="Read more."):
    return {
        "id":                   id,
        "news_title":           title,
        "news_summary":         "Summary text.",
        "why_it_matters":       "It matters.",
        "learning_topics_json": json.dumps([{"title": t, "reason": "r", "difficulty": "intermediate"} for t in topics]),
        "next_step":            next_step,
        "source_links_json":    "[]",
        "source":               source,
        "generated_at":         ts,
    }


def _research(id, topic, ts="2026-05-12T14:00:00", confidence="high"):
    data = {
        "research_summary":   f"Summary of {topic}.",
        "key_findings":       [f"Finding A for {topic}", f"Finding B for {topic}"],
        "confidence_level":   confidence,
        "related_concepts":   [],
        "implementation_ideas": [],
        "practical_applications": [],
        "advanced_follow_ups": [],
    }
    return {
        "id":            id,
        "topic":         topic,
        "topic_key":     topic.lower(),
        "research_json": json.dumps(data),
        "generated_at":  ts,
    }


def _pref(topic, score, last_updated="2026-05-10T00:00:00"):
    return {
        "topic":            topic,
        "preference_score": score,
        "times_liked":      max(0, int(score)),
        "times_disliked":   0,
        "times_recommended": 2,
        "last_updated":     last_updated,
    }


DIGESTS = [
    _digest(3, "AI Safety", ["Constitutional AI", "RLHF", "Red-Teaming"], ts="2026-05-14T09:00:00"),
    _digest(2, "Efficient Transformers", ["Sparse Attention", "Flash Attention"], ts="2026-05-12T11:00:00"),
    _digest(1, "Intro to ML", ["Supervised Learning", "Gradient Descent", "Overfitting", "Cross-Validation", "Feature Engineering"], ts="2026-03-10T08:30:00"),
]

RESEARCH = [
    _research(2, "Transformer Architecture", ts="2026-05-15T14:00:00", confidence="high"),
    _research(1, "Reinforcement Learning",   ts="2026-04-20T10:00:00", confidence="medium"),
]

PREFERENCES = [
    _pref("Transformers",        2.1, last_updated="2026-05-15T00:00:00"),
    _pref("LLMs",                1.8, last_updated="2026-05-14T00:00:00"),
    _pref("Finance",             0.8, last_updated="2026-05-10T00:00:00"),
    _pref("Crypto",             -0.5, last_updated="2026-05-09T00:00:00"),
]


# ═══════════════════════════════════════════════════════════════════════════════
# 1. _build_session_events
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildSessionEvents:

    def test_returns_one_event_per_digest(self):
        events = _build_session_events(DIGESTS)
        assert len(events) == len(DIGESTS)

    def test_event_type_is_session(self):
        for e in _build_session_events(DIGESTS):
            assert e["type"] == "session"

    def test_event_id_prefixed_with_session(self):
        for e in _build_session_events(DIGESTS):
            assert e["id"].startswith("session-")

    def test_topics_extracted_from_json(self):
        events = _build_session_events([DIGESTS[0]])
        assert "Constitutional AI" in events[0]["topics"]
        assert "RLHF"              in events[0]["topics"]

    def test_title_preserved(self):
        events = _build_session_events([DIGESTS[0]])
        assert events[0]["title"] == "AI Safety"

    def test_source_preserved(self):
        d = _digest(99, "Test", ["T1"], source="user")
        events = _build_session_events([d])
        assert events[0]["source"] == "user"

    def test_date_only_field_present(self):
        events = _build_session_events([DIGESTS[0]])
        assert events[0]["date"] == "2026-05-14"

    def test_timestamp_normalised(self):
        events = _build_session_events([DIGESTS[0]])
        assert "T" in events[0]["timestamp"]

    def test_digest_id_preserved(self):
        events = _build_session_events([DIGESTS[0]])
        assert events[0]["digest_id"] == 3

    def test_next_step_preserved(self):
        d = _digest(5, "X", ["A"], next_step="Do something specific.")
        assert _build_session_events([d])[0]["next_step"] == "Do something specific."

    def test_empty_input_returns_empty(self):
        assert _build_session_events([]) == []

    def test_topics_are_strings(self):
        events = _build_session_events(DIGESTS)
        for e in events:
            assert all(isinstance(t, str) for t in e["topics"])

    def test_malformed_topics_json_gives_empty_list(self):
        d = _digest(10, "Bad", [])
        d["learning_topics_json"] = "not json {"
        events = _build_session_events([d])
        assert events[0]["topics"] == []


# ═══════════════════════════════════════════════════════════════════════════════
# 2. _build_research_events
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildResearchEvents:

    def test_returns_one_event_per_research(self):
        assert len(_build_research_events(RESEARCH)) == 2

    def test_event_type_is_deep_dive(self):
        for e in _build_research_events(RESEARCH):
            assert e["type"] == "deep_dive"

    def test_event_id_prefixed_with_deep_dive(self):
        for e in _build_research_events(RESEARCH):
            assert e["id"].startswith("deep_dive-")

    def test_title_is_topic_name(self):
        events = _build_research_events(RESEARCH)
        assert events[0]["title"] == "Transformer Architecture"

    def test_confidence_level_extracted(self):
        events = _build_research_events(RESEARCH)
        assert events[0]["confidence_level"] == "high"

    def test_key_findings_capped_at_2(self):
        events = _build_research_events(RESEARCH)
        assert len(events[0]["key_findings"]) <= 2

    def test_research_summary_extracted(self):
        events = _build_research_events([RESEARCH[0]])
        assert "Transformer Architecture" in events[0]["research_summary"]

    def test_date_field_present(self):
        events = _build_research_events([RESEARCH[0]])
        assert events[0]["date"] == "2026-05-15"

    def test_empty_research_json_gives_defaults(self):
        r = _research(99, "Topic X")
        r["research_json"] = "{}"
        events = _build_research_events([r])
        assert events[0]["confidence_level"] == "medium"
        assert events[0]["key_findings"] == []

    def test_empty_input_returns_empty(self):
        assert _build_research_events([]) == []


# ═══════════════════════════════════════════════════════════════════════════════
# 3. _derive_milestones
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeriveMilestones:

    def _make_digests_asc(self, topic_sets):
        """Build chronological digests, each containing given topics."""
        return [
            _digest(i + 1, f"Session {i + 1}", topics, ts=f"2026-0{(i // 9) + 1}-{(i % 28) + 1:02d}T08:00:00")
            for i, topics in enumerate(topic_sets)
        ]

    def test_no_milestones_when_few_topics(self):
        digests = self._make_digests_asc([["Topic A", "Topic B"]])
        milestones = _derive_milestones(digests, [])
        types = {m["id"] for m in milestones}
        assert "milestone-topics-5" not in types

    def test_five_topic_milestone_triggered(self):
        digests = self._make_digests_asc([
            ["A", "B", "C"],
            ["D", "E", "F"],
        ])
        ms = _derive_milestones(digests, [])
        ids = [m["id"] for m in ms]
        assert "milestone-topics-5" in ids

    def test_ten_topic_milestone_triggered(self):
        # 5 digests × 2 distinct topics each = 10 unique topics
        topic_sets = [[f"Topic{i*2}", f"Topic{i*2+1}"] for i in range(5)]
        digests = self._make_digests_asc(topic_sets)
        ms = _derive_milestones(digests, [])
        ids = [m["id"] for m in ms]
        assert "milestone-topics-10" in ids

    def test_milestone_not_duplicated(self):
        topic_sets = [[f"T{i}", f"T{i+1}", f"T{i+2}"] for i in range(5)]
        digests = self._make_digests_asc(topic_sets)
        ms = _derive_milestones(digests, [])
        ids = [m["id"] for m in ms]
        assert ids.count("milestone-topics-5") == 1

    def test_first_deep_dive_milestone_added(self):
        ms = _derive_milestones([], RESEARCH)
        ids = [m["id"] for m in ms]
        assert "milestone-first-deep-dive" in ids

    def test_first_deep_dive_uses_oldest_research(self):
        ms = _derive_milestones([], RESEARCH)
        m = next(m for m in ms if m["id"] == "milestone-first-deep-dive")
        assert "Reinforcement Learning" in m["description"]

    def test_no_first_deep_dive_when_no_research(self):
        ms = _derive_milestones([], [])
        ids = [m["id"] for m in ms]
        assert "milestone-first-deep-dive" not in ids

    def test_milestone_has_required_fields(self):
        topic_sets = [["A", "B", "C", "D", "E", "F"]]
        digests = self._make_digests_asc(topic_sets)
        ms = _derive_milestones(digests, [])
        for m in ms:
            assert "id"          in m
            assert "type"        in m
            assert "timestamp"   in m
            assert "date"        in m
            assert "title"       in m
            assert "icon"        in m
            assert "description" in m

    def test_milestone_type_is_milestone(self):
        ms = _derive_milestones([], RESEARCH)
        for m in ms:
            assert m["type"] == "milestone"

    def test_duplicate_topics_across_sessions_not_double_counted(self):
        # Sessions 1+2 both have A,B,C — only 3 unique so far (milestone NOT triggered).
        # Session 3 adds D,E — now 5 unique, milestone fires here (not earlier).
        digests = self._make_digests_asc([
            ["A", "B", "C"],
            ["A", "B", "C"],   # same topics — unique count stays at 3
            ["D", "E"],        # crosses 5 unique here
        ])
        ms = _derive_milestones(digests, [])
        ids = {m["id"] for m in ms}
        # Milestone SHOULD be present (5 unique reached), but only once
        assert "milestone-topics-5" in ids
        assert [m["id"] for m in ms].count("milestone-topics-5") == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 4. _find_unfinished
# ═══════════════════════════════════════════════════════════════════════════════

class TestFindUnfinished:

    def test_returns_list(self):
        assert isinstance(_find_unfinished(DIGESTS, set()), list)

    def test_excludes_researched_topics(self):
        researched = {"transformer architecture", "reinforcement learning"}
        # DIGESTS don't contain these — but we can build a controlled set
        d = _digest(1, "Test", ["Transformer Architecture", "New Topic"])
        result = _find_unfinished([d], researched)
        topics = [r["topic"] for r in result]
        assert "Transformer Architecture" not in topics
        assert "New Topic" in topics

    def test_deduplicates_across_sessions(self):
        d1 = _digest(1, "Session A", ["Topic X", "Topic Y"], ts="2026-05-10T00:00:00")
        d2 = _digest(2, "Session B", ["Topic X", "Topic Z"], ts="2026-05-11T00:00:00")
        result = _find_unfinished([d1, d2], set())
        topics = [r["topic"] for r in result]
        assert topics.count("Topic X") == 1

    def test_includes_session_title(self):
        d = _digest(1, "My Session Title", ["Novel Topic"])
        result = _find_unfinished([d], set())
        assert result[0]["from_session_title"] == "My Session Title"

    def test_includes_last_seen_date(self):
        d = _digest(1, "Session", ["Topic A"], ts="2026-05-14T09:00:00")
        result = _find_unfinished([d], set())
        assert result[0]["last_seen_date"] == "2026-05-14"

    def test_empty_digests_gives_empty_result(self):
        assert _find_unfinished([], set()) == []

    def test_all_topics_researched_gives_empty(self):
        d = _digest(1, "Session", ["AI", "ML"])
        result = _find_unfinished([d], {"ai", "ml"})
        assert result == []

    def test_capped_at_six(self):
        topics = [f"Topic {i}" for i in range(20)]
        d = _digest(1, "Big Session", topics)
        result = _find_unfinished([d], set())
        assert len(result) <= 6


# ═══════════════════════════════════════════════════════════════════════════════
# 5. _compute_stats
# ═══════════════════════════════════════════════════════════════════════════════

class TestComputeStats:

    def test_total_sessions_matches_digest_count(self):
        stats = _compute_stats(DIGESTS, RESEARCH, PREFERENCES)
        assert stats["total_sessions"] == len(DIGESTS)

    def test_deep_dives_matches_research_count(self):
        stats = _compute_stats(DIGESTS, RESEARCH, PREFERENCES)
        assert stats["deep_dives_completed"] == len(RESEARCH)

    def test_unique_topics_deduplicates(self):
        d1 = _digest(1, "A", ["Topic X", "Topic Y"])
        d2 = _digest(2, "B", ["Topic X", "Topic Z"])   # Topic X appears twice
        stats = _compute_stats([d1, d2], [], [])
        assert stats["unique_topics_explored"] == 3

    def test_active_interests_counts_positive_scores(self):
        stats = _compute_stats([], [], PREFERENCES)
        # 3 positive (2.1, 1.8, 0.8), 1 negative (-0.5)
        assert stats["active_interests"] == 3

    def test_empty_inputs_give_zero_stats(self):
        stats = _compute_stats([], [], [])
        assert stats["total_sessions"]        == 0
        assert stats["unique_topics_explored"] == 0
        assert stats["deep_dives_completed"]  == 0
        assert stats["active_interests"]      == 0

    def test_all_required_keys_present(self):
        stats = _compute_stats(DIGESTS, RESEARCH, PREFERENCES)
        assert {"total_sessions", "unique_topics_explored", "deep_dives_completed", "active_interests"} <= stats.keys()


# ═══════════════════════════════════════════════════════════════════════════════
# 6. _interest_trajectory
# ═══════════════════════════════════════════════════════════════════════════════

class TestInterestTrajectory:

    def test_returns_list_of_strings(self):
        result = _interest_trajectory(PREFERENCES)
        assert all(isinstance(t, str) for t in result)

    def test_excludes_negative_score_topics(self):
        result = _interest_trajectory(PREFERENCES)
        assert "Crypto" not in result

    def test_sorted_by_last_updated_desc(self):
        prefs = [
            _pref("Old Topic",    1.0, last_updated="2026-01-01T00:00:00"),
            _pref("New Topic",    1.0, last_updated="2026-05-15T00:00:00"),
            _pref("Middle Topic", 1.0, last_updated="2026-03-01T00:00:00"),
        ]
        result = _interest_trajectory(prefs)
        assert result[0] == "New Topic"

    def test_capped_at_eight(self):
        prefs = [_pref(f"Topic {i}", 1.0, last_updated=f"2026-05-{i+1:02d}T00:00:00") for i in range(20)]
        assert len(_interest_trajectory(prefs)) <= 8

    def test_empty_preferences_returns_empty(self):
        assert _interest_trajectory([]) == []


# ═══════════════════════════════════════════════════════════════════════════════
# 7. build_timeline (end-to-end with mocked fetchers)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildTimeline:

    def _run(self, digests=None, research=None, preferences=None):
        d = digests     if digests     is not None else DIGESTS
        r = research    if research    is not None else RESEARCH
        p = preferences if preferences is not None else PREFERENCES

        with patch("backend.services.timeline_service._fetch_digests",     return_value=d), \
             patch("backend.services.timeline_service._fetch_research",     return_value=r), \
             patch("backend.services.timeline_service._fetch_preferences",  return_value=p):
            return build_timeline(limit=50)

    def test_returns_dict_with_required_keys(self):
        result = self._run()
        assert {"timeline", "stats", "unfinished_explorations", "interest_trajectory"} <= result.keys()

    def test_timeline_is_list(self):
        assert isinstance(self._run()["timeline"], list)

    def test_stats_is_dict(self):
        assert isinstance(self._run()["stats"], dict)

    def test_unfinished_is_list(self):
        assert isinstance(self._run()["unfinished_explorations"], list)

    def test_interest_trajectory_is_list(self):
        assert isinstance(self._run()["interest_trajectory"], list)

    def test_events_sorted_newest_first(self):
        result = self._run()
        events = result["timeline"]
        for i in range(len(events) - 1):
            assert events[i]["timestamp"] >= events[i + 1]["timestamp"]

    def test_contains_session_events(self):
        result = self._run()
        types = {e["type"] for e in result["timeline"]}
        assert "session" in types

    def test_contains_deep_dive_events(self):
        result = self._run()
        types = {e["type"] for e in result["timeline"]}
        assert "deep_dive" in types

    def test_contains_milestone_events(self):
        # Enough topics to trigger a milestone
        d1 = _digest(1, "Intro", ["A","B","C","D","E","F"], ts="2026-03-01T08:00:00")
        result = self._run(digests=[d1], research=RESEARCH, preferences=[])
        types = {e["type"] for e in result["timeline"]}
        assert "milestone" in types

    def test_limit_respected(self):
        many_digests = [_digest(i, f"Session {i}", [f"T{i}"], ts=f"2026-05-{(i%28)+1:02d}T08:00:00") for i in range(100)]
        with patch("backend.services.timeline_service._fetch_digests",     return_value=many_digests), \
             patch("backend.services.timeline_service._fetch_research",     return_value=[]), \
             patch("backend.services.timeline_service._fetch_preferences",  return_value=[]):
            result = build_timeline(limit=10)
        assert len(result["timeline"]) <= 10

    def test_empty_db_gives_empty_timeline(self):
        result = self._run(digests=[], research=[], preferences=[])
        assert result["timeline"]               == []
        assert result["unfinished_explorations"] == []
        assert result["interest_trajectory"]    == []

    def test_researched_topics_excluded_from_unfinished(self):
        d = _digest(1, "AI Deep Dive", ["Transformer Architecture"], ts="2026-05-10T09:00:00")
        result = self._run(digests=[d], research=RESEARCH, preferences=[])
        topics = [e["topic"] for e in result["unfinished_explorations"]]
        assert "Transformer Architecture" not in topics

    def test_trajectory_excludes_negative_prefs(self):
        result = self._run()
        assert "Crypto" not in result["interest_trajectory"]

    def test_fetcher_failure_gives_empty_timeline(self):
        with patch("backend.services.timeline_service._fetch_digests",    side_effect=Exception("DB down")), \
             patch("backend.services.timeline_service._fetch_research",    side_effect=Exception("DB down")), \
             patch("backend.services.timeline_service._fetch_preferences", side_effect=Exception("DB down")):
            result = build_timeline()
        assert result["timeline"] == []


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Helpers
# ═══════════════════════════════════════════════════════════════════════════════

class TestHelpers:

    def test_parse_json_string(self):
        assert _parse_json('[{"a": 1}]', []) == [{"a": 1}]

    def test_parse_json_already_list(self):
        lst = [1, 2, 3]
        assert _parse_json(lst, []) == lst

    def test_parse_json_bad_string_returns_default(self):
        assert _parse_json("not json {", []) == []

    def test_parse_json_none_returns_default(self):
        assert _parse_json(None, "default") == "default"

    def test_parse_json_empty_string_returns_default(self):
        assert _parse_json("", []) == []

    def test_normalise_ts_replaces_space(self):
        assert _normalise_ts("2026-05-10 09:00:00") == "2026-05-10T09:00:00"

    def test_normalise_ts_preserves_t_format(self):
        assert _normalise_ts("2026-05-10T09:00:00") == "2026-05-10T09:00:00"

    def test_normalise_ts_empty_returns_fallback(self):
        assert _normalise_ts("") == "1970-01-01T00:00:00"

    def test_date_only_from_iso(self):
        assert _date_only("2026-05-15T14:22:00") == "2026-05-15"

    def test_date_only_from_space_separated(self):
        assert _date_only("2026-05-15 14:22:00") == "2026-05-15"

    def test_date_only_empty_returns_fallback(self):
        assert _date_only("") == "1970-01-01"
