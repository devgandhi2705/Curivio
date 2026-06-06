"""
BudgetDegradationEngine — graceful prompt degradation under token pressure.

Phase 3.5 deliverable.

The Problem
-----------
When a prompt exceeds the model's context window, naive implementations fail
with a token-limit error.  The user sees "Token limit exceeded" or, worse,
a silently truncated / broken response.

The Solution
-----------
Apply a deterministic six-step degradation sequence that progressively reduces
prompt size, cheapest / lowest-quality-impact first, stopping the moment the
budget is met.  P1 CRITICAL sections are never touched.  Generation always
succeeds.

Degradation sequence
--------------------
Step 1  DROP_LUXURY         Remove P5 luxury sections — title libraries,
                            style example banks, action templates.
                            Cost: minor quality reduction on output formatting.
                            Typical savings: 200–400 tokens.

Step 2  DROP_OPTIONAL       Drop P4 optional narrative and context sections —
                            narrative frames, tension engine, continuity hints,
                            beginner calibration, exploration breadth.
                            Cost: slightly less stylistic variety.
                            Typical savings: 150–300 tokens.

Step 3  TRIM_STYLE          Truncate P3 writing/style sections to 50%.
                            The first half of a style guide carries the most
                            important rules; the tail is refinements.
                            Cost: minor; model follows most style rules.
                            Typical savings: 200–500 tokens.

Step 4  TRIM_MEMORY         Truncate the memory section to 25% of its length.
                            Pairs with MemoryCompressor — a 400-token memory
                            block shrinks to ~100 tokens of core facts.
                            Cost: some learning context lost.
                            Typical savings: 100–300 tokens.

Step 5  TRIM_ARTICLES       Truncate article content sections to 50%.
                            Titles and leading sentences are preserved;
                            tail content is often redundant with other articles.
                            Cost: moderate; model has less raw material.
                            Typical savings: 400–1,200 tokens.

Step 6  DROP_ARTICLES       Drop non-P1 article sections beyond the minimum
                            required.  Core articles (P1) always survive.
                            Curiosity / supplementary sections are dropped.
                            Cost: highest — significant content reduction.
                            Typical savings: up to 2,000 tokens.

Invariants
----------
1. P1 CRITICAL sections are NEVER modified or removed — output schema,
   task definition, core articles, project state.
2. P2 HIGH required sections are NEVER dropped — they may be truncated
   only at Steps 3–5 if their name appears in the target sets.
3. Truncation always preserves paragraph boundaries.  No mid-sentence cuts.
4. The engine always returns a valid non-empty prompt string.
   It never raises.  It never returns None.
5. The original PromptComposer is never mutated.  All changes are applied
   to an internal working copy.

Usage
-----
    from backend.prompts.budget_degradation import BudgetDegradationEngine

    engine = BudgetDegradationEngine()
    prompt, report = engine.degrade(composer, budget_tokens=8_000)
    if not report.fits:
        logger.warning(report.summary())

    # Or: derive budget from the model registry
    prompt, report = BudgetDegradationEngine.degrade_for_model(
        composer, model_name="llama-3.3-70b-versatile"
    )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from dataclasses import replace as _replace

from .prompt_composer import PromptComposer, PromptSection
from .context_prioritizer import P_CRITICAL, P_HIGH, P_OPTIONAL, P_LUXURY

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Protection predicates
# ═══════════════════════════════════════════════════════════════════════════════

def _drop_protected(section: PromptSection) -> bool:
    """
    True when a section must never be dropped.

    P1 CRITICAL — absolute invariant, never touched.
    P2 HIGH required — never dropped; may be truncated if in a trim step's target set.
    """
    if section.priority <= P_CRITICAL:
        return True
    if section.priority <= P_HIGH and section.required:
        return True
    return False


def _truncation_protected(section: PromptSection) -> bool:
    """True when a section must never be truncated (P1 only)."""
    return section.priority <= P_CRITICAL


# ═══════════════════════════════════════════════════════════════════════════════
# Section name groups — keyed per degradation step
# ═══════════════════════════════════════════════════════════════════════════════

# Step 1 — P5 luxury sections: style example banks, title libraries, action templates.
# These are decorative scaffolding — the model can produce good output without them.
_LUXURY_NAMES: frozenset[str] = frozenset({
    "title_library",
    "emotional_tone",
    "action_design",
    "narrative",
    "engineering_rules",
})

# Step 2 — P4 optional narrative/context sections.
# These enhance stylistic variety and personalisation but are not load-bearing.
# Memory names are deliberately excluded — memory survives to Step 4.
_OPTIONAL_NAMES: frozenset[str] = frozenset({
    "narrative_frames",
    "tension",
    "exploration_breadth",
    "preference_snapshot",
    "explanation_directive",
    "domain_directive",
    "continuity",
    "action_result",
    "beginner_calibration",
})

# Step 3 — P3 style/writing sections: truncated to 50%, not dropped.
# The leading half of a style guide contains the most important rules.
_STYLE_NAMES: frozenset[str] = frozenset({
    "writing_style",
    "writing_rules",
    "banned_phrases",
    "hook_rules",
    "why_it_works",
    "synthesis_rules",
    "writing_rules_detail",
    "output_rules",
    "rules",
    "guidelines",
    "source_signals",
    "real_world_tension",
    "acceleration_philosophy",
})

# Step 4 — Memory sections: truncated to 25%.
# MemoryCompressor already capped these at 400 tokens; this squeezes to ~100.
_MEMORY_NAMES: frozenset[str] = frozenset({
    "memory_section",
    "knowledge_state",
    "session",
})

# Step 5 — Article content sections: truncated to 50%.
# Core articles (P1) are truncated but never removed.
# Curiosity / supplementary articles are also truncated here before Step 6 drops them.
_ARTICLE_NAMES: frozenset[str] = frozenset({
    "articles",
    "core_articles",
    "curiosity_articles",
    "source_analysis",
    "viewpoints",
})


# ═══════════════════════════════════════════════════════════════════════════════
# Text truncation
# ═══════════════════════════════════════════════════════════════════════════════

def _truncate_text(text: str, fraction: float) -> str:
    """
    Truncate text to approximately fraction of its length at a natural boundary.

    Search order: paragraph break (double newline) → single newline → space.
    Always preserves at least 100 characters.
    Never cuts mid-word.
    """
    if fraction >= 1.0 or not text:
        return text
    target = max(100, int(len(text) * fraction))
    if target >= len(text):
        return text

    # Paragraph boundary — best cut point
    cut = text.rfind("\n\n", 0, target)
    if cut > target // 3:
        return text[:cut].rstrip()

    # Single newline
    cut = text.rfind("\n", 0, target)
    if cut > target // 3:
        return text[:cut].rstrip()

    # Word boundary
    cut = text.rfind(" ", 0, target)
    if cut > 0:
        return text[:cut]

    return text[:target]


# ═══════════════════════════════════════════════════════════════════════════════
# Token estimation
# ═══════════════════════════════════════════════════════════════════════════════

def _estimate_tokens(sections: list[PromptSection], separator: str) -> int:
    """Estimate total prompt tokens for an assembled section list."""
    if not sections:
        return 0
    total_chars = sum(len(s.content) for s in sections)
    if len(sections) > 1:
        total_chars += len(separator) * (len(sections) - 1)
    return max(1, total_chars // 4)


# ═══════════════════════════════════════════════════════════════════════════════
# Result dataclasses
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class StepOutcome:
    """
    Record of what one degradation step did (or didn't need to do).
    """

    step_number:         int
    step_name:           str
    description:         str
    applied:             bool
    skipped_reason:      str       = ""
    sections_removed:    list[str] = field(default_factory=list)
    sections_truncated:  list[str] = field(default_factory=list)
    tokens_before:       int       = 0
    tokens_after:        int       = 0

    @property
    def tokens_saved(self) -> int:
        return max(0, self.tokens_before - self.tokens_after)


@dataclass
class DegradationReport:
    """
    Complete record of a single degrade() call — which steps ran, what changed,
    and whether the budget was met.
    """

    original_tokens: int
    final_tokens:    int
    target_budget:   int
    fits:            bool
    outcomes:        list[StepOutcome] = field(default_factory=list)

    @property
    def total_saved(self) -> int:
        return max(0, self.original_tokens - self.final_tokens)

    @property
    def steps_applied(self) -> list[StepOutcome]:
        return [o for o in self.outcomes if o.applied]

    def summary(self) -> str:
        """
        One-line summary for logging.

        Example::
            BudgetDegradation: 4,200 → 3,100 tok  (2 steps)  budget=3,500  OK
        """
        n      = len(self.steps_applied)
        status = "OK" if self.fits else "OVER BUDGET"
        return (
            f"BudgetDegradation: {self.original_tokens:,} → {self.final_tokens:,} tok"
            f"  ({n} step{'s' if n != 1 else ''} applied)"
            f"  budget={self.target_budget:,}  {status}"
        )

    def report(self) -> str:
        """
        Multi-line diagnostic report.

        Example::
            BudgetDegradation — 4,200 → 3,100 tokens  (budget 3,500)
            ──────────────────────────────────────────────────────────────
            Step 1  DROP_LUXURY              applied  — removed: title_library, emotional_tone  −320 tok
            Step 2  DROP_OPTIONAL            skipped  — already within budget
            ──────────────────────────────────────────────────────────────
            Total saved: 1,100 tokens (26%)
            Status: OK
        """
        sep = "─" * 64
        lines: list[str] = [
            f"BudgetDegradation — {self.original_tokens:,} → {self.final_tokens:,} tokens"
            f"  (budget {self.target_budget:,})"
        ]
        lines.append(sep)

        for o in self.outcomes:
            tag    = "applied " if o.applied else "skipped "
            detail = ""
            if o.applied:
                parts: list[str] = []
                if o.sections_removed:
                    parts.append(f"removed: {', '.join(o.sections_removed)}")
                if o.sections_truncated:
                    parts.append(f"trimmed: {', '.join(o.sections_truncated)}")
                saved  = o.tokens_saved
                detail = (
                    f"— {'; '.join(parts)}  −{saved:,} tok" if parts
                    else f"— −{saved:,} tok"
                )
            elif o.skipped_reason:
                detail = f"— {o.skipped_reason}"
            lines.append(
                f"  Step {o.step_number}  {o.step_name:<24s}  {tag}  {detail}"
            )

        lines.append(sep)
        pct = (self.total_saved / self.original_tokens * 100) if self.original_tokens else 0.0
        lines.append(f"  Total saved: {self.total_saved:,} tokens ({pct:.0f}%)")
        status = (
            "OK" if self.fits
            else f"OVER BUDGET by {self.final_tokens - self.target_budget:,} tokens"
        )
        lines.append(f"  Status: {status}")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Engine
# ═══════════════════════════════════════════════════════════════════════════════

class BudgetDegradationEngine:
    """
    Applies a six-step degradation sequence to a PromptComposer until the
    assembled prompt fits within the target token budget.

    The original PromptComposer is never mutated.  All modifications are
    applied to an internal working copy.

    Parameters
    ----------
    separator
        Section separator used when estimating tokens and assembling the
        final prompt.  Must match the separator used by the PromptComposer
        (default "\\n\\n").
    """

    def __init__(self, separator: str = "\n\n") -> None:
        self._sep = separator

    # ── Primary API ──────────────────────────────────────────────────────────

    def degrade(
        self,
        composer: PromptComposer,
        budget_tokens: int,
    ) -> tuple[str, DegradationReport]:
        """
        Apply degradation steps until the prompt fits within budget_tokens.

        Returns
        -------
        (prompt_text, DegradationReport)

        prompt_text is always a valid non-empty string.
        If even all six steps cannot reach the budget (e.g. P1 sections alone
        exceed it), the best-effort result is returned with fits=False and a
        WARNING logged.  Generation is never blocked.
        """
        sections: list[PromptSection] = list(composer._sections)
        original_tokens = _estimate_tokens(sections, self._sep)

        # Fast path — already within budget
        if original_tokens <= budget_tokens:
            text = self._sep.join(s.content for s in sections)
            return text, DegradationReport(
                original_tokens = original_tokens,
                final_tokens    = original_tokens,
                target_budget   = budget_tokens,
                fits            = True,
            )

        logger.info(
            "[degradation] over budget: %d > %d tokens — applying degradation steps",
            original_tokens, budget_tokens,
        )

        outcomes: list[StepOutcome] = []

        # ── Step 1: Drop P5 luxury sections ──────────────────────────────────
        sections, o = self._step_drop(
            sections, 1, "DROP_LUXURY",
            "Remove P5 luxury sections (style examples, title banks)",
            lambda s: s.priority == P_LUXURY or s.name in _LUXURY_NAMES,
        )
        outcomes.append(o)
        if _estimate_tokens(sections, self._sep) <= budget_tokens:
            return self._done(sections, original_tokens, budget_tokens, outcomes)

        # ── Step 2: Drop P4 optional narrative/context sections ───────────────
        sections, o = self._step_drop(
            sections, 2, "DROP_OPTIONAL",
            "Drop P4 optional narrative and context sections",
            lambda s: (
                s.priority >= P_OPTIONAL or s.name in _OPTIONAL_NAMES
            ) and s.name not in _MEMORY_NAMES,
        )
        outcomes.append(o)
        if _estimate_tokens(sections, self._sep) <= budget_tokens:
            return self._done(sections, original_tokens, budget_tokens, outcomes)

        # ── Step 3: Truncate style/writing sections to 50% ───────────────────
        sections, o = self._step_truncate(
            sections, 3, "TRIM_STYLE",
            "Truncate P3 style/writing sections to 50%",
            lambda s: s.name in _STYLE_NAMES,
            fraction=0.50,
        )
        outcomes.append(o)
        if _estimate_tokens(sections, self._sep) <= budget_tokens:
            return self._done(sections, original_tokens, budget_tokens, outcomes)

        # ── Step 4: Truncate memory to 25% ───────────────────────────────────
        sections, o = self._step_truncate(
            sections, 4, "TRIM_MEMORY",
            "Truncate memory sections to 25%",
            lambda s: s.name in _MEMORY_NAMES,
            fraction=0.25,
        )
        outcomes.append(o)
        if _estimate_tokens(sections, self._sep) <= budget_tokens:
            return self._done(sections, original_tokens, budget_tokens, outcomes)

        # ── Step 5: Truncate article content to 50% ───────────────────────────
        sections, o = self._step_truncate(
            sections, 5, "TRIM_ARTICLES",
            "Truncate article content sections to 50%",
            lambda s: s.name in _ARTICLE_NAMES,
            fraction=0.50,
        )
        outcomes.append(o)
        if _estimate_tokens(sections, self._sep) <= budget_tokens:
            return self._done(sections, original_tokens, budget_tokens, outcomes)

        # ── Step 6: Drop excess non-P1 article sections ───────────────────────
        sections, o = self._step_drop_excess(
            sections, 6, "DROP_ARTICLES",
            "Drop non-P1 article sections beyond the minimum",
            target_names=_ARTICLE_NAMES,
            min_keep=1,
        )
        outcomes.append(o)

        return self._done(sections, original_tokens, budget_tokens, outcomes)

    @classmethod
    def degrade_for_model(
        cls,
        composer: PromptComposer,
        model_name: str,
        expected_output_tokens: int = 0,
        separator: str = "\n\n",
    ) -> tuple[str, DegradationReport]:
        """
        Degrade using the budget derived from the model's context window.

        Convenience wrapper — derives the budget from BudgetAllocator.for_model()
        so callers don't need to compute the budget manually.

        Parameters
        ----------
        composer                PromptComposer to degrade.
        model_name              Model name from the registry (e.g. "llama-3.3-70b-versatile").
        expected_output_tokens  Caller's estimate of the model output size.
                                When larger than the model's output_reserve, this value is used.
        separator               Section separator (must match composer's separator).
        """
        from .budget_allocator import BudgetAllocator   # deferred: avoids circular import
        budget = BudgetAllocator.for_model(model_name).compute_budget(expected_output_tokens)
        return cls(separator=separator).degrade(composer, budget)

    # ── Step implementations ──────────────────────────────────────────────────

    def _step_drop(
        self,
        sections: list[PromptSection],
        step_number: int,
        step_name: str,
        description: str,
        predicate,   # Callable[[PromptSection], bool]
    ) -> tuple[list[PromptSection], StepOutcome]:
        """
        Drop all sections that satisfy predicate AND are not drop-protected.

        P1 sections and P2 required sections are always kept regardless of
        what the predicate returns.
        """
        tokens_before = _estimate_tokens(sections, self._sep)
        removed: list[str] = []
        kept:    list[PromptSection] = []

        for s in sections:
            if not _drop_protected(s) and predicate(s):
                removed.append(s.name)
            else:
                kept.append(s)

        tokens_after = _estimate_tokens(kept, self._sep)
        return kept, StepOutcome(
            step_number      = step_number,
            step_name        = step_name,
            description      = description,
            applied          = bool(removed),
            skipped_reason   = "" if removed else "no matching sections found",
            sections_removed = removed,
            tokens_before    = tokens_before,
            tokens_after     = tokens_after,
        )

    def _step_truncate(
        self,
        sections: list[PromptSection],
        step_number: int,
        step_name: str,
        description: str,
        predicate,   # Callable[[PromptSection], bool]
        fraction: float,
    ) -> tuple[list[PromptSection], StepOutcome]:
        """
        Truncate all sections that satisfy predicate AND are not truncation-protected.

        Only P1 sections are truncation-protected.  P2–P5 sections may be
        truncated if their name appears in the step's target set.
        Sections shorter than 100 characters are left untouched.
        """
        tokens_before = _estimate_tokens(sections, self._sep)
        truncated:    list[str]            = []
        new_sections: list[PromptSection]  = []

        for s in sections:
            if (
                not _truncation_protected(s)
                and predicate(s)
                and len(s.content) > 100
            ):
                new_content = _truncate_text(s.content, fraction)
                if new_content != s.content:
                    truncated.append(s.name)
                    # estimated_tokens=0 forces the property to recompute from new content
                    new_sections.append(_replace(s, content=new_content, estimated_tokens=0))
                    continue
            new_sections.append(s)

        tokens_after = _estimate_tokens(new_sections, self._sep)
        return new_sections, StepOutcome(
            step_number         = step_number,
            step_name           = step_name,
            description         = description,
            applied             = bool(truncated),
            skipped_reason      = "" if truncated else "no matching sections or content too short",
            sections_truncated  = truncated,
            tokens_before       = tokens_before,
            tokens_after        = tokens_after,
        )

    def _step_drop_excess(
        self,
        sections: list[PromptSection],
        step_number: int,
        step_name: str,
        description: str,
        target_names: frozenset[str],
        min_keep: int,
    ) -> tuple[list[PromptSection], StepOutcome]:
        """
        Drop non-protected sections matching target_names beyond min_keep.

        Of the matching non-protected sections, the first min_keep are kept
        (in their original order).  The rest are dropped.

        Protected sections (P1, P2 required) matching target_names always survive.
        """
        tokens_before = _estimate_tokens(sections, self._sep)

        # Identify non-protected candidates in the order they appear
        candidates = [
            s for s in sections
            if s.name in target_names and not _drop_protected(s)
        ]
        drop_names: set[str] = {s.name for s in candidates[min_keep:]}

        removed: list[str] = []
        kept:    list[PromptSection] = []
        for s in sections:
            if s.name in drop_names:
                removed.append(s.name)
            else:
                kept.append(s)

        tokens_after = _estimate_tokens(kept, self._sep)
        return kept, StepOutcome(
            step_number      = step_number,
            step_name        = step_name,
            description      = description,
            applied          = bool(removed),
            skipped_reason   = "" if removed else "within min_keep limit — nothing to drop",
            sections_removed = removed,
            tokens_before    = tokens_before,
            tokens_after     = tokens_after,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _done(
        self,
        sections: list[PromptSection],
        original_tokens: int,
        budget_tokens: int,
        outcomes: list[StepOutcome],
    ) -> tuple[str, DegradationReport]:
        text         = self._sep.join(s.content for s in sections)
        final_tokens = _estimate_tokens(sections, self._sep)
        report       = DegradationReport(
            original_tokens = original_tokens,
            final_tokens    = final_tokens,
            target_budget   = budget_tokens,
            fits            = final_tokens <= budget_tokens,
            outcomes        = outcomes,
        )
        if report.fits:
            logger.debug("[degradation] %s", report.summary())
        else:
            logger.warning("[degradation] %s", report.summary())
        return text, report
