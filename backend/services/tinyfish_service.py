"""
TinyFish retrieval layer — Feed's live search/fetch backend, replacing Tavily.

Two TinyFish endpoints:
    search(query)              -> list[dict]  Search API, normalised to the same
                                   shape tavily_service._to_article() produced:
                                   {title, url, content, source_op}. Response field
                                   is "snippet", mapped here to "content".
    fetch(urls, image_links)   -> dict[url, dict]  Fetch API — full clean content
                                   (untruncated) + optional image_links per URL.
                                   Callers decide truncation (see fetch_as_articles()
                                   for the live-pipeline path, which truncates).
    fetch_as_articles(urls)    -> list[dict]  Fetch, normalised + truncated to the
                                   same 2000-char article shape as search() — used
                                   by retrieval_router in place of Tavily's
                                   extract_strategy() for the 6 curated-domain
                                   extract_targets (these feed the live pipeline).

TinyFish Search has no result-count parameter — sliced to _MAX_SEARCH_RESULTS
client-side to match Tavily's max_results=5 default. Neither endpoint consumes
credits (per TinyFish docs).
"""

from __future__ import annotations

import os
import logging
from pathlib import Path

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

_MAX_SEARCH_RESULTS = 5    # matches Tavily's max_results=5 default (no server-side param exists)
_MAX_FETCH_URLS     = 10   # TinyFish Fetch's per-request limit
_SEARCH_TIMEOUT_S   = 30
_FETCH_TIMEOUT_S    = 60   # Fetch renders real JS pages, up to 10 in one request — needs more headroom

logger = logging.getLogger(__name__)


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


def search(query: str, include_domains: list[str] | None = None) -> list[dict]:
    """
    TinyFish Search — normalised article dicts (title, url, content, source_op).
    Never raises for empty results; raises RuntimeError on a request-level failure
    (network/auth) — same contract tavily_service._search_raw() had.

    `include_domains`, when given, scopes results to those domains using
    TinyFish's documented in-query search-operator support (there is no
    separate include_domains request param) — replaces Tavily's
    include_domains for the one live call site that used it (project_service's
    rotating_theme trusted-domain supplementary search).
    """
    if _MOCK:
        return _mock_articles(query)

    q = query
    if include_domains:
        site_ops = " OR ".join(f"site:{d}" for d in include_domains)
        q = f"{query} ({site_ops})"

    try:
        resp = requests.get(
            _SEARCH_URL,
            params={"query": q},
            headers={"X-API-Key": _API_KEY},
            timeout=_SEARCH_TIMEOUT_S,
        )
        resp.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"TinyFish search failed: {exc}") from exc

    results = resp.json().get("results", [])[:_MAX_SEARCH_RESULTS]
    return [
        {
            "title":     r.get("title", ""),
            "url":       r.get("url", ""),
            "content":   truncate_at_sentence(r.get("snippet") or "", 2000),
            "source_op": "tinyfish_search",
        }
        for r in results
    ]


def fetch(urls: list[str], image_links: bool = False) -> dict[str, dict]:
    """
    TinyFish Fetch — full clean content for up to 10 URLs per call. Returns
    {url: raw_result_dict} keyed by the requested url, UNTRUNCATED. Per-URL
    failures are logged and omitted from the result (TinyFish reports them in
    a separate "errors" list rather than failing the whole request); a total
    request-level failure (network/auth) raises RuntimeError.
    """
    if not urls:
        return {}
    if _MOCK:
        return {u: {"title": "", "text": f"Mock full content for {u}", "image_links": []} for u in urls}

    batch = urls[:_MAX_FETCH_URLS]
    try:
        resp = requests.post(
            _FETCH_URL,
            headers={"X-API-Key": _API_KEY, "Content-Type": "application/json"},
            json={"urls": batch, "format": "markdown", "image_links": image_links, "ttl": 0},
            timeout=_FETCH_TIMEOUT_S,
        )
        resp.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"TinyFish fetch failed: {exc}") from exc

    data = resp.json()
    out: dict[str, dict] = {r.get("url", ""): r for r in data.get("results", [])}
    for err in data.get("errors", []):
        logger.warning("[tinyfish] fetch failed for %s: %s", err.get("url"), err.get("error"))
    return out


def fetch_as_articles(urls: list[str]) -> list[dict]:
    """
    Fetch full content for known URLs, truncated to the same 2000-char article
    shape tavily_service._to_article() used for extract() results. For the live
    retrieval path only (retrieval_router's extract op) — feeds directly into
    retrieval_validator/source_ranker, so truncation must match today's behavior.
    Not for the ranked-pool full_content capture, which wants untruncated text —
    use fetch() directly for that.
    """
    fetched = fetch(urls)
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
