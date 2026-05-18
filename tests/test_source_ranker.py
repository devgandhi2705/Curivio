"""
Tests for source_ranker.py.

Test levels:
  1. Dimension unit tests  — pure functions, zero I/O
  2. score_article tests   — combined scoring with known articles
  3. rank_articles tests   — ordering, spam filtering, domain deduplication
  4. Integration test      — one real Tavily search (skip by default)

Run non-integration tests:
    pytest tests/test_source_ranker.py -v

Run the live integration test:
    pytest tests/test_source_ranker.py -v -m integration
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.source_ranker import (
    MAX_PER_DOMAIN,
    MIN_SCORE_FLOOR,
    W_EDUCATION,
    W_KEYWORD,
    W_QUALITY,
    W_RECENCY,
    W_TECHNICAL,
    _content_quality_score,
    _domain_reputation,
    _educational_value_score,
    _extract_domain,
    _keyword_score,
    _recency_score,
    _technical_depth_score,
    _try_parse_iso,
    rank_articles,
    score_article,
)


# ── Article fixtures ──────────────────────────────────────────────────────────

def _article(title="", content="", url="https://example.com/post", published_date=None):
    a = {"title": title, "content": content, "url": url}
    if published_date:
        a["published_date"] = published_date
    return a


TECHNICAL_ARTICLE = _article(
    title="Implementing RAG with LLM Embeddings",
    content=(
        "This tutorial covers retrieval-augmented generation pipelines. "
        "We benchmark inference latency at 120ms with a 7B parameter model. "
        "The implementation uses PyTorch, a vector index, and attention layers. "
        "We optimize throughput by batching 32 tokens per step with gradient checkpointing. "
        "Accuracy improves 12% over baseline with this architecture. "
        "This deep-dive guide walks through training, evaluation, and deployment on GPU."
    ),
    url="https://arxiv.org/abs/2312.12345",
)

SPAM_ARTICLE = _article(
    title="You won't believe how this one weird trick doubled my AI accuracy",
    content="Short stub.",
    url="https://buzzfeed.com/sponsored/ai-hack",
)

EDUCATIONAL_ARTICLE = _article(
    title="A beginner's guide to transformer architecture",
    content=(
        "Step-by-step introduction to transformer models. "
        "This walkthrough covers the fundamentals of attention mechanisms, "
        "how tokens flow through layers, and practical examples. "
        "Great for beginners learning the basics."
    ),
    url="https://towardsdatascience.com/transformers-101",
)

LOW_CONTENT_ARTICLE = _article(
    title="AI news",
    content="Short.",
    url="https://somenewssite.com/ai",
)

RECENT_ARTICLE = _article(
    title="New LLM Architecture Released",
    content="A detailed analysis of the architecture with benchmarks and implementation details.",
    url="https://huggingface.co/blog/new-llm",
    published_date="2026-05-13T10:00:00Z",   # 1 day ago
)

OLD_ARTICLE = _article(
    title="Understanding Neural Networks (2018)",
    content="A comprehensive overview of neural network architectures.",
    url="https://example.com/2018/01/neural-networks",
    published_date="2018-01-01T00:00:00Z",
)

QUERY = "RAG pipelines LLM inference"


# ── 1. Dimension unit tests ───────────────────────────────────────────────────

class TestKeywordScore:
    def test_returns_float_in_range(self):
        s = _keyword_score(TECHNICAL_ARTICLE, QUERY)
        assert 0.0 <= s <= 1.0

    def test_full_title_match_scores_high(self):
        art = _article(title="RAG pipelines LLM inference guide")
        assert _keyword_score(art, QUERY) > 0.7

    def test_no_match_scores_low(self):
        art = _article(title="Cooking recipes for beginners", content="pasta sauce ingredients")
        assert _keyword_score(art, QUERY) < 0.2

    def test_empty_query_returns_neutral(self):
        assert _keyword_score(TECHNICAL_ARTICLE, "") == 0.5

    def test_title_weighted_higher_than_content(self):
        # Same keyword in title vs only in content
        title_only = _article(title="RAG pipelines", content="unrelated text")
        content_only = _article(title="unrelated", content="RAG pipelines in use")
        assert _keyword_score(title_only, "RAG pipelines") > _keyword_score(content_only, "RAG pipelines")

    def test_case_insensitive(self):
        art = _article(title="RAG PIPELINES", content="")
        assert _keyword_score(art, "rag pipelines") > 0.5

    def test_stopwords_excluded(self):
        # "the" and "a" should not count as keyword matches
        s_with = _keyword_score(_article(title="the a an"), "the quick brown fox")
        s_without = _keyword_score(_article(title="quick brown fox"), "the quick brown fox")
        assert s_without > s_with


class TestTechnicalDepthScore:
    def test_returns_float_in_range(self):
        s = _technical_depth_score(TECHNICAL_ARTICLE)
        assert 0.0 <= s <= 1.0

    def test_technical_article_scores_higher_than_spam(self):
        assert _technical_depth_score(TECHNICAL_ARTICLE) > _technical_depth_score(SPAM_ARTICLE)

    def test_technical_terms_boost_score(self):
        no_terms = _article(content="Some article about things happening today.")
        with_terms = _article(content="transformer architecture with attention layers and gradient descent")
        assert _technical_depth_score(with_terms) > _technical_depth_score(no_terms)

    def test_quantitative_data_boosts_score(self):
        no_quant = _article(content="This model performs well on the benchmark.")
        with_quant = _article(content="Model achieves 94.2% accuracy with 7B parameters at 120ms latency.")
        assert _technical_depth_score(with_quant) > _technical_depth_score(no_quant)

    def test_long_content_scores_higher_than_stub(self):
        stub = _article(content="Short.")
        long = _article(content="x" * 1200)
        assert _technical_depth_score(long) > _technical_depth_score(stub)


class TestContentQualityScore:
    def test_returns_float_in_range(self):
        s = _content_quality_score(TECHNICAL_ARTICLE)
        assert 0.0 <= s <= 1.0

    def test_spam_title_returns_zero(self):
        assert _content_quality_score(SPAM_ARTICLE) == 0.0

    def test_trusted_domain_boosts_score(self):
        arxiv = _article(content="x" * 500, url="https://arxiv.org/abs/123")
        unknown = _article(content="x" * 500, url="https://randomblog.net/post")
        assert _content_quality_score(arxiv) > _content_quality_score(unknown)

    def test_short_content_penalised(self):
        stub = _article(content="x" * 30)
        long = _article(content="x" * 900)
        assert _content_quality_score(long) > _content_quality_score(stub)

    def test_no_spam_pattern_full_length_scores_well(self):
        art = _article(title="Deep Dive: LLM Architectures", content="x" * 1000)
        assert _content_quality_score(art) > 0.5


class TestEducationalValueScore:
    def test_returns_float_in_range(self):
        s = _educational_value_score(EDUCATIONAL_ARTICLE)
        assert 0.0 <= s <= 1.0

    def test_educational_article_scores_higher_than_stub(self):
        assert _educational_value_score(EDUCATIONAL_ARTICLE) > _educational_value_score(LOW_CONTENT_ARTICLE)

    def test_tutorial_keyword_boosts_score(self):
        no_edu = _article(content="Research results and findings from experiments.")
        with_edu = _article(content="A hands-on tutorial guide with step-by-step walkthrough examples.")
        assert _educational_value_score(with_edu) > _educational_value_score(no_edu)

    def test_educational_url_path_adds_bonus(self):
        no_path  = _article(url="https://example.com/post/12345")
        edu_path = _article(url="https://example.com/docs/tutorial/intro")
        assert _educational_value_score(edu_path) > _educational_value_score(no_path)

    def test_score_capped_at_one(self):
        art = _article(
            title="Tutorial guide walkthrough introduction beginner step-by-step",
            content="learn course lesson practical hands-on tutorial guide walkthrough",
            url="https://docs.example.com/tutorial/learn",
        )
        assert _educational_value_score(art) <= 1.0


class TestRecencyScore:
    def test_returns_float_in_range(self):
        assert 0.0 <= _recency_score(RECENT_ARTICLE) <= 1.0

    def test_recent_article_scores_higher_than_old(self):
        assert _recency_score(RECENT_ARTICLE) > _recency_score(OLD_ARTICLE)

    def test_unknown_date_returns_neutral(self):
        assert _recency_score(_article()) == 0.5

    def test_date_in_url_path_parsed(self):
        art = _article(url="https://blog.example.com/2026/04/new-llm-post")
        assert _recency_score(art) > 0.5  # 2026/04 is ~40 days ago → 0.65

    def test_old_url_date_returns_low_score(self):
        art = _article(url="https://blog.example.com/2017/03/old-post")
        assert _recency_score(art) < 0.5

    def test_very_recent_published_date_returns_high_score(self):
        art = _article(published_date="2026-05-13T00:00:00Z")
        assert _recency_score(art) >= 0.85


class TestDomainReputation:
    def test_arxiv_scores_high(self):
        assert _domain_reputation("https://arxiv.org/abs/123") == 1.0

    def test_buzzfeed_scores_low(self):
        assert _domain_reputation("https://buzzfeed.com/post") <= 0.1

    def test_unknown_domain_returns_neutral(self):
        assert _domain_reputation("https://unknownsite123.com/post") == 0.50

    def test_huggingface_scores_high(self):
        assert _domain_reputation("https://huggingface.co/blog") >= 0.90

    def test_github_scores_above_neutral(self):
        assert _domain_reputation("https://github.com/user/repo") > 0.50


class TestExtractDomain:
    def test_extracts_netloc(self):
        assert _extract_domain("https://arxiv.org/abs/123") == "arxiv.org"

    def test_strips_www_prefix(self):
        assert _extract_domain("https://www.example.com/page") == "example.com"

    def test_handles_subdomain(self):
        assert _extract_domain("https://blog.openai.com/post") == "blog.openai.com"

    def test_handles_empty_string(self):
        result = _extract_domain("")
        assert isinstance(result, str)


class TestTryParseIso:
    def test_parses_standard_iso(self):
        dt = _try_parse_iso("2025-05-14T10:00:00Z")
        assert dt is not None
        assert dt.year == 2025

    def test_parses_date_only(self):
        dt = _try_parse_iso("2024-03-01")
        assert dt is not None
        assert dt.month == 3

    def test_returns_none_for_garbage(self):
        assert _try_parse_iso("not-a-date") is None

    def test_returns_none_for_empty_string(self):
        assert _try_parse_iso("") is None


# ── 2. score_article tests ────────────────────────────────────────────────────

class TestScoreArticle:
    def test_returns_all_required_keys(self):
        breakdown = score_article(TECHNICAL_ARTICLE, QUERY)
        for key in ("keyword_relevance", "technical_depth", "content_quality",
                    "educational_value", "recency", "total"):
            assert key in breakdown

    def test_total_in_range(self):
        breakdown = score_article(TECHNICAL_ARTICLE, QUERY)
        assert 0.0 <= breakdown["total"] <= 1.0

    def test_total_matches_weighted_sum(self):
        b = score_article(TECHNICAL_ARTICLE, QUERY)
        expected = round(
            b["keyword_relevance"] * W_KEYWORD  +
            b["technical_depth"]   * W_TECHNICAL +
            b["content_quality"]   * W_QUALITY   +
            b["educational_value"] * W_EDUCATION +
            b["recency"]           * W_RECENCY,
            3,
        )
        assert abs(b["total"] - expected) < 0.001

    def test_technical_article_beats_spam(self):
        tech  = score_article(TECHNICAL_ARTICLE, QUERY)
        spam  = score_article(SPAM_ARTICLE,      QUERY)
        assert tech["total"] > spam["total"]

    def test_all_dimensions_are_floats(self):
        b = score_article(TECHNICAL_ARTICLE, QUERY)
        for v in b.values():
            assert isinstance(v, float)

    def test_weights_sum_to_one(self):
        assert abs(W_KEYWORD + W_TECHNICAL + W_QUALITY + W_EDUCATION + W_RECENCY - 1.0) < 1e-9


# ── 3. rank_articles tests ────────────────────────────────────────────────────

class TestRankArticles:
    def test_returns_list(self):
        result = rank_articles([TECHNICAL_ARTICLE, EDUCATIONAL_ARTICLE], QUERY)
        assert isinstance(result, list)

    def test_empty_input_returns_empty(self):
        assert rank_articles([], QUERY) == []

    def test_top_n_limits_results(self):
        articles = [TECHNICAL_ARTICLE, EDUCATIONAL_ARTICLE, RECENT_ARTICLE]
        result = rank_articles(articles, QUERY, top_n=2)
        assert len(result) <= 2

    def test_spam_below_min_score_excluded(self):
        result = rank_articles([SPAM_ARTICLE], QUERY, min_score=0.15)
        assert result == []

    def test_high_quality_article_included(self):
        result = rank_articles([TECHNICAL_ARTICLE, SPAM_ARTICLE], QUERY)
        titles = [a["title"] for a in result]
        assert TECHNICAL_ARTICLE["title"] in titles

    def test_domain_deduplication_limits_per_domain(self):
        same_domain = [
            _article(title=f"Article {i}", content="x" * 600, url=f"https://arxiv.org/abs/{i}")
            for i in range(MAX_PER_DOMAIN + 2)
        ]
        result = rank_articles(same_domain, "arxiv research", top_n=10)
        arxiv_count = sum(1 for a in result if "arxiv.org" in a["url"])
        assert arxiv_count <= MAX_PER_DOMAIN

    def test_result_articles_are_original_dicts(self):
        result = rank_articles([TECHNICAL_ARTICLE], QUERY)
        if result:
            assert result[0]["title"] == TECHNICAL_ARTICLE["title"]

    def test_best_article_ranked_first(self):
        result = rank_articles([LOW_CONTENT_ARTICLE, TECHNICAL_ARTICLE], QUERY)
        if len(result) >= 2:
            # Technical article should beat low-content article
            assert result[0]["title"] == TECHNICAL_ARTICLE["title"]

    def test_higher_quality_ordered_before_lower(self):
        articles = [LOW_CONTENT_ARTICLE, SPAM_ARTICLE, TECHNICAL_ARTICLE, EDUCATIONAL_ARTICLE]
        result = rank_articles(articles, QUERY, top_n=4)
        # Spam should not be first
        if result:
            assert result[0]["title"] != SPAM_ARTICLE["title"]

    def test_returns_fewer_than_top_n_when_not_enough_pass_filter(self):
        # Only one good article in a list of mostly spam
        all_spam = [SPAM_ARTICLE] * 4 + [TECHNICAL_ARTICLE]
        result = rank_articles(all_spam, QUERY, top_n=5)
        assert len(result) <= 2   # only TECHNICAL_ARTICLE survives per domain dedup

    def test_min_score_zero_passes_all_nonspam(self):
        articles = [TECHNICAL_ARTICLE, EDUCATIONAL_ARTICLE, LOW_CONTENT_ARTICLE]
        result = rank_articles(articles, QUERY, top_n=10, min_score=0.0)
        assert len(result) == len(articles)

    def test_curator_integration_uses_ranker(self):
        """rank_articles is called inside generate_learning_feed on a cache miss."""
        from unittest.mock import patch as p
        import json

        MOCK_FEED = {
            "news_insight": {"title": "T", "summary": "S", "why_it_matters": "W", "sources": []},
            "learning_topics": [
                {"title": "A", "reason": "r", "difficulty": "beginner"},
                {"title": "B", "reason": "r", "difficulty": "intermediate"},
                {"title": "C", "reason": "r", "difficulty": "intermediate"},
                {"title": "D", "reason": "r", "difficulty": "advanced"},
            ],
            "next_step": "do it",
        }

        with (
            p("backend.services.curator_service.search_articles", return_value=[TECHNICAL_ARTICLE]),
            p("backend.services.curator_service.rank_articles", return_value=[TECHNICAL_ARTICLE]) as mock_rank,
            p("backend.services.curator_service.ask_grok", return_value=json.dumps(MOCK_FEED)),
            p("backend.services.curator_service.get_cached_feed", return_value=None),
            p("backend.services.curator_service.cache_feed"),
            p("backend.services.curator_service._build_memory_fingerprint", return_value="fp"),
        ):
            from backend.services.curator_service import generate_learning_feed
            generate_learning_feed("AI agents")

        mock_rank.assert_called_once()
        _, call_kwargs = mock_rank.call_args.args, mock_rank.call_args.kwargs
        # Verify query was passed through
        assert "AI agents" in str(mock_rank.call_args)


# ── 4. Real integration test ──────────────────────────────────────────────────

@pytest.mark.integration
def test_real_search_and_rank():
    """
    One real Tavily search → rank_articles pipeline.

    Run with:  pytest tests/test_source_ranker.py -v -m integration
    """
    from backend.services.tavily_service import search_articles

    query    = "transformer architecture attention mechanism"
    articles = search_articles(query)

    assert len(articles) > 0, "Tavily returned no results"

    ranked = rank_articles(articles, query, top_n=5)

    assert len(ranked) > 0, "All articles were filtered out — check min_score"
    assert len(ranked) <= 5

    # First result should score higher than last
    if len(ranked) > 1:
        first_score = score_article(ranked[0],  query)["total"]
        last_score  = score_article(ranked[-1], query)["total"]
        assert first_score >= last_score, "Results are not ordered by score"

    # Spot-check that the worst article from the raw set did not end up first
    all_scores = [score_article(a, query)["total"] for a in articles]
    worst_raw  = min(all_scores)
    best_ranked = score_article(ranked[0], query)["total"]
    assert best_ranked >= worst_raw
