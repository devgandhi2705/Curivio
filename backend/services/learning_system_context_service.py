"""
Learning System Context Service.

Unifies feed, explain simply, chat, and web search into one coherent
learning identity by injecting a compact "LEARNING SYSTEM" framing section
into every system prompt.

The section positions the current mode in the depth hierarchy, shows what the
user has already established on this topic, and states the specific analytical
objective for this particular depth layer.

The user should feel: "I am continuously evolving my understanding."
NOT: "I am switching between disconnected AI tools."

Depth hierarchy
---------------
  Discover      (feed)           Surface-level insight introduction
  Understand    (layman)         Abstraction compression; intuition first
  Explore       (normal chat)    Interactive mechanism-building
  Validate      (web_search)     Reality-test analytical conclusions

Public API
----------
build_learning_system_section(context: dict, mode: str) -> str
"""

from __future__ import annotations

# ── Depth layer definitions ───────────────────────────────────────────────────

_LAYER_META: dict[str, dict] = {
    "normal": {
        "label":     "Interactive Exploration",
        "objective": "Build understanding by asking, pushing back, and following threads to their structural roots.",
        "mission":   (
            "Every answer should open one thread the user hasn't yet pulled. "
            "Go deeper than the question asks. Leave something genuinely unresolved."
        ),
        "next_layer": "Web Search — to validate conclusions against current evidence",
    },
    "layman": {
        "label":     "Abstraction Compression",
        "objective": "Compress complexity into intuition without losing the underlying mechanism.",
        "mission":   (
            "The goal is the 'I finally understand this' moment — not simplified vocabulary, "
            "but the full intelligence of the idea in language the user already speaks."
        ),
        "next_layer": "Chat Exploration — to ask questions and build deeper mechanisms",
    },
    "web_search": {
        "label":     "Reality Validation",
        "objective": "Test analytical conclusions against current evidence — confirm, challenge, or update them.",
        "mission":   (
            "Do not use evidence only to confirm. Actively find where reality complicates, "
            "contradicts, or updates what was established analytically. "
            "The most valuable finding is one that changes the conclusion."
        ),
        "next_layer": None,
    },
}

# Fallback for modes not explicitly mapped
_DEFAULT_LAYER = {
    "label":     "Learning Session",
    "objective": "Build understanding interactively.",
    "mission":   "Go deeper than the surface. Surface mechanisms and leave threads open.",
    "next_layer": None,
}

# How many mechanisms / unresolved questions to show (keep the section compact)
_MAX_MECHANISMS_SHOWN  = 3
_MAX_UNRESOLVED_SHOWN  = 1


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def build_learning_system_section(context: dict, mode: str) -> str:
    """
    Build the LEARNING SYSTEM framing section for the system prompt.

    Returns a compact multi-line string (8-15 lines) that:
    1. Names the depth layer and its one-line objective
    2. Shows what the user already understands (mechanisms from conv state)
    3. Names what remains unresolved (from conv state)
    4. States the layer-specific analytical mission for this turn

    Returns an empty string for trivial quick-depth responses.
    """
    depth = context.get("response_depth", "standard")
    if depth == "quick":
        return ""

    knowledge = context.get("conversation_knowledge", {}) or {}
    lines: list[str] = []

    # Structured-mode fix (Task 1): a freshly feed-linked turn (feed_action set
    # this turn by chat_service.py, not just a resolved feed_entry_anchor
    # carried from a prior turn) gets framing tied to the REAL action + card
    # title, instead of a generic label hardcoded to mode="deep_research"
    # regardless of what actually triggered the turn. chat_modes_service.
    # build_feed_context_note() no longer appends its own copy of this note
    # (removed there) — this is now the single source, so the two can't
    # disagree or duplicate.
    feed_action = context.get("feed_action")
    feed_topic  = context.get("feed_topic", "")
    feed_note   = build_feed_layer_note(feed_action, feed_topic) if feed_action and feed_topic else ""

    if feed_note:
        lines.append(feed_note)
        mission = ""  # feed_note already states its own mission inline
    else:
        layer = _LAYER_META.get(mode, _DEFAULT_LAYER)
        lines.append(f"LEARNING SYSTEM — {layer['label']}:")
        lines.append(layer["objective"])
        mission = layer["mission"]

    # Thread context — only when there's meaningful state
    thread    = (knowledge.get("current_thread") or "").strip()
    domain    = (knowledge.get("active_domain")  or context.get("domain_context", {}).get("domain") or "").strip()
    mechanisms = knowledge.get("mechanisms_covered", [])
    unresolved = knowledge.get("unresolved_questions", [])
    turn_count = knowledge.get("turn_count", 0)

    # Show accumulated understanding only when it's substantive (2+ turns, 1+ mechanisms)
    if turn_count >= 2 and mechanisms:
        thread_line = ""
        if thread:
            thread_line = f"Thread: \"{thread}\""
            if domain:
                thread_line += f"  [{domain}]"

        if thread_line:
            lines.append(thread_line)

        lines.append("What this user already understands — build on this, do not re-explain:")
        for m in mechanisms[:_MAX_MECHANISMS_SHOWN]:
            lines.append(f"  • {m[:110]}")

        if unresolved:
            lines.append(f"Still unresolved: {unresolved[0][:100]}")

    # Layer-specific mission (feed-aware framing above already states its own)
    if mission:
        lines.append(mission)

    # Curiosity momentum signal (recent questions — gives the AI conversational context)
    curiosity = knowledge.get("curiosity_momentum", [])
    if curiosity and turn_count >= 1:
        recent_q = curiosity[0][:80]
        lines.append(f"User's most recent question: \"{recent_q}\"")

    # Breadth signal — how widely the user has explored. Task 3 (structured-mode
    # fix pass): used to append "— {inferred_level} level" here too, reading
    # learner_profile.inferred_level directly — an entirely separate,
    # independently-computed level signal from _build_profile_section's
    # "Learning stage: X" line elsewhere in this same structured prompt, able
    # to disagree with it (recon: "early" here, "advanced" there, same user,
    # same turn). resolve_user_level() is the one place level gets resolved
    # now — _build_profile_section already surfaces it, so this line states
    # only what it uniquely knows (breadth), not a second, possibly-conflicting
    # restatement of a signal owned elsewhere.
    breadth = context.get("exploration_breadth", {})
    total   = breadth.get("total_explored", 0)
    if total >= 5:
        lines.append(f"Learner context: {total} topics explored.")

    # Phase 4.6: inject project-level cross-session knowledge
    # This section shows what the user has learned ACROSS ALL feed sessions for this
    # project — giving every mode a shared foundation, not just session memory.
    slc_block = context.get("shared_learning_context", "")
    if slc_block:
        lines.append("")
        lines.append(slc_block)

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Feed context enrichment
# ═══════════════════════════════════════════════════════════════════════════════

def build_feed_layer_note(feed_action: str, topic: str) -> str:
    """
    Return a one-paragraph note positioning a feed interaction in the learning hierarchy.

    Called by chat_modes_service.build_feed_context_note to append learning
    continuity framing to the feed insight note.
    """
    if feed_action == "ask_about":
        return (
            f"LEARNING SYSTEM — Discovery Layer: "
            f"The user encountered \"{topic}\" in their feed. "
            f"Your role is to open the next layer below the surface — "
            f"introduce the mechanism, show why it matters, and leave one thread "
            f"the user will want to pull further. This is the entry point; "
            f"Chat and Web Search can deepen it from here."
        )
    if feed_action == "explain_simply":
        return (
            f"LEARNING SYSTEM — Abstraction Compression: "
            f"Compress \"{topic}\" into intuition. Preserve the mechanism — "
            f"simplify the vocabulary, not the intelligence."
        )
    if feed_action == "continue_research":
        return (
            f"LEARNING SYSTEM — Validation Extension: "
            f"The user already has a surface understanding of \"{topic}\" from their feed. "
            f"Use web search results to extend, challenge, and update that foundation."
        )
    return ""
