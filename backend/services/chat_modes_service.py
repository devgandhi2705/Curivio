"""
Chat mode orchestration — feed-context system note formatting.

Three modes
-----------
  normal        — memory/context only, fastest, no external retrieval
  web_search    — Tavily search injected before LLM call
  deep_research — full DeepResearchWorkflow; always uses web retrieval

Retrieval for web_search/deep_research is now driven by the model itself via
real tool calls (chat_agent.py + chat_tools.py, Chat-4.1) — this module no
longer pre-fetches or builds mode-flag system notes for chat_stream(). It
still formats the feed-context note (build_feed_context_note) and the two
tool-result formatters chat_tools.py calls after a live tool invocation
(format_reasoning_search_note, format_research_note).

prepare_mode_context/build_mode_system_note (the old backend-orchestrated
mode-flag pre-fetch) and their private helpers/formatters were removed —
confirmed zero callers repo-wide once chat_service.chat() (the sync /chat
path, retired) was deleted; chat_stream() never called them.

Public API
----------
build_feed_context_note(feed_context)       → str
format_reasoning_search_note(reasoning)     → str
format_research_note(result)                → str
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_DEEP_RESEARCH_SUMMARY_LEN = 600
_DEEP_RESEARCH_FINDINGS    = 4


def build_feed_context_note(feed_context: dict) -> str:
    """
    Format a feed insight card as a compact system note for the LLM.

    Injected before the user's first message so the model understands what
    the user is discussing without requiring a retrieval call.  The action
    field guides the model on how much context to assume is complete.

    All three zoom modes (explain_simply, web_search, deep_research) receive the
    same shared learning context — mechanism, project, day, difficulty — so they
    feel like depth layers of the same card, not disconnected tools.
    """
    action       = feed_context.get("action",           "ask_about")
    title        = feed_context.get("insight_title",    "")
    summary      = feed_context.get("insight_summary",  "")
    why          = feed_context.get("why_it_matters",   "")
    sources      = feed_context.get("source_urls",      [])
    project      = feed_context.get("project_name",     "")
    domain       = feed_context.get("domain",           "")
    content_type = feed_context.get("content_type",     "")
    # Enriched fields (set by _enrich_feed_context in chat_service)
    mechanism         = feed_context.get("mechanism",         "")
    current_day       = feed_context.get("current_day",       "")
    difficulty        = feed_context.get("difficulty_level",  "")
    progression_stage = feed_context.get("progression_stage", "")
    recent_mechanisms = feed_context.get("recent_mechanisms", [])

    _ACTION_LABELS = {
        "ask_about":         "Discussion",
        "continue_research": "Extended Research",
        "deep_research":     "Deep Research",
        "explain_simply":    "Simple Explanation",
    }
    label = _ACTION_LABELS.get(action, "Feed Insight")

    parts = [f"[FEED INSIGHT — {label}]"]

    # ── Shared learning context (all modes receive this) ──────────────────────
    context_parts: list[str] = []
    if project:
        context_parts.append(f"Project: {project}")
    if current_day:
        context_parts.append(f"Session: {current_day}")
    if difficulty:
        context_parts.append(f"Difficulty: {difficulty}")
    if progression_stage:
        context_parts.append(f"Stage: {progression_stage}")
    if context_parts:
        parts.append("  ".join(context_parts))

    meta = " | ".join(filter(None, [domain, content_type]))
    if meta:
        parts.append(f"Domain/Type: {meta}")
    parts.append("")
    parts.append(f"Card: {title}")
    if summary:
        parts.append(f"Summary: {summary[:500]}")
    if why:
        parts.append(f"Mechanism: {why[:400]}")
    if sources:
        parts.append("Sources:")
        for url in sources[:3]:
            parts.append(f"  • {url}")

    # Prior mechanisms this user has covered in this project
    if recent_mechanisms:
        parts.append("")
        parts.append("Prior mechanisms covered in this project (build on these, do not re-explain):")
        for m in recent_mechanisms:
            parts.append(f"  • {m}")

    parts.append("")

    # ── Mode-specific instruction (references the card's mechanism directly) ──
    if action == "ask_about":
        parts.append(
            "The user opened this card from their feed and wants to discuss it. "
            "Answer directly from the context above — do NOT search the web. "
            "Reference the summary and sources naturally."
        )
    elif action == "explain_simply":
        if mechanism:
            parts.append(
                f"The user wants this card explained in the simplest, most intuitive terms. "
                f"PRESERVE THIS SPECIFIC MECHANISM: \"{mechanism[:200]}\" "
                f"— simplify the vocabulary, not the intelligence. "
                f"Use the Explain Simply structure from your system prompt. "
                f"Do NOT search the web — the card above is sufficient."
            )
        else:
            parts.append(
                "The user wants this topic explained in the simplest, most intuitive way possible. "
                "Use the feed insight above as the source material. "
                "Do NOT search the web — the context above is sufficient. "
                "Follow the Explain Simply mode instructions in your system prompt."
            )
    elif action == "continue_research":
        if mechanism:
            parts.append(
                f"ZOOM LEVEL: Reality Validation. "
                f"The card established this mechanism: \"{mechanism[:200]}\" "
                f"Use the web search results below to VALIDATE, EXTEND, or CHALLENGE this specific claim "
                f"with current evidence and live examples. "
                f"Open with what the evidence confirms or contradicts — not with a re-summary of the card."
            )
        else:
            parts.append(
                "The user wants to dig deeper into this topic beyond the feed insight. "
                "Use the feed context as background knowledge and the web search results "
                "below to expand with new angles and recent developments."
            )
    else:  # deep_research
        if mechanism:
            parts.append(
                f"ZOOM LEVEL: Strategic Expansion. "
                f"The card's mechanism is the seed: \"{mechanism[:200]}\" "
                f"Branch outward from here — explore adjacent systems, strategic implications, "
                f"what the surface framing consistently misses, and second-order consequences. "
                f"Do NOT re-explain what the card already established. "
                f"Use the deep research results below to extend into new territory."
            )
        else:
            parts.append(
                "The user wants comprehensive research starting from this feed insight. "
                "Use the feed context as the seed and the deep research results below "
                "to produce a thorough, multi-angle analysis."
            )

    # Learning system layer note — positions this in the depth hierarchy
    try:
        from .learning_system_context_service import build_feed_layer_note
        layer_note = build_feed_layer_note(action, title)
        if layer_note:
            parts.append("")
            parts.append(layer_note)
    except Exception:
        pass

    return "\n".join(parts)


# Chat-4.3: stream_status_event removed — confirmed genuinely orphaned (zero
# real callers repo-wide, only its own unit tests). It drove the pre-fetch
# status line for the OLD backend-orchestrated web_search/deep_research
# retrieval; chat_stream doesn't pre-fetch anymore (Chat-4.1's real tool
# calls surface their own tool_start status events instead).

# Chat-4.2: stream_research_progress removed — confirmed genuinely orphaned
# (Chat-4.1 recon found zero callers in chat_service.py; this phase's recon
# re-confirmed zero callers anywhere in the repo, backend or frontend, beyond
# its own direct unit tests). The per-stage status UX it drove is superseded
# by chat_agent.ask_chat_stream's real tool_start/tool_end events (Chat-4.1)
# and deep_research_service's own plan->act->replan subgraph logging
# (Chat-4.2) — there was no real remaining use to wire it to.


# ═══════════════════════════════════════════════════════════════════════════════
# Note formatters
# ═══════════════════════════════════════════════════════════════════════════════

def format_reasoning_search_note(reasoning: dict) -> str:
    """
    Reasoning-first system note for web search mode.

    Splits results into supporting vs. complicating sections and instructs the
    LLM to: (1) state its prior position before incorporating results, (2)
    explicitly update conclusions where complicating evidence warrants it, and
    (3) include a 'What the data complicates' section when contradictions exist.
    """
    p_query  = reasoning.get("primary_query",       "")
    c_query  = reasoning.get("contradiction_query",  "")
    supporting   = reasoning.get("supporting",   [])
    complicating = reasoning.get("complicating",  [])
    has_complicating = reasoning.get("has_complicating", False)

    lines = ["[REASONING-AUGMENTED WEB SEARCH]"]
    lines.append(
        "\nSearch covered two angles deliberately:"
        f"\n  • Primary:      \"{p_query[:120]}\""
        f"\n  • Contradiction: \"{c_query[:120]}\""
    )

    lines.append(
        "\nBEFORE incorporating these results, work through this sequence internally:"
        "\n  1. PRIOR POSITION — What would you have concluded without this search data? Identify it."
        "\n  2. EVIDENCE CHECK — Which results support your prior? Which complicate or contradict it?"
        "\n  3. POSITION UPDATE — Revise explicitly where the evidence changes your conclusion."
        "\n  4. OPEN QUESTIONS — What remains genuinely unresolved after seeing this evidence?"
    )

    # Supporting results
    if supporting:
        lines.append("\nSUPPORTING EVIDENCE — confirms or elaborates the mainstream understanding:")
        for i, a in enumerate(supporting, 1):
            title   = a.get("title", "").strip()
            content = (a.get("content") or "").strip()
            url     = a.get("url", "")
            snippet = content[:280] + ("…" if len(content) > 280 else "")
            lines.append(f"\n  [{i}] {title}\n      {snippet}\n      Source: {url}")

    # Complicating results
    if complicating:
        lines.append(
            "\nCOMPLICATING EVIDENCE — challenges assumptions, surfaces recent shifts, "
            "or contradicts the expected conclusion:"
        )
        offset = len(supporting)
        for i, a in enumerate(complicating, offset + 1):
            title   = a.get("title", "").strip()
            content = (a.get("content") or "").strip()
            url     = a.get("url", "")
            snippet = content[:280] + ("…" if len(content) > 280 else "")
            lines.append(f"\n  [{i}] ⚑ {title}\n      {snippet}\n      Source: {url}")

    # Synthesis requirements
    lines.append("\nSYNTHESIS REQUIREMENTS — enforce every rule:")
    lines.append(
        "- Extract cross-source PATTERNS — never summarise articles one by one."
    )
    lines.append(
        "- Cite inline naturally: 'According to Bloomberg…', 'A recent study found…' — not as footnotes."
    )
    if has_complicating:
        lines.append(
            "- MANDATORY: include a 'What the data complicates' or 'Where this assumption breaks' section."
            "\n  BAD:  'Here are articles supporting Indian pharma growth.'"
            "\n  GOOD: 'Recent FDA warning letters suggest quality issues remain uneven despite export growth,"
            "\n         complicating the assumption that the sector is uniformly improving.'"
        )
        lines.append(
            "- Where complicating evidence conflicts with supporting evidence: name what each claims"
            "\n  and explicitly state what the contradiction means for the overall conclusion."
        )
    else:
        lines.append(
            "- If any source contradicts another: surface the disagreement explicitly — name what each says."
        )
    lines.append(
        "- DO NOT open with a summary of what you searched for — open with the substantive finding."
        "\n- The response must feel like informed, updated reasoning — not a digest of search results."
    )

    return "\n".join(lines)


def format_research_note(result: dict) -> str:
    topic    = result.get("topic", "")
    summary  = (result.get("research_summary") or result.get("executive_summary") or "").strip()
    findings = result.get("key_findings", [])
    lines    = [f"[DEEP RESEARCH REPORT: {topic}]"]
    if summary:
        lines.append(f"Core finding: {summary[:_DEEP_RESEARCH_SUMMARY_LEN]}")
    if findings:
        lines.append("Evidence points:")
        for f in findings[:_DEEP_RESEARCH_FINDINGS]:
            lines.append(f"  • {f}")
    # viewpoint_comparison is the correct key from deep_research_prompt.py
    viewpoints = result.get("viewpoint_comparison", []) or result.get("viewpoints", [])
    if viewpoints:
        lines.append("Perspectives in tension:")
        for v in viewpoints[:2]:
            perspective = v.get("perspective") or v.get("angle") or v.get("label", "")
            stance      = (v.get("stance") or v.get("summary") or v.get("insight", ""))[:160]
            if perspective:
                lines.append(f"  [{perspective}] {stance}")
    contrarian = result.get("contrarian_view", "")
    if contrarian:
        lines.append(f"Contrarian view: {contrarian[:200]}")
    shifts = result.get("what_shifts_next", "")
    if shifts:
        lines.append(f"What shifts next: {shifts[:200]}")
    lines.append(
        "\nAnalytical framework — work through ALL of these before writing:"
        "\n1. What do sources AGREE on? (establish the foundation — avoid restating the obvious)"
        "\n2. Where do they CONTRADICT? (surface disagreement explicitly — name what each position claims)"
        "\n3. Hidden TRADEOFFS and costs that most coverage underweights?"
        "\n4. What does HISTORICAL EVOLUTION reveal about why this is the way it is?"
        "\n5. STRATEGIC IMPLICATIONS — what concrete decision does this create for a practitioner?"
        "\n6. What remains GENUINELY UNRESOLVED — where do experts still actively disagree?"
        "\n7. CONTRARIAN VIEW — what is the conventional framing getting wrong or underweighting?"
        "\n\nWrite like an analyst memo, not a research summary:"
        "\n- Open with the single most important synthesised insight — not background or topic introduction"
        "\n- For every claim: name the causal mechanism — not 'X is growing' but 'X grows because Y'"
        "\n  creates incentive Z, which produces outcome W'"
        "\n- Include a 'What Shifts Next' section: name the specific force that will change the equilibrium"
        "\n- Surface the underpriced risk: what is the market or conventional wisdom getting wrong?"
        "\n- Use ## headers for clearly distinct analytical dimensions — they should aid navigation"
        "\n- Prioritise insight density over exhaustive coverage"
    )
    return "\n".join(lines)

