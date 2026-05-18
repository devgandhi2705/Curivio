"""
Tests for similarity_service.py.

Test levels
-----------
1. token_overlap        — Jaccard correctness, stop words, acronym expansion, edge cases
2. are_duplicate_articles — URL identity, title similarity triggers
3. deduplicate_articles — batch dedup logic, order preservation
4. find_similar_in      — threshold behaviour, best-match selection
5. deduplicate_topics   — within-list topic dedup, keeps first occurrence
6. is_fresh_summary     — freshness vs repetition detection
7. Pipeline wiring      — rank_articles deduplicates articles end-to-end

Run:
    pytest tests/test_similarity_service.py -v
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.similarity_service import (
    ARTICLE_DUP_THRESHOLD,
    SUMMARY_SIM_THRESHOLD,
    TOPIC_SIM_THRESHOLD,
    are_duplicate_articles,
    deduplicate_articles,
    deduplicate_topics,
    find_similar_in,
    is_fresh_summary,
    token_overlap,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _art(title="Some Article", url="https://example.com/post", content="content"):
    return {"title": title, "url": url, "content": content}


def _topic(title, difficulty="intermediate"):
    return {"title": title, "reason": f"Learn about {title}", "difficulty": difficulty}


# ── TestTokenOverlap ──────────────────────────────────────────────────────────

class TestTokenOverlap:
    def test_identical_strings_return_one(self):
        assert token_overlap("transformer attention", "transformer attention") == 1.0

    def test_no_shared_words_return_zero(self):
        assert token_overlap("gradient descent", "vector database") == 0.0

    def test_partial_overlap(self):
        score = token_overlap("transformer model", "transformer architecture")
        assert 0.0 < score < 1.0

    def test_empty_both_returns_one(self):
        assert token_overlap("", "") == 1.0

    def test_empty_one_returns_zero(self):
        assert token_overlap("transformer", "") == 0.0
        assert token_overlap("", "transformer") == 0.0

    def test_stop_words_excluded(self):
        # "the" and "a" are stop words — removing them should not affect overlap
        score_with    = token_overlap("the transformer model", "a transformer model")
        score_without = token_overlap("transformer model", "transformer model")
        assert score_with == score_without == 1.0

    def test_short_words_excluded(self):
        # "to" and "in" are short stop words; "go" and "be" are short non-stop
        score = token_overlap("go", "be")
        # Both should be below _MIN_TOKEN_LEN and filtered → both empty
        assert score == 1.0  # vacuously equal after filtering

    def test_acronym_rag_expands_to_match_full_form(self):
        # "RAG" should expand to "retrieval augmented generation"
        score = token_overlap("RAG Pipelines", "Retrieval Augmented Generation")
        assert score >= TOPIC_SIM_THRESHOLD

    def test_acronym_llm_expands_to_match_full_form(self):
        score = token_overlap("Fine-tuning LLMs", "Fine-Tuning Large Language Models")
        assert score >= TOPIC_SIM_THRESHOLD

    def test_acronym_mlm_expands(self):
        score = token_overlap("MLM pretraining", "Masked Language Model pretraining")
        assert score >= TOPIC_SIM_THRESHOLD

    def test_symmetric(self):
        a, b = "vector database indexing", "database indexing vector"
        assert token_overlap(a, b) == token_overlap(b, a)

    def test_high_overlap_for_near_identical_topics(self):
        score = token_overlap(
            "Transformer Self-Attention Mechanism",
            "Self-Attention Mechanism in Transformers",
        )
        assert score >= 0.50

    def test_low_overlap_for_unrelated_topics(self):
        score = token_overlap("sorting algorithms", "neural network training")
        assert score < 0.20


# ── TestAreDuplicateArticles ──────────────────────────────────────────────────

class TestAreDuplicateArticles:
    def test_identical_url_is_duplicate(self):
        a = _art(url="https://arxiv.org/abs/2401.0001", title="Paper A")
        b = _art(url="https://arxiv.org/abs/2401.0001", title="Paper B")
        assert are_duplicate_articles(a, b) is True

    def test_url_with_www_and_without_are_duplicate(self):
        a = _art(url="https://www.example.com/post")
        b = _art(url="https://example.com/post")
        assert are_duplicate_articles(a, b) is True

    def test_high_title_overlap_is_duplicate(self):
        a = _art(title="RAG Pipeline Optimization for LLM Inference")
        b = _art(title="RAG Pipeline Optimization for LLM Applications", url="https://other.com/x")
        assert are_duplicate_articles(a, b) is True

    def test_different_title_and_url_is_not_duplicate(self):
        a = _art(title="Vector Databases for AI", url="https://example.com/a")
        b = _art(title="Training Transformers at Scale", url="https://example.com/b")
        assert are_duplicate_articles(a, b) is False

    def test_different_url_same_title_is_duplicate(self):
        a = _art(title="Introduction to Transformers", url="https://site-a.com/intro")
        b = _art(title="Introduction to Transformers", url="https://site-b.com/intro")
        assert are_duplicate_articles(a, b) is True

    def test_same_domain_different_article_is_not_duplicate(self):
        a = _art(title="How Attention Works", url="https://arxiv.org/abs/1001")
        b = _art(title="Scaling Laws for Neural Language Models", url="https://arxiv.org/abs/1002")
        assert are_duplicate_articles(a, b) is False

    def test_empty_titles_both_are_duplicate(self):
        a = _art(title="", url="https://a.com")
        b = _art(title="", url="https://b.com")
        # Both empty → vacuously identical token sets → overlap = 1.0 ≥ threshold
        assert are_duplicate_articles(a, b) is True


# ── TestDeduplicateArticles ───────────────────────────────────────────────────

class TestDeduplicateArticles:
    def test_empty_list_returns_empty(self):
        assert deduplicate_articles([]) == []

    def test_single_article_returned(self):
        a = _art(title="Unique Article")
        assert deduplicate_articles([a]) == [a]

    def test_all_unique_articles_returned(self):
        articles = [
            _art(title="Transformers", url="https://a.com"),
            _art(title="Vector Databases", url="https://b.com"),
            _art(title="LLM Fine-tuning", url="https://c.com"),
        ]
        result = deduplicate_articles(articles)
        assert len(result) == 3

    def test_duplicate_by_url_removed(self):
        a = _art(title="Article", url="https://example.com/post")
        b = _art(title="Article Updated", url="https://example.com/post")
        result = deduplicate_articles([a, b])
        assert len(result) == 1
        assert result[0] is a  # first occurrence kept

    def test_duplicate_by_title_removed(self):
        a = _art(title="RAG Pipeline Optimization for LLM Inference", url="https://a.com")
        b = _art(title="RAG Pipeline Optimization for LLM Applications", url="https://b.com")
        result = deduplicate_articles([a, b])
        assert len(result) == 1
        assert result[0] is a

    def test_first_occurrence_kept_not_second(self):
        a = _art(title="Attention Mechanisms Explained", url="https://a.com")
        b = _art(title="Attention Mechanisms Explained In Depth", url="https://b.com")
        c = _art(title="Completely Different Topic", url="https://c.com")
        result = deduplicate_articles([a, b, c])
        assert a in result
        assert b not in result
        assert c in result

    def test_order_of_unique_articles_preserved(self):
        articles = [
            _art(title="Alpha Article", url="https://a.com"),
            _art(title="Beta Article", url="https://b.com"),
            _art(title="Gamma Article", url="https://c.com"),
        ]
        result = deduplicate_articles(articles)
        assert [r["url"] for r in result] == ["https://a.com", "https://b.com", "https://c.com"]

    def test_does_not_mutate_input(self):
        original = [_art(title="A", url="https://a.com"), _art(title="A copy", url="https://a.com")]
        copy = list(original)
        deduplicate_articles(original)
        assert original == copy


# ── TestFindSimilarIn ─────────────────────────────────────────────────────────

class TestFindSimilarIn:
    def test_empty_seen_returns_none(self):
        assert find_similar_in("Transformer Architecture", []) is None

    def test_exact_match_returns_that_title(self):
        result = find_similar_in("RAG Pipelines", ["RAG Pipelines", "Vector Databases"])
        assert result == "RAG Pipelines"

    def test_similar_above_threshold_returned(self):
        # "RAG Pipelines" vs "Retrieval Augmented Generation" → high overlap after expansion
        result = find_similar_in(
            "RAG Pipelines",
            ["Retrieval Augmented Generation", "Completely Unrelated Thing"],
            threshold=TOPIC_SIM_THRESHOLD,
        )
        assert result == "Retrieval Augmented Generation"

    def test_dissimilar_below_threshold_returns_none(self):
        result = find_similar_in(
            "Gradient Descent",
            ["Vector Database Indexing", "Attention Mechanism Explained"],
            threshold=TOPIC_SIM_THRESHOLD,
        )
        assert result is None

    def test_returns_best_match_when_multiple_above_threshold(self):
        # "LLM Fine-tuning" should match "LLM Fine-tuning for Classification"
        # better than "LLM Training Basics"
        result = find_similar_in(
            "LLM Fine-tuning",
            ["LLM Training Basics", "LLM Fine-tuning for Classification"],
            threshold=0.30,
        )
        assert result == "LLM Fine-tuning for Classification"

    def test_custom_threshold_higher_requires_better_match(self):
        # With threshold=1.0 only exact token sets match
        result = find_similar_in(
            "Transformer Model",
            ["Transformer Architecture"],
            threshold=1.0,
        )
        assert result is None

    def test_custom_threshold_lower_captures_loose_matches(self):
        # "Transformer Model" vs "Transformer Architecture Paper":
        # tokens_a={transformer, model}, tokens_b={transformer, architecture, paper}
        # intersection={transformer}, union={transformer, model, architecture, paper}
        # Jaccard = 1/4 = 0.25, exactly at threshold
        result = find_similar_in(
            "Transformer Model",
            ["Transformer Architecture Paper"],
            threshold=0.25,
        )
        assert result is not None


# ── TestDeduplicateTopics ─────────────────────────────────────────────────────

class TestDeduplicateTopics:
    def test_empty_list_returns_empty(self):
        assert deduplicate_topics([]) == []

    def test_all_unique_topics_returned(self):
        topics = [
            _topic("Transformer Architecture"),
            _topic("Vector Databases"),
            _topic("Gradient Descent"),
            _topic("Attention Mechanisms"),
        ]
        result = deduplicate_topics(topics)
        assert len(result) == 4

    def test_near_duplicate_topic_removed(self):
        topics = [
            _topic("RAG Pipelines"),
            _topic("Retrieval Augmented Generation"),  # near-duplicate of first
            _topic("Vector Databases"),
            _topic("Attention Mechanisms"),
        ]
        result = deduplicate_topics(topics)
        titles = [t["title"] for t in result]
        # First occurrence kept, near-duplicate dropped
        assert "RAG Pipelines" in titles
        assert "Retrieval Augmented Generation" not in titles

    def test_first_occurrence_kept(self):
        topics = [
            _topic("Fine-tuning LLMs"),
            _topic("Fine-Tuning Large Language Models"),
        ]
        result = deduplicate_topics(topics)
        assert result[0]["title"] == "Fine-tuning LLMs"

    def test_exact_duplicate_title_removed(self):
        topics = [_topic("BERT Pretraining"), _topic("BERT Pretraining")]
        result = deduplicate_topics(topics)
        assert len(result) == 1

    def test_difficulty_preserved_on_kept_topic(self):
        topics = [
            _topic("Transformer Architecture", difficulty="beginner"),
            _topic("Transformer Design Patterns", difficulty="advanced"),
        ]
        result = deduplicate_topics(topics, threshold=0.40)
        # Exactly one kept; its difficulty should be that of the first
        assert result[0]["difficulty"] == "beginner"

    def test_custom_strict_threshold_keeps_all_unique(self):
        topics = [
            _topic("Transformer Architecture"),
            _topic("Transformer Models"),
        ]
        # With threshold=1.0 only exact token sets are duplicates
        result = deduplicate_topics(topics, threshold=1.0)
        assert len(result) == 2


# ── TestIsFreshSummary ────────────────────────────────────────────────────────

class TestIsFreshSummary:
    def test_empty_recent_is_always_fresh(self):
        assert is_fresh_summary("New Breakthrough in LLM Efficiency", []) is True

    def test_dissimilar_title_is_fresh(self):
        assert is_fresh_summary(
            "Vector Database Indexing Strategies",
            ["Fine-tuning Methods for BERT", "Scaling Laws in GPT"],
        ) is True

    def test_similar_title_is_not_fresh(self):
        # "LLM Training Efficiency" vs "LLM Efficiency Training" → high overlap
        assert is_fresh_summary(
            "LLM Training Efficiency Improvements",
            ["LLM Efficiency Training Methods", "Other Unrelated News"],
            threshold=SUMMARY_SIM_THRESHOLD,
        ) is False

    def test_near_identical_title_is_not_fresh(self):
        title = "RAG Pipelines Achieve New Benchmarks"
        recent = ["RAG Pipeline Benchmarks Achieved", "Some Other News"]
        assert is_fresh_summary(title, recent, threshold=SUMMARY_SIM_THRESHOLD) is False

    def test_slightly_different_framing_is_fresh_at_higher_threshold(self):
        # At a strict threshold, slightly different framings should be considered fresh
        assert is_fresh_summary(
            "Efficient Attention for Long Contexts",
            ["Flash Attention Memory Savings"],
            threshold=0.80,  # very strict
        ) is True

    def test_returns_true_when_all_recent_are_unrelated(self):
        assert is_fresh_summary(
            "Mixture of Experts Scaling",
            ["LSTM Sequence Modelling", "Bayesian Neural Networks", "Graph Neural Networks"],
        ) is True


# ── TestPipelineWiring ────────────────────────────────────────────────────────

class TestPipelineWiring:
    """
    Verify that rank_articles calls deduplicate_articles as part of its pipeline.
    These tests use mocked scoring to isolate the deduplication step.
    """

    def test_rank_articles_deduplicates_identical_url(self):
        from backend.services.source_ranker import rank_articles

        shared_content = (
            "Transformer architecture uses self-attention mechanisms for parallel "
            "processing. Benchmark results show 40% latency reduction. The model "
            "achieves state-of-the-art performance across multiple NLP tasks. " * 3
        )
        a = _art(title="Attention Is All You Need", url="https://arxiv.org/abs/1706", content=shared_content)
        b = _art(title="Attention Is All You Need — Mirror", url="https://arxiv.org/abs/1706", content=shared_content)

        result = rank_articles([a, b], query="transformer attention")
        urls = [r["url"] for r in result]
        # Only one of the identical-URL pair should survive
        assert urls.count("https://arxiv.org/abs/1706") <= 1

    def test_rank_articles_deduplicates_near_identical_titles(self):
        from backend.services.source_ranker import rank_articles

        shared_content = (
            "RAG pipeline optimization improves retrieval accuracy. "
            "Experiments on benchmark datasets show 25% improvement. "
            "Implementation details include vector indexing and reranking strategies. " * 3
        )
        a = _art(
            title="RAG Pipeline Optimization for LLM Inference",
            url="https://site-a.com/rag",
            content=shared_content,
        )
        b = _art(
            title="RAG Pipeline Optimization for LLM Applications",
            url="https://site-b.com/rag",
            content=shared_content,
        )
        result = rank_articles([a, b], query="RAG retrieval augmented generation")
        # The near-duplicate should be removed; at most one survives
        assert len(result) <= 1

    def test_rank_articles_keeps_distinct_articles(self):
        from backend.services.source_ranker import rank_articles

        def make(title, url):
            return _art(
                title=title,
                url=url,
                # Varied content — no single word repeated 6+ times in <800 chars
                content=(
                    "Research demonstrates measurable performance gains on standard benchmarks. "
                    "Engineers apply these methods in production systems at scale. "
                    "The approach reduces computational costs while maintaining accuracy. "
                    "Experimental results show improvements across diverse evaluation tasks. "
                    "Practical deployment requires careful consideration of latency trade-offs. "
                ),
            )

        articles = [
            make("Understanding Transformer Architecture", "https://a.com/transformers"),
            make("Vector Database Indexing Strategies", "https://b.com/vectors"),
            make("Parameter Efficient Fine-Tuning Methods", "https://c.com/peft"),
        ]
        result = rank_articles(articles, query="machine learning deep learning")
        assert len(result) >= 2  # distinct articles survive


class TestCuratorRecentNewsWiring:
    """Verify that recent news titles are injected into the memory context."""

    def test_recent_news_titles_appear_in_memory_context(self):
        from backend.services.curator_service import _build_memory_context

        mock_digests = [
            {"news_title": "Flash Attention 3 Halves Inference Cost", "id": 1},
            {"news_title": "Mixture of Experts Scales to 1 Trillion Parameters", "id": 2},
        ]

        with patch("backend.services.curator_service.list_digests", return_value=mock_digests), \
             patch("backend.services.curator_service.get_top_user_interests", return_value=[]), \
             patch("backend.services.curator_service.get_suppressed_topics", return_value=[]):
            context = _build_memory_context()

        assert "Flash Attention 3 Halves Inference Cost" in context
        assert "Mixture of Experts Scales to 1 Trillion Parameters" in context

    def test_no_recent_news_context_omitted_gracefully(self):
        from backend.services.curator_service import _build_memory_context

        with patch("backend.services.curator_service.list_digests", return_value=[]), \
             patch("backend.services.curator_service.get_top_user_interests", return_value=[]), \
             patch("backend.services.curator_service.get_suppressed_topics", return_value=[]):
            context = _build_memory_context()

        # Should still return a valid context string without crashing
        assert isinstance(context, str)

    def test_digest_db_error_does_not_break_context(self):
        from backend.services.curator_service import _build_memory_context

        with patch("backend.services.curator_service.list_digests", side_effect=Exception("DB error")), \
             patch("backend.services.curator_service.get_top_user_interests", return_value=[]), \
             patch("backend.services.curator_service.get_suppressed_topics", return_value=[]):
            # Should not raise; DB error is swallowed gracefully
            context = _build_memory_context()

        assert isinstance(context, str)
