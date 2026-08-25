"""
Prompt construction for the conversational chat system.

Responsible for assembling the OpenAI-format messages list sent to Groq,
including the system prompt (persona + user profile + research context),
truncated conversation history, and the new user message.

Public API
----------
build_system_prompt(context: dict) -> str
build_messages(history: list[dict], user_message: str, context: dict) -> list[dict]
"""

from __future__ import annotations

import json
import re

from ..prompts.prompt_composer import PromptComposer
# Phase K: imported at module scope, not lazily inside a try/except like the
# other section builders. A swallowed ImportError here would silently strip the
# crisis-support section out of every prompt — i.e. exactly the regression this
# phase forbids — so this dependency is allowed to fail loudly at startup
# instead of quietly at the worst possible moment. It imports only pytz, so
# there is no circular-import reason for it to be lazy.
from .crisis_support_service import build_crisis_support_section

# Phase T: was 6. Real data (llm_call_log/chat_messages, 665 real turns):
# average turn pair ~439 tokens (4-chars/token heuristic), p95 assistant
# reply ~1200 tokens. The smallest real prompt budget actually seen serving
# chat traffic is the OpenRouter nemotron-nano fallback (~16.4K tokens,
# unregistered in model_registry.py -> conservative default) and Groq's
# llama-3.1-8b-instant on-demand tier (~17.5K effective) — both close to
# 16-17.5K. Reserving ~3K for system prompt + dynamic context sections and
# ~3K headroom for a document excerpt, ~10K is safely left for history; at
# p95-per-turn sizing (~1.2K) that's ~8 turns without risking a budget
# failure on the weakest model actually in the pool.
MAX_HISTORY_TURNS = 8

# ── Depth detection ───────────────────────────────────────────────────────────

_QUICK_GREETINGS = frozenset(
    "hi hey hello sup yo hiya howdy greetings good morning good afternoon good evening "
    "thanks thank you bye goodbye ok okay cool noted got it lol".split()
)

# Chat-R7b: phrases, not a word bag — the old frozenset(single_string.split())
# shape flattened multi-word phrases ("in detail", "how does", "step by step",
# "teach me", "walk me through", "from scratch", "all about") into individual
# words, so a token-set intersection false-positived on any message merely
# containing "how" or "about" in isolation (confirmed live, R7 recon: a plain
# personal/career question landed on "detailed" purely because it used the
# words "how" and "about" — neither phrase was actually present). Matched via
# regex word-boundary search against the raw message instead of a token-set
# intersection, so "how does" only fires when those two words are contiguous.
_DETAILED_TRIGGERS = (
    "in detail", "detailed", "deeply", "deep", "explain properly", "thoroughly",
    "complete", "completely", "comprehensive", "full", "understand properly",
    "how does", "internally", "step by step", "teach me", "walk me through",
    "guide me", "from scratch", "everything about", "all about",
)

_RESEARCH_TRIGGERS = (
    "research", "analyze", "analyse", "compare", "deeply", "contrast", "tradeoffs",
    "implications", "perspectives", "viewpoints", "history", "historical",
    "evolution", "future outlook", "multi-angle", "cross-domain",
    "strategic implications", "contradictions", "competing",
)

_DETAILED_PATTERN = re.compile(r"\b(?:" + "|".join(re.escape(p) for p in _DETAILED_TRIGGERS) + r")\b")
_RESEARCH_PATTERN = re.compile(r"\b(?:" + "|".join(re.escape(p) for p in _RESEARCH_TRIGGERS) + r")\b")


def detect_depth(message: str) -> str:
    """
    Classify the intended response depth from user phrasing and mode.

    Returns one of: "quick" | "standard" | "detailed" | "research"

    - Short / casual / greeting → quick
    - Explicit depth phrases (phrase-matched, see _DETAILED_PATTERN/_RESEARCH_PATTERN) → detailed or research
    - Default → standard
    """
    m = message.strip().lower()

    # Typo or nonsense: very short, no real words
    if len(m) <= 6 and not any(c.isalpha() for c in m):
        return "quick"

    # Greeting / casual
    tokens = set(m.split())
    if tokens <= _QUICK_GREETINGS or (len(tokens) <= 3 and tokens & _QUICK_GREETINGS):
        return "quick"

    has_detailed = bool(_DETAILED_PATTERN.search(m))
    has_research = bool(_RESEARCH_PATTERN.search(m))

    # Very short factual asks (< 5 words, no depth trigger)
    if len(tokens) <= 4 and not has_detailed and not has_research:
        return "quick"

    # Research-grade
    if has_research:
        return "research"

    # Detailed
    if has_detailed:
        return "detailed"

    return "standard"


# ── Intent-aware format directives ────────────────────────────────────────────

_FORMAT_DIRECTIVES: dict[str, str] = {
    "explanation": """\
FORMAT GUIDANCE — EXPLANATION:
Build intuition before definitions. Lead with what it IS and DOES, then HOW it works, then WHY it matters.
Name a concrete real-world example (company, event, or person — not "some organisations do this").
End with the non-obvious insight: what would genuinely surprise someone who just learned this?
The user should finish reading and think "I finally understand this clearly." """,

    "comparison": """\
FORMAT GUIDANCE — COMPARISON:
Analyse ACROSS dimensions — do not write "A does X, B does Y" parallel summaries.
For each meaningful dimension of difference: explain WHY each subject occupies its position — name
the structural, economic, or incentive force behind it.
BAD: "China dominates APIs."
GOOD: "China dominates APIs because vertically integrated, state-supported manufacturing compresses
margins below what competitors can structurally match — giving China upstream pricing power over
downstream exporters, including India's generic pharma sector."
End with a clear verdict and explicit reasoning — not "both have advantages in different contexts." """,

    "analysis": """\
FORMAT GUIDANCE — ANALYSIS:
Explain WHY before WHAT. Go beyond describing what is happening — explain the mechanism driving it.
Cover: the core structural force, hidden factors conventional coverage underweights, second-order
effects, tradeoffs with real costs, strategic implications, and where experts actually disagree.
Write like an analyst constructing a brief — name mechanisms and causality, not just patterns.""",

    "historical": """\
FORMAT GUIDANCE — HISTORICAL/EVOLUTION:
Structure around causality, not chronology. Identify phases defined by dominant dynamics, not dates.
At each turning point: what caused the transition? Who triggered it and why?
Trace causal threads: how did earlier decisions constrain later ones?
End with the lesson: what does this history reveal about how the domain works today?
The reader should understand not just what happened, but why it had to happen that way.""",

    "strategic": """\
FORMAT GUIDANCE — STRATEGIC/INDUSTRY:
Cover structural forces over surface statistics. Address: the incentive structures explaining why
incumbents behave as they do; competitive moats and what could displace them; regulatory or
geopolitical vectors creating leverage or vulnerability; what currently holds the equilibrium in place;
what specific force will change that equilibrium; and the underpriced risk — what is the conventional
view getting wrong?
Write like a sector analyst briefing a decision-maker, not a reporter covering the industry.""",

    # ── Semantic-layer intent types (no regex fast-path equivalent) ───────────

    "causal": """\
FORMAT GUIDANCE — CAUSAL ANALYSIS:
The question asks WHY — start with the mechanism, not the outcome.
Trace backward from effect to root cause. Don't stop at the first explanation — ask what produced THAT.
Name actors, structural forces, and constraints specifically. Generic explanations fail.
Surface the counterintuitive: why did rational actors produce this outcome?
End with the implication: what does the causal logic reveal about what would change the outcome?""",

    "prediction": """\
FORMAT GUIDANCE — PREDICTIVE ANALYSIS:
Anchor predictions in current structural dynamics — not optimism or trend extrapolation.
Name the specific forces that would accelerate, decelerate, or reverse for different outcomes.
Surface where genuine uncertainty exists vs. where the trajectory is relatively clear.
A good prediction names the conditions under which it fails — that is what makes it useful.""",

    "critique": """\
FORMAT GUIDANCE — CRITICAL ANALYSIS:
Start with the strongest version of the position being critiqued. No strawmen.
Name specific flaws: which assumption fails? Where does evidence not support the claim?
Distinguish fatal flaws from superficial weaknesses.
End with the verdict: what does the critique change about how we should understand or use this?""",

    "synthesis": """\
FORMAT GUIDANCE — SYNTHESIS:
The goal is integration, not summary. What do the pieces reveal together that no single part shows?
Surface hidden connections, unexpected tensions, and emergent patterns.
The synthetic insight should be something you couldn't have said before seeing the whole picture.
End with the one load-bearing insight the rest of the answer supports.""",
}


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def build_system_prompt(context: dict, mode: str = "normal") -> str:
    """
    Assemble the system prompt from all available context sections.

    Routing (Chat-R7b — was mode-based: web_search/roadmap/compare/
    trend_analysis always got the JSON schema regardless of whether
    the turn had anything to do with Feed. That forced a Key Takeaways/
    Resources/Explore Next card onto plain conversational answers like "top
    10 github trends" — confirmed live, R1/R7 recon. roadmap/compare/
    trend_analysis were never even reachable in practice: ChatRequest.
    chat_mode only ever validates to normal/web_search/layman.)
    ------------
    context["feed_linked"] present and truthy (chat_service.py: feed_context
    for this turn, OR a resolved feed_entry_anchor from a prior turn's
    feed_chat_links row — a union because the link row isn't persisted until
    after the first Feed-triggered turn's response completes, so
    feed_entry_anchor alone is empty on turn 1)
        Full context injection (profile, research, domain, action) + structured
        JSON format directive so the renderer can display rich sections —
        this is a genuine Feed-linked conversation, structure is warranted.

    Everything else (normal / web_search / layman with no Feed link)
        Minimal prompt: persona + conversation memory + natural guidelines.
        No JSON schema. No research dumps. Adaptive free-form prose — the
        default for an ordinary chat turn, whichever tool answered it.
    """
    if context.get("feed_linked"):
        return _build_structured_prompt(context)
    else:
        return _build_natural_prompt(context, mode)


def build_messages(
    history:      list[dict],
    user_message: str,
    context:      dict,
    mode:         str = "normal",
    attachments:  list[dict] | None = None,
) -> list[dict]:
    """
    Build the full OpenAI-format messages list for the Groq API call.

    - Prepends the mode-aware system prompt.
    - Truncates history to the most recent MAX_HISTORY_TURNS turns.
    - Appends the new user message.

    `attachments` (Chat-5): list of {uri, mime_type, ...} from
    model_provider.upload_attachment(). When present, the final user message's
    content becomes a list of parts (text + Gemini "media" file_uri parts)
    instead of a plain string — verified live against the real SDK's content-
    block format (langchain_google_genai).
    """
    system_prompt = build_system_prompt(context, mode=mode)

    max_msgs = MAX_HISTORY_TURNS * 2
    truncated_history = history[-max_msgs:] if len(history) > max_msgs else history

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(truncated_history)
    if attachments:
        parts = [{"type": "text", "text": user_message}] if user_message else []
        parts += [{"type": "media", "file_uri": a["uri"], "mime_type": a["mime_type"]} for a in attachments]
        messages.append({"role": "user", "content": parts})
    else:
        messages.append({"role": "user", "content": user_message})
    return messages


# ═══════════════════════════════════════════════════════════════════════════════
# Mode-specific prompt builders
# ═══════════════════════════════════════════════════════════════════════════════

def _build_format_directive_section(format_intent: str, intent_profile: dict | None = None) -> str:
    """
    Return the intent-aware format directive string.

    When the semantic intent profile signals a blended multi-intent prompt
    (blended_format=True), the composed_directive from the semantic layer
    takes precedence over the single-intent fallback.

    Falls back to the single-intent directive from _FORMAT_DIRECTIVES, or
    empty string for "default" with no semantic signal.
    """
    # Blended path — use the composed directive from semantic scoring
    if intent_profile and intent_profile.get("blended_format"):
        composed = intent_profile.get("composed_directive", "")
        if composed:
            return composed

    # Single-intent path — look up in the directive table
    return _FORMAT_DIRECTIVES.get(format_intent, "")


def _build_natural_prompt(context: dict, mode: str) -> str:
    """
    Minimal, natural-feeling system prompt for normal and layman chat.

    Injects: persona (with response principles folded in) + conversation memory +
             optional layman directive + attachment awareness.
    Omits: research dumps, exploration history, JSON schema.

    Chat identity pass: RESPONSE DEPTH / FORMAT GUIDANCE / NARRATIVE MODE /
    CONVERSATIONAL RULES / CODE GENERATION RULES are gone from this function —
    replaced by _RESPONSE_PRINCIPLES (judgment-based, no classifier gating length
    or structure). learning_system_context_service's tactical section is also
    gone here; the identity addition in _PERSONA_NATURAL carries that framing now.
    detect_intent()/detect_depth() still run upstream in chat_service.py — their
    output still feeds recommendations enrichment and the tension directive below,
    just no longer injected as prompt text in this function.
    """
    composer = PromptComposer()
    composer.add_section("persona",        _build_persona_section(context.get("user_name", "")),
                         priority=1, required=True,  source_pack="")

    # Conversation memory: most important for continuity (always inject if present)
    composer.add_section("conversation_memory", _build_conversation_memory_section(
        context.get("conversation_memory", {}), include_recency=False
    ),                   priority=2, required=False, source_pack="dynamic")

    # Active analytical thread — mechanisms, unresolved tensions, comparative frame.
    # Injected when the session has 2+ turns and at least one established mechanism.
    # Enables compound reasoning without re-explaining prior context.
    composer.add_section("knowledge_state", _build_knowledge_state_section(
        context.get("conversation_knowledge", {})
    ),                   priority=2, required=False, source_pack="dynamic")

    # Chat-3: semantic long-term memory recall — additive third layer alongside
    # conversation_memory/knowledge_state (regex-based, session/exact-topic scoped).
    # Pre-formatted by vector_memory_service.format_for_prompt(); "" when no hits.
    composer.add_section("vector_memory", context.get("vector_memory", ""),
                         priority=2, required=False, source_pack="dynamic")

    # Chat-3: Feed-entry persistent anchor — resolved from feed_chat_links,
    # independent of shared_learning_context. Present every turn of a
    # Feed-linked session, pre-formatted by feed_entry_anchor_service.
    composer.add_section("feed_entry_anchor", context.get("feed_entry_anchor", ""),
                         priority=2, required=False, source_pack="dynamic")

    # Cognitive tension directive — forces intellectual friction over flat informational phrasing.
    # Skipped in layman mode (directive conflicts with ELI5 framing) and for trivial messages.
    if mode != "layman":
        composer.add_section("tension",    _build_tension_section(context, mode),
                             priority=3, required=False, source_pack="dynamic")

    # User profile: only inject a one-liner if interesting
    composer.add_section("user_profile",   _build_compact_profile(context),
                         priority=3, required=False, source_pack="dynamic")

    # Layman directive when explain-simply mode is active
    if mode == "layman":
        composer.add_section("layman_directive", _build_layman_mode_section(context),
                             priority=2, required=False, source_pack="core_learning_pack")
        # Phase 4.6: inject known concept anchors into the layman directive
        # so simplifications can reference what the user has already learned.
        slc = context.get("shared_learning_context", "")
        if slc and "ANALOGY ANCHORS" in slc:
            composer.add_section("layman_anchors", slc,
                                 priority=2, required=False, source_pack="dynamic")

    composer.add_section("response_principles",
                         _RESPONSE_PRINCIPLES_LAYMAN if mode == "layman" else _RESPONSE_PRINCIPLES,
                         priority=3, required=True,  source_pack="")

    # Phase T: conditional on context["has_attachment"] (chat_service.py — set
    # from this turn's own image/document attachments, or a relevant document
    # persisted from earlier in the session). Was unconditional: real text
    # weight on every turn regardless of whether the feature was in play.
    if context.get("has_attachment"):
        composer.add_section("attachment_awareness", _ATTACHMENT_AWARENESS,
                             priority=3, required=True,  source_pack="")

    # Phase K -> Phase U: was unconditional (see crisis_support_service's module
    # docstring for why, at the time). Gated now on context["crisis_active"]
    # (chat_service.py — chat_router.classify_message's real crisis field, with
    # a code-level fail-safe defaulting to True on any classify failure or
    # skip, plus a few-turn carry-forward after a real crisis turn — never
    # left to the model alone). Still deliberately last when present, so it's
    # the final thing the model reads and can override what precedes it
    # (specifically the RESPONSE PRINCIPLES line about pushback meaning
    # "change your approach", which is what turned a real crisis follow-up
    # into an apology and a retraction).
    if context.get("crisis_active"):
        composer.add_section("crisis_support",
                             build_crisis_support_section(context.get("client_timezone")),
                             priority=1, required=True,  source_pack="")
    return composer.build()


def _build_structured_prompt(context: dict) -> str:
    """
    Full context injection for specialized research/analysis modes.

    Injects all available sections + structured JSON format directive.

    Structured-mode fix (Task 2): response_depth is computed upstream
    regardless of feed_linked, but this function used to never read it — a
    feed-linked "hi" got the exact same 19-section, mandatory-JSON-schema
    treatment as a genuinely complex feed-linked question. is_quick below
    gates out the sections that are analytical-depth aids (irrelevant to a
    short exchange regardless of what triggered it — research, session,
    knowledge_state, exploration_breadth, preference_snapshot,
    explanation_directive, domain_directive, continuity, format_directive,
    tension) and swaps the mandatory JSON schema for RESPONSE PRINCIPLES
    (conversational, closer to natural mode) — confirmed via the frontend's
    real rendering code that this is safe: StructuredResponseRenderer's
    children (KeyTakeawaysList, ResourceLinksPanel, etc.) all early-return
    null on an empty/absent array, and _parse_structured_response's only
    validity check is the presence of a "response_type" key, so a fuller
    JSON response was never actually required by anything downstream.
    conversation_memory, vector_memory, and feed_entry_anchor stay
    unconditional — continuity/context about what the user is discussing,
    not analytical depth, so orthogonal to how complex this message is.
    action_result stays unconditional too — real per-turn workflow data a
    prior step already produced for this exact turn, not a depth aid.
    """
    is_quick = context.get("response_depth") == "quick"

    composer = PromptComposer()
    composer.add_section("persona",        _PERSONA,
                         priority=1, required=True,  source_pack="")

    # Learning system framing — anchors the structured response to the user's learning journey.
    # Structured mode (web_search) carries the most state; this ensures the AI
    # builds on established mechanisms rather than re-starting from scratch each time.
    #
    # Structured-mode fix (Task 1, was a KNOWN BUG deferred out of the natural-mode
    # identity pass): mode="web_search" here is only the fallback framing for turns
    # 2+ of a feed-linked session — learning_system_context_service checks context's
    # feed_action/feed_topic (set by chat_service.py only on the turn feed_context
    # itself is present) and uses the real action's framing instead when available.
    # chat_modes_service.build_feed_context_note() no longer appends a second copy.
    composer.add_section("learning_system", _build_learning_system_section(context, mode="web_search"),
                         priority=2, required=False, source_pack="dynamic")

    composer.add_section("user_profile",        _build_profile_section(context),
                         priority=2, required=False, source_pack="dynamic")

    if not is_quick:
        composer.add_section("research",        _build_research_section(context.get("research", {})),
                             priority=1, required=False, source_pack="dynamic")
        composer.add_section("session",         _build_session_section(context.get("session", {})),
                             priority=3, required=False, source_pack="dynamic")

    composer.add_section("conversation_memory", _build_conversation_memory_section(context.get("conversation_memory", {})),
                         priority=2, required=False, source_pack="dynamic")

    if not is_quick:
        composer.add_section("knowledge_state", _build_knowledge_state_section(context.get("conversation_knowledge", {})),
                             priority=2, required=False, source_pack="dynamic")

    # Chat-3: semantic long-term memory recall + Feed-entry persistent anchor
    # (see _build_natural_prompt for full rationale — same sections, same
    # context keys, mirrored here for structured modes). Unconditional: both
    # are continuity/context about what's being discussed, not depth aids.
    composer.add_section("vector_memory",       context.get("vector_memory", ""),
                         priority=2, required=False, source_pack="dynamic")
    composer.add_section("feed_entry_anchor",   context.get("feed_entry_anchor", ""),
                         priority=2, required=False, source_pack="dynamic")

    if not is_quick:
        composer.add_section("exploration_breadth", _build_exploration_breadth_section(context.get("exploration_breadth", {})),
                             priority=3, required=False, source_pack="dynamic")
        composer.add_section("preference_snapshot", _build_preference_snapshot_section(context.get("preference_snapshot", {})),
                             priority=3, required=False, source_pack="dynamic")
        composer.add_section("explanation_directive", _build_explanation_directive_section(context.get("learner_profile", {})),
                             priority=3, required=False, source_pack="dynamic")
        composer.add_section("domain_directive", _build_domain_directive_section(context.get("domain_context", {})),
                             priority=3, required=False, source_pack="dynamic")
        composer.add_section("continuity",      _build_continuity_section(context.get("continuity", {})),
                             priority=2, required=False, source_pack="dynamic")

    # action_result: real per-turn workflow data a prior step already produced
    # for this exact turn — unconditional, not a depth aid (its own builder
    # already returns "" when there's nothing to present).
    composer.add_section("action_result",       _build_action_result_section(context.get("action_result", {})),
                         priority=2, required=False, source_pack="dynamic")

    if not is_quick:
        # Intent-aware format directive — guides response structure for the detected intent.
        # Passes intent_profile so blended multi-intent prompts get composed directives.
        composer.add_section("format_directive", _build_format_directive_section(
            context.get("format_intent", "default"),
            intent_profile=context.get("intent_profile"),
        ),                   priority=3, required=False, source_pack="")

        # Cognitive tension — short version for structured modes; informs key_takeaway quality.
        composer.add_section("tension",    _build_tension_section(context, mode="web_search"),
                             priority=3, required=False, source_pack="dynamic")

    composer.add_section("guidelines",     _GUIDELINES,
                         priority=3, required=True,  source_pack="")
    composer.add_section("format_schema",
                         _RESPONSE_PRINCIPLES if is_quick else _STRUCTURED_FORMAT_DIRECTIVE,
                         priority=1, required=True,  source_pack="")

    # Phase K -> Phase U: same section, same gate (context["crisis_active"], see
    # _build_natural_prompt) in the Feed-linked path too — distress isn't less
    # likely just because the session started from a Feed card. Placed after
    # format_schema on purpose: it carries the one instruction allowed to
    # override the mandatory-JSON directive above (a crisis answer must be plain
    # prose, not a response schema). chat_service._parse_structured_response returns
    # None for non-JSON and the frontend then renders raw text — the same path every
    # natural-mode turn already takes, so this is an exercised fallback, not a new one.
    if context.get("crisis_active"):
        composer.add_section("crisis_support",
                             build_crisis_support_section(context.get("client_timezone")),
                             priority=1, required=True,  source_pack="")
    return composer.build()


# ═══════════════════════════════════════════════════════════════════════════════
# Prompt fragments
# ═══════════════════════════════════════════════════════════════════════════════

_PERSONA = """\
You are Curivio — an expert AI research and learning companion. You act as a technical mentor,
research assistant, and personalized learning guide. Your tone is knowledgeable but
approachable. You explain complex topics clearly, tailor your depth to the user's level,
and are honest about uncertainty."""

_PERSONA_NATURAL = """\
You are Curivio — an intelligent research and learning companion.
Help the user understand ideas, explore topics, and think more clearly.
Be direct, thoughtful, and conversational. Match your depth to what the user needs.

You're a learning companion this person comes back to, not a one-off chatbot — lean on
what you know about how they think and what they've explored before, the way someone
who's worked with them for a while would. When you know their name, use it where it
feels human — greeting them by name when a conversation opens, or in a genuinely warm
or personal moment — not stapled onto the start of every reply."""


def _build_persona_section(user_name: str = "") -> str:
    """
    Natural-mode persona, with the user's name folded in when available (Chat
    identity pass) so "use their name naturally" has a real name to work with.
    Empty/missing name: omit the line entirely, no placeholder fallback.
    """
    if user_name:
        return f"{_PERSONA_NATURAL}\n\nThe user's name is {user_name}."
    return _PERSONA_NATURAL

# Chat identity pass: replaces the old RESPONSE DEPTH / FORMAT GUIDANCE / NARRATIVE
# MODE / CONVERSATIONAL RULES / CODE GENERATION RULES stack in natural mode — one
# block, judgment-based instead of mechanically classified. Structured mode is
# untouched and keeps _GUIDELINES below unchanged.
_RESPONSE_PRINCIPLES = """\
RESPONSE PRINCIPLES:
- Decide the length and depth yourself, based on what this specific question actually needs. A quick factual question deserves a few sentences. A real "explain this to me" deserves real depth — and when the conversation, memory, or source material already in front of you genuinely supports going deeper (real prior discussion, a real document, real history here), draw on it rather than staying generic. Don't pad either way, and don't force a fixed length onto an answer that doesn't need one.
- Lead with the actual answer — not a definition, not throat-clearing, not "great question."
- Prioritise causality over description: explain WHY things work the way they do, not just WHAT they are.
- Name specifics and surface what's non-obvious — the company, the event, the mechanism, the second-order effect the user probably hasn't considered — rather than restating what they likely already know.
- Decide the shape yourself too, the same way you decide length — a genuine comparison can be a table, a genuine multi-step process can be numbered, a genuine list of options can be bulleted, and a genuine short conversational answer can still just be prose. Match the structure to what this content actually is, not a default in either direction.
- Write code whenever it's genuinely the clearest way to answer — a worked example, a specific technique, a syntax question — regardless of the subject. Skip code when prose serves better. Never tack code onto the end of a prose answer as an unrequested bonus. Always put code in a fenced block tagged with its language — unfenced code loses its indentation when it renders, which for Python makes it wrong rather than merely ugly.
- When code is the answer, give it a line of framing — what the approach is and why it's shaped that way. One or two sentences, before or after the block, not a preamble. Drop it only when the user actually said they want code only ("just the code", "no explanation"), or when the answer is a single obvious line that explains itself.
- Say plainly what you're actually sure of. When you're inferring, generalising, or working from memory rather than something concrete in front of you, say so ("as far as I know," "I'd want to check this") instead of stating it with more confidence than you have — and never manufacture a source or citation to sound more certain than you are.
- If the user tells you your last answer missed the mark, that's a real signal — change your approach. Don't just apologise and repeat the same thing with more words.
- Don't open by naming yourself. Just answer.
- If a topic came up earlier in this conversation, build on it — don't re-explain from scratch.
- Default to continuity, not a hard cut: when a short or fragmentary message COULD plausibly extend what you were just discussing, assume it does — answer with that topic's version of the new phrase, not the generic, context-free reading, the way someone mid-conversation defaults to assuming the next thing relates rather than treating every short message as a reset. Only answer it as genuinely standalone when the wording actively rules out a connection (a real subject change signaled by the user, or a topic the conversation truly has no bearing on) — the bar is whether this plausibly extends the thread, not whether it explicitly references it."""

# Layman-fix pass: same principles minus the two lines that structurally conflict
# with LAYMAN_SIMPLIFICATION_DIRECTIVE's mandated 5-step sequence (core idea ->
# analogy -> mechanism -> why it exists -> insight) — "decide length/structure
# yourself" and "headers only when genuinely list-like" both contradict a directive
# that mandates the response's shape outright. Every other line is orthogonal
# (uncertainty honesty, code judgment, pushback responsiveness, causality,
# specificity, continuity) and applies exactly as much in layman mode as anywhere
# else — kept verbatim, not reworded.
_RESPONSE_PRINCIPLES_LAYMAN = """\
RESPONSE PRINCIPLES:
- Lead with the actual answer — not a definition, not throat-clearing, not "great question."
- Prioritise causality over description: explain WHY things work the way they do, not just WHAT they are.
- Name specifics and surface what's non-obvious — the company, the event, the mechanism, the second-order effect the user probably hasn't considered — rather than restating what they likely already know.
- Write code whenever it's genuinely the clearest way to answer — a worked example, a specific technique, a syntax question — regardless of the subject. Skip code when prose serves better. Never tack code onto the end of a prose answer as an unrequested bonus. Always put code in a fenced block tagged with its language — unfenced code loses its indentation when it renders, which for Python makes it wrong rather than merely ugly.
- When code is the answer, give it a line of framing — what the approach is and why it's shaped that way. One or two sentences, before or after the block, not a preamble. Drop it only when the user actually said they want code only ("just the code", "no explanation"), or when the answer is a single obvious line that explains itself.
- Say plainly what you're actually sure of. When you're inferring, generalising, or working from memory rather than something concrete in front of you, say so ("as far as I know," "I'd want to check this") instead of stating it with more confidence than you have — and never manufacture a source or citation to sound more certain than you are.
- If the user tells you your last answer missed the mark, that's a real signal — change your approach. Don't just apologise and repeat the same thing with more words.
- Don't open by naming yourself. Just answer.
- If a topic came up earlier in this conversation, build on it — don't re-explain from scratch.
- Default to continuity, not a hard cut: when a short or fragmentary message COULD plausibly extend what you were just discussing, assume it does — answer with that topic's version of the new phrase, not the generic, context-free reading, the way someone mid-conversation defaults to assuming the next thing relates rather than treating every short message as a reset. Only answer it as genuinely standalone when the wording actively rules out a connection (a real subject change signaled by the user, or a topic the conversation truly has no bearing on) — the bar is whether this plausibly extends the thread, not whether it explicitly references it."""

_ATTACHMENT_AWARENESS = """\
ATTACHMENT AWARENESS:
- Images: when this turn includes an image, you genuinely receive and see its actual visual
  content through this interface — describe what you actually observe. Never say you cannot
  process, view, or see images; you can, and one may be attached right now.
- Documents: extracted document text in your context is labeled either "full text" (the complete
  file) or "showing the N most relevant excerpts out of M total" (a partial, retrieval-trimmed
  selection). When you were given excerpts, say so — "based on the visible excerpts" or similar —
  never claim to have read the entire document when you were only shown a portion of it."""

_GUIDELINES = """\
Guidelines:
- Give clear, structured answers. Use bullet points or code blocks where helpful.
- Tailor complexity to the user's learning stage and stated interests.
- Build on what this session has already covered: go deeper, don't re-explain; connect new questions to prior context.
- Keep responses focused and avoid unnecessary repetition.
- If the user asks about something outside your knowledge, say so honestly.
- Images and documents: if this turn includes an image, you genuinely see its actual visual
  content — never claim you cannot process images. If a document is labeled as excerpted
  ("showing the N most relevant excerpts"), represent it as a partial excerpt, not a full read."""

_STRUCTURED_FORMAT_DIRECTIVE = """\
OUTPUT FORMAT — MANDATORY:
You MUST respond with ONLY a valid JSON object. No text before or after the JSON. No markdown code fences.
If this turn calls for using one of your tools (e.g. a mode hint says to prefer one, or the question
needs live data you don't have), call it first — this JSON-only rule applies to your final answer after
any tool results return, not to the tool call itself.

Schema (all fields required; use [] for unused arrays):
{
  "response_type": "chat_explanation",
  "title": "5-10 word descriptive title",
  "summary": "2-3 sentences synthesising the single most important insight — NOT a definition or overview",
  "sections": [
    {
      "title": "Section Title",
      "content": "Body — supports **bold**, `code`, bullet lists (- item), numbered lists, and fenced code blocks",
      "importance": "high",
      "collapsible": false
    }
  ],
  "key_takeaways": ["Non-obvious insight 1", "Non-obvious insight 2"],
  "resources": [
    {"title": "Resource name", "url": "https://...", "type": "article"}
  ],
  "next_topics": ["Specific follow-up question 1", "Specific follow-up question 2"]
}

response_type values and their section structures:
- "chat_explanation"  — default; free-form sections matching the question
- "comparison"        — sections: [Structural Differences], [Economics & Incentives], [Strategic Advantage], [Verdict & Recommendation]
- "roadmap"           — sections: ordered learning stages with milestone titles
- "deep_research"     — sections: [Core Finding], [Critical Analysis], [Strategic Implications], [Key Risks & Uncertainties], [What Shifts Next]
- "industry_analysis" — sections: [Market Structure], [Competitive Dynamics], [Key Risks], [Strategic Outlook]
- "feed_insight"      — sections: [Quick Take], [Why It Matters], [Learning Angle]

resource.type values: "article" | "github" | "arxiv" | "official" | "report"

Rules:
- 2-5 sections total — never more
- Prefer bullet points and short analytical paragraphs over long prose blocks
- key_takeaways: 3-5 items maximum, each under 25 words
  — MUST be genuinely non-obvious insights — not summaries of the obvious
  — Each should reveal a mechanism, tension, implication, or hidden connection
  — "AI is growing fast" is NOT an insight. "China's API dominance gives it veto power over Indian pharma
    exports without direct political leverage" IS an insight.
- resources: only real, widely-known URLs you are highly confident exist; use [] if uncertain
- next_topics: 2-4 items — phrase as specific questions or angles, NOT generic topic names
  — BAD: "Learn more about APIs" | GOOD: "How API pricing power shapes pharma export margins"
  — Should feel like the natural next intellectual question — specific enough to be immediately interesting
  — Make them curiosity-inducing: the reader should think "yes, I want to know exactly that"
- Do NOT wrap the JSON in markdown code fences

Synthesis quality rules:
- summary must open with the single most important finding — not background, not a definition
- Every section must ADD something new — never restate the summary in different words
- For "comparison" type: each section must analyse WHY — name incentive structures, causal forces,
  hidden dependencies. Do NOT write "A has X, B has Y" parallel descriptions.
- For "deep_research" type: "Core Finding" opens with the synthesised key insight (not topic background);
  "Critical Analysis" surfaces contradictions and what sources underplay; "Strategic Implications" names
  concrete decisions or shifts — not vague opportunities; "What Shifts Next" names the specific force
  that will change the current equilibrium, with reasoning.
- For "industry_analysis" type: name mechanisms, not just outcomes. "Competition is intense" is not analysis.
  "Three firms hold 70% of API production capacity because capital costs create natural oligopoly
  conditions" IS analysis.
- If sources or perspectives conflict, surface the disagreement explicitly — do not paper over it
- Increase insight density per sentence — if a sentence doesn't add something new, cut it"""


def _build_profile_section(context: dict) -> str:
    """
    Structured-mode profile block. Task 3 (structured-mode fix pass): now
    routes "level" through the same resolve_user_level() natural mode uses,
    instead of reading user_profile.learning_stage directly — that was an
    entirely separate, independently-contradicting level signal from the
    "Learner context: N topics — {level} level" line the learning_system
    section could also emit (different vocabulary, different thresholds).
    Both modes now share one resolution path.
    """
    profile = context.get("user_profile", {})
    if not profile:
        return ""

    lines = ["User learning profile:"]
    level = resolve_user_level(context)
    if level:
        lines.append(f"- Learning stage: {level}")

    diff = profile.get("difficulty_preference")
    if diff:
        lines.append(f"- Preferred difficulty: {diff}")

    interests = profile.get("top_interests", [])
    if interests:
        lines.append(f"- Top interests: {', '.join(interests)}")

    suppressed = profile.get("suppressed_topics", [])
    if suppressed:
        lines.append(f"- Topics to avoid: {', '.join(suppressed)}")

    return "\n".join(lines) if len(lines) > 1 else ""


def resolve_user_level(context: dict) -> str:
    """
    Single user-level signal, shared by natural mode (Chat identity pass)
    and structured mode (structured-mode fix pass, Task 3).

    Previously two independent, differently-scaled paths could both reach the
    prompt: recommendation_service.get_learning_stage() (early/developing/
    proficient, liked-topic count) via user_profile.learning_stage, and
    adaptive_explanation_service's 4-signal inferred_level (beginner/
    intermediate/advanced) via learning_system_context_service's "Learner
    context" line. That second path is gone from natural mode along with the
    rest of the learning_system section (see _build_natural_prompt) — this
    resolver just picks which single value is worth surfacing here: the richer
    multi-signal inferred_level once there's enough history to trust it
    (5+ explored topics), the coarser liked-topic stage before that.
    """
    total_explored = context.get("exploration_breadth", {}).get("total_explored", 0)
    if total_explored >= 5:
        level = context.get("learner_profile", {}).get("inferred_level", "")
        if level:
            return level
    return context.get("user_profile", {}).get("learning_stage", "")


def _build_compact_profile(context: dict) -> str:
    """One-liner profile hint for natural mode — avoids verbose context dumps."""
    profile   = context.get("user_profile", {})
    interests = profile.get("top_interests", [])
    level     = resolve_user_level(context)
    if not interests and not level:
        return ""
    parts = []
    if interests:
        parts.append(f"has shown interest in {', '.join(interests[:3])}")
    if level:
        # "the {level} stage", not "a/an {level} stage" — sidesteps a/an agreement
        # (early/advanced/intermediate all take "an", developing/proficient/beginner take "a").
        parts.append(f"is currently at the {level} stage")
    return f"What you know about this user: {' and '.join(parts)}." if parts else ""


def _build_research_section(research: dict) -> str:
    if not research or not research.get("topic"):
        return ""

    topic = research["topic"]
    lines = [f"Research context for topic: {topic!r}"]

    deep = research.get("deep_research")
    if isinstance(deep, dict):
        summary = deep.get("summary") or deep.get("overview") or ""
        if summary:
            lines.append(f"Deep research summary: {summary[:400]}")

        key_concepts = deep.get("key_concepts", [])
        if key_concepts:
            lines.append(f"Key concepts: {', '.join(str(c) for c in key_concepts[:6])}")

    path = research.get("learning_path")
    if isinstance(path, dict):
        beginner_steps = path.get("beginner", [])
        if beginner_steps:
            titles = [s.get("concept", "") for s in beginner_steps[:3] if isinstance(s, dict)]
            if titles:
                lines.append(f"Learning path (beginner): {', '.join(titles)}")

    expansion = research.get("topic_expansion")
    if isinstance(expansion, dict):
        related = expansion.get("related", [])
        prereqs = expansion.get("prerequisites", [])
        if prereqs:
            lines.append(f"Prerequisites: {', '.join(str(p) for p in prereqs[:4])}")
        if related:
            lines.append(f"Related topics: {', '.join(str(r) for r in related[:4])}")

    return "\n".join(lines) if len(lines) > 1 else ""


def _build_session_section(session: dict) -> str:
    if not session or not session.get("topic"):
        return ""

    topic = session["topic"]
    times = session.get("times_explored", 0)
    if times == 0:
        return ""

    done_flags = {
        "deep_research":   session.get("has_deep_research",   False),
        "learning_path":   session.get("has_learning_path",   False),
        "topic_expansion": session.get("has_topic_expansion", False),
        "github_repos":    session.get("has_github_repos",    False),
    }
    done = [k for k, v in done_flags.items() if v]
    if not done:
        return ""

    return (
        f"Session memory: {topic!r} has been explored {times}× "
        f"(completed: {', '.join(done)})."
    )


def _build_conversation_memory_section(conv: dict, include_recency: bool = True) -> str:
    """
    include_recency=True (default — structured mode, untouched this pass): keeps
    the turn-count header and the "Most recent question" line.

    include_recency=False (natural mode, Chat identity pass): drops both. Recon
    confirmed both are redundant — last_user_messages[0] duplicates the prior
    turn already present verbatim in the truncated history array build_messages()
    sends alongside this system prompt; session_turns adds nothing the model
    needs. topics_discussed + the "do not re-explain" instruction (genuinely
    additive — aggregated across the session, not derivable from the last-N-turn
    array alone) are kept in both modes.
    """
    if not conv or conv.get("message_count", 0) == 0:
        return ""

    topics = conv.get("topics_discussed", [])
    lines: list[str] = []

    if include_recency:
        turns = conv.get("session_turns", 0)
        lines.append(f"This conversation ({turns} turn{'s' if turns != 1 else ''} so far):")
    else:
        lines.append("This conversation:")

    if topics:
        lines.append(f"- Topics discussed: {', '.join(topics)}")
        lines.append(
            "- Do not re-explain these topics from scratch unless the user asks. "
            "Build on what has already been covered."
        )

    if include_recency:
        last_qs = conv.get("last_user_messages", [])
        if last_qs:
            # Show the most recent user question for continuity context
            lines.append(f"- Most recent question: \"{last_qs[0][:120]}\"")

    return "\n".join(lines) if len(lines) > 1 else ""


def _build_exploration_breadth_section(breadth: dict) -> str:
    if not breadth or breadth.get("total_explored", 0) == 0:
        return ""

    total     = breadth.get("total_explored", 0)
    recent    = breadth.get("recently_explored", [])
    deep_done = breadth.get("deep_dived_topics", [])

    lines = [f"User's research history ({total} topic{'s' if total != 1 else ''} explored in this app):"]

    if recent:
        lines.append(f"- Recently explored: {', '.join(recent[:6])}")
    if deep_done:
        lines.append(f"- Deep-dived: {', '.join(deep_done[:4])}")
    if total > 1:
        lines.append(
            "- When relevant, connect answers to topics the user has already studied."
        )

    return "\n".join(lines) if len(lines) > 1 else ""


def _build_preference_snapshot_section(prefs: dict) -> str:
    if not prefs:
        return ""

    liked    = prefs.get("liked_topics", [])
    disliked = prefs.get("disliked_topics", [])
    diff     = prefs.get("difficulty_preference")
    level    = prefs.get("engagement_level", "new")

    if not liked and not disliked and not diff:
        return ""

    lines = ["User learning preferences (from feedback history):"]

    if liked:
        lines.append(f"- Engages positively with: {', '.join(liked[:6])}")
    if disliked:
        lines.append(f"- Tends to disengage from: {', '.join(disliked[:4])}")
    if diff:
        lines.append(f"- Preferred difficulty: {diff}")
    if level == "high":
        lines.append("- High engagement — user responds well to depth and detail.")
    elif level == "low":
        lines.append("- Low engagement — keep answers focused and practical.")

    return "\n".join(lines) if len(lines) > 1 else ""


def _build_explanation_directive_section(learner_profile: dict) -> str:
    """
    Inject the adaptive explanation directive from the learner profile.

    The directive is the pre-formatted, ready-to-use instruction string
    produced by adaptive_explanation_service.build_learner_profile().
    If absent or empty we return empty string so the section is omitted.
    """
    if not learner_profile:
        return ""

    directive = learner_profile.get("directive", "")
    return directive.strip() if directive else ""


def _build_action_result_section(action_result: dict) -> str:
    """
    Inject the per-turn action instruction produced by action_router_service.

    The instruction is a ready-to-use string that tells the AI what workflow
    data is available and how to present it for this specific turn.
    Empty / missing action_result is silently skipped.
    """
    if not action_result:
        return ""
    instruction = action_result.get("instruction", "")
    return instruction.strip() if instruction else ""


def _build_domain_directive_section(domain_context: dict) -> str:
    """
    Inject the domain-specific explanation directive into the system prompt.

    Expects the dict produced by domain_classifier_service.get_domain_context().
    Returns empty string when the domain is unclassified or no directive exists.
    """
    if not domain_context:
        return ""
    directive = domain_context.get("directive", "")
    return directive.strip() if directive else ""


# Fallback for when layman_mode_service is unavailable.
# Canonical source: core_learning_pack.LAYMAN_SIMPLIFICATION_SIMPLE
from ..prompts.instruction_packs.core_learning_pack import LAYMAN_SIMPLIFICATION_SIMPLE as _LAYMAN_MODE_DIRECTIVE


def _build_learning_system_section(context: dict, mode: str) -> str:
    """
    Inject the learning system framing section.

    Positions the current mode in the depth hierarchy (Discover → Understand →
    Explore → Validate → Master) and anchors the response to what the user
    already understands.  Appears at the top of every system prompt so all
    subsequent directives are interpreted through the learning journey lens.

    Returns empty string for quick-depth responses (no framing needed).
    """
    try:
        from .learning_system_context_service import build_learning_system_section
        return build_learning_system_section(context, mode)
    except Exception:
        return ""


def _build_layman_mode_section(context: dict) -> str:
    """
    Inject the mechanism-preserving simplification directive when layman mode is active.

    Pulls domain, topic_hint, and card mechanism from context so the analogy bank
    is tailored to the subject matter and the specific mechanism is explicitly preserved.
    Falls back to the static directive when the service is unavailable.
    """
    layman_ctx = context.get("layman_mode_context", {}) or {}
    if not layman_ctx.get("active"):
        return ""
    domain     = context.get("domain_context", {}).get("domain", "")
    topic_hint = context.get("research",       {}).get("topic") or None
    mechanism  = layman_ctx.get("mechanism", "")
    try:
        from .layman_mode_service import build_layman_directive
        directive = build_layman_directive(domain=domain, topic_hint=topic_hint)
    except Exception:
        directive = _LAYMAN_MODE_DIRECTIVE.strip()
    # Prepend mechanism-preservation instruction when available
    if mechanism:
        prefix = (
            f"MECHANISM TO PRESERVE: \"{mechanism[:200]}\"\n"
            "This is the core causal claim from the feed card. "
            "Your simplification MUST carry this mechanism — simplified vocabulary, preserved logic.\n\n"
        )
        return prefix + directive
    return directive


def _build_knowledge_state_section(knowledge: dict) -> str:
    """
    Inject the active conversation knowledge state.

    Uses conversation_state_service.format_state_for_prompt to produce
    a compact, ready-to-use section. Returns empty string when the state
    is too sparse to be useful (first turn, no mechanisms established).
    """
    if not knowledge:
        return ""
    try:
        from .conversation_state_service import format_state_for_prompt
        return format_state_for_prompt(knowledge)
    except Exception:
        return ""


def _build_tension_section(context: dict, mode: str = "normal") -> str:
    """
    Inject cognitive tension directive from the tension engine.

    Skipped for layman mode, trivial messages, and when no message is in context.
    Short version used for structured mode (web_search) since the JSON
    format directive already enforces insight density.
    """
    message = context.get("current_message", "")
    if not message:
        return ""
    try:
        from .tension_engine import build_tension_directive
        return build_tension_directive(
            message        = message,
            intent_profile = context.get("intent_profile", {}),
            domain         = context.get("domain_context", {}).get("domain", ""),
            conv_state     = context.get("conversation_knowledge", {}),
            mode           = mode,
        )
    except Exception:
        return ""


def _build_continuity_section(continuity: dict) -> str:
    """
    Inject cross-session learning history so the AI avoids repetition and builds
    on what the user already knows from previous sessions.
    """
    if not continuity or not continuity.get("topic"):
        return ""

    topic      = continuity["topic"]
    explained  = continuity.get("explained_concepts",    [])
    prior_recs = continuity.get("prior_recommendations", [])
    turns      = continuity.get("cross_session_turns",   0)
    sessions   = continuity.get("sessions_count",        0)

    if not explained and not prior_recs and turns == 0:
        return ""

    lines = [f"Cross-session learning history for \"{topic}\":"]

    if explained:
        lines.append(
            f"- Already explained across sessions: {', '.join(explained[:10])}.\n"
            "  Build on this knowledge — do not re-explain these from scratch."
        )

    if prior_recs:
        lines.append(
            f"- Previously recommended to the user: {', '.join(prior_recs[:6])}.\n"
            "  Skip repeating these recommendations unless the user asks."
        )

    if turns > 0 and sessions > 1:
        lines.append(
            f"- Discussed across {sessions} sessions ({turns} total turns)."
            " The user has meaningful familiarity — engage at appropriate depth."
        )

    return "\n".join(lines) if len(lines) > 1 else ""
