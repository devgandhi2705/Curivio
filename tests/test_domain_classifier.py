"""
Tests for domain_classifier_service.

All tests are pure unit tests — no API calls, no DB access, no file I/O.
Domain classification is deterministic keyword matching, so every assertion
is exact.

Run with:
    pytest tests/test_domain_classifier.py -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.domain_classifier_service import (
    DOMAIN_UNCATEGORIZED,
    DOMAINS,
    build_retrieval_query,
    classify_domain,
    format_domain_directive,
    get_domain_context,
)

# ── Fixtures: one representative phrase per domain ────────────────────────────

AI_TOPICS = [
    "Introduction to neural networks and deep learning",
    "Fine-tuning LLMs with LoRA and PEFT",
    "RAG pipeline with vector embeddings",
    "Reinforcement learning agent for game playing",
    "Transformer architecture attention mechanisms",
    "Hugging Face model inference optimization",
]

FINANCE_TOPICS = [
    "Portfolio optimization using Monte Carlo simulation",
    "Credit risk modeling for bank loan defaults",
    "Cryptocurrency market volatility analysis",
    "Basel IV capital requirements for banks",
    "Options pricing with Black-Scholes model",
    "Fintech payment processing compliance",
]

PHARMA_TOPICS = [
    "Phase III clinical trial design for oncology",
    "FDA drug approval NDA submission process",
    "Biosimilar development and EMA guidelines",
    "GMP manufacturing compliance for biologics",
    "Pharmacokinetics of oral drug compounds",
    "Clinical trial adverse event reporting",
]

MANUFACTURING_TOPICS = [
    "Lean manufacturing and Six Sigma implementation",
    "Predictive maintenance using IoT sensor data",
    "CNC machining tolerances and quality control",
    "Industry 4.0 automation in factory assembly",
    "OEE improvement through Kaizen workshops",
    "ERP integration with MES for production planning",
]

EXPORT_TOPICS = [
    "Export customs documentation and HS codes",
    "Incoterms FOB vs CIF trade contract terms",
    "WTO tariff schedules and bilateral trade agreements",
    "Letter of credit documentary compliance",
    "DGFT export incentive schemes for manufacturers",
    "International logistics and 3PL freight forwarding",
]

TECHNOLOGY_TOPICS = [
    "Kubernetes container orchestration and DevOps pipelines",
    "AWS microservices architecture with serverless functions",
    "Cybersecurity encryption protocols for web APIs",
    "Backend database SQL optimization techniques",
    "Frontend React component architecture best practices",
    "CI/CD pipeline with Docker and cloud deployment",
]

BUSINESS_TOPICS = [
    "Startup growth strategy and venture capital funding",
    "OKR framework for management and team alignment",
    "Marketing customer acquisition and sales funnels",
    "McKinsey consulting framework for business strategy",
    "Merger and acquisition due diligence process",
    "Agile scrum team operations and sprint planning",
]

UNCLASSIFIED_TOPICS = [
    "The history of ancient Rome",
    "How to bake sourdough bread",
    "Introduction to chess openings",
]


# ── 1. classify_domain ────────────────────────────────────────────────────────

class TestClassifyDomain:

    @pytest.mark.parametrize("topic", AI_TOPICS)
    def test_ai_topics(self, topic):
        assert classify_domain(topic) == "AI", f"Expected AI for: {topic!r}"

    @pytest.mark.parametrize("topic", FINANCE_TOPICS)
    def test_finance_topics(self, topic):
        assert classify_domain(topic) == "Finance", f"Expected Finance for: {topic!r}"

    @pytest.mark.parametrize("topic", PHARMA_TOPICS)
    def test_pharma_topics(self, topic):
        assert classify_domain(topic) == "Pharmaceutical", f"Expected Pharmaceutical for: {topic!r}"

    @pytest.mark.parametrize("topic", MANUFACTURING_TOPICS)
    def test_manufacturing_topics(self, topic):
        assert classify_domain(topic) == "Manufacturing", f"Expected Manufacturing for: {topic!r}"

    @pytest.mark.parametrize("topic", EXPORT_TOPICS)
    def test_export_topics(self, topic):
        assert classify_domain(topic) == "Export/Trade", f"Expected Export/Trade for: {topic!r}"

    @pytest.mark.parametrize("topic", TECHNOLOGY_TOPICS)
    def test_technology_topics(self, topic):
        assert classify_domain(topic) == "Technology", f"Expected Technology for: {topic!r}"

    @pytest.mark.parametrize("topic", BUSINESS_TOPICS)
    def test_business_topics(self, topic):
        assert classify_domain(topic) == "Business", f"Expected Business for: {topic!r}"

    @pytest.mark.parametrize("topic", UNCLASSIFIED_TOPICS)
    def test_unclassified_topics(self, topic):
        assert classify_domain(topic) == DOMAIN_UNCATEGORIZED, f"Expected General for: {topic!r}"

    def test_empty_string_returns_uncategorized(self):
        assert classify_domain("") == DOMAIN_UNCATEGORIZED

    def test_whitespace_only_returns_uncategorized(self):
        assert classify_domain("   ") == DOMAIN_UNCATEGORIZED

    def test_case_insensitive(self):
        assert classify_domain("NEURAL NETWORK DEEP LEARNING") == "AI"
        assert classify_domain("PORTFOLIO STOCK TRADING") == "Finance"

    def test_hyphenated_tokens(self):
        # "fine-tuning" should match AI keyword "finetuning"
        assert classify_domain("fine-tuning language models") == "AI"

    def test_return_type_is_str(self):
        assert isinstance(classify_domain("machine learning"), str)

    def test_result_is_in_domains_list(self):
        for topic in AI_TOPICS + FINANCE_TOPICS + PHARMA_TOPICS:
            assert classify_domain(topic) in DOMAINS


# ── 2. get_domain_context ─────────────────────────────────────────────────────

class TestGetDomainContext:

    def test_returns_dict_with_required_keys(self):
        ctx = get_domain_context("machine learning model")
        assert set(ctx.keys()) == {"domain", "retrieval", "resources", "directive"}

    def test_domain_field_matches_classify_domain(self):
        text = "clinical trial FDA drug approval"
        ctx  = get_domain_context(text)
        assert ctx["domain"] == classify_domain(text)

    def test_retrieval_has_required_keys(self):
        ctx = get_domain_context("machine learning")
        ret = ctx["retrieval"]
        assert "query_templates" in ret
        assert "source_priority" in ret
        assert "search_depth"    in ret
        assert "max_results"     in ret

    def test_retrieval_query_templates_are_strings(self):
        ctx = get_domain_context("transformer neural network")
        for tmpl in ctx["retrieval"]["query_templates"]:
            assert isinstance(tmpl, str)
            assert "{topic}" in tmpl   # templates must be formattable

    def test_resources_has_required_keys(self):
        ctx  = get_domain_context("fintech payment processing")
        res  = ctx["resources"]
        assert "primary_sources" in res
        assert "databases"       in res
        assert "communities"     in res
        assert "tools"           in res

    def test_directive_is_string(self):
        ctx = get_domain_context("export tariff customs")
        assert isinstance(ctx["directive"], str)

    def test_ai_directive_mentions_domain(self):
        ctx = get_domain_context("transformer architecture attention")
        assert "AI" in ctx["directive"] or "Machine Learning" in ctx["directive"]

    def test_finance_directive_mentions_domain(self):
        ctx = get_domain_context("stock market portfolio optimization")
        assert "Finance" in ctx["directive"]

    def test_pharma_directive_mentions_domain(self):
        ctx = get_domain_context("clinical trial adverse events")
        assert "Pharmaceutical" in ctx["directive"] or "Pharma" in ctx["directive"]

    def test_unclassified_directive_is_empty_string(self):
        ctx = get_domain_context("ancient Roman history")
        assert ctx["directive"] == ""

    def test_ai_source_priority_includes_arxiv(self):
        ctx = get_domain_context("LLM inference benchmark")
        sources = [s.lower() for s in ctx["retrieval"]["source_priority"]]
        assert any("arxiv" in s for s in sources)

    def test_pharma_source_priority_includes_pubmed(self):
        ctx = get_domain_context("drug clinical trial phase")
        sources = [s.lower() for s in ctx["retrieval"]["source_priority"]]
        assert any("pubmed" in s for s in sources)

    def test_max_results_is_positive_int(self):
        for topic in ["neural network", "stock market", "drug trial"]:
            ctx = get_domain_context(topic)
            assert isinstance(ctx["retrieval"]["max_results"], int)
            assert ctx["retrieval"]["max_results"] > 0


# ── 3. format_domain_directive ────────────────────────────────────────────────

class TestFormatDomainDirective:

    def test_returns_non_empty_for_classified_domain(self):
        assert format_domain_directive("machine learning neural network") != ""

    def test_returns_empty_for_unclassified(self):
        assert format_domain_directive("sourdough bread recipe") == ""

    def test_return_type_is_str(self):
        assert isinstance(format_domain_directive("kubernetes docker deployment"), str)

    def test_directive_has_no_leading_trailing_whitespace(self):
        directive = format_domain_directive("manufacturing lean production")
        assert directive == directive.strip()

    def test_all_domains_have_non_empty_directives(self):
        domain_samples = {
            "AI":              "neural network deep learning",
            "Finance":         "stock market portfolio trading",
            "Pharmaceutical":  "clinical trial FDA drug approval",
            "Manufacturing":   "lean manufacturing production automation",
            "Export/Trade":    "export customs tariff trade",
            "Technology":      "kubernetes cloud devops software",
            "Business":        "strategy management startup venture",
        }
        for domain, sample in domain_samples.items():
            directive = format_domain_directive(sample)
            assert directive, f"Expected non-empty directive for domain '{domain}' (sample: {sample!r})"


# ── 4. build_retrieval_query ──────────────────────────────────────────────────

class TestBuildRetrievalQuery:

    def test_topic_is_substituted_in_output(self):
        query = build_retrieval_query("transformer architecture")
        assert "transformer architecture" in query

    def test_returns_string(self):
        assert isinstance(build_retrieval_query("portfolio risk"), str)

    def test_template_index_0_is_default(self):
        q0 = build_retrieval_query("LLM finetuning", 0)
        q_default = build_retrieval_query("LLM finetuning")
        assert q0 == q_default

    def test_template_index_1_differs_from_index_0(self):
        topic = "clinical trial drug approval"
        q0 = build_retrieval_query(topic, 0)
        q1 = build_retrieval_query(topic, 1)
        # At least one domain should have ≥2 templates that differ
        # (Pharmaceutical has 3 distinct templates)
        assert q0 != q1

    def test_out_of_range_index_does_not_raise(self):
        # Should clamp to last available template
        query = build_retrieval_query("stock market analysis", 999)
        assert "stock market analysis" in query

    def test_empty_topic_does_not_raise(self):
        query = build_retrieval_query("")
        assert isinstance(query, str)
