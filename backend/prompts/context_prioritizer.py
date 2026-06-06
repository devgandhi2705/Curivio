"""
ContextPrioritizer — ranks every prompt section by importance.

Phase 3.1 deliverable.  This module is purely observational: it does NOT
modify, remove, or reorder sections.  It gives the system a vocabulary for
understanding what matters most — in preparation for Phase 3.2's budget-aware
assembly.

Priority scale
--------------
  P1  CRITICAL   — user request, output schema, task definition.
                   Never dropped under any budget.
  P2  HIGH       — core editorial / quality rules, learning framework.
                   Dropped only under extreme budget pressure.
  P3  USEFUL     — writing standards, source analysis, personalization rules.
                   Dropped when moderate budget pressure requires it.
  P4  OPTIONAL   — memory, continuity, session context.
                   Dropped when budget is tight.
  P5  LUXURY     — style libraries, narrative examples, action templates.
                   Dropped first.

Section-name hints
------------------
SECTION_PRIORITY_HINTS maps common section names to their expected priority so
that future tooling can verify assignments are semantically correct.

Usage
-----
    from backend.prompts.context_prioritizer import ContextPrioritizer
    from backend.prompts.project_insight_prompt import make_daily_package_prompt

    # The composer already has sections with priorities attached.
    # Build the report before calling composer.build().
    report = ContextPrioritizer.from_composer(composer).report()
    prompt = composer.build()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .prompt_composer import PromptComposer, PromptSection


# ── Priority constants ─────────────────────────────────────────────────────────

P_CRITICAL = 1   # user request · output schema · task definition
P_HIGH     = 2   # core editorial rules · quality framework
P_USEFUL   = 3   # article content · source analysis · writing standards
P_OPTIONAL = 4   # memory · continuity · session context
P_LUXURY   = 5   # style libraries · narrative examples · action templates

ALL_PRIORITIES = (P_CRITICAL, P_HIGH, P_USEFUL, P_OPTIONAL, P_LUXURY)

TIER_LABELS: dict[int, str] = {
    P_CRITICAL: "CRITICAL",
    P_HIGH:     "HIGH",
    P_USEFUL:   "USEFUL",
    P_OPTIONAL: "OPTIONAL",
    P_LUXURY:   "LUXURY",
}

TIER_DESCRIPTIONS: dict[int, str] = {
    P_CRITICAL: "user request, output schema, task definition — never trimmed",
    P_HIGH:     "core editorial and quality rules — trimmed only under extreme budget pressure",
    P_USEFUL:   "article content, source analysis, writing standards — trimmed under moderate pressure",
    P_OPTIONAL: "memory, continuity, session context — trimmed when budget is tight",
    P_LUXURY:   "style libraries, narrative examples, action templates — trimmed first",
}

# ── Section-name priority hints ────────────────────────────────────────────────

SECTION_PRIORITY_HINTS: dict[str, int] = {
    # P1 — CRITICAL
    "persona":              P_CRITICAL,
    "personas":             P_CRITICAL,
    "intro":                P_CRITICAL,
    "output_schema":        P_CRITICAL,
    "schema":               P_CRITICAL,
    "format_schema":        P_CRITICAL,
    "topic_input":          P_CRITICAL,
    "learner_profile":      P_CRITICAL,
    "articles":             P_CRITICAL,
    "core_articles":        P_CRITICAL,
    "content_input":        P_CRITICAL,
    "user_state":           P_CRITICAL,
    "project_state":        P_CRITICAL,
    "user_profile":         P_CRITICAL,
    "user_interests":       P_CRITICAL,
    "industry_focus":       P_CRITICAL,
    "context_input":        P_CRITICAL,

    # P2 — HIGH
    "schema_intro":         P_HIGH,
    "output_preamble":      P_HIGH,
    "writing_rules":        P_HIGH,
    "url_rule":             P_HIGH,
    "hard_rules":           P_HIGH,
    "editorial_philosophy": P_HIGH,
    "beginner_calibration": P_HIGH,
    "depth":                P_HIGH,
    "learning_system":      P_HIGH,
    "layman_directive":     P_HIGH,
    "task_intro":           P_HIGH,
    "section1_instructions":P_HIGH,
    "curiosity_instructions":P_HIGH,
    "curiosity_articles":   P_HIGH,

    # P3 — USEFUL
    "source_analysis":      P_USEFUL,
    "viewpoints":           P_USEFUL,
    "tier_requirements":    P_USEFUL,
    "per_concept":          P_USEFUL,
    "personalization_rules":P_USEFUL,
    "output_rules":         P_USEFUL,
    "field_requirements":   P_USEFUL,
    "rules":                P_USEFUL,
    "writing_style":        P_USEFUL,
    "banned_phrases":       P_USEFUL,
    "synthesis_rules":      P_USEFUL,
    "writing_rules_detail": P_USEFUL,
    "source_signals":       P_USEFUL,
    "real_world_tension":   P_USEFUL,
    "hook_rules":           P_USEFUL,
    "why_it_works":         P_USEFUL,
    "acceleration_philosophy": P_USEFUL,
    "guidelines":           P_USEFUL,
    "format_directive":     P_USEFUL,

    # P4 — OPTIONAL
    "memory_section":       P_OPTIONAL,
    "continuity":           P_OPTIONAL,
    "conversation_memory":  P_OPTIONAL,
    "knowledge_state":      P_OPTIONAL,
    "session":              P_OPTIONAL,
    "exploration_breadth":  P_OPTIONAL,
    "preference_snapshot":  P_OPTIONAL,
    "explanation_directive":P_OPTIONAL,
    "domain_directive":     P_OPTIONAL,
    "action_result":        P_OPTIONAL,
    "research":             P_OPTIONAL,
    # learning_trajectory is P1 in feed prompts because it carries the
    # explored-concepts list that shapes the entire day's output.
    "learning_trajectory":  P_CRITICAL,
    "narrative_frames":     P_OPTIONAL,
    "tension":              P_OPTIONAL,

    # P5 — LUXURY
    "title_library":        P_LUXURY,
    "emotional_tone":       P_LUXURY,
    "action_design":        P_LUXURY,
    "narrative":            P_LUXURY,
    "engineering_rules":    P_LUXURY,
}


# ── Per-tier statistics ────────────────────────────────────────────────────────

@dataclass
class TierStats:
    """Aggregated metrics for all sections at a given priority tier."""

    priority: int
    label: str
    description: str
    section_count: int
    total_tokens: int
    required_count: int
    optional_count: int
    section_names: list[str] = field(default_factory=list)
    source_packs: list[str]  = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return self.section_count == 0


# ── Core engine ────────────────────────────────────────────────────────────────

class ContextPrioritizer:
    """
    Ranks and analyses prompt sections by priority tier.

    Accepts a PromptComposer (or a list of PromptSection objects directly).
    All methods are read-only — Phase 3.1 does not trim or reorder anything.

    Example
    -------
        composer = PromptComposer()
        # ... add_section() calls ...
        prioritizer = ContextPrioritizer.from_composer(composer)
        print(prioritizer.report())
        prompt = composer.build()
    """

    def __init__(self, sections: Sequence[PromptSection]) -> None:
        self._sections: list[PromptSection] = list(sections)

    @classmethod
    def from_composer(cls, composer: PromptComposer) -> "ContextPrioritizer":
        """Create a ContextPrioritizer from an assembled PromptComposer."""
        return cls(composer._sections)

    @classmethod
    def from_sections(cls, sections: Sequence[PromptSection]) -> "ContextPrioritizer":
        """Create directly from a list of PromptSection objects."""
        return cls(sections)

    # ── Section access ────────────────────────────────────────────────────────

    def sections_at(self, priority: int) -> list[PromptSection]:
        """Return all sections whose priority equals the given value."""
        return [s for s in self._sections if s.priority == priority]

    def ranked(self) -> list[PromptSection]:
        """Return all sections sorted by priority (lowest number first)."""
        return sorted(self._sections, key=lambda s: (s.priority, s.name))

    # ── Budget analysis ───────────────────────────────────────────────────────

    def total_tokens(self) -> int:
        """Total token estimate across all sections."""
        return sum(s.tokens for s in self._sections)

    def required_tokens(self) -> int:
        """Token estimate for sections marked required=True only."""
        return sum(s.tokens for s in self._sections if s.required)

    def tokens_through(self, max_priority: int) -> int:
        """
        Cumulative tokens for all sections at or above max_priority.

        Useful for pre-planning: 'how many tokens do we need if we include
        everything up to P3 (USEFUL)?'
        """
        return sum(s.tokens for s in self._sections if s.priority <= max_priority)

    # ── Per-tier stats ────────────────────────────────────────────────────────

    def tier_stats(self, priority: int) -> TierStats:
        """Return aggregated statistics for a single priority tier."""
        sections = self.sections_at(priority)
        packs = sorted({s.source_pack for s in sections if s.source_pack})
        return TierStats(
            priority      = priority,
            label         = TIER_LABELS.get(priority, f"P{priority}"),
            description   = TIER_DESCRIPTIONS.get(priority, ""),
            section_count = len(sections),
            total_tokens  = sum(s.tokens for s in sections),
            required_count= sum(1 for s in sections if s.required),
            optional_count= sum(1 for s in sections if not s.required),
            section_names = [s.name for s in sections],
            source_packs  = packs,
        )

    def all_tier_stats(self) -> dict[int, TierStats]:
        """Return TierStats for every priority level (1-5)."""
        return {p: self.tier_stats(p) for p in ALL_PRIORITIES}

    # ── Validation ────────────────────────────────────────────────────────────

    def validate(self) -> list[str]:
        """
        Return a list of advisory warnings about the priority assignments.

        Does NOT raise — purely informational so callers can log or surface
        these in a budget report.
        """
        warnings: list[str] = []

        for section in self._sections:
            hint = SECTION_PRIORITY_HINTS.get(section.name)
            if hint is not None and section.priority != hint:
                warnings.append(
                    f"[{section.name}] assigned P{section.priority} "
                    f"({TIER_LABELS.get(section.priority, '?')}), "
                    f"hint suggests P{hint} "
                    f"({TIER_LABELS.get(hint, '?')})"
                )

        # Required sections at P4+ create a design tension: they are always
        # included NOW (because content is non-empty) but would be candidates
        # for trimming in Phase 3.2's budget-aware assembly.  Surface these so
        # Phase 3.2 can convert them to required=False when appropriate.
        for section in self._sections:
            if section.required and section.priority >= P_OPTIONAL:
                warnings.append(
                    f"[{section.name}] is marked required=True but priority={section.priority} "
                    f"({TIER_LABELS.get(section.priority, '?')}) — "
                    "consider required=False so Phase 3.2 can drop it under budget pressure"
                )

        return warnings

    # ── Human-readable report ─────────────────────────────────────────────────

    def report(self) -> str:
        """
        Return a formatted multi-line report showing the priority distribution.

        Example output::

            ContextPrioritizer — 24 sections · 4,320 tokens
            ──────────────────────────────────────────────────
            P1  CRITICAL   │  5 sections │  1,100 tok │ intro, schema, …
            P2  HIGH       │  6 sections │    900 tok │ editorial_philosophy, …
            P3  USEFUL     │  9 sections │  1,800 tok │ writing_style, …
            P4  OPTIONAL   │  2 sections │    320 tok │ memory_section, continuity
            P5  LUXURY     │  3 sections │    200 tok │ title_library, …
            ──────────────────────────────────────────────────
            CRITICAL + HIGH    2,000 tok   (46%)
            through USEFUL     3,800 tok   (88%)
            Total              4,320 tok
        """
        total = self.total_tokens()
        lines: list[str] = []
        lines.append(f"ContextPrioritizer — {len(self._sections)} sections · {total:,} tokens")
        sep = "─" * 54
        lines.append(sep)

        for p in ALL_PRIORITIES:
            stats = self.tier_stats(p)
            if stats.is_empty:
                continue
            names_preview = ", ".join(stats.section_names[:4])
            if len(stats.section_names) > 4:
                names_preview += f" … +{len(stats.section_names) - 4}"
            pct = (stats.total_tokens / total * 100) if total > 0 else 0.0
            lines.append(
                f"P{p}  {stats.label:<10s}│ {stats.section_count:2d} sections │"
                f" {stats.total_tokens:5,d} tok ({pct:4.0f}%) │ {names_preview}"
            )

        lines.append(sep)

        for cutoff, label in (
            (P_HIGH,     "CRITICAL + HIGH "),
            (P_USEFUL,   "through USEFUL  "),
            (P_OPTIONAL, "through OPTIONAL"),
        ):
            tok = self.tokens_through(cutoff)
            pct = (tok / total * 100) if total > 0 else 0.0
            lines.append(f"  {label}  {tok:5,d} tok  ({pct:.0f}%)")

        lines.append(f"  {'Total':<18s}  {total:5,d} tok")

        warnings = self.validate()
        if warnings:
            lines.append(sep)
            lines.append(f"Warnings ({len(warnings)}):")
            for w in warnings:
                lines.append(f"  ⚠  {w}")

        return "\n".join(lines)

    def __repr__(self) -> str:
        return (
            f"ContextPrioritizer("
            f"{len(self._sections)} sections, "
            f"{self.total_tokens()} tokens, "
            f"P1={len(self.sections_at(1))} "
            f"P2={len(self.sections_at(2))} "
            f"P3={len(self.sections_at(3))} "
            f"P4={len(self.sections_at(4))} "
            f"P5={len(self.sections_at(5))})"
        )
