"""
Tests for source_intelligence_service.py — Phase 9.3.1

Covers (Task 9):
  - Numbers extracted from content
  - Dates extracted
  - Entities extracted
  - Empty snippets handled gracefully
  - Low-information sources handled (low signal_density)
  - signal_density generated (float, 0–1)
  - source_strength generated and ordered correctly by type
  - Backward compatibility: existing fields not overwritten

Run:
    pytest tests/test_source_intelligence.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.source_intelligence_service import enrich_articles


# ── Helpers ────────────────────────────────────────────────────────────────────

def _article(
    title:       str = "Test Article",
    url:         str = "https://news.example.org/test",
    content:     str = "Short content.",
    source_type: str = "news",
) -> dict:
    return {"title": title, "url": url, "content": content, "source_type": source_type}


def _enrich(article: dict) -> dict:
    enrich_articles([article])
    return article


# ── Task 9.1: Numbers extracted ────────────────────────────────────────────────

def test_percentage_extracted():
    a = _enrich(_article(content="Revenue grew 23% year-over-year in Q3 2025."))
    assert any("23" in n for n in a["important_numbers"]), a["important_numbers"]


def test_large_number_extracted():
    a = _enrich(_article(content="Company raised $4.2 billion in its Series D round."))
    assert any("4.2" in n or "billion" in n.lower() for n in a["important_numbers"]), \
        a["important_numbers"]


def test_multiple_numbers_extracted():
    a = _enrich(_article(content="The model has 70 billion parameters and 128,000 tokens context."))
    assert len(a["important_numbers"]) >= 2


def test_bare_small_numbers_filtered():
    a = _enrich(_article(content="There are 3 reasons and 7 examples in this post."))
    # Bare 1-2 digit numbers should be filtered as too noisy
    for n in a["important_numbers"]:
        assert not (n in ("3", "7")), f"Bare small number not filtered: {n!r}"


# ── Task 9.2: Dates extracted ──────────────────────────────────────────────────

def test_year_extracted():
    a = _enrich(_article(content="Report published in 2024 shows strong growth through 2025."))
    assert any("2024" in d or "2025" in d for d in a["important_dates"]), a["important_dates"]


def test_quarter_extracted():
    a = _enrich(_article(content="Earnings rose 12% in Q3 2025 compared to Q3 2024."))
    assert any("Q3" in d or "q3" in d.lower() for d in a["important_dates"]), a["important_dates"]


def test_month_extracted():
    a = _enrich(_article(content="The acquisition closed in March 2025 after regulatory review."))
    assert any("March" in d or "march" in d.lower() for d in a["important_dates"]), \
        a["important_dates"]


# ── Task 9.3: Entities extracted ───────────────────────────────────────────────

def test_two_word_entity_extracted():
    a = _enrich(_article(
        title="OpenAI Partners with Microsoft",
        content="OpenAI and Microsoft announced a strategic partnership.",
    ))
    entities_lower = [e.lower() for e in a["important_entities"]]
    assert any("openai" in e for e in entities_lower), a["important_entities"]


def test_entity_from_content():
    a = _enrich(_article(
        title="New drug approved",
        content="The Food and Drug Administration approved the treatment for adult patients.",
    ))
    assert any(
        "food" in e.lower() or "drug" in e.lower() or "administration" in e.lower()
        for e in a["important_entities"]
    ), a["important_entities"]


def test_stopword_only_sequences_filtered():
    a = _enrich(_article(content="The New Best Top Most features are here."))
    for ent in a["important_entities"]:
        # "The New Best" should not appear as an entity
        words = ent.split()
        from backend.services.source_intelligence_service import _ENTITY_STOPWORDS
        all_stop = all(w in _ENTITY_STOPWORDS for w in words)
        assert not all_stop, f"Stopword-only entity not filtered: {ent!r}"


# ── Task 9.4: Empty snippets handled ──────────────────────────────────────────

def test_empty_content_no_crash():
    a = _enrich({"title": "Empty Article", "url": "https://example.org/x",
                 "content": "", "source_type": "news"})
    assert a["important_numbers"]  == []
    assert a["important_entities"] == []
    assert a["important_dates"]    == []
    assert a["key_evidence"]       == []
    assert isinstance(a["signal_density"],  float)
    assert isinstance(a["source_strength"], float)


def test_none_content_no_crash():
    a = _enrich({"title": "No Content", "url": "https://example.org/y",
                 "content": None, "source_type": "news"})
    assert a["important_numbers"]  == []
    assert a["signal_density"]     >= 0.0


def test_missing_fields_no_crash():
    a = _enrich({})
    assert "signal_density"  in a
    assert "source_strength" in a


# ── Task 9.5: Low-information sources handled ──────────────────────────────────

def test_sparse_content_low_density():
    a = _enrich(_article(content="Brief update.", source_type="news"))
    # No numbers, no entities, short content — density should be low
    assert a["signal_density"] <= 0.30, f"Expected low density, got {a['signal_density']}"


def test_rich_content_higher_density():
    a = _enrich(_article(
        title="GDP Grows 5.2% in Q2 2025 as Federal Reserve Raises Rates",
        content=(
            "The United States economy expanded 5.2% in the second quarter of 2025, "
            "the Bureau of Economic Analysis reported on Thursday. "
            "Federal Reserve Chair Jerome Powell said interest rates could rise by 25 basis points. "
            "Unemployment fell to 3.8%, the lowest since 2019. "
            "Goldman Sachs revised its forecast to 4.9% growth for full-year 2025."
        ),
        source_type="government",
    ))
    assert a["signal_density"] >= 0.40, f"Expected higher density, got {a['signal_density']}"


# ── Task 9.6: signal_density generated ────────────────────────────────────────

def test_signal_density_is_float_in_range():
    for content in [
        "",
        "Short.",
        "Revenue grew 40% to $2 billion in Q2 2025.",
        "A " * 200,  # long but low-signal content
    ]:
        a = _enrich(_article(content=content))
        assert isinstance(a["signal_density"], float), content
        assert 0.0 <= a["signal_density"] <= 1.0, f"Out of range: {a['signal_density']}"


def test_signal_density_higher_with_numbers_and_entities():
    a_rich = _enrich(_article(
        title="Apple Reports $95 Billion Revenue in Q4 2025",
        content="Apple Inc. reported $95 billion in revenue for Q4 2025, up 12% year-over-year.",
    ))
    a_poor = _enrich(_article(content="Some things happened recently."))
    assert a_rich["signal_density"] > a_poor["signal_density"]


# ── Task 9.7: source_strength generated ───────────────────────────────────────

def test_source_strength_ordering():
    types = ["government", "research_paper", "regulatory", "industry_report",
             "educational", "news", "company_blog"]
    articles = [_enrich(_article(source_type=t)) for t in types]
    strengths = [a["source_strength"] for a in articles]
    # government should be strongest
    assert strengths[0] == max(strengths), f"government not strongest: {list(zip(types, strengths))}"
    # company_blog should be weakest of the named types
    assert strengths[-1] == min(strengths), f"company_blog not weakest: {list(zip(types, strengths))}"


def test_unknown_source_type_default():
    a = _enrich(_article(source_type=""))
    assert a["source_strength"] == 0.40

    a2 = _enrich(_article(source_type="some_unknown_type"))
    assert a2["source_strength"] == 0.40


def test_source_strength_in_range():
    for stype in ["government", "news", "company_blog", "", "mystery"]:
        a = _enrich(_article(source_type=stype))
        assert 0.0 <= a["source_strength"] <= 1.0, f"Out of range for {stype!r}"


# ── Task 9.8: Backward compatibility ──────────────────────────────────────────

def test_existing_fields_not_overwritten():
    orig = {
        "title":       "Original Title",
        "url":         "https://reuters.com/article/1",
        "content":     "Original content with 25% growth.",
        "source_type": "news",
        "domain":      "reuters.com",
        "final_score": 0.82,
        "_rank_score": 0.79,
    }
    enrich_articles([orig])
    assert orig["title"]       == "Original Title"
    assert orig["url"]         == "https://reuters.com/article/1"
    assert orig["content"]     == "Original content with 25% growth."
    assert orig["source_type"] == "news"
    assert orig["domain"]      == "reuters.com"
    assert orig["final_score"] == 0.82
    assert orig["_rank_score"] == 0.79


def test_all_intelligence_fields_present_after_enrich():
    a = _enrich(_article())
    required = [
        "main_claim", "key_evidence", "important_numbers",
        "important_entities", "important_dates", "implications",
        "risks", "contradictions", "signal_density", "source_strength",
    ]
    for field in required:
        assert field in a, f"Missing field: {field!r}"


def test_multiple_articles_all_enriched():
    articles = [_article(content=f"Article {i} grew {i * 10}% in 2025.") for i in range(5)]
    enrich_articles(articles)
    for a in articles:
        assert "signal_density"  in a
        assert "source_strength" in a
        assert isinstance(a["signal_density"], float)
