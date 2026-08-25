"""
Domain-aware retrieval orchestration router.

Replaces the pattern ``query → search_articles()`` with:

    query → classify → plan → execute

The router selects the right Tavily operations (search / extract / crawl / map)
based on the query domain, retrieval mode, and domain config rules — never
blindly calling search() for everything.

Two retrieval modes
-------------------
  chat          Fast, single query, minimal credits.  Prioritises latency.
  feed          Educational, trusted-source focused.  2 queries + targeted
                extract for known high-value URLs in the domain.

Public API
----------
route(query, mode, override_queries)   → list[dict]   classify+plan+execute
build_plan(query, mode, override_queries) → RetrievalPlan   plan only (no I/O)
execute_plan(plan)                     → list[dict]   execute a pre-built plan
multi_classify(text)                   → ClassificationResult  domain scoring

Classes
-------
DomainScore          domain key + confidence + classifier name
ClassificationResult primary domain + secondary domains above threshold
RetrievalPlan        full execution plan (no I/O; fully serialisable)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

VALID_MODES       = ("chat", "feed")
_CONF_NORM        = 6     # keyword overlap ≥ this → confidence = 1.0
_SECONDARY_FLOOR  = 0.15  # minimum confidence to be listed as a secondary domain
_MOCK_RETRIEVAL   = os.getenv("VITE_USE_MOCK", "").lower() == "true" or \
                    os.getenv("MOCK_RETRIEVAL",  "").lower() == "true"


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DomainScore:
    domain_key:      str    # retrieval_config key, e.g. "finance"
    classifier_name: str    # domain_classifier name, e.g. "Finance"
    confidence:      float  # [0, 1]


@dataclass(frozen=True)
class ClassificationResult:
    primary:   DomainScore
    secondary: list[DomainScore]  # above _SECONDARY_FLOOR, descending confidence
    raw_text:  str


@dataclass
class RetrievalPlan:
    """
    Fully describes a retrieval job.

    Building a plan is pure (no I/O).  Executing it makes Tavily calls.
    """
    mode:              str                   # "chat" | "feed"
    classification:    ClassificationResult
    strategy:          str                   # from DomainRetrievalConfig
    operations:        list[str]             # ordered: e.g. ["extract", "search"]
    search_queries:    list[str]
    extract_urls:      list[str]
    crawl_url:         str | None
    max_results:       int
    search_depth:      str
    domain_key:        str
    preferred_domains: list[str] = field(default_factory=list)


# ── Classification ────────────────────────────────────────────────────────────

def multi_classify(text: str) -> ClassificationResult:
    """
    Score text against every domain keyword vocab and return the top result
    plus any secondary domains above _SECONDARY_FLOOR confidence.

    Confidence is min(1.0, overlap / _CONF_NORM).  Six or more keyword
    matches → 100% confidence.

    Multi-domain detection example:
      "FDA pharma manufacturing quality" → primary=pharma(0.67), secondary=[manufacturing(0.33)]
    """
    from .domain_classifier_service import (       # deferred: avoids circular at load
        _tokenise, _DOMAIN_KEYWORDS, DOMAIN_PRIORITY, DOMAIN_UNCATEGORIZED,
    )
    from ..config.retrieval_config import CLASSIFIER_NAME_MAP

    tokens = _tokenise(text)
    scored: list[tuple[int, str]] = []

    for classifier_name in DOMAIN_PRIORITY:
        if classifier_name == DOMAIN_UNCATEGORIZED:
            continue
        keywords = _DOMAIN_KEYWORDS.get(classifier_name, frozenset())
        overlap  = len(tokens & keywords)
        if overlap > 0:
            scored.append((overlap, classifier_name))

    if not scored:
        primary = DomainScore(
            domain_key      = "default",
            classifier_name = DOMAIN_UNCATEGORIZED,
            confidence      = 0.5,
        )
        return ClassificationResult(primary=primary, secondary=[], raw_text=text)

    scored.sort(key=lambda x: x[0], reverse=True)

    domain_scores: list[DomainScore] = [
        DomainScore(
            domain_key      = CLASSIFIER_NAME_MAP.get(name, "default"),
            classifier_name = name,
            confidence      = min(1.0, overlap / _CONF_NORM),
        )
        for overlap, name in scored
    ]

    primary   = domain_scores[0]
    secondary = [d for d in domain_scores[1:] if d.confidence >= _SECONDARY_FLOOR]
    return ClassificationResult(primary=primary, secondary=secondary, raw_text=text)


# ── Plan building ─────────────────────────────────────────────────────────────

def build_plan(
    query:             str,
    mode:              str             = "chat",
    override_queries:  list[str] | None = None,
    preferred_domains: list[str] | None = None,
) -> RetrievalPlan:
    """
    Build a RetrievalPlan without making any API calls.

    Parameters
    ----------
    query            The user's raw query or topic string.
    mode             "chat" | "feed"
    override_queries If provided, these queries are used for 'search' operations
                     instead of the templates in domain config.  Useful when a
                     caller has already expanded domain-specific queries and
                     wants the router to handle only the Tavily dispatch and
                     extract steps.
    """
    from ..config.retrieval_config import get_domain_config

    if mode not in VALID_MODES:
        logger.warning("[retrieval_router] unknown mode %r — falling back to chat", mode)
        mode = "chat"

    classification = multi_classify(query)
    domain_key     = classification.primary.domain_key
    cfg            = get_domain_config(domain_key)
    strategy       = cfg.retrieval_strategy

    # ── Mode rules ────────────────────────────────────────────────────────────
    if mode == "chat":
        search_count  = 1
        max_results   = min(cfg.feed_retrieval_rules.max_results_per_query, 8)
        search_depth  = "basic"
        use_extract   = False
        use_crawl     = False
        max_extracts  = 0

    else:  # feed
        r             = cfg.feed_retrieval_rules
        search_count  = r.search_queries_per_package
        max_results   = r.max_results_per_query
        search_depth  = r.search_depth
        use_extract   = r.use_extract_for_known_urls
        use_crawl     = False
        max_extracts  = 2

    # ── Search queries ────────────────────────────────────────────────────────
    if override_queries:
        search_queries = list(override_queries[:search_count])
    else:
        try:
            from .query_expansion_engine import get_query_strings
            search_queries = get_query_strings(query, mode=mode)[:search_count]
        except Exception:
            logger.warning("[retrieval_router] query expansion failed, using config templates")
            templates      = cfg.query_templates[:search_count]
            search_queries = [t.format(topic=query) for t in templates] or [query]

    # ── Extract targets ───────────────────────────────────────────────────────
    extract_urls: list[str] = []
    if use_extract and cfg.extract_targets:
        extract_urls = [t.url for t in cfg.extract_targets[:max_extracts]]

    # ── Crawl target ──────────────────────────────────────────────────────────
    crawl_url: str | None = None
    if use_crawl and cfg.crawl_targets:
        crawl_url = cfg.crawl_targets[0].url

    operations = _select_operations(strategy, search_queries, extract_urls, crawl_url, mode)

    return RetrievalPlan(
        mode              = mode,
        classification    = classification,
        strategy          = strategy,
        operations        = operations,
        search_queries    = search_queries,
        extract_urls      = extract_urls,
        crawl_url         = crawl_url,
        max_results       = max_results,
        search_depth      = search_depth,
        domain_key        = domain_key,
        preferred_domains = list(preferred_domains) if preferred_domains else [],
    )


def _select_operations(
    strategy:      str,
    search_queries: list[str],
    extract_urls:  list[str],
    crawl_url:     str | None,
    mode:          str,
) -> list[str]:
    """
    Return an ordered list of Tavily operations to execute for this plan.

    Strategy mapping
    ----------------
    extract_first   extract → search (search as fallback/supplement)
    mixed           search → extract (parallel intent, sequential here)
    crawl_primary   crawl  → search
    search_first    search → extract (extract only in non-chat modes)
    """
    if strategy == "extract_first" and extract_urls:
        ops = ["extract", "search"] if search_queries else ["extract"]

    elif strategy == "mixed" and extract_urls:
        ops = ["search", "extract"]

    elif strategy == "crawl_primary" and crawl_url:
        ops = ["crawl", "search"] if search_queries else ["crawl"]

    else:  # search_first or no matching targets
        ops = ["search"]
        if extract_urls and mode != "chat":
            ops.append("extract")

    return ops


# ── Plan execution ────────────────────────────────────────────────────────────

def execute_plan(plan: RetrievalPlan, meta: dict | None = None) -> list[dict]:
    """
    Execute a RetrievalPlan and return a URL-deduplicated article list.

    Each article has: title, url, content.
    Partial operation failures are logged and skipped; never raised.

    `meta`, when given, is passed through to tinyfish_service so its raw-
    response llm_call_log row (Phase B1) carries the caller's trace_id/
    user_id/project_id/surface — otherwise those TinyFish calls log ungrouped.
    """
    if _MOCK_RETRIEVAL:
        return _mock_execute(plan)

    from .tinyfish_service import search as tinyfish_search, fetch_as_articles

    seen: set[str]  = set()
    results: list[dict] = []

    def _merge(articles: list[dict]) -> None:
        for a in articles:
            url = a.get("url", "")
            if url and url not in seen:
                seen.add(url)
                results.append(a)

    for op in plan.operations:

        if op == "search":
            for query in plan.search_queries:
                try:
                    _merge(tinyfish_search(query, meta=meta))
                except Exception as exc:
                    logger.warning(
                        "[retrieval_router] search failed for %r: %s", query[:60], exc
                    )

        elif op == "extract" and plan.extract_urls:
            try:
                _merge(fetch_as_articles(plan.extract_urls, meta=meta))
            except Exception as exc:
                logger.warning("[retrieval_router] extract failed: %s", exc)

        elif op == "crawl" and plan.crawl_url:
            try:
                from .tavily_service import crawl_strategy  # no mode sets use_crawl=True currently; kept for a future mode
                query_hint = plan.search_queries[0] if plan.search_queries else None
                _merge(crawl_strategy(
                    plan.crawl_url,
                    query  = query_hint,
                    domain = plan.domain_key,
                ))
            except Exception as exc:
                logger.warning("[retrieval_router] crawl failed: %s", exc)

    logger.info(
        "[retrieval_router] %s/%s: %d articles | ops=%s | queries=%d",
        plan.mode, plan.domain_key, len(results), plan.operations, len(plan.search_queries),
    )
    return results


# ── Public convenience function ───────────────────────────────────────────────

def route(
    query:             str,
    mode:              str             = "chat",
    override_queries:  list[str] | None = None,
    preferred_domains: list[str] | None = None,
    meta:              dict | None      = None,
) -> list[dict]:
    """
    Classify, plan, and execute retrieval in one call.

    Parameters
    ----------
    query             User query or topic string.
    mode              "chat" | "feed"
    override_queries  Optional explicit search queries (bypasses template expansion).
    preferred_domains Trusted domain hints injected into Tavily include_domains.
                      Biases results toward these domains without restricting broader search.
    meta              Optional trace_id/user_id/project_id/surface/is_test — forwarded
                      to tinyfish_service's raw-capture logging (Phase B1). Every
                      caller (legacy feed, chat's web_search) may pass it;
                      omitted, TinyFish calls still log, just ungrouped.

    Returns a list of article dicts.  Never raises — errors return an empty list.
    """
    try:
        plan = build_plan(
            query,
            mode,
            override_queries  = override_queries,
            preferred_domains = preferred_domains,
        )
        return execute_plan(plan, meta=meta)
    except Exception as exc:
        logger.exception(
            "[retrieval_router] route failed for %r (mode=%s): %s", query[:60], mode, exc
        )
        return []


# ── Mock execution ────────────────────────────────────────────────────────────

def _mock_execute(plan: RetrievalPlan) -> list[dict]:
    """
    Return synthetic articles for testing without hitting Tavily.

    Produces 3 articles labelled with domain and operation type.
    """
    domain  = plan.domain_key
    op_list = ", ".join(plan.operations)
    logger.info(
        "[retrieval_router] MOCK execute | mode=%s domain=%s ops=[%s]",
        plan.mode, domain, op_list,
    )
    q = plan.search_queries[0] if plan.search_queries else plan.classification.raw_text
    return [
        {
            "url":     f"https://mock-{domain}.example.com/article-{i}",
            "title":   f"[MOCK {domain.upper()}] {q} — Article {i}",
            "content": (
                f"Mock content for '{q}' in domain '{domain}'. "
                f"Retrieved via {op_list} strategy in {plan.mode} mode. "
                f"This article simulates a trusted source for testing purposes. "
                f"It contains enough text to pass the content-length quality filter "
                f"and avoid being discarded by source_ranker."
            ),
        }
        for i in range(1, 4)
    ]
