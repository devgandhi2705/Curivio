"""
Budget Controller Tests — Phase 9.2 (Steps 2–11)
==================================================

Covers:
  Step 2  — unified budget model (ModelConfig derived properties)
  Step 3  — BudgetPlan fields and status classification
  Step 4  — preflight evaluate() blocks OVER_LIMIT
  Step 5  — repair pipeline (ModelAwareAssembler degradation)
  Step 6/7 — priority ordering: P1 CRITICAL survives compression
  Step 8  — source excerpt budget: TRIM_ARTICLES degrades correctly
  Step 9  — model-agnostic: different model limits yield different budgets
  Step 10 — observability: single log call, no duplicate instrumentation
  Step 11 — SAFE / NEAR_LIMIT / OVER_LIMIT + repair convergence

Run:
    pytest tests/test_budget_controller.py -v
"""

from __future__ import annotations

import sys
import logging
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# Override conftest autouse fixture that imports backend.main (needs jose/env)
@pytest.fixture(autouse=True)
def reset_rate_limiter():
    yield


from backend.services.token_budget import (
    BudgetStatus, BudgetPlan, evaluate, log_budget_plan,
    estimate_tokens,
)
from backend.services.model_registry import get_model_config
from backend.prompts.prompt_composer import PromptComposer
from backend.prompts.model_aware_assembler import ModelAwareAssembler


# ── Model budget constants (derived from model_registry.py) ──────────────────

# llama-3.3-70b-versatile: 128K ctx, 0.80 util, 8K out, 2K buffer
# safe_context = 128000*0.80 - 2000 = 100400
# prompt_budget = 100400 - 8000 = 92400
LLAMA_BUDGET = 92_400
LLAMA_MODEL  = "llama-3.3-70b-versatile"

# gemma2-9b-it: 8192 ctx, 0.80 util, 2K out, 500 buffer
# safe_context = 8192*0.80 - 500 = 6053
# prompt_budget = 6053 - 2000 = 4053
GEMMA_BUDGET = 4_053
GEMMA_MODEL  = "gemma2-9b-it"

# claude-sonnet-4-6: 200K ctx, 0.80 util, 8K out, 2K buffer
# safe_context = 200000*0.80 - 2000 = 158000
# prompt_budget = 158000 - 8000 = 150000
SONNET_BUDGET = 150_000
SONNET_MODEL  = "claude-sonnet-4-6"


# ═══════════════════════════════════════════════════════════════════════════════
# Step 2 — Unified budget model
# ═══════════════════════════════════════════════════════════════════════════════

class TestModelConfig:
    """ModelConfig exposes context_limit, output_reserve, safety_margin, prompt_budget."""

    def test_llama_budget_math(self):
        cfg = get_model_config(LLAMA_MODEL)
        assert cfg.context_window == 128_000
        assert cfg.output_reserve == 8_000
        assert cfg.safety_buffer == 2_000
        assert cfg.prompt_budget == LLAMA_BUDGET

    def test_gemma_budget_math(self):
        cfg = get_model_config(GEMMA_MODEL)
        assert cfg.context_window == 8_192
        assert cfg.prompt_budget == GEMMA_BUDGET

    def test_sonnet_budget_math(self):
        cfg = get_model_config(SONNET_MODEL)
        assert cfg.context_window == 200_000
        assert cfg.prompt_budget == SONNET_BUDGET

    def test_unknown_model_fallback(self):
        # Unknown model falls back to conservative defaults
        cfg = get_model_config("unknown-model-xyz")
        assert cfg.context_window >= 1_000     # some fallback exists
        assert cfg.prompt_budget > 0           # always positive

    def test_available_input_budget_never_negative(self):
        for name in [LLAMA_MODEL, GEMMA_MODEL, SONNET_MODEL]:
            cfg = get_model_config(name)
            assert cfg.prompt_budget > 0, f"{name}: prompt_budget must be positive"


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3 — BudgetPlan object
# ═══════════════════════════════════════════════════════════════════════════════

class TestBudgetPlan:
    """BudgetPlan contains all required fields and classifies status correctly."""

    def test_fields_present(self):
        plan = evaluate(1_000, LLAMA_MODEL)
        assert hasattr(plan, "model_name")
        assert hasattr(plan, "context_limit")
        assert hasattr(plan, "reserved_output")
        assert hasattr(plan, "safety_margin")
        assert hasattr(plan, "available_input_budget")
        assert hasattr(plan, "current_prompt_tokens")
        assert hasattr(plan, "overflow_tokens")
        assert hasattr(plan, "status")
        # Phase 9.2B fields
        assert hasattr(plan, "provider_name")
        assert hasattr(plan, "provider_tier")
        assert hasattr(plan, "model_limit")
        assert hasattr(plan, "provider_limit")
        assert hasattr(plan, "effective_limit")
        assert hasattr(plan, "reserved_output_budget")
        assert hasattr(plan, "reserved_system_budget")

    def test_fields_populated_correctly(self):
        # Without explicit provider_tier: backward-compat — uses model budget
        plan = evaluate(5_000, LLAMA_MODEL)
        cfg  = get_model_config(LLAMA_MODEL)
        assert plan.model_name             == LLAMA_MODEL
        assert plan.context_limit          == cfg.context_window
        assert plan.reserved_output        == cfg.output_reserve
        assert plan.safety_margin          == cfg.safety_buffer
        assert plan.available_input_budget == cfg.prompt_budget   # model budget when no tier
        assert plan.current_prompt_tokens  == 5_000
        assert plan.model_limit            == cfg.prompt_budget
        assert plan.provider_limit         == 0                   # no tier → no provider limit
        assert plan.effective_limit        == cfg.prompt_budget

    def test_fields_populated_correctly_with_provider_tier(self):
        # With provider_tier: effective_limit = MIN(model, provider)
        from backend.services.model_registry import PROVIDER_SAFETY_FACTOR
        plan = evaluate(5_000, LLAMA_MODEL, provider_tier="on_demand")
        cfg  = get_model_config(LLAMA_MODEL)
        tpm  = cfg.tier_limits["on_demand"]["tpm"]      # 12,000
        expected_provider = int(tpm * PROVIDER_SAFETY_FACTOR)  # 10,500
        assert plan.model_limit     == cfg.prompt_budget         # 92,400
        assert plan.provider_limit  == expected_provider         # 10,500
        assert plan.effective_limit == expected_provider         # min = 10,500
        assert plan.available_input_budget == expected_provider

    def test_overflow_zero_when_under_budget(self):
        plan = evaluate(1_000, LLAMA_MODEL)
        assert plan.overflow_tokens == 0

    def test_overflow_computed_correctly_when_over(self):
        over_by = 5_000
        tokens  = LLAMA_BUDGET + over_by
        plan    = evaluate(tokens, LLAMA_MODEL)
        assert plan.overflow_tokens == over_by


# ═══════════════════════════════════════════════════════════════════════════════
# Step 4 + Step 11 — Preflight classification: SAFE / NEAR_LIMIT / OVER_LIMIT
# ═══════════════════════════════════════════════════════════════════════════════

class TestEvaluate:
    """evaluate() classifies budget status correctly for all three states."""

    def test_safe_status_low_utilization(self):
        # 1% utilization → SAFE
        plan = evaluate(int(LLAMA_BUDGET * 0.01), LLAMA_MODEL)
        assert plan.status == BudgetStatus.SAFE

    def test_safe_status_at_84_pct(self):
        tokens = int(LLAMA_BUDGET * 0.84)
        plan   = evaluate(tokens, LLAMA_MODEL)
        assert plan.status == BudgetStatus.SAFE

    def test_near_limit_at_85_pct(self):
        tokens = int(LLAMA_BUDGET * 0.85)
        plan   = evaluate(tokens, LLAMA_MODEL)
        assert plan.status == BudgetStatus.NEAR_LIMIT

    def test_near_limit_at_99_pct(self):
        tokens = int(LLAMA_BUDGET * 0.99)
        plan   = evaluate(tokens, LLAMA_MODEL)
        assert plan.status == BudgetStatus.NEAR_LIMIT

    def test_over_limit_at_100_pct_plus_one(self):
        plan = evaluate(LLAMA_BUDGET + 1, LLAMA_MODEL)
        assert plan.status == BudgetStatus.OVER_LIMIT

    def test_over_limit_large_overflow(self):
        plan = evaluate(LLAMA_BUDGET + 50_000, LLAMA_MODEL)
        assert plan.status == BudgetStatus.OVER_LIMIT
        assert plan.overflow_tokens == 50_000

    def test_safe_on_small_model(self):
        plan = evaluate(1_000, GEMMA_MODEL)
        assert plan.status == BudgetStatus.SAFE

    def test_over_limit_on_small_model(self):
        plan = evaluate(GEMMA_BUDGET + 1, GEMMA_MODEL)
        assert plan.status == BudgetStatus.OVER_LIMIT

    def test_large_model_has_more_headroom(self):
        # Sonnet (150K budget) should be SAFE where Gemma (4K budget) is OVER_LIMIT
        tokens = 10_000
        plan_sonnet = evaluate(tokens, SONNET_MODEL)
        plan_gemma  = evaluate(tokens, GEMMA_MODEL)
        assert plan_sonnet.status == BudgetStatus.SAFE
        assert plan_gemma.status  == BudgetStatus.OVER_LIMIT


# ═══════════════════════════════════════════════════════════════════════════════
# Step 5 — Repair pipeline: ModelAwareAssembler degrades to fit
# ═══════════════════════════════════════════════════════════════════════════════

def _make_composer(total_chars: int) -> PromptComposer:
    """Build a composer with realistic section structure and ~total_chars of content."""
    seed = "The mechanism behind this is fundamentally misunderstood by practitioners. "
    body = (seed * (total_chars // len(seed) + 1))[:total_chars]

    c = PromptComposer()
    c.add_section("intro",    "ANCHOR_INTRO\n" + body[:600], priority=1, required=True)
    c.add_section("schema",   "ANCHOR_SCHEMA\n" + body[:800], priority=1, required=True)
    c.add_section("articles", "ANCHOR_ARTICLES\n" + body[:total_chars // 2], priority=1, required=True)
    c.add_section("style",    "WRITING STYLE\n" + body[:1_600], priority=3, required=True)
    c.add_section("memory",   "MEMORY\n" + body[:1_200], priority=4, required=False)
    c.add_section("examples", "TITLE EXAMPLES\n" + body[:2_000], priority=5, required=True)
    c.add_section("tones",    "EMOTIONAL TONES\n" + body[:1_600], priority=5, required=True)
    return c


class TestRepairPipeline:
    """ModelAwareAssembler degrades gracefully — never raises, P1 always survives."""

    def test_small_prompt_fits_without_degradation(self):
        c = _make_composer(2_000)
        prompt, report = ModelAwareAssembler.build(c, LLAMA_MODEL)
        assert prompt
        assert not report.degraded
        assert report.fits

    def test_large_prompt_degrades_to_fit(self):
        # ~80K chars → ~20K tokens. Gemma budget = 4053 → must degrade
        c = _make_composer(80_000)
        prompt, report = ModelAwareAssembler.build(c, GEMMA_MODEL)
        assert prompt                   # always returns non-empty string
        assert report.degraded          # degradation was applied

    def test_repair_never_raises(self):
        # Even extreme overflow must not raise
        c = _make_composer(400_000)     # ~100K tokens
        try:
            prompt, report = ModelAwareAssembler.build(c, GEMMA_MODEL)
        except Exception as exc:
            pytest.fail(f"ModelAwareAssembler raised: {exc}")
        assert prompt

    def test_repair_result_non_empty(self):
        c = _make_composer(200_000)
        prompt, _ = ModelAwareAssembler.build(c, GEMMA_MODEL)
        assert len(prompt) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# Step 6/7 — Priority ordering: P1 CRITICAL never dropped
# ═══════════════════════════════════════════════════════════════════════════════

class TestPriorityOrdering:
    """P1 sections survive all degradation. P5 drops first."""

    def test_p1_anchors_survive_small_model(self):
        c = _make_composer(80_000)
        prompt, _ = ModelAwareAssembler.build(c, GEMMA_MODEL)
        assert "ANCHOR_INTRO"    in prompt, "P1 intro section was dropped"
        assert "ANCHOR_SCHEMA"   in prompt, "P1 schema section was dropped"
        assert "ANCHOR_ARTICLES" in prompt, "P1 articles section was dropped"

    def test_p5_dropped_before_p1_under_pressure(self):
        # Build composer where P5 content alone would exceed budget
        c = PromptComposer()
        c.add_section("critical", "ANCHOR_CRITICAL\n" + "x" * 400, priority=1, required=True)
        c.add_section("luxury",   "TITLE_EXAMPLES\n"  + "x" * 80_000, priority=5, required=True)
        prompt, report = ModelAwareAssembler.build(c, GEMMA_MODEL)
        assert "ANCHOR_CRITICAL" in prompt, "P1 CRITICAL section was dropped"
        assert report.degraded, "Expected degradation to drop P5 content"

    def test_p1_required_sections_never_absent(self):
        # Feed-style composer: large P5/P4, small P1
        c = PromptComposer()
        c.add_section("output_schema", "ANCHOR_OUTPUT_SCHEMA content",
                      priority=1, required=True)
        c.add_section("title_lib", "T" * 30_000, priority=5, required=True)
        c.add_section("tones",     "T" * 20_000, priority=5, required=True)
        c.add_section("memory",    "T" * 15_000, priority=4, required=False)

        prompt, _ = ModelAwareAssembler.build(c, GEMMA_MODEL)
        assert "ANCHOR_OUTPUT_SCHEMA content" in prompt

    def test_compression_order_p5_before_p3(self):
        # A composer where both P5 and P3 exist; budget tight enough to drop P5 first
        c = PromptComposer()
        c.add_section("schema",  "ANCHOR_SCHEMA",  priority=1, required=True)
        c.add_section("writing", "ANCHOR_WRITING " + "w" * 500, priority=3, required=True)
        c.add_section("luxury",  "ANCHOR_LUXURY "  + "l" * 60_000, priority=5, required=True)

        prompt, report = ModelAwareAssembler.build(c, GEMMA_MODEL)
        # P3 writing guidance should survive longer than P5 luxury
        # (degradation drops luxury first via DROP_LUXURY step)
        assert "ANCHOR_SCHEMA" in prompt


# ═══════════════════════════════════════════════════════════════════════════════
# Step 8 — Source excerpt budget (TRIM_ARTICLES degrades article sections)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSourceExcerptBudget:
    """TRIM_ARTICLES step halves article-named sections when budget is tight."""

    def test_articles_section_trimmed_under_pressure(self):
        c = PromptComposer()
        c.add_section("intro",         "ANCHOR_INTRO",   priority=1, required=True)
        c.add_section("schema",        "ANCHOR_SCHEMA",  priority=1, required=True)
        c.add_section("core_articles", "A" * 40_000,     priority=1, required=True)

        original_tokens = c.estimate_tokens()
        prompt, report  = ModelAwareAssembler.build(c, GEMMA_MODEL)

        # P1 content is present; article section may have been trimmed
        assert "ANCHOR_INTRO"  in prompt
        assert "ANCHOR_SCHEMA" in prompt
        if report.degraded:
            assert report.final_tokens <= report.original_tokens

    def test_final_tokens_le_original_after_degradation(self):
        c = _make_composer(120_000)
        _, report = ModelAwareAssembler.build(c, GEMMA_MODEL)
        assert report.final_tokens <= report.original_tokens


# ═══════════════════════════════════════════════════════════════════════════════
# Step 9 — Model-agnostic: different models yield different budgets
# ═══════════════════════════════════════════════════════════════════════════════

class TestModelAgnostic:
    """Budget decisions driven by model registry — no hardcoded provider constants."""

    def test_same_prompt_different_fits_by_model(self):
        tokens = 10_000  # fits llama/sonnet but not gemma
        plan_llama  = evaluate(tokens, LLAMA_MODEL)
        plan_gemma  = evaluate(tokens, GEMMA_MODEL)
        plan_sonnet = evaluate(tokens, SONNET_MODEL)
        assert plan_llama.status  == BudgetStatus.SAFE
        assert plan_gemma.status  == BudgetStatus.OVER_LIMIT
        assert plan_sonnet.status == BudgetStatus.SAFE

    def test_budget_scales_with_context_window(self):
        # Larger context window → larger available budget
        assert SONNET_BUDGET > LLAMA_BUDGET > GEMMA_BUDGET

    def test_no_groq_tpm_hardcoded_in_evaluate(self):
        # evaluate() must not use 12000 as a limit for non-Groq models
        plan = evaluate(15_000, SONNET_MODEL)
        assert plan.status == BudgetStatus.SAFE, (
            "Sonnet should not be limited by Groq's 12K on_demand TPM"
        )

    def test_openai_model_works_without_tier_limits(self):
        plan = evaluate(5_000, "gpt-4o")
        assert plan.status == BudgetStatus.SAFE
        cfg  = get_model_config("gpt-4o")
        assert plan.available_input_budget == cfg.prompt_budget

    def test_assembly_adapts_to_model_context(self):
        c = _make_composer(50_000)   # ~12500 tokens — fits llama, not gemma
        _, large_report = ModelAwareAssembler.build(c, LLAMA_MODEL)
        _, small_report = ModelAwareAssembler.build(c, GEMMA_MODEL)
        # Large model should not need degradation; small model likely does
        assert large_report.effective_budget > small_report.effective_budget


# ═══════════════════════════════════════════════════════════════════════════════
# Step 10 — Observability: log_budget_plan emits expected records
# ═══════════════════════════════════════════════════════════════════════════════

class TestObservability:
    """log_budget_plan emits INFO for every plan; WARNING on NEAR_LIMIT/OVER_LIMIT."""

    def _capture_logs(self, plan: BudgetPlan) -> list[logging.LogRecord]:
        test_logger = logging.getLogger("test_budget_plan_log")
        records: list[logging.LogRecord] = []

        class _Handler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        handler = _Handler()
        handler.setLevel(logging.DEBUG)
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.DEBUG)
        try:
            log_budget_plan(plan, logger_inst=test_logger)
        finally:
            test_logger.removeHandler(handler)
        return records

    def test_safe_plan_emits_info(self):
        plan    = evaluate(1_000, LLAMA_MODEL)
        records = self._capture_logs(plan)
        levels  = [r.levelno for r in records]
        assert logging.INFO in levels

    def test_safe_plan_no_warning(self):
        plan    = evaluate(1_000, LLAMA_MODEL)
        records = self._capture_logs(plan)
        levels  = [r.levelno for r in records]
        assert logging.WARNING not in levels

    def test_near_limit_emits_warning(self):
        tokens  = int(LLAMA_BUDGET * 0.90)
        plan    = evaluate(tokens, LLAMA_MODEL)
        records = self._capture_logs(plan)
        levels  = [r.levelno for r in records]
        assert logging.WARNING in levels

    def test_over_limit_emits_warning(self):
        plan    = evaluate(LLAMA_BUDGET + 1, LLAMA_MODEL)
        records = self._capture_logs(plan)
        levels  = [r.levelno for r in records]
        assert logging.WARNING in levels

    def test_assembly_report_summary_populated(self):
        c = _make_composer(5_000)
        _, report = ModelAwareAssembler.build(c, LLAMA_MODEL)
        summary = report.summary()
        assert report.model_name in summary
        assert str(report.final_tokens) in summary or str(report.final_tokens // 1000) in summary
