"""
Phase 9.3.4B — Batch-Aware Prompt Assembly Tests

Tests:
  - PromptMode enum values
  - PromptContext construction
  - build_batch_prompt package mode (batch_plan=None)
  - build_batch_prompt batch mode (batch_plan provided)
  - Batch source ID prefix (B1-CORE-N) in schema + grounding + plan block
  - Curiosity section present in package mode, absent in batch mode
  - Batch header in core_articles section
  - Multiple batches have distinct source ID prefixes
  - [PROMPT BREAKDOWN] log fires with correct fields
  - make_daily_package_composer backward compat (unchanged call signature)

Run:
    pytest tests/test_batch_prompt.py -v --noconftest
"""

from __future__ import annotations
import logging
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from backend.prompts.project_insight_prompt import (
    PromptMode,
    PromptContext,
    build_batch_prompt,
    make_daily_package_composer,
)
from backend.services.article_plan_service import (
    build_article_plans,
    build_batch_plans,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ctx(**overrides) -> PromptContext:
    defaults = dict(
        project_name="AI Agents",
        keywords=["LLM", "agent", "tools"],
        difficulty="intermediate",
        day_number=1,
        display_label="Day 1",
    )
    defaults.update(overrides)
    return PromptContext(**defaults)


def _art(i: int) -> dict:
    return {
        "title":          f"Article {i}: Test Headline",
        "url":            f"https://source{i}.com/article",
        "content":        f"Content {i}.",
        "_rank_score":    max(0.30, 0.92 - i * 0.06),
        "signal_density": 0.70,
        "source_strength": 0.75,
        "source_type":    "news",
    }


def _section_content(composer, name: str) -> str:
    """Return the content string for a named section (empty string if absent)."""
    for s in composer._sections:
        if s.name == name:
            return s.content
    return ""


def _has_section(composer, name: str) -> bool:
    return any(s.name == name for s in composer._sections)


# ── PromptMode ────────────────────────────────────────────────────────────────

def test_prompt_mode_values():
    assert PromptMode.PACKAGE.value   == "package"
    assert PromptMode.BATCH.value     == "batch"
    assert PromptMode.SYNTHESIS.value == "synthesis"

def test_prompt_mode_is_str_enum():
    assert isinstance(PromptMode.PACKAGE, str)


# ── PromptContext ─────────────────────────────────────────────────────────────

def test_prompt_context_minimal():
    ctx = _ctx()
    assert ctx.project_name == "AI Agents"
    assert ctx.mode == PromptMode.PACKAGE

def test_prompt_context_defaults():
    ctx = _ctx()
    assert ctx.daily_core_article_count == 4
    assert ctx.intent_profile is None
    assert ctx.knowledge_state is None
    assert ctx.article_plan_block is None
    assert ctx.article_budget_tokens == 0

def test_prompt_context_accepts_mode_override():
    ctx = _ctx(mode=PromptMode.BATCH)
    assert ctx.mode == PromptMode.BATCH


# ── build_batch_prompt — package mode ────────────────────────────────────────

def test_package_mode_returns_composer():
    composer = build_batch_prompt(_ctx())
    assert composer is not None
    assert composer._sections

def test_package_mode_has_required_sections():
    composer = build_batch_prompt(_ctx())
    section_names = {s.name for s in composer._sections}
    for required in ("intro", "project_state", "core_articles", "curiosity_articles",
                     "output_schema", "source_grounding", "editorial_philosophy"):
        assert required in section_names, f"Missing section: {required}"

def test_package_mode_curiosity_section_present():
    composer = build_batch_prompt(_ctx(), curiosity_article_text="[CURIOSITY 1] title\n")
    assert _has_section(composer, "curiosity_articles")

def test_package_mode_core_header():
    composer = build_batch_prompt(_ctx(), core_article_text="ARTICLE TEXT\n")
    core_content = _section_content(composer, "core_articles")
    assert "AVAILABLE ARTICLES — CORE LEARNING" in core_content
    assert "ARTICLE TEXT" in core_content

def test_package_mode_source_id_no_prefix():
    composer = build_batch_prompt(_ctx())
    schema = _section_content(composer, "output_schema")
    assert "CORE-N reports" in schema
    assert "B1-CORE-N" not in schema

def test_package_mode_grounding_no_prefix():
    composer = build_batch_prompt(_ctx())
    grounding = _section_content(composer, "source_grounding")
    assert "CORE-1 reports" in grounding
    assert "B1-CORE-1" not in grounding

def test_package_mode_with_intent_profile():
    ctx = _ctx(intent_profile={
        "persona": "ML engineer",
        "goal": "master agents",
        "industry_context": "tech",
        "primary_focus": "LLM tooling",
        "search_lens": "technical",
        "intent_summary": "Deep mastery of agent systems.",
    })
    composer = build_batch_prompt(ctx)
    assert _has_section(composer, "intent_profile")
    assert "ML engineer" in _section_content(composer, "intent_profile")

def test_package_mode_with_knowledge_state():
    ctx = _ctx(knowledge_state={
        "covered_topics": ["transformers", "attention"],
        "active_topics": ["RLHF"],
        "recent_topics": ["GPT-4"],
        "knowledge_gaps": ["multi-agent coordination"],
        "covered_entities": ["OpenAI"],
        "covered_keywords": ["LLM"],
    })
    composer = build_batch_prompt(ctx)
    assert _has_section(composer, "knowledge_state")

def test_package_mode_article_plan_block_injected():
    ctx = _ctx(article_plan_block="ARTICLE SOURCE ASSIGNMENTS\n==\nSLOT 1 -- Topic hint: Test\n")
    composer = build_batch_prompt(ctx)
    assert _has_section(composer, "article_source_assignments")
    assert "SLOT 1" in _section_content(composer, "article_source_assignments")

def test_package_mode_no_article_plan_block_no_section():
    composer = build_batch_prompt(_ctx())
    assert not _has_section(composer, "article_source_assignments")


# ── build_batch_prompt — batch mode ──────────────────────────────────────────

def _make_batch_1():
    arts = [_art(i) for i in range(4)]
    plans = build_article_plans(arts, 4)
    batches = build_batch_plans(plans)
    return batches[0]


def test_batch_mode_returns_composer():
    bp = _make_batch_1()
    composer = build_batch_prompt(_ctx(), batch_plan=bp, core_article_text="BATCH CONTENT\n")
    assert composer is not None

def test_batch_mode_no_curiosity_section():
    bp = _make_batch_1()
    composer = build_batch_prompt(_ctx(), batch_plan=bp)
    assert not _has_section(composer, "curiosity_articles")

def test_batch_mode_core_header_contains_batch_id():
    bp = _make_batch_1()
    composer = build_batch_prompt(_ctx(), batch_plan=bp, core_article_text="BATCH ARTICLES\n")
    core_content = _section_content(composer, "core_articles")
    assert f"BATCH {bp.batch_id}" in core_content
    assert "AVAILABLE ARTICLES — CORE LEARNING" not in core_content

def test_batch_mode_core_header_shows_article_type():
    bp = _make_batch_1()
    composer = build_batch_prompt(_ctx(), batch_plan=bp)
    core_content = _section_content(composer, "core_articles")
    assert "CORE" in core_content    # batch type derived from plans[0].article_type


# ── Task 5: Batch source IDs ──────────────────────────────────────────────────

def test_batch_source_id_prefix_in_schema():
    bp = _make_batch_1()
    composer = build_batch_prompt(_ctx(), batch_plan=bp)
    schema = _section_content(composer, "output_schema")
    assert f"B{bp.batch_id}-CORE-N" in schema

def test_batch_source_id_prefix_in_grounding():
    bp = _make_batch_1()
    composer = build_batch_prompt(_ctx(), batch_plan=bp)
    grounding = _section_content(composer, "source_grounding")
    assert f"B{bp.batch_id}-CORE-1" in grounding

def test_batch_source_id_prefix_in_plan_block():
    bp = _make_batch_1()
    composer = build_batch_prompt(_ctx(), batch_plan=bp)
    plan_block = _section_content(composer, "article_source_assignments")
    assert plan_block, "article_source_assignments section must be populated in batch mode"
    assert f"B{bp.batch_id}-CORE-" in plan_block

def test_multiple_batches_distinct_prefixes():
    arts = [_art(i) for i in range(8)]
    plans = build_article_plans(arts, 8)
    batches = build_batch_plans(plans, max_articles_per_batch=4)
    assert len(batches) == 2

    c1 = build_batch_prompt(_ctx(), batch_plan=batches[0])
    c2 = build_batch_prompt(_ctx(), batch_plan=batches[1])

    schema1 = _section_content(c1, "output_schema")
    schema2 = _section_content(c2, "output_schema")

    assert "B1-CORE-N" in schema1
    assert "B2-CORE-N" in schema2
    assert "B2-CORE-N" not in schema1
    assert "B1-CORE-N" not in schema2


# ── Task 9B: Source isolation per batch ───────────────────────────────────────

def test_batch_core_text_appears_in_section():
    bp = _make_batch_1()
    sentinel = "BATCH_ARTICLE_SENTINEL_XYZ"
    composer = build_batch_prompt(_ctx(), batch_plan=bp, core_article_text=sentinel)
    assert sentinel in _section_content(composer, "core_articles")

def test_batch_curiosity_text_ignored():
    """Curiosity text passed to batch mode should not appear (no curiosity section)."""
    bp = _make_batch_1()
    sentinel = "CURIOSITY_SENTINEL_XYZ"
    composer = build_batch_prompt(_ctx(), batch_plan=bp, curiosity_article_text=sentinel)
    assert not _has_section(composer, "curiosity_articles")
    # sentinel should not appear anywhere in batch mode
    all_content = " ".join(s.content for s in composer._sections)
    assert sentinel not in all_content


# ── Task 8: [PROMPT BREAKDOWN] logging ───────────────────────────────────────

def test_prompt_breakdown_logged_package_mode(caplog):
    with caplog.at_level(logging.INFO, logger="backend.prompts.project_insight_prompt"):
        build_batch_prompt(_ctx())
    assert any("[PROMPT BREAKDOWN]" in r.message for r in caplog.records)

def test_prompt_breakdown_logged_batch_mode(caplog):
    bp = _make_batch_1()
    with caplog.at_level(logging.INFO, logger="backend.prompts.project_insight_prompt"):
        build_batch_prompt(_ctx(), batch_plan=bp)
    assert any("[PROMPT BREAKDOWN]" in r.message for r in caplog.records)

def test_prompt_breakdown_has_mode_field(caplog):
    with caplog.at_level(logging.INFO, logger="backend.prompts.project_insight_prompt"):
        build_batch_prompt(_ctx())
    breakdown = next(r.message for r in caplog.records if "[PROMPT BREAKDOWN]" in r.message)
    assert "mode=package" in breakdown

def test_prompt_breakdown_has_token_fields(caplog):
    with caplog.at_level(logging.INFO, logger="backend.prompts.project_insight_prompt"):
        build_batch_prompt(_ctx())
    breakdown = next(r.message for r in caplog.records if "[PROMPT BREAKDOWN]" in r.message)
    for field in ("instruction=", "source=", "schema=", "knowledge=", "total="):
        assert field in breakdown, f"Missing field '{field}' in breakdown: {breakdown}"

def test_prompt_breakdown_batch_shows_batch_id(caplog):
    bp = _make_batch_1()
    with caplog.at_level(logging.INFO, logger="backend.prompts.project_insight_prompt"):
        build_batch_prompt(_ctx(), batch_plan=bp)
    breakdown = next(r.message for r in caplog.records if "[PROMPT BREAKDOWN]" in r.message)
    assert f"batch={bp.batch_id}" in breakdown
    assert "mode=batch" in breakdown


# ── Task 7: make_daily_package_composer backward compat ──────────────────────

def test_wrapper_returns_composer():
    composer = make_daily_package_composer(
        project_name="Test", keywords=["test"],
        difficulty="intermediate", day_number=1, display_label="Day 1",
        core_articles=[], curiosity_articles=[],
    )
    assert composer is not None

def test_wrapper_has_standard_sections():
    composer = make_daily_package_composer(
        project_name="Test", keywords=["test"],
        difficulty="intermediate", day_number=1, display_label="Day 1",
        core_articles=[], curiosity_articles=[],
    )
    section_names = {s.name for s in composer._sections}
    assert "core_articles"      in section_names
    assert "curiosity_articles" in section_names
    assert "output_schema"      in section_names
    assert "source_grounding"   in section_names

def test_wrapper_pre_formatted_text_used():
    pre_core  = "[CORE 1]\nTitle: Pre-formatted\nURL: https://test.com\n"
    pre_curio = "[CURIOSITY 1]\nTitle: Curious\nURL: https://q.com\n"
    composer = make_daily_package_composer(
        project_name="Test", keywords=["test"],
        difficulty="intermediate", day_number=1, display_label="Day 1",
        core_articles=[], curiosity_articles=[],
        core_article_text=pre_core,
        curiosity_article_text=pre_curio,
    )
    core_section = next(s for s in composer._sections if s.name == "core_articles")
    assert pre_core.strip() in core_section.content
    curio_section = next(s for s in composer._sections if s.name == "curiosity_articles")
    assert pre_curio.strip() in curio_section.content

def test_wrapper_package_mode_no_batch_prefix():
    composer = make_daily_package_composer(
        project_name="Test", keywords=["test"],
        difficulty="beginner", day_number=5, display_label="Day 5",
        core_articles=[], curiosity_articles=[],
    )
    schema = _section_content(composer, "output_schema")
    # Package mode must not contain any batch prefix
    assert "B1-CORE" not in schema
    assert "B2-CORE" not in schema

def test_wrapper_fires_prompt_breakdown(caplog):
    with caplog.at_level(logging.INFO, logger="backend.prompts.project_insight_prompt"):
        make_daily_package_composer(
            project_name="Test", keywords=["test"],
            difficulty="intermediate", day_number=1, display_label="Day 1",
            core_articles=[], curiosity_articles=[],
        )
    assert any("[PROMPT BREAKDOWN]" in r.message for r in caplog.records)
