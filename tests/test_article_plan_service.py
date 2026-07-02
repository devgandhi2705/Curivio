"""
Tests for article_plan_service.py — Phase 7.4

Covers:
  - _is_dummy_url: dummy patterns, empty string, real URLs
  - _derive_topic_hint: title truncation, empty title, long title
  - build_article_plans:
      count honored (never more plans than valid sources)
      primary source is by rank
      supporting sources added correctly
      dummy URLs excluded upfront
      empty input returns empty
      fewer articles than count handled
  - validate_plans:
      valid plans pass
      empty plan list fails
      plan with < MIN_SOURCES fails
      dummy URL in plan fails
      empty URL in plan fails
  - plans_to_prompt_block:
      output contains slot numbers
      output contains source IDs when core_articles supplied
      output contains article titles
      empty plans returns empty string
      handles missing core_articles gracefully

Run:
    pytest tests/test_article_plan_service.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.article_plan_service import (
    MAX_SOURCES,
    MIN_SOURCES,
    ArticlePlan,
    _derive_topic_hint,
    _generate_why_used,
    _is_dummy_url,
    build_article_plans,
    plans_to_prompt_block,
    validate_plans,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _art(url: str, title: str = "Test Article", score: float = 0.5) -> dict:
    return {"url": url, "title": title, "_retrieval_score": score}


def _art_with_content(url: str, title: str, score: float, content: str) -> dict:
    return {"url": url, "title": title, "_retrieval_score": score, "content": content}


_TRADE_CONTENT_A = (
    "Founders expanding internationally often underestimate trade barriers, tariff costs, "
    "and market entry requirements. Export strategy mistakes include poor market selection, "
    "insufficient due diligence on local regulations, and underestimating logistics. "
    "Global trade dynamics require careful analysis of trade agreements, currency risk, "
    "and supply chain resilience. Companies must evaluate international market opportunities "
    "against domestic growth potential before committing to export programs."
)
_TRADE_CONTENT_B = (
    "World Bank trade data shows global trade volumes recovering after supply chain disruptions. "
    "Emerging markets drive export growth while developed economies face trade deficit pressures. "
    "Trade finance gaps continue to hinder small business international expansion. "
    "The report highlights tariff barriers, logistics costs, and market access challenges "
    "facing exporters. Trade policy uncertainty remains a key risk for global commerce."
)
_TRADE_CONTENT_C = (
    "IMF global trade outlook projects moderate growth in merchandise trade and services exports. "
    "Trade policy uncertainty, tariff disputes, and geopolitical risks weigh on global commerce. "
    "Emerging markets benefit from commodity export revenues while import costs rise. "
    "Supply chain realignment continues as companies diversify from single-source suppliers. "
    "International trade financing conditions have tightened, affecting export credit availability."
)
_TRADE_CONTENT_D = (
    "Market entry analysis requires evaluating trade agreements, local competition, "
    "regulatory requirements, and distribution networks. Financial Times examines how companies "
    "select international markets and structure their export strategies. Due diligence on "
    "trade barriers, tariff schedules, and customs procedures is essential for successful "
    "market entry. Supply chain localization versus global sourcing trade-offs are central."
)
_TRADE_CONTENT_E = (
    "Supply chain risks have intensified due to geopolitical tensions, trade policy shifts, "
    "and climate-related disruptions. Companies are reassessing global supply chain exposure "
    "and building resilience through diversification and nearshoring. Trade route vulnerabilities "
    "and logistics bottlenecks affect export competitiveness. Supply chain risk management "
    "has become a strategic priority for international trade-dependent businesses."
)
_TRADE_CONTENT_F = (
    "Globalization trends show bifurcation between regionalized supply chains and continued "
    "global trade flows. McKinsey analysis highlights how companies are adapting trade strategies "
    "to new geopolitical realities. Export market diversification reduces concentration risk. "
    "International trade patterns are shifting as tariff and non-tariff barriers reshape "
    "comparative advantages across industries and regions."
)

REAL_ARTICLES = [
    _art_with_content("https://reuters.com/a",     "Export Strategy Mistakes Founders Make", 0.9, _TRADE_CONTENT_A),
    _art_with_content("https://worldbank.org/b",   "World Bank Trade Report 2025",           0.8, _TRADE_CONTENT_B),
    _art_with_content("https://imf.org/c",         "IMF Global Trade Outlook",               0.7, _TRADE_CONTENT_C),
    _art_with_content("https://ft.com/d",          "Financial Times Market Entry Analysis",  0.6, _TRADE_CONTENT_D),
    _art_with_content("https://economist.com/e",   "Economist: Supply Chain Risks",          0.5, _TRADE_CONTENT_E),
    _art_with_content("https://mckinsey.com/f",    "McKinsey Report on Globalization",       0.4, _TRADE_CONTENT_F),
]


# ── _is_dummy_url ─────────────────────────────────────────────────────────────

class TestIsDummyUrl:
    def test_empty_string_is_dummy(self):
        assert _is_dummy_url("") is True

    def test_whitespace_only_is_dummy(self):
        assert _is_dummy_url("   ") is True

    def test_example_com_is_dummy(self):
        assert _is_dummy_url("https://example.com/article") is True

    def test_example_org_is_dummy(self):
        assert _is_dummy_url("https://example.org/page") is True

    def test_placeholder_is_dummy(self):
        assert _is_dummy_url("https://placeholder.com") is True

    def test_localhost_is_dummy(self):
        assert _is_dummy_url("http://localhost:8000/article") is True

    def test_loopback_is_dummy(self):
        assert _is_dummy_url("http://127.0.0.1/page") is True

    def test_http_url_literal_is_dummy(self):
        assert _is_dummy_url("http://url") is True

    def test_real_reuters_url_is_not_dummy(self):
        assert _is_dummy_url("https://reuters.com/business/article-2025") is False

    def test_real_worldbank_url_is_not_dummy(self):
        assert _is_dummy_url("https://worldbank.org/en/topic/trade/overview") is False

    def test_real_arxiv_url_is_not_dummy(self):
        assert _is_dummy_url("https://arxiv.org/abs/2301.00001") is False


# ── _derive_topic_hint ────────────────────────────────────────────────────────

class TestDeriveTopicHint:
    def test_returns_first_8_words(self):
        art = _art("https://a.com", "Word1 Word2 Word3 Word4 Word5 Word6 Word7 Word8 Word9 Word10")
        hint = _derive_topic_hint(art)
        assert len(hint.split()) <= 8

    def test_short_title_returned_in_full(self):
        art = _art("https://a.com", "Short Title")
        assert _derive_topic_hint(art) == "Short Title"

    def test_empty_title_returns_default(self):
        art = {"url": "https://a.com", "title": ""}
        assert _derive_topic_hint(art) == "Topic"

    def test_missing_title_returns_default(self):
        art = {"url": "https://a.com"}
        assert _derive_topic_hint(art) == "Topic"

    def test_strips_punctuation(self):
        art = _art("https://a.com", "Export Strategy: Mistakes & Lessons!")
        hint = _derive_topic_hint(art)
        assert ":" not in hint
        assert "!" not in hint

    def test_returns_string(self):
        art = _art("https://a.com", "Some Title")
        assert isinstance(_derive_topic_hint(art), str)


# ── build_article_plans ───────────────────────────────────────────────────────

class TestBuildArticlePlans:
    def test_returns_empty_for_no_articles(self):
        assert build_article_plans([], count=4) == []

    def test_returns_empty_when_all_dummy(self):
        arts = [_art("https://example.com/a"), _art("https://example.com/b")]
        assert build_article_plans(arts, count=4) == []

    def test_count_honored(self):
        plans = build_article_plans(REAL_ARTICLES, count=4)
        assert len(plans) == 4

    def test_never_more_plans_than_valid_articles(self):
        arts = REAL_ARTICLES[:2]
        plans = build_article_plans(arts, count=10)
        assert len(plans) <= 2

    def test_primary_is_highest_ranked(self):
        plans = build_article_plans(REAL_ARTICLES, count=4)
        assert plans[0].primary_source["url"] == REAL_ARTICLES[0]["url"]

    def test_primary_by_rank_order(self):
        plans = build_article_plans(REAL_ARTICLES, count=3)
        for i, plan in enumerate(plans):
            assert plan.primary_source["url"] == REAL_ARTICLES[i]["url"]

    def test_supporting_sources_included(self):
        plans = build_article_plans(REAL_ARTICLES, count=1)
        # slot 1 primary = articles[0]; supporting from articles[1..3]
        assert len(plans[0].assigned_sources) > 1

    def test_primary_not_repeated_in_supporting(self):
        plans = build_article_plans(REAL_ARTICLES, count=4)
        for plan in plans:
            primary_url = plan.primary_source["url"]
            supporting_urls = [s["url"] for s in plan.assigned_sources[1:]]
            assert primary_url not in supporting_urls

    def test_max_sources_per_plan(self):
        plans = build_article_plans(REAL_ARTICLES, count=4)
        for plan in plans:
            assert len(plan.assigned_sources) <= MAX_SOURCES

    def test_dummy_urls_excluded_from_pool(self):
        articles = [
            _art("https://example.com/dummy"),
            _art("https://reuters.com/real", "Real Article"),
        ]
        plans = build_article_plans(articles, count=4)
        all_urls = [url for plan in plans for url in plan.source_urls]
        assert "https://example.com/dummy" not in all_urls
        assert "https://reuters.com/real" in all_urls

    def test_slot_ids_sequential(self):
        plans = build_article_plans(REAL_ARTICLES, count=3)
        assert [p.slot_id for p in plans] == ["slot-1", "slot-2", "slot-3"]

    def test_topic_hints_derived_from_primary(self):
        plans = build_article_plans(REAL_ARTICLES, count=1)
        # Primary of slot-1 = REAL_ARTICLES[0] whose title is "Export Strategy Mistakes..."
        assert "Export" in plans[0].topic_hint

    def test_returns_article_plan_instances(self):
        plans = build_article_plans(REAL_ARTICLES, count=2)
        assert all(isinstance(p, ArticlePlan) for p in plans)


# ── validate_plans ────────────────────────────────────────────────────────────

class TestValidatePlans:
    def test_valid_plans_pass(self):
        plans = build_article_plans(REAL_ARTICLES, count=4)
        ok, errors = validate_plans(plans)
        assert ok is True
        assert errors == []

    def test_empty_plans_fail(self):
        ok, errors = validate_plans([])
        assert ok is False
        assert len(errors) > 0

    def test_plan_with_dummy_url_fails(self):
        bad_plan = ArticlePlan(
            slot_id="slot-1",
            topic_hint="Test",
            assigned_sources=[{"url": "https://example.com/fake", "title": "Fake"}],
        )
        ok, errors = validate_plans([bad_plan])
        assert ok is False
        assert any("dummy" in e.lower() for e in errors)

    def test_plan_with_empty_url_fails(self):
        bad_plan = ArticlePlan(
            slot_id="slot-1",
            topic_hint="Test",
            assigned_sources=[{"url": "", "title": "No URL"}],
        )
        ok, errors = validate_plans([bad_plan])
        assert ok is False
        assert any("empty" in e.lower() for e in errors)

    def test_plan_with_no_sources_fails(self):
        empty_plan = ArticlePlan(slot_id="slot-1", topic_hint="Test", assigned_sources=[])
        ok, errors = validate_plans([empty_plan])
        assert ok is False
        assert any("fewer" in e.lower() or "min" in e.lower() or "sources" in e.lower() for e in errors)

    def test_mixed_valid_invalid_reports_all_errors(self):
        good = ArticlePlan(
            slot_id="slot-1",
            topic_hint="Good",
            assigned_sources=[{"url": "https://reuters.com/a", "title": "Good"}],
        )
        bad = ArticlePlan(
            slot_id="slot-2",
            topic_hint="Bad",
            assigned_sources=[{"url": "https://example.com/dummy", "title": "Bad"}],
        )
        ok, errors = validate_plans([good, bad])
        assert ok is False
        assert len(errors) >= 1


# ── plans_to_prompt_block ─────────────────────────────────────────────────────

class TestPlansToPromptBlock:
    def test_empty_plans_returns_empty_string(self):
        assert plans_to_prompt_block([]) == ""

    def test_output_contains_slot_numbers(self):
        plans = build_article_plans(REAL_ARTICLES, count=3)
        block = plans_to_prompt_block(plans, REAL_ARTICLES)
        assert "SLOT 1" in block
        assert "SLOT 2" in block
        assert "SLOT 3" in block

    def test_output_contains_core_ids(self):
        plans = build_article_plans(REAL_ARTICLES, count=2)
        block = plans_to_prompt_block(plans, REAL_ARTICLES)
        assert "CORE-1" in block

    def test_output_contains_article_titles(self):
        plans = build_article_plans(REAL_ARTICLES, count=1)
        block = plans_to_prompt_block(plans, REAL_ARTICLES)
        assert "Export Strategy" in block

    def test_output_contains_mandatory_header(self):
        plans = build_article_plans(REAL_ARTICLES, count=1)
        block = plans_to_prompt_block(plans, REAL_ARTICLES)
        assert "MANDATORY" in block

    def test_output_contains_primary_label(self):
        plans = build_article_plans(REAL_ARTICLES, count=1)
        block = plans_to_prompt_block(plans, REAL_ARTICLES)
        assert "Primary" in block

    def test_output_contains_supporting_label(self):
        plans = build_article_plans(REAL_ARTICLES, count=1)
        block = plans_to_prompt_block(plans, REAL_ARTICLES)
        assert "Supporting" in block

    def test_works_without_core_articles(self):
        plans = build_article_plans(REAL_ARTICLES, count=2)
        block = plans_to_prompt_block(plans)   # no core_articles
        assert "SLOT 1" in block
        assert "SLOT 2" in block

    def test_returns_string(self):
        plans = build_article_plans(REAL_ARTICLES, count=2)
        block = plans_to_prompt_block(plans, REAL_ARTICLES)
        assert isinstance(block, str)

    def test_frame_hint_injected_when_provided(self):
        plans = build_article_plans(REAL_ARTICLES, count=1)
        block = plans_to_prompt_block(plans, REAL_ARTICLES, frame_hint="timeline")
        assert "Narrative shape: timeline" in block

    def test_frame_hint_absent_when_none(self):
        plans = build_article_plans(REAL_ARTICLES, count=1)
        block = plans_to_prompt_block(plans, REAL_ARTICLES)
        assert "Narrative shape" not in block


# ── _generate_why_used ────────────────────────────────────────────────────────

class TestGenerateWhyUsed:
    def _src(self, rank_reason="authority", source_type="news",
             domain="reuters.com", retrieval_query="export barriers") -> dict:
        return {
            "_rank_reason":    rank_reason,
            "source_type":     source_type,
            "domain":          domain,
            "retrieval_query": retrieval_query,
        }

    def test_returns_string(self):
        result = _generate_why_used(self._src(), "export strategy")
        assert isinstance(result, str)

    def test_max_25_words(self):
        result = _generate_why_used(self._src(), "a very long topic hint " * 5)
        assert len(result.split()) <= 25

    def test_references_topic_hint(self):
        result = _generate_why_used(self._src(), "export barriers")
        assert "export" in result.lower() or "barriers" in result.lower()

    def test_authority_rank_reason(self):
        result = _generate_why_used(self._src(rank_reason="authority"), "trade policy")
        assert "authority" in result.lower() or "high-authority" in result.lower()

    def test_freshness_rank_reason(self):
        result = _generate_why_used(self._src(rank_reason="freshness"), "trade policy")
        assert "recent" in result.lower()

    def test_intent_match_rank_reason(self):
        result = _generate_why_used(self._src(rank_reason="intent_match"), "trade policy")
        assert "matched" in result.lower()

    def test_novelty_rank_reason(self):
        result = _generate_why_used(self._src(rank_reason="novelty"), "trade policy")
        assert "unique" in result.lower() or "perspective" in result.lower()

    def test_news_source_type_label(self):
        result = _generate_why_used(self._src(source_type="news"), "topic")
        assert "reporting" in result.lower()

    def test_government_source_type_label(self):
        result = _generate_why_used(self._src(source_type="government"), "topic")
        assert "official" in result.lower()

    def test_research_paper_source_type_label(self):
        result = _generate_why_used(self._src(source_type="research_paper"), "topic")
        assert "research" in result.lower()

    def test_unknown_rank_reason_does_not_crash(self):
        src = self._src(rank_reason="unknown_future_dimension")
        result = _generate_why_used(src, "topic")
        assert isinstance(result, str) and len(result) > 0

    def test_unknown_source_type_does_not_crash(self):
        src = self._src(source_type="podcast")
        result = _generate_why_used(src, "topic")
        assert isinstance(result, str) and len(result) > 0

    def test_empty_topic_falls_back_to_retrieval_query(self):
        src = self._src(retrieval_query="trade barriers")
        result = _generate_why_used(src, "")
        assert "trade" in result.lower() or "barriers" in result.lower()

    def test_deterministic(self):
        src = self._src()
        assert _generate_why_used(src, "export") == _generate_why_used(src, "export")

    def test_not_generic_useful_source(self):
        result = _generate_why_used(self._src(), "export barriers")
        assert result.lower() not in {"useful source.", "relevant information.", "good article."}

    def test_domain_included_in_output(self):
        result = _generate_why_used(self._src(domain="wto.org"), "trade policy")
        assert "wto.org" in result


# ── why_used in build_article_plans ──────────────────────────────────────────

class TestWhyUsedInPlans:
    def test_all_sources_have_why_used(self):
        plans = build_article_plans(REAL_ARTICLES, count=3)
        for plan in plans:
            for src in plan.assigned_sources:
                assert "why_used" in src, f"why_used missing from source in {plan.slot_id}"

    def test_why_used_is_non_empty_string(self):
        plans = build_article_plans(REAL_ARTICLES, count=2)
        for plan in plans:
            for src in plan.assigned_sources:
                assert isinstance(src["why_used"], str)
                assert len(src["why_used"]) > 0

    def test_original_articles_not_mutated(self):
        originals = [dict(a) for a in REAL_ARTICLES]
        build_article_plans(REAL_ARTICLES, count=3)
        for orig, after in zip(originals, REAL_ARTICLES):
            assert "why_used" not in after, "build_article_plans must not mutate input articles"

    def test_why_used_respects_25_word_limit(self):
        plans = build_article_plans(REAL_ARTICLES, count=4)
        for plan in plans:
            for src in plan.assigned_sources:
                assert len(src["why_used"].split()) <= 25
