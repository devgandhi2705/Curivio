"""
Autonomous deep-dive research workflow for the AI learning agent.

When a topic becomes "important" (user liked it, or it has been seen frequently),
this service performs multi-angle Tavily searches, ranks the results, and calls
Groq to generate a structured deep-dive: related concepts, implementation ideas,
practical applications, and advanced follow-up topics.

Workflow architecture
---------------------
DeepResearchWorkflow is a six-stage pipeline.  Each stage is a separate method
that reads from and writes to self.state, making it independently testable:

  Stage 1 — expand_queries  :  build multiple search angles from the topic title
  Stage 2 — fetch_articles  :  Tavily searches across all query angles (cached)
  Stage 3 — rank_articles   :  quality-filter, score, and deduplicate results
  Stage 4 — extract_viewpoints : source_analyzer + viewpoint_extractor pre-analysis
  Stage 5 — generate        :  Groq call → structured JSON analysis
  Stage 6 — persist         :  upsert result into the deep_research DB table

Each stage method above is unchanged and still independently callable/testable
(see tests/test_deep_research.py). Chat-4.2: run() no longer chains stages 1-3
as a fixed one-shot sequence — it runs them as a plan->act->replan LangGraph
subgraph instead (_run_research_act_subgraph below), so a thin first pass (an
obscure topic starving rank_articles' min_score=0.1 filter) gets one bounded
retry with broadened query angles before falling through to stage 4 with
whatever it found. Stages 4-6 stay exactly the linear chain they always were —
forcing a replan loop around deterministic synthesis steps is theater, not
correctness (recon finding, Chat-4 recon).

Public API
----------
DeepResearchWorkflow(topic)    — workflow class; call run() or individual stages
is_important_topic(topic)      — True if topic qualifies for deep research
get_stored_research(topic)     — retrieve cached result (None if missing/expired)
list_research_topics(limit)    — list stored topics newest-first
run_deep_research(topic)       — convenience: cache check + full workflow
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import TypedDict

from langgraph.graph import StateGraph, END

from ..utils.db import get_connection, get_preference
from ..prompts.deep_research_prompt import build_deep_research_prompt

logger = logging.getLogger(__name__)

# Target survivor count after ranking — also the thin-coverage threshold that
# triggers a replan (real existing number, not invented: this was already
# rank_articles' top_n default before Chat-4.2).
_TARGET_ARTICLE_COUNT = 6

# Bounds the plan->act->replan subgraph: 1 initial attempt + at most 1 replan.
# Small and explicit per Chat-4.2's constraint — no unbounded loop.
_MAX_RESEARCH_ATTEMPTS = 2

# Real min_domains value already used by project_service.py's feed-mode
# rank_articles calls for primary/core content (used twice there — the main
# core_articles call and its own thin-result retry-fallback); deep_research's
# role matches "core" content, not the lighter "curiosity" slot which uses 3.
_DEEP_RESEARCH_MIN_DOMAINS = 4

# ── Configuration ──────────────────────────────────────────────────────────────

from ..config import (
    DEEP_RESEARCH_TTL_HOURS,
    DEEP_RESEARCH_SEARCH_COUNT,
    DEEP_RESEARCH_LIKE_THRESHOLD      as IMPORTANCE_LIKE_THRESHOLD,
    DEEP_RESEARCH_SCORE_THRESHOLD     as IMPORTANCE_SCORE_THRESHOLD,
    DEEP_RESEARCH_RECOMMEND_THRESHOLD as IMPORTANCE_RECOMMEND_THRESHOLD,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Workflow class
# ═══════════════════════════════════════════════════════════════════════════════

class DeepResearchWorkflow:
    """
    Autonomous deep-dive research pipeline.

    Each stage transforms self.state and returns self so stages can be chained
    fluently or called individually for testing.

    State keys
    ----------
    topic            str            The research topic (set at __init__)
    queries          list[str]      Search queries expanded from the topic
    articles         list[dict]     Fetched + ranked articles
    source_analysis  dict           Signal extraction from source_analyzer
    viewpoints       dict           Multi-angle viewpoint analysis
    result           dict           Structured analysis from Groq
    research_id      int | None     DB row id after persist
    """

    STAGES = (
        "expand_queries",
        "fetch_articles",
        "rank_articles",
        "extract_viewpoints",
        "generate",
        "persist",
    )

    def __init__(self, topic: str) -> None:
        self.topic = topic
        self.state: dict = {
            "topic":           topic,
            "queries":         [],
            "articles":        [],
            "source_analysis": {},
            "viewpoints":      {},
            "result":          {},
            "research_id":     None,
        }

    # ── Stage 1 ───────────────────────────────────────────────────────────────

    def expand_queries(self) -> "DeepResearchWorkflow":
        """Build multiple search angles from the topic title."""
        self.state["queries"] = _expand_queries(self.topic)
        return self

    # ── Stage 2 ───────────────────────────────────────────────────────────────

    def fetch_articles(self) -> "DeepResearchWorkflow":
        """Search Tavily for each query angle, merging and deduplicating URLs."""
        self.state["articles"] = _fetch_research_articles(self.state["queries"])
        return self

    # ── Stage 3 ───────────────────────────────────────────────────────────────

    def rank_articles(self) -> "DeepResearchWorkflow":
        """Quality-filter, score, and trim articles to the top 6."""
        self.state["articles"] = _rank_research_articles(
            self.state["articles"], self.topic
        )
        return self

    # ── Stage 4 ───────────────────────────────────────────────────────────────

    def extract_viewpoints(self) -> "DeepResearchWorkflow":
        """
        Run multi-angle pre-analysis: source_analyzer + viewpoint_extractor.

        Populates state["source_analysis"] and state["viewpoints"] so that
        the generate stage has a rich analytical scaffold rather than raw text.
        Errors here are non-fatal — generation falls back to raw articles.
        """
        articles = self.state["articles"]
        try:
            from .source_analyzer import analyze_sources
            from .retrieval_router import multi_classify
            domain = multi_classify(self.topic).primary.domain_key
            self.state["source_analysis"] = analyze_sources(articles, self.topic, domain=domain)
        except Exception:
            logger.warning("[deep_research] source_analyzer failed (non-fatal)")
            self.state["source_analysis"] = {}

        try:
            from .viewpoint_extractor import extract_viewpoints
            self.state["viewpoints"] = extract_viewpoints(articles, self.topic)
        except Exception:
            logger.warning("[deep_research] viewpoint_extractor failed (non-fatal)")
            self.state["viewpoints"] = {}

        return self

    # ── Stage 5 ───────────────────────────────────────────────────────────────

    def generate(self) -> "DeepResearchWorkflow":
        """Call Groq and parse the structured JSON analysis."""
        self.state["result"] = _generate_analysis(
            self.topic,
            self.state["articles"],
            self.state.get("source_analysis", {}),
            self.state.get("viewpoints", {}),
            project_id=self.state.get("project_id", ""),
        )
        return self

    # ── Stage 6 ───────────────────────────────────────────────────────────────

    def persist(self) -> "DeepResearchWorkflow":
        """Upsert the result into the deep_research table."""
        self.state["research_id"] = _store_research(self.topic, self.state["result"])
        return self

    # ── Runner ────────────────────────────────────────────────────────────────

    def run(self) -> dict:
        """
        Execute the full pipeline and return the result dict.

        Chat-4.2: stages 1-3 (expand_queries/fetch_articles/rank_articles) run
        as the plan->act->replan subgraph instead of a fixed one-shot chain —
        see _run_research_act_subgraph(). The individual stage methods above
        are unchanged and still independently callable (tests call them
        directly); this only changes what run() does with them. Stages 4-6
        are unchanged, called linearly exactly as before.
        """
        self.state["queries"], self.state["articles"] = _run_research_act_subgraph(self.topic)
        for stage in self.STAGES[3:]:
            getattr(self, stage)()
        return self.state["result"]


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def is_important_topic(topic: str) -> bool:
    """
    Return True if a topic qualifies for autonomous deep research.

    A topic is important when the user has:
    - explicitly liked it at least once, OR
    - built up a strong positive preference score, OR
    - been recommended it enough times to warrant deeper coverage.

    Thresholds are configurable via env vars (DEEP_RESEARCH_*_THRESHOLD).
    """
    pref = get_preference(topic)
    if pref is None:
        return False
    return (
        pref["times_liked"]      >= IMPORTANCE_LIKE_THRESHOLD      or
        pref["preference_score"] >= IMPORTANCE_SCORE_THRESHOLD     or
        pref["times_recommended"] >= IMPORTANCE_RECOMMEND_THRESHOLD
    )


def get_stored_research(topic: str) -> dict | None:
    """
    Return stored deep research for a topic if it exists and hasn't expired.

    Expiry is governed by DEEP_RESEARCH_TTL_HOURS (default 48 h).
    Returns None on a miss or if the stored entry is stale.
    """
    topic_key = _topic_key(topic)
    cutoff    = datetime.now(timezone.utc) - timedelta(hours=DEEP_RESEARCH_TTL_HOURS)

    with get_connection() as conn:
        row = conn.execute(
            "SELECT research_json, generated_at FROM deep_research WHERE topic_key = ?",
            (topic_key,),
        ).fetchone()

    if row is None:
        return None
    if _parse_ts(row["generated_at"]) < cutoff:
        return None

    return json.loads(row["research_json"])


def list_research_topics(limit: int = 20) -> list[dict]:
    """Return stored research entries newest-first (id, topic, generated_at)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, topic, generated_at FROM deep_research ORDER BY generated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def run_deep_research(topic: str, project_id: str = "") -> dict:
    """
    Return deep research for a topic, running the full workflow on a cache miss.

    Always checks get_stored_research() first so that repeated calls — including
    those from background auto-triggers — are not expensive.

    project_id: optional — when present, injects shared learning context so the
                research builds on what the user has already learned (Phase 4.6).
    """
    cached = get_stored_research(topic)
    if cached is not None:
        logger.info("[deep_research] cache hit for topic %r", topic)
        return cached

    logger.info("[deep_research] starting workflow for topic %r", topic)
    wf = DeepResearchWorkflow(topic)
    if project_id:
        wf.state["project_id"] = project_id
    return wf.run()


# ═══════════════════════════════════════════════════════════════════════════════
# Stage implementations (internal, exposed for testing)
# ═══════════════════════════════════════════════════════════════════════════════

def _expand_queries(topic: str) -> list[str]:
    """
    Build domain-aware search queries for deep research via the expansion engine.

    Returns up to DEEP_RESEARCH_SEARCH_COUNT + 1 queries ordered by retrieval
    priority (primary topic first, authority/trusted-source queries next).
    """
    try:
        from .query_expansion_engine import get_query_strings
        queries = get_query_strings(topic.strip(), mode="deep_research")
        return queries[: DEEP_RESEARCH_SEARCH_COUNT + 1]
    except Exception:
        logger.warning("[deep_research] query expansion failed; using generic fallback")
        base = topic.strip()
        return [
            base,
            f"{base} architecture implementation guide",
            f"{base} practical applications use cases tutorial",
        ][: DEEP_RESEARCH_SEARCH_COUNT + 1]


def _fetch_research_articles(queries: list[str]) -> list[dict]:
    """
    Retrieve articles across all query angles via the retrieval router.

    Passes the domain-expanded queries as overrides so the router handles
    Tavily operation selection (search + extract for trusted sources) without
    re-expanding the topic into new queries.
    """
    from .retrieval_router import route

    topic = queries[0] if queries else ""
    return route(
        topic,
        mode             = "deep_research",
        override_queries = queries,
    )


def _rank_research_articles(
    articles: list[dict], topic: str, top_n: int = _TARGET_ARTICLE_COUNT,
) -> list[dict]:
    """Rank and deduplicate articles using domain-aware deep_research scoring."""
    from .source_ranker import rank_articles  # deferred to avoid circular
    from .retrieval_router import multi_classify

    domain = multi_classify(topic).primary.domain_key
    return rank_articles(articles, query=topic, top_n=top_n, min_score=0.1,
                         domain=domain, mode="deep_research",
                         min_domains=_DEEP_RESEARCH_MIN_DOMAINS)


# ═══════════════════════════════════════════════════════════════════════════════
# Plan -> act -> replan subgraph (stages 1-3, Chat-4.2)
# ═══════════════════════════════════════════════════════════════════════════════
#
# act reuses _expand_queries / _fetch_research_articles / _rank_research_articles
# unchanged above — this only adds a bounded retry loop around them, it does not
# rewrite their logic. Stages 4-6 (extract_viewpoints/generate/persist) are not
# part of this graph; DeepResearchWorkflow.run() calls them linearly afterward.

def _broaden_queries(topic: str) -> list[str]:
    """
    Replan-only query set — genuinely different angles from _expand_queries().

    query_expansion_engine's domain-angle tables already cap out at the
    deep_research query budget (6) on the FIRST call for every known domain
    (confirmed: each of ai/technology/finance/pharma/manufacturing/
    export_trade/business has exactly 6 angles; "default" has 3, still under
    budget) — calling _expand_queries() again would return the identical
    list. If 6 targeted domain-angle queries already came up thin, the real
    gap is that the query language itself is too narrow — broader, plainer
    phrasing is a genuinely different second attempt, not a rewrite of the
    angle-template engine.
    """
    base = topic.strip()
    return [
        f"{base} explained",
        f"{base} overview introduction",
        f"{base} recent developments",
    ]


class _ActState(TypedDict):
    topic:        str
    queries:      list[str]
    raw_articles: list[dict]   # accumulated pre-rank articles across attempts
    ranked:       list[dict]   # latest rank_articles() output
    attempt:      int


def _plan_node(state: _ActState) -> dict:
    topic = state["topic"]
    queries = _expand_queries(topic) if state["attempt"] == 0 else _broaden_queries(topic)
    return {"queries": queries}


def _act_node(state: _ActState) -> dict:
    new_raw      = _fetch_research_articles(state["queries"])
    combined_raw = state["raw_articles"] + new_raw
    ranked       = _rank_research_articles(combined_raw, state["topic"])
    return {"raw_articles": combined_raw, "ranked": ranked, "attempt": state["attempt"] + 1}


def _should_replan(state: _ActState) -> str:
    thin = len(state["ranked"]) < _TARGET_ARTICLE_COUNT
    if thin and state["attempt"] < _MAX_RESEARCH_ATTEMPTS:
        logger.info(
            "[deep_research] thin coverage (%d/%d articles) after attempt %d — replanning",
            len(state["ranked"]), _TARGET_ARTICLE_COUNT, state["attempt"],
        )
        return "plan"
    return END


_act_graph = StateGraph(_ActState)
_act_graph.add_node("plan", _plan_node)
_act_graph.add_node("act", _act_node)
_act_graph.set_entry_point("plan")
_act_graph.add_edge("plan", "act")
_act_graph.add_conditional_edges("act", _should_replan, {"plan": "plan", END: END})
_compiled_act_graph = _act_graph.compile()


def _run_research_act_subgraph(topic: str) -> tuple[list[str], list[dict]]:
    """Run the plan->act->replan subgraph; returns (last queries used, ranked articles)."""
    result = _compiled_act_graph.invoke({
        "topic": topic, "queries": [], "raw_articles": [], "ranked": [], "attempt": 0,
    })
    return result["queries"], result["ranked"]


def _generate_analysis(
    topic: str,
    articles: list[dict],
    source_analysis: dict | None = None,
    viewpoints: dict | None = None,
    project_id: str = "",
) -> dict:
    """
    Call Groq with the upgraded three-persona deep research prompt.

    Incorporates source_analysis and viewpoints pre-processing so the LLM
    reasons across sources rather than summarising each article separately.
    Adds metadata fields and guarantees all required keys exist.
    """
    from .grok_service import ask_grok
    from .source_analyzer    import format_analysis_for_prompt
    from .viewpoint_extractor import format_viewpoints_for_prompt

    formatted_articles  = _format_articles(articles)
    formatted_source    = format_analysis_for_prompt(source_analysis or {})
    formatted_viewpoints = format_viewpoints_for_prompt(viewpoints or {})

    # Phase 4.6: load shared learning context when project_id is available
    shared_context: str = ""
    if project_id:
        try:
            from .shared_learning_context import get_shared_prompt_block
            shared_context = get_shared_prompt_block(project_id, mode="deep_research")
        except Exception:
            logger.debug("[deep_research] shared_learning_context unavailable (non-fatal)")

    prompt = build_deep_research_prompt(
        topic              = topic,
        source_count       = len(articles),
        source_analysis    = formatted_source,
        viewpoint_analysis = formatted_viewpoints,
        articles           = formatted_articles,
        shared_context     = shared_context or None,
    )

    # ── Token budget instrumentation (diagnostics only, non-fatal) ───────────
    try:
        from .token_budget import estimate_tokens, estimate_total_request, BudgetReport, log_budget_report
        from .model_registry import get_model_config
        from ..config import GROQ_MODEL as _MODEL_DR
        _cfg_dr        = get_model_config(_MODEL_DR)
        _articles_tok  = estimate_tokens(formatted_articles)
        _source_tok    = estimate_tokens(formatted_source)
        _viewpts_tok   = estimate_tokens(formatted_viewpoints)
        _total_dr      = estimate_total_request(prompt=prompt)
        _base_tok      = max(0, _total_dr - _articles_tok - _source_tok - _viewpts_tok)
        _remain_dr     = _cfg_dr.prompt_budget - _total_dr
        log_budget_report(BudgetReport(
            operation        = f"deep_research/{topic[:40]}",
            model_name       = _MODEL_DR,
            context_window   = _cfg_dr.context_window,
            safe_budget      = _cfg_dr.prompt_budget,
            output_reserve   = _cfg_dr.output_budget,
            prompt_tokens    = _total_dr,
            remaining_budget = _remain_dr,
            utilization_pct  = (_total_dr / _cfg_dr.prompt_budget * 100) if _cfg_dr.prompt_budget > 0 else 0.0,
            sections         = {
                "articles":         _articles_tok,
                "source_analysis":  _source_tok,
                "viewpoints":       _viewpts_tok,
                "prompt_base":      _base_tok,
            },
            warnings = [
                f"OVER SAFE BUDGET: {_total_dr:,} > {_cfg_dr.prompt_budget:,}"
            ] if _remain_dr < 0 else [],
        ), logger)
    except Exception:
        logger.debug("[deep_research] budget instrumentation failed (non-fatal)", exc_info=True)

    raw    = ask_grok(prompt)
    result = _parse_json_response(raw)

    # Guarantee backward-compatible fields exist
    result.setdefault("related_concepts",       [])
    result.setdefault("implementation_ideas",   [])
    result.setdefault("practical_applications", [])
    result.setdefault("advanced_follow_ups",    [])
    result.setdefault("research_summary",       "")

    # Guarantee new fields exist (empty defaults are safe for callers)
    result.setdefault("key_findings",           [])
    result.setdefault("viewpoint_comparison",   [])
    result.setdefault("trends_identified",      [])
    result.setdefault("tradeoffs",              [])
    result.setdefault("strategic_implications", [])
    result.setdefault("open_questions",         [])
    result.setdefault("confidence_level",       "medium")

    # Inject metadata
    result["topic"]        = topic
    result["sources"]      = [a["url"] for a in articles if a.get("url")]
    result["generated_at"] = datetime.now(timezone.utc).isoformat()

    return result


def _store_research(topic: str, result: dict) -> int:
    """Upsert the result dict for a topic; return the DB row id."""
    key = _topic_key(topic)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO deep_research (topic, topic_key, research_json, generated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(topic_key) DO UPDATE SET
                topic         = excluded.topic,
                research_json = excluded.research_json,
                generated_at  = CURRENT_TIMESTAMP
            """,
            (topic, key, json.dumps(result)),
        )
        row = conn.execute(
            "SELECT id FROM deep_research WHERE topic_key = ?", (key,)
        ).fetchone()
    return row["id"]


# ═══════════════════════════════════════════════════════════════════════════════
# Private helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _topic_key(topic: str) -> str:
    return topic.strip().lower()


def _format_articles(articles: list[dict]) -> str:
    if not articles:
        return "(no articles retrieved)"
    lines = []
    for i, a in enumerate(articles, start=1):
        lines.append(f"{i}. {a['title']}\n   URL: {a['url']}\n   {a['content']}")
    return "\n\n".join(lines)


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
        f"Raw output (first 300 chars): {cleaned[:300]}"
    )


def _parse_ts(value: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Unrecognised timestamp format: {value!r}")
