"""
Phase A verification tests — run from repo root:
  python -m pytest tests/verify_phase_a_fixes.py -v

Fix 1: frame_hint threads into assembled batch prompt text.
Fix 2: orchestrator validate_plans() catches invalid plans before generate_batch().
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Fix 1: frame_hint wiring
# ─────────────────────────────────────────────────────────────────────────────

def test_prompt_context_has_frame_hint_field():
    from backend.prompts.project_insight_prompt import PromptContext
    ctx = PromptContext(
        project_name="Indian Pharma",
        keywords=["API manufacturing", "CDMO"],
        difficulty="intermediate",
        day_number=3,
        display_label="Day 3",
        frame_hint="CRISIS → RESPONSE",
    )
    assert ctx.frame_hint == "CRISIS → RESPONSE"


def test_frame_hint_appears_in_batch_prompt_text():
    """
    Assemble a real BATCH-mode prompt with a non-None frame_hint and confirm
    'Narrative shape: CRISIS → RESPONSE' is present in the rendered text.
    Uses non-dummy URLs so build_article_plans doesn't pre-filter them.
    """
    from backend.prompts.project_insight_prompt import PromptContext, build_batch_prompt
    from backend.services.article_plan_service import build_article_plans, build_batch_plans

    FRAME_HINT = "CRISIS → RESPONSE"

    articles = [
        {"url": "https://reuters.com/pharma/api-crisis", "title": "Indian API supply crisis", "source_type": "news"},
        {"url": "https://bloomberg.com/cdmo-expansion",  "title": "CDMO capacity expansion",  "source_type": "industry_report"},
        {"url": "https://nature.com/pharma-china-dep",   "title": "Pharma dependency on China","source_type": "research_paper"},
        {"url": "https://pib.gov.in/regulatory-path",    "title": "Regulatory pathway India",  "source_type": "government"},
    ]

    plans   = build_article_plans(articles, 4)
    assert plans, "build_article_plans produced no plans"
    batches = build_batch_plans(plans)
    assert batches, "build_batch_plans produced no batch plans"

    ctx = PromptContext(
        project_name="Indian Pharma",
        keywords=["API", "CDMO", "supply chain"],
        difficulty="intermediate",
        day_number=3,
        display_label="Day 3",
        frame_hint=FRAME_HINT,
    )

    from backend.prompts.article_compressor import ArticleCompressor
    ac = ArticleCompressor()
    batch_text, _ = ac.format_intel_batch(articles, "CORE", 3000)

    composer = build_batch_prompt(
        ctx,
        batch_plan=batches[0],
        core_article_text=batch_text,
    )

    prompt_text = "\n".join(s.content for s in composer._sections if s.content)

    assert f"Narrative shape: {FRAME_HINT}" in prompt_text, (
        f"'Narrative shape: {FRAME_HINT}' NOT found in assembled prompt.\n"
        "article_source_assignments section:\n"
        + next(
            (s.content for s in composer._sections if s.name == "article_source_assignments"),
            "<section missing>"
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# Fix 2: validate_plans catches invalid plans in orchestrator
# ─────────────────────────────────────────────────────────────────────────────

def test_validate_plans_catches_zero_source_plan():
    """
    validate_plans() fails on a plan with zero assigned sources.
    This is the invalid plan the orchestrator's validate_plans() call now catches.
    """
    from backend.services.article_plan_service import ArticlePlan, validate_plans

    bad_plan = ArticlePlan(
        slot_id="slot-1",
        topic_hint="missing sources slot",
        assigned_sources=[],   # zero sources — invalid
        backup_sources=[],
        article_type="core",
    )
    good_plan = ArticlePlan(
        slot_id="slot-2",
        topic_hint="good slot",
        assigned_sources=[{"url": "https://real.com/article", "title": "Real article"}],
        backup_sources=[],
        article_type="core",
    )

    ok, errors = validate_plans([bad_plan, good_plan])

    assert not ok, "validate_plans should fail for zero-source slot"
    assert any("slot-1" in e for e in errors), (
        f"Expected slot-1 error, got: {errors}"
    )


def test_validate_plans_catches_dummy_url_in_assigned_sources():
    """
    validate_plans() fails when assigned_sources contains a dummy/placeholder URL.
    Direct construction bypasses build_article_plans pre-filter (which also catches it,
    but this tests the validation layer itself).
    """
    from backend.services.article_plan_service import ArticlePlan, validate_plans

    plan_with_dummy = ArticlePlan(
        slot_id="slot-1",
        topic_hint="dummy url slot",
        assigned_sources=[{"url": "https://example.com/fake", "title": "Placeholder"}],
        backup_sources=[],
        article_type="core",
    )

    ok, errors = validate_plans([plan_with_dummy])

    assert not ok, "validate_plans should reject dummy URL"
    assert any("example.com" in e for e in errors), (
        f"Expected dummy URL error, got: {errors}"
    )


def test_validate_batch_plans_catches_empty_batch():
    """
    validate_batch_plans() catches an empty BatchPlan (E check).
    This mirrors what the orchestrator now calls after build_batch_plans().
    """
    from backend.services.article_plan_service import BatchPlan, validate_batch_plans

    empty_bp = BatchPlan(
        batch_id=1,
        article_ids=[],
        plans=[],
        primary_source_urls=[],
        supporting_source_urls=[],
        backup_source_urls=[],
    )

    ok, errors = validate_batch_plans([empty_bp])
    assert not ok
    assert any("empty" in e for e in errors), f"Expected empty-batch error, got: {errors}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
