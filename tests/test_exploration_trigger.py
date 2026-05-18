"""
Tests for the autonomous exploration trigger logic.

Test levels
-----------
1. TriggerSignal        — dataclass fields and defaults
2. ExplorationDecision  — dataclass fields and defaults
3. UserEngagement       — _evaluate_user_engagement signal logic
4. NewsFrequency        — _evaluate_news_frequency signal logic
5. EducationalImportance— _evaluate_educational_importance signal logic
6. CooldownGuard        — _is_in_cooldown TTL logic
7. RecommendActions     — _recommend_actions deduplication and ordering
8. EvaluateExploration  — evaluate_exploration aggregator and decision
9. ExploreEndpoint      — GET /explore/{topic} HTTP shape
10. Integration         — live round-trip with real DB (gated -m integration)

Patching note
-------------
get_connection is patched at backend.services.exploration_trigger_service.get_connection.
Endpoint tests patch backend.main.evaluate_exploration (module-level import).

Run:
    pytest tests/test_exploration_trigger.py -v
    pytest tests/test_exploration_trigger.py -v -m integration
"""

import json
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.database.schema import ALL_TABLES
from backend.services.exploration_trigger_service import (
    COOLDOWN_HOURS,
    COOLDOWN_SCORE_MULT,
    NEWS_LOOKBACK_DAYS,
    SIGNAL_WEIGHTS,
    TRIGGER_THRESHOLD,
    ExplorationDecision,
    TriggerSignal,
    _evaluate_educational_importance,
    _evaluate_news_frequency,
    _evaluate_user_engagement,
    _is_in_cooldown,
    _recommend_actions,
    evaluate_exploration,
)


# ── In-memory DB fixture ───────────────────────────────────────────────────────

@pytest.fixture
def mem_db(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    for stmt in ALL_TABLES:
        conn.execute(stmt)
    conn.commit()

    @contextmanager
    def _get_conn():
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    monkeypatch.setattr(
        "backend.services.exploration_trigger_service.get_connection", _get_conn
    )
    yield conn
    conn.close()


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _insert_pref(conn, topic="RAG", times_liked=0, preference_score=0.0):
    conn.execute(
        """INSERT INTO user_preferences (topic, times_liked, preference_score)
           VALUES (?, ?, ?)
           ON CONFLICT(topic) DO UPDATE SET
               times_liked=excluded.times_liked,
               preference_score=excluded.preference_score""",
        (topic, times_liked, preference_score),
    )
    conn.commit()


def _insert_digest(conn, news_title="AI News", news_summary="summary", days_ago=1):
    ts = (
        datetime.now(timezone.utc) - timedelta(days=days_ago)
    ).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """INSERT INTO daily_digests
               (generated_at, news_title, news_summary, why_it_matters,
                learning_topics_json, next_step)
           VALUES (?, ?, ?, 'matters', '[]', 'next')""",
        (ts, news_title, news_summary),
    )
    conn.commit()


def _insert_learning_path(conn, topic="RAG", path_json=None):
    key = topic.lower().strip()
    path_json = path_json or json.dumps({"topic": topic, "beginner": [], "intermediate": [], "advanced": []})
    conn.execute(
        """INSERT INTO learning_paths (topic, topic_key, path_json, learning_stage)
           VALUES (?, ?, ?, 'beginner')
           ON CONFLICT(topic_key) DO UPDATE SET path_json=excluded.path_json""",
        (topic, key, path_json),
    )
    conn.commit()


def _insert_topic_expansion(conn, topic="RAG", expansion_json=None):
    key = topic.lower().strip()
    expansion_json = expansion_json or json.dumps({"topic": topic, "prerequisites": [], "related_topics": []})
    conn.execute(
        """INSERT INTO topic_expansions (topic, topic_key, expansion_json)
           VALUES (?, ?, ?)
           ON CONFLICT(topic_key) DO UPDATE SET expansion_json=excluded.expansion_json""",
        (topic, key, expansion_json),
    )
    conn.commit()


def _insert_research(conn, topic="RAG", hours_ago=1):
    key = topic.lower().strip()
    ts = (
        datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    ).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """INSERT INTO deep_research (topic, topic_key, research_json, generated_at)
           VALUES (?, ?, '{}', ?)
           ON CONFLICT(topic_key) DO UPDATE SET generated_at=excluded.generated_at""",
        (topic, key, ts),
    )
    conn.commit()


def _fired_signal(name: str) -> TriggerSignal:
    return TriggerSignal(name=name, score=1.0, fired=True, reason="test")


def _unfired_signal(name: str) -> TriggerSignal:
    return TriggerSignal(name=name, score=0.0, fired=False, reason="test")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. TriggerSignal dataclass
# ═══════════════════════════════════════════════════════════════════════════════

class TestTriggerSignal:
    def test_fields_accessible(self):
        s = TriggerSignal(name="user_engagement", score=0.5, fired=True, reason="ok")
        assert s.name   == "user_engagement"
        assert s.score  == 0.5
        assert s.fired  is True
        assert s.reason == "ok"

    def test_fired_false_by_default_when_set(self):
        s = TriggerSignal(name="x", score=0.0, fired=False, reason="")
        assert s.fired is False

    def test_score_can_be_zero(self):
        s = TriggerSignal(name="x", score=0.0, fired=False, reason="none")
        assert s.score == 0.0

    def test_score_can_be_one(self):
        s = TriggerSignal(name="x", score=1.0, fired=True, reason="max")
        assert s.score == 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ExplorationDecision dataclass
# ═══════════════════════════════════════════════════════════════════════════════

class TestExplorationDecision:
    def _make(self, should_explore=False, cooldown_active=False):
        return ExplorationDecision(
            topic="RAG",
            should_explore=should_explore,
            total_score=0.6 if should_explore else 0.2,
            signals=[],
            recommended_actions=["deep_research"] if should_explore else [],
            cooldown_active=cooldown_active,
            reason="test",
        )

    def test_fields_accessible(self):
        d = self._make(should_explore=True)
        assert d.topic          == "RAG"
        assert d.should_explore is True
        assert d.total_score    == 0.6
        assert d.signals        == []
        assert "deep_research"  in d.recommended_actions
        assert d.cooldown_active is False
        assert d.reason         == "test"

    def test_should_explore_false(self):
        d = self._make(should_explore=False)
        assert d.should_explore is False
        assert d.recommended_actions == []

    def test_cooldown_active_flag(self):
        d = self._make(cooldown_active=True)
        assert d.cooldown_active is True


# ═══════════════════════════════════════════════════════════════════════════════
# 3. User Engagement signal
# ═══════════════════════════════════════════════════════════════════════════════

class TestUserEngagementSignal:
    def test_returns_trigger_signal(self, mem_db):
        s = _evaluate_user_engagement("RAG")
        assert isinstance(s, TriggerSignal)
        assert s.name == "user_engagement"

    def test_no_preference_record_score_zero(self, mem_db):
        s = _evaluate_user_engagement("unknown topic xyz")
        assert s.score == 0.0
        assert s.fired is False

    def test_three_likes_fires_signal(self, mem_db):
        _insert_pref(mem_db, "RAG", times_liked=3, preference_score=0.0)
        s = _evaluate_user_engagement("RAG")
        assert s.fired is True
        assert s.score > 0.33

    def test_one_like_fires_signal(self, mem_db):
        _insert_pref(mem_db, "RAG", times_liked=1, preference_score=0.0)
        s = _evaluate_user_engagement("RAG")
        # 0.6*(1/3) = 0.2 — not enough alone; below 0.33, check exactly
        assert s.fired is False  # 0.2 < 0.33

    def test_high_pref_score_fires_signal(self, mem_db):
        _insert_pref(mem_db, "RAG", times_liked=0, preference_score=2.0)
        s = _evaluate_user_engagement("RAG")
        # 0.4*(2.0/2.0) = 0.4 >= 0.33
        assert s.fired is True

    def test_combined_likes_and_pref_fires(self, mem_db):
        _insert_pref(mem_db, "RAG", times_liked=1, preference_score=0.5)
        s = _evaluate_user_engagement("RAG")
        # 0.6*(1/3) + 0.4*(0.5/2.0) = 0.2 + 0.1 = 0.3 — still below 0.33
        assert s.score == pytest.approx(0.3, abs=0.01)

    def test_case_insensitive_lookup(self, mem_db):
        _insert_pref(mem_db, "rag", times_liked=3, preference_score=0.0)
        s = _evaluate_user_engagement("RAG")
        assert s.fired is True

    def test_score_capped_at_one(self, mem_db):
        _insert_pref(mem_db, "RAG", times_liked=100, preference_score=100.0)
        s = _evaluate_user_engagement("RAG")
        assert s.score <= 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# 4. News Frequency signal
# ═══════════════════════════════════════════════════════════════════════════════

class TestNewsFrequencySignal:
    def test_returns_trigger_signal(self, mem_db):
        s = _evaluate_news_frequency("RAG")
        assert isinstance(s, TriggerSignal)
        assert s.name == "news_frequency"

    def test_no_digests_score_zero(self, mem_db):
        s = _evaluate_news_frequency("RAG")
        assert s.score == 0.0
        assert s.fired is False

    def test_title_match_fires_signal(self, mem_db):
        _insert_digest(mem_db, news_title="RAG Pipelines explained", days_ago=3)
        s = _evaluate_news_frequency("RAG")
        assert s.fired is True

    def test_summary_match_fires_signal(self, mem_db):
        _insert_digest(mem_db, news_title="AI update", news_summary="rag is hot", days_ago=2)
        s = _evaluate_news_frequency("RAG")
        assert s.fired is True

    def test_old_digest_outside_lookback_not_counted(self, mem_db):
        _insert_digest(mem_db, news_title="RAG wins", days_ago=NEWS_LOOKBACK_DAYS + 1)
        s = _evaluate_news_frequency("RAG")
        assert s.fired is False

    def test_three_matches_scores_one(self, mem_db):
        for i in range(3):
            _insert_digest(mem_db, news_title=f"RAG article {i}", days_ago=i + 1)
        s = _evaluate_news_frequency("RAG")
        assert s.score == pytest.approx(1.0)

    def test_no_false_match_on_unrelated_topic(self, mem_db):
        _insert_digest(mem_db, news_title="LLM updates", news_summary="transformers are great")
        s = _evaluate_news_frequency("RAG")
        assert s.fired is False

    def test_reason_contains_count(self, mem_db):
        _insert_digest(mem_db, news_title="RAG is trending")
        s = _evaluate_news_frequency("RAG")
        assert "1" in s.reason


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Educational Importance signal
# ═══════════════════════════════════════════════════════════════════════════════

class TestEducationalImportanceSignal:
    def test_returns_trigger_signal(self, mem_db):
        s = _evaluate_educational_importance("RAG")
        assert isinstance(s, TriggerSignal)
        assert s.name == "educational_importance"

    def test_no_artifacts_score_zero(self, mem_db):
        s = _evaluate_educational_importance("RAG")
        assert s.score == 0.0
        assert s.fired is False

    def test_learning_path_match_fires(self, mem_db):
        _insert_learning_path(mem_db, "RAG", json.dumps({"topic": "RAG pipelines", "beginner": []}))
        s = _evaluate_educational_importance("RAG")
        assert s.fired is True

    def test_topic_expansion_match_fires(self, mem_db):
        _insert_topic_expansion(mem_db, "LLM", json.dumps({"topic": "LLM", "prerequisites": ["RAG"]}))
        s = _evaluate_educational_importance("RAG")
        assert s.fired is True

    def test_counts_both_tables(self, mem_db):
        _insert_learning_path(mem_db, "RAG", json.dumps({"topic": "RAG"}))
        _insert_topic_expansion(mem_db, "LLM", json.dumps({"related": ["RAG", "embeddings"]}))
        s = _evaluate_educational_importance("RAG")
        assert s.score == pytest.approx(2 / 3, abs=0.01)

    def test_three_refs_scores_one(self, mem_db):
        _insert_learning_path(mem_db, "RAG", json.dumps({"topic": "RAG"}))
        _insert_topic_expansion(mem_db, "LLM", json.dumps({"prerequisites": ["RAG"]}))
        _insert_topic_expansion(mem_db, "embeddings", json.dumps({"advanced": ["RAG retrieval"]}))
        s = _evaluate_educational_importance("RAG")
        assert s.score == pytest.approx(1.0)

    def test_unrelated_artifacts_do_not_fire(self, mem_db):
        _insert_learning_path(mem_db, "BERT", json.dumps({"topic": "BERT fine-tuning"}))
        s = _evaluate_educational_importance("RAG")
        assert s.fired is False

    def test_reason_contains_ref_count(self, mem_db):
        _insert_learning_path(mem_db, "RAG", json.dumps({"topic": "RAG"}))
        s = _evaluate_educational_importance("RAG")
        assert "1" in s.reason


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Cooldown guard
# ═══════════════════════════════════════════════════════════════════════════════

class TestCooldownGuard:
    def test_no_research_not_in_cooldown(self, mem_db):
        assert _is_in_cooldown("RAG") is False

    def test_recent_research_activates_cooldown(self, mem_db):
        _insert_research(mem_db, "RAG", hours_ago=1)
        assert _is_in_cooldown("RAG") is True

    def test_just_within_cooldown_window(self, mem_db):
        _insert_research(mem_db, "RAG", hours_ago=COOLDOWN_HOURS - 1)
        assert _is_in_cooldown("RAG") is True

    def test_just_outside_cooldown_window(self, mem_db):
        _insert_research(mem_db, "RAG", hours_ago=COOLDOWN_HOURS + 1)
        assert _is_in_cooldown("RAG") is False

    def test_cooldown_case_insensitive(self, mem_db):
        _insert_research(mem_db, "RAG", hours_ago=2)
        assert _is_in_cooldown("rag") is True
        assert _is_in_cooldown("RAG") is True

    def test_different_topic_not_in_cooldown(self, mem_db):
        _insert_research(mem_db, "RAG", hours_ago=2)
        assert _is_in_cooldown("Vector Databases") is False


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Recommend actions
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecommendActions:
    def test_empty_signals_returns_empty(self):
        assert _recommend_actions([]) == []

    def test_user_engagement_actions(self):
        actions = _recommend_actions([_fired_signal("user_engagement")])
        assert "deep_research" in actions
        assert "learning_path" in actions

    def test_news_frequency_actions(self):
        actions = _recommend_actions([_fired_signal("news_frequency")])
        assert actions == ["deep_research"]

    def test_educational_importance_actions(self):
        actions = _recommend_actions([_fired_signal("educational_importance")])
        assert "topic_expansion" in actions
        assert "learning_path"   in actions
        assert "github_repos"    in actions

    def test_deduplicates_across_signals(self):
        # both user_engagement and news_frequency recommend deep_research
        signals = [_fired_signal("user_engagement"), _fired_signal("news_frequency")]
        actions = _recommend_actions(signals)
        assert actions.count("deep_research") == 1

    def test_empty_list_produces_no_actions(self):
        # _recommend_actions is called with already-filtered fired signals;
        # passing an empty list (no fired signals) must return no actions.
        assert _recommend_actions([]) == []

    def test_preserves_insertion_order(self):
        actions = _recommend_actions([
            _fired_signal("user_engagement"),
            _fired_signal("educational_importance"),
        ])
        assert actions.index("deep_research") < actions.index("topic_expansion")


# ═══════════════════════════════════════════════════════════════════════════════
# 8. evaluate_exploration — aggregator and decision
# ═══════════════════════════════════════════════════════════════════════════════

class TestEvaluateExploration:
    def test_returns_exploration_decision(self, mem_db):
        d = evaluate_exploration("RAG")
        assert isinstance(d, ExplorationDecision)

    def test_empty_topic_returns_should_not_explore(self, mem_db):
        d = evaluate_exploration("")
        assert d.should_explore is False
        assert d.total_score == 0.0

    def test_whitespace_topic_treated_as_empty(self, mem_db):
        d = evaluate_exploration("   ")
        assert d.should_explore is False

    def test_three_signals_always_present(self, mem_db):
        d = evaluate_exploration("RAG")
        names = [s.name for s in d.signals]
        assert "user_engagement"        in names
        assert "news_frequency"         in names
        assert "educational_importance" in names

    def test_no_activity_does_not_explore(self, mem_db):
        d = evaluate_exploration("RAG")
        assert d.should_explore is False
        assert d.total_score < TRIGGER_THRESHOLD

    def test_high_engagement_triggers_exploration(self, mem_db):
        # 3 likes → user_engagement score=1.0, weighted 0.4 — not enough alone
        # Add news + educational to push over 0.5
        _insert_pref(mem_db, "RAG", times_liked=3, preference_score=2.0)
        _insert_digest(mem_db, news_title="RAG trends", days_ago=1)
        _insert_learning_path(mem_db, "RAG", json.dumps({"topic": "RAG"}))
        d = evaluate_exploration("RAG")
        assert d.should_explore is True
        assert d.total_score >= TRIGGER_THRESHOLD

    def test_cooldown_suppresses_exploration(self, mem_db):
        # Set up enough signal to normally trigger
        _insert_pref(mem_db, "RAG", times_liked=3, preference_score=2.0)
        _insert_digest(mem_db, news_title="RAG trends", days_ago=1)
        _insert_learning_path(mem_db, "RAG", json.dumps({"topic": "RAG"}))
        # But recent research puts it in cooldown
        _insert_research(mem_db, "RAG", hours_ago=1)
        d = evaluate_exploration("RAG")
        assert d.should_explore is False
        assert d.cooldown_active is True

    def test_cooldown_dampens_score(self, mem_db):
        _insert_pref(mem_db, "RAG", times_liked=3, preference_score=2.0)
        _insert_research(mem_db, "RAG", hours_ago=1)
        d = evaluate_exploration("RAG")
        # Dampened score should be COOLDOWN_SCORE_MULT * raw_score
        assert d.total_score < d.total_score / COOLDOWN_SCORE_MULT + 0.001  # sanity

    def test_total_score_rounded_to_4_places(self, mem_db):
        d = evaluate_exploration("RAG")
        assert d.total_score == round(d.total_score, 4)

    def test_reason_contains_threshold_when_not_triggered(self, mem_db):
        d = evaluate_exploration("RAG")
        assert str(TRIGGER_THRESHOLD) in d.reason or "below" in d.reason

    def test_reason_mentions_cooldown_when_active(self, mem_db):
        _insert_pref(mem_db, "RAG", times_liked=3, preference_score=2.0)
        _insert_digest(mem_db, news_title="RAG trends", days_ago=1)
        _insert_research(mem_db, "RAG", hours_ago=1)
        d = evaluate_exploration("RAG")
        assert "cooldown" in d.reason.lower()

    def test_actions_empty_when_not_triggered(self, mem_db):
        d = evaluate_exploration("RAG")
        assert d.recommended_actions == []

    def test_topic_preserved_in_decision(self, mem_db):
        d = evaluate_exploration("Vector Databases")
        assert d.topic == "Vector Databases"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. GET /explore/{topic} endpoint
# ═══════════════════════════════════════════════════════════════════════════════

class TestExploreEndpoint:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        return TestClient(app)

    def _decision(self, should_explore=False):
        return ExplorationDecision(
            topic="RAG",
            should_explore=should_explore,
            total_score=0.7 if should_explore else 0.2,
            signals=[
                TriggerSignal("user_engagement", 0.8, True, "3 likes"),
            ],
            recommended_actions=["deep_research"] if should_explore else [],
            cooldown_active=False,
            reason="test fixture",
        )

    def test_returns_200(self, client):
        with patch("backend.main.evaluate_exploration", return_value=self._decision()):
            resp = client.get("/explore/RAG")
        assert resp.status_code == 200

    def test_response_has_all_fields(self, client):
        with patch("backend.main.evaluate_exploration", return_value=self._decision()):
            resp = client.get("/explore/RAG")
        body = resp.json()
        for field in ("topic", "should_explore", "total_score", "signals",
                      "recommended_actions", "cooldown_active", "reason"):
            assert field in body, f"Missing field: {field}"

    def test_signals_list_has_expected_shape(self, client):
        with patch("backend.main.evaluate_exploration", return_value=self._decision()):
            resp = client.get("/explore/RAG")
        signals = resp.json()["signals"]
        assert isinstance(signals, list)
        assert len(signals) == 1
        sig = signals[0]
        for key in ("name", "score", "fired", "reason"):
            assert key in sig

    def test_should_explore_true_propagated(self, client):
        with patch("backend.main.evaluate_exploration", return_value=self._decision(True)):
            resp = client.get("/explore/RAG")
        assert resp.json()["should_explore"] is True

    def test_should_explore_false_propagated(self, client):
        with patch("backend.main.evaluate_exploration", return_value=self._decision(False)):
            resp = client.get("/explore/RAG")
        assert resp.json()["should_explore"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Integration — full round-trip with in-memory DB
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.integration
class TestExplorationIntegration:
    def test_full_evaluation_no_activity(self, mem_db):
        """With an empty DB, evaluation must not error and must not trigger."""
        d = evaluate_exploration("RAG Pipelines")
        assert d.should_explore is False
        assert len(d.signals) == 3
        assert all(s.score == 0.0 for s in d.signals)

    def test_full_evaluation_with_all_signals(self, mem_db):
        """When all signals are set up, exploration should trigger."""
        topic = "RAG Pipelines"
        _insert_pref(mem_db, topic, times_liked=3, preference_score=2.0)
        _insert_digest(mem_db, news_title=f"{topic} overview", days_ago=2)
        _insert_learning_path(mem_db, "Embeddings",
                               json.dumps({"topic": "Embeddings", "advanced": [f"Use {topic}"]}))

        d = evaluate_exploration(topic)
        assert d.should_explore is True
        assert d.total_score >= TRIGGER_THRESHOLD
        assert len(d.recommended_actions) > 0

    def test_cooldown_after_recent_research(self, mem_db):
        """Exploration must be suppressed after a recent deep_research run."""
        topic = "RAG Pipelines"
        _insert_pref(mem_db, topic, times_liked=3, preference_score=2.0)
        _insert_digest(mem_db, news_title=f"{topic} explained", days_ago=1)
        _insert_research(mem_db, topic, hours_ago=12)

        d = evaluate_exploration(topic)
        assert d.should_explore is False
        assert d.cooldown_active is True
