"""
ModelAwareAssembler — model-aware prompt assembly pipeline.

Phase 3.6 deliverable.

The Problem
-----------
Prompt construction across services is currently model-blind.  Every service
builds the same prompt regardless of whether the target model has a 8K or
1M context window.  Small models silently overflow; large models never benefit
from the extra context they can absorb.

The Solution
-----------
One assembler that connects the four existing Phase 3 components into a single
pass:

    Model Registry       → ModelConfig (context_window, safe_utilization …)
          ↓
    Budget Allocator     → per-tier token allocation from ModelConfig
          ↓
    Context Prioritizer  → section analysis and tier validation
          ↓
    Budget Degradation   → graceful compression when over budget
          ↓
    Prompt Composer      → final assembled string

Small model  →  tight budget  →  degradation engine applies early steps
                                  (drops P5/P4, truncates P3)  →  less content
Large model  →  generous budget  →  no degradation  →  full context

No model-specific hacks.  No provider-specific conditionals.  Switching models
requires only a registry entry — all behavior is driven by configuration.

Tier-limit awareness
--------------------
Some providers enforce a per-request token ceiling that is tighter than the
context window (e.g. Groq's free on_demand tier: 12,000 TPM).  When a tier
limit is configured, the assembler uses it as the effective budget ceiling and
surfaces a warning in the AssemblyReport rather than silently overflowing.

Usage
-----
    from backend.prompts.model_aware_assembler import ModelAwareAssembler

    # Minimal — uses model's full prompt budget
    prompt, report = ModelAwareAssembler().assemble(composer, "llama-3.3-70b-versatile")

    # With output size hint (shrinks available prompt budget accordingly)
    prompt, report = ModelAwareAssembler().assemble(
        composer, "llama-3.3-70b-versatile", expected_output_tokens=4_000
    )

    # With explicit tier hint for rate-limited deployments
    prompt, report = ModelAwareAssembler().assemble(
        composer, "llama-3.3-70b-versatile",
        provider_tier="on_demand",          # caps budget to tier TPM limit
    )

    print(report.summary())
    print(report.report())
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .prompt_composer import PromptComposer
from .context_prioritizer import ContextPrioritizer
from .budget_allocator import BudgetAllocator, BudgetAllocation
from .budget_degradation import BudgetDegradationEngine, DegradationReport

logger = logging.getLogger(__name__)

# Re-exported from model_registry to avoid callers needing two imports.
# Applied to provider TPM limits: 87.5% is mid-point of the 85–90% safety target.
# At 12K TPM: effective budget = int(12000 × 0.875) = 10,500 tokens.
_PROVIDER_SAFETY_FACTOR: float = 0.875


# ═══════════════════════════════════════════════════════════════════════════════
# Assembly report
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class AssemblyReport:
    """
    Complete snapshot of one prompt assembly pass.

    Combines model configuration, tier allocation, and degradation
    into a single inspectable record.

    Fields
    ------
    model_name          Model identifier from the registry.
    provider            Provider string ("groq", "openai", "anthropic", "google").
    context_window      Model's full context window in tokens.
    prompt_budget       Available tokens for the prompt (after output reserve and buffer).
    effective_budget    Budget actually used — may be tighter than prompt_budget when
                        a provider tier limit is active (e.g. Groq on_demand TPM).

    section_count       Number of sections in the original PromptComposer.
    original_tokens     Estimated tokens before any degradation.
    final_tokens        Estimated tokens in the assembled prompt.
    utilization_pct     final_tokens / effective_budget × 100.
    fits                True when final_tokens ≤ effective_budget.

    degraded            True when the BudgetDegradationEngine was invoked.
    degradation         Full DegradationReport, or None if no degradation was needed.
    allocation          BudgetAllocation from the adaptive allocator.
    warnings            Any budget, overflow, or tier-limit warnings.
    """

    # ── Model ─────────────────────────────────────────────────────────────────
    model_name:       str
    provider:         str
    context_window:   int
    prompt_budget:    int       # theoretical budget from ModelConfig
    effective_budget: int       # budget actually enforced (may be lower than prompt_budget)

    # ── Sections ──────────────────────────────────────────────────────────────
    section_count:    int
    original_tokens:  int

    # ── Final result ──────────────────────────────────────────────────────────
    final_tokens:     int
    utilization_pct:  float
    fits:             bool

    # ── Degradation ───────────────────────────────────────────────────────────
    degraded:         bool
    degradation:      DegradationReport | None = None

    # ── Allocation ────────────────────────────────────────────────────────────
    allocation:       BudgetAllocation | None = None

    # ── Warnings ──────────────────────────────────────────────────────────────
    warnings:         list[str] = field(default_factory=list)

    # ── Summaries ─────────────────────────────────────────────────────────────

    def summary(self) -> str:
        """
        One-line summary for logging.

        Example::
            [assembly] llama-3.3-70b-versatile  3,200/92,400 tok (3%)  degraded=No  OK
        """
        tag    = "degraded" if self.degraded else "OK"
        status = "OK" if self.fits else "OVER BUDGET"
        return (
            f"[assembly] {self.model_name}"
            f"  {self.final_tokens:,}/{self.effective_budget:,} tok"
            f" ({self.utilization_pct:.0f}%)"
            f"  degraded={'Yes' if self.degraded else 'No'}"
            f"  {status}"
        )

    def report(self) -> str:
        """
        Multi-line diagnostic report.

        Example::
            ModelAwareAssembler — llama-3.3-70b-versatile (groq)
            Context 128,000  |  Budget 92,400  |  Effective 92,400  |  Output reserve 8,000
            ──────────────────────────────────────────────────────────────────
            Sections:  24  |  Original: 4,200 tok  |  Final: 3,800 tok  |  3.6% utilization
            Degraded:  No
            ──────────────────────────────────────────────────────────────────
            P1  CRITICAL    5 sections   1,100 tok  (26%)
            P2  HIGH        6 sections     900 tok  (21%)
            P3  USEFUL      9 sections   1,800 tok  (43%)
            P4  OPTIONAL    2 sections     320 tok  ( 8%)
            P5  LUXURY      2 sections     200 tok  ( 5%)  [will be first to drop]
            ──────────────────────────────────────────────────────────────────
            Status: OK
        """
        sep = "─" * 68
        lines: list[str] = [
            f"ModelAwareAssembler — {self.model_name} ({self.provider})"
        ]

        # Model budget line
        eff_note = (
            f"  |  Effective {self.effective_budget:,}"
            if self.effective_budget != self.prompt_budget
            else ""
        )
        lines.append(
            f"  Context {self.context_window:,}"
            f"  |  Budget {self.prompt_budget:,}"
            f"{eff_note}"
        )
        lines.append(sep)

        # Section summary
        lines.append(
            f"  Sections: {self.section_count:>3}"
            f"  |  Original: {self.original_tokens:,} tok"
            f"  |  Final: {self.final_tokens:,} tok"
            f"  |  {self.utilization_pct:.1f}% utilization"
        )
        lines.append(
            f"  Degraded:  {'Yes — ' + str(len(self.degradation.steps_applied)) + ' step(s) applied' if self.degraded and self.degradation else 'No'}"
        )
        lines.append(sep)

        # Tier distribution (from BudgetAllocation)
        if self.allocation:
            total_tok = self.original_tokens or 1
            from .context_prioritizer import ALL_PRIORITIES
            for p in ALL_PRIORITIES:
                ta = self.allocation.tier_allocations[p]
                if ta.actual_tokens == 0 and ta.allocated_tokens == 0:
                    continue
                n_sec      = len(ta.section_names)
                pct        = ta.actual_tokens / total_tok * 100
                note       = "  [first to drop]" if p == 5 else ""
                status_tag = "" if ta.fits else "  [OVERFLOW]"
                lines.append(
                    f"  P{p}  {ta.label:<10s}"
                    f"  {n_sec:2d} section{'s' if n_sec != 1 else ' '}"
                    f"  {ta.actual_tokens:>6,} tok"
                    f"  ({pct:4.0f}%)"
                    f"{note}{status_tag}"
                )

        lines.append(sep)

        # Warnings
        if self.warnings:
            for w in self.warnings:
                lines.append(f"  WARNING: {w}")
            lines.append(sep)

        # Status
        if self.fits:
            lines.append("  Status: OK")
        else:
            over = self.final_tokens - self.effective_budget
            lines.append(f"  Status: OVER BUDGET by {over:,} tokens")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Assembler
# ═══════════════════════════════════════════════════════════════════════════════

class ModelAwareAssembler:
    """
    Assembles a final prompt from a PromptComposer, adapting automatically to
    the active model's context window.

    The assembler:
    1. Derives available budget from the model registry.
    2. Analyzes section priorities with ContextPrioritizer.
    3. Allocates budget per tier with BudgetAllocator (adaptive).
    4. Applies BudgetDegradationEngine when the prompt exceeds budget.
    5. Returns the assembled prompt and a full AssemblyReport.

    No model-specific hacks.  No provider-specific conditionals.  Adding a new
    model requires only a ModelConfig entry in model_registry.py.

    Parameters
    ----------
    separator
        Section separator (must match the PromptComposer used upstream;
        default "\\n\\n").
    """

    def __init__(self, separator: str = "\n\n") -> None:
        self._sep = separator

    # ── Primary API ──────────────────────────────────────────────────────────

    def assemble(
        self,
        composer: PromptComposer,
        model_name: str,
        expected_output_tokens: int = 0,
        provider_tier: str | None = None,
    ) -> tuple[str, AssemblyReport]:
        """
        Assemble the final prompt for the given model.

        Parameters
        ----------
        composer
            PromptComposer with all sections already added by the calling
            service.  Never mutated.
        model_name
            Model identifier from the registry (e.g. "llama-3.3-70b-versatile").
            Unknown models fall back to conservative defaults.
        expected_output_tokens
            Caller's estimate of how many tokens the model will generate.
            When larger than the model's output_reserve, this takes precedence,
            shrinking the available prompt budget accordingly.
        provider_tier
            Optional tier name from ModelConfig.tier_limits (e.g. "on_demand").
            When provided, the corresponding TPM limit is used as a ceiling on
            the effective budget.  Useful for Groq free-tier deployments.

        Returns
        -------
        (prompt_text, AssemblyReport)
        prompt_text is always a valid non-empty string.
        """
        from ..services.model_registry import get_model_config  # deferred: avoid circular import
        cfg = get_model_config(model_name)

        # ── Step 1: Compute budget ────────────────────────────────────────────
        allocator     = BudgetAllocator(cfg)
        prompt_budget = allocator.compute_budget(expected_output_tokens)

        # Auto-detect provider tier when caller doesn't supply one.
        # Groq models register "on_demand" as their default; non-Groq models
        # leave default_provider_tier=None so their full context window is used.
        active_tier = provider_tier if provider_tier is not None else cfg.default_provider_tier

        # Apply provider-tier TPM ceiling when active
        effective_budget = prompt_budget
        tier_warnings: list[str] = []

        if active_tier:
            tier_config = cfg.tier_limits.get(active_tier, {})
            tpm = tier_config.get("tpm")
            if tpm is not None:
                # Provider TPM is an INPUT-token limit; apply safety factor directly.
                # Do NOT subtract output_reserve — that would double-count it because
                # output_reserve is already excluded from prompt_budget above.
                tier_prompt_cap = int(tpm * _PROVIDER_SAFETY_FACTOR)
                if tier_prompt_cap < effective_budget:
                    effective_budget = max(0, tier_prompt_cap)
                    safety_pct = int(_PROVIDER_SAFETY_FACTOR * 100)
                    tier_warnings.append(
                        f"{cfg.provider!r} {active_tier!r} tier TPM limit ({tpm:,}) is "
                        f"tighter than context-window budget ({prompt_budget:,}) — "
                        f"effective budget capped at {effective_budget:,} tokens "
                        f"({safety_pct}% safety target applied)"
                    )

        # ── Step 2: Analyze sections ──────────────────────────────────────────
        sections       = composer._sections
        prioritizer    = ContextPrioritizer.from_composer(composer)
        original_tokens = composer.estimate_tokens()

        # Adaptive allocation — redistributes surplus from low to high tiers
        allocation = allocator.allocate_adaptive(sections, expected_output_tokens)

        # Collect allocation warnings + prioritizer validation warnings
        all_warnings: list[str] = list(allocation.warnings) + list(tier_warnings)
        pv_warnings = prioritizer.validate()
        if pv_warnings:
            # Only surface unexpected priority assignment warnings; skip "required=True at P4+"
            # noise unless something is genuinely misconfigured
            critical_pv = [w for w in pv_warnings if "CRITICAL" in w or "required" not in w.lower()]
            all_warnings.extend(critical_pv[:3])   # cap noise at 3

        # ── Step 3: Assemble — degrade if over budget ─────────────────────────
        degraded   = False
        degradation: DegradationReport | None = None

        if original_tokens <= effective_budget:
            # Fits as-is — build directly
            prompt_text  = self._sep.join(s.content for s in sections)
            final_tokens = original_tokens
        else:
            # Over budget — apply degradation engine
            engine = BudgetDegradationEngine(separator=self._sep)
            prompt_text, degradation = engine.degrade(composer, effective_budget)
            final_tokens = degradation.final_tokens
            degraded     = True

            # Surface degradation steps as warnings if still over budget
            if not degradation.fits:
                all_warnings.append(
                    f"Degradation could not fully meet the budget: "
                    f"{final_tokens:,} tok remaining after all 6 steps "
                    f"(budget {effective_budget:,} tok). "
                    f"P1 CRITICAL sections alone may exceed budget."
                )

        # ── Step 4: Build report ──────────────────────────────────────────────
        utilization = (final_tokens / effective_budget * 100) if effective_budget else 0.0
        report = AssemblyReport(
            model_name       = cfg.model_name,
            provider         = cfg.provider,
            context_window   = cfg.context_window,
            prompt_budget    = prompt_budget,
            effective_budget = effective_budget,
            section_count    = len(sections),
            original_tokens  = original_tokens,
            final_tokens     = final_tokens,
            utilization_pct  = utilization,
            fits             = final_tokens <= effective_budget,
            degraded         = degraded,
            degradation      = degradation,
            allocation       = allocation,
            warnings         = all_warnings,
        )

        if report.fits:
            logger.debug("[assembler] %s", report.summary())
        else:
            logger.warning("[assembler] %s", report.summary())

        return prompt_text, report

    # ── Convenience classmethod ───────────────────────────────────────────────

    @classmethod
    def build(
        cls,
        composer: PromptComposer,
        model_name: str,
        expected_output_tokens: int = 0,
        provider_tier: str | None = None,
        separator: str = "\n\n",
    ) -> tuple[str, AssemblyReport]:
        """
        Class-level shortcut — no need to instantiate explicitly.

        Equivalent to ModelAwareAssembler(separator).assemble(...).
        """
        return cls(separator=separator).assemble(
            composer,
            model_name,
            expected_output_tokens=expected_output_tokens,
            provider_tier=provider_tier,
        )
