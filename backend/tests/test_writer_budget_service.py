"""
Tests for Phase 9.3.4E — Writer Budget Service.

Run: python -m pytest backend/tests/test_writer_budget_service.py -v
"""

import pytest
from backend.services.writer_budget_service import (
    StageBudgets,
    WriterBudgetPlan,
    build_writer_budget,
    max_articles_for_budget,
    _WRITER_RESERVE,
    _FULL_TOKENS_EACH,
)


# ── build_writer_budget ───────────────────────────────────────────────────────

def _stage(eff: int = 10_500) -> StageBudgets:
    return StageBudgets(
        provider_effective = eff,
        writer_budget      = eff,
        synthesizer_budget = 1_500,
    )


def test_source_budget_is_available_minus_overheads():
    stage  = _stage(10_500)
    plan   = build_writer_budget(stage, instruction_overhead=8_000, schema_overhead=500)
    assert plan.source_budget == 10_500 - 8_000 - 500 - _WRITER_RESERVE


def test_source_budget_floors_at_800():
    stage  = _stage(10_500)
    plan   = build_writer_budget(stage, instruction_overhead=10_000, schema_overhead=500)
    assert plan.source_budget == 800


def test_instruction_pct_correct():
    stage = _stage(10_000)
    plan  = build_writer_budget(stage, instruction_overhead=8_500, schema_overhead=0)
    assert plan.instruction_pct == round(8_500 / 10_000 * 100, 1)


def test_source_pct_correct():
    stage      = _stage(10_000)
    plan       = build_writer_budget(stage, instruction_overhead=8_000, schema_overhead=200)
    expected_source = max(800, 10_000 - 8_000 - 200 - _WRITER_RESERVE)
    assert plan.source_pct == round(expected_source / 10_000 * 100, 1)


def test_reserve_is_always_set():
    plan = build_writer_budget(_stage(), instruction_overhead=5_000, schema_overhead=1_000)
    assert plan.reserve_budget == _WRITER_RESERVE


# ── max_articles_for_budget ───────────────────────────────────────────────────

def test_max_articles_scales_with_budget():
    assert max_articles_for_budget(2_000) == 2_000 // _FULL_TOKENS_EACH


def test_max_articles_minimum_one():
    assert max_articles_for_budget(0)   == 1
    assert max_articles_for_budget(50)  == 1
    assert max_articles_for_budget(199) == 1


def test_max_articles_large_budget():
    assert max_articles_for_budget(4_000) == 4_000 // _FULL_TOKENS_EACH


# ── compute_stage_budgets ─────────────────────────────────────────────────────

def test_compute_stage_budgets_groq_on_demand():
    from backend.services.writer_budget_service import compute_stage_budgets
    sb = compute_stage_budgets("llama-3.3-70b-versatile", provider_tier="on_demand")
    # Groq on_demand: 12K TPM × 0.875 = 10,500
    assert sb.provider_effective == 10_500
    assert sb.writer_budget == sb.provider_effective
    assert sb.synthesizer_budget == 1_500


def test_compute_stage_budgets_writer_equals_provider():
    from backend.services.writer_budget_service import compute_stage_budgets
    sb = compute_stage_budgets("llama-3.3-70b-versatile")
    assert sb.writer_budget == sb.provider_effective


# ── Validation target: FULL becomes normal for multi-call ────────────────────

def test_full_compression_achievable_per_article_groq_on_demand():
    """
    With Groq on_demand (10,500 effective) and typical instruction overhead (80%),
    source_budget must allow at least 2 articles at FULL level (180+ tokens each).
    """
    from backend.services.writer_budget_service import compute_stage_budgets
    stage           = compute_stage_budgets("llama-3.3-70b-versatile", provider_tier="on_demand")
    # Simulate 80% instruction overhead
    instr_oh        = int(stage.provider_effective * 0.80)
    schema_oh       = 500
    plan            = build_writer_budget(stage, instr_oh, schema_oh)
    per_article_bud = plan.source_budget // 2  # 2 articles per batch
    # FULL compression threshold is 180 tokens
    assert per_article_bud >= 180, (
        f"per_article_budget={per_article_bud} too low for FULL compression. "
        f"source_budget={plan.source_budget}"
    )


def test_source_budget_higher_than_single_call_calibration():
    """
    Per-batch source budget must exceed the single-call calibration value
    (which splits article_budget across ALL articles, not just 1-2 per batch).
    Single-call: ~1,700 tokens / 6 articles ≈ 283 per article.
    Multi-call: source_budget / 2 articles per batch >> 283.
    """
    from backend.services.writer_budget_service import compute_stage_budgets
    stage          = compute_stage_budgets("llama-3.3-70b-versatile", provider_tier="on_demand")
    instr_oh       = int(stage.provider_effective * 0.80)
    plan           = build_writer_budget(stage, instr_oh, schema_overhead=500)
    single_call_per_article = 1_700 // 6   # ≈ 283
    per_batch_per_article   = plan.source_budget // 2
    assert per_batch_per_article > single_call_per_article, (
        f"Expected per-batch ({per_batch_per_article}) > single-call ({single_call_per_article})"
    )
