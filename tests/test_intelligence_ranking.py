"""
Tests for Phase 9.3.2 — Intelligence-Aware Ranking

Covers:
  A: Publisher intelligence identifies known domain
  B: Publisher intelligence returns None for unknown domain
  C: Intent relevance uses project_description (T3)
  D: Signal density high → ranks above equal article with low density (T4)
  E: Source strength serves as tie-breaker (T5)
  F: Publisher diversity penalty for same publisher family (T6)
  G: Story diversity clusters same-angle articles at lower threshold (T7)
  H: Ranking formula signal bonus is bounded (T4+T5)
  I: Ranking audit log is emitted (T9)

Run:
    pytest tests/test_intelligence_ranking.py -v
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.publisher_intelligence_service import enrich_publisher, identify
from backend.services.source_diversity_scorer import diversity_adjustment
from backend.services.similarity_service import deduplicate_by_story


# ── Helpers ────────────────────────────────────────────────────────────────────

def _article(
    title:           str   = "Test Article",
    url:             str   = "https://news.example.org/test",
    content:         str   = "Some content about the topic.",
    source_type:     str   = "news",
    signal_density:  float | None = None,
    source_strength: float | None = None,
    retrieval_query: str   = "",
    perspective:     str   = "",
    publisher_family: str | None = None,
    rank_score:      float = 0.5,
) -> dict:
    a: dict = {
        "title":           title,
        "url":             url,
        "content":         content,
        "source_type":     source_type,
        "retrieval_query": retrieval_query,
        "_perspective":    perspective,
        "_rank_score":     rank_score,
    }
    if signal_density  is not None:
        a["signal_density"]  = signal_density
    if source_strength is not None:
        a["source_strength"] = source_strength
    if publisher_family is not None:
        a["publisher_family"] = publisher_family
    return a


# ── A: Publisher identity — known domain ───────────────────────────────────────

def test_publisher_identifies_imf():
    info = identify("https://www.imf.org/en/Publications/WEO/Issues/2025/04")
    assert info["publisher_name"]   == "IMF"
    assert info["publisher_family"] == "imf"
    assert info["publisher_tier"]   == 1


def test_publisher_identifies_reuters():
    info = identify("https://reuters.com/markets/global/2025-04-01")
    assert info["publisher_name"]   == "Reuters"
    assert info["publisher_family"] == "reuters"
    assert info["publisher_tier"]   == 2


def test_publisher_identifies_wto():
    info = identify("https://www.wto.org/english/news_e/news25_e.htm")
    assert info["publisher_name"]   == "WTO"
    assert info["publisher_tier"]   == 1


def test_publisher_identifies_deepmind():
    info = identify("https://deepmind.google/research/publications/2025")
    assert info["publisher_name"]   == "DeepMind"
    assert info["publisher_family"] == "google_research"


# ── B: Publisher identity — unknown domain ─────────────────────────────────────

def test_publisher_unknown_domain_returns_none():
    info = identify("https://some-random-blog.com/article/123")
    assert info["publisher_name"]   is None
    assert info["publisher_family"] is None
    assert info["publisher_tier"]   is None


def test_publisher_empty_url_returns_none():
    info = identify("")
    assert info["publisher_name"] is None


def test_enrich_publisher_sets_fields():
    a = _article(url="https://arxiv.org/abs/2501.12345")
    enrich_publisher(a)
    assert a["publisher_name"]   == "arXiv"
    assert a["publisher_family"] == "arxiv"
    assert a["publisher_tier"]   == 2


def test_enrich_publisher_idempotent():
    a = _article(url="https://imf.org/paper")
    enrich_publisher(a)
    first_name = a["publisher_name"]
    enrich_publisher(a)  # second call must not change value
    assert a["publisher_name"] == first_name


# ── C: Intent relevance uses project_description (T3) ────────────────────────

def test_intent_match_uses_project_description():
    from backend.services.source_ranker import _intent_match_score

    article_on_topic = _article(
        title="How tariff policy affects global supply chains",
        content="Tariff changes by the WTO and EU are reshaping global trade flows.",
    )
    article_off_topic = _article(
        title="Best recipes for summer barbecue",
        content="Grilling tips and tricks for the perfect burger.",
    )

    project_description = "Understanding international trade policy and tariff impacts"
    keywords = ["trade", "tariff"]

    score_on  = _intent_match_score(article_on_topic,  None, keywords, project_description)
    score_off = _intent_match_score(article_off_topic, None, keywords, project_description)

    assert score_on > score_off, f"on={score_on:.3f} off={score_off:.3f}"


def test_retrieval_query_boosts_intent_match():
    from backend.services.source_ranker import _intent_match_score

    # Article that matches on retrieval_query but not on title
    a = _article(
        title="Market update Q2 2025",
        content="Brief summary.",
        retrieval_query="central bank interest rate monetary policy 2025",
    )
    keywords = ["monetary", "policy", "interest", "rate"]
    # With retrieval_query, reference is richer → better match
    score = _intent_match_score(a, None, keywords, "")
    # Without retrieval_query (blank it)
    a2 = dict(a)
    a2["retrieval_query"] = ""
    score2 = _intent_match_score(a2, None, keywords, "")

    assert score >= score2, f"retrieval_query should not reduce score: {score:.3f} vs {score2:.3f}"


# ── D: Signal density amplifies ranking (T4) ─────────────────────────────────

def test_high_signal_density_boosts_score():
    from backend.services.source_ranker import _learning_score_article

    lc = {"intent_profile": None, "knowledge_state": None, "keywords": ["trade"], "project_description": ""}

    a_rich = _article(
        title="Global trade flows shift as tariffs rise 25%",
        content="The WTO reported a 25% tariff increase in Q2 2025 affecting $400B trade volume.",
        signal_density=0.80,
        source_strength=0.58,
    )
    a_poor = _article(
        title="Global trade flows shift as tariffs rise 25%",
        content="The WTO reported a 25% tariff increase in Q2 2025 affecting $400B trade volume.",
        signal_density=0.10,
        source_strength=0.58,
    )

    bd_rich = _learning_score_article(a_rich, "trade", "default", lc)
    bd_poor = _learning_score_article(a_poor, "trade", "default", lc)

    assert bd_rich["total"] > bd_poor["total"], (
        f"rich={bd_rich['total']} poor={bd_poor['total']}"
    )


# ── E: Source strength as tie-breaker (T5) ───────────────────────────────────

def test_source_strength_acts_as_tiebreaker():
    from backend.services.source_ranker import _learning_score_article

    lc = {"intent_profile": None, "knowledge_state": None, "keywords": ["trade"], "project_description": ""}

    # Same article, different source_strength
    a_gov  = _article(title="Trade policy update", content="Same content." * 20,
                      signal_density=0.40, source_strength=0.92)  # government
    a_blog = _article(title="Trade policy update", content="Same content." * 20,
                      signal_density=0.40, source_strength=0.48)  # company_blog

    bd_gov  = _learning_score_article(a_gov,  "trade", "default", lc)
    bd_blog = _learning_score_article(a_blog, "trade", "default", lc)

    assert bd_gov["total"] > bd_blog["total"], (
        f"gov={bd_gov['total']} blog={bd_blog['total']}"
    )


# ── F: Information diversity — concept novelty (T2 / Phase 9.3.2B) ──────────

def test_same_concept_articles_penalized_regardless_of_publisher():
    # Two "dynamic programming intro" articles already selected (different publishers)
    selected = [
        _article(title="Dynamic programming introduction algorithms",
                 url="https://geeksforgeeks.org/dp-intro",
                 perspective="technology"),
        _article(title="Dynamic programming tutorial beginners guide",
                 url="https://leetcode.com/dp-tutorial",
                 perspective="technology"),
    ]
    # Third DP intro article — same concepts, yet another publisher
    candidate = _article(
        title="Dynamic programming basics memoization guide",
        url="https://towardsdatascience.com/dp-basics",
        perspective="technology",
    )
    candidate["_perspective"] = "technology"

    adj = diversity_adjustment(candidate, selected)
    # Concept overlap should be high (same DP concepts) → penalty
    assert adj <= -0.03, f"Repeated concept articles should be penalized, got {adj}"


def test_different_concept_same_publisher_not_penalized():
    # Same publisher (GeeksForGeeks), very different topics
    selected = [
        _article(title="Dynamic programming memoization tabulation algorithms",
                 url="https://geeksforgeeks.org/dp",
                 perspective="technology"),
    ]
    candidate = _article(
        title="Segment trees range query update binary",
        url="https://geeksforgeeks.org/segment-trees",
        perspective="technology",
    )
    candidate["_perspective"] = "technology"

    adj = diversity_adjustment(candidate, selected)
    # Different concepts despite same publisher → bonus or neutral, never strong penalty
    assert adj >= -0.02, f"Different-concept same-publisher should not be penalized, got {adj}"


# ── G: Story diversity clusters same-angle articles (T7) ─────────────────────

def test_story_dedup_clusters_same_angle_partial_title():
    # Same perspective, >25% title overlap — should cluster even without same query
    a1 = _article(
        title="Federal Reserve raises interest rates by 25 basis points",
        url="https://reuters.com/fed-1",
        perspective="economic_financial",
        rank_score=0.80,
    )
    a2 = _article(
        title="Federal Reserve increases interest rates amid inflation concerns",
        url="https://bloomberg.com/fed-1",
        perspective="economic_financial",
        rank_score=0.70,
    )
    a1["_perspective"] = "economic_financial"
    a2["_perspective"] = "economic_financial"

    result = deduplicate_by_story([a1, a2])
    # Should keep only a1 (higher _rank_score)
    assert len(result) == 1
    assert result[0]["url"] == "https://reuters.com/fed-1"


def test_story_dedup_keeps_different_angles():
    # Titles with low overlap (<25%) AND different perspectives → NOT clustered
    a1 = _article(
        title="Dollar index surges as Fed signals rate pause",
        url="https://reuters.com/dollar-1",
        perspective="economic_financial",
        rank_score=0.80,
    )
    a2 = _article(
        title="Workers demand higher wages amid automation wave",
        url="https://bbc.com/workers-1",
        perspective="social_human",
        rank_score=0.70,
    )
    a1["_perspective"] = "economic_financial"
    a2["_perspective"] = "social_human"

    result = deduplicate_by_story([a1, a2])
    assert len(result) == 2, "Low-overlap titles with different perspectives should not cluster"


# ── H: Signal bonus bounded (T4+T5) ──────────────────────────────────────────

def test_signal_bonus_does_not_exceed_one():
    from backend.services.source_ranker import _learning_score_article

    lc = {"intent_profile": None, "knowledge_state": None, "keywords": ["ai"], "project_description": ""}

    # Maximum possible signal values
    a = _article(
        title="AI breakthrough sets new benchmark on all tasks",
        content=("Researchers at MIT and Stanford achieved state-of-the-art results "
                 "across 15 benchmarks with 70 billion parameters. "
                 "The model was 40% more efficient at $0.002 per token. ") * 5,
        signal_density=1.0,
        source_strength=1.0,
    )

    bd = _learning_score_article(a, "ai", "default", lc)
    assert 0.0 <= bd["total"] <= 1.0, f"total out of range: {bd['total']}"


# ── I: Ranking audit log is emitted (T9) ─────────────────────────────────────

def test_ranking_audit_log_emitted(caplog):
    from backend.services.source_ranker import rank_articles

    articles = [
        {
            "title":   "IMF World Economic Outlook 2025",
            "url":     "https://imf.org/weo/2025",
            "content": "The global economy is expected to grow by 3.2% in 2025 "
                       "according to IMF forecasts. Emerging markets lead growth.",
            "source_type": "government",
            "signal_density": 0.70,
            "source_strength": 0.92,
        },
        {
            "title":   "Trade tensions rise in Q2 2025",
            "url":     "https://reuters.com/trade-tensions",
            "content": "Reuters: New tariffs of 25% on electronics announced by US. "
                       "Global trade volume expected to fall 5% by year end 2025.",
            "source_type": "news",
            "signal_density": 0.55,
            "source_strength": 0.58,
        },
    ]

    with caplog.at_level(logging.INFO, logger="backend.services.source_ranker"):
        result = rank_articles(articles, query="global trade", top_n=5)

    audit_logs = [r for r in caplog.records if "ranking_audit" in r.message]
    assert len(audit_logs) >= 1, "Expected at least one ranking_audit log entry"
