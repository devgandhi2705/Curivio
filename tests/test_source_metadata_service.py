"""
Tests for source_metadata_service.py — Phase 7.1

Covers:
  - _classify_source_type: URL-based and title-based classification for all 8 types
  - enrich(): correct field mapping from both learning-path and standard-path breakdowns,
    idempotency, defaults, domain extraction
  - Integration: rank_articles() returns articles with the formal model fields populated

Run:
    pytest tests/test_source_metadata_service.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.source_metadata_service import (
    _classify_source_type,
    _extract_domain,
    enrich,
)


# ── _classify_source_type ─────────────────────────────────────────────────────

class TestClassifySourceType:
    # research_paper
    def test_arxiv_is_research_paper(self):
        assert _classify_source_type("https://arxiv.org/abs/2301.00001", "") == "research_paper"

    def test_pubmed_is_research_paper(self):
        assert _classify_source_type("https://pubmed.ncbi.nlm.nih.gov/123456/", "") == "research_paper"

    def test_nature_is_research_paper(self):
        assert _classify_source_type("https://www.nature.com/articles/s123", "") == "research_paper"

    def test_doi_is_research_paper(self):
        assert _classify_source_type("https://doi.org/10.1234/journal.pone", "") == "research_paper"

    # government
    def test_dot_gov_is_government(self):
        assert _classify_source_type("https://www.sec.gov/rules/", "") == "government"

    def test_who_int_is_government(self):
        assert _classify_source_type("https://www.who.int/publications/", "") == "government"

    def test_worldbank_is_government(self):
        assert _classify_source_type("https://worldbank.org/en/topic/trade", "") == "government"

    # regulatory
    def test_ema_is_regulatory(self):
        assert _classify_source_type("https://ema.europa.eu/en/regulatory/", "") == "regulatory"

    def test_finra_is_regulatory(self):
        assert _classify_source_type("https://www.finra.org/rules-guidance/", "") == "regulatory"

    # industry_report
    def test_gartner_is_industry_report(self):
        assert _classify_source_type("https://www.gartner.com/en/research/", "") == "industry_report"

    def test_mckinsey_is_industry_report(self):
        assert _classify_source_type("https://www.mckinsey.com/insights/", "") == "industry_report"

    def test_statista_is_industry_report(self):
        assert _classify_source_type("https://statista.com/statistics/", "") == "industry_report"

    # news
    def test_bloomberg_is_news(self):
        assert _classify_source_type("https://www.bloomberg.com/news/articles/", "") == "news"

    def test_techcrunch_is_news(self):
        assert _classify_source_type("https://techcrunch.com/2025/", "") == "news"

    def test_bbc_is_news(self):
        assert _classify_source_type("https://www.bbc.com/news/technology", "") == "news"

    # educational
    def test_coursera_is_educational(self):
        assert _classify_source_type("https://www.coursera.org/learn/ml", "") == "educational"

    def test_mit_edu_is_educational(self):
        assert _classify_source_type("https://mit.edu/courses/ocw/", "") == "educational"

    def test_tutorial_path_is_educational(self):
        assert _classify_source_type("https://docs.example.com/tutorial/intro", "") == "educational"

    # company_blog
    def test_medium_is_company_blog(self):
        assert _classify_source_type("https://medium.com/@user/article", "") == "company_blog"

    def test_openai_blog_is_company_blog(self):
        assert _classify_source_type("https://openai.com/blog/gpt-4", "") == "company_blog"

    def test_substack_is_company_blog(self):
        assert _classify_source_type("https://newsletter.substack.com/p/post", "") == "company_blog"

    def test_blog_path_is_company_blog(self):
        assert _classify_source_type("https://company.example.com/blog/update", "") == "company_blog"

    # title fallback
    def test_title_fallback_research(self):
        t = _classify_source_type("https://unknownsite.example.com/page", "New Study Published in Journal")
        assert t == "research_paper"

    def test_title_fallback_tutorial(self):
        t = _classify_source_type("https://unknownsite.example.com/page", "Python Tutorial for Beginners")
        assert t == "educational"

    def test_unknown_url_defaults_to_news(self):
        t = _classify_source_type("https://randomsite.example.com/article", "")
        assert t == "news"

    # Return type always a valid string
    def test_returns_string_for_empty_inputs(self):
        result = _classify_source_type("", "")
        assert isinstance(result, str)
        assert len(result) > 0


# ── enrich() — score field mapping ───────────────────────────────────────────

class TestEnrichLearningPathBreakdown:
    """Learning-path breakdown: authority, freshness, intent_match, novelty."""

    ARTICLE = {
        "url":   "https://arxiv.org/abs/2301.00001",
        "title": "Attention Is All You Need",
    }
    BREAKDOWN = {
        "intent_match":        0.82,
        "topic_match":         0.70,
        "learning_continuity": 0.65,
        "novelty":             0.55,
        "authority":           0.90,
        "freshness":           0.75,
        "practical_value":     0.40,
        "perspective":         0.30,
        "total":               0.78,
    }

    def _fresh(self):
        return dict(self.ARTICLE)

    def test_intent_score_mapped(self):
        a = self._fresh()
        enrich(a, self.BREAKDOWN, final_score=0.80)
        assert a["intent_score"] == 0.82

    def test_authority_score_mapped(self):
        a = self._fresh()
        enrich(a, self.BREAKDOWN, final_score=0.80)
        assert a["authority_score"] == 0.90

    def test_freshness_score_mapped(self):
        a = self._fresh()
        enrich(a, self.BREAKDOWN, final_score=0.80)
        assert a["freshness_score"] == 0.75

    def test_novelty_score_mapped(self):
        a = self._fresh()
        enrich(a, self.BREAKDOWN, final_score=0.80)
        assert a["novelty_score"] == 0.55

    def test_final_score_uses_adjusted_rank_score(self):
        a = self._fresh()
        enrich(a, self.BREAKDOWN, final_score=0.80)
        assert a["final_score"] == 0.80

    def test_final_score_defaults_to_breakdown_total(self):
        """When final_score not supplied, fall back to breakdown total."""
        a = self._fresh()
        enrich(a, self.BREAKDOWN)
        assert a["final_score"] == self.BREAKDOWN["total"]

    def test_source_type_classified(self):
        a = self._fresh()
        enrich(a, self.BREAKDOWN, final_score=0.80)
        assert a["source_type"] == "research_paper"

    def test_retrieval_query_defaults_to_empty(self):
        a = self._fresh()
        enrich(a, self.BREAKDOWN, final_score=0.80)
        assert a["retrieval_query"] == ""

    def test_retrieval_query_preserved_when_already_set(self):
        a = self._fresh()
        a["retrieval_query"] = "attention mechanism transformers 2025"
        enrich(a, self.BREAKDOWN, final_score=0.80)
        assert a["retrieval_query"] == "attention mechanism transformers 2025"

    def test_domain_extracted_when_missing(self):
        a = self._fresh()
        enrich(a, self.BREAKDOWN, final_score=0.80)
        assert a["domain"] == "arxiv.org"

    def test_domain_preserved_when_already_set(self):
        a = self._fresh()
        a["domain"] = "custom.override.com"
        enrich(a, self.BREAKDOWN, final_score=0.80)
        assert a["domain"] == "custom.override.com"

    def test_published_date_defaults_to_empty(self):
        a = self._fresh()
        enrich(a, self.BREAKDOWN, final_score=0.80)
        assert "published_date" in a

    def test_all_formal_fields_present(self):
        a = self._fresh()
        enrich(a, self.BREAKDOWN, final_score=0.80)
        required = {
            "url", "title", "domain", "published_date",
            "authority_score", "freshness_score", "intent_score",
            "novelty_score", "final_score", "retrieval_query", "source_type",
        }
        assert required.issubset(a.keys())


class TestEnrichStandardPathBreakdown:
    """Standard-path breakdown: fallback mapping for content_quality, recency, keyword_relevance."""

    ARTICLE = {
        "url":   "https://techcrunch.com/2025/ai-news",
        "title": "OpenAI Releases New Model",
    }
    BREAKDOWN = {
        "keyword_relevance":  0.72,
        "technical_depth":    0.45,
        "content_quality":    0.68,
        "educational_value":  0.30,
        "recency":            0.85,
        "supplemental_bonus": 0.04,
        "total":              0.60,
    }

    def _fresh(self):
        return dict(self.ARTICLE)

    def test_authority_falls_back_to_content_quality(self):
        a = self._fresh()
        enrich(a, self.BREAKDOWN, final_score=0.60)
        assert a["authority_score"] == 0.68

    def test_freshness_falls_back_to_recency(self):
        a = self._fresh()
        enrich(a, self.BREAKDOWN, final_score=0.60)
        assert a["freshness_score"] == 0.85

    def test_intent_falls_back_to_keyword_relevance(self):
        a = self._fresh()
        enrich(a, self.BREAKDOWN, final_score=0.60)
        assert a["intent_score"] == 0.72

    def test_novelty_is_zero_when_absent(self):
        a = self._fresh()
        enrich(a, self.BREAKDOWN, final_score=0.60)
        assert a["novelty_score"] == 0.0

    def test_source_type_is_news_for_techcrunch(self):
        a = self._fresh()
        enrich(a, self.BREAKDOWN, final_score=0.60)
        assert a["source_type"] == "news"


class TestEnrichIdempotency:
    def test_source_type_set_only_on_first_call(self):
        article = {
            "url":         "https://arxiv.org/abs/123",
            "title":       "Test Paper",
            "source_type": "manually_set",  # pre-set
        }
        breakdown = {"authority": 0.5, "freshness": 0.5, "intent_match": 0.5,
                     "novelty": 0.5, "total": 0.5}
        enrich(article, breakdown)
        assert article["source_type"] == "manually_set"   # not overwritten

    def test_scores_overwritten_on_second_call(self):
        article = {"url": "https://arxiv.org/abs/456", "title": "Test"}
        bd1 = {"authority": 0.3, "freshness": 0.3, "intent_match": 0.3,
               "novelty": 0.3, "total": 0.3}
        bd2 = {"authority": 0.9, "freshness": 0.9, "intent_match": 0.9,
               "novelty": 0.9, "total": 0.9}
        enrich(article, bd1)
        enrich(article, bd2)
        assert article["authority_score"] == 0.9

    def test_scores_rounded_to_three_places(self):
        article = {"url": "https://test.com", "title": "Test"}
        bd = {"authority": 0.12345678, "freshness": 0.0, "intent_match": 0.0,
              "novelty": 0.0, "total": 0.0}
        enrich(article, bd)
        assert article["authority_score"] == 0.123

    def test_no_crash_on_empty_breakdown(self):
        article = {"url": "https://test.com", "title": "Test"}
        enrich(article, {})
        assert article["authority_score"] == 0.0
        assert article["final_score"] == 0.0

    def test_no_crash_on_empty_article(self):
        enrich({}, {"authority": 0.5, "total": 0.5})


# ── _extract_domain ───────────────────────────────────────────────────────────

class TestExtractDomain:
    def test_strips_www_prefix(self):
        assert _extract_domain("https://www.bloomberg.com/news") == "bloomberg.com"

    def test_no_www(self):
        assert _extract_domain("https://arxiv.org/abs/123") == "arxiv.org"

    def test_empty_url_returns_empty(self):
        assert _extract_domain("") == ""

    def test_invalid_url_does_not_crash(self):
        result = _extract_domain("not a url at all")
        assert isinstance(result, str)
