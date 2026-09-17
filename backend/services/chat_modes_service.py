"""
Chat mode orchestration — system note formatting for chat_service.

Two note formatters, both plain string builders with no I/O of their own:

  build_feed_context_note      — the Feed card note. When a chat turn opens
                                  from a Feed card, chat_service injects this
                                  before the user's first message so the model
                                  has the card's title/summary/sources/mechanism
                                  without a retrieval call.
  format_reasoning_search_note — the search-results note. Chat-routing v2's
                                  classifier (chat_router) decides a turn needs
                                  a web search, web_search_reasoning_service
                                  runs it, and chat_service injects this note
                                  with the results — there is no model-invoked
                                  search tool anymore.

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
import re

logger = logging.getLogger(__name__)


_ASK_ABOUT_INSTRUCTION = (
    "The user opened this card from their feed and asked the question below. Answer THEIR "
    "question: the card is grounding, not the subject, so don't summarise it unless that is what "
    'they asked. A narrow question gets a narrow, exact answer; an open one ("explain this") gets '
    "the full teach-through. The blocks above are compressed notes — use their specifics (the "
    "named company, the mechanism, the number, the failure mode) instead of restating the summary "
    "in more general words."
)

_MD_IMAGE_RE     = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK_ONLY_RE = re.compile(r"^\s*[-*]?\s*\[[^\]]*\]\([^)]*\)\s*$")
_MD_LINK_RE      = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_BARE_URL_RE     = re.compile(r"^\s*https?://\S+\s*$")


def _clean_extracted_text(text: str) -> str:
    """Page markdown as retrieved is mostly furniture. A real sample: 1.9K chars
    whose first 700 were a logo, a newsletter prompt repeated twice, and avatar
    images. Images and link-only nav lines go; a heading's link TEXT stays
    (that is usually the article title); repeated lines are kept once."""
    kept: list[str] = []
    seen: set[str] = set()
    for raw_line in (text or "").splitlines():
        line = _MD_IMAGE_RE.sub("", raw_line).rstrip()
        if not line.strip() or _MD_LINK_ONLY_RE.match(line) or _BARE_URL_RE.match(line):
            continue
        line = _MD_LINK_RE.sub(r"\1", line).strip()
        if not line or line in seen:
            continue
        seen.add(line)
        kept.append(line)
    return "\n".join(kept)


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
        # Skip a block that just repeats the summary or "Why it matters" line —
        # real cards carry the mechanism in both, which is two of the up-to-four
        # copies of the same sentence this task removes.
        already_said = {(summary or "").strip(), (why or "").strip()}
        block_lines = [f"  [{b.get('type', 'content')}] {b.get('content', '')}"
                       for b in blocks
                       if isinstance(b, dict) and b.get("content")
                       and b["content"].strip() not in already_said]
        if block_lines:
            parts.append("Card content blocks:")
            parts.extend(block_lines)
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
            body = _clean_extracted_text(contents.get(url) or "")
            if body:
                parts.append(f"    Extracted text: {body}")
        if contents:
            parts.append(
                f"({len(contents)} of {len(sources)} sources include their extracted text above — "
                "quote and reason from that text, not from the card summary.)"
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
        # The mechanism sentence itself is already above (it IS the card's "Why
        # it matters" line, or the first line of its summary). It used to be
        # pasted again here AND again in the system prompt — up to four copies
        # of the same sentence in one prompt.
        anchor = "the “Why it matters” line" if why else "the summary above"
        parts.append(
            "The user wants this card explained in the simplest, most intuitive terms. Keep its "
            f"core mechanism — {anchor} — intact: simplify the vocabulary, not the logic."
        )

    return "\n".join(parts)


# Chat-4.3: stream_status_event removed — confirmed genuinely orphaned (zero
# real callers repo-wide, only its own unit tests). It drove the pre-fetch
# status line for the OLD backend-orchestrated web_search/deep_research
# retrieval; chat_stream doesn't pre-fetch anymore (chat_service now runs the
# web search step itself and emits its own tool_start/tool_end status events).

# Chat-4.2: stream_research_progress removed — confirmed genuinely orphaned
# (Chat-4.1 recon found zero callers in chat_service.py; this phase's recon
# re-confirmed zero callers anywhere in the repo, backend or frontend, beyond
# its own direct unit tests). The per-stage status UX it drove is superseded
# by chat_service's own tool_start/tool_end status events around its web
# search step, and deep_research_service's own plan->act->replan subgraph
# logging (Chat-4.2) — there was no real remaining use to wire it to.


# ═══════════════════════════════════════════════════════════════════════════════
# Note formatters
# ═══════════════════════════════════════════════════════════════════════════════

def format_reasoning_search_note(reasoning: dict) -> str:
    """The system note that carries search results into the turn.

    Was ~2K chars of instruction: a four-step internal ritual (PRIOR POSITION /
    EVIDENCE CHECK / POSITION UPDATE / OPEN QUESTIONS), a MANDATORY "What the
    data complicates" section on every search turn whether or not anything
    conflicted, and rules the system prompt already carries. What stays is what
    the citations and the frontend depend on: one contiguous 1..N numbering
    across both result sets (so [N] resolves to sources[N-1]) and the rules
    specific to reading search results.
    """
    supporting   = reasoning.get("supporting", [])
    complicating = reasoning.get("complicating", [])
    queries = [q for q in (reasoning.get("primary_query"), reasoning.get("contradiction_query")) if q]

    lines = ["[WEB SEARCH RESULTS]"]
    if queries:
        lines.append("Searched: " + " · ".join(f'"{q[:120]}"' for q in queries))

    for index, article in enumerate(supporting + complicating, 1):
        marker  = " ⚑" if index > len(supporting) else ""
        title   = (article.get("title") or "").strip()
        content = (article.get("content") or "").strip()
        lines.append(f"\n  [{index}]{marker} {title}\n      {content}\n      Source: {article.get('url', '')}")

    lines.append(
        "\nHow to use these results:"
        "\n- Open with the substantive finding, not with what was searched. Draw patterns across "
        "sources rather than summarising them one by one."
        '\n- Cite claims with the bracketed source number, e.g. "the market grew 5% [1]"; stack '
        'numbers when several sources support a claim ("[1][3]"). Cite only what that source '
        "genuinely supports, and leave your own synthesis uncited."
    )
    if complicating:
        lines.append(
            "- Results marked ⚑ came from a deliberately contradicting search. Where they genuinely "
            "conflict with the rest, say what each claims and what the conflict means for the "
            'conclusion, under a short "What the data complicates" heading.'
        )
    else:
        lines.append("- If two sources contradict each other, surface the disagreement explicitly.")
    return "\n".join(lines)
