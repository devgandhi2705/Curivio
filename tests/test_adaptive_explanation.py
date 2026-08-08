"""
Tests for the adaptive explanation engine.

Test classes
------------
1.  TestGatherSignals            — DB queries, signal extraction, session depth
2.  TestComputeLevelScore        — pure scoring logic for each signal combination
3.  TestScoreToLevel             — threshold boundary mapping
4.  TestComputeConfidence        — confidence rises with more signals
5.  TestBuildLearnerProfile      — full profile shape, defaults, level mapping
6.  TestDirectiveContent         — directive strings match each level's style
7.  TestTopicConnections         — topic grounding in directive
8.  TestProgressiveDepth         — session depth modifies directive
9.  TestExplanationDirectivePrompt — prompt builder includes directive section
10. TestInjectMemoryIncludesProfile — inject_memory adds learner_profile key

Patching rules
--------------
- DB tests monkeypatch backend.utils.db.get_connection.
- inject_memory tests patch the deferred imports at their source modules.
- All tests are unit / integration-free (no live AI calls).
"""

from __future__ import annotations

import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.database.schema import ALL_TABLES, MIGRATIONS
from backend.services.adaptive_explanation_service import (
    BASE_SCORE,
    BEGINNER_CAP,
    ADVANCED_FLOOR,
    EXPLANATION_STYLES,
    _build_directive,
    _compute_confidence,
    _compute_level_score,
    _gather_signals,
    _score_to_level,
    build_learner_profile,
    get_explanation_directive,
)
from backend.services.chat_prompt_service import (
    _build_explanation_directive_section,
    build_system_prompt,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Shared fixtures
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def mem_db(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    for stmt in ALL_TABLES:
        conn.execute(stmt)
    # Chat-R7a: user_preferences/research_sessions only gain their user_id
    # column via MIGRATIONS (matches real init_db()'s behavior).
    for migration in MIGRATIONS:
        try:
            if isinstance(migration, (list, tuple)):
                for stmt in migration:
                    conn.execute(stmt)
            else:
                conn.execute(migration)
        except sqlite3.OperationalError:
            pass
    conn.commit()

    @contextmanager
    def _get_conn():
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    import backend.utils.db as _db
    monkeypatch.setattr(_db, "get_connection", _get_conn)
    return conn


_TEST_USER = "test-user-1"


def _insert_pref(conn, topic, score, difficulty=None, user_id=_TEST_USER):
    conn.execute(
        "INSERT OR REPLACE INTO user_preferences "
        "(topic, user_id, preference_score, difficulty_preference) VALUES (?, ?, ?, ?)",
        (topic, user_id, score, difficulty),
    )
    conn.commit()


def _insert_session(conn, topic, activity="deep_research", ts="2025-01-01 10:00:00", user_id=_TEST_USER):
    conn.execute(
        "INSERT INTO research_sessions (topic, topic_key, activity, recorded_at, user_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (topic, topic.lower().strip(), activity, ts, user_id),
    )
    conn.commit()


def _insert_chat(conn, session_id, role, content, ts="2025-01-01 10:00:00"):
    conn.execute(
        "INSERT INTO chat_messages (session_id, role, content, created_at) "
        "VALUES (?, ?, ?, ?)",
        (session_id, role, content, ts),
    )
    conn.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. TestGatherSignals
# ═══════════════════════════════════════════════════════════════════════════════

class TestGatherSignals:

    def test_empty_db_returns_defaults(self, mem_db):
        signals = _gather_signals(None, user_id=_TEST_USER)
        assert signals["explicit_difficulty"] is None
        assert signals["exploration_breadth"] == 0
        assert signals["avg_preference_score"] == 0.0
        assert signals["session_depth"] == 0

    def test_missing_user_id_returns_defaults_even_with_data(self, mem_db):
        # Chat-R7a: no user_id must never fall back to global/other-user data.
        _insert_pref(mem_db, "T1", 1.0, "advanced")
        signals = _gather_signals(None)
        assert signals["explicit_difficulty"] is None

    def test_explicit_difficulty_most_common(self, mem_db):
        _insert_pref(mem_db, "T1", 1.0, "intermediate")
        _insert_pref(mem_db, "T2", 0.5, "intermediate")
        _insert_pref(mem_db, "T3", 0.2, "advanced")
        signals = _gather_signals(None, user_id=_TEST_USER)
        assert signals["explicit_difficulty"] == "intermediate"

    def test_difficulty_distribution_populated(self, mem_db):
        _insert_pref(mem_db, "T1", 1.0, "beginner")
        _insert_pref(mem_db, "T2", 0.5, "advanced")
        signals = _gather_signals(None, user_id=_TEST_USER)
        assert "beginner" in signals["difficulty_distribution"]
        assert "advanced" in signals["difficulty_distribution"]

    def test_avg_preference_score_correct(self, mem_db):
        _insert_pref(mem_db, "T1", 2.0)
        _insert_pref(mem_db, "T2", 0.0)
        signals = _gather_signals(None, user_id=_TEST_USER)
        assert abs(signals["avg_preference_score"] - 1.0) < 0.01

    def test_exploration_breadth_counts_unique_topics(self, mem_db):
        _insert_session(mem_db, "RAG",  "deep_research",   "2025-01-01")
        _insert_session(mem_db, "LoRA", "topic_expansion", "2025-01-02")
        _insert_session(mem_db, "RAG",  "learning_path",   "2025-01-03")  # duplicate topic
        signals = _gather_signals(None, user_id=_TEST_USER)
        assert signals["exploration_breadth"] == 2

    def test_other_user_signals_not_visible(self, mem_db):
        _insert_pref(mem_db, "T1", 2.0, "advanced", user_id="other-user")
        _insert_session(mem_db, "RAG", "deep_research", user_id="other-user")
        signals = _gather_signals(None, user_id=_TEST_USER)
        assert signals["explicit_difficulty"] is None
        assert signals["exploration_breadth"] == 0

    def test_session_depth_counts_user_turns(self, mem_db):
        _insert_chat(mem_db, "s1", "user",      "q1", "2025-01-01 10:00:00")
        _insert_chat(mem_db, "s1", "assistant", "a1", "2025-01-01 10:01:00")
        _insert_chat(mem_db, "s1", "user",      "q2", "2025-01-01 10:02:00")
        signals = _gather_signals("s1", user_id=_TEST_USER)
        assert signals["session_depth"] == 2

    def test_session_depth_zero_without_session_id(self, mem_db):
        _insert_chat(mem_db, "s1", "user", "q1")
        signals = _gather_signals(None, user_id=_TEST_USER)
        assert signals["session_depth"] == 0

    def test_session_depth_isolates_sessions(self, mem_db):
        _insert_chat(mem_db, "s1", "user", "q1", "2025-01-01 10:00:00")
        _insert_chat(mem_db, "s1", "user", "q2", "2025-01-01 10:01:00")
        _insert_chat(mem_db, "s2", "user", "q3", "2025-01-01 10:02:00")
        assert _gather_signals("s1", user_id=_TEST_USER)["session_depth"] == 2
        assert _gather_signals("s2", user_id=_TEST_USER)["session_depth"] == 1

    def test_graceful_on_db_error(self, monkeypatch):
        import backend.utils.db as _db
        monkeypatch.setattr(_db, "get_connection", MagicMock(side_effect=RuntimeError))
        signals = _gather_signals("any", user_id=_TEST_USER)
        assert signals["explicit_difficulty"] is None
        assert signals["exploration_breadth"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 2. TestComputeLevelScore
# ═══════════════════════════════════════════════════════════════════════════════

class TestComputeLevelScore:

    def _signals(self, **kwargs):
        base = {
            "explicit_difficulty": None,
            "difficulty_distribution": {},
            "exploration_breadth": 0,
            "avg_preference_score": 0.0,
            "session_depth": 0,
        }
        base.update(kwargs)
        return base

    def test_no_signals_returns_base_score(self):
        score = _compute_level_score(self._signals())
        assert abs(score - BASE_SCORE) < 0.01

    def test_beginner_difficulty_lowers_score(self):
        score = _compute_level_score(self._signals(explicit_difficulty="beginner"))
        assert score < BASE_SCORE
        assert score < BEGINNER_CAP

    def test_advanced_difficulty_raises_score(self):
        score = _compute_level_score(self._signals(explicit_difficulty="advanced"))
        assert score > BASE_SCORE
        assert score >= ADVANCED_FLOOR

    def test_intermediate_difficulty_no_change(self):
        score = _compute_level_score(self._signals(explicit_difficulty="intermediate"))
        assert abs(score - BASE_SCORE) < 0.01

    def test_high_breadth_raises_score(self):
        low  = _compute_level_score(self._signals(exploration_breadth=1))
        high = _compute_level_score(self._signals(exploration_breadth=20))
        assert high > low

    def test_low_breadth_lowers_score(self):
        none  = _compute_level_score(self._signals(exploration_breadth=0))
        small = _compute_level_score(self._signals(exploration_breadth=1))
        # breadth 0 triggers no threshold match; breadth 1 is under 3 so modifier=-0.05
        assert small < BASE_SCORE

    def test_positive_avg_score_raises(self):
        base = _compute_level_score(self._signals())
        high = _compute_level_score(self._signals(avg_preference_score=1.5))
        assert high > base

    def test_negative_avg_score_lowers(self):
        base = _compute_level_score(self._signals())
        low  = _compute_level_score(self._signals(avg_preference_score=-0.5))
        assert low < base

    def test_score_clamped_above_floor(self):
        score = _compute_level_score(self._signals(
            explicit_difficulty="beginner",
            exploration_breadth=0,
            avg_preference_score=-5.0,
        ))
        assert score >= 0.05

    def test_score_clamped_below_ceiling(self):
        score = _compute_level_score(self._signals(
            explicit_difficulty="advanced",
            exploration_breadth=25,
            avg_preference_score=5.0,
        ))
        assert score <= 0.95

    def test_combined_signals_are_additive(self):
        score_both = _compute_level_score(self._signals(
            explicit_difficulty="advanced",
            exploration_breadth=20,
        ))
        score_diff_only = _compute_level_score(self._signals(
            explicit_difficulty="advanced",
        ))
        assert score_both > score_diff_only


# ═══════════════════════════════════════════════════════════════════════════════
# 3. TestScoreToLevel
# ═══════════════════════════════════════════════════════════════════════════════

class TestScoreToLevel:

    def test_below_beginner_cap(self):
        assert _score_to_level(BEGINNER_CAP - 0.01) == "beginner"

    def test_exactly_beginner_cap_is_intermediate(self):
        assert _score_to_level(BEGINNER_CAP) == "intermediate"

    def test_midpoint_is_intermediate(self):
        mid = (BEGINNER_CAP + ADVANCED_FLOOR) / 2
        assert _score_to_level(mid) == "intermediate"

    def test_just_below_advanced_floor_is_intermediate(self):
        assert _score_to_level(ADVANCED_FLOOR - 0.01) == "intermediate"

    def test_exactly_advanced_floor_is_advanced(self):
        assert _score_to_level(ADVANCED_FLOOR) == "advanced"

    def test_above_advanced_floor_is_advanced(self):
        assert _score_to_level(0.95) == "advanced"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. TestComputeConfidence
# ═══════════════════════════════════════════════════════════════════════════════

class TestComputeConfidence:

    def _signals(self, **kwargs):
        base = {
            "explicit_difficulty": None,
            "difficulty_distribution": {},
            "exploration_breadth": 0,
            "avg_preference_score": 0.0,
            "session_depth": 0,
        }
        base.update(kwargs)
        return base

    def test_no_signals_low_confidence(self):
        conf = _compute_confidence(self._signals())
        assert conf < 0.4

    def test_explicit_difficulty_increases_confidence(self):
        no_diff   = _compute_confidence(self._signals())
        with_diff = _compute_confidence(self._signals(explicit_difficulty="intermediate"))
        assert with_diff > no_diff

    def test_more_signals_higher_confidence(self):
        few  = _compute_confidence(self._signals(explicit_difficulty="advanced"))
        many = _compute_confidence(self._signals(
            explicit_difficulty="advanced",
            exploration_breadth=10,
            avg_preference_score=1.2,
            session_depth=5,
        ))
        assert many > few

    def test_confidence_capped_at_0_9(self):
        conf = _compute_confidence(self._signals(
            explicit_difficulty="advanced",
            exploration_breadth=50,
            avg_preference_score=2.0,
            session_depth=20,
        ))
        assert conf <= 0.9


# ═══════════════════════════════════════════════════════════════════════════════
# 5. TestBuildLearnerProfile
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildLearnerProfile:

    def test_profile_has_expected_keys(self, mem_db):
        profile = build_learner_profile()
        for key in ("inferred_level", "level_score", "confidence", "signals",
                    "style", "directive", "topic_connections"):
            assert key in profile

    def test_default_level_is_intermediate(self, mem_db):
        profile = build_learner_profile()
        assert profile["inferred_level"] == "intermediate"

    def test_beginner_preference_produces_beginner_level(self, mem_db):
        _insert_pref(mem_db, "T1", 0.5, "beginner")
        _insert_pref(mem_db, "T2", 0.3, "beginner")
        _insert_pref(mem_db, "T3", 0.1, "beginner")
        profile = build_learner_profile(user_id=_TEST_USER)
        assert profile["inferred_level"] == "beginner"

    def test_advanced_preference_produces_advanced_level(self, mem_db):
        _insert_pref(mem_db, "T1", 1.5, "advanced")
        _insert_pref(mem_db, "T2", 1.2, "advanced")
        profile = build_learner_profile(user_id=_TEST_USER)
        assert profile["inferred_level"] == "advanced"

    def test_style_matches_inferred_level(self, mem_db):
        _insert_pref(mem_db, "T1", 0.5, "advanced")
        profile = build_learner_profile()
        assert profile["style"] == EXPLANATION_STYLES[profile["inferred_level"]]

    def test_directive_is_non_empty_string(self, mem_db):
        profile = build_learner_profile()
        assert isinstance(profile["directive"], str)
        assert len(profile["directive"]) > 20

    def test_level_score_in_range(self, mem_db):
        profile = build_learner_profile()
        assert 0.0 <= profile["level_score"] <= 1.0

    def test_confidence_in_range(self, mem_db):
        profile = build_learner_profile()
        assert 0.0 <= profile["confidence"] <= 1.0

    def test_topic_connections_populated(self, mem_db):
        _insert_session(mem_db, "RAG Pipelines",  "deep_research",   "2025-01-02")
        _insert_session(mem_db, "LoRA Fine-tuning","topic_expansion", "2025-01-01")
        profile = build_learner_profile(user_id=_TEST_USER)
        assert "RAG Pipelines" in profile["topic_connections"]

    def test_session_id_passed_for_depth(self, mem_db):
        _insert_chat(mem_db, "s1", "user", "q1", "2025-01-01 10:00:00")
        _insert_chat(mem_db, "s1", "user", "q2", "2025-01-01 10:01:00")
        _insert_chat(mem_db, "s1", "user", "q3", "2025-01-01 10:02:00")
        profile = build_learner_profile("s1", user_id=_TEST_USER)
        assert profile["signals"]["session_depth"] == 3

    def test_get_explanation_directive_returns_string(self, mem_db):
        directive = get_explanation_directive()
        assert isinstance(directive, str)
        assert len(directive) > 10

    def test_get_explanation_directive_matches_profile(self, mem_db):
        profile   = build_learner_profile()
        directive = get_explanation_directive()
        assert directive == profile["directive"]


# ═══════════════════════════════════════════════════════════════════════════════
# 6. TestDirectiveContent
# ═══════════════════════════════════════════════════════════════════════════════

class TestDirectiveContent:

    def _empty_signals(self):
        return {
            "explicit_difficulty": None,
            "difficulty_distribution": {},
            "exploration_breadth": 0,
            "avg_preference_score": 0.0,
            "session_depth": 0,
        }

    def test_beginner_directive_mentions_simplicity(self):
        directive = _build_directive("beginner", self._empty_signals(), [])
        assert any(word in directive.lower() for word in ("simple", "accessible", "jargon"))

    def test_beginner_directive_mentions_analogies(self):
        directive = _build_directive("beginner", self._empty_signals(), [])
        assert "analog" in directive.lower()

    def test_beginner_directive_mentions_step_by_step(self):
        directive = _build_directive("beginner", self._empty_signals(), [])
        assert "step" in directive.lower() or "first principles" in directive.lower()

    def test_intermediate_directive_mentions_examples(self):
        directive = _build_directive("intermediate", self._empty_signals(), [])
        assert "example" in directive.lower() or "code" in directive.lower()

    def test_intermediate_directive_mentions_technical_terms(self):
        directive = _build_directive("intermediate", self._empty_signals(), [])
        assert "technical" in directive.lower() or "terminology" in directive.lower()

    def test_advanced_directive_mentions_depth(self):
        directive = _build_directive("advanced", self._empty_signals(), [])
        assert any(word in directive.lower() for word in ("depth", "detail", "nuance", "implement"))

    def test_advanced_directive_skip_basics(self):
        directive = _build_directive("advanced", self._empty_signals(), [])
        assert "basic" in directive.lower() or "skip" in directive.lower()

    def test_level_label_in_directive(self):
        for level in ("beginner", "intermediate", "advanced"):
            directive = _build_directive(level, self._empty_signals(), [])
            assert level.upper() in directive


# ═══════════════════════════════════════════════════════════════════════════════
# 7. TestTopicConnections
# ═══════════════════════════════════════════════════════════════════════════════

class TestTopicConnections:

    def _empty_signals(self):
        return {
            "explicit_difficulty": None,
            "difficulty_distribution": {},
            "exploration_breadth": 0,
            "avg_preference_score": 0.0,
            "session_depth": 0,
        }

    def test_no_topics_no_grounding_line(self):
        directive = _build_directive("intermediate", self._empty_signals(), [])
        assert "already knows" not in directive

    def test_topics_added_to_directive(self):
        directive = _build_directive("intermediate", self._empty_signals(), ["RAG Pipelines", "LoRA"])
        assert "RAG Pipelines" in directive

    def test_multiple_topics_joined(self):
        directive = _build_directive("beginner", self._empty_signals(), ["A", "B", "C"])
        assert "A" in directive and "B" in directive

    def test_topic_connections_capped_at_three(self):
        topics = ["T1", "T2", "T3", "T4", "T5"]
        directive = _build_directive("intermediate", self._empty_signals(), topics)
        # Should only include first 3
        assert "T4" not in directive
        assert "T5" not in directive

    def test_topic_connections_in_full_profile(self, mem_db):
        _insert_session(mem_db, "RAG Pipelines", "deep_research", "2025-01-02")
        profile = build_learner_profile(user_id=_TEST_USER)
        assert "RAG Pipelines" in profile["topic_connections"]
        assert "RAG Pipelines" in profile["directive"]


# ═══════════════════════════════════════════════════════════════════════════════
# 8. TestProgressiveDepth
# ═══════════════════════════════════════════════════════════════════════════════

class TestProgressiveDepth:

    def _signals_with_depth(self, depth):
        return {
            "explicit_difficulty": None,
            "difficulty_distribution": {},
            "exploration_breadth": 0,
            "avg_preference_score": 0.0,
            "session_depth": depth,
        }

    def test_no_progressive_note_below_threshold(self):
        directive = _build_directive("intermediate", self._signals_with_depth(1), [])
        assert "turns" not in directive.lower()

    def test_progressive_note_at_threshold(self):
        from backend.services.adaptive_explanation_service import _SESSION_DEPTH_PROGRESSIVE
        directive = _build_directive("intermediate", self._signals_with_depth(_SESSION_DEPTH_PROGRESSIVE), [])
        assert "turns" in directive.lower() or "session" in directive.lower()

    def test_progressive_note_includes_turn_count(self):
        directive = _build_directive("advanced", self._signals_with_depth(7), [])
        assert "7" in directive

    def test_beginner_progressive_note_is_gentle(self):
        directive = _build_directive("beginner", self._signals_with_depth(5), [])
        assert "gradually" in directive.lower() or "slightly" in directive.lower()

    def test_advanced_progressive_note_encourages_depth(self):
        directive = _build_directive("advanced", self._signals_with_depth(8), [])
        assert "depth" in directive.lower() or "deeper" in directive.lower()

    def test_low_confidence_adds_fallback_note(self):
        signals = self._signals_with_depth(0)  # 0 non-default signals → low confidence
        directive = _build_directive("intermediate", signals, [])
        assert "limited" in directive.lower() or "adjust" in directive.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# 9. TestExplanationDirectivePrompt
# ═══════════════════════════════════════════════════════════════════════════════

class TestExplanationDirectivePrompt:

    def _make_context(self, learner_profile=None):
        return {
            "user_profile": {"learning_stage": "beginner", "difficulty_preference": None,
                             "top_interests": [], "suppressed_topics": []},
            "research":  {"topic": None},
            "session":   {"topic": None},
            "conversation_memory": {},
            "exploration_breadth": {},
            "preference_snapshot": {},
            "learner_profile": learner_profile or {},
        }

    def test_empty_learner_profile_returns_empty(self):
        assert _build_explanation_directive_section({}) == ""

    def test_directive_from_profile_passed_through(self):
        directive = "Explanation style: ADVANCED\n- Use precise terminology."
        result = _build_explanation_directive_section({"directive": directive})
        assert result == directive.strip()

    def test_empty_directive_returns_empty(self):
        result = _build_explanation_directive_section({"directive": ""})
        assert result == ""

    def test_whitespace_directive_returns_empty(self):
        result = _build_explanation_directive_section({"directive": "   "})
        assert result == ""

    def test_full_prompt_includes_beginner_directive(self):
        profile = {
            "directive": "Explanation style: BEGINNER\n- Use simple language.\n- Use analogies.",
            "inferred_level": "beginner",
        }
        ctx = self._make_context(learner_profile=profile)
        prompt = build_system_prompt(ctx)
        assert "BEGINNER" in prompt

    def test_full_prompt_includes_advanced_directive(self):
        profile = {
            "directive": "Explanation style: ADVANCED\n- Full technical depth.",
            "inferred_level": "advanced",
        }
        ctx = self._make_context(learner_profile=profile)
        prompt = build_system_prompt(ctx)
        assert "ADVANCED" in prompt

    def test_directive_appears_before_guidelines_in_prompt(self):
        profile = {
            "directive": "Explanation style: INTERMEDIATE\n- Standard depth.",
            "inferred_level": "intermediate",
        }
        ctx = self._make_context(learner_profile=profile)
        prompt = build_system_prompt(ctx)
        directive_pos  = prompt.index("INTERMEDIATE")
        guidelines_pos = prompt.index("Guidelines:")
        assert directive_pos < guidelines_pos


# ═══════════════════════════════════════════════════════════════════════════════
# 10. TestInjectMemoryIncludesProfile
# ═══════════════════════════════════════════════════════════════════════════════

class TestInjectMemoryIncludesProfile:

    def _mock_base(self):
        return {
            "user_profile": {"learning_stage": "intermediate", "difficulty_preference": None,
                             "top_interests": [], "suppressed_topics": []},
            "research": {"topic": None, "has_deep_research": False, "has_learning_path": False,
                         "has_topic_expansion": False, "has_github_repos": False,
                         "deep_research": None, "learning_path": None,
                         "topic_expansion": None, "github_repos": None},
            "session": {"topic": None, "times_explored": 0, "has_deep_research": False,
                        "has_learning_path": False, "has_topic_expansion": False,
                        "has_github_repos": False, "last_activity_at": None,
                        "recommended_next": []},
        }

    def _mock_profile(self):
        return {
            "inferred_level":  "intermediate",
            "level_score":     0.50,
            "confidence":      0.35,
            "signals":         {"explicit_difficulty": None, "difficulty_distribution": {},
                                "exploration_breadth": 0, "avg_preference_score": 0.0,
                                "session_depth": 0},
            "style":           {"depth": "moderate", "use_analogies": True,
                                "use_code_examples": True, "use_jargon": True, "pace": "normal"},
            "directive":       "Explanation style: INTERMEDIATE\n- Standard depth.",
            "topic_connections": [],
        }

    def test_inject_memory_has_learner_profile_key(self):
        from backend.services.memory_injection_service import inject_memory

        with (
            patch("backend.services.chat_context_service.build_full_context", return_value=self._mock_base()),
            patch("backend.services.memory_injection_service.build_conversation_memory", return_value={}),
            patch("backend.services.memory_injection_service.build_exploration_breadth", return_value={}),
            patch("backend.services.memory_injection_service.build_preference_snapshot", return_value={}),
            patch("backend.services.adaptive_explanation_service.build_learner_profile", return_value=self._mock_profile()),
        ):
            result = inject_memory("session-1", "RAG")

        assert "learner_profile" in result

    def test_inject_memory_learner_profile_correct(self):
        from backend.services.memory_injection_service import inject_memory

        expected = self._mock_profile()
        with (
            patch("backend.services.chat_context_service.build_full_context", return_value=self._mock_base()),
            patch("backend.services.memory_injection_service.build_conversation_memory", return_value={}),
            patch("backend.services.memory_injection_service.build_exploration_breadth", return_value={}),
            patch("backend.services.memory_injection_service.build_preference_snapshot", return_value={}),
            patch("backend.services.adaptive_explanation_service.build_learner_profile", return_value=expected),
        ):
            result = inject_memory("session-1", "RAG")

        assert result["learner_profile"]["inferred_level"] == "intermediate"
        assert result["learner_profile"]["directive"] == expected["directive"]

    def test_inject_memory_passes_session_id_to_profile(self):
        from backend.services.memory_injection_service import inject_memory

        captured = {}
        def mock_profile(session_id=None, user_id=None):
            captured["session_id"] = session_id
            return self._mock_profile()

        with (
            patch("backend.services.chat_context_service.build_full_context", return_value=self._mock_base()),
            patch("backend.services.memory_injection_service.build_conversation_memory", return_value={}),
            patch("backend.services.memory_injection_service.build_exploration_breadth", return_value={}),
            patch("backend.services.memory_injection_service.build_preference_snapshot", return_value={}),
            patch("backend.services.adaptive_explanation_service.build_learner_profile", side_effect=mock_profile),
        ):
            inject_memory("my-session", "LoRA")

        assert captured["session_id"] == "my-session"

    def test_inject_memory_does_not_overwrite_base_keys(self):
        from backend.services.memory_injection_service import inject_memory

        with (
            patch("backend.services.chat_context_service.build_full_context", return_value=self._mock_base()),
            patch("backend.services.memory_injection_service.build_conversation_memory", return_value={}),
            patch("backend.services.memory_injection_service.build_exploration_breadth", return_value={}),
            patch("backend.services.memory_injection_service.build_preference_snapshot", return_value={}),
            patch("backend.services.adaptive_explanation_service.build_learner_profile", return_value=self._mock_profile()),
        ):
            result = inject_memory("session-1", "RAG")

        assert "user_profile" in result
        assert result["user_profile"]["learning_stage"] == "intermediate"
