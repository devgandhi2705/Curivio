"""
Feed Intelligence Layer — Phase 4.5

Upgrades feed generation from article selection to knowledge selection.

Old pipeline:  keywords → article search → LLM generates whatever fits articles
New pipeline:  learning plan → concept targets → targeted searches → articles serve the plan

How it works
------------
1. Read the LearningPlan (Phase 4.3): what concepts are ready to learn next
2. For each top concept target, generate 2–3 targeted search queries
3. Fetch articles — each article is retrieved because it supports a specific concept
4. Score and rank articles by how well they match the concept targets
5. Return a FeedIntelligencePlan containing:
     - concept_targets  : what to teach today (ordered by readiness)
     - core_articles    : concept-targeted articles for core cards
     - curiosity_articles: article pool for curiosity cards
     - intelligence_summary : prompt injection block

Fallback
--------
If the knowledge graph is empty or plan is unavailable, returns None and the
caller falls back to the existing _fetch_core_articles() behaviour.

Query strategy per concept
--------------------------
  Query 1: news-anchored  — "{domain} {concept} 2025 2026"
  Query 2: depth          — how/why framing, mechanism-level, stage-adapted
  Query 3: example        — named concrete cases (only for strategic/mechanism gaps)

Article budget
--------------
  2 concepts × 2 queries = 4 searches (same count as current pipeline)
  Curiosity articles: 2 searches (same as current)
  Net change: zero extra API calls, significantly better targeting

Public API
----------
  build_feed_intelligence(project_id, project, progression_stage) -> FeedIntelligencePlan | None
  get_intelligence_summary(project_id) -> str
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ── Data types ─────────────────────────────────────────────────────────────────

@dataclass
class ConceptTarget:
    concept:     str
    domain:      str
    gap_type:    str    # concept | mechanism | strategic
    readiness:   float  # 0.0 – 1.0
    queries:     list[str] = field(default_factory=list)
    article_count: int = 0


@dataclass
class FeedIntelligencePlan:
    project_id:          str
    concept_targets:     list[ConceptTarget]
    core_articles:       list[dict]
    curiosity_articles:  list[dict]
    intelligence_summary: str
    fallback_used:       bool = False


# ── Query generation ───────────────────────────────────────────────────────────

_STAGE_DEPTH_MODIFIER: dict[str, str] = {
    "foundation":   "introduction basics explained",
    "mechanisms":   "how it works process mechanism causal chain",
    "dependencies": "dependency risk supply chain fragility upstream",
    "optimization": "efficiency benchmarks competitive dynamics best practice",
    "geopolitical": "geopolitics policy trade implications national strategy",
    "disruption":   "disruption emerging threat startup challenger paradigm",
    "synthesis":    "cross-domain strategy second-order effects future implications",
}

_GAP_TYPE_DEPTH: dict[str, str] = {
    "concept":   "{concept} {domain} explained analysis real-world impact",
    "mechanism": "how {concept} works {domain} process step by step",
    "strategic": "{concept} {domain} strategic implications industry analysis 2025",
}

_GAP_TYPE_EXAMPLE: dict[str, str] = {
    "concept":   "{concept} {domain} example case study company",
    "mechanism": "{concept} {domain} failure success case mechanics",
    "strategic": "{concept} {domain} strategic decision outcome result",
}


def _queries_for_concept(
    concept: str,
    domain: str,
    gap_type: str,
    progression_stage: str,
    n_queries: int = 2,
) -> list[str]:
    """Generate n_queries targeted search queries for a concept."""
    cl = concept.lower()
    dl = domain.lower()

    # Q1: news-anchored (always present)
    q_news = f"{dl} {cl} 2025 2026"

    # Q2: depth — stage-adapted
    stage_mod = _STAGE_DEPTH_MODIFIER.get(progression_stage, "explained analysis")
    depth_template = _GAP_TYPE_DEPTH.get(gap_type, "{concept} {domain} explained")
    q_depth = depth_template.format(concept=cl, domain=dl) + " " + stage_mod[:20]

    if n_queries == 2:
        return [q_news, q_depth]

    # Q3: example (only when 3 queries are requested)
    example_template = _GAP_TYPE_EXAMPLE.get(gap_type, "{concept} {domain} example")
    q_example = example_template.format(concept=cl, domain=dl)
    return [q_news, q_depth, q_example]


def _curiosity_queries_for_orchestrator(briefing) -> list[str]:
    """
    Extract targeted curiosity queries from the CuriosityBriefing.
    Falls back to generic curiosity queries if briefing is unavailable.
    """
    if briefing is None:
        return []
    queries: list[str] = []
    for card in [briefing.card_1, briefing.card_2]:
        if card is None:
            continue
        anchor = card.anchor_concept.lower()
        target = card.target_concept.lower()
        domain = card.domain.lower()
        if anchor and target:
            queries.append(f"{domain} {anchor} {target} history failure mechanism")
        elif anchor:
            queries.append(f"{domain} {anchor} surprising counterintuitive hidden")
    return queries[:2]


# ── Article retrieval ──────────────────────────────────────────────────────────

def _search(query: str) -> list[dict]:
    """Thin wrapper around retrieval_router.route — never raises."""
    try:
        from .retrieval_router import route
        return route(query, mode="feed")
    except Exception as e:
        logger.debug("[feed_intelligence] search failed for %r: %s", query, e)
        return []


def _dedup(articles: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for a in articles:
        url = a.get("url", "")
        if url and url not in seen:
            seen.add(url)
            out.append(a)
        elif not url:
            out.append(a)
    return out


# ── Article scoring ────────────────────────────────────────────────────────────

def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def _score_article(article: dict, concept_targets: list[ConceptTarget]) -> float:
    """
    Score an article by how well it matches the concept targets.
    First target (highest readiness) gets weight 1.0, second 0.6, third 0.3.
    """
    title   = _norm(article.get("title", ""))
    snippet = _norm((article.get("content") or "")[:300])
    text    = f"{title} {snippet}"

    weights = [1.0, 0.6, 0.3]
    score   = 0.0

    for i, ct in enumerate(concept_targets[:3]):
        w = weights[i]
        concept_words = {wd for wd in ct.concept.lower().split() if len(wd) >= 3}
        domain_words  = {wd for wd in ct.domain.lower().split()  if len(wd) >= 3}
        concept_hits  = sum(1 for wd in concept_words if wd in text)
        domain_hits   = 1 if any(wd in text for wd in domain_words) else 0
        if concept_words:
            score += w * (concept_hits / len(concept_words) + 0.1 * domain_hits)

    return score


def _rank_articles(
    articles: list[dict],
    concept_targets: list[ConceptTarget],
) -> list[dict]:
    """Sort articles by relevance to concept targets, highest score first."""
    scored = [(a, _score_article(a, concept_targets)) for a in articles]
    scored.sort(key=lambda x: -x[1])
    return [a for a, _ in scored]


# ── Intelligence summary ───────────────────────────────────────────────────────

def _build_intelligence_summary(
    plan: FeedIntelligencePlan,
    progression_stage: str,
    gap_score: float,
) -> str:
    """Build the prompt injection block describing today's learning intent."""
    if not plan.concept_targets:
        return ""

    primary   = plan.concept_targets[0]
    secondary = plan.concept_targets[1] if len(plan.concept_targets) > 1 else None
    coverage  = round((1.0 - gap_score) * 100) if gap_score <= 1.0 else 0

    lines: list[str] = []
    lines.append("══════════════════════════════════════")
    lines.append("FEED INTELLIGENCE  <- what this feed should teach")
    lines.append("══════════════════════════════════════")

    lines.append(
        f"Primary learning target: {primary.concept} "
        f"[{primary.gap_type}, {primary.domain}, readiness={primary.readiness:.2f}]"
    )
    if secondary:
        lines.append(
            f"Secondary target:        {secondary.concept} "
            f"[{secondary.gap_type}, {secondary.domain}, readiness={secondary.readiness:.2f}]"
        )

    lines.append(f"Stage: {progression_stage.upper()}  |  Domain coverage: {coverage}%")
    lines.append("")
    lines.append("Article intent:")
    for i, ct in enumerate(plan.concept_targets[:3], 1):
        slots = f"article{'s' if ct.article_count > 1 else ''} {2*i-1}{'–'+str(2*i) if ct.article_count > 1 else ''}"
        lines.append(f"  {slots}: retrieved to support '{ct.concept}' — use {ct.article_count} article(s)")

    lines.append("")
    lines.append("Generation mandate:")

    if progression_stage == "foundation":
        lines.append("  Build the mental map. Introduce WHAT and WHY. Assume intelligent newcomer.")
    elif progression_stage == "mechanisms":
        lines.append("  Expose HOW. Every card must show a causal chain, feedback loop, or process logic.")
    elif progression_stage == "dependencies":
        lines.append("  Map what depends on what. Show fragility, upstream risk, hidden prerequisites.")
    elif progression_stage == "optimization":
        lines.append("  Explore efficiency, benchmarks, competitive trade-offs.")
    elif progression_stage == "geopolitical":
        lines.append("  Frame through political economy, regulation, national industrial strategy.")
    elif progression_stage == "disruption":
        lines.append("  What is being disrupted and by what. What changes first?")
    else:  # synthesis
        lines.append("  Cross-domain synthesis, second-order effects, strategic arc.")

    lines.append("")
    lines.append(
        "IMPORTANT: articles are retrieved BECAUSE they support these specific concepts. "
        "Do not let off-topic content in the articles redirect the learning intent. "
        "If an article touches the concept target, extract that angle — not the article's headline."
    )

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def build_feed_intelligence(
    project_id: str,
    project: dict,
    progression_stage: str = "foundation",
    max_concept_targets: int = 2,
) -> "FeedIntelligencePlan | None":
    """
    Build a concept-targeted article retrieval plan for the project.

    Returns None if the knowledge graph is empty (first-time generation) so
    the caller can fall back to the existing keyword-based approach.
    Non-fatal — catches all exceptions and returns None.
    """
    try:
        from .learning_path_planner import plan as build_plan
        from .knowledge_gap_detector import detect_gaps

        lp = build_plan(project_id)

        # No next concepts means the graph isn't populated yet — fall back
        if not lp.next_concepts:
            return None

        gap_report = detect_gaps(project_id)
        gap_score  = gap_report.gap_score

        # ── Select concept targets ────────────────────────────────────────────
        concept_targets: list[ConceptTarget] = [
            ConceptTarget(
                concept=c.label,
                domain=c.domain,
                gap_type=c.gap_type,
                readiness=c.readiness_score,
            )
            for c in lp.next_concepts[:max_concept_targets]
        ]

        # ── Retrieve articles for each concept target ─────────────────────────
        all_core_articles: list[dict] = []
        article_slot = 0

        for ct in concept_targets:
            n_q = 2  # 2 queries per concept — same total as current pipeline
            ct.queries = _queries_for_concept(
                ct.concept, ct.domain, ct.gap_type, progression_stage, n_queries=n_q
            )
            concept_articles: list[dict] = []
            for q in ct.queries:
                concept_articles.extend(_search(q))
            concept_articles = _dedup(concept_articles)
            ct.article_count = len(concept_articles)

            # Tag articles with their concept origin for slot tracking
            for a in concept_articles:
                a["_concept_target"] = ct.concept
            all_core_articles.extend(concept_articles)

        # ── Rank and deduplicate core articles ────────────────────────────────
        core_articles = _dedup(all_core_articles)
        core_articles = _rank_articles(core_articles, concept_targets)

        # ── Curiosity articles: driven by orchestrator targets ────────────────
        curiosity_articles: list[dict] = []
        try:
            from .curiosity_orchestrator import orchestrate
            briefing = orchestrate(project_id)
            curiosity_queries = _curiosity_queries_for_orchestrator(briefing)
            for q in curiosity_queries:
                curiosity_articles.extend(_search(q))
            curiosity_articles = _dedup(curiosity_articles)
        except Exception:
            pass  # curiosity articles are optional

        if not curiosity_articles:
            # Generic fallback curiosity search
            kw = " ".join((project.get("keywords") or [])[:2]) or project.get("name", "")
            curiosity_articles = _search(
                f"{kw} hidden mechanism surprising failure scandal controversy"
            )

        # ── Build intelligence summary ────────────────────────────────────────
        plan = FeedIntelligencePlan(
            project_id=project_id,
            concept_targets=concept_targets,
            core_articles=core_articles,
            curiosity_articles=_dedup(curiosity_articles),
            intelligence_summary="",  # filled below
            fallback_used=False,
        )
        plan.intelligence_summary = _build_intelligence_summary(
            plan, progression_stage, gap_score
        )

        logger.info(
            "[feed_intelligence] %s stage=%s targets=%s core=%d curiosity=%d",
            project_id, progression_stage,
            [ct.concept for ct in concept_targets],
            len(core_articles), len(curiosity_articles),
        )

        return plan

    except Exception:
        logger.exception("[feed_intelligence] build_feed_intelligence failed for %s", project_id)
        return None


def get_intelligence_summary(project_id: str) -> str:
    """
    Standalone prompt string summarising today's learning intent.
    Returns "" if the graph is empty or any error occurs.
    """
    try:
        from .learning_path_planner import plan as build_plan
        from .knowledge_gap_detector import detect_gaps
        from .learning_memory_service import get_memory

        lp = build_plan(project_id)
        if not lp.next_concepts:
            return ""

        gap_report = detect_gaps(project_id)
        mem = get_memory(project_id)
        stage = mem.get("progression_stage", "foundation")

        dummy = FeedIntelligencePlan(
            project_id=project_id,
            concept_targets=[
                ConceptTarget(
                    concept=c.label, domain=c.domain,
                    gap_type=c.gap_type, readiness=c.readiness_score,
                    article_count=2,
                )
                for c in lp.next_concepts[:2]
            ],
            core_articles=[], curiosity_articles=[], intelligence_summary="",
        )
        return _build_intelligence_summary(dummy, stage, gap_report.gap_score)

    except Exception:
        logger.exception("[feed_intelligence] get_intelligence_summary failed for %s", project_id)
        return ""
