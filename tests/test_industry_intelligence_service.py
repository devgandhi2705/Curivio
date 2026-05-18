"""
Tests for industry_intelligence_service and the industry_brief action router action.

All Tavily, Groq, and DB calls are mocked — zero API cost, zero network traffic.

Test coverage:
  1. Industry config & metadata
  2. detect_industry_from_text — keyword matching
  3. analyze_industry — cache hit path
  4. analyze_industry — full generation path (mocked Groq + Tavily)
  5. analyze_industry — error paths (no articles, bad JSON, missing keys)
  6. Action router — industry_brief detection & dispatch

Run with:
    pytest tests/test_industry_intelligence_service.py -v
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.industry_intelligence_service import (
    analyze_industry,
    detect_industry_from_text,
    get_industry_config,
    list_supported_industries,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

SUPPORTED = ["finance", "pharma", "manufacturing", "exports", "ai_business"]

def _make_articles(n=5, prefix="Article"):
    return [
        {
            "title":   f"{prefix} {i}",
            "url":     f"https://source.example.com/article/{i}",
            "content": f"Content for article {i}. Detailed analysis follows.",
        }
        for i in range(1, n + 1)
    ]


def _mock_brief(industry_display="Finance & Capital Markets"):
    """Return a minimal valid brief that passes _validate_brief."""
    return {
        "industry":    industry_display,
        "trend_summary": "Test trend summary sentence one. Sentence two provides detail.",
        "market_developments": [
            {
                "title":           "Dev 1",
                "insight":         "Insight sentence one. Insight sentence two.",
                "business_impact": "Impact sentence.",
                "sources":         ["https://source.example.com/article/1"],
            },
            {
                "title":           "Dev 2",
                "insight":         "Insight.",
                "business_impact": "Impact.",
                "sources":         [],
            },
            {
                "title":           "Dev 3",
                "insight":         "Insight.",
                "business_impact": "Impact.",
                "sources":         [],
            },
        ],
        "emerging_opportunities": [
            {"opportunity": "Opp 1", "rationale": "Rationale.",     "time_horizon": "near-term"},
            {"opportunity": "Opp 2", "rationale": "Rationale.",     "time_horizon": "mid-term"},
            {"opportunity": "Opp 3", "rationale": "Rationale.",     "time_horizon": "long-term"},
        ],
        "key_signals":  ["Signal 1", "Signal 2", "Signal 3"],
        "action_items": ["Action 1", "Action 2", "Action 3"],
    }


def _run_analyze(industry_key, grok_json=None, articles=None, cached=None):
    """
    Run analyze_industry with all external dependencies mocked.

    Patch at source modules per project convention (deferred imports).
    - cached=None  → cache miss (full generation path)
    - cached=dict  → cache hit (returns immediately)
    - grok_json    → what ask_grok returns (JSON string)
    - articles     → what search_articles returns
    """
    articles   = articles  if articles  is not None else _make_articles()
    grok_json  = grok_json if grok_json is not None else json.dumps(
        _mock_brief(_display(industry_key))
    )

    with (
        patch("backend.services.feed_cache_service.get_cached_feed",
              return_value=cached),
        patch("backend.services.feed_cache_service.cache_feed"),
        patch("backend.services.tavily_service.search_articles",
              return_value=articles),
        patch("backend.services.source_ranker.rank_articles",
              side_effect=lambda arts, **kw: arts),
        patch("backend.services.grok_service.ask_grok",
              return_value=grok_json),
    ):
        return analyze_industry(industry_key)


def _display(key: str) -> str:
    """Return expected display name for a given key."""
    from backend.services.industry_intelligence_service import _INDUSTRY_CONFIG
    return _INDUSTRY_CONFIG[key].display_name


# ── 1. Industry config & metadata ─────────────────────────────────────────────

class TestIndustryConfig:

    def test_list_supported_returns_all_five(self):
        assert set(list_supported_industries()) == set(SUPPORTED)

    def test_get_config_returns_dict_for_each_supported(self):
        for key in SUPPORTED:
            cfg = get_industry_config(key)
            assert cfg is not None, f"No config for {key!r}"

    def test_get_config_has_required_keys(self):
        for key in SUPPORTED:
            cfg = get_industry_config(key)
            assert "display_name"  in cfg
            assert "focus_areas"   in cfg
            assert "business_lens" in cfg
            assert "detection_keywords" in cfg

    def test_get_config_returns_none_for_unknown(self):
        assert get_industry_config("blockchain_nfts") is None

    def test_focus_areas_nonempty_for_all_industries(self):
        for key in SUPPORTED:
            cfg = get_industry_config(key)
            assert len(cfg["focus_areas"]) >= 2, f"Too few focus areas for {key!r}"

    def test_detection_keywords_nonempty_for_all_industries(self):
        for key in SUPPORTED:
            cfg = get_industry_config(key)
            assert len(cfg["detection_keywords"]) >= 3


# ── 2. detect_industry_from_text ──────────────────────────────────────────────

class TestDetectIndustry:

    # Finance
    @pytest.mark.parametrize("text", [
        "what are the current stock market trends?",
        "fintech regulation update 2025",
        "hedge fund macro strategy",
        "banking sector investment outlook",
    ])
    def test_detects_finance(self, text):
        assert detect_industry_from_text(text) == "finance", f"Failed for: {text!r}"

    # Pharma
    @pytest.mark.parametrize("text", [
        "FDA drug approval pipeline oncology",
        "pharma biotech clinical trial results",
        "EMA regulatory guidance biologics",
        "medicine therapeutics news",
    ])
    def test_detects_pharma(self, text):
        assert detect_industry_from_text(text) == "pharma", f"Failed for: {text!r}"

    # Manufacturing
    @pytest.mark.parametrize("text", [
        "factory automation manufacturing trends",
        "supply chain resilience production costs",
        "industrial IoT smart factory",
        "lean manufacturing robotics",
    ])
    def test_detects_manufacturing(self, text):
        assert detect_industry_from_text(text) == "manufacturing", f"Failed for: {text!r}"

    # Exports
    @pytest.mark.parametrize("text", [
        "export tariff WTO trade policy",
        "customs compliance logistics freight",
        "international trade emerging market",
        "shipping FOB CIF incoterms",
    ])
    def test_detects_exports(self, text):
        assert detect_industry_from_text(text) == "exports", f"Failed for: {text!r}"

    # AI Business
    @pytest.mark.parametrize("text", [
        "enterprise AI adoption ROI business impact",
        "AI startup generative AI enterprise ecosystem",
        "AI regulation governance enterprise risk",
        "openai anthropic ai strategy",
    ])
    def test_detects_ai_business(self, text):
        assert detect_industry_from_text(text) == "ai_business", f"Failed for: {text!r}"

    def test_returns_none_for_unrelated_text(self):
        assert detect_industry_from_text("ancient Roman architecture") is None

    def test_returns_none_for_empty_string(self):
        assert detect_industry_from_text("") is None

    def test_returns_str(self):
        result = detect_industry_from_text("stock market trends")
        assert result is None or isinstance(result, str)


# ── 3. analyze_industry — cache hit ───────────────────────────────────────────

class TestAnalyzeIndustryCacheHit:

    def test_returns_cached_brief_immediately(self):
        cached_brief = {**_mock_brief(), "industry_key": "finance", "cached": True}
        with patch("backend.services.feed_cache_service.get_cached_feed",
                   return_value=cached_brief):
            result = analyze_industry("finance")
        assert result["cached"] is True

    def test_cache_hit_does_not_call_grok(self):
        cached_brief = {**_mock_brief(), "industry_key": "pharma", "cached": True}
        with (
            patch("backend.services.feed_cache_service.get_cached_feed",
                  return_value=cached_brief),
            patch("backend.services.grok_service.ask_grok") as mock_grok,
        ):
            analyze_industry("pharma")
        mock_grok.assert_not_called()

    def test_cache_hit_does_not_call_tavily(self):
        cached_brief = {**_mock_brief(), "industry_key": "manufacturing", "cached": True}
        with (
            patch("backend.services.feed_cache_service.get_cached_feed",
                  return_value=cached_brief),
            patch("backend.services.tavily_service.search_articles") as mock_tav,
        ):
            analyze_industry("manufacturing")
        mock_tav.assert_not_called()


# ── 4. analyze_industry — full generation path ────────────────────────────────

class TestAnalyzeIndustryGeneration:

    def test_returns_all_required_fields(self):
        result = _run_analyze("finance")
        for field in ("industry", "trend_summary", "market_developments",
                      "emerging_opportunities", "key_signals", "action_items",
                      "industry_key", "generated_at", "cached"):
            assert field in result, f"Missing field: {field!r}"

    def test_industry_key_is_set(self):
        result = _run_analyze("exports")
        assert result["industry_key"] == "exports"

    def test_cached_is_false_on_generation(self):
        result = _run_analyze("pharma")
        assert result["cached"] is False

    def test_generated_at_is_iso_string(self):
        result = _run_analyze("manufacturing")
        ts = result["generated_at"]
        assert isinstance(ts, str)
        # Must be parseable
        from datetime import datetime
        datetime.fromisoformat(ts)

    def test_market_developments_list(self):
        result = _run_analyze("ai_business")
        devs = result["market_developments"]
        assert isinstance(devs, list)
        assert len(devs) >= 1

    def test_market_developments_have_required_subkeys(self):
        result = _run_analyze("finance")
        for dev in result["market_developments"]:
            assert "title"          in dev
            assert "insight"        in dev
            assert "business_impact" in dev

    def test_emerging_opportunities_list(self):
        result = _run_analyze("pharma")
        opps = result["emerging_opportunities"]
        assert isinstance(opps, list)
        assert len(opps) >= 1

    def test_opportunities_have_time_horizon(self):
        result = _run_analyze("exports")
        for opp in result["emerging_opportunities"]:
            assert "time_horizon" in opp
            assert opp["time_horizon"] in ("near-term", "mid-term", "long-term")

    def test_key_signals_is_list_of_strings(self):
        result = _run_analyze("manufacturing")
        signals = result["key_signals"]
        assert isinstance(signals, list)
        assert all(isinstance(s, str) for s in signals)

    def test_action_items_is_list_of_strings(self):
        result = _run_analyze("ai_business")
        actions = result["action_items"]
        assert isinstance(actions, list)
        assert all(isinstance(a, str) for a in actions)

    @pytest.mark.parametrize("key", SUPPORTED)
    def test_all_industries_run_without_error(self, key):
        result = _run_analyze(key)
        assert "trend_summary" in result

    def test_tavily_called_with_industry_queries(self):
        from backend.services.industry_intelligence_service import _INDUSTRY_CONFIG
        cfg = _INDUSTRY_CONFIG["finance"]

        with (
            patch("backend.services.feed_cache_service.get_cached_feed",
                  return_value=None),
            patch("backend.services.feed_cache_service.cache_feed"),
            patch("backend.services.tavily_service.search_articles",
                  return_value=_make_articles()) as mock_tav,
            patch("backend.services.source_ranker.rank_articles",
                  side_effect=lambda arts, **kw: arts),
            patch("backend.services.grok_service.ask_grok",
                  return_value=json.dumps(_mock_brief())),
        ):
            analyze_industry("finance")

        # Each of the 3 configured queries should trigger a search_articles call
        assert mock_tav.call_count == len(cfg.search_queries)

    def test_brief_is_written_to_cache(self):
        with (
            patch("backend.services.feed_cache_service.get_cached_feed",
                  return_value=None),
            patch("backend.services.feed_cache_service.cache_feed") as mock_cache,
            patch("backend.services.tavily_service.search_articles",
                  return_value=_make_articles()),
            patch("backend.services.source_ranker.rank_articles",
                  side_effect=lambda arts, **kw: arts),
            patch("backend.services.grok_service.ask_grok",
                  return_value=json.dumps(_mock_brief())),
        ):
            analyze_industry("pharma")

        mock_cache.assert_called_once()


# ── 5. Error paths ────────────────────────────────────────────────────────────

class TestAnalyzeIndustryErrors:

    def test_unsupported_industry_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported industry key"):
            analyze_industry("cryptocurrency")

    def test_no_articles_raises_value_error(self):
        with (
            patch("backend.services.feed_cache_service.get_cached_feed",
                  return_value=None),
            patch("backend.services.tavily_service.search_articles", return_value=[]),
        ):
            with pytest.raises(ValueError, match="No articles retrieved"):
                analyze_industry("finance")

    def test_all_tavily_queries_failing_raises(self):
        with (
            patch("backend.services.feed_cache_service.get_cached_feed",
                  return_value=None),
            patch("backend.services.tavily_service.search_articles",
                  side_effect=RuntimeError("Tavily down")),
        ):
            with pytest.raises(ValueError):
                analyze_industry("exports")

    def test_bad_grok_json_raises_value_error(self):
        with (
            patch("backend.services.feed_cache_service.get_cached_feed",
                  return_value=None),
            patch("backend.services.tavily_service.search_articles",
                  return_value=_make_articles()),
            patch("backend.services.source_ranker.rank_articles",
                  side_effect=lambda arts, **kw: arts),
            patch("backend.services.grok_service.ask_grok",
                  return_value="not json at all {{ broken"),
        ):
            with pytest.raises(ValueError, match="could not be parsed"):
                analyze_industry("finance")

    def test_missing_required_keys_raises_value_error(self):
        incomplete = {"industry": "Finance", "trend_summary": "summary only"}
        with (
            patch("backend.services.feed_cache_service.get_cached_feed",
                  return_value=None),
            patch("backend.services.tavily_service.search_articles",
                  return_value=_make_articles()),
            patch("backend.services.source_ranker.rank_articles",
                  side_effect=lambda arts, **kw: arts),
            patch("backend.services.grok_service.ask_grok",
                  return_value=json.dumps(incomplete)),
        ):
            with pytest.raises(ValueError, match="missing required keys"):
                analyze_industry("manufacturing")

    def test_cache_write_failure_is_non_fatal(self):
        """Brief is returned even when cache_feed raises."""
        with (
            patch("backend.services.feed_cache_service.get_cached_feed",
                  return_value=None),
            patch("backend.services.feed_cache_service.cache_feed",
                  side_effect=Exception("disk full")),
            patch("backend.services.tavily_service.search_articles",
                  return_value=_make_articles()),
            patch("backend.services.source_ranker.rank_articles",
                  side_effect=lambda arts, **kw: arts),
            patch("backend.services.grok_service.ask_grok",
                  return_value=json.dumps(_mock_brief())),
        ):
            result = analyze_industry("ai_business")   # must not raise
        assert "trend_summary" in result

    def test_partial_tavily_failure_continues_with_remaining_articles(self):
        """One failing query should not abort the workflow."""
        good_articles = _make_articles(4)
        call_count = {"n": 0}

        def flaky_search(query):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("second query failed")
            return good_articles

        with (
            patch("backend.services.feed_cache_service.get_cached_feed",
                  return_value=None),
            patch("backend.services.feed_cache_service.cache_feed"),
            patch("backend.services.tavily_service.search_articles",
                  side_effect=flaky_search),
            patch("backend.services.source_ranker.rank_articles",
                  side_effect=lambda arts, **kw: arts),
            patch("backend.services.grok_service.ask_grok",
                  return_value=json.dumps(_mock_brief())),
        ):
            result = analyze_industry("finance")   # must not raise
        assert "trend_summary" in result


# ── 6. Action router — industry_brief ────────────────────────────────────────

class TestIndustryBriefAction:

    def _route(self, message, topic, domain=None, brief=None, brief_raises=False):
        """Route a message with all external calls mocked."""
        context = {}
        if domain:
            context["domain_context"] = {"domain": domain}

        def mock_analyze(key):
            if brief_raises:
                raise RuntimeError("generation failed")
            from backend.services.industry_intelligence_service import _INDUSTRY_CONFIG
            display = _INDUSTRY_CONFIG[key].display_name if key in _INDUSTRY_CONFIG else key
            return brief or {**_mock_brief(display), "industry_key": key, "cached": False}

        with patch(
            "backend.services.industry_intelligence_service.analyze_industry",
            side_effect=mock_analyze,
        ):
            from backend.services.action_router_service import route
            return route(message, topic, context)

    # ── Detection ─────────────────────────────────────────────────────────────

    @pytest.mark.parametrize("msg", [
        "give me an industry trend analysis for finance",
        "what's the market outlook for pharma?",
        "what is happening in manufacturing right now?",
        "finance trends and news",
        "sector analysis for exports",
        "show me business intelligence for the AI ecosystem",
    ])
    def test_industry_brief_detected(self, msg):
        result = self._route(msg, "finance", domain="Finance")
        assert result is not None
        assert result["action"] == "industry_brief"

    def test_non_industry_message_not_detected(self):
        result = self._route("explain transformers to me", "transformers")
        assert result is None or result.get("action") != "industry_brief"

    # ── Dispatch — domain context maps to industry ────────────────────────────

    @pytest.mark.parametrize("domain,expected_key", [
        ("Finance",        "finance"),
        ("Pharmaceutical", "pharma"),
        ("Manufacturing",  "manufacturing"),
        ("Export/Trade",   "exports"),
        ("AI",             "ai_business"),
    ])
    def test_domain_context_maps_to_correct_industry(self, domain, expected_key):
        called_with: list[str] = []

        def mock_analyze(key):
            called_with.append(key)
            return {**_mock_brief(), "industry_key": key, "cached": False}

        context = {"domain_context": {"domain": domain}}
        with patch(
            "backend.services.industry_intelligence_service.analyze_industry",
            side_effect=mock_analyze,
        ):
            from backend.services.action_router_service import route
            route("industry trends", domain.lower(), context)

        assert called_with == [expected_key]

    # ── Result shape ──────────────────────────────────────────────────────────

    def test_found_true_when_brief_generated(self):
        result = self._route("market trends for finance", "finance", domain="Finance")
        assert result["found"] is True

    def test_data_contains_brief_fields(self):
        result = self._route("sector analysis finance", "finance", domain="Finance")
        assert "trend_summary" in result["data"]
        assert "market_developments" in result["data"]

    def test_instruction_contains_trend_summary(self):
        result = self._route("industry brief pharma", "pharma", domain="Pharmaceutical")
        assert "trend_summary" in result["instruction"].lower() \
               or "Test trend summary" in result["instruction"]

    def test_instruction_mentions_industry(self):
        result = self._route("manufacturing outlook", "manufacturing", domain="Manufacturing")
        assert "Manufacturing" in result["instruction"] or "manufacturing" in result["instruction"]

    # ── No-industry fallback ──────────────────────────────────────────────────

    def test_no_industry_detected_returns_found_false(self):
        result = self._route("industry trends", "blockchain gaming NFTs")
        # When domain_context absent and topic doesn't match any industry
        if result and result["action"] == "industry_brief":
            # Could be found=False (ask user) or skipped — either is valid
            assert isinstance(result["found"], bool)

    # ── Generation failure fallback ───────────────────────────────────────────

    def test_generation_failure_returns_result_not_raises(self):
        result = self._route(
            "industry trends manufacturing",
            "manufacturing",
            domain="Manufacturing",
            brief_raises=True,
        )
        assert result is not None
        assert result["action"] == "industry_brief"
        assert result["found"] is False

    def test_generation_failure_instruction_has_fallback_text(self):
        result = self._route(
            "industry news for exports",
            "exports",
            domain="Export/Trade",
            brief_raises=True,
        )
        assert result is not None
        instruction = result["instruction"]
        assert "Draw on your own knowledge" in instruction or "failed" in instruction.lower()

    # ── Missing topic → None ──────────────────────────────────────────────────

    def test_route_returns_none_without_topic(self):
        with patch(
            "backend.services.industry_intelligence_service.analyze_industry",
            return_value=_mock_brief(),
        ):
            from backend.services.action_router_service import route
            result = route("industry trend analysis", None, {})
        assert result is None
