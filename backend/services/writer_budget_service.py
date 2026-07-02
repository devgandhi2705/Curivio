"""
Phase 9.3.4E — Writer Budget Service

Stage-aware budget allocation for multi-call generation.
Computes per-writer-call source budgets based on probed batch-prompt overhead,
replacing the single-call article_budget_tokens calibration from project_service.

Public surface:
    StageBudgets         — per-stage budget limits
    WriterBudgetPlan     — explicit budget breakdown for a single writer call
    compute_stage_budgets()   — derive stage limits from model/provider config
    probe_writer_overhead()   — measure instruction + schema overhead via empty-article probe
    build_writer_budget()     — compute WriterBudgetPlan from probed overhead
    max_articles_for_budget() — how many articles fit at FULL compression
"""

from __future__ import annotations

from dataclasses import dataclass

# Per-call safety buffer held back after overhead allocation.
_WRITER_RESERVE    = 300
# Conservative FULL-level token estimate per article (FULL threshold is 180).
_FULL_TOKENS_EACH  = 200


@dataclass
class StageBudgets:
    """
    Per-call token limits for each pipeline stage.
    Each writer call has its own full provider-effective limit (not shared across calls).
    Synthesizer gets a fixed reservation for observability.
    """
    provider_effective:  int   # raw provider effective limit per call
    writer_budget:       int   # per writer-call limit (= provider_effective)
    synthesizer_budget:  int   # expected tokens for synthesis call (informational)


@dataclass
class WriterBudgetPlan:
    """
    Explicit budget breakdown for a single writer LLM call.
    source_budget is the allocation for formatted source articles.
    """
    available_budget:   int
    instruction_budget: int    # probe-measured: instruction sections (no articles)
    schema_budget:      int    # probe-measured: output_schema section
    source_budget:      int    # available - instruction - schema - reserve
    reserve_budget:     int    # safety buffer
    instruction_pct:    float  # instruction_budget / available_budget × 100
    source_pct:         float  # source_budget / available_budget × 100


def compute_stage_budgets(
    model_name:    str,
    provider_tier: str | None = None,
) -> StageBudgets:
    """
    Derive per-stage budget limits from model registry and provider tier.
    Each writer call gets the full provider-effective per-call limit.
    """
    from .model_registry import get_model_config
    cfg = get_model_config(model_name)
    eff = cfg.get_effective_prompt_budget(provider_tier or cfg.default_provider_tier)
    return StageBudgets(
        provider_effective = eff,
        writer_budget      = eff,
        synthesizer_budget = 1_500,
    )


def probe_writer_overhead(
    ctx:        "PromptContext",
    batch_plan: "BatchPlan",
) -> tuple[int, int]:
    """
    Build a batch prompt with no source articles and measure fixed token overhead.
    Uses PromptComposer.generate_report() — no LLM call.

    Returns:
        (instruction_tokens, schema_tokens)
        instruction_tokens: all non-schema sections (includes article section headers)
        schema_tokens:      output_schema section only
    """
    from ..prompts.project_insight_prompt import build_batch_prompt

    probe   = build_batch_prompt(ctx, batch_plan, core_article_text="", curiosity_article_text="")
    report  = probe.generate_report()
    sections = report["sections"]

    schema_tokens = sections.get("output_schema", {}).get("tokens", 0)
    total_tokens  = report["total_tokens"]
    instr_tokens  = total_tokens - schema_tokens

    return instr_tokens, schema_tokens


def build_writer_budget(
    stage_budgets:        StageBudgets,
    instruction_overhead: int,
    schema_overhead:      int,
) -> WriterBudgetPlan:
    """
    Compute WriterBudgetPlan from probed overhead values.
    source_budget is floored at 800 to prevent pathological cases.
    """
    avail      = stage_budgets.writer_budget
    source_bud = max(800, avail - instruction_overhead - schema_overhead - _WRITER_RESERVE)
    return WriterBudgetPlan(
        available_budget   = avail,
        instruction_budget = instruction_overhead,
        schema_budget      = schema_overhead,
        source_budget      = source_bud,
        reserve_budget     = _WRITER_RESERVE,
        instruction_pct    = round(instruction_overhead / avail * 100, 1) if avail else 0.0,
        source_pct         = round(source_bud / avail * 100, 1) if avail else 0.0,
    )


def max_articles_for_budget(source_budget: int) -> int:
    """
    Maximum articles that fit in source_budget at FULL compression.
    Minimum 1.
    """
    return max(1, source_budget // _FULL_TOKENS_EACH)
