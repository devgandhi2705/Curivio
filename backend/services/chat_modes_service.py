"""
Chat mode orchestration — feed-context system note formatting.

Two modes
---------
  normal        — memory/context only, fastest, no external retrieval
  web_search    — Tavily search injected before LLM call

Retrieval for web_search is now driven by the model itself via real tool
calls (chat_agent.py + chat_tools.py, Chat-4.1) — this module no longer
pre-fetches or builds mode-flag system notes for chat_stream(). It still
formats the feed-context note (build_feed_context_note) and the tool-result
formatter chat_tools.py calls after a live tool invocation
(format_reasoning_search_note).

prepare_mode_context/build_mode_system_note (the old backend-orchestrated
mode-flag pre-fetch) and their private helpers/formatters were removed —
confirmed zero callers repo-wide once chat_service.chat() (the sync /chat
path, retired) was deleted; chat_stream() never called them.

Public API
----------
build_feed_context_note(feed_context)       → str
format_reasoning_search_note(reasoning)     → str
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


_ASK_ABOUT_INSTRUCTION = """\
The user opened this card from their feed and asked the question below.

Answer THEIR question. The card is your grounding material, not your subject — do
not write a summary of the card unless that is what they asked for. A narrow question
gets a narrow, exact answer. An open one (“explain this”, “what does this mean”) is a
request for the full teach-through, so give it in full.

Work from what you actually have. The blocks above are compressed notes, not the
article: use their specifics — the named company, the mechanism, the number, the
failure mode — rather than restating them in more general language. Restating the
summary in different words is the single most common way this answer goes wrong.
When the answer turns on something only the underlying articles can settle, call
web_search on the source URLs above instead of hedging.

Make it worth reading:
- Open with the one sentence that actually answers them. No preamble, no restating
  the question, no “this card discusses…”.
- Then the mechanism — WHY it works this way, in causal steps that follow one from
  the next, not a list of characteristics.
- Give genuinely list-like material real bullets with bolded lead-ins, and leave
  genuine prose as prose. An undifferentiated wall of paragraphs is the failure mode
  here; so is bulleting something that is really one idea.
- End on what is genuinely non-obvious — the second-order effect, the thing that
  breaks, the reason a practitioner would care. Never end by summarising what you
  just wrote.

Depth means more real content — a named example, a concrete number, one more step of
mechanism, a tension between two sources. It never means longer sentences about the
same thing. If you have nothing further that is real, stop."""


def build_feed_context_note(feed_context: dict) -> str:
    """
    Format a feed insight card as a compact system note for the LLM.

    Injected before the user's first message so the model understands what
    the user is discussing without requiring a retrieval call.  The action
    field guides the model on how much context to assume is complete.

    All zoom modes (explain_simply, web_search) receive the same shared
    learning context — mechanism, project, day, difficulty — so they feel
    like depth layers of the same card, not disconnected tools.
    """
    action       = feed_context.get("action",           "ask_about")
    title        = feed_context.get("insight_title",    "")
    summary      = feed_context.get("insight_summary",  "")
    why          = feed_context.get("why_it_matters",   "")
    explanation  = feed_context.get("educational_explanation", "")
    blocks       = feed_context.get("blocks",             [])
    source_links = feed_context.get("source_links",       [])
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
        parts.append(f"Summary: {summary}")
    if why:
        parts.append(f"Why it matters: {why}")
    if explanation:
        parts.append(f"Educational explanation: {explanation}")
    if blocks:
        parts.append("Card content blocks:")
        for block in blocks:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type", "content")
            content = block.get("content", "")
            if content:
                parts.append(f"  [{block_type}] {content}")
    if sources:
        # Where the cache still holds the article text behind a source, it is
        # rendered inline under that source rather than as a bare URL. This is
        # the difference between the model reasoning from the card's own summary
        # (which the user has already read, so restating it answers nothing) and
        # reasoning from the article that produced it. Sources without cached
        # text still render exactly as before — a plain labelled URL — so a
        # partial hit degrades gracefully instead of looking broken.
        contents = feed_context.get("source_contents") or {}
        parts.append("Sources:")
        for index, url in enumerate(sources):
            link = source_links[index] if index < len(source_links) else None
            if isinstance(link, dict):
                source_title = link.get("title", "")
                label = f"{source_title}: {url}" if source_title else url
            else:
                label = url
            parts.append(f"  • {label}")
            body = (contents.get(url) or "").strip()
            if body:
                parts.append(f"    Extracted text: {body}")
        if contents:
            parts.append(
                f"({len(contents)} of {len(sources)} sources include their extracted text above — "
                "quote and reason from that text, not from the card summary. Sources shown as a bare "
                "URL were not retrieved; use web_search if the answer needs them.)"
            )

    # Prior mechanisms this user has covered in this project
    if recent_mechanisms:
        parts.append("")
        parts.append("Prior mechanisms covered in this project (build on these, do not re-explain):")
        for m in recent_mechanisms:
            parts.append(f"  • {m}")

    parts.append("")

    # ── Mode-specific instruction (references the card's mechanism directly) ──
    if action == "ask_about":
        # Phase Q: was four vague lines ("discuss it", "use the card as a starting
        # point", "reference sources naturally"), which produced what vague
        # instructions produce on a weak leg — one flat paragraph restating the
        # card's own summary in more general words, no tool call, nothing named that
        # the card had not already said. Modelled instead on
        # feed_v2/agents/section_writer.py's _SYS prompts, the best writing prompts
        # in this codebase, which share three traits this one lacked: a narrow role,
        # an explicit statement of what NOT to do, and a named output shape.
        # Guidance, not a template — a narrow question still gets a narrow answer.
        parts.append(_ASK_ABOUT_INSTRUCTION)
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
    else:  # continue_research
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

    # Structured-mode fix (Task 1): the LEARNING SYSTEM layer note used to be
    # appended here too, via learning_system_context_service.build_feed_layer_note()
    # — a second copy of the same framing the composer's own "learning_system"
    # section already adds in _build_structured_prompt, previously hardcoded to
    # a generic mode="deep_research" label so the two could actively disagree.
    # That section now reads the real feed action (chat_service.py threads it
    # into context as feed_action/feed_topic) and produces this exact note
    # itself — this is no longer the place that adds it.

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
    #
    # Web-search fix: content is already truncate_at_sentence()-capped at 2000
    # chars upstream (tavily_service._to_article / tinyfish_service.
    # fetch_as_articles, the shared per-result ingestion cap every consumer of
    # these results — Feed, deep_research, chat — reads). The [:280] cut here
    # predates that upstream cap by ~7 weeks (git blame: this line landed
    # 2026-05-24, the 2000-char cap 2026-07-11) and was never revisited once it
    # became redundant — confirmed no comment or commit message anywhere states
    # a real reason for 280 specifically (UI space, token budget), and this
    # content only ever reaches the model (chat_tools.py's own docstring: the
    # tool's `content` return is what the model reads; `artifact`, the only
    # user-facing part, carries just {title, url} — never this snippet text).
    # Recon's real numbers: 2000 sentence-aware chars vs. a hard 280-char
    # midsentence cut was routinely starving the model of the part of a
    # result that actually answered the question.
    if supporting:
        lines.append("\nSUPPORTING EVIDENCE — confirms or elaborates the mainstream understanding:")
        for i, a in enumerate(supporting, 1):
            title   = a.get("title", "").strip()
            content = (a.get("content") or "").strip()
            url     = a.get("url", "")
            lines.append(f"\n  [{i}] {title}\n      {content}\n      Source: {url}")

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
            lines.append(f"\n  [{i}] ⚑ {title}\n      {content}\n      Source: {url}")

    # Synthesis requirements
    lines.append("\nSYNTHESIS REQUIREMENTS — enforce every rule:")
    lines.append(
        "- Extract cross-source PATTERNS — never summarise articles one by one."
    )
    lines.append(
        "- Cite claims to their source using the bracketed number shown next to each result above — "
        "e.g. 'the market grew 5% [1]'. Stack multiple numbers when a claim draws on more than one "
        "source, e.g. '[1][3]'. Only cite a number for a claim that source genuinely supports — never "
        "invent a number, and leave genuinely uncited claims (your own synthesis, general knowledge) "
        "unmarked."
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

