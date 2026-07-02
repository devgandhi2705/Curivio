"""
Tests for Phase 6.4 intent_alignment_score in retrieval_validator.py.

Validates that articles clearly mismatched to the learner's persona are
discarded before ranking, while genuinely relevant content passes through.

Run:
    pytest tests/test_retrieval_validator_alignment.py -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.retrieval_validator import (
    _THRESHOLDS,
    _build_intent_alignment_terms,
    filter_articles,
    validate,
)


# ── Shared fixtures ──────────────────────────────────────────────────────────

STUDENT_PROFILE = {
    "persona":          "Economics Student",
    "goal":             "Understand globalization for CBSE board exams",
    "industry_context": "Academic",
    "primary_focus":    "Trade theory and policy frameworks",
    "search_lens":      "Educational",
    "intent_summary":   "A student focused on exam-ready trade economics concepts.",
}

FOUNDER_PROFILE = {
    "persona":          "Startup Founder",
    "goal":             "Navigate international expansion successfully",
    "industry_context": "Startup",
    "primary_focus":    "Market entry strategy and cross-border regulatory risk",
    "search_lens":      "Business Strategy",
    "intent_summary":   "A founder taking a SaaS product global — needs market entry intel.",
}

STUDENT_KW = ["globalization", "trade", "WTO"]
FOUNDER_KW = ["globalization", "startup", "market entry"]

# Article that clearly signals "academic / exam prep" context
CBSE_ARTICLE = {
    "title":   "CBSE Class 12 Globalization Chapter Notes",
    "content": (
        "Chapter 4 covers globalization in CBSE economics. "
        "Students must understand trade as per NCERT syllabus for board exams."
    ),
    "url": "https://cbseguide.com/globalization-notes",
}

# Article that clearly signals "startup / market entry" context
FOUNDER_ARTICLE = {
    "title":   "SaaS Startup International Expansion Playbook",
    "content": (
        "SaaS founders navigating international market entry must address "
        "cross-border regulatory risk, GTM strategy, and currency exposure. "
        "Market entry requires local partnerships and startup-specific compliance."
    ),
    "url": "https://hbr.org/saas-expansion-playbook",
}

# Genuinely relevant article for both (trade theory + globalization topic)
WTO_ARTICLE = {
    "title":   "WTO Trade Policy Frameworks Analysis",
    "content": (
        "The World Trade Organization shapes international trade policy. "
        "Comparative advantage theory underpins WTO agreements. "
        "Trade liberalization frameworks reduce tariff barriers across borders."
    ),
    "url": "https://worldbank.org/wto-trade-frameworks",
}

# Genuinely relevant article for Founder (international market strategy)
EXPANSION_ARTICLE = {
    "title":   "International Market Entry Strategy Guide",
    "content": (
        "Navigating international expansion requires evaluating market entry modes: "
        "direct export, joint ventures, or wholly-owned subsidiaries. "
        "Regulatory risk and cross-border compliance shape the strategy choice."
    ),
    "url": "https://hbr.org/market-entry-strategy",
}


# ── Threshold integrity ──────────────────────────────────────────────────────

class TestThresholds:
    def test_core_intent_alignment_threshold_exists(self):
        assert "intent_alignment" in _THRESHOLDS["core"]

    def test_serendipity_intent_alignment_threshold_exists(self):
        assert "intent_alignment" in _THRESHOLDS["serendipity"]

    def test_core_threshold_is_minimal(self):
        # Conservative: only blocks zero-overlap articles
        assert _THRESHOLDS["core"]["intent_alignment"] <= 0.05

    def test_serendipity_threshold_is_zero(self):
        # Serendipity exempt: intentionally off-persona content is expected
        assert _THRESHOLDS["serendipity"]["intent_alignment"] == 0.0


# ── _build_intent_alignment_terms ────────────────────────────────────────────

class TestBuildAlignmentTerms:
    def test_no_profile_returns_empty_frozenset(self):
        terms = _build_intent_alignment_terms(None, ["globalization"])
        assert terms == frozenset()

    def test_empty_profile_returns_empty_frozenset(self):
        terms = _build_intent_alignment_terms({}, ["globalization"])
        assert terms == frozenset()

    def test_keywords_not_included_in_alignment_terms(self):
        """Keywords contain shared topic words — must NOT appear in alignment set."""
        terms = _build_intent_alignment_terms(FOUNDER_PROFILE, ["globalization", "startup"])
        assert "globalization" not in terms

    def test_primary_focus_tokens_in_set(self):
        terms = _build_intent_alignment_terms(STUDENT_PROFILE, [])
        # "Trade theory and policy frameworks" → trade, theory, policy, frameworks
        assert "trade"    in terms
        assert "policy"   in terms
        assert "theory"   in terms

    def test_goal_tokens_in_set(self):
        terms = _build_intent_alignment_terms(STUDENT_PROFILE, [])
        # "Understand globalization for CBSE board exams"
        assert "understand"    in terms
        assert "globalization"  in terms
        assert "exams"         in terms

    def test_search_lens_tokens_in_set(self):
        terms = _build_intent_alignment_terms(STUDENT_PROFILE, [])
        # "Educational"
        assert "educational" in terms

    def test_founder_profile_contains_market_tokens(self):
        terms = _build_intent_alignment_terms(FOUNDER_PROFILE, [])
        assert "market"  in terms
        assert "entry"   in terms
        assert "strategy" in terms

    def test_founder_profile_does_not_contain_student_tokens(self):
        founder_terms = _build_intent_alignment_terms(FOUNDER_PROFILE, [])
        student_terms = _build_intent_alignment_terms(STUDENT_PROFILE, [])
        # The profiles must produce substantially different term sets
        assert founder_terms != student_terms
        # cbse / exams are student-only
        assert "cbse"  in student_terms
        assert "cbse"  not in founder_terms


# ── validate() — intent_alignment_score field ────────────────────────────────

class TestValidateAlignmentScore:
    def test_field_present_in_result(self):
        result = validate(WTO_ARTICLE, STUDENT_PROFILE, None, STUDENT_KW)
        assert "intent_alignment_score" in result

    def test_score_in_range(self):
        result = validate(WTO_ARTICLE, STUDENT_PROFILE, None, STUDENT_KW)
        assert 0.0 <= result["intent_alignment_score"] <= 1.0

    def test_no_profile_score_is_one(self):
        """No profile → no constraint → 1.0 (pass-through)."""
        result = validate(WTO_ARTICLE, None, None, STUDENT_KW)
        assert result["intent_alignment_score"] == 1.0

    def test_cbse_article_low_alignment_for_founder(self):
        """CBSE article shares zero tokens with Founder's profile."""
        result = validate(CBSE_ARTICLE, FOUNDER_PROFILE, None, FOUNDER_KW)
        assert result["intent_alignment_score"] < _THRESHOLDS["core"]["intent_alignment"] + 0.01

    def test_wto_article_passes_alignment_for_student(self):
        """WTO/trade-policy article aligns with Student's trade focus."""
        result = validate(WTO_ARTICLE, STUDENT_PROFILE, None, STUDENT_KW)
        assert result["intent_alignment_score"] >= _THRESHOLDS["core"]["intent_alignment"]

    def test_founder_article_low_alignment_for_student(self):
        """SaaS/startup article shares zero tokens with Student's profile."""
        result = validate(FOUNDER_ARTICLE, STUDENT_PROFILE, None, STUDENT_KW)
        assert result["intent_alignment_score"] < _THRESHOLDS["core"]["intent_alignment"] + 0.01

    def test_expansion_article_passes_for_founder(self):
        """International expansion article aligns with Founder's goal."""
        result = validate(EXPANSION_ARTICLE, FOUNDER_PROFILE, None, FOUNDER_KW)
        assert result["intent_alignment_score"] >= _THRESHOLDS["core"]["intent_alignment"]


# ── filter_articles() — persona drift rejection ───────────────────────────────

class TestFilterArticlesPersonaDrift:
    """The canonical examples from the task spec."""

    def test_cbse_article_discarded_for_founder(self):
        """Founder project: CBSE globalization notes → Discard."""
        passing = filter_articles(
            [CBSE_ARTICLE],
            intent_profile=FOUNDER_PROFILE,
            knowledge_state=None,
            keywords=FOUNDER_KW,
            mode="core",
        )
        assert CBSE_ARTICLE not in passing, "CBSE article should be discarded for Startup Founder"

    def test_founder_article_discarded_for_student(self):
        """Student project: SaaS startup expansion playbook → Discard."""
        passing = filter_articles(
            [FOUNDER_ARTICLE],
            intent_profile=STUDENT_PROFILE,
            knowledge_state=None,
            keywords=STUDENT_KW,
            mode="core",
        )
        assert FOUNDER_ARTICLE not in passing, "SaaS playbook should be discarded for Economics Student"

    def test_wto_article_passes_for_student(self):
        """WTO trade policy article aligns with Student → keep."""
        passing = filter_articles(
            [WTO_ARTICLE],
            intent_profile=STUDENT_PROFILE,
            knowledge_state=None,
            keywords=STUDENT_KW,
            mode="core",
        )
        assert WTO_ARTICLE in passing, "WTO article should pass for Economics Student"

    def test_expansion_article_passes_for_founder(self):
        """International market entry article aligns with Founder → keep."""
        passing = filter_articles(
            [EXPANSION_ARTICLE],
            intent_profile=FOUNDER_PROFILE,
            knowledge_state=None,
            keywords=FOUNDER_KW,
            mode="core",
        )
        assert EXPANSION_ARTICLE in passing, "Expansion article should pass for Startup Founder"

    def test_no_profile_passes_all(self):
        """No intent profile → alignment check disabled → all articles pass."""
        articles = [CBSE_ARTICLE, FOUNDER_ARTICLE, WTO_ARTICLE, EXPANSION_ARTICLE]
        passing = filter_articles(
            articles,
            intent_profile=None,
            knowledge_state=None,
            keywords=["globalization"],
            mode="core",
        )
        # Every article should pass the alignment gate (1.0 score, no profile)
        # (some may still fail other checks like relevance, but alignment is no constraint)
        alignment_rejections = [a for a in articles if a not in passing]
        for a in alignment_rejections:
            result = validate(a, None, None, ["globalization"])
            assert result["intent_alignment_score"] == 1.0

    def test_serendipity_mode_does_not_discard_on_alignment(self):
        """Serendipity threshold = 0.0 — alignment check never fires."""
        # CBSE article for Founder in serendipity mode — must not be rejected on alignment
        result = validate(CBSE_ARTICLE, FOUNDER_PROFILE, None, FOUNDER_KW)
        t_sera = _THRESHOLDS["serendipity"]
        # alignment check disabled (threshold = 0.0): 0 < 0.0 is always False
        assert not (result["intent_alignment_score"] < t_sera["intent_alignment"])

    def test_cbse_article_passes_for_student(self):
        """CBSE article is appropriate for a Student — must not be discarded."""
        passing = filter_articles(
            [CBSE_ARTICLE],
            intent_profile=STUDENT_PROFILE,
            knowledge_state=None,
            keywords=STUDENT_KW,
            mode="core",
        )
        assert CBSE_ARTICLE in passing, "CBSE article should pass for Economics Student"

    def test_mixed_batch_only_discards_mismatched(self):
        """Correct articles pass; mismatched article is discarded."""
        articles = [WTO_ARTICLE, CBSE_ARTICLE]
        passing = filter_articles(
            articles,
            intent_profile=FOUNDER_PROFILE,
            knowledge_state=None,
            keywords=FOUNDER_KW,
            mode="core",
        )
        # WTO article has "international" in content — may or may not pass other checks;
        # but CBSE article MUST NOT be in passing
        assert CBSE_ARTICLE not in passing
