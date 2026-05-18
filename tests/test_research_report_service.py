"""
Tests for research_report_service.

All tests use mocked research inputs — no AI calls, no Tavily, no DB.

Coverage
--------
  TestGenerateReport          — top-level dict shape and section contents
  TestExecutiveSummary        — synthesis logic (summary, implications, industry, confidence)
  TestKeyFindings             — augmentation from viewpoints when sparse
  TestTrendAnalysis           — trends list and momentum scoring
  TestOpportunitiesAndRisks   — extraction from tradeoffs + strategic_implications
  TestImportantResources      — URL classification and sort order
  TestFormatReportAsMarkdown  — section headings, confidence badge, date, table
  TestFormatReportAsText      — strips markdown symbols
  TestActionRouterIntegration — detect_action + dispatch for research_report
  TestEdgeCases               — empty data, missing optional fields, industry enrichment
"""

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from backend.services.research_report_service import (
    _build_executive_summary,
    _build_resource_list,
    _build_trend_analysis,
    _classify_url,
    _extract_key_findings,
    _extract_opportunities,
    _extract_risks,
    _score_momentum,
    format_report_as_markdown,
    format_report_as_text,
    generate_report,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Shared fixtures
# ═══════════════════════════════════════════════════════════════════════════════

FULL_RESEARCH = {
    "topic":            "transformer architecture",
    "confidence_level": "high",
    "research_summary": (
        "Transformer architecture revolutionised NLP via self-attention. "
        "Scaling laws suggest larger models generalise better. "
        "Inference cost remains a key barrier for production deployment."
    ),
    "key_findings": [
        "Finding 1 — attention mechanism enables parallel sequence processing",
        "Finding 2 — pre-training on large corpora transfers well to downstream tasks",
        "Finding 3 — RLHF alignment significantly improves instruction following",
        "Finding 4 — MoE variants reduce per-token compute while maintaining capacity",
    ],
    "viewpoint_comparison": [
        {
            "perspective": "Academic / Research",
            "stance":      "Scaling laws predict continued capability gains.",
            "evidence":    "Chinchilla paper demonstrates optimal compute allocation.",
            "sources":     ["https://arxiv.org/abs/2203.15556"],
        },
        {
            "perspective": "Industry Practitioners",
            "stance":      "Inference cost constrains real-world deployment.",
            "evidence":    "Production teams report 10x latency vs smaller models.",
            "sources":     [],
        },
    ],
    "trends_identified": [
        "Rapid growth in open-source model releases (Llama, Mistral)",
        "Emerging specialisation via LoRA fine-tuning at low cost",
        "Increasing adoption of MoE for compute efficiency",
    ],
    "tradeoffs": [
        {
            "dimension": "Accuracy vs Latency",
            "option_a":  "Large dense model",
            "option_b":  "Small quantised model",
            "context":   "Large models win on benchmarks; small models win in production.",
            "verdict":   "Quantise where latency is critical; use dense for quality-critical paths.",
        },
        {
            "dimension": "Fine-tuning vs Prompting",
            "option_a":  "Full fine-tune",
            "option_b":  "Prompt engineering",
            "context":   "Fine-tuning locks in domain knowledge; prompting stays flexible.",
            "verdict":   "Prefer prompting for low-volume tasks; fine-tune for high-volume specialisation.",
        },
    ],
    "strategic_implications": [
        "Implication 1 — Strategy Consultant: Organisations must build internal inference infrastructure or face vendor lock-in.",
        "Implication 2 — Strategy Consultant: Open-source models shift the cost structure for AI teams dramatically.",
        "Implication 3 — Strategy Consultant: Regulatory pressure on model provenance will increase audit requirements.",
    ],
    "open_questions": [
        "Question 1 — Technical Investigator: What is the theoretical limit of in-context learning?",
        "Question 2 — Technical Investigator: Can MoE routing be made fully differentiable?",
        "Question 3 — Technical Investigator: Does constitutional AI generalise beyond RLHF?",
    ],
    "practical_applications": [
        "Retrieval-augmented generation for enterprise knowledge bases",
        "Code generation assistants integrated into IDE workflows",
        "Multilingual customer support automation",
    ],
    "implementation_ideas": [
        "Fine-tune a small model on internal docs for low-latency Q&A",
        "Use LoRA adapters to specialise a base model per business unit",
    ],
    "related_concepts": ["attention mechanism", "RLHF", "LoRA", "MoE", "scaling laws"],
    "advanced_follow_ups": ["sparse attention", "state-space models", "retrieval augmentation"],
    "sources": [
        "https://arxiv.org/abs/2203.15556",
        "https://github.com/huggingface/transformers",
        "https://techcrunch.com/2024/01/01/transformers-everywhere",
        "https://example.com/unknown",
    ],
    "generated_at": "2026-05-16T10:00:00+00:00",
}

MINIMAL_RESEARCH = {
    "confidence_level": "low",
    "research_summary": "",
    "key_findings": [],
    "viewpoint_comparison": [],
    "trends_identified": [],
    "tradeoffs": [],
    "strategic_implications": [],
    "open_questions": [],
    "practical_applications": [],
    "related_concepts": [],
    "advanced_follow_ups": [],
    "sources": [],
}

INDUSTRY_DATA = {
    "industry": "AI Business Ecosystem",
    "trend_summary": "Enterprise AI adoption is accelerating driven by foundation models.",
    "emerging_opportunities": [
        {"opportunity": "LLM-powered document automation", "time_horizon": "near-term"},
        {"opportunity": "AI-native product teams", "time_horizon": "mid-term"},
    ],
    "market_developments": [],
    "key_signals": [],
    "action_items": [],
}


# ═══════════════════════════════════════════════════════════════════════════════
# 1. generate_report — shape
# ═══════════════════════════════════════════════════════════════════════════════

class TestGenerateReport:

    def _report(self, research=None, industry=None):
        return generate_report("transformer architecture", research or FULL_RESEARCH, industry)

    def test_returns_dict(self):
        assert isinstance(self._report(), dict)

    def test_top_level_keys(self):
        report = self._report()
        assert {"title", "topic", "generated_at", "confidence_level", "sections", "appendix"} <= report.keys()

    def test_title_contains_topic(self):
        report = self._report()
        assert "transformer" in report["title"].lower()

    def test_topic_field_preserved(self):
        assert self._report()["topic"] == "transformer architecture"

    def test_confidence_level_preserved(self):
        assert self._report()["confidence_level"] == "high"

    def test_generated_at_is_iso_string(self):
        ts = self._report()["generated_at"]
        assert "T" in ts or "-" in ts

    def test_sections_contains_all_required_keys(self):
        sections = self._report()["sections"]
        required = {
            "executive_summary", "key_findings", "trend_analysis",
            "opportunities", "risks", "important_resources", "source_references",
        }
        assert required <= sections.keys()

    def test_appendix_contains_expected_keys(self):
        appendix = self._report()["appendix"]
        assert {"related_concepts", "open_questions", "advanced_follow_ups"} <= appendix.keys()

    def test_related_concepts_copied(self):
        assert self._report()["appendix"]["related_concepts"] == FULL_RESEARCH["related_concepts"]

    def test_open_questions_copied_to_appendix(self):
        appendix = self._report()["appendix"]
        assert len(appendix["open_questions"]) > 0

    def test_source_references_are_urls(self):
        refs = self._report()["sections"]["source_references"]
        assert all(r.startswith("http") for r in refs)

    def test_source_references_excludes_empty(self):
        data = {**FULL_RESEARCH, "sources": ["https://a.com", "", None]}
        report = generate_report("x", data)
        assert "" not in report["sections"]["source_references"]
        assert None not in report["sections"]["source_references"]

    def test_minimal_research_does_not_raise(self):
        report = generate_report("empty topic", MINIMAL_RESEARCH)
        assert isinstance(report["sections"]["executive_summary"], str)
        assert len(report["sections"]["executive_summary"]) > 0

    def test_industry_data_optional(self):
        report = generate_report("transformer architecture", FULL_RESEARCH, None)
        assert report is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Executive summary
# ═══════════════════════════════════════════════════════════════════════════════

class TestExecutiveSummary:

    def _summary(self, research=None, industry=None):
        return _build_executive_summary(research or FULL_RESEARCH, industry)

    def test_returns_string(self):
        assert isinstance(self._summary(), str)

    def test_includes_research_summary(self):
        text = self._summary()
        assert "self-attention" in text or "Transformer" in text

    def test_includes_strategic_implication(self):
        text = self._summary()
        assert "Strategically" in text

    def test_strips_persona_prefix_from_implication(self):
        text = self._summary()
        assert "Implication 1" not in text
        assert "Strategy Consultant" not in text

    def test_includes_confidence_note_for_high(self):
        text = self._summary()
        assert "converging sources" in text

    def test_confidence_note_for_medium(self):
        data = {**FULL_RESEARCH, "confidence_level": "medium"}
        text = _build_executive_summary(data, None)
        assert "mixed signals" in text

    def test_confidence_note_for_low(self):
        data = {**FULL_RESEARCH, "confidence_level": "low"}
        text = _build_executive_summary(data, None)
        assert "preliminary" in text

    def test_industry_context_included_when_provided(self):
        text = self._summary(industry=INDUSTRY_DATA)
        assert "Industry context" in text
        assert "foundation models" in text

    def test_no_industry_no_industry_context(self):
        text = self._summary(industry=None)
        assert "Industry context" not in text

    def test_empty_research_summary_still_returns_confidence_note(self):
        text = _build_executive_summary(MINIMAL_RESEARCH, None)
        # MINIMAL_RESEARCH has confidence_level "low" — confidence note is always appended
        assert "preliminary" in text or len(text) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Key findings
# ═══════════════════════════════════════════════════════════════════════════════

class TestKeyFindings:

    def test_returns_list(self):
        assert isinstance(_extract_key_findings(FULL_RESEARCH), list)

    def test_full_findings_preserved(self):
        findings = _extract_key_findings(FULL_RESEARCH)
        assert len(findings) == 4

    def test_max_8_findings(self):
        data = {**FULL_RESEARCH, "key_findings": [f"finding {i}" for i in range(20)]}
        assert len(_extract_key_findings(data)) <= 8

    def test_augments_from_viewpoints_when_sparse(self):
        data = {**FULL_RESEARCH, "key_findings": ["only one finding"]}
        findings = _extract_key_findings(data)
        assert len(findings) >= 2
        assert any("Academic" in f or "Industry" in f for f in findings)

    def test_no_augmentation_when_findings_sufficient(self):
        findings = _extract_key_findings(FULL_RESEARCH)
        assert not any("[Academic" in f for f in findings)

    def test_empty_findings_and_empty_viewpoints(self):
        findings = _extract_key_findings(MINIMAL_RESEARCH)
        assert findings == []


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Trend analysis
# ═══════════════════════════════════════════════════════════════════════════════

class TestTrendAnalysis:

    def test_returns_dict_with_trends_and_momentum(self):
        ta = _build_trend_analysis(FULL_RESEARCH)
        assert "trends" in ta and "momentum" in ta

    def test_trends_list_preserved(self):
        ta = _build_trend_analysis(FULL_RESEARCH)
        assert ta["trends"] == FULL_RESEARCH["trends_identified"]

    def test_momentum_is_valid_string(self):
        ta = _build_trend_analysis(FULL_RESEARCH)
        assert ta["momentum"] in ("accelerating", "stable", "declining")

    def test_momentum_accelerating_on_growth_words(self):
        data = {**MINIMAL_RESEARCH, "trends_identified": ["rapidly growing emerging novel"]}
        assert _build_trend_analysis(data)["momentum"] == "accelerating"

    def test_momentum_declining_on_decline_words(self):
        data = {**MINIMAL_RESEARCH, "trends_identified": ["declining legacy obsolete saturated"]}
        assert _build_trend_analysis(data)["momentum"] == "declining"

    def test_momentum_stable_when_balanced(self):
        data = {**MINIMAL_RESEARCH, "trends_identified": ["growing declining"], "research_summary": ""}
        assert _build_trend_analysis(data)["momentum"] == "stable"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Opportunities and risks
# ═══════════════════════════════════════════════════════════════════════════════

class TestOpportunitiesAndRisks:

    def test_opportunities_returns_list(self):
        assert isinstance(_extract_opportunities(FULL_RESEARCH, None), list)

    def test_opportunities_from_strategic_implications(self):
        opps = _extract_opportunities(FULL_RESEARCH, None)
        assert any("inference infrastructure" in o or "vendor lock-in" in o for o in opps)

    def test_opportunities_persona_prefix_stripped(self):
        opps = _extract_opportunities(FULL_RESEARCH, None)
        assert not any("Implication 1" in o for o in opps)
        assert not any("Strategy Consultant" in o for o in opps)

    def test_opportunities_augmented_by_practical_applications(self):
        data = {**FULL_RESEARCH, "strategic_implications": []}
        opps = _extract_opportunities(data, None)
        assert any("Retrieval" in o or "Code generation" in o or "Multilingual" in o for o in opps)

    def test_opportunities_include_industry_data(self):
        opps = _extract_opportunities(FULL_RESEARCH, INDUSTRY_DATA)
        assert any("document automation" in o or "AI-native" in o for o in opps)

    def test_max_8_opportunities(self):
        assert len(_extract_opportunities(FULL_RESEARCH, INDUSTRY_DATA)) <= 8

    def test_risks_returns_list(self):
        assert isinstance(_extract_risks(FULL_RESEARCH), list)

    def test_risks_from_tradeoffs(self):
        risks = _extract_risks(FULL_RESEARCH)
        assert any("Accuracy vs Latency" in r or "Fine-tuning" in r for r in risks)

    def test_risks_include_unresolved_questions(self):
        risks = _extract_risks(FULL_RESEARCH)
        assert any("Unresolved:" in r for r in risks)

    def test_risks_question_persona_prefix_stripped(self):
        risks = _extract_risks(FULL_RESEARCH)
        assert not any("Technical Investigator" in r for r in risks)

    def test_max_6_risks(self):
        assert len(_extract_risks(FULL_RESEARCH)) <= 6

    def test_empty_tradeoffs_and_questions_gives_empty_risks(self):
        assert _extract_risks(MINIMAL_RESEARCH) == []


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Resource classification and list building
# ═══════════════════════════════════════════════════════════════════════════════

class TestImportantResources:

    def test_classify_arxiv_as_academic(self):
        assert _classify_url("https://arxiv.org/abs/1234") == "academic"

    def test_classify_github_as_practitioner(self):
        assert _classify_url("https://github.com/owner/repo") == "practitioner"

    def test_classify_techcrunch_as_news(self):
        assert _classify_url("https://techcrunch.com/article") == "news"

    def test_classify_gov_domain_as_official(self):
        assert _classify_url("https://nih.gov/research") == "official"

    def test_classify_unknown_as_general(self):
        assert _classify_url("https://randomsite.xyz/page") == "general"

    def test_resource_list_deduplicates_urls(self):
        data = {**FULL_RESEARCH, "sources": ["https://arxiv.org/abs/1", "https://arxiv.org/abs/1"]}
        resources = _build_resource_list(data)
        urls = [r["url"] for r in resources]
        assert len(urls) == len(set(urls))

    def test_resource_list_sorted_academic_first(self):
        resources = _build_resource_list(FULL_RESEARCH)
        types = [r["type"] for r in resources]
        first_academic = next((i for i, t in enumerate(types) if t == "academic"), None)
        first_news     = next((i for i, t in enumerate(types) if t == "news"),     None)
        if first_academic is not None and first_news is not None:
            assert first_academic < first_news

    def test_resource_list_max_10(self):
        data = {**FULL_RESEARCH, "sources": [f"https://example{i}.com" for i in range(20)]}
        assert len(_build_resource_list(data)) <= 10

    def test_resource_list_each_entry_has_url_and_type(self):
        for res in _build_resource_list(FULL_RESEARCH):
            assert "url" in res and "type" in res

    def test_empty_sources_gives_empty_list(self):
        assert _build_resource_list(MINIMAL_RESEARCH) == []


# ═══════════════════════════════════════════════════════════════════════════════
# 7. format_report_as_markdown
# ═══════════════════════════════════════════════════════════════════════════════

class TestFormatReportAsMarkdown:

    def _md(self, research=None):
        report = generate_report("transformer architecture", research or FULL_RESEARCH)
        return format_report_as_markdown(report)

    def test_returns_string(self):
        assert isinstance(self._md(), str)

    def test_starts_with_h1_title(self):
        md = self._md()
        assert md.startswith("# Research Report:")

    def test_contains_executive_summary_heading(self):
        assert "## Executive Summary" in self._md()

    def test_contains_key_findings_heading(self):
        assert "## Key Findings" in self._md()

    def test_contains_trend_analysis_heading(self):
        assert "## Trend Analysis" in self._md()

    def test_contains_opportunities_risks_heading(self):
        assert "## Opportunities & Risks" in self._md()

    def test_contains_important_resources_heading(self):
        assert "## Important Resources" in self._md()

    def test_contains_source_references_heading(self):
        assert "## Source References" in self._md()

    def test_contains_appendix_heading_when_non_empty(self):
        assert "## Appendix" in self._md()

    def test_confidence_badge_present(self):
        md = self._md()
        assert "Confidence:" in md

    def test_high_confidence_shows_check(self):
        assert "High" in self._md()

    def test_low_confidence_shows_warning(self):
        data = {**FULL_RESEARCH, "confidence_level": "low"}
        md = generate_report("t", data)
        assert "Low" in format_report_as_markdown(md)

    def test_generated_date_in_header(self):
        md = self._md()
        assert "Generated:" in md
        assert "2026" in md or "May" in md

    def test_resources_formatted_as_table(self):
        md = self._md()
        assert "| Source |" in md or "| [" in md

    def test_numbered_source_references(self):
        md = self._md()
        assert "1. https://" in md or "1. http" in md

    def test_opportunities_section_contains_content(self):
        md = self._md()
        assert "### Opportunities" in md

    def test_risks_section_contains_content(self):
        md = self._md()
        assert "### Risks" in md

    def test_no_appendix_when_empty(self):
        report = generate_report("x", MINIMAL_RESEARCH)
        md = format_report_as_markdown(report)
        assert "## Appendix" not in md

    def test_market_momentum_in_trend_section(self):
        md = self._md()
        assert "Market Momentum:" in md


# ═══════════════════════════════════════════════════════════════════════════════
# 8. format_report_as_text
# ═══════════════════════════════════════════════════════════════════════════════

class TestFormatReportAsText:

    def _text(self):
        report = generate_report("transformer architecture", FULL_RESEARCH)
        return format_report_as_text(report)

    def test_returns_string(self):
        assert isinstance(self._text(), str)

    def test_no_markdown_headings(self):
        text = self._text()
        assert not any(line.startswith("#") for line in text.splitlines())

    def test_no_bold_syntax(self):
        assert "**" not in self._text()

    def test_contains_executive_summary_label(self):
        assert "Executive Summary" in self._text()

    def test_links_replaced_with_text(self):
        text = self._text()
        assert "[" not in text or "http" not in text.split("[")[1].split("]")[0]

    def test_non_empty(self):
        assert len(self._text()) > 100


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Action router integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestActionRouterIntegration:

    def test_detect_generate_report(self):
        from backend.services.action_router_service import detect_action
        assert detect_action("generate a research report") == "research_report"

    def test_detect_create_report(self):
        from backend.services.action_router_service import detect_action
        assert detect_action("create a report on this topic") == "research_report"

    def test_detect_research_report_phrase(self):
        from backend.services.action_router_service import detect_action
        assert detect_action("show me the research report") == "research_report"

    def test_detect_full_report(self):
        from backend.services.action_router_service import detect_action
        assert detect_action("give me the full report") == "research_report"

    def test_detect_detailed_report(self):
        from backend.services.action_router_service import detect_action
        assert detect_action("can you make a detailed report") == "research_report"

    def test_detect_format_findings(self):
        from backend.services.action_router_service import detect_action
        assert detect_action("format my findings into a document") == "research_report"

    def test_dispatch_returns_dict_on_stored_research(self):
        from backend.services.action_router_service import dispatch_action
        with patch("backend.services.deep_research_service.get_stored_research",
                   return_value=FULL_RESEARCH):
            result = dispatch_action("research_report", "transformer architecture", {})
        assert isinstance(result, dict)
        assert result["found"] is True

    def test_dispatch_success_false_when_no_research(self):
        from backend.services.action_router_service import dispatch_action
        with patch("backend.services.deep_research_service.get_stored_research",
                   return_value=None):
            result = dispatch_action("research_report", "unknown topic", {})
        assert result["found"] is False

    def test_dispatch_instruction_contains_markdown_report(self):
        from backend.services.action_router_service import dispatch_action
        with patch("backend.services.deep_research_service.get_stored_research",
                   return_value=FULL_RESEARCH):
            result = dispatch_action("research_report", "transformer architecture", {})
        assert "## Key Findings" in result["instruction"]

    def test_dispatch_instruction_prompts_research_when_missing(self):
        from backend.services.action_router_service import dispatch_action
        with patch("backend.services.deep_research_service.get_stored_research",
                   return_value=None):
            result = dispatch_action("research_report", "unknown topic", {})
        assert "deep research" in result["instruction"].lower()

    def test_report_action_higher_priority_than_find_reports(self):
        from backend.services.action_router_service import detect_action
        assert detect_action("generate a detailed report on AI") == "research_report"


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Edge cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:

    def test_topic_with_special_chars_does_not_raise(self):
        data = {**MINIMAL_RESEARCH}
        report = generate_report("C++ & Rust (2024)", data)
        assert report["topic"] == "C++ & Rust (2024)"

    def test_none_sources_skipped(self):
        data = {**FULL_RESEARCH, "sources": [None, "", "https://arxiv.org/abs/1"]}
        report = generate_report("t", data)
        refs = report["sections"]["source_references"]
        assert all(r and r.startswith("http") for r in refs)

    def test_industry_data_enriches_opportunities(self):
        opps_without = _extract_opportunities(FULL_RESEARCH, None)
        opps_with    = _extract_opportunities(FULL_RESEARCH, INDUSTRY_DATA)
        assert len(opps_with) >= len(opps_without)

    def test_tradeoff_without_verdict_still_included(self):
        data = {**FULL_RESEARCH, "tradeoffs": [{"dimension": "Speed vs Quality", "verdict": ""}]}
        risks = _extract_risks(data)
        assert any("Speed vs Quality" in r for r in risks)

    def test_score_momentum_empty_texts(self):
        assert _score_momentum([]) == "stable"

    def test_score_momentum_accelerating(self):
        assert _score_momentum(["rapidly growing emerging novel breakthrough"]) == "accelerating"

    def test_score_momentum_declining(self):
        assert _score_momentum(["declining legacy obsolete saturated deprecated"]) == "declining"

    def test_generated_at_formatted_correctly(self):
        report = generate_report("test", FULL_RESEARCH)
        md = format_report_as_markdown(report)
        assert "May" in md or "2026" in md

    def test_report_without_viewpoints_does_not_raise(self):
        data = {**FULL_RESEARCH, "viewpoint_comparison": []}
        report = generate_report("t", data)
        assert report is not None

    def test_format_text_strips_all_hash_headings(self):
        report = generate_report("t", FULL_RESEARCH)
        text = format_report_as_text(report)
        assert not any(line.startswith("#") for line in text.splitlines())
