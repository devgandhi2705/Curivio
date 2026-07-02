"""
Tests for the Phase 6.3 three-bucket learning scorer in source_ranker.py.

Formula: FinalScore = 0.6 * intent_match + 0.3 * topic_match + 0.1 * freshness

Run:
    pytest tests/test_source_ranker_learning.py -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.source_ranker import (
    _LEARNING_WEIGHTS,
    _TOPIC_SUBWEIGHTS,
    _intent_match_score,
    _learning_score_article,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

STUDENT_PROFILE = {
    "persona":          "Economics Student",
    "goal":             "Understand globalization for CBSE board exams",
    "industry_context": "Academic",
    "primary_focus":    "Trade theory and policy frameworks",
    "search_lens":      "Educational",
    "intent_summary":   "A student focused on exam-ready concepts in trade and economics.",
}

FOUNDER_PROFILE = {
    "persona":          "Startup Founder",
    "goal":             "Navigate international expansion successfully",
    "industry_context": "Startup",
    "primary_focus":    "Market entry strategy and cross-border regulatory risk",
    "search_lens":      "Business Strategy",
    "intent_summary":   "A founder taking a SaaS product global — needs market entry intel.",
}

WTO_ARTICLE = {
    "title":   "History of WTO and global trade policy frameworks",
    "content": "The World Trade Organization shapes international trade rules and policy. "
               "Comparative advantage theory underpins WTO agreements. "
               "Trade liberalization and tariff reduction are core WTO policy mechanisms.",
    "url":     "https://worldbank.org/trade/wto-history",
}

SAAS_ARTICLE = {
    "title":   "How SaaS startups expand globally",
    "content": "SaaS startups entering international markets must navigate regulatory risk, "
               "market entry strategy, cross-border compliance, and currency exposure. "
               "Successful global expansion requires local partnerships and GTM planning.",
    "url":     "https://hbr.org/saas-global-expansion",
}

STUDENT_CTX = {
    "intent_profile":    STUDENT_PROFILE,
    "knowledge_state":   None,
    "keywords":          ["globalization", "trade", "WTO"],
}

FOUNDER_CTX = {
    "intent_profile":    FOUNDER_PROFILE,
    "knowledge_state":   None,
    "keywords":          ["globalization", "startup", "market entry"],
}


# ── Weight integrity ──────────────────────────────────────────────────────────

class TestWeightIntegrity:
    def test_learning_weights_sum_to_one(self):
        total = sum(_LEARNING_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9, f"_LEARNING_WEIGHTS sums to {total}"

    def test_topic_subweights_sum_to_one(self):
        total = sum(_TOPIC_SUBWEIGHTS.values())
        assert abs(total - 1.0) < 1e-9, f"_TOPIC_SUBWEIGHTS sums to {total}"

    def test_intent_match_weight_is_sixty_percent(self):
        assert _LEARNING_WEIGHTS["intent_match"] == 0.60

    def test_topic_match_weight_is_thirty_percent(self):
        assert _LEARNING_WEIGHTS["topic_match"] == 0.30

    def test_freshness_weight_is_ten_percent(self):
        assert _LEARNING_WEIGHTS["freshness"] == 0.10

    def test_intent_is_dominant_bucket(self):
        assert _LEARNING_WEIGHTS["intent_match"] > _LEARNING_WEIGHTS["topic_match"]
        assert _LEARNING_WEIGHTS["intent_match"] > _LEARNING_WEIGHTS["freshness"]


# ── Persona differentiation ───────────────────────────────────────────────────

class TestPersonaDifferentiation:
    """Same topic, different persona → different intent_match scores."""

    def test_student_scores_wto_higher_than_saas(self):
        score_wto  = _intent_match_score(WTO_ARTICLE,  STUDENT_PROFILE, ["globalization", "trade"])
        score_saas = _intent_match_score(SAAS_ARTICLE, STUDENT_PROFILE, ["globalization", "trade"])
        assert score_wto > score_saas, (
            f"Student: WTO={score_wto:.3f} should exceed SaaS={score_saas:.3f}"
        )

    def test_founder_scores_saas_higher_than_wto(self):
        score_saas = _intent_match_score(SAAS_ARTICLE, FOUNDER_PROFILE, ["globalization", "startup"])
        score_wto  = _intent_match_score(WTO_ARTICLE,  FOUNDER_PROFILE, ["globalization", "startup"])
        assert score_saas > score_wto, (
            f"Founder: SaaS={score_saas:.3f} should exceed WTO={score_wto:.3f}"
        )

    def test_same_article_different_personas_yield_different_scores(self):
        student_score = _intent_match_score(SAAS_ARTICLE, STUDENT_PROFILE, [])
        founder_score = _intent_match_score(SAAS_ARTICLE, FOUNDER_PROFILE, [])
        assert student_score != founder_score

    def test_no_profile_does_not_crash(self):
        score = _intent_match_score(WTO_ARTICLE, None, ["globalization"])
        assert 0.0 <= score <= 1.0

    def test_empty_profile_does_not_crash(self):
        score = _intent_match_score(WTO_ARTICLE, {}, [])
        assert 0.0 <= score <= 1.0


# ── Score range ───────────────────────────────────────────────────────────────

class TestScoreRange:
    def test_student_wto_total_in_range(self):
        result = _learning_score_article(WTO_ARTICLE, "globalization", "economics", STUDENT_CTX)
        assert 0.0 <= result["total"] <= 1.0

    def test_founder_saas_total_in_range(self):
        result = _learning_score_article(SAAS_ARTICLE, "global expansion", "business", FOUNDER_CTX)
        assert 0.0 <= result["total"] <= 1.0

    def test_all_sub_scores_in_range(self):
        result = _learning_score_article(WTO_ARTICLE, "globalization", "economics", STUDENT_CTX)
        for field in ("intent_match", "topic_match", "learning_continuity",
                      "novelty", "authority", "freshness", "practical_value", "perspective"):
            assert 0.0 <= result[field] <= 1.0, f"{field}={result[field]} out of range"


# ── Formula correctness ───────────────────────────────────────────────────────

class TestFormula:
    def test_total_equals_weighted_sum_of_three_buckets(self):
        """total must equal exactly 0.6*intent + 0.3*topic + 0.1*freshness."""
        result = _learning_score_article(WTO_ARTICLE, "trade policy", "economics", STUDENT_CTX)
        expected = min(1.0, round(
            result["intent_match"] * 0.60 +
            result["topic_match"]  * 0.30 +
            result["freshness"]    * 0.10,
            3,
        ))
        assert abs(result["total"] - expected) < 0.001, (
            f"total={result['total']} expected={expected}"
        )

    def test_intent_contribution_largest_with_high_match(self):
        """When intent_match is high, its weighted contribution must exceed topic's."""
        result = _learning_score_article(WTO_ARTICLE, "trade policy", "economics", STUDENT_CTX)
        intent_contribution = result["intent_match"] * _LEARNING_WEIGHTS["intent_match"]
        topic_contribution  = result["topic_match"]  * _LEARNING_WEIGHTS["topic_match"]
        # This holds unless intent_match is very low and topic_match very high
        # For a well-matched article+profile, intent dominates
        if result["intent_match"] > 0.3:
            assert intent_contribution >= topic_contribution

    def test_breakdown_contains_all_required_fields(self):
        result = _learning_score_article(WTO_ARTICLE, "globalization", "economics", STUDENT_CTX)
        required = {
            "intent_match", "topic_match", "learning_continuity", "novelty",
            "authority", "freshness", "practical_value", "perspective", "total",
        }
        assert required == set(result.keys()), (
            f"Missing: {required - set(result.keys())}, Extra: {set(result.keys()) - required}"
        )

    def test_high_intent_match_raises_total(self):
        """An article that strongly matches the intent profile must score higher than one that doesn't."""
        student_wto    = _learning_score_article(WTO_ARTICLE,  "globalization", "economics", STUDENT_CTX)
        student_saas   = _learning_score_article(SAAS_ARTICLE, "globalization", "economics", STUDENT_CTX)
        assert student_wto["total"] > student_saas["total"], (
            f"WTO total={student_wto['total']:.3f} should exceed SaaS={student_saas['total']:.3f} for student"
        )
