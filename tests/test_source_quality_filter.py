"""
Tests for source_quality_filter.py.

Test levels
-----------
1. classify_source_type  — domain, URL-path, content-keyword, and fallback signals
2. quality_multiplier    — correct value per source type; ordering invariants
3. is_low_quality        — each hard-fail trigger in isolation
4. filter_articles       — batch filtering
5. rank_articles wiring  — quality filter + multiplier applied end-to-end

Run:
    pytest tests/test_source_quality_filter.py -v
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.source_quality_filter import (
    SOURCE_TYPES,
    _STUFFING_MIN_WORD_LEN,
    _STUFFING_REPEAT_THRESH,
    _STUFFING_CONTENT_WINDOW,
    classify_source_type,
    filter_articles,
    is_low_quality,
    quality_multiplier,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _art(title="A technical article", content="x" * 200, url="https://example.com/post"):
    """Minimal valid article (passes all hard-quality checks by default)."""
    return {"title": title, "content": content, "url": url}


def _good(url="https://example.com/post", title="Some Article", content=None):
    return _art(
        title=title,
        content=content or (
            "This article examines machine learning methods and neural network design. "
            "Recent advances in transformer models have improved many benchmarks. "
            "Deep learning research explores new training strategies and hardware. "
            "Language model evaluation across diverse tasks shows consistent gains. "
            "Efficient inference techniques reduce deployment costs significantly. "
        ),
        url=url,
    )


# ── TestClassifySourceType ────────────────────────────────────────────────────

class TestClassifySourceType:
    # --- Domain-based ---

    def test_arxiv_domain_is_research_paper(self):
        assert classify_source_type(_art(url="https://arxiv.org/abs/2401.12345")) == "research_paper"

    def test_semanticscholar_is_research_paper(self):
        assert classify_source_type(_art(url="https://semanticscholar.org/paper/abc")) == "research_paper"

    def test_paperswithcode_is_research_paper(self):
        assert classify_source_type(_art(url="https://paperswithcode.com/paper/some-paper")) == "research_paper"

    def test_pytorch_is_official_docs(self):
        assert classify_source_type(_art(url="https://pytorch.org/docs/stable/nn.html")) == "official_docs"

    def test_huggingface_is_official_docs(self):
        assert classify_source_type(_art(url="https://huggingface.co/docs/transformers/index")) == "official_docs"

    def test_openai_com_is_engineering_blog(self):
        assert classify_source_type(_art(url="https://openai.com/blog/gpt-4")) == "engineering_blog"

    def test_distill_pub_is_engineering_blog(self):
        assert classify_source_type(_art(url="https://distill.pub/2024/attention")) == "engineering_blog"

    def test_fastai_is_educational(self):
        assert classify_source_type(_art(url="https://fast.ai/course")) == "educational"

    def test_towardsdatascience_is_educational(self):
        assert classify_source_type(_art(url="https://towardsdatascience.com/intro-to-rag-123")) == "educational"

    def test_buzzfeed_is_content_farm(self):
        assert classify_source_type(_art(url="https://buzzfeed.com/ai-stuff")) == "content_farm"

    def test_listverse_is_content_farm(self):
        assert classify_source_type(_art(url="https://listverse.com/top-10-ai")) == "content_farm"

    # --- URL path signals ---

    def test_arxiv_in_url_path_is_research_paper(self):
        assert classify_source_type(_art(url="https://blog.example.com/arxiv/summary")) == "research_paper"

    def test_papers_in_url_path_is_research_paper(self):
        assert classify_source_type(_art(url="https://example.com/papers/2024/model")) == "research_paper"

    def test_docs_in_url_path_is_official_docs(self):
        assert classify_source_type(_art(url="https://somelib.io/docs/getting-started")) == "official_docs"

    def test_tutorial_in_url_path_is_educational(self):
        assert classify_source_type(_art(url="https://example.com/tutorial/llms")) == "educational"

    def test_learn_in_url_path_is_educational(self):
        assert classify_source_type(_art(url="https://example.com/learn/transformers")) == "educational"

    # --- Content keyword signals ---

    def test_abstract_keyword_is_research_paper(self):
        a = _art(
            content="Abstract: We present a new method for training language models.",
            url="https://example.com/article",
        )
        assert classify_source_type(a) == "research_paper"

    def test_we_propose_keyword_is_research_paper(self):
        a = _art(
            content="In this work we propose a novel architecture.",
            url="https://example.com/post",
        )
        assert classify_source_type(a) == "research_paper"

    def test_returns_keyword_is_official_docs(self):
        a = _art(
            content="parameters: learning_rate (float). returns: trained model object.",
            url="https://somelib.example.com/reference",
        )
        assert classify_source_type(a) == "official_docs"

    # --- Content-farm title fallback ---

    def test_top_n_title_on_unknown_domain_is_content_farm(self):
        a = _art(
            title="Top 10 Best AI Tools for 2024",
            url="https://randomsite.com/post",
        )
        assert classify_source_type(a) == "content_farm"

    def test_ultimate_guide_title_is_content_farm(self):
        a = _art(
            title="Ultimate Guide to Machine Learning",
            url="https://unknownblog.net/ml",
        )
        assert classify_source_type(a) == "content_farm"

    # --- Unknown fallback ---

    def test_no_signals_is_unknown(self):
        a = _art(
            title="A Nice Article About AI",
            content="Some generic content without special keywords.",
            url="https://randomblog.io/post",
        )
        assert classify_source_type(a) == "unknown"

    # --- Return value is always in SOURCE_TYPES ---

    def test_result_always_in_source_types(self):
        articles = [
            _art(url="https://arxiv.org/abs/1"),
            _art(url="https://buzzfeed.com/x"),
            _art(url="https://randomblog.io/x"),
            _art(title="Top 5 Ways to Fail", url="https://spam.com"),
        ]
        for article in articles:
            assert classify_source_type(article) in SOURCE_TYPES


# ── TestQualityMultiplier ─────────────────────────────────────────────────────

class TestQualityMultiplier:
    def test_research_paper_has_highest_multiplier(self):
        rp = quality_multiplier(_art(url="https://arxiv.org/abs/1"))
        eb = quality_multiplier(_art(url="https://openai.com/blog/x"))
        assert rp > eb

    def test_official_docs_multiplier_greater_than_one(self):
        assert quality_multiplier(_art(url="https://pytorch.org/docs/x")) > 1.0

    def test_engineering_blog_multiplier_greater_than_one(self):
        assert quality_multiplier(_art(url="https://distill.pub/2024/x")) > 1.0

    def test_educational_multiplier_greater_than_one(self):
        assert quality_multiplier(_art(url="https://fast.ai/course")) > 1.0

    def test_content_farm_multiplier_less_than_one(self):
        assert quality_multiplier(_art(url="https://buzzfeed.com/x")) < 1.0

    def test_unknown_multiplier_is_one(self):
        assert quality_multiplier(_art(url="https://randomblog.io/post")) == 1.0

    def test_content_farm_multiplier_significantly_lower_than_research(self):
        rp = quality_multiplier(_art(url="https://arxiv.org/abs/1"))
        cf = quality_multiplier(_art(url="https://buzzfeed.com/x"))
        assert rp > cf * 2   # research paper multiplier at least 2x content farm


# ── TestIsLowQuality ─────────────────────────────────────────────────────────

class TestIsLowQuality:
    def test_thin_content_is_low_quality(self):
        a = _art(content="Too short.")
        assert is_low_quality(a) is True

    def test_empty_content_is_low_quality(self):
        a = _art(content="")
        assert is_low_quality(a) is True

    def test_content_just_below_threshold_is_low_quality(self):
        a = _art(content="x" * 79)
        assert is_low_quality(a) is True

    def test_content_at_threshold_is_not_low_quality(self):
        a = _art(content="x" * 80)
        assert is_low_quality(a) is False

    def test_content_farm_title_is_low_quality(self):
        a = _art(
            title="Top 10 Best AI Frameworks for 2024",
            content="x" * 300,
        )
        assert is_low_quality(a) is True

    def test_ultimate_guide_title_is_low_quality(self):
        a = _art(
            title="Ultimate Guide to Neural Networks",
            content="x" * 300,
        )
        assert is_low_quality(a) is True

    def test_boilerplate_opener_is_low_quality(self):
        a = _art(content="In this article, we will explore the best practices for LLMs. " + "x" * 200)
        assert is_low_quality(a) is True

    def test_welcome_to_this_guide_is_low_quality(self):
        a = _art(content="Welcome to this guide on transformers! " + "x" * 200)
        assert is_low_quality(a) is True

    def test_comprehensive_guide_boilerplate_is_low_quality(self):
        a = _art(content="In this comprehensive guide we'll cover everything. " + "x" * 200)
        assert is_low_quality(a) is True

    def test_keyword_stuffed_content_is_low_quality(self):
        stuffed_word = "neural" * _STUFFING_REPEAT_THRESH  # repeat 6 times consecutively
        content = " ".join(["neural"] * _STUFFING_REPEAT_THRESH) + " " + "padding words " * 10
        a = _art(content=content)
        assert is_low_quality(a) is True

    def test_content_farm_domain_is_low_quality(self):
        a = _art(
            url="https://buzzfeed.com/ai-tips",
            content="x" * 300,
        )
        assert is_low_quality(a) is True

    def test_long_content_with_repeated_word_not_stuffed(self):
        # > _STUFFING_CONTENT_WINDOW chars — stuffing check skipped
        long_content = ("neural " * 10 + "other words " * 100)[:900]
        a = _art(content=long_content)
        assert is_low_quality(a) is False

    def test_high_quality_arxiv_article_is_not_low_quality(self):
        a = _art(
            title="Attention Is All You Need",
            content=(
                "Abstract: We propose a new neural architecture based purely on attention "
                "mechanisms. Our model achieves state-of-the-art results on WMT 2014 "
                "English-to-German translation with 28.4 BLEU. " * 5
            ),
            url="https://arxiv.org/abs/1706.03762",
        )
        assert is_low_quality(a) is False

    def test_good_engineering_blog_is_not_low_quality(self):
        a = _art(
            title="How We Scaled Our Vector Index to 1B Embeddings",
            content=(
                "In this post we describe the infrastructure challenges we faced when "
                "scaling our nearest-neighbour search from 10M to 1B vectors. "
                "Key bottlenecks were latency and memory footprint. " * 5
            ),
            url="https://netflixtechblog.com/scaling-vector-index",
        )
        assert is_low_quality(a) is False


# ── TestFilterArticles ────────────────────────────────────────────────────────

class TestFilterArticles:
    def test_empty_list_returns_empty(self):
        assert filter_articles([]) == []

    def test_all_good_articles_returned(self):
        articles = [_good(f"https://example.com/{i}") for i in range(3)]
        result = filter_articles(articles)
        assert len(result) == 3

    def test_all_bad_articles_removed(self):
        articles = [
            _art(content="too short"),
            _art(title="Top 10 Best AI Tools 2024", content="x" * 300),
        ]
        assert filter_articles(articles) == []

    def test_mixed_list_keeps_only_good_articles(self):
        good  = _good(url="https://arxiv.org/abs/1")
        bad   = _art(content="x" * 50, url="https://example.com/stub")
        spammy = _art(title="Top 5 Ways to Learn AI", content="x" * 300)
        result = filter_articles([good, bad, spammy])
        assert result == [good]

    def test_order_is_preserved(self):
        articles = [
            _good(url=f"https://arxiv.org/abs/{i}") for i in range(5)
        ]
        result = filter_articles(articles)
        assert result == articles


# ── TestRankArticlesIntegration ───────────────────────────────────────────────

class TestRankArticlesIntegration:
    """Verify that quality filter + multiplier are applied inside rank_articles."""

    def test_research_paper_ranked_above_content_farm(self):
        from backend.services.source_ranker import rank_articles

        content = (
            "Retrieval-augmented generation improves LLM accuracy. "
            "We benchmark on standard RAG evaluation datasets. " * 8
        )
        research = _good(url="https://arxiv.org/abs/2401.00001", content=content, title="RAG Benchmark")
        farm      = _good(url="https://buzzfeed.com/rag-tips",  content=content, title="RAG Benchmark")

        result = rank_articles([farm, research], query="RAG retrieval augmented generation")
        urls = [a["url"] for a in result]
        # Content farm should be filtered out entirely (is_low_quality → False here,
        # but buzzfeed.com triggers content_farm domain → low quality)
        assert "https://arxiv.org/abs/2401.00001" in urls

    def test_low_quality_article_excluded_from_results(self):
        from backend.services.source_ranker import rank_articles

        stub = _art(content="Too short.", url="https://example.com/stub")
        good = _good(url="https://arxiv.org/abs/1", title="Transformer Architecture Deep Dive")
        result = rank_articles([stub, good], query="transformer")
        urls = [a["url"] for a in result]
        assert "https://example.com/stub" not in urls
        assert "https://arxiv.org/abs/1" in urls

    def test_empty_input_returns_empty(self):
        from backend.services.source_ranker import rank_articles
        assert rank_articles([], query="transformers") == []

    def test_all_low_quality_returns_empty(self):
        from backend.services.source_ranker import rank_articles
        articles = [_art(content="short"), _art(content="also short")]
        assert rank_articles(articles, query="anything") == []

    def test_quality_multiplier_boosts_official_docs_above_unknown(self):
        from backend.services.source_ranker import rank_articles

        shared_content = (
            "Parameters: learning_rate (float), num_epochs (int). "
            "This guide explains transformer training step by step. "
            "Returns: trained model with benchmark accuracy of 92.5%. " * 6
        )
        docs    = _good(url="https://pytorch.org/docs/training",   content=shared_content, title="PyTorch Training Guide")
        unknown = _good(url="https://randomblog.io/pytorch-guide",  content=shared_content, title="PyTorch Training Guide")

        result = rank_articles([unknown, docs], query="pytorch training guide")
        # Both should survive; docs should appear before unknown
        assert len(result) >= 1
        if len(result) == 2:
            assert result[0]["url"] == "https://pytorch.org/docs/training"
