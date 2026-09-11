"""
TinyFish retrieval layer — Feed's only live search/fetch backend.

Two TinyFish endpoints:
    search(query)              -> list[dict]  Search API, normalised to the
                                   article shape every consumer reads:
                                   {title, url, content, source_op}. Response field
                                   is "snippet", mapped here to "content".
    fetch(urls, image_links)   -> dict[url, dict]  Fetch API — full clean content
                                   (untruncated) + optional image_links per URL.
                                   Callers decide truncation (see fetch_as_articles()
                                   for the live-pipeline path, which truncates).
    fetch_as_articles(urls)    -> list[dict]  Fetch, normalised + truncated to the
                                   same 2000-char article shape as search() — used
                                   by retrieval_router for the 6 curated-domain
                                   extract_targets (these feed the live pipeline).

TinyFish Search has no result-count parameter — sliced to _MAX_SEARCH_RESULTS
client-side. Neither endpoint consumes credits (per TinyFish docs).
"""

from __future__ import annotations

import json
import os
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import requests
from dotenv import load_dotenv

from ..utils.text import truncate_at_sentence

load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")

_API_KEY = os.getenv("TINYFISH_API_KEY", "")
_MOCK    = os.getenv("MOCK_RETRIEVAL", "").lower() == "true"

if not _MOCK and not _API_KEY:
    raise EnvironmentError("TINYFISH_API_KEY is not set in the environment.")

_SEARCH_URL = "https://api.search.tinyfish.ai"
_FETCH_URL  = "https://api.fetch.tinyfish.ai"

_MAX_SEARCH_RESULTS = 5    # TinyFish Search has no server-side result-count param
_MAX_FETCH_URLS     = 10   # TinyFish Fetch's per-request limit
_SEARCH_TIMEOUT_S   = 30
_FETCH_TIMEOUT_S    = 60   # Fetch renders real JS pages, up to 10 in one request — needs more headroom

logger = logging.getLogger(__name__)


def _log_raw(
    call_type: str, input_text: str, t0: float,
    *, output: str | None, success: bool, error: Exception | None,
    meta: dict | None,
) -> None:
    """Phase B1 / Admin-4: one row per real TinyFish request, capturing the
    RAW response — before search()'s 2000-char snippet truncation and
    _MAX_SEARCH_RESULTS slice, before fetch()'s per-URL normalisation. Shared
    by every caller (legacy feed direct calls, retrieval_router, chat's
    web_search) so the raw capture lives in exactly one place
    instead of being duplicated per caller. meta carries trace_id/user_id/
    project_id/day_ref/surface/is_test from whichever caller made the request;
    omitted (None) meta still logs, just ungrouped. Never raises."""
    from ..llm.call_logger import write_call_row
    meta = meta or {}
    now = datetime.now(timezone.utc).isoformat()
    write_call_row(
        run_id=uuid4().hex,
        parent_run_id=None,
        timestamp_start=now,
        timestamp_end=now,
        latency_ms=int((time.monotonic() - t0) * 1000),
        provider="tinyfish",
        call_type=call_type,
        user_id=meta.get("user_id"),
        project_id=meta.get("project_id"),
        day_ref=meta.get("day_ref"),
        input_text=input_text,
        output=output,
        success=success,
        error_type=type(error).__name__ if error else None,
        error_message=str(error) if error else None,
        trace_id=meta.get("trace_id"),
        agent_name=meta.get("agent_name", "tinyfish"),
        surface=meta.get("surface"),
        is_test=bool(meta.get("is_test", False)),
    )


def _mock_articles(query: str, count: int = 3) -> list[dict]:
    return [
        {
            "title":     f"[MOCK/TINYFISH] {query} — result {i}",
            "url":       f"https://mock-tinyfish.example.com/{i}",
            "content":   (
                f"Mock content for '{query}' via tinyfish search. "
                "Contains sufficient text to pass the content-length quality filter."
            ),
            "source_op": "tinyfish_search",
        }
        for i in range(1, count + 1)
    ]


def _cache_get(key: str) -> list[dict] | None:
    """Cached results for `key`, or None on a miss.

    Deferred import + swallowed errors on purpose: retrieval is a live user path
    and must not fail because the cache table is missing or unreadable (a fresh
    DB, a test with no search_cache table). A cache problem degrades to a live
    call, never to a failed search.
    """
    try:
        from .search_cache_service import get_cached_search
        return get_cached_search(key)
    except Exception:
        logger.debug("[tinyfish] cache read failed — falling through to live search", exc_info=True)
        return None


def _cache_put(key: str, articles: list[dict]) -> None:
    """Store results for `key`. Same non-fatal contract as _cache_get."""
    try:
        from .search_cache_service import cache_search
        cache_search(key, articles)
    except Exception:
        logger.debug("[tinyfish] cache write failed — result not cached", exc_info=True)


def search(query: str, include_domains: list[str] | None = None, meta: dict | None = None) -> list[dict]:
    """
    TinyFish Search — normalised article dicts (title, url, content, source_op).
    Never raises for empty results; raises RuntimeError on a request-level failure
    (network/auth).

    Cached in search_cache (SEARCH_CACHE_TTL_HOURS, default 6) keyed on the
    effective query, so repeating a query inside the window costs no API call.
    A cache hit skips the llm_call_log raw-capture row below — the row records a
    real outbound request, and a hit makes none.

    `include_domains`, when given, scopes results to those domains using
    TinyFish's documented in-query search-operator support (there is no
    separate include_domains request param) — used by the one live call site
    that needs it (project_service's rotating_theme trusted-domain
    supplementary search).

    `meta`, when given, carries trace_id/user_id/project_id/day_ref/surface/
    is_test for the raw-response llm_call_log row Phase B1 writes here — the
    ONE place the true unsliced, untruncated TinyFish response is captured,
    shared by every caller (retrieval_router, legacy feed's direct calls).
    """
    if _MOCK:
        return _mock_articles(query)

    q = query
    if include_domains:
        site_ops = " OR ".join(f"site:{d}" for d in include_domains)
        q = f"{query} ({site_ops})"

    # Cache on the EFFECTIVE query (site: operators included), so a domain-scoped
    # search never collides with the same bare query. The prefix keeps these rows
    # from colliding with anything else sharing the search_cache table.
    cache_key = f"tinyfish_search:{q}"
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.info("[tinyfish] search CACHE HIT | %.60s", q)
        return cached

    t0 = time.monotonic()
    try:
        resp = requests.get(
            _SEARCH_URL,
            params={"query": q},
            headers={"X-API-Key": _API_KEY},
            timeout=_SEARCH_TIMEOUT_S,
        )
        resp.raise_for_status()
    except Exception as exc:
        _log_raw("tinyfish_search", q, t0, output=None, success=False, error=exc, meta=meta)
        raise RuntimeError(f"TinyFish search failed: {exc}") from exc

    raw_results = resp.json().get("results", [])
    _log_raw("tinyfish_search", q, t0, output=json.dumps(raw_results), success=True, error=None, meta=meta)

    results = raw_results[:_MAX_SEARCH_RESULTS]
    articles = [
        {
            "title":     r.get("title", ""),
            "url":       r.get("url", ""),
            "content":   truncate_at_sentence(r.get("snippet") or "", 2000),
            "source_op": "tinyfish_search",
        }
        for r in results
    ]
    # Only cache a non-empty result: a transient empty response shouldn't pin an
    # empty answer for the whole TTL window.
    if articles:
        _cache_put(cache_key, articles)
    return articles


def fetch(urls: list[str], image_links: bool = False, meta: dict | None = None) -> dict[str, dict]:
    """
    TinyFish Fetch — full clean content for up to 10 URLs per call. Returns
    {url: raw_result_dict} keyed by the requested url, UNTRUNCATED. Per-URL
    failures are logged and omitted from the result (TinyFish reports them in
    a separate "errors" list rather than failing the whole request); a total
    request-level failure (network/auth) raises RuntimeError.

    `meta`: see search()'s docstring — same raw-capture contract.
    """
    if not urls:
        return {}
    if _MOCK:
        return {u: {"title": "", "text": f"Mock full content for {u}", "image_links": []} for u in urls}

    batch = urls[:_MAX_FETCH_URLS]
    t0 = time.monotonic()
    try:
        resp = requests.post(
            _FETCH_URL,
            headers={"X-API-Key": _API_KEY, "Content-Type": "application/json"},
            json={"urls": batch, "format": "markdown", "image_links": image_links, "ttl": 0},
            timeout=_FETCH_TIMEOUT_S,
        )
        resp.raise_for_status()
    except Exception as exc:
        _log_raw("tinyfish_fetch", ", ".join(batch), t0, output=None, success=False, error=exc, meta=meta)
        raise RuntimeError(f"TinyFish fetch failed: {exc}") from exc

    data = resp.json()
    _log_raw("tinyfish_fetch", ", ".join(batch), t0, output=json.dumps(data), success=True, error=None, meta=meta)

    out: dict[str, dict] = {r.get("url", ""): r for r in data.get("results", [])}
    for err in data.get("errors", []):
        logger.warning("[tinyfish] fetch failed for %s: %s", err.get("url"), err.get("error"))
    return out


def fetch_as_articles(urls: list[str], meta: dict | None = None) -> list[dict]:
    """
    Fetch full content for known URLs, truncated to the same 2000-char article
    shape search() emits. For the live
    retrieval path only (retrieval_router's extract op) — feeds directly into
    retrieval_validator/source_ranker, so truncation must match today's behavior.
    Not for the ranked-pool full_content capture, which wants untruncated text —
    use fetch() directly for that.
    """
    fetched = fetch(urls, meta=meta)
    articles: list[dict] = []
    for url in urls:
        r = fetched.get(url)
        if not r:
            continue
        articles.append({
            "title":     r.get("title") or "",
            "url":       url,
            "content":   truncate_at_sentence(r.get("text") or "", 2000),
            "source_op": "tinyfish_fetch",
        })
    return articles
