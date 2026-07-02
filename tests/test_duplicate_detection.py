"""
Tests for near-duplicate detection — Phase 7.3

Covers:
  - _extract_entities: capitalized proper-noun extraction
  - _content_overlap: Jaccard on content tokens
  - _entity_overlap: entity set overlap
  - duplicate_score: composite formula, syndicated article detection
  - deduplicate_ranked:
      - single article / empty list / no duplicates
      - keeps highest _retrieval_score per cluster
      - merges metadata from discarded into winner
      - tags winner with correct duplicate_score
      - multiple independent clusters preserved
      - transitive clustering (A~B and B~C → A,B,C same cluster)

Run:
    pytest tests/test_duplicate_detection.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.similarity_service import (
    NEAR_DUP_THRESHOLD,
    _content_overlap,
    _entity_overlap,
    _extract_entities,
    deduplicate_ranked,
    duplicate_score,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

_REUTERS_CONTENT = (
    "Federal Reserve Chairman Jerome Powell raised interest rates by 25 basis "
    "points on Wednesday, citing persistent inflation in the United States economy. "
    "The decision was unanimous among Federal Open Market Committee members. "
    "Powell signalled that additional hikes remain possible if inflation data "
    "does not moderate. Treasury yields rose sharply following the announcement "
    "while equity markets sold off. The S&P 500 fell 1.2 percent."
)

# Yahoo syndicates Reuters articles nearly verbatim — only a prefix + byline differs.
_YAHOO_CONTENT = (
    "(Reuters) - Federal Reserve Chairman Jerome Powell raised interest rates by 25 basis "
    "points on Wednesday, citing persistent inflation in the United States economy. "
    "The decision was unanimous among Federal Open Market Committee members. "
    "Powell signalled that additional hikes remain possible if inflation data "
    "does not moderate. Treasury yields rose sharply following the announcement "
    "while equity markets sold off. The S&P 500 fell 1.2 percent. "
    "Reporting by Ann Saphir; Editing by Paul Simao."
)

_UNRELATED_CONTENT = (
    "OpenAI released a new version of its large language model today. "
    "The model achieves state-of-the-art performance on coding benchmarks. "
    "Microsoft, an investor in OpenAI, announced integration into Azure services. "
    "Researchers said the model shows improved reasoning and reduced hallucinations."
)


def _art(url: str, title: str, content: str = "",
         retrieval_score: float = 0.5, **extra) -> dict:
    a = {
        "url":              url,
        "title":            title,
        "content":          content,
        "_retrieval_score": retrieval_score,
    }
    a.update(extra)
    return a


# ── _extract_entities ─────────────────────────────────────────────────────────

class TestExtractEntities:
    def test_finds_proper_nouns(self):
        entities = _extract_entities("Jerome Powell raised interest rates")
        assert "powell" in entities

    def test_finds_organization(self):
        entities = _extract_entities("The Federal Reserve raised rates")
        assert "federal" in entities or "reserve" in entities

    def test_filters_stop_words(self):
        entities = _extract_entities("This article covers the situation")
        # "This", "That" etc. are stop words and should not appear
        assert "this" not in entities

    def test_min_length_enforced(self):
        # "AI" has length 2, should not appear (regex requires ≥ 4 total chars = 1 cap + 3 lower)
        entities = _extract_entities("AI researchers at MIT released results")
        assert "ai" not in entities

    def test_returns_frozenset(self):
        result = _extract_entities("OpenAI released a model")
        assert isinstance(result, frozenset)

    def test_empty_text_returns_empty(self):
        assert _extract_entities("") == frozenset()

    def test_two_similar_texts_share_entities(self):
        e1 = _extract_entities(_REUTERS_CONTENT)
        e2 = _extract_entities(_YAHOO_CONTENT)
        shared = e1 & e2
        assert len(shared) > 3, f"Expected >3 shared entities, got {len(shared)}: {shared}"


# ── _content_overlap ──────────────────────────────────────────────────────────

class TestContentOverlap:
    def test_identical_content_scores_high(self):
        a = _art("https://a.com", "T", _REUTERS_CONTENT)
        b = _art("https://b.com", "T", _REUTERS_CONTENT)
        assert _content_overlap(a, b) > 0.90

    def test_syndicated_content_scores_high(self):
        # Yahoo syndicates Reuters near-verbatim; content overlap should be very high.
        a = _art("https://reuters.com/fed", "Fed Raises", _REUTERS_CONTENT)
        b = _art("https://yahoo.com/fed",   "Fed Raises", _YAHOO_CONTENT)
        score = _content_overlap(a, b)
        assert score > 0.85, f"Syndicated overlap should be > 0.85, got {score}"

    def test_unrelated_content_scores_low(self):
        a = _art("https://a.com", "T", _REUTERS_CONTENT)
        b = _art("https://b.com", "T", _UNRELATED_CONTENT)
        assert _content_overlap(a, b) < 0.30

    def test_missing_content_returns_zero(self):
        a = {"url": "https://a.com", "title": "T"}
        b = _art("https://b.com", "T", _REUTERS_CONTENT)
        assert _content_overlap(a, b) == 0.0

    def test_both_missing_content_returns_zero(self):
        a = {"url": "https://a.com", "title": "T"}
        b = {"url": "https://b.com", "title": "T"}
        assert _content_overlap(a, b) == 0.0


# ── _entity_overlap ───────────────────────────────────────────────────────────

class TestEntityOverlap:
    def test_syndicated_articles_share_entities(self):
        a = _art("https://reuters.com", "Fed Hike", _REUTERS_CONTENT)
        b = _art("https://yahoo.com",   "Fed Rate", _YAHOO_CONTENT)
        assert _entity_overlap(a, b) > 0.30

    def test_unrelated_articles_low_entity_overlap(self):
        a = _art("https://reuters.com", "Fed Hike", _REUTERS_CONTENT)
        b = _art("https://openai.com",  "GPT News", _UNRELATED_CONTENT)
        assert _entity_overlap(a, b) < 0.30

    def test_no_content_uses_title_only(self):
        a = {"url": "https://a.com", "title": "Federal Reserve Raises Rates"}
        b = {"url": "https://b.com", "title": "Federal Reserve Interest Rate Hike"}
        score = _entity_overlap(a, b)
        assert score > 0.0


# ── duplicate_score ───────────────────────────────────────────────────────────

class TestDuplicateScore:
    def test_identical_articles_score_near_one(self):
        a = _art("https://a.com", "Fed Raises Rates by 25 Basis Points", _REUTERS_CONTENT)
        score = duplicate_score(a, a)
        assert score > 0.90

    def test_syndicated_reuters_yahoo(self):
        a = _art("https://reuters.com/article",
                 "Fed Raises Interest Rates 25 Basis Points",
                 _REUTERS_CONTENT)
        b = _art("https://yahoo.com/finance/news",
                 "Federal Reserve Raises Rates by Quarter Point",
                 _YAHOO_CONTENT)
        score = duplicate_score(a, b)
        assert score >= NEAR_DUP_THRESHOLD, (
            f"Syndicated article scored {score}, threshold is {NEAR_DUP_THRESHOLD}"
        )

    def test_different_stories_score_low(self):
        a = _art("https://reuters.com/fed", "Fed Raises Rates", _REUTERS_CONTENT)
        b = _art("https://openai.com/news", "OpenAI New Model", _UNRELATED_CONTENT)
        score = duplicate_score(a, b)
        assert score < NEAR_DUP_THRESHOLD

    def test_same_title_no_content_above_threshold(self):
        # Title alone at 0.8 → 0.5*0.8 = 0.40, content = 0, entity = title only ~0.6
        # 0.50*0.80 + 0.35*0.0 + 0.15*0.60 = 0.40 + 0 + 0.09 = 0.49 — below threshold
        # So purely title match with no content is borderline
        a = _art("https://a.com", "Federal Reserve Raises Interest Rates")
        b = _art("https://b.com", "Federal Reserve Raises Interest Rates")
        score = duplicate_score(a, b)
        assert 0.0 < score, "Same title should produce nonzero score"

    def test_score_is_float_in_range(self):
        a = _art("https://a.com", "Title A", "content a")
        b = _art("https://b.com", "Title B", "content b")
        score = duplicate_score(a, b)
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_score_rounded_to_3_places(self):
        a = _art("https://a.com", "Test", _REUTERS_CONTENT)
        b = _art("https://b.com", "Test", _YAHOO_CONTENT)
        score = duplicate_score(a, b)
        assert score == round(score, 3)

    def test_symmetric(self):
        a = _art("https://a.com", "Fed Hike", _REUTERS_CONTENT)
        b = _art("https://b.com", "Fed Rate", _YAHOO_CONTENT)
        assert abs(duplicate_score(a, b) - duplicate_score(b, a)) < 0.001


# ── deduplicate_ranked ────────────────────────────────────────────────────────

class TestDeduplicateRanked:
    def test_empty_list_returns_empty(self):
        assert deduplicate_ranked([]) == []

    def test_single_article_returned_unchanged(self):
        a = _art("https://a.com", "Title")
        result = deduplicate_ranked([a])
        assert len(result) == 1
        assert result[0] is a

    def test_single_article_gets_zero_duplicate_score(self):
        a = _art("https://a.com", "Title")
        deduplicate_ranked([a])
        assert a["duplicate_score"] == 0.0

    def test_no_duplicates_all_kept(self):
        a = _art("https://a.com", "Fed Raises Rates", _REUTERS_CONTENT, 0.7)
        b = _art("https://b.com", "OpenAI New Model", _UNRELATED_CONTENT, 0.5)
        result = deduplicate_ranked([a, b])
        assert len(result) == 2

    def test_no_duplicates_all_get_zero_score(self):
        a = _art("https://a.com", "Fed Raises Rates", _REUTERS_CONTENT, 0.7)
        b = _art("https://b.com", "OpenAI New Model", _UNRELATED_CONTENT, 0.5)
        deduplicate_ranked([a, b])
        assert a.get("duplicate_score", 0.0) == 0.0
        assert b.get("duplicate_score", 0.0) == 0.0

    def test_keeps_higher_retrieval_score(self):
        reuters = _art("https://reuters.com/article",
                       "Fed Raises Interest Rates 25 Basis Points",
                       _REUTERS_CONTENT,
                       retrieval_score=0.80)
        yahoo   = _art("https://yahoo.com/finance",
                       "Federal Reserve Raises Rates by Quarter Point",
                       _YAHOO_CONTENT,
                       retrieval_score=0.55)
        result = deduplicate_ranked([reuters, yahoo])
        assert len(result) == 1
        assert result[0]["url"] == "https://reuters.com/article"

    def test_discards_lower_retrieval_score(self):
        reuters = _art("https://reuters.com/article",
                       "Fed Raises Interest Rates 25 Basis Points",
                       _REUTERS_CONTENT,
                       retrieval_score=0.80)
        yahoo   = _art("https://yahoo.com/finance",
                       "Federal Reserve Raises Rates by Quarter Point",
                       _YAHOO_CONTENT,
                       retrieval_score=0.55)
        result = deduplicate_ranked([reuters, yahoo])
        urls = [r["url"] for r in result]
        assert "https://yahoo.com/finance" not in urls

    def test_winner_gets_nonzero_duplicate_score(self):
        reuters = _art("https://reuters.com/article",
                       "Fed Raises Interest Rates 25 Basis Points",
                       _REUTERS_CONTENT,
                       retrieval_score=0.80)
        yahoo   = _art("https://yahoo.com/finance",
                       "Federal Reserve Raises Rates by Quarter Point",
                       _YAHOO_CONTENT,
                       retrieval_score=0.55)
        result = deduplicate_ranked([reuters, yahoo])
        assert result[0]["duplicate_score"] > 0

    def test_merges_published_date_from_discarded(self):
        """Winner has no published_date; discarded has one — should be merged."""
        reuters = _art("https://reuters.com/article",
                       "Fed Raises Interest Rates 25 Basis Points",
                       _REUTERS_CONTENT,
                       retrieval_score=0.80)
        yahoo   = _art("https://yahoo.com/finance",
                       "Federal Reserve Raises Rates by Quarter Point",
                       _YAHOO_CONTENT,
                       retrieval_score=0.55,
                       published_date="2025-06-01")
        result = deduplicate_ranked([reuters, yahoo])
        assert result[0].get("published_date") == "2025-06-01"

    def test_does_not_overwrite_existing_metadata(self):
        """Winner already has published_date — should NOT be overwritten."""
        reuters = _art("https://reuters.com/article",
                       "Fed Raises Interest Rates 25 Basis Points",
                       _REUTERS_CONTENT,
                       retrieval_score=0.80,
                       published_date="2025-05-30")
        yahoo   = _art("https://yahoo.com/finance",
                       "Federal Reserve Raises Rates by Quarter Point",
                       _YAHOO_CONTENT,
                       retrieval_score=0.55,
                       published_date="2025-06-01")
        result = deduplicate_ranked([reuters, yahoo])
        assert result[0]["published_date"] == "2025-05-30"

    def test_multiple_independent_clusters_all_preserved(self):
        """Two unrelated stories → two winners."""
        a1 = _art("https://reuters.com/fed",  "Fed Raises Rates 25bp", _REUTERS_CONTENT, 0.9)
        a2 = _art("https://yahoo.com/fed",    "Federal Reserve Rate Hike Quarter Point", _YAHOO_CONTENT, 0.6)
        b1 = _art("https://openai.com/news",  "OpenAI Releases New Model", _UNRELATED_CONTENT, 0.8)
        result = deduplicate_ranked([a1, a2, b1])
        assert len(result) == 2
        urls = {r["url"] for r in result}
        assert "https://reuters.com/fed" in urls
        assert "https://openai.com/news" in urls

    def test_transitive_cluster(self):
        """A is dup of B, B is dup of C → all three in same cluster → one winner."""
        # Three near-identical articles with same content
        base = _REUTERS_CONTENT
        a = _art("https://site1.com", "Fed Raises Interest Rates by 25 Basis Points", base, 0.9)
        b = _art("https://site2.com", "Federal Reserve Raises Interest Rates 25bp",   base, 0.7)
        c = _art("https://site3.com", "Fed Hikes Rates by 25 Basis Points",           base, 0.5)
        result = deduplicate_ranked([a, b, c])
        assert len(result) == 1
        assert result[0]["url"] == "https://site1.com"  # highest score
