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

        # ── Build intelligence summary ────────────────────────────────────────
        plan = FeedIntelligencePlan(
            project_id=project_id,
            concept_targets=concept_targets,
            core_articles=[],
            curiosity_articles=[],
            intelligence_summary="",  # filled below
            fallback_used=False,
        )
        plan.intelligence_summary = _build_intelligence_summary(
            plan, progression_stage, gap_score
        )

        logger.info(
            "[feed_intelligence] %s stage=%s targets=%s",
            project_id, progression_stage,
            [ct.concept for ct in concept_targets],
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
