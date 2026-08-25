"""
Shared Learning Context — Phase 4.6

Unifies Feed, Chat, Explain Simply, and Web Search by assembling a single,
mode-aware context object from the Phase 4 knowledge stack and injecting it
into every mode's system prompt.

What it provides
----------------
  known_concepts    — top graph nodes (what the user has genuinely learned)
  active_domains    — industries currently mapped
  progression_stage — current depth stage (foundation → synthesis)
  coverage_pct      — % of domain knowledge covered (from gap score)
  top_gaps          — highest-priority concepts not yet learned
  open_questions    — curiosity card titles from recent sessions (unresolved)
  strategic_threads — cross-domain connections being tracked (from plan)
  next_concepts     — top 3 ready-to-learn concepts (from planner)

Mode-aware formatting
---------------------
  chat        : "Build on what they know — don't re-explain FDA."
  layman      : "Use these as analogy anchors."
  web_search  : "Frame results to build on this background."
  feed        : Compact reminder of what was previously taught.

Public API
----------
  get_shared_context(project_id) -> SharedLearningContext | None
  get_shared_prompt_block(project_id, mode="normal") -> str
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ── Data type ──────────────────────────────────────────────────────────────────

@dataclass
class SharedLearningContext:
    project_id:        str
    known_concepts:    list[str]  = field(default_factory=list)
    active_domains:    list[str]  = field(default_factory=list)
    progression_stage: str        = "foundation"
    coverage_pct:      int        = 0
    top_gaps:          list[str]  = field(default_factory=list)
    open_questions:    list[str]  = field(default_factory=list)
    strategic_threads: list[str]  = field(default_factory=list)
    next_concepts:     list[str]  = field(default_factory=list)


# ── Open question extraction ───────────────────────────────────────────────────

def _load_open_questions(project_id: str, limit: int = 4) -> list[str]:
    """
    Pull curiosity card titles from the most recent project insights.
    These represent topics the user has encountered but not yet resolved —
    the natural open threads of the learning journey.
    """
    try:
        from .project_service import list_project_insights
        recent = list_project_insights(project_id, limit=3)
        questions: list[str] = []
        seen: set[str] = set()
        for pkg in reversed(recent):
            for card in (pkg.get("curiosity_insights") or []):
                title = (card.get("title") or "").strip()
                if title and title.lower() not in seen:
                    seen.add(title.lower())
                    questions.append(title)
                    if len(questions) >= limit:
                        return questions
        return questions
    except Exception:
        return []


# ── Context assembly ───────────────────────────────────────────────────────────

def get_shared_context(project_id: str) -> SharedLearningContext | None:
    """
    Assemble a SharedLearningContext from the Phase 4 knowledge stack.
    Returns None when the knowledge graph is empty (first-time generation).
    Non-fatal — returns None on any error.
    """
    try:
        from .learning_graph import get_graph
        from .knowledge_gap_detector import detect_gaps
        from .learning_path_planner import plan as build_plan
        from .learning_memory_service import get_memory

        graph = get_graph(project_id)
        nodes = graph.get("nodes", [])

        if not nodes:
            return None

        # Known concepts: non-industry nodes, highest weight, up to 8
        content_nodes = sorted(
            [n for n in nodes if n["node_type"] not in ("industry",)],
            key=lambda n: -n["weight"],
        )
        known_concepts = [n["label"] for n in content_nodes[:8]]

        # Active domains
        active_domains = [n["label"] for n in nodes if n["node_type"] == "industry"]

        # Progression stage from learning memory
        mem = get_memory(project_id)
        stage = mem.get("progression_stage", "foundation")

        # Gap info
        gap_report = detect_gaps(project_id)
        coverage_pct = round((1.0 - gap_report.gap_score) * 100)
        top_gaps = [
            g.label
            for g in (gap_report.missing_concepts + gap_report.missing_mechanisms)
            if g.priority == "high"
        ][:5]

        # Open questions from recent curiosity cards
        open_questions = _load_open_questions(project_id)

        # Strategic threads + next concepts from learning plan
        lp = build_plan(project_id)
        strategic_threads = [ca.label for ca in lp.curiosity_areas[:4]]
        next_concepts     = [c.label for c in lp.next_concepts[:3]]

        return SharedLearningContext(
            project_id=project_id,
            known_concepts=known_concepts,
            active_domains=active_domains,
            progression_stage=stage,
            coverage_pct=coverage_pct,
            top_gaps=top_gaps,
            open_questions=open_questions,
            strategic_threads=strategic_threads,
            next_concepts=next_concepts,
        )

    except Exception:
        logger.exception("[shared_learning_context] get_shared_context failed for %s", project_id)
        return None


# ── Mode-aware formatting ──────────────────────────────────────────────────────

def _fmt_list(items: list[str], bullet: str = "•", max_n: int = 6) -> str:
    return "\n".join(f"  {bullet} {item}" for item in items[:max_n])


def format_for_mode(ctx: SharedLearningContext, mode: str) -> str:
    """
    Return a compact, mode-aware string for prompt injection.
    Each mode gets exactly what it needs — no more.
    """
    known_str = ", ".join(ctx.known_concepts[:6]) if ctx.known_concepts else "none yet"
    domains_str = ", ".join(ctx.active_domains) if ctx.active_domains else "not yet identified"

    if mode == "layman":
        if not ctx.known_concepts:
            return ""
        lines = [
            "ANALOGY ANCHORS  <- connect new ideas to what they already know",
            f"Known concepts to use as bridges:",
            _fmt_list(ctx.known_concepts[:5]),
            "",
            "When explaining a new concept, reference one of these anchors first: "
            "'Remember how [known concept] works? This is the same mechanism, one step upstream.'",
        ]
        return "\n".join(lines)

    elif mode == "web_search":
        lines = [
            f"SEARCH CONTEXT  <- user background for framing results",
            f"Stage: {ctx.progression_stage.upper()}  |  Domains: {domains_str}",
            f"User already knows: {known_str}",
        ]
        if ctx.top_gaps:
            lines.append(f"Currently learning: {', '.join(ctx.top_gaps[:3])}")
        lines.append(
            "Frame search results to build on this background — "
            "skip re-explaining what they know, highlight what they don't."
        )
        return "\n".join(lines)

    else:
        # chat / normal — compact framing
        if not ctx.known_concepts and not ctx.active_domains:
            return ""
        lines = [
            f"PROJECT LEARNING STATE  "
            f"[{ctx.progression_stage.upper()} stage, {ctx.coverage_pct}% coverage]",
            f"Domains: {domains_str}",
            f"Already knows: {known_str}",
        ]
        if ctx.top_gaps:
            lines.append(f"Currently learning: {', '.join(ctx.top_gaps[:3])}")
        if ctx.open_questions:
            lines.append(
                f"Open thread from recent session: \"{ctx.open_questions[0][:80]}\""
            )
        if ctx.strategic_threads:
            lines.append(
                f"Strategic thread: {ctx.strategic_threads[0]}"
            )
        lines += [
            "",
            "Build directly on what they know. Reference known concepts as foundations. "
            "Don't re-introduce them from scratch.",
        ]
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def get_shared_prompt_block(project_id: str, mode: str = "normal") -> str:
    """
    Assemble and format the shared context block for the given mode.
    Returns "" when the graph is empty or any error occurs.
    """
    try:
        ctx = get_shared_context(project_id)
        if ctx is None:
            return ""
        return format_for_mode(ctx, mode)
    except Exception:
        logger.exception("[shared_learning_context] get_shared_prompt_block failed for %s", project_id)
        return ""
