"""
Reasoning-Augmented Web Search.

Transforms web search from "find sources supporting the answer" into
"find evidence that challenges, complicates, and updates the answer."

Two-query approach:
  primary query      — surfaces mainstream understanding (what the user asked)
  contradiction query — specifically seeks challenges, recent shifts, counterexamples

Results are annotated by search angle so the prompt formatter can render
a "supporting evidence" block alongside a "complicating evidence" block,
forcing the LLM to explicitly reason through the tension.

Public API
----------
build_search_queries(message, intent_profile, domain) -> dict
fetch_reasoned_results(message, intent_profile, domain) -> dict
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_PRIMARY_MAX      = 3   # max articles from primary query
_CONTRADICTION_MAX = 3   # max NEW articles from contradiction query (deduped vs primary)


# ── Intent → contradiction angle templates ────────────────────────────────────
# Per-intent suffixes that bias Tavily toward challenge/critical content.

_INTENT_CONTRADICTION_SUFFIXES: dict[str, str] = {
    "causal":      "evidence against mechanism counterexample alternative explanation",
    "comparison":  "limitations weaknesses failure modes where it breaks",
    "historical":  "reversal setback recent shift 2024 2025",
    "strategic":   "hidden risk vulnerability strategic weakness disruption",
    "research":    "contradicting evidence criticism controversy competing viewpoint",
    "prediction":  "risks uncertainty headwinds scenarios where this fails",
    "critique":    "counterargument strongest case evidence against",
    "synthesis":   "tension contradiction unresolved competing framework",
    "explanation": "common misconception misleading oversimplification nuance",
}

_DEFAULT_CONTRADICTION_SUFFIX = "criticism problems challenges limitations recent issues"

# ── Domain-boosted contradiction hints ───────────────────────────────────────
# Override the generic suffix with domain-specific challenge language.

_DOMAIN_CONTRADICTION_HINTS: dict[str, dict[str, str]] = {
    "pharmaceutical": {
        "causal":    "FDA warning letter quality failure compliance problem",
        "strategic": "Chinese API dependency supply chain risk vulnerability",
        "default":   "FDA warning recall quality issue problem",
    },
    "ai": {
        "causal":    "benchmark failure hallucination limitation criticism",
        "strategic": "risk deployment failure misuse safety problem",
        "default":   "hallucination failure limitation criticism risk",
    },
    "finance": {
        "causal":    "crisis failure systemic risk contagion blow-up",
        "strategic": "fraud misalignment hidden risk tail risk",
        "default":   "risk failure fraud criticism problem",
    },
    "manufacturing": {
        "causal":    "supply chain disruption shortage single-source failure",
        "strategic": "concentration risk dependency fragility",
        "default":   "disruption shortage quality problem recall",
    },
    "technology": {
        "causal":    "failure security vulnerability limitation criticism",
        "strategic": "lock-in dependency risk disruption alternative",
        "default":   "security failure privacy concern limitation",
    },
    "economics": {
        "causal":    "unintended consequence policy failure critique",
        "strategic": "inequality rent-seeking market failure criticism",
        "default":   "critique problem unintended consequence failure",
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def build_search_queries(
    message:        str,
    intent_profile: dict | None = None,
    domain:         str         = "",
) -> dict:
    """
    Build a primary query and a contradiction-seeking query for this message.

    Returns
    -------
    {
      "primary_query":       str,
      "contradiction_query": str,
      "primary_label":       str,  # human-readable label for the formatter
      "contradiction_label": str,
    }
    """
    intent_profile  = intent_profile or {}
    primary_intent  = intent_profile.get("primary_intent", "default")
    domain_key      = _normalise_domain(domain)
    base            = message.strip()[:150]
    primary_query   = base

    # Prefer domain-boosted suffix, fall back to intent-based, then generic
    suffix = (
        _domain_boosted_suffix(domain_key, primary_intent)
        or _INTENT_CONTRADICTION_SUFFIXES.get(primary_intent, "")
        or _DEFAULT_CONTRADICTION_SUFFIX
    )

    # For recency-flagged messages, force a recent-shift angle
    _recency_re = re.compile(
        r'\b(current|today|now|recent|latest|modern|2024|2025|this year)\b', re.I
    )
    if _recency_re.search(message):
        suffix = f"latest news 2024 2025 problems challenges reversal"

    contradiction_query = f"{base} {suffix}"

    return {
        "primary_query":       primary_query,
        "contradiction_query": contradiction_query,
        "primary_label":       "confirms or elaborates current understanding",
        "contradiction_label": "challenges, complicates, or reveals recent shifts",
    }


def fetch_reasoned_results(
    message:        str,
    intent_profile: dict | None = None,
    domain:         str         = "",
) -> dict:
    """
    Execute primary + contradiction searches and annotate results by angle.

    The contradiction results are deduplicated against the primary results
    so the LLM sees genuinely new complicating evidence, not overlap.

    Returns
    -------
    {
      "primary_query":       str,
      "contradiction_query": str,
      "supporting":          list[dict],   # primary results (tagged _angle="supporting")
      "complicating":        list[dict],   # contradiction-only results (tagged _angle="complicating")
      "all_articles":        list[dict],   # merged: primary first, then complicating
      "has_complicating":    bool,
    }
    """
    queries  = build_search_queries(message, intent_profile, domain)
    p_query  = queries["primary_query"]
    c_query  = queries["contradiction_query"]

    primary_articles = _safe_search(p_query)[:_PRIMARY_MAX]
    contra_articles  = _safe_search(c_query)

    # Dedup: only keep contradiction results not already in primary
    primary_urls = {a.get("url", "") for a in primary_articles if a.get("url")}
    complicating = [
        a for a in contra_articles
        if a.get("url", "") and a.get("url", "") not in primary_urls
    ][:_CONTRADICTION_MAX]

    # Tag by angle (metadata only — not shown to user, used by formatter)
    for a in primary_articles:
        a["_angle"] = "supporting"
    for a in complicating:
        a["_angle"] = "complicating"

    return {
        "primary_query":       p_query,
        "contradiction_query": c_query,
        "supporting":          primary_articles,
        "complicating":        complicating,
        "all_articles":        primary_articles + complicating,
        "has_complicating":    len(complicating) > 0,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Private helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _safe_search(query: str) -> list[dict]:
    try:
        from .retrieval_router import route
        return route(query, mode="chat")
    except Exception:
        logger.warning("[web_search_reasoning] search failed for %r", query[:60])
        return []


def _domain_boosted_suffix(domain_key: str, primary_intent: str) -> str:
    table = _DOMAIN_CONTRADICTION_HINTS.get(domain_key, {})
    return table.get(primary_intent) or table.get("default", "")


def _normalise_domain(domain: str) -> str:
    d = (domain or "").lower()
    if "pharma" in d:                              return "pharmaceutical"
    if "financ" in d or "bank" in d:              return "finance"
    if d == "ai" or "machine" in d or "intellig" in d: return "ai"
    if "manufact" in d:                            return "manufacturing"
    if "tech" in d or "software" in d or "comput" in d: return "technology"
    if "econ" in d or "trade" in d or "market" in d:    return "economics"
    return d
