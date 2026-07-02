"""
Phase 9.3.4C — Multi-Call Generation Orchestrator

Replaces single LLM call with N writer calls (one per BatchPlan) followed by a
merge step.  Returns a raw package dict structurally identical to the single-call
output so grounding, storage, and all downstream consumers are unchanged.

Public surface:
    BatchGenerationResult          — per-batch output dataclass
    generate_batch()               — execute one writer LLM call
    merge_batch_results()          — combine results into raw package dict
    run_generation_orchestrator()  — top-level entry called by project_service
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class BatchGenerationResult:
    batch_id:            int
    insights:            list[dict]
    curiosity_insights:  list[dict]
    prompt_tokens:       int
    completion_tokens:   int
    generation_time_ms:  float
    source_ids_used:     list[str]
    error:               str | None = None
    provider:            str        = "groq"   # "gemini" | "groq"


@dataclass
class GenerationContext:
    """
    Accumulates package state across writer batches.
    Injected into each writer call to prevent duplication and advance narrative coherence.
    """
    package_goal:                str
    learning_thread_seed:        str
    already_covered_topics:      list[str] = field(default_factory=list)
    already_used_frames:         list[str] = field(default_factory=list)
    already_used_title_patterns: list[str] = field(default_factory=list)
    already_used_primary_urls:   list[str] = field(default_factory=list)
    already_generated_titles:    list[str] = field(default_factory=list)


def _build_cross_batch_section(gen_ctx: GenerationContext, batch_num: int) -> str:
    """
    Build the cross-batch context prompt section (fixes A + B).
    Returns empty string for batch 1 (no prior context to share).
    """
    if not (gen_ctx.already_generated_titles or gen_ctx.already_used_primary_urls):
        return ""
    lines = [
        "══════════════════════════════════════",
        f"PACKAGE STATE — Batch {batch_num}",
        "══════════════════════════════════════",
    ]
    if gen_ctx.package_goal:
        lines.append(f"Package goal: {gen_ctx.package_goal}")
    if gen_ctx.learning_thread_seed:
        lines.append(f"Building on: {gen_ctx.learning_thread_seed}")
    if gen_ctx.already_generated_titles:
        lines.append("\nALREADY GENERATED — do not repeat these central ideas:")
        for t in gen_ctx.already_generated_titles[-12:]:
            lines.append(f"  • {t}")
    if gen_ctx.already_covered_topics:
        lines.append(f"\nTopics covered: {', '.join(gen_ctx.already_covered_topics[-8:])}")
    if gen_ctx.already_used_frames:
        lines.append(f"Frames used: {', '.join(sorted(set(gen_ctx.already_used_frames)))}")
    if gen_ctx.already_used_primary_urls:
        lines.append("\nURLs already assigned as primary_source (use as supporting_source only):")
        for url in gen_ctx.already_used_primary_urls:
            lines.append(f"  • {url}")
    lines.append("\nAdvance the package — complement earlier batches, never repeat them.")
    return "\n".join(lines)


def _build_curiosity_anchor(ctx: "PromptContext") -> str:
    """
    Build curiosity anchoring section (fix C).
    Forces curiosity cards to connect to the learner's journey, not be unrelated trivia.
    """
    topics: list[str] = []
    if ctx.knowledge_state:
        focus = (ctx.knowledge_state.get("current_focus") or "").strip()
        if focus and focus not in topics:
            topics.append(focus)
    if not topics:
        topics = list(ctx.keywords[:3])
    if not topics:
        return ""
    return (
        "══════════════════════════════════════\n"
        "CURIOSITY ANCHORING — MANDATORY\n"
        "══════════════════════════════════════\n"
        f"This learner is studying: {', '.join(topics)}\n\n"
        "Each curiosity card MUST create a conceptual bridge to these core topics.\n"
        f"ACCEPT: surprising angles, adjacent domains, unexpected mechanisms "
        f"that deepen understanding of {ctx.project_name}.\n"
        f"REJECT: interesting trivia with no connection to {ctx.project_name} or the above topics.\n"
        f"Test before writing: 'Does this card make the learner sharper at {ctx.project_name}?' "
        "If no, replace it."
    )


def _update_generation_context(
    gen_ctx: GenerationContext,
    result:  BatchGenerationResult,
) -> None:
    """Extract card metadata from a completed batch and update the generation context."""
    for card in result.insights + result.curiosity_insights:
        title = (card.get("title") or "").strip()
        if title and title not in gen_ctx.already_generated_titles:
            gen_ctx.already_generated_titles.append(title)
            words   = [w for w in title.split() if len(w) > 2][:3]
            pattern = " ".join(words)
            if pattern and pattern not in gen_ctx.already_used_title_patterns:
                gen_ctx.already_used_title_patterns.append(pattern)

        category = (card.get("category") or "").strip()
        if category and category not in gen_ctx.already_covered_topics:
            gen_ctx.already_covered_topics.append(category)

        frame = (card.get("narrative_frame") or "").strip()
        if frame and frame not in gen_ctx.already_used_frames:
            gen_ctx.already_used_frames.append(frame)

        ps_url = ((card.get("primary_source") or {}).get("url") or "").strip()
        if ps_url and ps_url not in gen_ctx.already_used_primary_urls:
            gen_ctx.already_used_primary_urls.append(ps_url)

    if gen_ctx.already_covered_topics:
        gen_ctx.learning_thread_seed = ", ".join(gen_ctx.already_covered_topics[-5:])


def generate_batch(
    batch_plan:             "BatchPlan",      # noqa: F821
    context:                "PromptContext",  # noqa: F821
    core_article_text:      str,
    curiosity_article_text: str        = "",
    cross_batch_context:    str | None = None,
    curiosity_anchor:       str | None = None,
    raw_batch_articles:     list[dict] | None = None,
) -> BatchGenerationResult:
    """Execute one writer LLM call for a single BatchPlan. Returns cards only."""
    from ..prompts.project_insight_prompt import build_batch_prompt
    from ..prompts.model_aware_assembler import ModelAwareAssembler
    from ..config import GROQ_MODEL as _ACTIVE_MODEL
    from .grok_service import ask_grok
    from .writer_provider_router import route_writer_call, format_articles_full

    t_start = time.monotonic()

    composer = build_batch_prompt(
        context,
        batch_plan=batch_plan,
        core_article_text=core_article_text,
        curiosity_article_text=curiosity_article_text,
    )

    # A+B: cross-batch context and duplicate prevention
    if cross_batch_context:
        composer.add_section(
            "cross_batch_context", cross_batch_context,
            priority=1, required=False, source_pack="dynamic",
        )
    # C: curiosity anchoring — only for curiosity batches
    _is_curiosity = bool(batch_plan.plans) and batch_plan.plans[0].article_type == "curiosity"
    if curiosity_anchor and _is_curiosity:
        composer.add_section(
            "curiosity_anchor", curiosity_anchor,
            priority=1, required=False, source_pack="dynamic",
        )

    prompt, assembly = ModelAwareAssembler.build(
        composer, _ACTIVE_MODEL, expected_output_tokens=1200,
    )

    # Build full Gemini prompt (no compression, no budget cap) when raw articles available
    if raw_batch_articles is not None:
        _batch_tag   = f"B{batch_plan.batch_id}-"
        _batch_type  = "CURIOSITY" if _is_curiosity else "CORE"
        _full_core   = format_articles_full(raw_batch_articles, f"{_batch_tag}{_batch_type}")
        _full_comp   = build_batch_prompt(
            context, batch_plan=batch_plan,
            core_article_text=_full_core,
            curiosity_article_text="",
        )
        if cross_batch_context:
            _full_comp.add_section("cross_batch_context", cross_batch_context,
                                   priority=1, required=False, source_pack="dynamic")
        if curiosity_anchor and _is_curiosity:
            _full_comp.add_section("curiosity_anchor", curiosity_anchor,
                                   priority=1, required=False, source_pack="dynamic")
        _gemini_prompt = _full_comp.build()
    else:
        _gemini_prompt = prompt  # fallback: route compressed prompt to Gemini

    logger.info(
        "[writer_router] batch=%d  gemini_prompt_tokens~=%d  groq_prompt_tokens=%d",
        batch_plan.batch_id, len(_gemini_prompt) // 4, assembly.final_tokens,
    )

    text, _batch_provider = route_writer_call(
        _gemini_prompt,
        lambda: ask_grok(prompt, json_mode=True),
        json_mode=True,
    )
    raw  = json.loads(text)

    insights           = raw.get("insights")           or []
    curiosity_insights = raw.get("curiosity_insights") or []

    expected_insights  = sum(1 for p in batch_plan.plans if p.article_type != "curiosity")
    expected_curiosity = sum(1 for p in batch_plan.plans if p.article_type == "curiosity")
    if len(insights) > expected_insights:
        logger.warning(
            "[GENERATE BATCH] batch=%d over-generated core: got=%d expected=%d — truncating",
            batch_plan.batch_id, len(insights), expected_insights,
        )
        insights = insights[:expected_insights]
    if len(curiosity_insights) > expected_curiosity:
        logger.warning(
            "[GENERATE BATCH] batch=%d over-generated curiosity: got=%d expected=%d — truncating",
            batch_plan.batch_id, len(curiosity_insights), expected_curiosity,
        )
        curiosity_insights = curiosity_insights[:expected_curiosity]

    source_ids = list({
        src.get("url", "")
        for card in (insights + curiosity_insights)
        for src in (
            [card.get("primary_source") or {}]
            + (card.get("supporting_sources") or [])
        )
        if src.get("url")
    })

    return BatchGenerationResult(
        batch_id           = batch_plan.batch_id,
        insights           = insights,
        curiosity_insights = curiosity_insights,
        prompt_tokens      = assembly.final_tokens,
        completion_tokens  = 0,
        generation_time_ms = (time.monotonic() - t_start) * 1000,
        source_ids_used    = source_ids,
        provider           = _batch_provider,
    )


def merge_batch_results(
    results:    list[BatchGenerationResult],
    day_number: int,
) -> dict:
    """Merge cards from all batches. Package-level metadata populated by synthesize_package()."""
    all_insights:  list[dict] = []
    all_curiosity: list[dict] = []
    for r in results:
        all_insights.extend(r.insights)
        all_curiosity.extend(r.curiosity_insights)
    return {
        "package_headline":   "",
        "content_mix":        f"{len(all_insights)} core + {len(all_curiosity)} curiosity",
        "learning_thread":    "",
        "action_item":        "",
        "insights":           all_insights,
        "curiosity_insights": all_curiosity,
    }


def _log_orchestrator_summary(
    batch_plans: list,
    results:     list[BatchGenerationResult],
    elapsed_ms:  float,
) -> None:
    total_prompt_tok = sum(r.prompt_tokens for r in results)
    total_cards      = sum(len(r.insights) + len(r.curiosity_insights) for r in results)
    batch_sizes      = [len(bp.plans) for bp in batch_plans]
    logger.info(
        "[GENERATION ORCHESTRATOR] batches=%d  sizes=%s  "
        "total_prompt_tok=%d  total_cards=%d  elapsed_ms=%.0f",
        len(batch_plans), batch_sizes,
        total_prompt_tok, total_cards, elapsed_ms,
    )


def run_generation_orchestrator(
    project_name:             str,
    keywords:                 list[str],
    difficulty:               str,
    day_number:               int,
    display_label:            str,
    daily_core_article_count: int,
    core_articles:            list[dict],
    curiosity_articles:       list[dict],
    article_budget_tokens:    int,
    project_id:               str,
    intent_profile:       dict | None = None,
    knowledge_state:      dict | None = None,
    curiosity_directives:     str | None  = None,
    intelligence_context:     str | None  = None,
    quality_feedback:         str | None  = None,
    article_plan_block:       str | None  = None,
    frame_hint:               str | None  = None,
) -> dict:
    """
    Top-level orchestrator entry point.

    Builds batch plans from articles, runs one writer call per batch in sequence,
    merges results, and returns a raw package dict identical in structure to the
    single-call output so all downstream code (grounding, storage, metrics) is
    unchanged.
    """
    from ..prompts.project_insight_prompt import PromptContext
    from ..prompts.article_compressor import ArticleCompressor
    from .article_plan_service import (
        build_article_plans, build_batch_plans, resolve_package_counts,
        validate_plans, validate_batch_plans,
    )

    t0 = time.monotonic()

    ctx = PromptContext(
        project_name             = project_name,
        keywords                 = keywords,
        difficulty               = difficulty,
        day_number               = day_number,
        display_label            = display_label,
        daily_core_article_count = daily_core_article_count,
        intent_profile  = intent_profile,
        knowledge_state = knowledge_state,
        curiosity_directives     = curiosity_directives,
        intelligence_context     = intelligence_context,
        quality_feedback         = quality_feedback,
        frame_hint               = frame_hint,
    )

    core_count, curiosity_count = resolve_package_counts(daily_core_article_count)
    core_plans      = build_article_plans(core_articles,      core_count)
    curiosity_plans = build_article_plans(curiosity_articles, curiosity_count, article_type="curiosity")

    _ok_core, _core_errs = validate_plans(core_plans)
    if not _ok_core:
        logger.warning("[GENERATION ORCHESTRATOR] project=%s core plan issues: %s", project_id, _core_errs)
    _ok_curio, _curio_errs = validate_plans(curiosity_plans)
    if not _ok_curio:
        logger.warning("[GENERATION ORCHESTRATOR] project=%s curiosity plan issues: %s", project_id, _curio_errs)

    # 9.3.4E: Budget-aware batch sizing — probe overhead before committing to batch layout
    from ..config import GROQ_MODEL as _ACTIVE_MODEL
    from .writer_budget_service import (
        compute_stage_budgets, probe_writer_overhead, build_writer_budget,
        max_articles_for_budget,
    )
    _default_plans = build_batch_plans(core_plans + curiosity_plans)

    if not _default_plans:
        raise RuntimeError(
            f"[GENERATION ORCHESTRATOR] No batch plans produced for project={project_id}"
        )

    _stage_budgets = compute_stage_budgets(_ACTIVE_MODEL)
    try:
        _instr_oh, _schema_oh = probe_writer_overhead(ctx, _default_plans[0])
        _writer_budget        = build_writer_budget(_stage_budgets, _instr_oh, _schema_oh)
    except Exception as _probe_exc:
        logger.warning(
            "[BUDGET ALLOCATION] Probe failed (%s) — falling back to article_budget_tokens=%d",
            _probe_exc, article_budget_tokens,
        )
        _writer_budget = None

    _max_per_batch = (
        max_articles_for_budget(_writer_budget.source_budget) if _writer_budget else 4
    )
    batch_plans = (
        build_batch_plans(core_plans + curiosity_plans, max_articles_per_batch=_max_per_batch)
        if _max_per_batch != 4
        else _default_plans
    )

    _ok_batch, _batch_errs = validate_batch_plans(batch_plans)
    if not _ok_batch:
        logger.warning("[GENERATION ORCHESTRATOR] project=%s batch plan issues: %s", project_id, _batch_errs)

    if _writer_budget:
        logger.info(
            "[BUDGET ALLOCATION] provider_eff=%d  instr=%d(%.1f%%)  "
            "schema=%d  source=%d(%.1f%%)  max_per_batch=%d  batches=%d",
            _stage_budgets.provider_effective,
            _writer_budget.instruction_budget, _writer_budget.instruction_pct,
            _writer_budget.schema_budget,
            _writer_budget.source_budget,     _writer_budget.source_pct,
            _max_per_batch, len(batch_plans),
        )

    url_to_core  = {a.get("url", ""): a for a in core_articles      if a.get("url")}
    url_to_curio = {a.get("url", ""): a for a in curiosity_articles  if a.get("url")}

    compressor = ArticleCompressor()

    results:  list[BatchGenerationResult] = []
    failures: list[str] = []

    # A+B+C: cross-batch context accumulator and curiosity anchor
    _goal = (
        (intent_profile or {}).get("goal")
        or f"Day {day_number} package for {project_name}: {', '.join(keywords[:3])}"
    )
    gen_ctx           = GenerationContext(package_goal=_goal, learning_thread_seed="")
    _curiosity_anchor = _build_curiosity_anchor(ctx) or None

    _cumulative_prompt_tok = 0
    _t_window_start        = time.monotonic()

    for i, bp in enumerate(batch_plans):
        is_curiosity_batch = bool(bp.plans) and bp.plans[0].article_type == "curiosity"
        url_map        = url_to_curio if is_curiosity_batch else url_to_core
        batch_articles = [url_map[url] for url in bp.primary_source_urls if url in url_map]
        label          = f"B{bp.batch_id}-CURIOSITY" if is_curiosity_batch else f"B{bp.batch_id}-CORE"

        _src_budget              = _writer_budget.source_budget if _writer_budget else article_budget_tokens
        batch_text, batch_meta   = compressor.format_intel_batch(
            batch_articles, label, _src_budget,
        )
        if batch_meta:
            _levels = [m.get("level_selected", "?") for m in batch_meta]
            logger.info(
                "[BUDGET ALLOCATION] batch=%d  articles=%d  src_budget=%d  compression=%s",
                bp.batch_id, len(batch_articles), _src_budget, _levels,
            )
        # curiosity_articles section is PACKAGE-mode only; in batch mode both
        # article types are injected via core_article_text (header reads "(CURIOSITY)")
        core_text  = batch_text
        curio_text = ""

        try:
            _cross_batch = _build_cross_batch_section(gen_ctx, bp.batch_id) or None
            result = generate_batch(
                bp, ctx,
                core_article_text=core_text,
                curiosity_article_text=curio_text,
                cross_batch_context=_cross_batch,
                curiosity_anchor=_curiosity_anchor,
                raw_batch_articles=batch_articles,
            )
            results.append(result)
            _update_generation_context(gen_ctx, result)
            _cumulative_prompt_tok += result.prompt_tokens
            logger.info(
                "[GENERATION ORCHESTRATOR] batch=%d ok  provider=%s  cards=%d  "
                "prompt_tok=%d  cumulative_prompt_tok=%d  "
                "window_elapsed_s=%.1f  elapsed_ms=%.0f",
                bp.batch_id,
                result.provider,
                len(result.insights) + len(result.curiosity_insights),
                result.prompt_tokens,
                _cumulative_prompt_tok,
                time.monotonic() - _t_window_start,
                result.generation_time_ms,
            )
        except Exception as exc:
            msg = f"batch={bp.batch_id} failed: {exc}"
            failures.append(msg)
            logger.error("[GENERATION ORCHESTRATOR] %s", msg)

        if i < len(batch_plans) - 1:
            _last_provider = results[-1].provider if results else "groq"
            if _last_provider == "gemini":
                logger.info(
                    "[GENERATION ORCHESTRATOR] skipping inter-batch sleep — served by Gemini, "
                    "no Groq TPM pressure  batch=%d/%d",
                    bp.batch_id, len(batch_plans),
                )
            else:
                logger.info(
                    "[GENERATION ORCHESTRATOR] post-batch pause 60s  "
                    "batch=%d/%d  cumulative_prompt_tok=%d  window_elapsed_s=%.1f",
                    bp.batch_id, len(batch_plans),
                    _cumulative_prompt_tok, time.monotonic() - _t_window_start,
                )
                time.sleep(60)

    if failures:
        succeeded = [r.batch_id for r in results]
        raise RuntimeError(
            f"[GENERATION ORCHESTRATOR] {len(failures)}/{len(batch_plans)} batch(es) failed. "
            f"Succeeded: {succeeded}. Failures: {failures}"
        )

    raw = merge_batch_results(results, day_number)

    # 9.3.4D: Synthesize package-level metadata from completed cards
    from .package_synthesizer_service import synthesize_package
    all_cards  = raw["insights"] + raw["curiosity_insights"]
    synthesis  = synthesize_package(
        cards           = all_cards,
        project_name    = project_name,
        difficulty      = difficulty,
        day_number      = day_number,
        knowledge_state = knowledge_state,
    )
    raw["package_headline"] = synthesis.package_headline
    raw["learning_thread"]  = synthesis.learning_thread
    raw["action_item"]      = synthesis.action_item

    # 9.3.4F: Package validation (audit-only — never blocks generation)
    from ..config import PACKAGE_VALIDATION_ENABLED
    if PACKAGE_VALIDATION_ENABLED:
        try:
            from .package_validation_service import validate_package
            _allowed_urls    = frozenset(
                a.get("url", "") for a in (core_articles + curiosity_articles) if a.get("url")
            )
            _learning_topics = list((knowledge_state or {}).get("active_topics", []))[:6]
            _health          = validate_package(
                raw_package     = raw,
                allowed_urls    = _allowed_urls,
                keywords        = keywords,
                learning_topics = _learning_topics,
                difficulty      = difficulty,
                project_name    = project_name,
            )
            _n_cards   = len(raw.get("insights", [])) + len(raw.get("curiosity_insights", []))
            _log_fn    = logger.warning if _health.status == "FAIL" else logger.info
            _log_fn(
                "[PACKAGE VALIDATION] project=%s  day=%d  cards=%d  batches=%d  "
                "grounding=%.1f  narrative=%.1f  dedup=%.1f  curiosity=%.1f  synthesis=%.1f  "
                "overall=%.1f  status=%s",
                project_id, day_number, _n_cards, len(batch_plans),
                _health.grounding_score, _health.narrative_score, _health.dedup_score,
                _health.curiosity_score, _health.synthesis_score,
                _health.overall_score,   _health.status,
            )
        except Exception as _val_exc:
            logger.warning("[PACKAGE VALIDATION] Validation failed (%s) — continuing", _val_exc)

    elapsed = (time.monotonic() - t0) * 1000
    _log_orchestrator_summary(batch_plans, results, elapsed)
    return raw
