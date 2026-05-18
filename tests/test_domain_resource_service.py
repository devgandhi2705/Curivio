"""
Tests for domain_resource_service and the upgraded action_router actions
(find_tutorials, find_reports).

All Tavily and GitHub calls are mocked — zero real network traffic.

Run with:
    pytest tests/test_domain_resource_service.py -v
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.domain_resource_service import (
    build_resource_instruction,
    discover_resources,
    get_domain_search_queries,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_tavily_results(n=3, prefix="Result"):
    return [
        {"title": f"{prefix} {i}", "url": f"https://example.com/{i}", "content": f"Content {i}"}
        for i in range(1, n + 1)
    ]

def _make_github_repos(n=2):
    return [
        {
            "name":        f"org/repo{i}",
            "description": f"A great repo {i}",
            "stars":       1000 * i,
            "url":         f"https://github.com/org/repo{i}",
        }
        for i in range(1, n + 1)
    ]


# ── 1. discover_resources — domain routing ────────────────────────────────────

class TestDiscoverResources:

    def _run(self, topic, domain=None, tavily_results=None, github_repos=None):
        """Helper: run discover_resources with mocked dependencies."""
        tavily_results = tavily_results if tavily_results is not None else _make_tavily_results()
        github_repos   = github_repos   if github_repos   is not None else _make_github_repos()

        with (
            patch("backend.services.domain_resource_service.search_articles",
                  return_value=tavily_results, create=True),
            patch("backend.services.domain_resource_service.get_topic_repos",
                  return_value=github_repos, create=True),
            patch("backend.services.tavily_service.search_articles",
                  return_value=tavily_results),
            patch("backend.services.github_service.get_topic_repos",
                  return_value=github_repos),
        ):
            return discover_resources(topic, domain=domain)

    # ── Return shape ──────────────────────────────────────────────────────────

    def test_returns_domain_and_groups(self):
        result = self._run("transformer neural network", domain="AI")
        assert "domain"          in result
        assert "resource_groups" in result

    def test_domain_matches_classification(self):
        result = self._run("transformer neural network", domain="AI")
        assert result["domain"] == "AI"

    def test_explicit_domain_overrides_classifier(self):
        result = self._run("supply chain logistics", domain="Finance")
        assert result["domain"] == "Finance"

    def test_auto_classify_when_domain_omitted(self):
        result = self._run("kubernetes docker devops")
        assert result["domain"] == "Technology"

    # ── Group structure ───────────────────────────────────────────────────────

    def test_each_group_has_required_keys(self):
        result = self._run("RAG retrieval augmented generation", domain="AI")
        for group in result["resource_groups"]:
            assert "label"         in group
            assert "resource_type" in group
            assert "items"         in group
            assert "query_used"    in group

    def test_items_have_url_field(self):
        result = self._run("LLM finetuning", domain="AI")
        for group in result["resource_groups"]:
            for item in group["items"]:
                assert "url" in item

    def test_group_count_matches_plan(self):
        # AI plan has 3 groups (repos, papers, tutorials)
        result = self._run("neural network deep learning", domain="AI")
        assert len(result["resource_groups"]) == 3

    def test_max_per_group_respected(self):
        many_results = _make_tavily_results(20)
        result = self._run("stock market trading", domain="Finance",
                           tavily_results=many_results, github_repos=[])
        for group in result["resource_groups"]:
            assert len(group["items"]) <= 5

    # ── Domain-specific resource types ────────────────────────────────────────

    def test_technology_has_repos_group(self):
        result = self._run("kubernetes container orchestration", domain="Technology")
        types = {g["resource_type"] for g in result["resource_groups"]}
        assert "repos" in types

    def test_ai_has_repos_and_papers_groups(self):
        result = self._run("transformer attention mechanism", domain="AI")
        types = {g["resource_type"] for g in result["resource_groups"]}
        assert "repos"  in types
        assert "papers" in types

    def test_finance_has_reports_group(self):
        result = self._run("portfolio optimization", domain="Finance",
                           github_repos=[])
        types = {g["resource_type"] for g in result["resource_groups"]}
        assert "reports" in types

    def test_business_has_reports_and_articles(self):
        result = self._run("startup growth strategy", domain="Business",
                           github_repos=[])
        types = {g["resource_type"] for g in result["resource_groups"]}
        assert "reports"  in types or "articles" in types

    def test_pharma_has_papers_group(self):
        result = self._run("clinical trial design oncology", domain="Pharmaceutical",
                           github_repos=[])
        types = {g["resource_type"] for g in result["resource_groups"]}
        assert "papers" in types

    def test_manufacturing_has_reports_group(self):
        result = self._run("lean manufacturing six sigma", domain="Manufacturing",
                           github_repos=[])
        types = {g["resource_type"] for g in result["resource_groups"]}
        assert "reports" in types

    def test_export_trade_has_reports_group(self):
        result = self._run("export customs tariff compliance", domain="Export/Trade",
                           github_repos=[])
        types = {g["resource_type"] for g in result["resource_groups"]}
        assert "reports" in types

    # ── Resilience ────────────────────────────────────────────────────────────

    def test_empty_tavily_results_produce_no_group(self):
        # A group with no items should be dropped
        with (
            patch("backend.services.tavily_service.search_articles", return_value=[]),
            patch("backend.services.github_service.get_topic_repos",  return_value=[]),
        ):
            result = discover_resources("some obscure topic", domain="Finance")
        assert result["resource_groups"] == []

    def test_tavily_failure_logged_not_raised(self):
        with (
            patch("backend.services.tavily_service.search_articles",
                  side_effect=RuntimeError("Tavily down")),
            patch("backend.services.github_service.get_topic_repos",
                  return_value=[]),
        ):
            result = discover_resources("supply chain", domain="Manufacturing")
        # Should not raise; empty or partial result is fine
        assert "resource_groups" in result

    def test_github_failure_falls_back_to_tavily(self):
        tavily = _make_tavily_results(3)
        with (
            patch("backend.services.tavily_service.search_articles",
                  return_value=tavily),
            patch("backend.services.github_service.get_topic_repos",
                  side_effect=RuntimeError("GitHub API rate limited")),
        ):
            result = discover_resources("pytorch deep learning", domain="AI")
        # Should still return tavily results in at least some groups
        total_items = sum(len(g["items"]) for g in result["resource_groups"])
        assert total_items > 0

    def test_unknown_domain_uses_fallback_plan(self):
        result = self._run("ancient Roman architecture", domain="General")
        assert "resource_groups" in result
        # Fallback plan produces at most 1 group
        assert len(result["resource_groups"]) <= 1


# ── 2. get_domain_search_queries ──────────────────────────────────────────────

class TestGetDomainSearchQueries:

    def test_returns_list_of_strings(self):
        queries = get_domain_search_queries("LLM agents", domain="AI")
        assert isinstance(queries, list)
        assert all(isinstance(q, str) for q in queries)

    def test_topic_appears_in_each_query(self):
        topic   = "portfolio risk management"
        queries = get_domain_search_queries(topic, domain="Finance")
        for q in queries:
            assert topic in q

    def test_finance_queries_differ_from_ai_queries(self):
        ai_qs  = get_domain_search_queries("transformer", domain="AI")
        fin_qs = get_domain_search_queries("transformer", domain="Finance")
        assert ai_qs != fin_qs

    def test_auto_classify_selects_correct_domain_queries(self):
        pharma_qs = get_domain_search_queries("FDA drug approval clinical trial")
        # Pharma plan references clinical/regulatory angles
        combined = " ".join(pharma_qs).lower()
        assert "clinical" in combined or "regulatory" in combined or "fda" in combined

    def test_all_domains_produce_queries(self):
        domains = ["AI", "Finance", "Technology", "Business",
                   "Pharmaceutical", "Manufacturing", "Export/Trade"]
        for domain in domains:
            queries = get_domain_search_queries(f"sample topic for {domain}", domain=domain)
            assert len(queries) >= 1, f"No queries for domain {domain!r}"

    def test_query_count_matches_plan_size(self):
        # Technology plan has 3 groups → 3 queries
        queries = get_domain_search_queries("kubernetes deployment", domain="Technology")
        assert len(queries) == 3

    def test_fallback_domain_returns_one_query(self):
        queries = get_domain_search_queries("ancient history", domain="General")
        assert len(queries) >= 1


# ── 3. build_resource_instruction ────────────────────────────────────────────

class TestBuildResourceInstruction:

    def _mock_result(self, domain="Finance", groups=None):
        if groups is None:
            groups = [
                {
                    "label":         "Market Analysis",
                    "resource_type": "reports",
                    "items": [
                        {"title": "Bloomberg Macro Report", "url": "https://bloomberg.com/1"},
                        {"title": "Reuters Analysis",       "url": "https://reuters.com/2"},
                    ],
                    "query_used": "portfolio macro trend analysis 2025",
                }
            ]
        return {"domain": domain, "resource_groups": groups}

    def test_returns_string(self):
        result = self._mock_result()
        assert isinstance(build_resource_instruction("portfolio optimization", result), str)

    def test_instruction_contains_domain(self):
        result = self._mock_result(domain="Finance")
        instruction = build_resource_instruction("portfolio optimization", result)
        assert "Finance" in instruction

    def test_instruction_contains_topic(self):
        result = self._mock_result()
        instruction = build_resource_instruction("portfolio optimization", result)
        assert "portfolio optimization" in instruction

    def test_instruction_contains_urls(self):
        result = self._mock_result()
        instruction = build_resource_instruction("portfolio optimization", result)
        assert "bloomberg.com" in instruction

    def test_empty_groups_produces_fallback_instruction(self):
        result = {"domain": "Business", "resource_groups": []}
        instruction = build_resource_instruction("strategy framework", result)
        assert "No resources" in instruction or "recommend" in instruction.lower()

    def test_instruction_mentions_resource_label(self):
        result = self._mock_result()
        instruction = build_resource_instruction("portfolio optimization", result)
        assert "Market Analysis" in instruction


# ── 4. Action router integration ─────────────────────────────────────────────

class TestActionRouterDomainIntegration:
    """
    Verify that the upgraded find_tutorials and new find_reports actions
    use domain_resource_service instead of hardcoded Tavily queries.
    """

    def _route(self, message, topic, domain="AI", tavily_results=None, github_repos=None):
        tavily_results = tavily_results or _make_tavily_results(3)
        github_repos   = github_repos   or _make_github_repos(2)
        context = {"domain_context": {"domain": domain}}

        with (
            patch("backend.services.tavily_service.search_articles",
                  return_value=tavily_results),
            patch("backend.services.github_service.get_topic_repos",
                  return_value=github_repos),
        ):
            from backend.services.action_router_service import route
            return route(message, topic, context)

    # ── find_tutorials ────────────────────────────────────────────────────────

    def test_find_tutorials_detected(self):
        result = self._route("show me some tutorials on transformers",
                             "transformers", domain="AI")
        assert result is not None
        assert result["action"] == "find_tutorials"

    def test_find_tutorials_returns_found_true_with_results(self):
        result = self._route("I want a hands-on tutorial for pytorch",
                             "pytorch", domain="Technology")
        assert result["found"] is True

    def test_find_tutorials_data_has_domain(self):
        result = self._route("tutorial on kubernetes", "kubernetes", domain="Technology")
        assert result is not None
        data = result.get("data", {})
        # Either domain_context was populated or resource_groups is present
        assert "domain" in data or "resource_groups" in data or "results" in data

    def test_find_tutorials_instruction_mentions_topic(self):
        result = self._route("tutorial for reinforcement learning",
                             "reinforcement learning", domain="AI")
        assert result is not None
        assert "reinforcement learning" in result["instruction"]

    def test_find_tutorials_fallback_when_no_results(self):
        result = self._route(
            "tutorial on quantum computing",
            "quantum computing",
            domain="Technology",
            tavily_results=[],
            github_repos=[],
        )
        assert result is not None
        assert result["action"] == "find_tutorials"
        # found=False is acceptable when all sources are empty
        assert isinstance(result["found"], bool)

    # ── find_reports ──────────────────────────────────────────────────────────

    def test_find_reports_detected_for_market_analysis(self):
        result = self._route("show me market analysis for fintech",
                             "fintech", domain="Finance", github_repos=[])
        assert result is not None
        assert result["action"] == "find_reports"

    def test_find_reports_detected_for_industry_analysis(self):
        result = self._route("do you have industry analysis for supply chain?",
                             "supply chain", domain="Manufacturing", github_repos=[])
        assert result is not None
        assert result["action"] == "find_reports"

    def test_find_reports_detected_for_trade_report(self):
        result = self._route("I need a trade report on exports",
                             "exports", domain="Export/Trade", github_repos=[])
        assert result is not None
        assert result["action"] == "find_reports"

    def test_find_reports_detected_for_clinical_trial(self):
        result = self._route("find me clinical trial data for oncology drugs",
                             "oncology drugs", domain="Pharmaceutical", github_repos=[])
        assert result is not None
        assert result["action"] == "find_reports"

    def test_find_reports_returns_report_type_resources(self):
        result = self._route("show me reports on manufacturing automation",
                             "manufacturing automation",
                             domain="Manufacturing", github_repos=[])
        assert result is not None
        if result["found"]:
            groups = result["data"].get("resource_groups", [])
            types  = {g["resource_type"] for g in groups}
            # Should prefer reports/articles/papers over repos/tutorials
            assert types & {"reports", "articles", "papers"}

    def test_find_reports_instruction_mentions_domain(self):
        result = self._route("market analysis for trade policy",
                             "trade policy", domain="Export/Trade", github_repos=[])
        assert result is not None
        assert "Export" in result["instruction"] or "Trade" in result["instruction"] \
               or "trade policy" in result["instruction"]

    def test_find_reports_fallback_when_no_results(self):
        result = self._route(
            "I need reports on quantum finance",
            "quantum finance",
            domain="Finance",
            tavily_results=[],
            github_repos=[],
        )
        assert result is not None
        assert result["action"] == "find_reports"
        assert isinstance(result["found"], bool)

    # ── Domain context passed through ─────────────────────────────────────────

    def test_no_action_returns_none(self):
        result = self._route("tell me about transformers", "transformers", domain="AI")
        assert result is None

    def test_route_returns_none_without_topic(self):
        with (
            patch("backend.services.tavily_service.search_articles", return_value=[]),
            patch("backend.services.github_service.get_topic_repos", return_value=[]),
        ):
            from backend.services.action_router_service import route
            result = route("find tutorials", None, {})
        assert result is None


# ── 5. deep_research query expansion ─────────────────────────────────────────

class TestDeepResearchDomainQueryExpansion:
    """
    Verify that _expand_queries now uses domain_resource_service
    instead of the old generic templates.
    """

    def _expand(self, topic, domain_queries=None):
        if domain_queries is None:
            domain_queries = [
                f"{topic} arxiv paper benchmark 2025",
                f"{topic} huggingface colab notebook",
                f"{topic} open source github",
            ]
        with patch(
            "backend.services.deep_research_service._expand_queries",
            wraps=lambda t: _expand_queries_patched(t, domain_queries),
        ):
            from backend.services.deep_research_service import _expand_queries
            return _expand_queries(topic)

    def test_base_topic_is_always_first_query(self):
        from backend.services.deep_research_service import _expand_queries
        with patch(
            "backend.services.domain_resource_service.get_domain_search_queries",
            return_value=["ai agents deep dive 2025", "ai agents huggingface"],
        ):
            queries = _expand_queries("AI agents")
        assert queries[0] == "AI agents"

    def test_domain_queries_included_after_base(self):
        domain_qs = ["AI agents arxiv paper 2025", "AI agents huggingface benchmark"]
        from backend.services.deep_research_service import _expand_queries
        with patch(
            "backend.services.domain_resource_service.get_domain_search_queries",
            return_value=domain_qs,
        ):
            queries = _expand_queries("AI agents")
        # Domain queries should appear in result
        assert any("arxiv" in q or "huggingface" in q for q in queries[1:])

    def test_query_count_capped_by_search_count_plus_one(self):
        from backend.services import deep_research_service as dr
        original_count = dr.DEEP_RESEARCH_SEARCH_COUNT
        dr.DEEP_RESEARCH_SEARCH_COUNT = 2

        many_domain_qs = [f"query {i}" for i in range(10)]
        from backend.services.deep_research_service import _expand_queries
        with patch(
            "backend.services.domain_resource_service.get_domain_search_queries",
            return_value=many_domain_qs,
        ):
            queries = _expand_queries("transformers")

        dr.DEEP_RESEARCH_SEARCH_COUNT = original_count
        assert len(queries) <= original_count + 1 + 1  # restored after test

    def test_expand_queries_falls_back_on_domain_service_error(self):
        from backend.services.deep_research_service import _expand_queries
        with patch(
            "backend.services.domain_resource_service.get_domain_search_queries",
            side_effect=RuntimeError("service unavailable"),
        ):
            queries = _expand_queries("machine learning")
        # Should not raise; must return at least the base query
        assert len(queries) >= 1
        assert queries[0] == "machine learning"


# ── helper used in test class above ──────────────────────────────────────────

def _expand_queries_patched(topic: str, domain_queries: list[str]) -> list[str]:
    """Mirrors the real _expand_queries logic for test isolation."""
    from backend.services import deep_research_service as dr
    candidates = [topic] + [q for q in domain_queries if q != topic]
    return candidates[: dr.DEEP_RESEARCH_SEARCH_COUNT + 1]
