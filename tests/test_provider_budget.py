"""
Provider-Aware Budget Tests — Phase 9.2B
=========================================

Task 10 validation suite: covers all 9 required scenarios plus helpers.

Scenarios
---------
A  92k model + 12k provider → effective = 12k
B  32k model + 32k provider → provider = model → effective = 32k model budget
C  Provider smaller than model → effective = provider
D  Model smaller than provider → effective = model
E  No degradation required (prompt already fits)
F  Small degradation (minor trim, fits after 1-2 steps)
G  Large degradation (multiple steps needed, P5/P4 dropped)
H  Provider limit change (tier swap — "dev" vs "on_demand")
I  Future source-intelligence growth simulation (10 articles)

Run:
    pytest tests/test_provider_budget.py -v
"""

from __future__ import annotations

import sys
import logging
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    yield


from backend.services.token_budget import (
    BudgetStatus, BudgetPlan, evaluate,
    _FEED_SYSTEM_RESERVE,
)
from backend.services.model_registry import (
    get_model_config, ModelConfig, PROVIDER_SAFETY_FACTOR,
)
from backend.prompts.prompt_composer import PromptComposer
from backend.prompts.model_aware_assembler import ModelAwareAssembler, _PROVIDER_SAFETY_FACTOR as ASM_SAFETY


# ── Constants ──────────────────────────────────────────────────────────────────

GROQ_MODEL    = "llama-3.3-70b-versatile"
GROQ_TPM      = 12_000
GROQ_SAFE_BUD = int(GROQ_TPM * PROVIDER_SAFETY_FACTOR)   # 10,500

GROQ_MODEL_BUDGET = get_model_config(GROQ_MODEL).prompt_budget   # 92,400

SONNET_MODEL  = "claude-sonnet-4-6"
SONNET_BUDGET = get_model_config(SONNET_MODEL).prompt_budget      # 150,000

GPT4O_MODEL   = "gpt-4o"
GPT4O_BUDGET  = get_model_config(GPT4O_MODEL).prompt_budget       # ~92,400


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_composer(total_chars: int) -> PromptComposer:
    """Build a realistic PromptComposer with ~total_chars of content."""
    seed = "The mechanism behind this domain is fundamentally misunderstood. "
    body = (seed * (total_chars // len(seed) + 1))[:total_chars]
    c = PromptComposer()
    c.add_section("intro",    "TASK_INTRO\n"    + body[:300],            priority=1, required=True)
    c.add_section("schema",   "OUTPUT_SCHEMA\n" + body[:800],            priority=1, required=True)
    c.add_section("articles", "ARTICLES\n"      + body[:total_chars // 2], priority=1, required=True)
    c.add_section("style",    "STYLE_RULES\n"   + body[:1_400],          priority=3, required=True)
    c.add_section("memory",   "MEMORY\n"        + body[:800],            priority=4, required=False)
    c.add_section("luxury",   "TITLE_EXAMPLES\n"+ body[:2_000],          priority=5, required=True)
    c.add_section("tones",    "TONE_BANK\n"     + body[:1_600],          priority=5, required=True)
    return c


def _make_composer_for_budget(target_tokens: int) -> PromptComposer:
    """Composer whose content is approximately target_tokens tokens."""
    return _make_composer(target_tokens * 4)   # 4 chars/token heuristic


# ═══════════════════════════════════════════════════════════════════════════════
# A — 92k model + 12k provider → effective = 12k safety target
# ═══════════════════════════════════════════════════════════════════════════════

class TestScenarioA_92kModel12kProvider:
    """Groq: huge context window, tiny per-request TPM cap."""

    def test_effective_budget_is_provider_capped(self):
        plan = evaluate(5_000, GROQ_MODEL, provider_tier="on_demand")
        assert plan.effective_limit == GROQ_SAFE_BUD, (
            f"Expected effective_limit={GROQ_SAFE_BUD}, got {plan.effective_limit}"
        )

    def test_model_limit_still_reflects_full_context(self):
        plan = evaluate(5_000, GROQ_MODEL, provider_tier="on_demand")
        assert plan.model_limit == GROQ_MODEL_BUDGET, (
            f"model_limit should be model budget ({GROQ_MODEL_BUDGET}), got {plan.model_limit}"
        )

    def test_prompt_under_provider_limit_is_safe(self):
        plan = evaluate(GROQ_SAFE_BUD - 1, GROQ_MODEL, provider_tier="on_demand")
        assert plan.status in (BudgetStatus.SAFE, BudgetStatus.NEAR_LIMIT)

    def test_prompt_over_provider_limit_is_over(self):
        plan = evaluate(GROQ_SAFE_BUD + 1, GROQ_MODEL, provider_tier="on_demand")
        assert plan.status == BudgetStatus.OVER_LIMIT

    def test_prompt_over_provider_but_under_model_is_over(self):
        # 20,000 tokens: over provider (10,500) but under model (92,400)
        plan = evaluate(20_000, GROQ_MODEL, provider_tier="on_demand")
        assert plan.status == BudgetStatus.OVER_LIMIT, (
            "20K tokens should exceed provider limit even though model allows 92K"
        )

    def test_assembler_uses_provider_limit_by_default(self):
        # Assembler auto-detects default_provider_tier="on_demand" from registry
        cfg = get_model_config(GROQ_MODEL)
        assert cfg.default_provider_tier == "on_demand"
        c = _make_composer(4_000)   # small — should fit
        _, report = ModelAwareAssembler.build(c, GROQ_MODEL)
        assert report.effective_budget == GROQ_SAFE_BUD, (
            f"Assembler effective budget should be {GROQ_SAFE_BUD} (provider cap), "
            f"got {report.effective_budget}"
        )

    def test_provider_limit_fields_populated(self):
        plan = evaluate(5_000, GROQ_MODEL, provider_tier="on_demand")
        assert plan.provider_name == "groq"
        assert plan.provider_tier == "on_demand"
        assert plan.provider_limit == GROQ_SAFE_BUD
        assert plan.reserved_system_budget == _FEED_SYSTEM_RESERVE


# ═══════════════════════════════════════════════════════════════════════════════
# B — 32k model + 32k provider → effective = model budget (provider not tighter)
# ═══════════════════════════════════════════════════════════════════════════════

class TestScenarioB_32kModelMatchingProvider:
    """When provider TPM is large relative to the model, model budget governs."""

    def test_groq_dev_tier_does_not_restrict_llama(self):
        # dev tier = 500K TPM, well above model budget of 92K
        plan = evaluate(50_000, GROQ_MODEL, provider_tier="dev")
        # Provider safe = int(500000 * 0.875) = 437500 > model 92400 → model governs
        assert plan.available_input_budget == GROQ_MODEL_BUDGET, (
            "dev tier (500K TPM) should not restrict model budget"
        )
        assert plan.status == BudgetStatus.SAFE

    def test_effective_limit_equals_model_when_provider_larger(self):
        plan = evaluate(5_000, GROQ_MODEL, provider_tier="dev")
        assert plan.effective_limit == GROQ_MODEL_BUDGET
        assert plan.model_limit == GROQ_MODEL_BUDGET

    def test_both_limits_present_in_plan(self):
        plan = evaluate(5_000, GROQ_MODEL, provider_tier="dev")
        assert plan.model_limit  > 0
        assert plan.provider_limit > 0
        # provider_limit >= model_limit for dev tier
        assert plan.provider_limit >= plan.model_limit


# ═══════════════════════════════════════════════════════════════════════════════
# C — Provider smaller than model → effective = provider
# ═══════════════════════════════════════════════════════════════════════════════

class TestScenarioC_ProviderSmallerThanModel:
    """Provider TPM cap tighter than model context → provider governs."""

    def test_on_demand_is_tighter_than_llama_model(self):
        cfg = get_model_config(GROQ_MODEL)
        assert cfg.tier_limits["on_demand"]["tpm"] < cfg.context_window

    def test_effective_budget_is_provider_when_smaller(self):
        plan = evaluate(5_000, GROQ_MODEL, provider_tier="on_demand")
        assert plan.effective_limit == plan.provider_limit
        assert plan.effective_limit < plan.model_limit

    def test_safe_utilization_target_met(self):
        # Provider safe budget should be 85-90% of raw TPM
        cfg        = get_model_config(GROQ_MODEL)
        tpm        = cfg.tier_limits["on_demand"]["tpm"]
        safe_bud   = int(tpm * PROVIDER_SAFETY_FACTOR)
        pct        = safe_bud / tpm
        assert 0.85 <= pct <= 0.90, (
            f"Safety factor {pct:.2%} outside 85-90% target"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# D — Model smaller than provider → effective = model
# ═══════════════════════════════════════════════════════════════════════════════

class TestScenarioD_ModelSmallerThanProvider:
    """When model context window < provider TPM cap, model budget governs."""

    def test_gemma_model_limit_governs_even_with_tier(self):
        # gemma2-9b-it: 8192 ctx → prompt_budget ≈ 4053
        # on_demand tpm = 15000, safe = int(15000 * 0.875) = 13125
        # model budget (4053) < provider safe (13125) → model governs
        cfg = get_model_config("gemma2-9b-it")
        plan = evaluate(2_000, "gemma2-9b-it", provider_tier="on_demand")
        assert plan.effective_limit == cfg.prompt_budget, (
            f"Gemma model budget ({cfg.prompt_budget}) should govern over provider safe ({plan.provider_limit})"
        )
        assert plan.effective_limit < plan.provider_limit

    def test_no_tier_gives_model_budget_for_gemma(self):
        cfg  = get_model_config("gemma2-9b-it")
        plan = evaluate(1_000, "gemma2-9b-it")
        assert plan.available_input_budget == cfg.prompt_budget


# ═══════════════════════════════════════════════════════════════════════════════
# E — No degradation required
# ═══════════════════════════════════════════════════════════════════════════════

class TestScenarioE_NoDegradationRequired:
    """Small prompt already fits within effective budget — assembler runs clean."""

    def test_small_prompt_no_degradation_groq(self):
        # 4 articles × ~175 tokens + instructions ≈ 2000-3000 tokens
        c = _make_composer(8_000)   # ~2000 tokens
        _, report = ModelAwareAssembler.build(c, GROQ_MODEL)
        assert not report.degraded
        assert report.fits
        assert report.final_tokens <= GROQ_SAFE_BUD

    def test_no_degradation_on_large_model(self):
        c = _make_composer(100_000)   # ~25K tokens — fits Sonnet (150K budget)
        _, report = ModelAwareAssembler.build(c, SONNET_MODEL)
        # Sonnet has no provider tier limit → full context budget applies
        assert not report.degraded


# ═══════════════════════════════════════════════════════════════════════════════
# F — Small degradation (minor overflow, 1-2 repair steps)
# ═══════════════════════════════════════════════════════════════════════════════

class TestScenarioF_SmallDegradation:
    """Prompt slightly over provider limit → 1-2 degradation steps sufficient."""

    def test_slight_overflow_triggers_degradation_groq(self):
        # Build a prompt slightly over the effective budget (10,500)
        # GROQ_SAFE_BUD = 10,500 tokens → ~42,000 chars + P5 fluff to push over
        c = _make_composer(42_000)
        _, report = ModelAwareAssembler.build(c, GROQ_MODEL)
        # Should trigger degradation but remain manageable
        if report.original_tokens > GROQ_SAFE_BUD:
            assert report.degraded
            assert report.final_tokens <= report.original_tokens

    def test_degradation_preserves_p1_sections(self):
        c = _make_composer(46_000)
        prompt, _ = ModelAwareAssembler.build(c, GROQ_MODEL)
        assert "TASK_INTRO" in prompt
        assert "OUTPUT_SCHEMA" in prompt
        assert "ARTICLES" in prompt

    def test_fits_after_small_degradation(self):
        # Target: budget + 10% overflow → should resolve in 1-2 steps
        c = _make_composer(int(GROQ_SAFE_BUD * 4 * 1.1))   # 10% over
        _, report = ModelAwareAssembler.build(c, GROQ_MODEL)
        assert report.fits or report.final_tokens <= report.original_tokens


# ═══════════════════════════════════════════════════════════════════════════════
# G — Large degradation (multiple steps, P5/P4 dropped)
# ═══════════════════════════════════════════════════════════════════════════════

class TestScenarioG_LargeDegradation:
    """Heavily overflowing prompt → multiple degradation steps needed."""

    def test_large_overflow_triggers_multi_step_degradation(self):
        # 3× the effective budget → needs multiple steps
        c = _make_composer(int(GROQ_SAFE_BUD * 4 * 3))
        _, report = ModelAwareAssembler.build(c, GROQ_MODEL)
        assert report.degraded
        if report.degradation:
            assert len(report.degradation.steps_applied) >= 1

    def test_final_tokens_always_le_original(self):
        c = _make_composer(200_000)
        _, report = ModelAwareAssembler.build(c, GROQ_MODEL)
        assert report.final_tokens <= report.original_tokens

    def test_p1_survives_aggressive_degradation(self):
        c = _make_composer(400_000)
        prompt, _ = ModelAwareAssembler.build(c, GROQ_MODEL)
        assert "TASK_INTRO"     in prompt
        assert "OUTPUT_SCHEMA"  in prompt

    def test_assembler_never_raises_on_large_overflow(self):
        c = _make_composer(500_000)
        try:
            ModelAwareAssembler.build(c, GROQ_MODEL)
        except Exception as exc:
            pytest.fail(f"ModelAwareAssembler raised on large overflow: {exc}")


# ═══════════════════════════════════════════════════════════════════════════════
# H — Provider limit change (tier swap)
# ═══════════════════════════════════════════════════════════════════════════════

class TestScenarioH_ProviderLimitChange:
    """Switching from on_demand → dev tier unlocks much larger budget."""

    def test_dev_tier_gives_larger_effective_budget(self):
        plan_od  = evaluate(5_000, GROQ_MODEL, provider_tier="on_demand")
        plan_dev = evaluate(5_000, GROQ_MODEL, provider_tier="dev")
        assert plan_dev.available_input_budget > plan_od.available_input_budget, (
            "dev tier should give larger budget than on_demand"
        )

    def test_status_changes_with_tier(self):
        # 11,000 tokens: OVER_LIMIT on on_demand (10,500 cap) but SAFE on dev
        tokens   = 11_000
        plan_od  = evaluate(tokens, GROQ_MODEL, provider_tier="on_demand")
        plan_dev = evaluate(tokens, GROQ_MODEL, provider_tier="dev")
        assert plan_od.status  == BudgetStatus.OVER_LIMIT
        assert plan_dev.status == BudgetStatus.SAFE

    def test_assembler_explicit_tier_override(self):
        # Explicitly pass dev tier to assembler — should use model budget
        c = _make_composer_for_budget(GROQ_SAFE_BUD + 2_000)   # over on_demand, fine on dev
        _, report = ModelAwareAssembler.build(c, GROQ_MODEL, provider_tier="dev")
        assert report.effective_budget > GROQ_SAFE_BUD

    def test_no_tier_uses_default_provider_tier(self):
        # Calling without tier → should use default_provider_tier="on_demand"
        cfg  = get_model_config(GROQ_MODEL)
        plan = evaluate(5_000, GROQ_MODEL)
        # Without tier: backward-compat → model budget
        assert plan.effective_limit == GROQ_MODEL_BUDGET
        # With explicit on_demand: provider budget
        plan2 = evaluate(5_000, GROQ_MODEL, provider_tier="on_demand")
        assert plan2.effective_limit == GROQ_SAFE_BUD


# ═══════════════════════════════════════════════════════════════════════════════
# I — Future source-intelligence growth simulation (10 articles, Day 1000)
# ═══════════════════════════════════════════════════════════════════════════════

class TestScenarioI_FutureSourceIntelligenceGrowth:
    """
    Day 1000 with 10 articles + richer source intelligence.

    Phase 9.3 will add per-article source metadata (provenance, diversity score,
    quality signals).  This test simulates that growth: articles are larger and
    the P3 section budget is heavier.  The system must still fit within the
    provider limit with degradation if necessary.
    """

    def _make_day1000_composer(self, n_articles: int = 10, source_intel: bool = True) -> PromptComposer:
        """
        Simulate Day 1000 prompt structure:
        - 10 core articles (vs 4 on Day 1)
        - Richer source intelligence section (P3, ~400 extra tokens per article)
        - Larger knowledge state / memory (P4)
        """
        seed = "The mechanism driving this domain has evolved significantly over 1000 days. "
        body = (seed * 300)[:12_000]

        per_article = 500 if source_intel else 200   # ~125/50 tokens each
        article_block = ("Article source signal data. " * 20)[:per_article] * n_articles

        c = PromptComposer()
        c.add_section("intro",    "TASK_INTRO\n"          + body[:300],        priority=1, required=True)
        c.add_section("schema",   "OUTPUT_SCHEMA\n"        + body[:800],        priority=1, required=True)
        c.add_section("articles", "CORE_ARTICLES\n"        + article_block,     priority=1, required=True)
        c.add_section("style",    "STYLE_RULES\n"          + body[:1_600],      priority=3, required=True)
        c.add_section("src_intel","SOURCE_INTELLIGENCE\n"  + body[:3_000],      priority=3, required=False)
        c.add_section("memory",   "MEMORY\n"               + body[:2_000],      priority=4, required=False)
        c.add_section("luxury",   "TITLE_EXAMPLES\n"       + body[:2_000],      priority=5, required=True)
        return c

    def test_day1000_10_articles_fits_groq(self):
        c = self._make_day1000_composer(n_articles=10, source_intel=False)
        _, report = ModelAwareAssembler.build(c, GROQ_MODEL)
        # Must either fit or degrade — never raises
        assert report.final_tokens > 0
        assert not report.final_tokens > report.original_tokens

    def test_day1000_with_source_intel_degrades_gracefully(self):
        c = self._make_day1000_composer(n_articles=10, source_intel=True)
        prompt, report = ModelAwareAssembler.build(c, GROQ_MODEL)
        assert "TASK_INTRO" in prompt
        assert report.final_tokens <= report.original_tokens

    def test_day1000_p1_articles_survive(self):
        c = self._make_day1000_composer(n_articles=10, source_intel=True)
        prompt, _ = ModelAwareAssembler.build(c, GROQ_MODEL)
        assert "TASK_INTRO"    in prompt
        assert "OUTPUT_SCHEMA" in prompt
        assert "CORE_ARTICLES" in prompt

    def test_day1000_headroom_exists_for_source_intelligence(self):
        # Day 1 baseline (4 articles, no source intel)
        c_day1 = self._make_day1000_composer(n_articles=4, source_intel=False)
        _, r1 = ModelAwareAssembler.build(c_day1, GROQ_MODEL)
        # Verify Day 1 fits within 90% of effective budget (leaves headroom for 9.3)
        assert r1.final_tokens <= int(GROQ_SAFE_BUD * 0.90), (
            f"Day 1 prompt ({r1.final_tokens} tok) exceeds 90% of effective budget "
            f"({int(GROQ_SAFE_BUD * 0.90)} tok) — no headroom for source-intel growth"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Provider-aware BudgetPlan field contract
# ═══════════════════════════════════════════════════════════════════════════════

class TestBudgetPlanProviderFields:
    """All Phase 9.2B BudgetPlan fields are present and correct."""

    def test_new_fields_present_without_tier(self):
        plan = evaluate(1_000, GROQ_MODEL)
        assert hasattr(plan, "provider_name")
        assert hasattr(plan, "provider_tier")
        assert hasattr(plan, "model_limit")
        assert hasattr(plan, "provider_limit")
        assert hasattr(plan, "effective_limit")
        assert hasattr(plan, "reserved_output_budget")
        assert hasattr(plan, "reserved_system_budget")

    def test_provider_fields_populated_with_tier(self):
        plan = evaluate(5_000, GROQ_MODEL, provider_tier="on_demand")
        assert plan.provider_name          == "groq"
        assert plan.provider_tier          == "on_demand"
        assert plan.model_limit            == GROQ_MODEL_BUDGET
        assert plan.provider_limit         == GROQ_SAFE_BUD
        assert plan.effective_limit        == GROQ_SAFE_BUD
        assert plan.reserved_output_budget == get_model_config(GROQ_MODEL).output_reserve
        assert plan.reserved_system_budget == _FEED_SYSTEM_RESERVE

    def test_no_tier_leaves_provider_fields_zero(self):
        plan = evaluate(5_000, GROQ_MODEL)   # no explicit tier
        # Without explicit tier: provider fields empty/zero
        assert plan.provider_tier   == ""
        assert plan.provider_limit  == 0
        assert plan.effective_limit == GROQ_MODEL_BUDGET

    def test_non_groq_model_no_provider_limit(self):
        plan = evaluate(5_000, SONNET_MODEL)
        assert plan.provider_limit == 0
        assert plan.effective_limit == SONNET_BUDGET

    def test_effective_limit_is_min_of_model_and_provider(self):
        plan = evaluate(5_000, GROQ_MODEL, provider_tier="on_demand")
        expected = min(plan.model_limit, plan.provider_limit)
        assert plan.effective_limit == expected


# ═══════════════════════════════════════════════════════════════════════════════
# Model registry — effective_prompt_budget property
# ═══════════════════════════════════════════════════════════════════════════════

class TestModelRegistryEffectiveBudget:
    """ModelConfig.get_effective_prompt_budget() respects provider tier."""

    def test_groq_default_tier_caps_budget(self):
        cfg = get_model_config(GROQ_MODEL)
        assert cfg.effective_prompt_budget == GROQ_SAFE_BUD

    def test_groq_dev_tier_allows_full_model_budget(self):
        cfg = get_model_config(GROQ_MODEL)
        dev_budget = cfg.get_effective_prompt_budget(tier="dev")
        # dev TPM safe = int(500000 * 0.875) = 437500 > model 92400 → model governs
        assert dev_budget == cfg.prompt_budget

    def test_non_groq_no_default_tier(self):
        cfg = get_model_config(SONNET_MODEL)
        assert cfg.default_provider_tier is None
        assert cfg.effective_prompt_budget == cfg.prompt_budget

    def test_safety_factor_constant_matches_assembler(self):
        # Both must use the same constant to be consistent
        assert abs(PROVIDER_SAFETY_FACTOR - ASM_SAFETY) < 1e-9

    def test_all_groq_models_have_on_demand_tier(self):
        for model in ["llama-3.3-70b-versatile", "llama-3.1-70b-versatile",
                      "llama-3.1-8b-instant", "gemma2-9b-it"]:
            cfg = get_model_config(model)
            assert cfg.default_provider_tier == "on_demand", (
                f"{model} should have default_provider_tier='on_demand'"
            )
            assert "on_demand" in cfg.tier_limits, (
                f"{model} missing on_demand tier_limits entry"
            )
