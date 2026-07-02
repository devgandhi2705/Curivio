"""
Intelligent Tavily retrieval layer.

Architecture
------------
Four primitive operations sit at the bottom:
    _search_raw()   → raw Tavily search(), cached
    _extract_raw()  → raw Tavily extract(), cached
    _crawl_raw()    → raw Tavily crawl(), cached
    _map_raw()      → raw Tavily map(), cached

Domain-aware strategy wrappers sit in the middle:
    search_strategy()   — query-normalized, domain-tuned search
    extract_strategy()  — scored URL filtering, re-extract of trusted hits
    crawl_strategy()    — config-driven depth/limit
    map_strategy()      — discover-then-extract pipeline

A single orchestration entry-point sits at the top:
    intelligent_retrieve()     — pick the right operation(s) for domain + mode
    retrieval_mode_handler()   — delegate by mode (chat / feed / deep_research)

Credit-optimization rules
-------------------------
1. Extract > Crawl > Search for known URLs.
2. Never use advanced search when a known trusted URL exists.
3. Basic search + re-extract trusted hits = cheaper than advanced search alone.
4. Query normalization maximises cache hit-rate across equivalent queries.
5. Domain-level cache keys deduplicate equivalent domain-retrieval jobs.

URL-to-operation routing (per spec)
------------------------------------
GitHub page / HuggingFace model  → extract()
Documentation sites              → crawl()
arXiv specific paper             → extract()
arXiv listing / WHO / FDA        → crawl()
Reuters / Bloomberg / news       → search()
SEC filing / Fed release         → extract()
"""

from __future__ import annotations

import os
import re
import time
import logging
from urllib.parse import urlparse

from tavily import TavilyClient
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")

_API_KEY = os.getenv("TAVILY_API_KEY", "")
_MOCK    = os.getenv("MOCK_RETRIEVAL", "").lower() == "true"

if not _MOCK and not _API_KEY:
    raise EnvironmentError("TAVILY_API_KEY is not set in the environment.")

_client = TavilyClient(api_key=_API_KEY) if not _MOCK else None

logger = logging.getLogger(__name__)

# ── Credit cost estimates (USD) ───────────────────────────────────────────────
# Used only for logging; not billing.
_COST = {
    "search_basic":    0.001,
    "search_advanced": 0.003,
    "extract":         0.0005,
    "crawl_page":      0.0008,
    "map":             0.0005,
}

# ── Re-extract limit ──────────────────────────────────────────────────────────
# After a cheap search, re-extract at most this many trusted URLs for full content.
_MAX_REEXTRACT = 3


# ═══════════════════════════════════════════════════════════════════════════════
# URL-to-operation routing table
# ═══════════════════════════════════════════════════════════════════════════════

# Each entry: (compiled pattern, preferred_operation)
# Matched top-to-bottom; first match wins.
# "search" entries are explicit overrides (paywalled / dynamic sites).

_URL_OP_RULES: list[tuple[re.Pattern, str]] = [
    # ── News / paywalled → search only ──────────────────────────────────────
    (re.compile(r"bloomberg\.com|reuters\.com|ft\.com|wsj\.com|economist\.com"),
     "search"),

    # ── AI / research ────────────────────────────────────────────────────────
    (re.compile(r"arxiv\.org/abs/"),               "extract"),   # specific paper
    (re.compile(r"arxiv\.org/list/"),              "crawl"),     # recent listing
    (re.compile(r"paperswithcode\.com/paper/"),    "extract"),
    (re.compile(r"huggingface\.co/[^/]+/[^/]+"),  "extract"),   # model / dataset page
    (re.compile(r"huggingface\.co"),               "crawl"),     # HF hub root

    # ── Technology / docs ────────────────────────────────────────────────────
    (re.compile(r"github\.com/[^/]+/[^/]+/(blob|tree|releases)"),
     "extract"),                                                  # file / release page
    (re.compile(r"github\.com"),                   "extract"),   # repo or org
    (re.compile(r"readthedocs\.io"),               "crawl"),
    (re.compile(r"docs\.[a-z]"),                   "crawl"),     # docs.*.com
    (re.compile(r"/docs/|/documentation/|/reference/"),
     "crawl"),

    # ── Finance / regulatory ─────────────────────────────────────────────────
    (re.compile(r"sec\.gov/Archives|sec\.gov/cgi-bin"), "extract"),
    (re.compile(r"sec\.gov"),                       "crawl"),
    (re.compile(r"federalreserve\.gov/releases"),  "extract"),
    (re.compile(r"federalreserve\.gov"),           "crawl"),
    (re.compile(r"imf\.org/en/Publications"),      "extract"),

    # ── Pharma / health ──────────────────────────────────────────────────────
    (re.compile(r"clinicaltrials\.gov/study/"),    "extract"),   # specific trial
    (re.compile(r"clinicaltrials\.gov"),           "crawl"),
    (re.compile(r"fda\.gov/drugs|fda\.gov/biologics"), "crawl"),
    (re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/\d+"), "extract"),
    (re.compile(r"who\.int"),                      "crawl"),
    (re.compile(r"ema\.europa\.eu"),               "crawl"),

    # ── Trade / export ───────────────────────────────────────────────────────
    (re.compile(r"wto\.org"),                      "crawl"),
    (re.compile(r"worldbank\.org"),                "crawl"),
    (re.compile(r"trade\.gov"),                    "extract"),
]


def url_preferred_operation(url: str) -> str:
    """
    Return the preferred Tavily operation for a known URL.

    Returns "search" | "extract" | "crawl".
    Defaults to "extract" for unrecognised trusted URLs (better content
    than search, and only called when a URL is already known).
    """
    for pattern, op in _URL_OP_RULES:
        if pattern.search(url):
            return op
    return "extract"  # safe default for known URLs


# ═══════════════════════════════════════════════════════════════════════════════
# Query normalisation
# ═══════════════════════════════════════════════════════════════════════════════

_FILLER_RE = re.compile(
    r"\b(please|can you|tell me about|what is|how does|explain|show me|"
    r"give me|find|search for|look up)\b",
    re.IGNORECASE,
)
_WS_RE = re.compile(r"\s{2,}")


def normalize_query(query: str) -> str:
    """
    Normalise a query for maximum cache-hit rate.

    Strips leading/trailing whitespace, lowercases, collapses runs of
    whitespace, and removes conversational filler that Tavily ignores anyway.

    "Can you tell me about transformer attention?" → "transformer attention"
    "   Machine  Learning  " → "machine learning"
    """
    q = _FILLER_RE.sub(" ", query).strip().lower()
    return _WS_RE.sub(" ", q).strip()


def _cache_key(prefix: str, *parts: str) -> str:
    """Build a deterministic cache key from a prefix and parts."""
    return prefix + "::" + "|".join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
# Unified article shape
# ═══════════════════════════════════════════════════════════════════════════════

def _to_article(raw: dict, source_op: str = "") -> dict:
    """
    Normalise a raw Tavily result to a consistent article dict.

    Fields: title, url, content, source_op (for debug/logging).
    ``raw_content`` from extract/crawl is truncated to 2 000 chars and placed
    in ``content`` so downstream rankers see a uniform schema.
    """
    content = (
        raw.get("content")
        or raw.get("raw_content")
        or ""
    )
    return {
        "title":      raw.get("title", ""),
        "url":        raw.get("url",   ""),
        "content":    content[:2000],
        "source_op":  source_op,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Mock helpers (MOCK_RETRIEVAL=true → no real API calls)
# ═══════════════════════════════════════════════════════════════════════════════

def _mock_articles(query: str, op: str, count: int = 3) -> list[dict]:
    return [
        {
            "title":     f"[MOCK/{op.upper()}] {query} — result {i}",
            "url":       f"https://mock-{op}.example.com/{i}",
            "content":   (
                f"Mock content for '{query}' via {op}. "
                "Contains sufficient text to pass the content-length quality filter "
                "and represent a realistic article for testing purposes."
            ),
            "source_op": op,
        }
        for i in range(1, count + 1)
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# Primitive operations  (raw Tavily calls + cache + logging)
# ═══════════════════════════════════════════════════════════════════════════════

def _search_raw(
    query:        str,
    max_results:  int  = 8,
    search_depth: str  = "basic",
    include_domains: list[str] | None = None,
) -> list[dict]:
    """
    Single Tavily search() call with caching.

    Returns normalised article dicts (title, url, content, source_op).
    """
    if _MOCK:
        return _mock_articles(query, "search")

    from .search_cache_service import get_cached_search, cache_search
    from .api_usage_service    import log_api_call, estimate_tavily_cost

    key = _cache_key(
        "search", query, str(max_results), search_depth,
        ",".join(sorted(include_domains or [])),
    )
    cached = get_cached_search(key)
    if cached is not None:
        log_api_call(service="tavily", operation="search", cache_hit=True,
                     query_hint=query[:120], estimated_cost_usd=0.0)
        logger.info("[tavily] search CACHE HIT | %.60s", query)
        return cached

    t0 = time.monotonic()
    kwargs: dict = dict(
        query        = query,
        max_results  = max_results,
        search_depth = search_depth,
        include_answer = False,
    )
    if include_domains:
        kwargs["include_domains"] = include_domains

    try:
        response = _client.search(**kwargs)
    except Exception as exc:
        raise RuntimeError(f"Tavily search failed: {exc}") from exc

    ms      = int((time.monotonic() - t0) * 1000)
    results = [_to_article(r, "search") for r in response.get("results", [])]
    cache_search(key, results)

    cost_key = f"search_{search_depth}"
    cost     = _COST.get(cost_key, _COST["search_basic"])
    log_api_call(service="tavily", operation="search", cache_hit=False,
                 query_hint=query[:120], duration_ms=ms, estimated_cost_usd=cost)
    logger.info("[tavily] search LIVE %dms | n=%d | depth=%s | $%.4f",
                ms, len(results), search_depth, cost)
    return results


def _extract_raw(urls: list[str]) -> list[dict]:
    """Single Tavily extract() call with caching."""
    if not urls:
        return []
    if _MOCK:
        return _mock_articles(urls[0], "extract", count=len(urls))

    from .search_cache_service import get_cached_search, cache_search
    from .api_usage_service    import log_api_call, estimate_tavily_cost

    key    = _cache_key("extract", *sorted(urls))
    cached = get_cached_search(key)
    if cached is not None:
        log_api_call(service="tavily", operation="extract", cache_hit=True,
                     query_hint=f"{len(urls)} urls", estimated_cost_usd=0.0)
        logger.info("[tavily] extract CACHE HIT | %d urls", len(urls))
        return cached

    t0 = time.monotonic()
    try:
        response = _client.extract(urls=urls)
    except Exception as exc:
        raise RuntimeError(f"Tavily extract failed: {exc}") from exc

    ms      = int((time.monotonic() - t0) * 1000)
    results = [_to_article(r, "extract") for r in response.get("results", [])]
    cache_search(key, results)

    cost = _COST["extract"] * len(urls)
    log_api_call(service="tavily", operation="extract", cache_hit=False,
                 query_hint=f"{len(urls)} urls", duration_ms=ms, estimated_cost_usd=cost)
    logger.info("[tavily] extract LIVE %dms | %d urls | $%.4f", ms, len(results), cost)
    return results


def _crawl_raw(
    url:       str,
    max_depth: int        = 2,
    limit:     int        = 20,
    query:     str | None = None,
) -> list[dict]:
    """Single Tavily crawl() call with caching."""
    if _MOCK:
        return _mock_articles(url, "crawl")

    from .search_cache_service import get_cached_search, cache_search
    from .api_usage_service    import log_api_call, estimate_tavily_cost

    key    = _cache_key("crawl", url, str(max_depth), str(limit), query or "")
    cached = get_cached_search(key)
    if cached is not None:
        log_api_call(service="tavily", operation="crawl", cache_hit=True,
                     query_hint=url[:120], estimated_cost_usd=0.0)
        logger.info("[tavily] crawl CACHE HIT | %.80s", url)
        return cached

    t0     = time.monotonic()
    kwargs: dict = dict(url=url, max_depth=max_depth, limit=limit)
    if query:
        kwargs["query"] = query
    try:
        response = _client.crawl(**kwargs)
    except Exception as exc:
        raise RuntimeError(f"Tavily crawl failed for {url!r}: {exc}") from exc

    ms      = int((time.monotonic() - t0) * 1000)
    results = [_to_article(r, "crawl") for r in response.get("results", [])]
    cache_search(key, results)

    cost = _COST["crawl_page"] * len(results)
    log_api_call(service="tavily", operation="crawl", cache_hit=False,
                 query_hint=url[:120], duration_ms=ms, estimated_cost_usd=cost)
    logger.info("[tavily] crawl LIVE %dms | %.60s | pages=%d | $%.4f",
                ms, url, len(results), cost)
    return results


def _map_raw(url: str, query: str | None = None) -> list[str]:
    """Single Tavily map() call with caching. Returns URL strings."""
    if _MOCK:
        return [f"https://mock-map.example.com/{i}" for i in range(1, 6)]

    from .search_cache_service import get_cached_search, cache_search
    from .api_usage_service    import log_api_call, estimate_tavily_cost

    key    = _cache_key("map", url, query or "")
    cached = get_cached_search(key)
    if cached is not None:
        log_api_call(service="tavily", operation="map", cache_hit=True,
                     query_hint=url[:120], estimated_cost_usd=0.0)
        logger.info("[tavily] map CACHE HIT | %.80s", url)
        return cached

    t0     = time.monotonic()
    kwargs: dict = {"url": url}
    if query:
        kwargs["query"] = query
    try:
        response = _client.map(**kwargs)
    except Exception as exc:
        raise RuntimeError(f"Tavily map failed for {url!r}: {exc}") from exc

    ms   = int((time.monotonic() - t0) * 1000)
    urls: list[str] = (
        response if isinstance(response, list) else response.get("urls", [])
    )
    cache_search(key, urls)

    log_api_call(service="tavily", operation="map", cache_hit=False,
                 query_hint=url[:120], duration_ms=ms, estimated_cost_usd=_COST["map"])
    logger.info("[tavily] map LIVE %dms | %.60s | found=%d", ms, url, len(urls))
    return urls


# ═══════════════════════════════════════════════════════════════════════════════
# Backward-compatible public aliases  (used by existing callers)
# ═══════════════════════════════════════════════════════════════════════════════

def search_articles(
    query:        str,
    max_results:  int = 10,
    search_depth: str = "basic",
) -> list[dict]:
    """Legacy alias → _search_raw().  Callers receive the unified article shape."""
    return _search_raw(normalize_query(query), max_results=max_results,
                       search_depth=search_depth)


def extract_urls(urls: list[str]) -> list[dict]:
    """Legacy alias → _extract_raw()."""
    return _extract_raw(urls)


def crawl_domain(
    url:       str,
    max_depth: int        = 2,
    limit:     int        = 20,
    query:     str | None = None,
) -> list[dict]:
    """Legacy alias → _crawl_raw()."""
    return _crawl_raw(url, max_depth=max_depth, limit=limit, query=query)


def map_domain(url: str, query: str | None = None) -> list[str]:
    """Legacy alias → _map_raw()."""
    return _map_raw(url, query=query)


# ═══════════════════════════════════════════════════════════════════════════════
# Domain-aware strategy wrappers
# ═══════════════════════════════════════════════════════════════════════════════

def search_strategy(
    query:           str,
    domain:          str             = "default",
    mode:            str             = "chat",
    extra_domains:   list[str] | None = None,
) -> list[dict]:
    """
    Domain-tuned search.

    Selects search depth and max_results from the domain config for the given
    mode. Applies the domain's ``include_domains`` filter so Tavily biases
    results toward trusted sources without burning extract credits.

    Credit usage: 1× basic or advanced search.
    """
    from ..config.retrieval_config import get_domain_config

    cfg  = get_domain_config(domain)
    nq   = normalize_query(query)

    if mode == "chat":
        depth   = "basic"
        max_r   = min(cfg.feed_retrieval_rules.max_results_per_query, 8)
    elif mode == "feed":
        depth   = cfg.feed_retrieval_rules.search_depth
        max_r   = cfg.feed_retrieval_rules.max_results_per_query
    else:  # deep_research
        depth   = cfg.deep_research_rules.search_depth
        max_r   = 10

    inc_domains = list(cfg.include_domains)
    if extra_domains:
        inc_domains = list(dict.fromkeys(inc_domains + extra_domains))

    return _search_raw(nq, max_results=max_r, search_depth=depth,
                       include_domains=inc_domains or None)


def extract_strategy(
    urls:       list[str],
    query_hint: str = "",
) -> list[dict]:
    """
    Extract full content from a list of known trusted URLs.

    Filters out URLs that the routing table says should use search() instead
    (e.g. paywalled news sites), then calls extract on the remainder.

    Credit usage: cheaper than one advanced search for ≤3 URLs.
    """
    extractable = [u for u in urls if url_preferred_operation(u) != "search"]
    if not extractable:
        logger.debug("[tavily] extract_strategy: all URLs flagged search-only, skipping")
        return []

    logger.info("[tavily] extract_strategy: %d/%d urls extractable",
                len(extractable), len(urls))
    return _extract_raw(extractable)


def crawl_strategy(
    url:    str,
    query:  str        = "",
    domain: str        = "default",
) -> list[dict]:
    """
    Crawl a domain URL using depth and limit from the domain config.

    Falls back to sensible defaults when no crawl_targets are configured.
    Credit usage: expensive — only call in deep_research or batch jobs.
    """
    from ..config.retrieval_config import get_domain_config

    cfg        = get_domain_config(domain)
    crawl_cfg  = cfg.crawl_targets[0] if cfg.crawl_targets else None
    max_depth  = crawl_cfg.max_depth if crawl_cfg else 2
    limit      = crawl_cfg.limit     if crawl_cfg else 20

    return _crawl_raw(url, max_depth=max_depth, limit=limit,
                      query=query or None)


def map_strategy(
    url:         str,
    query:       str = "",
    then_extract: bool = True,
    max_extract:  int = 5,
) -> list[dict]:
    """
    Discover URLs via map(), then extract the top matches.

    ``then_extract=True`` (default) converts the URL list into full articles
    via extract_strategy().  Set to False to get just the URL strings.

    Credit usage: 1× map + up to ``max_extract`` × extract.
    """
    discovered = _map_raw(url, query=query or None)
    if not discovered:
        return []

    if not then_extract:
        return [{"url": u, "title": "", "content": "", "source_op": "map"}
                for u in discovered]

    target_urls = discovered[:max_extract]
    logger.info("[tavily] map_strategy: discovered %d, extracting %d",
                len(discovered), len(target_urls))
    return extract_strategy(target_urls, query_hint=query)


# ═══════════════════════════════════════════════════════════════════════════════
# Re-extraction of trusted hits
# ═══════════════════════════════════════════════════════════════════════════════

def _reextract_trusted(
    search_results: list[dict],
    authority_domains: dict[str, float],
    limit: int = _MAX_REEXTRACT,
) -> list[dict]:
    """
    From a list of search results, find URLs belonging to trusted domains and
    re-extract them for full content.

    This is the core credit-optimization pattern:
        cheap basic_search → find trusted URLs → extract(those URLs)
    is cheaper than a single advanced_search over the same corpus.

    Returns a list of extracted articles for the trusted URLs found.
    """
    trusted_urls: list[str] = []
    for article in search_results:
        url = article.get("url", "")
        if not url:
            continue
        try:
            netloc = urlparse(url).netloc.lower().removeprefix("www.")
        except Exception:
            continue
        if any(td in netloc for td in authority_domains):
            op = url_preferred_operation(url)
            if op == "extract":
                trusted_urls.append(url)
            # skip crawl-preferred URLs — too expensive to crawl per-result

    if not trusted_urls:
        return []

    batch = trusted_urls[:limit]
    logger.info("[tavily] re-extracting %d trusted URLs from search results", len(batch))
    return extract_strategy(batch)


# ═══════════════════════════════════════════════════════════════════════════════
# intelligent_retrieve — main orchestration entry point
# ═══════════════════════════════════════════════════════════════════════════════

def intelligent_retrieve(
    query:             str,
    domain:            str             = "default",
    mode:              str             = "chat",
    pre_known_urls:    list[str] | None = None,
    crawl_seed:        str | None       = None,
) -> list[dict]:
    """
    Retrieve articles using the best Tavily operation mix for the given
    domain and mode.

    Decision flow
    -------------
    1. Normalise query (maximises cache hits).
    2. If pre_known_urls provided → route each by URL operation table
       (extract, crawl, or skip).  This handles ``extract_targets`` from
       retrieval_config.
    3. Run search_strategy() with domain ``include_domains`` filter.
    4. Re-extract trusted URLs found in search results (cheap pattern).
    5. If crawl_seed provided (deep_research / crawl_primary strategy) →
       run crawl_strategy().
    6. URL-deduplicate and return.

    Parameters
    ----------
    query          User query (will be normalised internally).
    domain         retrieval_config key, e.g. "finance", "pharma".
    mode           "chat" | "feed" | "deep_research"
    pre_known_urls Static trusted URLs to extract/crawl before searching.
                   Typically the domain config's extract_targets.
    crawl_seed     URL to crawl (deep_research mode, crawl_primary strategy).
    """
    from ..config.retrieval_config import get_domain_config

    nq  = normalize_query(query)
    cfg = get_domain_config(domain)

    seen:    set[str]    = set()
    results: list[dict]  = []

    def _add(articles: list[dict]) -> None:
        for a in articles:
            url = a.get("url", "")
            if url and url not in seen:
                seen.add(url)
                results.append(a)

    # ── Step 1: pre-known URLs (extract / crawl by URL routing table) ─────────
    if pre_known_urls and mode != "chat":
        extract_batch: list[str] = []
        for url in pre_known_urls:
            op = url_preferred_operation(url)
            if op == "extract":
                extract_batch.append(url)
            elif op == "crawl":
                try:
                    _add(crawl_strategy(url, query=nq, domain=domain))
                except Exception as exc:
                    logger.warning("[tavily] pre-known crawl failed %s: %s", url, exc)

        if extract_batch:
            try:
                _add(extract_strategy(extract_batch))
            except Exception as exc:
                logger.warning("[tavily] pre-known extract failed: %s", exc)

    # ── Step 2: domain-filtered search ───────────────────────────────────────
    try:
        search_hits = search_strategy(nq, domain=domain, mode=mode)
        _add(search_hits)
    except Exception as exc:
        logger.warning("[tavily] search_strategy failed: %s", exc)
        search_hits = []

    # ── Step 3: re-extract trusted URLs from search hits (feed/deep only) ────
    if mode != "chat" and search_hits and cfg.trusted_domains:
        try:
            _add(_reextract_trusted(search_hits, cfg.trusted_domains))
        except Exception as exc:
            logger.warning("[tavily] re-extract failed: %s", exc)

    # ── Step 4: crawl seed (deep_research / crawl_primary) ───────────────────
    if crawl_seed and mode == "deep_research":
        try:
            _add(crawl_strategy(crawl_seed, query=nq, domain=domain))
        except Exception as exc:
            logger.warning("[tavily] crawl_seed failed %s: %s", crawl_seed, exc)

    logger.info(
        "[tavily] intelligent_retrieve | domain=%s mode=%s query=%.50s → %d articles",
        domain, mode, nq, len(results),
    )
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# retrieval_mode_handler — delegates by mode
# ═══════════════════════════════════════════════════════════════════════════════

def retrieval_mode_handler(
    query:  str,
    domain: str = "default",
    mode:   str = "chat",
) -> list[dict]:
    """
    Top-level mode dispatcher.

    chat          → single search_strategy() call, no extract/crawl
    feed          → intelligent_retrieve() with domain extract_targets
    deep_research → intelligent_retrieve() with extract_targets + crawl_seed

    This is the function retrieval_router.execute_plan() delegates to for
    each operation, replacing direct primitive calls.
    """
    from ..config.retrieval_config import get_domain_config

    cfg = get_domain_config(domain)

    if mode == "chat":
        return search_strategy(query, domain=domain, mode="chat")

    pre_known = (
        [t.url for t in cfg.extract_targets]
        if cfg.extract_targets else None
    )
    crawl_seed = (
        cfg.crawl_targets[0].url
        if cfg.crawl_targets and mode == "deep_research" and cfg.deep_research_rules.use_crawl
        else None
    )

    return intelligent_retrieve(
        query        = query,
        domain       = domain,
        mode         = mode,
        pre_known_urls = pre_known,
        crawl_seed   = crawl_seed,
    )
