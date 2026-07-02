"""
Tests for Phase 9.3.4F — Package Validation Service.

Run: python -m pytest backend/tests/test_package_validation_service.py -v
"""

import pytest
from unittest.mock import patch, MagicMock

from backend.services.package_validation_service import (
    audit_duplicate_concepts,
    audit_narrative_consistency,
    audit_grounding,
    audit_curiosity_relevance,
    audit_synthesis_quality,
    validate_package,
    PackageHealthReport,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _card(
    i: int,
    title: str | None = None,
    summary: str | None = None,
    frame: str = "INVESTIGATIVE",
    difficulty: str = "intermediate",
    url: str | None = None,
    ctype: str = "news",
) -> dict:
    return {
        "id":              f"card-{i}",
        "content_type":    ctype,
        "title":           title or f"Card {i}: Neural Networks Scale Rapidly In 2025",
        "summary":         summary or f"Summary of card {i} covering machine learning developments.",
        "category":        "Machine Learning",
        "narrative_frame": frame,
        "difficulty":      difficulty,
        "primary_source":  {"title": f"Source {i}", "url": url or f"https://example.com/source-{i}"},
    }


def _allowed(cards: list[dict]) -> frozenset:
    return frozenset(
        c["primary_source"]["url"] for c in cards if c.get("primary_source")
    )


def _package(insights: list[dict], curiosity: list[dict] | None = None, **meta) -> dict:
    return {
        "insights":          insights,
        "curiosity_insights": curiosity or [],
        "package_headline":  meta.get("package_headline", ""),
        "learning_thread":   meta.get("learning_thread",  ""),
        "action_item":       meta.get("action_item",      ""),
    }


# ── A: Duplicate concepts ─────────────────────────────────────────────────────

def test_audit_duplicate_concepts_detects_near_identical_cards():
    """Two cards with same title/summary should be flagged as duplicates."""
    shared_title   = "OpenAI Releases GPT-5 With Major Performance Improvements"
    shared_summary = "OpenAI has released GPT-5, offering significant improvements in reasoning and performance."
    cards = [
        _card(1, title=shared_title, summary=shared_summary),
        _card(2, title=shared_title, summary=shared_summary),  # exact duplicate
        _card(3),  # unique card
    ]
    result = audit_duplicate_concepts(cards)
    assert result.duplicate_count >= 1
    assert result.score < 2.0


# ── B: Narrative regression ───────────────────────────────────────────────────

def test_audit_narrative_consistency_flags_dominant_frame():
    """Frame used in >60% of cards should fail diversity check."""
    cards = [_card(i, frame="CONTROVERSY") for i in range(1, 6)]
    result = audit_narrative_consistency(cards, "intermediate")
    assert not result.frame_diversity_ok
    assert result.score < 2.0


# ── C: Fabricated URL ─────────────────────────────────────────────────────────

def test_audit_grounding_flags_fabricated_url():
    """Card with URL not in allowed set should be counted as fabricated."""
    real_card    = _card(1, url="https://example.com/real-article")
    fake_card    = _card(2, url="https://hallucinated.com/fake-article")
    allowed      = frozenset(["https://example.com/real-article"])
    pkg          = _package([real_card, fake_card])
    result       = audit_grounding(pkg, allowed)
    assert result.fabricated_count >= 1
    assert "https://hallucinated.com/fake-article" in result.fabricated_urls
    assert result.score < 2.0


# ── D: Duplicate primary source ───────────────────────────────────────────────

def test_audit_grounding_flags_duplicate_primary_url():
    """Two cards sharing the same primary source URL should be detected."""
    shared_url = "https://example.com/shared-source"
    cards      = [
        _card(1, url=shared_url),
        _card(2, url=shared_url),  # same primary source
        _card(3, url="https://example.com/different"),
    ]
    allowed = frozenset([shared_url, "https://example.com/different"])
    pkg     = _package(cards)
    result  = audit_grounding(pkg, allowed)
    assert result.duplicate_primary_count >= 1
    assert result.score < 2.0


# ── E: Unrelated curiosity ────────────────────────────────────────────────────

def test_audit_curiosity_relevance_flags_unrelated_cards():
    """Curiosity cards with no overlap with learning topics should be flagged."""
    curiosity_cards = [
        # Explicit inline to avoid the "Machine Learning" default category
        {"id": "cu1", "content_type": "curiosity",
         "title": "Ancient Roman Cooking Techniques",
         "summary": "Historical recipes from antiquity.",
         "category": "History"},
        {"id": "cu2", "content_type": "curiosity",
         "title": "Knitting Patterns For Beginners",
         "summary": "Basic yarn craft tutorial.",
         "category": "Crafts"},
    ]
    result = audit_curiosity_relevance(
        curiosity_cards,
        learning_topics=["machine learning", "neural networks", "deep learning"],
        keywords=["pytorch", "transformers"],
        project_name="AI Research",
    )
    assert result.relevant_count < result.curiosity_count
    assert len(result.irrelevant_topics) > 0
    assert result.score < 2.0


# ── F: Generic headline ───────────────────────────────────────────────────────

def test_audit_synthesis_quality_flags_generic_headline():
    """Headline with no words from card content should fail."""
    cards    = [_card(i) for i in range(1, 4)]
    headline = "Today's Roundup"   # no content words matching cards
    result   = audit_synthesis_quality(headline, "Thread about learning.", "Explore resources.", cards)
    assert not result.headline_ok


# ── G: Generic action item ────────────────────────────────────────────────────

def test_audit_synthesis_quality_flags_generic_action_item():
    """Action item with no words from card content should fail."""
    cards  = [_card(i, title="Transformer Architecture Explained In Detail") for i in range(1, 4)]
    result = audit_synthesis_quality(
        "Transformers dominate NLP research today.",
        "Architecture breakthroughs changed deep learning.",
        "Check it out.",  # generic — no content words
        cards,
    )
    assert not result.action_ok


# ── H: Healthy package ────────────────────────────────────────────────────────

_HEALTHY_CARDS = [
    {"id": "h1", "content_type": "news", "title": "OpenAI Launches Enterprise GPT Platform",
     "summary": "OpenAI released enterprise tooling for corporate reasoning automation.",
     "category": "Generative Models", "narrative_frame": "INVESTIGATIVE", "difficulty": "intermediate",
     "primary_source": {"title": "TechCrunch", "url": "https://techcrunch.com/h1"}},
    {"id": "h2", "content_type": "news", "title": "DeepMind Protein Folding Accuracy Reaches Record",
     "summary": "DeepMind published protein structure prediction achieving accuracy for drug discovery.",
     "category": "Biotechnology", "narrative_frame": "MECHANISM", "difficulty": "intermediate",
     "primary_source": {"title": "Nature", "url": "https://nature.com/h2"}},
    {"id": "h3", "content_type": "news", "title": "Semiconductor Supply Faces Geopolitical Bottleneck",
     "summary": "Taiwan geopolitics create chip manufacturing delays affecting electronics supply chain.",
     "category": "Geopolitics", "narrative_frame": "CONTROVERSY", "difficulty": "intermediate",
     "primary_source": {"title": "Bloomberg", "url": "https://bloomberg.com/h3"}},
    {"id": "h4", "content_type": "news", "title": "Battery Costs Drop Below Profitability Threshold",
     "summary": "Lithium prices fell below the threshold making electric vehicles profitable without subsidies.",
     "category": "Clean Energy", "narrative_frame": "TREND", "difficulty": "intermediate",
     "primary_source": {"title": "WSJ", "url": "https://wsj.com/h4"}},
    {"id": "h5", "content_type": "news", "title": "Quantum Startup Demonstrates Practical Error Correction",
     "summary": "IonQ demonstrated quantum error correction reducing decoherence in physical qubit experiments.",
     "category": "Quantum Computing", "narrative_frame": "CONTRAST", "difficulty": "intermediate",
     "primary_source": {"title": "MIT Review", "url": "https://technologyreview.com/h5"}},
]


def test_validate_package_healthy():
    """Well-formed package with clean distinct cards should score >= 8.0."""
    cards = _HEALTHY_CARDS
    pkg   = _package(
        cards,
        package_headline = "OpenAI Enterprise Launch Signals Generative Reasoning Transformation",
        learning_thread  = "DeepMind protein folding and quantum error correction breakthroughs reshape industries. Q: what drives acceleration?",
        action_item      = "INVESTIGATE — compare OpenAI enterprise deployment against DeepMind research publication strategy.",
    )
    allowed = frozenset(c["primary_source"]["url"] for c in cards)
    report  = validate_package(
        raw_package     = pkg,
        allowed_urls    = allowed,
        keywords        = ["neural networks", "machine learning", "deep learning"],
        learning_topics = ["generative models", "biotechnology", "quantum computing"],
        difficulty      = "intermediate",
        project_name    = "Technology Research",
    )
    assert isinstance(report, PackageHealthReport)
    assert report.overall_score >= 8.0, (
        f"Expected >=8 but got {report.overall_score}. "
        f"grounding={report.grounding_score} narr={report.narrative_score} "
        f"dedup={report.dedup_score} cur={report.curiosity_score} syn={report.synthesis_score}"
    )
    assert report.status == "HEALTHY"


# ── I: Unhealthy package ──────────────────────────────────────────────────────

def test_validate_package_unhealthy():
    """Package with fabricated URLs, dominant frame, and generic synthesis should score < 6.0."""
    cards = [_card(i, frame="CONTROVERSY", url=f"https://fake-{i}.xyz/unknown") for i in range(1, 6)]
    allowed = frozenset()   # no URLs allowed — everything fabricated
    pkg = _package(
        cards,
        package_headline = "Today Digest",   # no content words → generic
        learning_thread  = "Stay curious.",  # no content words → generic
        action_item      = "Read more.",     # no content words → generic
    )
    report = validate_package(
        raw_package     = pkg,
        allowed_urls    = allowed,
        keywords        = [],
        learning_topics = [],
        difficulty      = "beginner",
        project_name    = "Test Project",
    )
    assert report.overall_score < 6.0
    assert report.status == "FAIL"
