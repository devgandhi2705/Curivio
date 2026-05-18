"""
Tests for source_analyzer.py.

Test levels:
  1. Helper unit tests     — pure string processing, zero I/O
  2. analyze_sources tests — full analysis dict with known inputs
  3. format_analysis tests — prompt-string rendering
  4. Curator wiring test   — mocked pipeline verifying analysis is injected
  5. Integration test      — one real Groq call (skip by default)

Run non-integration tests:
    pytest tests/test_source_analyzer.py -v

Run the live integration test:
    pytest tests/test_source_analyzer.py -v -m integration
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.source_analyzer import (
    _detect_contrastive_signals,
    _empty_analysis,
    _extract_themes,
    _find_repeated_insights,
    _identify_trends,
    _tokenize,
    _unique_domains,
    analyze_sources,
    format_analysis_for_prompt,
)


# ── Article fixtures ──────────────────────────────────────────────────────────

def _art(title="", content="", url="https://example.com/post"):
    return {"title": title, "content": content, "url": url}


RAG_ARTICLES = [
    _art(
        title="RAG Pipeline Optimization for LLM Inference",
        content="Retrieval-augmented generation improves accuracy by 30%. However, latency increases.",
        url="https://arxiv.org/abs/001",
    ),
    _art(
        title="New RAG Architecture Reduces Inference Latency",
        content="A novel approach challenges existing pipelines. Trade-off between speed and accuracy.",
        url="https://huggingface.co/blog/rag",
    ),
    _art(
        title="Vector Databases for Efficient RAG Retrieval",
        content="Alternatives to dense retrieval show promise. Debate continues over sparse vs dense.",
        url="https://github.com/vectordb/paper",
    ),
    _art(
        title="Scaling RAG Systems in Production",
        content="Emerging challenges in production include latency and cost. New solutions are needed.",
        url="https://blog.langchain.dev/scaling",
    ),
    _art(
        title="LLM Inference Benchmarks 2026",
        content="Latest benchmarks show breakthroughs in throughput. Limitations remain for edge deployment.",
        url="https://paperswithcode.com/bench",
    ),
]

SINGLE_ARTICLE = [
    _art(title="Introduction to Neural Networks", content="Deep learning basics.", url="https://example.com/1")
]

EMPTY_ARTICLES: list = []


# ── 1. Helper unit tests ──────────────────────────────────────────────────────

class TestTokenize:
    def test_lowercases_text(self):
        assert all(w == w.lower() for w in _tokenize("Hello World"))

    def test_removes_stop_words(self):
        result = _tokenize("the quick brown fox")
        assert "the" not in result

    def test_removes_punctuation(self):
        result = _tokenize("hello, world!")
        assert all(c.isalnum() or c == "_" for w in result for c in w)

    def test_removes_single_char_words(self):
        result = _tokenize("a b c hello")
        assert all(len(w) > 1 for w in result)

    def test_returns_list(self):
        assert isinstance(_tokenize("test"), list)

    def test_empty_string_returns_empty(self):
        assert _tokenize("") == []


class TestExtractThemes:
    def test_returns_list(self):
        assert isinstance(_extract_themes(RAG_ARTICLES, "RAG inference"), list)

    def test_finds_word_in_multiple_titles(self):
        # "inference" appears in multiple titles and passes the min-length-4 filter
        themes = _extract_themes(RAG_ARTICLES, "unrelated query")
        assert "inference" in themes

    def test_query_words_excluded(self):
        themes = _extract_themes(RAG_ARTICLES, "RAG inference")
        # "rag" and "inference" are in the query — should be excluded
        assert "rag" not in themes
        assert "inference" not in themes

    def test_single_source_word_excluded(self):
        # "benchmarks" only appears in one title
        themes = _extract_themes(RAG_ARTICLES, "")
        # Should only include words from 2+ articles
        # Verify no theme appears in fewer than 2 titles
        title_texts = [a["title"].lower() for a in RAG_ARTICLES]
        for theme in themes:
            count = sum(1 for t in title_texts if theme in t)
            assert count >= 2, f"Theme '{theme}' appears in only {count} articles"

    def test_short_words_excluded(self):
        themes = _extract_themes(RAG_ARTICLES, "")
        assert all(len(t) >= 4 for t in themes)

    def test_empty_articles_returns_empty(self):
        assert _extract_themes([], "query") == []


class TestFindRepeatedInsights:
    def test_returns_list(self):
        assert isinstance(_find_repeated_insights(RAG_ARTICLES), list)

    def test_finds_repeated_bigrams(self):
        # "rag pipeline" or similar bigrams appear in multiple titles
        articles = [
            _art(title="RAG pipeline for production"),
            _art(title="Scaling RAG pipeline systems"),
            _art(title="Unrelated article title"),
        ]
        insights = _find_repeated_insights(articles)
        assert "rag pipeline" in insights

    def test_single_occurrence_bigram_excluded(self):
        articles = [
            _art(title="unique phrase only once"),
            _art(title="another article"),
        ]
        insights = _find_repeated_insights(articles)
        # No bigrams should appear in both titles
        for insight in insights:
            count = sum(1 for a in articles if insight in a["title"].lower())
            assert count >= 2

    def test_empty_articles_returns_empty(self):
        assert _find_repeated_insights([]) == []


class TestIdentifyTrends:
    def test_returns_list(self):
        assert isinstance(_identify_trends(RAG_ARTICLES), list)

    def test_detects_new_keyword(self):
        articles = [_art(title="New RAG Architecture Released")]
        trends = _identify_trends(articles)
        assert len(trends) > 0

    def test_detects_emerging_keyword(self):
        articles = [_art(title="Emerging Trends in LLM Optimization")]
        trends = _identify_trends(articles)
        assert len(trends) > 0

    def test_no_trend_signals_returns_empty(self):
        articles = [_art(title="Understanding Transformers"), _art(title="Attention Mechanisms")]
        trends = _identify_trends(articles)
        assert trends == []

    def test_trend_phrase_contains_surrounding_words(self):
        articles = [_art(title="Novel Approach to RAG Retrieval")]
        trends = _identify_trends(articles)
        # Should return a phrase around "Novel", not just "Novel"
        assert any(len(t.split()) > 1 for t in trends)

    def test_empty_articles_returns_empty(self):
        assert _identify_trends([]) == []


class TestDetectContrastiveSignals:
    def test_returns_list(self):
        assert isinstance(_detect_contrastive_signals(RAG_ARTICLES), list)

    def test_finds_however_sentence(self):
        articles = [_art(content="The model performs well. However, latency is a concern.")]
        signals = _detect_contrastive_signals(articles)
        assert len(signals) > 0
        assert any("however" in s.lower() for s in signals)

    def test_finds_tradeoff_sentence(self):
        articles = [_art(content="There is a trade-off between speed and accuracy in these systems.")]
        signals = _detect_contrastive_signals(articles)
        assert len(signals) > 0

    def test_long_sentences_truncated(self):
        long_sentence = "However, " + "x " * 100 + "end."
        articles = [_art(content=long_sentence)]
        signals = _detect_contrastive_signals(articles)
        assert all(len(s) <= 125 for s in signals)

    def test_no_contrastive_content_returns_empty(self):
        articles = [_art(content="This is a great approach. It works well. Results are positive.")]
        assert _detect_contrastive_signals(articles) == []

    def test_deduplicates_identical_sentences(self):
        content = "However, this is a limitation. However, this is a limitation."
        articles = [_art(content=content)]
        signals = _detect_contrastive_signals(articles)
        assert len(signals) == 1


class TestUniqueDomains:
    def test_counts_unique_netlocs(self):
        articles = [
            _art(url="https://arxiv.org/abs/1"),
            _art(url="https://arxiv.org/abs/2"),    # same domain
            _art(url="https://github.com/repo"),
        ]
        assert len(_unique_domains(articles)) == 2

    def test_strips_www_prefix(self):
        articles = [
            _art(url="https://www.example.com/a"),
            _art(url="https://example.com/b"),
        ]
        # Both should resolve to the same domain
        assert len(_unique_domains(articles)) == 1

    def test_empty_articles_returns_empty(self):
        assert len(_unique_domains([])) == 0


# ── 2. analyze_sources tests ──────────────────────────────────────────────────

class TestAnalyzeSources:
    def test_returns_dict(self):
        result = analyze_sources(RAG_ARTICLES, "RAG LLM")
        assert isinstance(result, dict)

    def test_has_all_required_keys(self):
        result = analyze_sources(RAG_ARTICLES, "RAG")
        for key in ("themes", "repeated_insights", "trends", "contrastive",
                    "source_count", "domain_count", "domain_diversity"):
            assert key in result, f"Missing key: {key}"

    def test_source_count_matches_input(self):
        assert analyze_sources(RAG_ARTICLES, "RAG")["source_count"] == 5
        assert analyze_sources(SINGLE_ARTICLE, "neural")["source_count"] == 1

    def test_domain_count_correct(self):
        result = analyze_sources(RAG_ARTICLES, "RAG")
        # All 5 articles have different domains
        assert result["domain_count"] == 5

    def test_empty_input_returns_empty_analysis(self):
        result = analyze_sources([], "RAG")
        assert result["source_count"] == 0
        assert result["themes"] == []

    def test_diversity_high_for_diverse_sources(self):
        result = analyze_sources(RAG_ARTICLES, "RAG")
        # 5 articles, 5 domains → high diversity
        assert result["domain_diversity"] == "high"

    def test_diversity_low_for_same_domain(self):
        same_domain = [
            _art(url=f"https://samesite.com/post/{i}") for i in range(4)
        ]
        result = analyze_sources(same_domain, "test")
        assert result["domain_diversity"] == "low"

    def test_themes_list_capped(self):
        result = analyze_sources(RAG_ARTICLES, "")
        assert len(result["themes"]) <= 6

    def test_trends_detected_when_present(self):
        articles = [
            _art(title="New RAG Architecture Released", url="https://a.com/1"),
            _art(title="Emerging LLM Trends 2026",     url="https://b.com/2"),
        ]
        result = analyze_sources(articles, "RAG")
        assert len(result["trends"]) > 0

    def test_contrastive_detected_in_content(self):
        articles = [
            _art(content="The approach works well. However, it has limitations.", url="https://a.com"),
        ]
        result = analyze_sources(articles, "AI")
        assert len(result["contrastive"]) > 0


# ── 3. format_analysis_for_prompt tests ──────────────────────────────────────

class TestFormatAnalysisForPrompt:
    def test_returns_string(self):
        analysis = analyze_sources(RAG_ARTICLES, "RAG")
        assert isinstance(format_analysis_for_prompt(analysis), str)

    def test_includes_source_count(self):
        analysis = analyze_sources(RAG_ARTICLES, "RAG")
        result = format_analysis_for_prompt(analysis)
        assert "5" in result

    def test_includes_domain_count(self):
        analysis = analyze_sources(RAG_ARTICLES, "RAG")
        result = format_analysis_for_prompt(analysis)
        assert str(analysis["domain_count"]) in result

    def test_includes_themes_when_present(self):
        analysis = analyze_sources(RAG_ARTICLES, "unique_query_xyz")
        result = format_analysis_for_prompt(analysis)
        if analysis["themes"]:
            assert "Common themes" in result

    def test_includes_contrastive_when_present(self):
        analysis = analyze_sources(RAG_ARTICLES, "RAG")
        result = format_analysis_for_prompt(analysis)
        if analysis["contrastive"]:
            assert "Tensions" in result or "tension" in result.lower()

    def test_empty_analysis_returns_fallback(self):
        result = format_analysis_for_prompt(_empty_analysis())
        assert isinstance(result, str)
        assert len(result) > 0

    def test_none_returns_fallback(self):
        result = format_analysis_for_prompt(None)
        assert isinstance(result, str)

    def test_output_is_compact(self):
        analysis = analyze_sources(RAG_ARTICLES, "RAG")
        result = format_analysis_for_prompt(analysis)
        # Should not be excessively long — keep prompt overhead low
        assert len(result) < 2000


# ── 4. Curator wiring test ────────────────────────────────────────────────────

class TestCuratorAnalysisWiring:
    MOCK_FEED = {
        "news_insight": {
            "title": "T", "summary": "S", "why_it_matters": "W", "sources": []
        },
        "perspectives": {
            "common_themes": ["RAG", "LLMs"],
            "synthesis": "Sources converge on X.",
            "notable_tension": None,
        },
        "learning_topics": [
            {"title": "A", "reason": "r", "difficulty": "beginner"},
            {"title": "B", "reason": "r", "difficulty": "intermediate"},
            {"title": "C", "reason": "r", "difficulty": "intermediate"},
            {"title": "D", "reason": "r", "difficulty": "advanced"},
        ],
        "next_step": "do it",
    }

    def test_analyze_sources_called_in_pipeline(self):
        from backend.services.curator_service import generate_learning_feed

        with (
            patch("backend.services.curator_service.search_articles", return_value=RAG_ARTICLES),
            patch("backend.services.curator_service.rank_articles",    return_value=RAG_ARTICLES),
            patch("backend.services.curator_service.analyze_sources")   as mock_analyze,
            patch("backend.services.curator_service.format_analysis_for_prompt", return_value="analysis text"),
            patch("backend.services.curator_service.ask_grok", return_value=json.dumps(self.MOCK_FEED)),
            patch("backend.services.curator_service.get_cached_feed",   return_value=None),
            patch("backend.services.curator_service.cache_feed"),
            patch("backend.services.curator_service._build_memory_fingerprint", return_value="fp"),
        ):
            mock_analyze.return_value = {
                "themes": ["rag"], "repeated_insights": [], "trends": [],
                "contrastive": [], "source_count": 5, "domain_count": 5,
                "domain_diversity": "high",
            }
            generate_learning_feed("RAG pipelines")

        mock_analyze.assert_called_once_with(RAG_ARTICLES, query="RAG pipelines")

    def test_source_analysis_injected_into_prompt(self):
        from backend.services.curator_service import generate_learning_feed

        captured_prompt = {}

        def capture_prompt(prompt):
            captured_prompt["value"] = prompt
            return json.dumps(self.MOCK_FEED)

        with (
            patch("backend.services.curator_service.search_articles", return_value=RAG_ARTICLES),
            patch("backend.services.curator_service.rank_articles",    return_value=RAG_ARTICLES),
            patch("backend.services.curator_service.analyze_sources",  return_value={
                "themes": [], "repeated_insights": [], "trends": [],
                "contrastive": [], "source_count": 5, "domain_count": 3,
                "domain_diversity": "moderate",
            }),
            patch("backend.services.curator_service.format_analysis_for_prompt",
                  return_value="INJECTED_ANALYSIS_MARKER"),
            patch("backend.services.curator_service.ask_grok", side_effect=capture_prompt),
            patch("backend.services.curator_service.get_cached_feed",  return_value=None),
            patch("backend.services.curator_service.cache_feed"),
            patch("backend.services.curator_service._build_memory_fingerprint", return_value="fp"),
        ):
            generate_learning_feed("RAG pipelines")

        assert "INJECTED_ANALYSIS_MARKER" in captured_prompt.get("value", "")

    def test_cache_hit_skips_analysis(self):
        from backend.services.curator_service import generate_learning_feed

        with (
            patch("backend.services.curator_service.get_cached_feed", return_value=self.MOCK_FEED),
            patch("backend.services.curator_service.analyze_sources") as mock_analyze,
            patch("backend.services.curator_service._build_memory_fingerprint", return_value="fp"),
            patch("backend.services.curator_service.build_cache_key",  return_value="k"),
        ):
            generate_learning_feed("RAG pipelines")

        mock_analyze.assert_not_called()

    def test_perspectives_in_feed_output(self):
        from backend.services.curator_service import generate_learning_feed

        with (
            patch("backend.services.curator_service.search_articles", return_value=RAG_ARTICLES),
            patch("backend.services.curator_service.rank_articles",    return_value=RAG_ARTICLES),
            patch("backend.services.curator_service.analyze_sources",  return_value={
                "themes": [], "repeated_insights": [], "trends": [],
                "contrastive": [], "source_count": 5, "domain_count": 3,
                "domain_diversity": "moderate",
            }),
            patch("backend.services.curator_service.format_analysis_for_prompt", return_value=""),
            patch("backend.services.curator_service.ask_grok", return_value=json.dumps(self.MOCK_FEED)),
            patch("backend.services.curator_service.get_cached_feed",  return_value=None),
            patch("backend.services.curator_service.cache_feed"),
            patch("backend.services.curator_service._build_memory_fingerprint", return_value="fp"),
        ):
            result = generate_learning_feed("RAG pipelines")

        assert "perspectives" in result
        assert result["perspectives"]["synthesis"] == "Sources converge on X."


# ── 5. Real integration test ──────────────────────────────────────────────────

@pytest.mark.integration
def test_real_multi_source_feed_has_perspectives():
    """
    One real Tavily + Groq call.  Verifies the perspectives field is present
    and non-empty in a live-generated feed.

    Run with:  pytest tests/test_source_analyzer.py -v -m integration
    """
    from backend.utils.db import init_db
    from backend.services.curator_service import generate_learning_feed

    init_db()

    feed = generate_learning_feed("RAG pipelines and vector databases")

    assert "news_insight"    in feed, "Missing news_insight"
    assert "learning_topics" in feed, "Missing learning_topics"

    perspectives = feed.get("perspectives")
    assert perspectives is not None, "perspectives field missing from feed"
    assert isinstance(perspectives.get("common_themes"), list)
    assert isinstance(perspectives.get("synthesis"), str)
    assert len(perspectives["synthesis"]) > 20, "synthesis too short — LLM likely ignored instruction"
    # notable_tension may be null — that's valid
    assert "notable_tension" in perspectives
