"""
Feed v2 web researcher (Phase 9) — real web search over the day's focus, uncapped
candidate count, governed by a self-loop coverage assessor (cap 3, enforced by
graph.py's existing _web_route), constrained differently per coverage_mode.

FOUR steps per research pass:
  1. QUERY CONSTRUCTION (LLM, web_researcher role) — 3-5 focused search queries from
     the day's focus + keywords + coverage_mode. On a loop re-entry it's told what was
     already found so it diversifies rather than repeating pass 1.
  2. SEARCH + FETCH (no LLM) — a v2-owned DIRECT TinyFish Search client
     (api.search.tinyfish.ai), same "call the API directly, don't import tinyfish_service"
     pattern Phase 4/8 used for FETCH. Uncapped: every useful result is kept; ranking is
     source_ranker's job later. Phase 9b: each result's URL is then FETCHED for full page
     content (api.fetch.tinyfish.ai, batched at 10/request) — a search snippet is ~150
     chars, too thin to extract a real claim from.
  3. CLAIM EXTRACTION (LLM, web_researcher role) — over the FETCHED full content (not the
     snippet), select the results actually supporting the focus and extract the claim.
     Citation metadata (url, title) comes from the RAW search response, never from the
     model — the model is trusted only for the relevance judgment and the extracted claim.
     Phase 9c: the full fetched page is RETAINED on the finding (`content`) alongside the
     claim (`text`) — the claim is a cheap summary, not the only thing downstream sees.
     An oversized page is first shrunk by own-code dedup (`_dedup_content`, no LLM): exact-
     duplicate boilerplate lines removed, then hard-capped only if still oversized.
  4. COVERAGE ASSESSMENT (heuristic, no LLM) — evidence_thin = too few relevant claims
     accumulated. A full "did I find enough?" LLM call each loop is overkill; the count
     of claims that survived extraction is a direct, robust coverage signal and gives
     the loop a real reason to fire (thin → diversified second pass → more claims).

COVERAGE_MODE (the constraint, enforced at QUERY CONSTRUCTION, not prompt-hoped):
  - material_bound: web may only explain concepts PRESENT in the uploaded material.
    Resolved architecturally (Phase 9 design decision): web reads the project's
    material text from the DB directly — NOT corpus_researcher's parallel output,
    which isn't visible in the same super-step (LangGraph fan-in barrier). Queries are
    built from the material and HARD-GATED: a query survives only if it shares a content
    word with the material, so an off-topic query (and thus off-topic results) can never
    be issued even if the model misbehaves.
  - material_anchored: material seeds the queries but does not fence them — expansion
    into related territory is allowed (no gate).
  - open: no material constraint, full latitude.

USER LINKS vs FRESH SEARCH: a user's uploaded link is corpus_researcher's material
(Phase 4/8). This agent only produces NEWLY DISCOVERED sources — any search result whose
url the user already uploaded (v2_materials.url) is dropped, so source_ranker never
double-counts it.

Isolation: imports only feed_v2's own db/provider + requests/stdlib. Never
backend.services.* / backend.llm.*, and does NOT import corpus_researcher (reads the
material from the DB itself).
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import requests
from dotenv import load_dotenv

from ..budget import count_tokens, input_budget, truncate_to_tokens
from ..db import get_connection
from ..llm.provider import AllLegsFailed, call_agent  # noqa: F401  (re-exported for callers)

load_dotenv(dotenv_path=Path(__file__).resolve().parents[4] / ".env")

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://api.search.tinyfish.ai"
_FETCH_URL = "https://api.fetch.tinyfish.ai"
_SEARCH_TIMEOUT_S = 30
_FETCH_TIMEOUT_S = 60      # TinyFish renders real JS pages — needs headroom (matches links.py)
_MOCK = os.getenv("MOCK_RETRIEVAL", "").lower() == "true"

MAX_QUERIES = 5            # distinct search queries per research pass (1 broad + a few angles)
MIN_CLAIMS_FOR_ENOUGH = 3  # fewer accumulated relevant claims than this ⇒ evidence_thin ⇒ loop
_MATERIAL_TEXT_LIMIT = 12  # chunks sampled to define the material_bound topic universe
_MAX_FETCH_URLS = 10       # TinyFish Fetch's per-request URL cap (Phase 4 links.py used the same API)
_EXTRACT_CHARS = 2500      # per-source full-page content fed to extraction (Phase 9b: real content,
                           # not the ~150-char search snippet, while keeping the prompt bounded)

# Phase 9c: the FULL fetched page is retained in state (not just the extracted claim). A page
# that alone exceeds a QUARTER of one ranking call's input budget starves the other sources
# downstream — that's when own-code dedup runs. web_researcher's primary is nemotron-nano-30b,
# so its (smaller) budget sizes the threshold. Tests override this to force dedup cheaply.
_DEDUP_THRESHOLD_TOKENS = input_budget("nemotron-nano-30b") // 4   # ≈ 26.9k tokens ≈ 108KB

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "what", "how", "why",
    "into", "over", "your", "you", "are", "was", "were", "will", "about", "explain",
    "explained", "overview", "introduction", "guide", "learn", "learning", "day",
}

_QUERIES_SCHEMA = {"type": "object", "required": ["queries"],
                   "properties": {"queries": {"type": "array", "items": {"type": "string"}}}}
_CLAIMS_SCHEMA = {"type": "object", "required": ["passages"],
                  "properties": {"passages": {"type": "array", "items": {
                      "type": "object", "properties": {
                          "index": {"type": "integer"},
                          "claim": {"type": "string"},
                          "why_relevant": {"type": "string"}}}}}}

_QUERY_SYSTEM = ("You generate focused web search queries for a learning lesson. "
                 "Return ONLY a JSON object — no prose, no markdown fences.")
_EXTRACT_SYSTEM = ("You are a precise research assistant selecting web results that "
                   "support a lesson's focus. Return ONLY a JSON object — no prose.")


# ── content-word helpers (the material_bound query gate) ──────────────────────
def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) > 3 and w not in _STOPWORDS}


def _norm_url(url: str) -> str:
    """Normalise for dedup: scheme-agnostic host+path, no trailing slash / query."""
    try:
        s = urlsplit(url.strip())
        host = s.netloc.lower().removeprefix("www.")
        return f"{host}{s.path.rstrip('/')}"
    except Exception:
        return (url or "").strip().lower()


# ── DB reads (material universe + user links) ─────────────────────────────────
def _material_text(project_id: str, limit: int = _MATERIAL_TEXT_LIMIT) -> str:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT chunk_text FROM v2_material_chunks WHERE project_id = ? LIMIT ?",
            (project_id, limit),
        ).fetchall()
    return "\n".join(r["chunk_text"] for r in rows if r["chunk_text"])


def _user_link_urls(project_id: str) -> set[str]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT url FROM v2_materials WHERE project_id = ? AND url IS NOT NULL AND url != ''",
            (project_id,),
        ).fetchall()
    return {_norm_url(r["url"]) for r in rows}


# ── the v2-owned direct TinyFish Search client ────────────────────────────────
def _search(query: str) -> list[dict]:
    """One search query -> normalised [{title, url, snippet}]. Uncapped. Non-fatal:
    a search-level failure returns [] (found nothing) — never fake results, never a
    graph-wedging raise (the coverage assessor treats empty as thin and loops)."""
    if _MOCK:
        return [{"title": f"[MOCK] {query} {i}", "url": f"https://mock.example.com/{i}",
                 "snippet": f"Mock snippet for {query} result {i}."} for i in range(3)]
    api_key = os.getenv("TINYFISH_API_KEY", "")
    if not api_key:
        logger.warning("[feed_v2.web] TINYFISH_API_KEY not set — no web search this pass")
        return []
    try:
        resp = requests.get(_SEARCH_URL, params={"query": query},
                            headers={"X-API-Key": api_key}, timeout=_SEARCH_TIMEOUT_S)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001 — infra must not wedge on a search outage
        logger.warning("[feed_v2.web] search failed for %r: %s", query, exc)
        return []
    out = []
    for r in resp.json().get("results", []):
        url = (r.get("url") or "").strip()
        if url:
            out.append({"title": (r.get("title") or "").strip(), "url": url,
                        "snippet": (r.get("snippet") or r.get("content") or "").strip()})
    return out


def _fetch(urls: list[str]) -> dict[str, str]:
    """Full page content (markdown) for URLs, batched at TinyFish's 10-per-request cap
    (multiple POSTs for larger sets). Same v2-owned direct Fetch API links.py uses.
    Returns {url: full_text} keyed by the returned url. Non-fatal: a per-batch failure
    is logged and omitted (extraction falls back to that source's snippet)."""
    if not urls:
        return {}
    if _MOCK:
        return {u: f"Mock full page content for {u}. " * 20 for u in urls}
    api_key = os.getenv("TINYFISH_API_KEY", "")
    if not api_key:
        logger.warning("[feed_v2.web] TINYFISH_API_KEY not set — no fetch, snippet-only extraction")
        return {}
    out: dict[str, str] = {}
    batches = 0
    for start in range(0, len(urls), _MAX_FETCH_URLS):
        batch = urls[start:start + _MAX_FETCH_URLS]
        batches += 1
        try:
            resp = requests.post(
                _FETCH_URL,
                headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                json={"urls": batch, "format": "markdown", "image_links": False, "ttl": 0},
                timeout=_FETCH_TIMEOUT_S,
            )
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001 — infra must not wedge on a fetch outage
            logger.warning("[feed_v2.web] fetch batch failed (%d urls): %s", len(batch), exc)
            continue
        data = resp.json()
        for r in data.get("results", []):
            u = (r.get("url") or "").strip()
            text = (r.get("text") or "").strip()
            if u and text:
                out[u] = text
        for err in data.get("errors", []):
            logger.info("[feed_v2.web] fetch failed for %s: %s", err.get("url"), err.get("error"))
    logger.info("[feed_v2.web] fetched %d/%d url(s) in %d batch(es)", len(out), len(urls), batches)
    return out


def _dedup_content(text: str) -> str:
    """Shrink an OVERSIZED scraped page WITHOUT summarizing (no LLM, no judgment). Runs only
    when the page alone exceeds _DEDUP_THRESHOLD_TOKENS; a normal-sized page is returned
    byte-for-byte untouched.

    Method: drop exact-duplicate non-blank lines (repeated nav/menu/footer/boilerplate that
    survives TinyFish's markdown extraction), keeping the FIRST occurrence and original order
    so no unique content is lost. If exact-line dedup still leaves it oversized, hard-cap the
    length as a last resort."""
    if not text or count_tokens(text) <= _DEDUP_THRESHOLD_TOKENS:
        return text
    seen: set[str] = set()
    kept: list[str] = []
    for line in text.split("\n"):
        key = line.strip()
        if key and key in seen:
            continue                    # exact-duplicate non-blank line → boilerplate, drop
        if key:
            seen.add(key)
        kept.append(line)               # blanks always kept (preserve paragraph structure)
    deduped = "\n".join(kept)
    if count_tokens(deduped) > _DEDUP_THRESHOLD_TOKENS:
        # ponytail: dedup alone didn't shrink it enough (a genuinely long, mostly-unique
        # page — rare). Hard-cap as last resort; raise the threshold if this fires often.
        deduped = truncate_to_tokens(deduped, _DEDUP_THRESHOLD_TOKENS)
    return deduped


# ── step 1: query construction (LLM + material_bound hard gate) ───────────────
def _build_queries(focus: str, keywords, coverage_mode: str, material_text: str,
                   already_found: list[str], meta: dict | None) -> list[str]:
    kw = ", ".join(keywords) if keywords else "(none)"
    if coverage_mode == "material_bound":
        constraint = ("CONSTRAINT: the learner is bound to their uploaded material. Every "
                      "query MUST target a concept that appears in the MATERIAL EXCERPTS "
                      "below. Do NOT introduce topics absent from the material.\n\n"
                      f"MATERIAL EXCERPTS:\n{material_text[:2000] or '(none)'}")
    elif coverage_mode == "material_anchored":
        constraint = ("The uploaded material SEEDS the search but does not fence it — you "
                      "may expand into closely related territory.\n\n"
                      f"MATERIAL EXCERPTS (seed):\n{material_text[:1500] or '(none)'}")
    else:
        constraint = "No material constraint — full latitude on the focus."
    diversify = (f"\nAlready covered (find DIFFERENT angles): {', '.join(already_found[:8])}"
                 if already_found else "")
    prompt = (f"TODAY'S FOCUS:\n{focus or '(general overview)'}\nKeywords: {kw}\n\n"
              f"{constraint}{diversify}\n\n"
              f"Return up to {MAX_QUERIES} distinct web search queries as JSON: "
              '{"queries": ["...", "..."]}.')
    call_meta = {"call_type": "feed_v2_web_queries", "surface": "feed_v2",
                 "agent_name": "web_researcher"}
    call_meta.update(meta or {})
    obj = call_agent("web_researcher", [{"role": "user", "content": prompt}],
                     system=_QUERY_SYSTEM, schema=_QUERIES_SCHEMA, meta=call_meta)
    queries = [q.strip() for q in (obj.get("queries") or []) if isinstance(q, str) and q.strip()]
    queries = queries[:MAX_QUERIES]

    if coverage_mode == "material_bound":
        vocab = _content_words(material_text)
        gated = [q for q in queries if _content_words(q) & vocab]  # HARD gate, not prompt-hope
        dropped = [q for q in queries if q not in gated]
        if dropped:
            logger.info("[feed_v2.web] material_bound gate dropped off-material queries: %s", dropped)
        queries = gated
    return queries


# ── step 3: claim extraction (LLM; citation metadata from raw results) ─────────
def _extract_claims(candidates: list[dict], focus: str, meta: dict | None) -> list[dict]:
    # Phase 9b: extract from the FETCHED full page content (bounded to _EXTRACT_CHARS),
    # falling back to the search snippet only when a fetch failed for that url.
    listing = "\n\n".join(
        f"[{i}] {c['title']}\n{(c.get('content') or c['snippet'])[:_EXTRACT_CHARS]}"
        for i, c in enumerate(candidates))
    prompt = (f"TODAY'S FOCUS:\n{focus or '(general overview)'}\n\n"
              f"WEB RESULTS ({len(candidates)}):\n{listing}\n\n"
              "Select ONLY results that genuinely support today's focus and extract the "
              "supporting claim. Return JSON: "
              '{"passages": [{"index": <result number>, "claim": "<supporting claim in '
              'your words or a quote>", "why_relevant": "<short phrase>"}]}. '
              'If none are relevant, return {"passages": []}.')
    call_meta = {"call_type": "feed_v2_web_extract", "surface": "feed_v2",
                 "agent_name": "web_researcher"}
    call_meta.update(meta or {})
    obj = call_agent("web_researcher", [{"role": "user", "content": prompt}],
                     system=_EXTRACT_SYSTEM, schema=_CLAIMS_SCHEMA, meta=call_meta)
    out = []
    for p in obj.get("passages") or []:
        idx = p.get("index")
        if not isinstance(idx, int) or not (0 <= idx < len(candidates)):
            continue
        c = candidates[idx]
        out.append({
            "src": "web",
            "url": c["url"],            # from the raw search result, NOT the model
            "title": c["title"],        # from the raw search result, NOT the model
            "text": (p.get("claim") or "").strip() or c["snippet"],
            "content": c.get("content") or "",   # Phase 9c: FULL (deduped) page retained, not only the claim
            "why_relevant": (p.get("why_relevant") or "").strip(),
        })
    return out


def run_web_research(*, project_id: str, journey_entry: dict, coverage_mode: str,
                     keywords=None, iteration: int = 1, prior_findings=None,
                     meta: dict | None = None) -> dict:
    """One research pass. Accumulates onto prior_findings (loop iterations are separate
    super-steps, so prior_findings carries pass-1 results into pass 2), dedups by url and
    against the user's uploaded links, and returns evidence_thin for graph.py's _web_route.

    Returns {"web_findings", "web_research_iters", "evidence_thin"} — the SAME state
    keys/shape the Phase-7 stub wrote. Propagates AllLegsFailed if a required LLM leg
    fails (no silent fake findings)."""
    prior_findings = list(prior_findings or [])
    focus = (journey_entry or {}).get("focus") or ""
    material_text = _material_text(project_id) if coverage_mode in ("material_bound", "material_anchored") else ""

    seen_urls = {_norm_url(f["url"]) for f in prior_findings if f.get("url")} | _user_link_urls(project_id)
    already = [f.get("title") or f.get("url") for f in prior_findings]

    queries = _build_queries(focus, keywords, coverage_mode, material_text, already, meta)

    candidates: list[dict] = []
    for q in queries:
        for r in _search(q):                       # uncapped
            nu = _norm_url(r["url"])
            if nu and nu not in seen_urls:
                seen_urls.add(nu)
                candidates.append(r)

    # Phase 9b: fetch full page content for every candidate (uncapped, batched at 10),
    # so extraction reads real content instead of the thin search snippet.
    fetched = _fetch([c["url"] for c in candidates])
    fetched_norm = {_norm_url(u): t for u, t in fetched.items()}
    for c in candidates:
        # Phase 9c: dedup oversized pages here so BOTH extraction and the retained state
        # content are the cleaned full page (normal pages pass through untouched).
        c["content"] = _dedup_content(fetched_norm.get(_norm_url(c["url"]), ""))

    new_findings = _extract_claims(candidates, focus, meta) if candidates else []
    for f in new_findings:
        f["coverage_mode"] = coverage_mode         # tag for later weighting (matches corpus)

    findings = prior_findings + new_findings
    thin = len(findings) < MIN_CLAIMS_FOR_ENOUGH   # coverage assessor (heuristic)
    return {"web_findings": findings, "web_research_iters": iteration, "evidence_thin": thin}


def _demo() -> None:
    """ponytail self-check: material_bound query gate + url dedup + content dedup, no network."""
    global _DEDUP_THRESHOLD_TOKENS
    vocab_text = "Photosynthesis converts light into glucose using chlorophyll in chloroplasts."
    assert _content_words("chlorophyll absorption spectrum") & _content_words(vocab_text)   # on-material
    assert not (_content_words("french revolution bastille 1789") & _content_words(vocab_text))  # off-material
    assert _norm_url("https://www.Example.com/a/") == _norm_url("http://example.com/a")
    # content dedup: normal page untouched; oversized repetitive page loses only duplicates.
    normal = "unique line one\nunique line two"
    assert _dedup_content(normal) == normal                       # under threshold → byte-identical
    saved = _DEDUP_THRESHOLD_TOKENS
    _DEDUP_THRESHOLD_TOKENS = 30    # force dedup: oversized page ~200 tok > 30; deduped ~9 tok < 30 (no hard-cap)
    page = "\n".join(["NAV BOILERPLATE"] * 50 + ["unique A", "unique B", "NAV BOILERPLATE"])
    out = _dedup_content(page)
    _DEDUP_THRESHOLD_TOKENS = saved
    assert out.count("NAV BOILERPLATE") == 1                       # 51 copies → 1
    assert "unique A" in out and "unique B" in out                # no unique content lost
    print("web_researcher._demo OK")


if __name__ == "__main__":
    _demo()
