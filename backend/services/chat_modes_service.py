"""
Chat mode orchestration — mode-specific context preparation.

Three modes
-----------
  normal        — memory/context only, fastest, no external retrieval
  web_search    — Tavily search injected before LLM call
  deep_research — full DeepResearchWorkflow; always uses web retrieval

Public API
----------
prepare_mode_context(mode, message, topic)  → dict
build_mode_system_note(mode_context)        → str
stream_status_event(mode)                   → str | None  (NDJSON line)
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

VALID_MODES = ("normal", "web_search", "deep_research", "layman")

_WEB_SEARCH_MAX_ARTICLES  = 5
_DEEP_RESEARCH_SUMMARY_LEN = 600
_DEEP_RESEARCH_FINDINGS    = 4


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

_STAGE_EXPANSION_ANGLES: dict[str, str] = {
    "foundation":   "implications downstream effects practical consequences",
    "mechanisms":   "system dependencies fragility upstream vulnerabilities failure modes",
    "dependencies": "geopolitical regulatory risk who controls who wins who loses",
    "optimization": "competitive dynamics incumbents structural advantage moat",
    "geopolitical": "cross-domain technology disruption second-order effects",
    "disruption":   "strategic synthesis future scenarios long-term structural shifts",
    "synthesis":    "cross-domain connections adjacent industries paradigm implications",
}


def prepare_mode_context(
    mode: str,
    message: str,
    topic: str | None,
    query_type: str = "default",
    subjects: list[str] | None = None,
    intent_profile: dict | None = None,
    domain: str = "",
    feed_context: dict | None = None,
) -> dict:
    """
    Return mode-specific additions to be merged into the chat context dict.

    Always safe to call — errors in retrieval are caught and return an empty
    result so the calling code can fall back to normal chat gracefully.

    Parameters
    ----------
    query_type : "default" | "comparison" | "research" | "analysis"
        Affects how retrieval queries are constructed and how the system note
        is formatted for the LLM.
    subjects   : two-item list for comparison queries (e.g. ["PyTorch", "TensorFlow"])
    """
    if mode not in VALID_MODES:
        logger.warning("[chat_modes] unknown mode %r — falling back to normal", mode)
        return {}

    if mode == "normal":
        return {}

    if mode == "layman":
        # No retrieval — context comes entirely from system prompt + feed context
        return {"mode": "layman"}

    if mode == "web_search":
        return _fetch_web_context(
            message, topic,
            query_type=query_type, subjects=subjects or [],
            intent_profile=intent_profile, domain=domain,
            feed_context=feed_context,
        )

    # deep_research
    return _fetch_deep_research_context(message, topic, query_type=query_type, feed_context=feed_context)


def build_mode_system_note(mode_context: dict) -> str:
    """
    Render the mode-specific retrieval data as a compact system note.

    The note is injected as a system message just before the last user turn
    so the LLM sees retrieval data immediately before generating its answer.
    Returns an empty string for normal mode or when no data was retrieved.
    """
    mode       = mode_context.get("mode", "normal")
    query_type = mode_context.get("query_type", "default")

    if mode == "web_search":
        articles = mode_context.get("web_search_results", [])
        if not articles:
            return "[WEB SEARCH]: No results retrieved for this query."
        if query_type == "comparison":
            return _format_comparison_note(mode_context, articles)
        reasoning = mode_context.get("reasoning_search")
        if reasoning and reasoning.get("all_articles"):
            return _format_reasoning_search_note(reasoning)
        return _format_web_search_note(articles)

    if mode == "deep_research":
        result = mode_context.get("deep_research_result")
        if not result or not isinstance(result, dict):
            return "[DEEP RESEARCH]: No research data available for this topic."
        if query_type == "analysis":
            return _format_analysis_note(result)
        return _format_research_note(result)

    return ""


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


def stream_status_event(mode: str) -> str | None:
    """
    Return a `{"t":"status","v":"..."}` NDJSON line for modes that do
    retrieval before streaming, or None for normal/layman mode.
    """
    if mode == "web_search":
        return json.dumps({"t": "status", "v": "Searching the web…"}) + "\n"
    if mode == "deep_research":
        return json.dumps({"t": "status", "v": "Starting deep research…"}) + "\n"
    return None


def stream_research_progress(
    message: str,
    topic: str | None,
    query_type: str = "default",
    feed_context: dict | None = None,
):
    """
    Generator — yields ``("status", text)`` tuples as each research stage runs,
    then yields ``("result", mode_context_dict)`` once all stages complete.

    Callers (chat_service) iterate this and forward status strings as
    ``{"t":"status","v":"..."}`` NDJSON events before the LLM call.

    Designed to be called instead of ``prepare_mode_context`` for
    deep_research mode; web_search and normal modes are unaffected.
    """
    from .deep_research_service import get_stored_research, DeepResearchWorkflow

    # When coming from a feed card: branch outward from the card's mechanism
    if feed_context and feed_context.get("mechanism"):
        mechanism = feed_context["mechanism"]
        title     = feed_context.get("insight_title", "")
        stage     = feed_context.get("progression_stage", "")
        expansion = _STAGE_EXPANSION_ANGLES.get(stage, "adjacent systems strategic implications")
        query = f"{title} {mechanism} {expansion}"
        query = query[:250]
    else:
        query = (topic or message)[:200]

    # Fast path — cached result needs no stage progress
    cached = get_stored_research(query)
    if cached is not None:
        logger.debug("[chat_modes] deep research cache hit for %r", query[:60])
        yield ("status", "Loading cached research…")
        yield ("result", {
            "mode":                 "deep_research",
            "query_type":           query_type,
            "deep_research_result": cached,
            "articles":             cached.get("articles", []) if isinstance(cached, dict) else [],
        })
        return

    # Stage-by-stage with status labels
    _STAGE_LABELS = {
        "expand_queries":    "Expanding search angles…",
        "fetch_articles":    "Searching sources…",
        "rank_articles":     "Ranking results…",
        "extract_viewpoints": "Comparing perspectives…",
        "generate":          "Generating findings…",
        "persist":           "Finalizing report…",
    }

    try:
        wf = DeepResearchWorkflow(query)
        for stage in DeepResearchWorkflow.STAGES:
            label = _STAGE_LABELS.get(stage, stage.replace("_", " ").capitalize() + "…")
            yield ("status", label)
            try:
                getattr(wf, stage)()
            except Exception:
                logger.warning("[chat_modes] deep research stage %r failed (non-fatal)", stage)

        yield ("result", {
            "mode":                 "deep_research",
            "query_type":           query_type,
            "deep_research_result": wf.state.get("result") or None,
            "articles":             wf.state.get("articles", []),
        })
    except Exception:
        logger.exception("[chat_modes] deep research workflow failed")
        yield ("result", {
            "mode":                 "deep_research",
            "query_type":           query_type,
            "deep_research_result": None,
            "articles":             [],
        })


# ═══════════════════════════════════════════════════════════════════════════════
# Note formatters
# ═══════════════════════════════════════════════════════════════════════════════

def _format_web_search_note(articles: list[dict]) -> str:
    """Fallback formatter used when reasoning_search data is unavailable."""
    lines = ["[WEB SEARCH CONTEXT — synthesise these into your answer]"]
    for i, a in enumerate(articles[:_WEB_SEARCH_MAX_ARTICLES], 1):
        title   = a.get("title", "").strip()
        content = (a.get("content") or "").strip()
        url     = a.get("url", "")
        snippet = content[:300] + ("…" if len(content) > 300 else "")
        lines.append(f"\n[{i}] {title}\n    {snippet}\n    Source: {url}")
    lines.append(
        "\nSynthesis rules — enforce strictly:"
        "\n- Deduplicate: if multiple sources report the same fact, state it ONCE using the most detailed version."
        "\n- DO NOT repeat the same information in both a paragraph and a bullet list."
        "\n- Extract PATTERNS across sources — do not summarise sources one by one."
        "\n- If sources contradict each other, surface the disagreement explicitly — name what each says."
        "\n- Cite inline naturally ('According to Bloomberg…', 'A recent study found…') — not as footnotes."
        "\n- Match depth to question complexity: a factual query gets a direct answer, not an essay."
        "\n- The response should feel like a fast, informed briefing — not a digest of search results."
    )
    return "\n".join(lines)


def _format_reasoning_search_note(reasoning: dict) -> str:
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


def _format_comparison_note(mode_context: dict, articles: list[dict]) -> str:
    subjects = mode_context.get("subjects", [])
    label    = f"{subjects[0]} vs {subjects[1]}" if len(subjects) >= 2 else "Comparison"
    lines    = [f"[WEB SEARCH — COMPARISON: {label}]"]
    lines.append("Retrieved context:")
    for i, a in enumerate(articles[:_WEB_SEARCH_MAX_ARTICLES], 1):
        title   = a.get("title", "").strip()
        content = (a.get("content") or "").strip()
        url     = a.get("url", "")
        snippet = content[:250] + ("…" if len(content) > 250 else "")
        lines.append(f"\n[{i}] {title}\n    {snippet}\n    Source: {url}")
    lines.append(
        "\nAnalysis rules — enforce strictly:"
        "\n- Do NOT write 'A has X, B has Y' parallel descriptions — analyse ACROSS dimensions with causality."
        "\n  BAD: 'China dominates APIs.' GOOD: 'China dominates APIs because vertically integrated"
        "\n  state-supported manufacturing creates margins competitors structurally cannot match.'"
        "\n- For each dimension of difference: explain WHY each subject occupies its position."
        "\n  Name the structural, economic, or incentive force behind each difference."
        "\n- Dimensions to analyse: structural differences, economics, competitive moats,"
        "\n  hidden dependencies, regulatory or geopolitical vectors, and practical verdict."
        "\n- Deliver a clear verdict with explicit reasoning — not 'both have advantages.'"
        "\n- Use headers/structure only where genuinely clearer than analytical prose."
    )
    return "\n".join(lines)


def _format_research_note(result: dict) -> str:
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


def _format_analysis_note(result: dict) -> str:
    topic    = result.get("topic", "")
    summary  = (result.get("research_summary") or result.get("executive_summary") or "").strip()
    findings = result.get("key_findings", [])
    lines    = [f"[DEEP RESEARCH — ANALYSIS REQUEST: {topic}]"]
    if summary:
        lines.append(f"Research context: {summary[:_DEEP_RESEARCH_SUMMARY_LEN]}")
    if findings:
        lines.append("Evidence points:")
        for f in findings[:_DEEP_RESEARCH_FINDINGS]:
            lines.append(f"  • {f}")
    contrarian = result.get("contrarian_view", "")
    if contrarian:
        lines.append(f"Contrarian view: {contrarian[:200]}")
    lines.append(
        "\nAnalytical framework — work through ALL of these before writing:"
        "\n1. Core MECHANISM: what structural force or dynamic is driving this situation?"
        "\n2. Hidden DRIVERS: what does conventional coverage underweight or miss entirely?"
        "\n3. KEY TENSIONS: what tradeoffs do practitioners actually face — with real costs?"
        "\n4. CONVERGENCE vs DIVERGENCE: where do the data points agree and where do they conflict?"
        "\n5. STRATEGIC IMPLICATIONS: what concrete decision does this create for a practitioner?"
        "\n6. SECOND-ORDER EFFECTS: what does this situation cause that will matter in 2–5 years?"
        "\n\nWrite like a sharp analyst — name mechanisms and causality, not just patterns:"
        "\n- NOT 'X is growing' — but 'X grows because Y creates incentive Z, which produces outcome W'"
        "\n- Name specifics: actors, events, data points, named mechanisms"
        "\n- Surface the non-obvious: what is the conventional framing getting wrong?"
        "\n- Use ## headers for distinct analytical dimensions; bullets for parallel evidence points"
    )
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Retrieval helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _fetch_web_context(
    message: str,
    topic: str | None,
    query_type: str = "default",
    subjects: list[str] | None = None,
    intent_profile: dict | None = None,
    domain: str = "",
    feed_context: dict | None = None,
) -> dict:
    if query_type == "comparison" and subjects and len(subjects) >= 2:
        search_message = f"{subjects[0]} vs {subjects[1]}"
    elif feed_context and feed_context.get("mechanism"):
        # Anchor on the card's specific mechanism claim, not just the title
        mechanism = feed_context["mechanism"]
        project   = feed_context.get("project_name", "")
        search_message = f"{mechanism} {project} evidence current 2025 examples"
        search_message = search_message[:220]
    else:
        search_message = (topic or message)[:200]

    try:
        from .web_search_reasoning_service import fetch_reasoned_results
        reasoning = fetch_reasoned_results(search_message, intent_profile, domain)
        return {
            "mode":               "web_search",
            "query_type":         query_type,
            "subjects":           subjects or [],
            "web_search_results": reasoning["all_articles"],
            "reasoning_search":   reasoning,
        }
    except Exception:
        logger.warning("[chat_modes] reasoning web search failed — falling back to plain search")
        try:
            from .retrieval_router import route
            articles = route(search_message, mode="chat")
        except Exception:
            logger.warning("[chat_modes] web search failed for query %r", search_message[:60])
            articles = []
        return {
            "mode":               "web_search",
            "query_type":         query_type,
            "subjects":           subjects or [],
            "web_search_results": articles,
            "reasoning_search":   None,
        }


def _fetch_deep_research_context(
    message: str,
    topic: str | None,
    query_type: str = "default",
    feed_context: dict | None = None,
) -> dict:
    if feed_context and feed_context.get("mechanism"):
        mechanism = feed_context["mechanism"]
        title     = feed_context.get("insight_title", "")
        stage     = feed_context.get("progression_stage", "")
        expansion = _STAGE_EXPANSION_ANGLES.get(stage, "adjacent systems strategic implications")
        query = f"{title} {mechanism} {expansion}"
        query = query[:250]
    else:
        query = (topic or message)[:200]
    try:
        from .deep_research_service import run_deep_research
        result = run_deep_research(query)
        return {
            "mode":                 "deep_research",
            "query_type":           query_type,
            "deep_research_result": result,
        }
    except Exception:
        logger.warning("[chat_modes] deep research failed for query %r", query[:60])
        return {
            "mode":                 "deep_research",
            "query_type":           query_type,
            "deep_research_result": None,
        }
