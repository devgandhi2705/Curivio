"""
Phase 9.3.4D — Package Synthesizer

Post-writer synthesis stage. Reads completed cards and generates
package-level metadata: package_headline, learning_thread, action_item.

Called after all writer batches complete. Does not modify cards.

Public surface:
    PackageSynthesisResult   — synthesis output dataclass
    synthesize_package()     — LLM call producing package metadata
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from ..prompts.instruction_packs.package_action_pack import ACTION_DESIGN

logger = logging.getLogger(__name__)


@dataclass
class PackageSynthesisResult:
    package_headline:  str
    learning_thread:   str
    action_item:       str
    prompt_tokens:     int
    completion_tokens: int


def _build_synthesis_prompt(
    cards:           list[dict],
    project_name:    str,
    difficulty:      str,
    day_number:      int,
    knowledge_state: dict | None = None,
) -> str:
    lines = []
    for i, card in enumerate(cards, 1):
        title   = card.get("title", f"Card {i}")
        summary = card.get("summary", "")
        nf      = card.get("narrative_frame", "")
        ctype   = card.get("content_type", "")
        ps      = (card.get("primary_source") or {}).get("title", "")
        line    = f"{i}. [{ctype}|{nf}] {title}"
        if summary:
            line += f"\n   {summary}"
        if ps:
            line += f"\n   Source: {ps}"
        lines.append(line)
    cards_block = "\n".join(lines)

    ctx_parts = []
    if knowledge_state:
        mastered = knowledge_state.get("mastered_concepts", [])
        if mastered:
            ctx_parts.append(f"Learner has mastered: {', '.join(mastered[:5])}")
        gaps = knowledge_state.get("knowledge_gaps", [])
        if gaps:
            ctx_parts.append(f"Known gaps: {', '.join(gaps[:3])}")
    context_block = "\n".join(ctx_parts)

    return (
        f"PROJECT: {project_name}  |  DIFFICULTY: {difficulty}  |  DAY: {day_number}\n"
        + (f"\nLEARNER CONTEXT:\n{context_block}\n" if context_block else "")
        + f"\nTODAY'S GENERATED CARDS ({len(cards)} total):\n{cards_block}\n\n"
        + ACTION_DESIGN
        + "\n\n"
        + "══════════════════════════════════════\n"
        + "SYNTHESIS OUTPUT — MANDATORY\n"
        + "══════════════════════════════════════\n"
        + "Generate ONLY these 3 fields. No cards, no blocks, no explanation.\n\n"
        + "package_headline: 10-word compelling headline capturing today's editorial theme\n"
        + "  — NOT the project name. Actual themes from today's cards.\n"
        + "learning_thread: 1-2 sentences\n"
        + "  — NAME the specific concept or mechanism built across today's cards\n"
        + "  — State what progression occurred and what question remains open\n"
        + "action_item: INVESTIGATIVE MISSION (see ACTION DESIGN rules above)\n"
        + "  — Must reference a named mechanism, company, or claim from today's cards\n"
        + "  — Ends with a concrete thing to find, verify, compare, or build\n\n"
        + 'Respond ONLY with valid JSON:\n'
        + '{\n  "package_headline": "...",\n  "learning_thread": "...",\n  "action_item": "..."\n}'
    )


def synthesize_package(
    cards:              list[dict],
    project_name:       str,
    difficulty:         str,
    day_number:         int,
    knowledge_state: dict | None = None,
    project_id:      str | None = None,
) -> PackageSynthesisResult:
    """
    Generate package_headline, learning_thread, and action_item from completed cards.
    Called after all writer batches complete. Does not modify cards.
    """
    t_start = time.monotonic()

    prompt = _build_synthesis_prompt(
        cards, project_name, difficulty, day_number,
        knowledge_state=knowledge_state,
    )

    try:
        from .token_budget import estimate_tokens as _est_tok
        _prompt_tok = _est_tok(prompt)
    except Exception:
        _prompt_tok = -1

    from .writer_provider_router import route_writer_call
    from ..llm import call_and_parse_json
    # Synthesis prompt is small (card summaries only, no raw articles) — the
    # same prompt is safe for both providers, no separate compression needed.
    raw, _synth_provider = call_and_parse_json(
        lambda: route_writer_call(
            prompt, prompt,
            call_type="feed_synthesis",
            json_mode=True,
            metadata={"project_id": project_id, "day_ref": day_number} if project_id else None,
        ),
        call_type="feed_synthesis",
    )

    headline        = (raw.get("package_headline") or "").strip()
    learning_thread = (raw.get("learning_thread")  or "").strip()
    action_item     = (raw.get("action_item")      or "").strip()

    elapsed_ms = (time.monotonic() - t_start) * 1000

    logger.info(
        "[PACKAGE SYNTHESIS] day=%d  cards=%d  provider=%s  prompt_tok=%d  elapsed_ms=%.0f  "
        "headline_len=%d  thread_len=%d  action_len=%d",
        day_number, len(cards), _synth_provider, _prompt_tok, elapsed_ms,
        len(headline), len(learning_thread), len(action_item),
    )

    if not headline:
        logger.warning("[PACKAGE SYNTHESIS] package_headline missing — using fallback. raw=%s", raw)
        headline = ""
    if not learning_thread:
        logger.warning("[PACKAGE SYNTHESIS] learning_thread missing — using fallback. raw=%s", raw)
        learning_thread = ""
    if not action_item:
        logger.warning("[PACKAGE SYNTHESIS] action_item missing — using fallback. raw=%s", raw)
        action_item = ""

    return PackageSynthesisResult(
        package_headline  = headline,
        learning_thread   = learning_thread,
        action_item       = action_item,
        prompt_tokens     = 0,
        completion_tokens = 0,
    )
