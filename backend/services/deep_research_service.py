"""
Autonomous deep-dive research workflow for the AI learning agent.

When a topic becomes "important" (user liked it, or it has been seen frequently),
this service performs multi-angle Tavily searches, ranks the results, and calls
Groq to generate a structured deep-dive: related concepts, implementation ideas,
practical applications, and advanced follow-up topics.

Workflow architecture
---------------------
DeepResearchWorkflow is a five-stage pipeline.  Each stage is a separate method
that reads from and writes to self.state, making it independently testable:

  Stage 1 — expand_queries  :  build multiple search angles from the topic title
  Stage 2 — fetch_articles  :  Tavily searches across all query angles (cached)
  Stage 3 — rank_articles   :  quality-filter, score, and deduplicate results
  Stage 4 — generate        :  Groq call → structured JSON analysis
  Stage 5 — persist         :  upsert result into the deep_research DB table

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

from ..utils.db import get_connection, get_preference
from ..prompts.deep_research_prompt import DEEP_RESEARCH_PROMPT

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────

DEEP_RESEARCH_TTL_HOURS: int  = int(os.getenv("DEEP_RESEARCH_TTL_HOURS",       "48"))
DEEP_RESEARCH_SEARCH_COUNT    = int(os.getenv("DEEP_RESEARCH_SEARCH_COUNT",    "2"))
IMPORTANCE_LIKE_THRESHOLD     = int(os.getenv("DEEP_RESEARCH_LIKE_THRESHOLD",  "1"))
IMPORTANCE_SCORE_THRESHOLD    = float(os.getenv("DEEP_RESEARCH_SCORE_THRESHOLD", "0.5"))
IMPORTANCE_RECOMMEND_THRESHOLD = int(os.getenv("DEEP_RESEARCH_RECOMMEND_THRESHOLD", "3"))


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
        )
        return self

    # ── Stage 6 ───────────────────────────────────────────────────────────────

    def persist(self) -> "DeepResearchWorkflow":
        """Upsert the result into the deep_research table."""
        self.state["research_id"] = _store_research(self.topic, self.state["result"])
        return self

    # ── Runner ────────────────────────────────────────────────────────────────

    def run(self) -> dict:
        """Execute all stages in order and return the result dict."""
        for stage in self.STAGES:
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


def run_deep_research(topic: str) -> dict:
    """
    Return deep research for a topic, running the full workflow on a cache miss.

    Always checks get_stored_research() first so that repeated calls — including
    those from background auto-triggers — are not expensive.
    """
    cached = get_stored_research(topic)
    if cached is not None:
        logger.info("[deep_research] cache hit for topic %r", topic)
        return cached

    logger.info("[deep_research] starting workflow for topic %r", topic)
    return DeepResearchWorkflow(topic).run()


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


def _rank_research_articles(articles: list[dict], topic: str, top_n: int = 6) -> list[dict]:
    """Rank and deduplicate articles using domain-aware deep_research scoring."""
    from .source_ranker import rank_articles  # deferred to avoid circular
    from .retrieval_router import multi_classify

    domain = multi_classify(topic).primary.domain_key
    return rank_articles(articles, query=topic, top_n=top_n, min_score=0.1,
                         domain=domain, mode="deep_research")


def _generate_analysis(
    topic: str,
    articles: list[dict],
    source_analysis: dict | None = None,
    viewpoints: dict | None = None,
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

    prompt = DEEP_RESEARCH_PROMPT.format(
        topic              = topic,
        articles           = formatted_articles,
        source_count       = len(articles),
        source_analysis    = formatted_source,
        viewpoint_analysis = formatted_viewpoints,
    )

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
