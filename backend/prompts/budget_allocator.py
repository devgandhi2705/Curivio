"""
BudgetAllocator — dynamic prompt budget computation and tier allocation.

Phase 3.2 deliverable.

Replaces fixed prompt assumptions with model-aware, adaptive budgeting:
  1. Derives the available prompt budget from any ModelConfig — no hardcoded
     values, no provider-specific constants.
  2. Allocates that budget across the five priority tiers using configurable
     weight ratios that match the Curivio content taxonomy.
  3. Redistributes surplus from underutilised tiers back to tiers that need it
     (adaptive reallocation).
  4. Reports what fits, what overflows, and the utilisation percentage.

Formula
-------
  safe_total      = context_window × safe_utilization
  effective_output = max(output_reserve, expected_output_tokens)
  prompt_budget    = safe_total − safety_buffer − effective_output

Default allocation weights (must sum to 1.0)
--------------------------------------------
  P1  CRITICAL   15%   task definition + output schema
  P2  HIGH       20%   core editorial rules + quality framework
  P3  USEFUL     40%   article content + source analysis
  P4  OPTIONAL   15%   memory + continuity + session context
  P5  LUXURY     10%   style libraries + narrative examples

Usage
-----
    from backend.prompts.budget_allocator import BudgetAllocator
    from backend.services.model_registry  import get_model_config

    allocator  = BudgetAllocator(get_model_config("llama-3.3-70b-versatile"))
    allocation = allocator.allocate(composer._sections, expected_output_tokens=4000)
    print(allocation.report())
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Sequence

# ── Local imports ──────────────────────────────────────────────────────────────
# budget_allocator lives in backend/prompts/ alongside prompt_composer and
# context_prioritizer; model_registry lives in backend/services/.
# We import ModelConfig by TYPE only at module level; the actual registry call
# is deferred to BudgetAllocator.for_model() to avoid circular-import issues.

from .prompt_composer import PromptSection
from .context_prioritizer import (
    ALL_PRIORITIES,
    P_CRITICAL, P_HIGH, P_USEFUL, P_OPTIONAL, P_LUXURY,
    TIER_LABELS, TIER_DESCRIPTIONS,
)


# ── Default tier weights ───────────────────────────────────────────────────────

# Maps priority level → fraction of total prompt budget.  Must sum to 1.0.
# These ratios encode the Curivio content taxonomy described in Phase 3.1.
DEFAULT_TIER_WEIGHTS: dict[int, float] = {
    P_CRITICAL: 0.15,   # P1: task definition + output schema
    P_HIGH:     0.20,   # P2: core editorial / quality rules
    P_USEFUL:   0.40,   # P3: article content + source analysis
    P_OPTIONAL: 0.15,   # P4: memory + continuity + session context
    P_LUXURY:   0.10,   # P5: style libraries + narrative examples
}

assert abs(sum(DEFAULT_TIER_WEIGHTS.values()) - 1.0) < 1e-9, \
    "DEFAULT_TIER_WEIGHTS must sum to 1.0"


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class TierAllocation:
    """Budget allocation result for a single priority tier."""

    priority:         int
    label:            str          # CRITICAL | HIGH | USEFUL | OPTIONAL | LUXURY
    description:      str
    weight:           float        # fraction of total budget assigned to this tier
    allocated_tokens: int          # tokens budgeted: total_budget × weight
    actual_tokens:    int          # tokens currently used by sections at this tier
    fits:             bool         # actual_tokens ≤ allocated_tokens
    overflow_tokens:  int          # max(0, actual − allocated)
    headroom_tokens:  int          # max(0, allocated − actual)
    section_names:    list[str] = field(default_factory=list)
    source_packs:     list[str] = field(default_factory=list)

    @property
    def utilization_pct(self) -> float:
        if self.allocated_tokens == 0:
            return 0.0
        return self.actual_tokens / self.allocated_tokens * 100.0


@dataclass
class BudgetAllocation:
    """
    Complete budget allocation snapshot for one prompt assembly.

    Built by BudgetAllocator.allocate() or allocate_adaptive().
    Never modifies prompts — diagnostics and Phase 3.3 input only.
    """

    # ── Model metadata ────────────────────────────────────────────────────────
    model_name:           str
    context_window:       int
    safe_utilization:     float
    output_reserve:       int
    safety_buffer:        int

    # ── Budget arithmetic ─────────────────────────────────────────────────────
    expected_output_tokens: int    # effective output reservation used
    total_budget:           int    # computed available prompt tokens

    # ── Allocation results ────────────────────────────────────────────────────
    tier_allocations:       dict[int, TierAllocation]
    total_actual_tokens:    int    # sum of all section tokens
    total_allocated_tokens: int    # sum of tier allocations (may differ from total_budget
                                   # after adaptive redistribution)
    utilization_pct:        float  # total_actual / total_budget × 100
    fits_within_budget:     bool
    overflow_tokens:        int    # max(0, total_actual − total_budget)
    adaptive:               bool = False   # True when allocate_adaptive() was used
    warnings:               list[str] = field(default_factory=list)

    # ── Convenience accessors ─────────────────────────────────────────────────

    @property
    def headroom_tokens(self) -> int:
        return max(0, self.total_budget - self.total_actual_tokens)

    @property
    def critical_tokens(self) -> int:
        return self.tier_allocations[P_CRITICAL].actual_tokens

    @property
    def luxury_tokens(self) -> int:
        return self.tier_allocations[P_LUXURY].actual_tokens

    def sections_that_overflow(self) -> list[str]:
        """Names of tiers where actual > allocated."""
        return [
            f"P{ta.priority} {ta.label}"
            for ta in self.tier_allocations.values()
            if not ta.fits
        ]

    # ── Report ────────────────────────────────────────────────────────────────

    def report(self) -> str:
        """
        Return a formatted multi-line budget allocation report.

        Example::

            BudgetAllocation — llama-3.3-70b-versatile
            Context 128,000  ×  0.80  −  2,000 (safety)  −  8,000 (output)  =  92,400 budget
            ─────────────────────────────────────────────────────────────────
            P1  CRITICAL  │  15.0% │ alloc  13,860 │ actual  1,200 │  OK  87% headroom
            P2  HIGH      │  20.0% │ alloc  18,480 │ actual  3,100 │  OK  83% headroom
            P3  USEFUL    │  40.0% │ alloc  36,960 │ actual  9,200 │  OK  75% headroom
            P4  OPTIONAL  │  15.0% │ alloc  13,860 │ actual    500 │  OK  96% headroom
            P5  LUXURY    │  10.0% │ alloc   9,240 │ actual  1,600 │  OK  83% headroom
            ─────────────────────────────────────────────────────────────────
            Total actual  15,600 /  92,400  (16.9%)  —  76,800 headroom
        """
        safe_total = int(self.context_window * self.safe_utilization)
        mode_tag = " [adaptive]" if self.adaptive else ""
        lines: list[str] = []
        lines.append(f"BudgetAllocation — {self.model_name}{mode_tag}")
        lines.append(
            f"  Context {self.context_window:>9,}"
            f"  × {self.safe_utilization:.2f}"
            f"  − {self.safety_buffer:,} (safety)"
            f"  − {self.expected_output_tokens:,} (output)"
            f"  =  {self.total_budget:,} budget"
        )
        sep = "─" * 65
        lines.append(sep)

        for p in ALL_PRIORITIES:
            ta = self.tier_allocations[p]
            if ta.actual_tokens == 0 and ta.allocated_tokens == 0:
                continue
            status = "OK " if ta.fits else "OVR"
            if ta.fits:
                detail = f"{ta.headroom_tokens:,} headroom"
            else:
                detail = f"OVERFLOW +{ta.overflow_tokens:,}"
            lines.append(
                f"P{p}  {ta.label:<10s}"
                f" │ {ta.weight*100:4.1f}%"
                f" │ alloc {ta.allocated_tokens:>8,}"
                f" │ actual {ta.actual_tokens:>7,}"
                f" │ {status}  {detail}"
            )

        lines.append(sep)
        util_str = f"{self.utilization_pct:.1f}%"
        budget_status = "OK" if self.fits_within_budget else f"OVER by {self.overflow_tokens:,}"
        lines.append(
            f"  Total actual  {self.total_actual_tokens:>8,}"
            f" / {self.total_budget:>8,}"
            f"  ({util_str:>6})  —  {self.headroom_tokens:,} headroom  [{budget_status}]"
        )

        if self.warnings:
            lines.append(sep)
            for w in self.warnings:
                lines.append(f"  ⚠  {w}")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Core allocator
# ═══════════════════════════════════════════════════════════════════════════════

class BudgetAllocator:
    """
    Computes and allocates the prompt budget for a given model configuration.

    Model-agnostic: derives all limits from ModelConfig — no hardcoded
    provider values.  Works equally for Groq, OpenAI, Anthropic, Google, or
    any future model added to the registry.

    Parameters
    ----------
    model_config    ModelConfig from model_registry (carries context_window,
                    safe_utilization, output_reserve, safety_buffer).
    tier_weights    Allocation fractions per priority tier (must sum to 1.0).
                    Defaults to DEFAULT_TIER_WEIGHTS.
    """

    def __init__(
        self,
        model_config,           # ModelConfig — not type-hinted to avoid circular import
        tier_weights: dict[int, float] | None = None,
    ) -> None:
        self._model   = model_config
        self._weights = tier_weights or DEFAULT_TIER_WEIGHTS
        _validate_weights(self._weights)

    @classmethod
    def for_model(
        cls,
        model_name:   str,
        tier_weights: dict[int, float] | None = None,
    ) -> "BudgetAllocator":
        """Convenience constructor — looks up the model by name."""
        from ..services.model_registry import get_model_config
        return cls(get_model_config(model_name), tier_weights)

    # ── Budget computation ────────────────────────────────────────────────────

    def compute_budget(self, expected_output_tokens: int = 0) -> int:
        """
        Derive available prompt tokens from the model config.

          safe_total       = context_window × safe_utilization
          effective_output = max(output_reserve, expected_output_tokens)
          prompt_budget    = safe_total − safety_buffer − effective_output

        Parameters
        ----------
        expected_output_tokens
            Caller's estimate of how large the model output will be.
            When larger than model_config.output_reserve, this takes precedence
            so the full output fits within the context window.
        """
        safe_total       = int(self._model.context_window * self._model.safe_utilization)
        effective_output = max(self._model.output_reserve, expected_output_tokens)
        return max(0, safe_total - self._model.safety_buffer - effective_output)

    # ── Static allocation ─────────────────────────────────────────────────────

    def allocate(
        self,
        sections: Sequence[PromptSection],
        expected_output_tokens: int = 0,
    ) -> BudgetAllocation:
        """
        Divide the total budget proportionally across priority tiers using the
        configured weights.  Each tier receives exactly weight × total_budget
        tokens regardless of actual usage.

        Use this when you want to understand the base allocation before any
        adaptive redistribution.  For production use, prefer allocate_adaptive().
        """
        total_budget = self.compute_budget(expected_output_tokens)
        tier_allocs  = _build_tier_allocs(sections, self._weights, total_budget)
        return _build_result(self._model, total_budget, expected_output_tokens,
                             tier_allocs, sections, adaptive=False)

    # ── Adaptive allocation ───────────────────────────────────────────────────

    def allocate_adaptive(
        self,
        sections: Sequence[PromptSection],
        expected_output_tokens: int = 0,
    ) -> BudgetAllocation:
        """
        Adaptive allocation: surplus budget from underutilised lower-priority
        tiers cascades upward to higher-priority tiers that need more space.

        Algorithm
        ---------
        Pass 1  — assign each tier its base allocation (weight × total_budget).
        Pass 2  — sweep P5 → P1: if a tier's actual usage is below its allocation,
                  the difference becomes surplus.
        Pass 3  — sweep P1 → P5: distribute surplus to tiers that overflowed,
                  highest priority first.

        This means a large P3 article batch absorbs any headroom from P4/P5
        automatically, without manual tuning.
        """
        total_budget = self.compute_budget(expected_output_tokens)

        # Base allocation
        base: dict[int, int] = {
            p: int(total_budget * self._weights.get(p, 0.0))
            for p in ALL_PRIORITIES
        }

        # Actual usage per tier
        actual: dict[int, int] = {
            p: sum(s.tokens for s in sections if s.priority == p)
            for p in ALL_PRIORITIES
        }

        # Pass 2 — collect surplus from low-priority tiers
        adapted: dict[int, int] = {}
        surplus = 0
        for p in reversed(ALL_PRIORITIES):   # P5 → P1
            used  = actual[p]
            alloc = base[p]
            if used < alloc:
                surplus  += alloc - used
                adapted[p] = used           # tier uses exactly what it needs
            else:
                adapted[p] = alloc          # can't give back what it doesn't have

        # Pass 3 — give surplus to overflowing tiers, P1 first
        for p in ALL_PRIORITIES:            # P1 → P5
            if surplus <= 0:
                break
            deficit = max(0, actual[p] - adapted[p])
            if deficit > 0:
                give       = min(deficit, surplus)
                adapted[p] += give
                surplus    -= give

        tier_allocs = _build_tier_allocs_from_map(sections, adapted, self._weights)
        return _build_result(self._model, total_budget, expected_output_tokens,
                             tier_allocs, sections, adaptive=True)

    # ── Section fitting ───────────────────────────────────────────────────────

    def sections_within_budget(
        self,
        sections: Sequence[PromptSection],
        expected_output_tokens: int = 0,
    ) -> list[PromptSection]:
        """
        Return the subset of sections that fit within the total prompt budget,
        including ALL required sections regardless of budget position.

        Inclusion order: required sections first (sorted P1 → P5), then
        optional sections by priority until the budget is exhausted.

        Note — Phase 3.2 is informational: this method exists so Phase 3.3+
        can call it to actually assemble trimmed prompts.  PromptComposer.build()
        is not yet wired to use it.
        """
        total_budget = self.compute_budget(expected_output_tokens)

        required    = sorted([s for s in sections if s.required],  key=lambda s: s.priority)
        optional    = sorted([s for s in sections if not s.required], key=lambda s: s.priority)

        # Always include all required sections
        included: list[PromptSection] = list(required)
        tokens_used = sum(s.tokens for s in included)

        # Add optional sections greedily, P1→P5
        for section in optional:
            if tokens_used + section.tokens <= total_budget:
                included.append(section)
                tokens_used += section.tokens

        return included


# ═══════════════════════════════════════════════════════════════════════════════
# Private helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _validate_weights(weights: dict[int, float]) -> None:
    total = sum(weights.values())
    if abs(total - 1.0) > 0.01:
        raise ValueError(
            f"Tier weights must sum to 1.0 (got {total:.4f}). "
            f"Adjust values in: {weights}"
        )


def _build_tier_allocs(
    sections: Sequence[PromptSection],
    weights:  dict[int, float],
    total_budget: int,
) -> dict[int, TierAllocation]:
    return {
        p: _make_tier_alloc(
            priority       = p,
            allocated      = int(total_budget * weights.get(p, 0.0)),
            weight         = weights.get(p, 0.0),
            tier_sections  = [s for s in sections if s.priority == p],
        )
        for p in ALL_PRIORITIES
    }


def _build_tier_allocs_from_map(
    sections:   Sequence[PromptSection],
    alloc_map:  dict[int, int],
    weights:    dict[int, float],
) -> dict[int, TierAllocation]:
    return {
        p: _make_tier_alloc(
            priority      = p,
            allocated     = alloc_map.get(p, 0),
            weight        = weights.get(p, 0.0),
            tier_sections = [s for s in sections if s.priority == p],
        )
        for p in ALL_PRIORITIES
    }


def _make_tier_alloc(
    priority:      int,
    allocated:     int,
    weight:        float,
    tier_sections: list[PromptSection],
) -> TierAllocation:
    actual   = sum(s.tokens for s in tier_sections)
    fits     = actual <= allocated
    overflow = max(0, actual - allocated)
    headroom = max(0, allocated - actual)
    packs    = sorted({s.source_pack for s in tier_sections if s.source_pack})
    return TierAllocation(
        priority         = priority,
        label            = TIER_LABELS.get(priority, f"P{priority}"),
        description      = TIER_DESCRIPTIONS.get(priority, ""),
        weight           = weight,
        allocated_tokens = allocated,
        actual_tokens    = actual,
        fits             = fits,
        overflow_tokens  = overflow,
        headroom_tokens  = headroom,
        section_names    = [s.name for s in tier_sections],
        source_packs     = packs,
    )


def _build_result(
    model,
    total_budget:          int,
    expected_output_tokens: int,
    tier_allocs:           dict[int, TierAllocation],
    sections:              Sequence[PromptSection],
    adaptive:              bool,
) -> BudgetAllocation:
    total_actual    = sum(s.tokens for s in sections)
    total_allocated = sum(ta.allocated_tokens for ta in tier_allocs.values())
    utilization     = (total_actual / total_budget * 100.0) if total_budget > 0 else 0.0
    effective_output = max(model.output_reserve, expected_output_tokens)

    warnings: list[str] = []
    if total_actual > total_budget:
        warnings.append(
            f"OVER BUDGET: prompt ({total_actual:,} tok) exceeds available budget "
            f"({total_budget:,} tok) by {total_actual - total_budget:,} tokens"
        )
    elif utilization > 85.0:
        warnings.append(
            f"HIGH UTILIZATION: {utilization:.1f}% of prompt budget consumed"
        )

    for ta in tier_allocs.values():
        if not ta.fits:
            warnings.append(
                f"P{ta.priority} {ta.label}: actual {ta.actual_tokens:,} tok "
                f"exceeds allocation {ta.allocated_tokens:,} tok "
                f"(+{ta.overflow_tokens:,} overflow)"
            )

    return BudgetAllocation(
        model_name             = model.model_name,
        context_window         = model.context_window,
        safe_utilization       = model.safe_utilization,
        output_reserve         = model.output_reserve,
        safety_buffer          = model.safety_buffer,
        expected_output_tokens = effective_output,
        total_budget           = total_budget,
        tier_allocations       = tier_allocs,
        total_actual_tokens    = total_actual,
        total_allocated_tokens = total_allocated,
        utilization_pct        = utilization,
        fits_within_budget     = total_actual <= total_budget,
        overflow_tokens        = max(0, total_actual - total_budget),
        adaptive               = adaptive,
        warnings               = warnings,
    )
