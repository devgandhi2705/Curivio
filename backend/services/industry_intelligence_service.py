"""
Industry intelligence workflow for the AI research companion.

Generates structured, decision-ready intelligence briefs for five target
industries: Finance, Pharma, Manufacturing, Exports, and AI Business Ecosystem.

Each brief contains:
  - trend_summary          — the single most important structural shift
  - market_developments    — 3 named developments with business impact
  - emerging_opportunities — 3 specific opportunities with time horizons
  - key_signals            — 3 observable signals
  - action_items           — 3 concrete actions

Workflow (per industry)
-----------------------
1. Classify industry → fetch its config (queries, focus areas, business lens).
2. Check feed_cache — return immediately on hit (TTL: INDUSTRY_BRIEF_TTL_HOURS).
3. Run 3 domain-specific Tavily queries; URL-deduplicate results.
4. Rank + trim to top 8 articles.
5. Call Groq with the INDUSTRY_INTELLIGENCE_PROMPT.
6. Parse JSON → validate required keys → cache → return.

Public API
----------
analyze_industry(industry_key)      -> dict
list_supported_industries()         -> list[str]
get_industry_config(industry_key)   -> dict | None
detect_industry_from_text(text)     -> str | None
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

INDUSTRY_BRIEF_TTL_HOURS: int = int(os.getenv("INDUSTRY_BRIEF_TTL_HOURS", "12"))

# ── Industry configuration ────────────────────────────────────────────────────

@dataclass
class _IndustryConfig:
    display_name:  str
    search_queries: list[str]
    focus_areas:   list[str]
    business_lens: str
    # Keywords used by detect_industry_from_text()
    detection_keywords: list[str] = field(default_factory=list)


_INDUSTRY_CONFIG: dict[str, _IndustryConfig] = {
    "finance": _IndustryConfig(
        display_name="Finance & Capital Markets",
        search_queries=[
            "finance banking capital markets trends outlook 2025",
            "fintech AI investment regulatory environment 2025",
            "quantitative macro hedge fund market intelligence 2025",
        ],
        focus_areas=[
            "market dynamics",
            "regulatory landscape",
            "fintech innovation",
            "investment themes",
        ],
        business_lens="for CFOs, investors, and fintech builders",
        detection_keywords=[
            "finance", "financial", "market", "banking", "investment",
            "fintech", "stock", "trading", "hedge", "fund", "macro",
            "quantitative", "capital markets", "credit",
        ],
    ),
    "pharma": _IndustryConfig(
        display_name="Pharmaceutical & Biotech",
        search_queries=[
            "pharmaceutical biotech drug approval pipeline 2025",
            "clinical trial results oncology rare disease breakthrough 2025",
            "pharma AI drug discovery regulatory FDA EMA outlook",
        ],
        focus_areas=[
            "pipeline developments",
            "regulatory approvals",
            "AI in drug discovery",
            "market consolidation",
        ],
        business_lens="for pharma executives, biotech investors, and clinical leaders",
        detection_keywords=[
            "pharma", "pharmaceutical", "biotech", "drug", "clinical",
            "trial", "fda", "ema", "oncology", "therapeutics", "biologics",
            "pipeline", "approval", "medicine",
        ],
    ),
    "manufacturing": _IndustryConfig(
        display_name="Manufacturing & Industry 4.0",
        search_queries=[
            "manufacturing industry 4.0 automation smart factory trends 2025",
            "supply chain resilience nearshoring production costs outlook 2025",
            "industrial IoT robotics predictive maintenance investment 2025",
        ],
        focus_areas=[
            "automation adoption",
            "supply chain shifts",
            "cost optimisation",
            "technology integration",
        ],
        business_lens="for plant managers, operations executives, and industrial investors",
        detection_keywords=[
            "manufacturing", "factory", "production", "automation", "robotics",
            "supply chain", "lean", "industry 4.0", "iot", "industrial",
            "logistics", "procurement", "assembly",
        ],
    ),
    "exports": _IndustryConfig(
        display_name="Export Trade & Global Commerce",
        search_queries=[
            "export trade tariff WTO policy outlook 2025",
            "global supply chain logistics freight costs shipping 2025",
            "international trade agreement emerging market export opportunity",
        ],
        focus_areas=[
            "trade policy changes",
            "logistics & freight costs",
            "emerging market opportunities",
            "compliance & customs shifts",
        ],
        business_lens="for export managers, trade finance professionals, and logistics operators",
        detection_keywords=[
            "export", "trade", "tariff", "customs", "logistics", "freight",
            "shipping", "wto", "incoterms", "import", "cross-border",
            "fob", "cif", "emerging market", "dgft",
        ],
    ),
    "ai_business": _IndustryConfig(
        display_name="AI Business Ecosystem",
        search_queries=[
            "AI enterprise adoption ROI productivity impact 2025",
            "generative AI market competition investment startup funding 2025",
            "AI regulation governance policy enterprise risk compliance 2025",
        ],
        focus_areas=[
            "enterprise AI adoption",
            "competitive dynamics & consolidation",
            "regulatory environment",
            "investment flows & valuations",
        ],
        business_lens="for product leaders, AI strategists, and venture investors",
        detection_keywords=[
            "ai business", "enterprise ai", "generative ai", "llm market",
            "ai startup", "ai adoption", "ai regulation", "ai governance",
            "ai investment", "ai ecosystem", "openai", "anthropic",
            "ai strategy", "ai roi",
        ],
    ),
}

# Required keys in the LLM JSON response
_REQUIRED_KEYS = {
    "industry", "trend_summary", "market_developments",
    "emerging_opportunities", "key_signals", "action_items",
}

# ── Public API ────────────────────────────────────────────────────────────────

def list_supported_industries() -> list[str]:
    """Return the list of supported industry keys."""
    return list(_INDUSTRY_CONFIG.keys())


def get_industry_config(industry_key: str) -> dict | None:
    """
    Return a serialisable config dict for the given industry key, or None.

    Shape: {display_name, focus_areas, business_lens, detection_keywords}
    """
    cfg = _INDUSTRY_CONFIG.get(industry_key.lower())
    if cfg is None:
        return None
    return {
        "display_name":       cfg.display_name,
        "focus_areas":        cfg.focus_areas,
        "business_lens":      cfg.business_lens,
        "detection_keywords": cfg.detection_keywords,
    }


def detect_industry_from_text(text: str) -> str | None:
    """
    Return the best-matching industry key for a query or topic string.

    Scores each industry by keyword overlap; returns None when nothing
    matches (score = 0 for all industries).
    """
    lower  = text.lower()
    scores: dict[str, int] = {}
    for key, cfg in _INDUSTRY_CONFIG.items():
        score = sum(1 for kw in cfg.detection_keywords if kw in lower)
        if score > 0:
            scores[key] = score
    if not scores:
        return None
    return max(scores, key=lambda k: scores[k])


def analyze_industry(industry_key: str) -> dict:
    """
    Return a structured intelligence brief for *industry_key*.

    Returns a cached brief if one exists and has not expired.
    Raises ValueError for unsupported industry keys.

    Return shape
    ------------
    {
      "industry":               str,        # display name
      "industry_key":           str,        # internal key
      "generated_at":           str,        # ISO-8601
      "cached":                 bool,
      "trend_summary":          str,
      "market_developments":    list[dict], # {title, insight, business_impact, sources}
      "emerging_opportunities": list[dict], # {opportunity, rationale, time_horizon}
      "key_signals":            list[str],
      "action_items":           list[str],
    }
    """
    key = industry_key.lower()
    cfg = _INDUSTRY_CONFIG.get(key)
    if cfg is None:
        raise ValueError(
            f"Unsupported industry key {industry_key!r}. "
            f"Supported: {list(_INDUSTRY_CONFIG.keys())}"
        )

    cache_key = _build_cache_key(key)

    from .feed_cache_service import get_cached_feed
    cached = get_cached_feed(cache_key)
    if cached is not None:
        cached["cached"] = True
        return cached

    logger.info("[industry_intelligence] generating brief for %r", key)

    articles  = _fetch_articles(cfg, industry_key=key)
    brief     = _generate_brief(cfg, articles)
    brief["industry_key"] = key
    brief["generated_at"] = datetime.now(timezone.utc).isoformat()
    brief["cached"]       = False

    _cache_brief(cache_key, key, brief)

    return brief


# ── Internals ─────────────────────────────────────────────────────────────────

def _build_cache_key(industry_key: str) -> str:
    """
    Daily cache key: expires at midnight so each day gets a fresh brief.
    Using feed_cache_service.build_cache_key for consistency.
    """
    from .feed_cache_service import build_cache_key
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return build_cache_key(f"industry:{industry_key}", today)


_INDUSTRY_DOMAIN_MAP: dict[str, str] = {
    "finance":      "finance",
    "pharma":       "pharma",
    "manufacturing": "manufacturing",
    "exports":      "export_trade",
    "ai_business":  "ai",
}


def _fetch_articles(cfg: _IndustryConfig, industry_key: str, top_n: int = 8) -> list[dict]:
    """
    Retrieve and rank articles for an industry brief via the retrieval router.

    Passes the pre-built domain-specific queries as overrides so the router
    uses Tavily operations optimised for this industry's domain config rather
    than re-expanding from templates.
    """
    from .retrieval_router import route
    from .source_ranker    import rank_articles

    raw = route(
        cfg.display_name,
        mode             = "feed",
        override_queries = cfg.search_queries,
    )

    if not raw:
        raise ValueError(
            f"No articles retrieved for industry {cfg.display_name!r}. "
            "Check Tavily API key and network connectivity."
        )

    domain = _INDUSTRY_DOMAIN_MAP.get(industry_key, "default")
    return rank_articles(raw, query=cfg.display_name, top_n=top_n,
                         domain=domain, mode="feed")


def _format_articles(articles: list[dict]) -> str:
    if not articles:
        return "(no articles retrieved)"
    lines = []
    for i, a in enumerate(articles, start=1):
        lines.append(
            f"{i}. {a.get('title', 'Untitled')}\n"
            f"   URL: {a.get('url', '')}\n"
            f"   {a.get('content', '')[:400]}"
        )
    return "\n\n".join(lines)


def _generate_brief(cfg: _IndustryConfig, articles: list[dict]) -> dict:
    """Call Groq with the industry intelligence prompt and parse JSON."""
    from .grok_service import ask_grok
    from ..prompts.industry_intelligence_prompt import INDUSTRY_INTELLIGENCE_PROMPT

    prompt = INDUSTRY_INTELLIGENCE_PROMPT.format(
        industry_display_name = cfg.display_name,
        business_lens         = cfg.business_lens,
        focus_areas           = ", ".join(cfg.focus_areas),
        article_count         = len(articles),
        articles              = _format_articles(articles),
    )

    raw    = ask_grok(prompt)
    result = _parse_json_response(raw)
    _validate_brief(result)
    return result


def _validate_brief(brief: dict) -> None:
    """Raise ValueError if required keys are missing from the LLM response."""
    missing = _REQUIRED_KEYS - set(brief.keys())
    if missing:
        raise ValueError(
            f"Industry brief missing required keys: {missing}. "
            f"Got: {list(brief.keys())}"
        )

    for field_name, expected_len in (
        ("market_developments",    3),
        ("emerging_opportunities", 3),
        ("key_signals",            3),
        ("action_items",           3),
    ):
        items = brief.get(field_name, [])
        if not isinstance(items, list) or len(items) < 1:
            raise ValueError(
                f"Field {field_name!r} must be a non-empty list; got {items!r}"
            )


def _cache_brief(cache_key: str, industry_key: str, brief: dict) -> None:
    """Write the brief to feed_cache using INDUSTRY_BRIEF_TTL_HOURS."""
    try:
        from .feed_cache_service import cache_feed
        cache_feed(cache_key, f"industry:{industry_key}", brief)
    except Exception:
        logger.warning(
            "[industry_intelligence] cache write failed for %r (non-fatal)", industry_key
        )


def _parse_json_response(raw: str) -> dict:
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    raise ValueError(
        f"LLM response could not be parsed as JSON. "
        f"First 300 chars: {cleaned[:300]}"
    )
