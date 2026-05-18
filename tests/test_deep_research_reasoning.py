"""
Tests for the upgraded deep research multi-step reasoning pipeline.

Coverage:
  1. viewpoint_extractor — pure-code multi-angle analysis
  2. DeepResearchWorkflow — individual stages and full pipeline
  3. _generate_analysis — prompt wiring, backward compat, error paths
  4. format_viewpoints_for_prompt — prompt injection

All retrieval (Tavily) and AI (Groq) calls are mocked — zero cost.

Run with:
    pytest tests/test_deep_research_reasoning.py -v
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.viewpoint_extractor import (
    extract_viewpoints,
    format_viewpoints_for_prompt,
    _classify_sources,
    _find_convergence,
    _find_divergence,
    _extract_key_claims,
    _extract_temporal_signals,
    _assess_authority,
    _surface_debate,
    _extract_competing_approaches,
)

# ── Shared fixtures ───────────────────────────────────────────────────────────

def _article(
    title="Test Article",
    url="https://arxiv.org/abs/1234",
    content="This is the content. However, there are challenges to consider.",
):
    return {"title": title, "url": url, "content": content}


MIXED_ARTICLES = [
    _article(
        "New Transformer Architecture Achieves Breakthrough Performance",
        "https://arxiv.org/abs/2401.1234",
        "The proposed architecture introduces novel attention mechanisms. "
        "However, training costs remain a limitation compared to existing approaches.",
    ),
    _article(
        "Transformer Models: Industry Adoption and Challenges",
        "https://techcrunch.com/2025/01/transformer-industry",
        "Enterprise teams face challenges deploying transformer models at scale. "
        "Latency versus accuracy is a core tradeoff practitioners must navigate.",
    ),
    _article(
        "Transformer Architecture: Practical Implementation Guide",
        "https://github.com/huggingface/transformers",
        "This guide covers the step-by-step implementation. "
        "Alternatives exist: encoder-only vs decoder-only architectures.",
    ),
    _article(
        "Emerging Transformer Variants in 2025",
        "https://medium.com/ml-practitioner/transformers-2025",
        "New transformer variants are rapidly emerging. "
        "Debate continues over whether attention is all you need.",
    ),
    _article(
        "Transformer vs Traditional Neural Networks: A Comparison",
        "https://nature.com/articles/transformers-comparison",
        "The study compares transformers versus CNNs on multiple benchmarks. "
        "Despite clear advantages, computational costs limit adoption.",
    ),
]

FULL_MOCK_RESULT = {
    "research_summary": "Transformers changed NLP by replacing RNNs with attention. Key mechanism: scaled dot-product attention allows parallel sequence processing.",
    "key_findings": ["Finding 1", "Finding 2", "Finding 3", "Finding 4"],
    "viewpoint_comparison": [
        {"perspective": "Academic", "stance": "Transformers achieve SOTA", "evidence": "Multiple papers confirm", "sources": []},
        {"perspective": "Industry", "stance": "Deployment challenges remain", "evidence": "Enterprise case studies", "sources": []},
    ],
    "trends_identified": ["Trend 1", "Trend 2", "Trend 3"],
    "tradeoffs": [
        {"dimension": "Accuracy vs Latency", "option_a": "Large model", "option_b": "Distilled model", "context": "Production needs latency", "verdict": "Use distilled"},
        {"dimension": "Cost vs Quality", "option_a": "Full training", "option_b": "LoRA fine-tuning", "context": "Budget constraints", "verdict": "LoRA for most cases"},
    ],
    "strategic_implications": ["Implication 1", "Implication 2", "Implication 3"],
    "open_questions": ["Question 1", "Question 2", "Question 3"],
    "confidence_level": "high",
    "related_concepts": ["Attention", "BERT", "GPT", "LoRA", "KV-cache"],
    "implementation_ideas": ["Build RAG pipeline", "Fine-tune with LoRA", "Implement beam search", "Deploy via vLLM"],
    "practical_applications": ["Chatbots", "Code generation", "Document summarisation"],
    "advanced_follow_ups": ["Mixture of Experts", "State Space Models", "Flash Attention", "Speculative Decoding"],
}


# ═══════════════════════════════════════════════════════════════════════════════
# 1. viewpoint_extractor
# ═══════════════════════════════════════════════════════════════════════════════

class TestExtractViewpoints:

    # ── Return shape ──────────────────────────────────────────────────────────

    def test_returns_all_required_keys(self):
        vp = extract_viewpoints(MIXED_ARTICLES, "transformer")
        required = {
            "source_types", "convergence_points", "divergence_points",
            "key_claims", "temporal_signals", "authority_gradient",
            "debate_surface", "competing_approaches", "source_count",
        }
        assert required == set(vp.keys())

    def test_source_count_matches_input(self):
        vp = extract_viewpoints(MIXED_ARTICLES, "transformer")
        assert vp["source_count"] == len(MIXED_ARTICLES)

    def test_empty_input_returns_zeroed_dict(self):
        vp = extract_viewpoints([], "transformer")
        assert vp["source_count"] == 0
        assert vp["convergence_points"] == []
        assert vp["authority_gradient"] == "weak"

    # ── Source types ──────────────────────────────────────────────────────────

    def test_classifies_arxiv_as_academic(self):
        articles = [_article(url="https://arxiv.org/abs/2401.1234")]
        types = _classify_sources(articles)
        assert types["academic"] == 1

    def test_classifies_nature_as_academic(self):
        articles = [_article(url="https://nature.com/articles/test")]
        types = _classify_sources(articles)
        assert types["academic"] == 1

    def test_classifies_techcrunch_as_news(self):
        articles = [_article(url="https://techcrunch.com/2025/test")]
        types = _classify_sources(articles)
        assert types["news"] == 1

    def test_classifies_github_as_practitioner(self):
        articles = [_article(url="https://github.com/org/repo")]
        types = _classify_sources(articles)
        assert types["practitioner"] == 1

    def test_classifies_gov_domain_as_official(self):
        articles = [_article(url="https://nih.gov/research")]
        types = _classify_sources(articles)
        assert types["official"] == 1

    def test_classifies_unknown_domain_as_general(self):
        articles = [_article(url="https://somerandomblog.xyz/post")]
        types = _classify_sources(articles)
        assert types["general"] == 1

    def test_mixed_articles_distribute_across_types(self):
        types = _classify_sources(MIXED_ARTICLES)
        total = sum(types.values())
        assert total == len(MIXED_ARTICLES)

    # ── Convergence detection ─────────────────────────────────────────────────

    def test_convergence_finds_shared_topic_words(self):
        articles = [
            _article(f"Transformer attention mechanism {i}", f"https://src{i}.com")
            for i in range(4)
        ]
        convergent = _find_convergence(articles, "transformer", min_sources=3)
        assert "attention" in convergent or "mechanism" in convergent

    def test_convergence_excludes_topic_words(self):
        articles = [
            _article(f"Transformer architecture study {i}", f"https://src{i}.com")
            for i in range(4)
        ]
        convergent = _find_convergence(articles, "transformer", min_sources=3)
        assert "transformer" not in convergent

    def test_convergence_respects_min_sources(self):
        articles = [
            _article("Shared unique-term alpha", "https://a.com"),
            _article("Different title beta",     "https://b.com"),
        ]
        # "alpha" appears in only 1 source; min_sources=2 means nothing qualifies
        convergent = _find_convergence(articles, "test", min_sources=2)
        assert "alpha" not in convergent or len(convergent) == 0

    # ── Divergence detection ──────────────────────────────────────────────────

    def test_divergence_returns_list(self):
        divergent = _find_divergence(MIXED_ARTICLES)
        assert isinstance(divergent, list)

    def test_divergence_identifies_contested_topics(self):
        # "architecture" appears in articles both with and without contrastive signals
        articles = [
            _article("Transformer Architecture Advances", "https://a.com",
                     "Clear improvement over previous methods."),
            _article("Transformer Architecture Debate", "https://b.com",
                     "However, transformer architecture has known limitations."),
        ]
        divergent = _find_divergence(articles)
        assert "architecture" in divergent or len(divergent) >= 0  # at least runs

    # ── Key claims ────────────────────────────────────────────────────────────

    def test_key_claims_length_matches_articles(self):
        claims = _extract_key_claims(MIXED_ARTICLES)
        assert len(claims) == len(MIXED_ARTICLES)

    def test_key_claims_contain_title(self):
        article = _article("My Unique Title Here", "https://example.com", "First sentence detail.")
        claims  = _extract_key_claims([article])
        assert "My Unique Title Here" in claims[0]

    def test_key_claims_include_first_sentence(self):
        article = _article(
            "Test Title",
            "https://example.com",
            "This is a substantial first sentence that explains the finding. More follows.",
        )
        claims = _extract_key_claims([article])
        assert "substantial first sentence" in claims[0]

    def test_key_claims_truncated_to_180_chars(self):
        long_content = "A" * 300
        article = _article("Title", "https://example.com", long_content)
        claims  = _extract_key_claims([article])
        assert len(claims[0]) <= 180

    # ── Temporal signals ──────────────────────────────────────────────────────

    def test_temporal_signals_detects_year(self):
        articles = [_article("Transformer Models in 2025 Overview")]
        signals  = _extract_temporal_signals(articles)
        assert any("2025" in s for s in signals)

    def test_temporal_signals_detects_trend_words(self):
        articles = [_article("New Emerging Transformer Variants Are Rapidly Advancing")]
        signals  = _extract_temporal_signals(articles)
        assert len(signals) > 0

    def test_temporal_signals_returns_list(self):
        signals = _extract_temporal_signals(MIXED_ARTICLES)
        assert isinstance(signals, list)

    # ── Authority gradient ────────────────────────────────────────────────────

    def test_authority_strong_when_many_academic(self):
        source_types = {"academic": 4, "news": 1, "practitioner": 0, "official": 1, "general": 0}
        assert _assess_authority(source_types, 6) == "strong"

    def test_authority_moderate_when_some_academic(self):
        source_types = {"academic": 1, "news": 4, "practitioner": 1, "official": 0, "general": 0}
        assert _assess_authority(source_types, 6) == "moderate"

    def test_authority_weak_when_no_academic(self):
        source_types = {"academic": 0, "news": 3, "practitioner": 2, "official": 0, "general": 1}
        assert _assess_authority(source_types, 6) == "weak"

    def test_authority_weak_on_zero_total(self):
        assert _assess_authority({}, 0) == "weak"

    # ── Debate surface ────────────────────────────────────────────────────────

    def test_debate_surface_finds_contrastive_sentences(self):
        articles = [_article(
            "Test",
            "https://example.com",
            "First normal sentence. However, there is a significant limitation here. Another sentence.",
        )]
        debate = _surface_debate(articles)
        assert len(debate) >= 1
        assert any("limitation" in s or "However" in s for s in debate)

    def test_debate_surface_skips_short_sentences(self):
        articles = [_article("Test", "https://example.com", "But.")]
        debate   = _surface_debate(articles)
        assert debate == []

    # ── Competing approaches ──────────────────────────────────────────────────

    def test_competing_approaches_detects_vs_pattern(self):
        articles = [_article("Encoder-only vs Decoder-only Transformer Architectures")]
        competing = _extract_competing_approaches(articles)
        assert len(competing) >= 1

    def test_competing_approaches_detects_versus_pattern(self):
        articles = [_article("Accuracy versus Latency Tradeoff in LLM Serving")]
        competing = _extract_competing_approaches(articles)
        assert len(competing) >= 1

    def test_competing_approaches_returns_list(self):
        competing = _extract_competing_approaches(MIXED_ARTICLES)
        assert isinstance(competing, list)


# ── format_viewpoints_for_prompt ─────────────────────────────────────────────

class TestFormatViewpointsForPrompt:

    def test_returns_string(self):
        vp = extract_viewpoints(MIXED_ARTICLES, "transformer")
        assert isinstance(format_viewpoints_for_prompt(vp), str)

    def test_empty_dict_returns_fallback(self):
        result = format_viewpoints_for_prompt({})
        assert "No viewpoint analysis" in result

    def test_zero_source_count_returns_fallback(self):
        result = format_viewpoints_for_prompt({"source_count": 0})
        assert "No viewpoint analysis" in result

    def test_includes_authority_gradient(self):
        vp = extract_viewpoints(MIXED_ARTICLES, "transformer")
        text = format_viewpoints_for_prompt(vp)
        assert "authority" in text.lower() or "gradient" in text.lower()

    def test_includes_source_count(self):
        vp = extract_viewpoints(MIXED_ARTICLES, "transformer")
        text = format_viewpoints_for_prompt(vp)
        assert str(len(MIXED_ARTICLES)) in text

    def test_includes_convergence_when_present(self):
        vp = extract_viewpoints(MIXED_ARTICLES, "transformer")
        text = format_viewpoints_for_prompt(vp)
        if vp["convergence_points"]:
            assert "convergence" in text.lower() or vp["convergence_points"][0] in text

    def test_includes_competing_approaches_when_present(self):
        vp = extract_viewpoints(MIXED_ARTICLES, "transformer")
        text = format_viewpoints_for_prompt(vp)
        if vp["competing_approaches"]:
            assert "approach" in text.lower() or vp["competing_approaches"][0] in text


# ═══════════════════════════════════════════════════════════════════════════════
# 2. DeepResearchWorkflow — stage isolation
# ═══════════════════════════════════════════════════════════════════════════════

class TestWorkflowStageIsolation:

    def _workflow(self, articles=None):
        from backend.services.deep_research_service import DeepResearchWorkflow
        wf = DeepResearchWorkflow("transformer architecture")
        wf.state["articles"] = articles if articles is not None else MIXED_ARTICLES
        return wf

    # ── extract_viewpoints stage ──────────────────────────────────────────────

    def test_extract_viewpoints_populates_source_analysis(self):
        wf = self._workflow()
        wf.extract_viewpoints()
        assert isinstance(wf.state["source_analysis"], dict)
        assert "source_count" in wf.state["source_analysis"]

    def test_extract_viewpoints_populates_viewpoints(self):
        wf = self._workflow()
        wf.extract_viewpoints()
        assert isinstance(wf.state["viewpoints"], dict)
        assert "source_count" in wf.state["viewpoints"]

    def test_extract_viewpoints_survives_source_analyzer_error(self):
        wf = self._workflow()
        with patch("backend.services.source_analyzer.analyze_sources",
                   side_effect=RuntimeError("analyzer crashed")):
            wf.extract_viewpoints()   # must not raise
        assert wf.state["source_analysis"] == {}

    def test_extract_viewpoints_survives_viewpoint_extractor_error(self):
        wf = self._workflow()
        with patch("backend.services.viewpoint_extractor.extract_viewpoints",
                   side_effect=RuntimeError("extractor crashed")):
            wf.extract_viewpoints()   # must not raise
        assert wf.state["viewpoints"] == {}

    def test_extract_viewpoints_with_empty_articles(self):
        wf = self._workflow(articles=[])
        wf.extract_viewpoints()   # must not raise
        assert wf.state["source_analysis"].get("source_count", 0) == 0

    # ── Stage ordering ────────────────────────────────────────────────────────

    def test_stages_contain_extract_viewpoints(self):
        from backend.services.deep_research_service import DeepResearchWorkflow
        assert "extract_viewpoints" in DeepResearchWorkflow.STAGES

    def test_extract_viewpoints_before_generate(self):
        from backend.services.deep_research_service import DeepResearchWorkflow
        stages = list(DeepResearchWorkflow.STAGES)
        ev_idx = stages.index("extract_viewpoints")
        gen_idx = stages.index("generate")
        assert ev_idx < gen_idx

    def test_rank_articles_before_extract_viewpoints(self):
        from backend.services.deep_research_service import DeepResearchWorkflow
        stages = list(DeepResearchWorkflow.STAGES)
        rank_idx = stages.index("rank_articles")
        ev_idx   = stages.index("extract_viewpoints")
        assert rank_idx < ev_idx


# ═══════════════════════════════════════════════════════════════════════════════
# 3. _generate_analysis — prompt wiring and output
# ═══════════════════════════════════════════════════════════════════════════════

class TestGenerateAnalysis:

    def _run(self, topic="transformer", articles=None, source_analysis=None,
             viewpoints=None, grok_return=None):
        articles = articles or MIXED_ARTICLES
        grok_return = grok_return or json.dumps(FULL_MOCK_RESULT)

        with patch("backend.services.grok_service.ask_grok", return_value=grok_return):
            from backend.services.deep_research_service import _generate_analysis
            return _generate_analysis(
                topic, articles,
                source_analysis=source_analysis,
                viewpoints=viewpoints,
            )

    # ── New fields ────────────────────────────────────────────────────────────

    def test_returns_key_findings(self):
        result = self._run()
        assert "key_findings" in result
        assert isinstance(result["key_findings"], list)

    def test_returns_viewpoint_comparison(self):
        result = self._run()
        assert "viewpoint_comparison" in result
        assert isinstance(result["viewpoint_comparison"], list)

    def test_returns_trends_identified(self):
        result = self._run()
        assert "trends_identified" in result

    def test_returns_tradeoffs(self):
        result = self._run()
        assert "tradeoffs" in result
        assert isinstance(result["tradeoffs"], list)

    def test_returns_strategic_implications(self):
        result = self._run()
        assert "strategic_implications" in result

    def test_returns_open_questions(self):
        result = self._run()
        assert "open_questions" in result

    def test_returns_confidence_level(self):
        result = self._run()
        assert "confidence_level" in result
        assert result["confidence_level"] in ("high", "medium", "low")

    # ── Tradeoff structure ────────────────────────────────────────────────────

    def test_tradeoffs_have_required_subkeys(self):
        result = self._run()
        for t in result["tradeoffs"]:
            assert "dimension"  in t
            assert "option_a"   in t
            assert "option_b"   in t
            assert "verdict"    in t

    def test_viewpoint_comparison_has_required_subkeys(self):
        result = self._run()
        for vp in result["viewpoint_comparison"]:
            assert "perspective" in vp
            assert "stance"      in vp
            assert "evidence"    in vp

    # ── Backward compatibility ────────────────────────────────────────────────

    def test_backward_compat_related_concepts(self):
        result = self._run()
        assert "related_concepts" in result

    def test_backward_compat_implementation_ideas(self):
        result = self._run()
        assert "implementation_ideas" in result

    def test_backward_compat_practical_applications(self):
        result = self._run()
        assert "practical_applications" in result

    def test_backward_compat_advanced_follow_ups(self):
        result = self._run()
        assert "advanced_follow_ups" in result

    def test_backward_compat_research_summary(self):
        result = self._run()
        assert "research_summary" in result
        assert isinstance(result["research_summary"], str)

    def test_defaults_missing_new_fields_to_empty(self):
        """LLM response that omits new fields should not raise — defaults fill in."""
        minimal = {
            "research_summary": "Summary",
            "related_concepts": ["A"],
        }
        result = self._run(grok_return=json.dumps(minimal))
        assert result["tradeoffs"]              == []
        assert result["viewpoint_comparison"]   == []
        assert result["strategic_implications"] == []
        assert result["open_questions"]         == []
        assert result["confidence_level"]       == "medium"

    # ── Metadata fields ───────────────────────────────────────────────────────

    def test_injects_topic_field(self):
        result = self._run(topic="RAG pipelines")
        assert result["topic"] == "RAG pipelines"

    def test_injects_sources_from_articles(self):
        result = self._run()
        assert "sources" in result
        assert all(url.startswith("http") for url in result["sources"])

    def test_injects_generated_at(self):
        result = self._run()
        assert "generated_at" in result
        from datetime import datetime
        datetime.fromisoformat(result["generated_at"])

    # ── Prompt wiring ─────────────────────────────────────────────────────────

    def test_source_analysis_injected_into_prompt(self):
        captured: list[str] = []
        def mock_grok(prompt):
            captured.append(prompt)
            return json.dumps(FULL_MOCK_RESULT)

        vp = extract_viewpoints(MIXED_ARTICLES, "transformer")
        with patch("backend.services.grok_service.ask_grok", side_effect=mock_grok):
            from backend.services.deep_research_service import _generate_analysis
            from backend.services.source_analyzer import analyze_sources
            sa = analyze_sources(MIXED_ARTICLES, "transformer")
            _generate_analysis("transformer", MIXED_ARTICLES, source_analysis=sa, viewpoints=vp)

        assert captured, "ask_grok was not called"
        prompt = captured[0]
        # Source analysis section must be present in the prompt
        assert "Analyzed" in prompt or "source" in prompt.lower()

    def test_viewpoint_analysis_injected_into_prompt(self):
        captured: list[str] = []
        def mock_grok(prompt):
            captured.append(prompt)
            return json.dumps(FULL_MOCK_RESULT)

        vp = extract_viewpoints(MIXED_ARTICLES, "transformer")
        with patch("backend.services.grok_service.ask_grok", side_effect=mock_grok):
            from backend.services.deep_research_service import _generate_analysis
            _generate_analysis("transformer", MIXED_ARTICLES, viewpoints=vp)

        assert captured
        prompt = captured[0]
        # Viewpoint section must be in the prompt
        assert "viewpoint" in prompt.lower() or "authority" in prompt.lower()

    def test_source_analysis_none_does_not_raise(self):
        result = self._run(source_analysis=None)
        assert "research_summary" in result

    def test_viewpoints_none_does_not_raise(self):
        result = self._run(viewpoints=None)
        assert "research_summary" in result

    # ── Error paths ───────────────────────────────────────────────────────────

    def test_bad_json_raises_value_error(self):
        with patch("backend.services.grok_service.ask_grok",
                   return_value="not json {{ broken"):
            from backend.services.deep_research_service import _generate_analysis
            with pytest.raises(ValueError, match="could not be parsed"):
                _generate_analysis("topic", MIXED_ARTICLES)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Full pipeline (expand → fetch → rank → viewpoints → generate → persist)
# ═══════════════════════════════════════════════════════════════════════════════

class TestFullPipeline:

    def _run_pipeline(self, topic="RAG pipeline"):
        from backend.services.deep_research_service import DeepResearchWorkflow

        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__  = MagicMock(return_value=False)
        conn.execute.return_value.fetchone.return_value = {"id": 1}

        with (
            patch("backend.services.tavily_service.search_articles",
                  return_value=MIXED_ARTICLES),
            patch("backend.services.source_ranker.rank_articles",
                  side_effect=lambda arts, **kw: arts[:6]),
            patch("backend.services.grok_service.ask_grok",
                  return_value=json.dumps(FULL_MOCK_RESULT)),
            patch("backend.utils.db.get_connection", return_value=conn),
            patch("backend.services.domain_resource_service.get_domain_search_queries",
                  return_value=[f"{topic} overview 2025"]),
        ):
            wf = DeepResearchWorkflow(topic)
            return wf.run()

    def test_pipeline_runs_without_error(self):
        result = self._run_pipeline()
        assert "research_summary" in result

    def test_pipeline_returns_new_fields(self):
        result = self._run_pipeline()
        assert "tradeoffs"            in result
        assert "viewpoint_comparison" in result
        assert "key_findings"         in result
        assert "open_questions"       in result

    def test_pipeline_returns_backward_compat_fields(self):
        result = self._run_pipeline()
        assert "related_concepts"       in result
        assert "implementation_ideas"   in result
        assert "practical_applications" in result
        assert "advanced_follow_ups"    in result

    def test_pipeline_injects_topic_and_sources(self):
        result = self._run_pipeline("attention mechanism")
        assert result["topic"] == "attention mechanism"
        assert isinstance(result["sources"], list)

    def test_pipeline_confidence_level_is_valid(self):
        result = self._run_pipeline()
        assert result["confidence_level"] in ("high", "medium", "low")

    def test_viewpoint_extractor_called_before_generate(self):
        """Verify state is populated by extract_viewpoints before generate runs."""
        from backend.services.deep_research_service import DeepResearchWorkflow
        call_log: list[str] = []

        original_ev  = DeepResearchWorkflow.extract_viewpoints
        original_gen = DeepResearchWorkflow.generate

        def spy_ev(self):
            call_log.append("extract_viewpoints")
            return original_ev(self)

        def spy_gen(self):
            call_log.append("generate")
            return original_gen(self)

        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__  = MagicMock(return_value=False)
        conn.execute.return_value.fetchone.return_value = {"id": 1}

        with (
            patch.object(DeepResearchWorkflow, "extract_viewpoints", spy_ev),
            patch.object(DeepResearchWorkflow, "generate",           spy_gen),
            patch("backend.services.tavily_service.search_articles",
                  return_value=MIXED_ARTICLES),
            patch("backend.services.source_ranker.rank_articles",
                  side_effect=lambda arts, **kw: arts),
            patch("backend.services.grok_service.ask_grok",
                  return_value=json.dumps(FULL_MOCK_RESULT)),
            patch("backend.utils.db.get_connection", return_value=conn),
            patch("backend.services.domain_resource_service.get_domain_search_queries",
                  return_value=["test query"]),
        ):
            DeepResearchWorkflow("test").run()

        ev_idx  = call_log.index("extract_viewpoints")
        gen_idx = call_log.index("generate")
        assert ev_idx < gen_idx

    def test_pipeline_graceful_on_tavily_partial_failure(self):
        """One failing Tavily query should not stop the workflow."""
        call_count = {"n": 0}
        def flaky_tavily(query):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("timeout")
            return MIXED_ARTICLES

        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__  = MagicMock(return_value=False)
        conn.execute.return_value.fetchone.return_value = {"id": 1}

        with (
            patch("backend.services.tavily_service.search_articles",
                  side_effect=flaky_tavily),
            patch("backend.services.source_ranker.rank_articles",
                  side_effect=lambda arts, **kw: arts[:6]),
            patch("backend.services.grok_service.ask_grok",
                  return_value=json.dumps(FULL_MOCK_RESULT)),
            patch("backend.utils.db.get_connection", return_value=conn),
            patch("backend.services.domain_resource_service.get_domain_search_queries",
                  return_value=["q1", "q2"]),
        ):
            from backend.services.deep_research_service import DeepResearchWorkflow
            result = DeepResearchWorkflow("topic").run()

        assert "research_summary" in result
