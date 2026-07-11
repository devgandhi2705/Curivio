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

from ..prompts.prompt_composer import PromptComposer

MAX_HISTORY_TURNS = 6

# Modes that receive the full structured context + JSON schema
_STRUCTURED_MODES = frozenset({"deep_research", "web_search", "roadmap", "compare", "trend_analysis"})

# ── Depth detection ───────────────────────────────────────────────────────────

_QUICK_GREETINGS = frozenset(
    "hi hey hello sup yo hiya howdy greetings good morning good afternoon good evening "
    "thanks thank you bye goodbye ok okay cool noted got it lol".split()
)

_DETAILED_TRIGGERS = frozenset(
    "in detail detailed deeply deep explain properly thoroughly complete completely "
    "comprehensive full understand properly how does internally step by step "
    "teach me walk me through guide me from scratch everything about all about".split()
)

_RESEARCH_TRIGGERS = frozenset(
    "research analyze analyse compare deeply contrast tradeoffs implications "
    "perspectives viewpoints history historical evolution future outlook "
    "multi-angle cross-domain strategic implications contradictions competing".split()
)


def detect_depth(message: str, mode: str = "normal") -> str:
    """
    Classify the intended response depth from user phrasing and mode.

    Returns one of: "quick" | "standard" | "detailed" | "research"

    - Mode deep_research always → research
    - Short / casual / greeting → quick
    - Explicit depth phrases → detailed or research
    - Default → standard
    """
    if mode == "deep_research":
        return "research"

    m = message.strip().lower()

    # Typo or nonsense: very short, no real words
    if len(m) <= 6 and not any(c.isalpha() for c in m):
        return "quick"

    # Greeting / casual
    tokens = set(m.split())
    if tokens <= _QUICK_GREETINGS or (len(tokens) <= 3 and tokens & _QUICK_GREETINGS):
        return "quick"

    # Very short factual asks (< 5 words, no depth trigger)
    if len(tokens) <= 4 and not (tokens & _DETAILED_TRIGGERS) and not (tokens & _RESEARCH_TRIGGERS):
        return "quick"

    # Research-grade
    if tokens & _RESEARCH_TRIGGERS:
        return "research"

    # Detailed
    if tokens & _DETAILED_TRIGGERS:
        return "detailed"

    return "standard"


# ── Depth instructions injected into system prompt ────────────────────────────

_DEPTH_INSTRUCTIONS: dict[str, str] = {
    "quick": """\
RESPONSE DEPTH: Quick
- Reply in 1–3 short paragraphs. Conversational prose — no headers, no bullet lists.
- For greetings or casual inputs: match the energy — brief and warm.
- For typos or gibberish: one sentence asking what they meant.
- Never generate code unless a one-liner IS the entire answer.
- Stop the moment the question is answered. No summaries, no suggestions.""",

    "standard": """\
RESPONSE DEPTH: Standard
- Open with the direct answer in the first sentence — not a definition, not background context.
- Follow with 1–2 paragraphs that add mechanism, causality, or non-obvious implication.
- Explain WHY, not just WHAT — surface the underlying reason things work this way.
- Use a concrete named example: name the company, event, or person — not "companies often do this."
- No headers for responses under 4 paragraphs — continuous prose is clearer.
- No code for conceptual, economics, history, or social questions.
- End when the essential point has been made. No "in summary" closer, no padding.""",

    "detailed": """\
RESPONSE DEPTH: Detailed
- Structure: intuition first → mechanism → concrete named example → implications and significance.
- Every claim needs causality: not "X is important" but "X matters because Y, which causes Z."
- Name specifics: actor, event, data point, company, framework. Never "some organisations do this."
- Surface the non-obvious: hidden dependencies, second-order effects, counterintuitive results.
- Insight density over paragraph count — every sentence must earn its place. Cut anything redundant.
- ## headers only for 3+ genuinely distinct analytical sections.
- No code for economics, history, social sciences, or conceptual explanations.
- Connect to what the user has already asked or explored in this conversation.""",

    "research": """\
RESPONSE DEPTH: Research-Grade
- Analyse, do not survey. The goal is genuine understanding, not encyclopedic coverage.
- Dimensions to address: causal mechanisms, competing viewpoints, hidden tradeoffs, structural
  dynamics, second-order effects, historical roots, strategic implications, genuine uncertainties.
- Synthesise across perspectives — build a coherent analytical argument, not a list of facts.
- Name specifics: mechanisms, actors, data points, dates, frameworks — generic statements fail.
- Surface contradictions and expert disagreement where they exist — do not paper over them.
- Second-order effects and hidden dependencies often matter more than obvious surface findings.
- Acknowledge genuine uncertainty clearly — it increases the quality of reasoning, not the doubt.
- Feel like a genuine analyst memo: insight-dense, argument-driven, intellectually honest.
- ## headers for clearly distinct analytical dimensions — aid navigation, not decoration.""",
}


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

    Mode routing
    ------------
    normal / feed_discussion
        Minimal prompt: persona + conversation memory + natural guidelines.
        No JSON schema. No research dumps. Feels like a natural AI assistant.

    layman
        Same minimal prompt but with the Explain Simply directive injected.

    web_search / deep_research / roadmap / compare / trend_analysis
        Full context injection (profile, research, domain, action) + structured
        JSON format directive so the renderer can display rich sections.
    """
    if mode in _STRUCTURED_MODES:
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

    Injects: persona + depth instruction + format directive + conversation memory +
             optional layman directive + natural guidelines.
    Omits: research dumps, exploration history, JSON schema.
    """
    composer = PromptComposer()
    composer.add_section("persona",        _PERSONA_NATURAL,
                         priority=1, required=True,  source_pack="")

    # Learning system framing — positions this interaction in the depth hierarchy.
    # Injected first so every subsequent directive is read within the learning journey context.
    composer.add_section("learning_system", _build_learning_system_section(context, mode),
                         priority=2, required=False, source_pack="dynamic")

    # Depth instruction — calibrates verbosity and structure before anything else
    depth = context.get("response_depth", "standard")
    composer.add_section("depth",          _DEPTH_INSTRUCTIONS.get(depth, _DEPTH_INSTRUCTIONS["standard"]),
                         priority=2, required=True,  source_pack="")

    # Intent-aware format directive — structural guidance for detected response shape.
    # Skipped in layman mode: the Explain Simply directive is fully self-contained.
    # Passes intent_profile so blended multi-intent prompts get composed directives.
    if mode != "layman":
        composer.add_section("format_directive", _build_format_directive_section(
            context.get("format_intent", "default"),
            intent_profile=context.get("intent_profile"),
        ),                   priority=3, required=False, source_pack="")

    # Conversation memory: most important for continuity (always inject if present)
    composer.add_section("conversation_memory", _build_conversation_memory_section(
        context.get("conversation_memory", {})
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
    composer.add_section("user_profile",   _build_compact_profile(context.get("user_profile", {})),
                         priority=3, required=False, source_pack="dynamic")

    # Dynamic narrative rhythm — rotates structural mode to prevent response homogeneity.
    # Skipped for layman (has its own structure) and quick depth (no structure needed).
    if mode != "layman":
        composer.add_section("narrative",  _build_narrative_section(context, mode),
                             priority=5, required=False, source_pack="dynamic")

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

    composer.add_section("guidelines",     _NATURAL_GUIDELINES,
                         priority=3, required=True,  source_pack="")
    return composer.build()


def _build_structured_prompt(context: dict) -> str:
    """
    Full context injection for specialized research/analysis modes.

    Injects all available sections + structured JSON format directive.
    """
    composer = PromptComposer()
    composer.add_section("persona",        _PERSONA,
                         priority=1, required=True,  source_pack="")

    # Learning system framing — anchors the structured response to the user's learning journey.
    # Structured modes (web_search, deep_research) carry the most state; this ensures the AI
    # builds on established mechanisms rather than re-starting from scratch each time.
    composer.add_section("learning_system", _build_learning_system_section(context, mode="deep_research"),
                         priority=2, required=False, source_pack="dynamic")

    composer.add_section("user_profile",        _build_profile_section(context.get("user_profile", {})),
                         priority=2, required=False, source_pack="dynamic")
    composer.add_section("research",            _build_research_section(context.get("research", {})),
                         priority=1, required=False, source_pack="dynamic")
    composer.add_section("session",             _build_session_section(context.get("session", {})),
                         priority=3, required=False, source_pack="dynamic")
    composer.add_section("conversation_memory", _build_conversation_memory_section(context.get("conversation_memory", {})),
                         priority=2, required=False, source_pack="dynamic")
    composer.add_section("knowledge_state",     _build_knowledge_state_section(context.get("conversation_knowledge", {})),
                         priority=2, required=False, source_pack="dynamic")
    # Chat-3: semantic long-term memory recall + Feed-entry persistent anchor
    # (see _build_natural_prompt for full rationale — same sections, same
    # context keys, mirrored here for structured modes).
    composer.add_section("vector_memory",       context.get("vector_memory", ""),
                         priority=2, required=False, source_pack="dynamic")
    composer.add_section("feed_entry_anchor",   context.get("feed_entry_anchor", ""),
                         priority=2, required=False, source_pack="dynamic")
    composer.add_section("exploration_breadth", _build_exploration_breadth_section(context.get("exploration_breadth", {})),
                         priority=3, required=False, source_pack="dynamic")
    composer.add_section("preference_snapshot", _build_preference_snapshot_section(context.get("preference_snapshot", {})),
                         priority=3, required=False, source_pack="dynamic")
    composer.add_section("explanation_directive", _build_explanation_directive_section(context.get("learner_profile", {})),
                         priority=3, required=False, source_pack="dynamic")
    composer.add_section("domain_directive",    _build_domain_directive_section(context.get("domain_context", {})),
                         priority=3, required=False, source_pack="dynamic")
    composer.add_section("continuity",          _build_continuity_section(context.get("continuity", {})),
                         priority=2, required=False, source_pack="dynamic")
    composer.add_section("action_result",       _build_action_result_section(context.get("action_result", {})),
                         priority=2, required=False, source_pack="dynamic")

    # Intent-aware format directive — guides response structure for the detected intent.
    # Passes intent_profile so blended multi-intent prompts get composed directives.
    composer.add_section("format_directive", _build_format_directive_section(
        context.get("format_intent", "default"),
        intent_profile=context.get("intent_profile"),
    ),                   priority=3, required=False, source_pack="")

    # Cognitive tension — short version for structured modes; informs key_takeaway quality.
    composer.add_section("tension",        _build_tension_section(context, mode="deep_research"),
                         priority=3, required=False, source_pack="dynamic")

    composer.add_section("guidelines",     _GUIDELINES,
                         priority=3, required=True,  source_pack="")
    composer.add_section("format_schema",  _STRUCTURED_FORMAT_DIRECTIVE,
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
Be direct, thoughtful, and conversational. Match your depth to what the user needs."""

_NATURAL_GUIDELINES = """\
CONVERSATIONAL RULES:
- Match response length to the question. A two-sentence question rarely needs a five-paragraph answer.
- Do NOT open every reply by naming yourself. Don't say "I'm Curivio" or "Great question!" — just answer.
- Conversational questions get conversational answers: prose, not bullet lists.
- Prioritise causality over description: explain WHY things work the way they do, not just WHAT they are.
- Name specifics rather than generalities: the company, the event, the mechanism, the person.
- Surface the non-obvious: second-order effects and hidden implications are more valuable than
  restating what the user likely already knows.
- Use markdown only when it genuinely aids clarity: code blocks for code, bullets for genuinely
  parallel items, headers only for 4+ genuinely distinct sections — never for prose that naturally
  fits 2–3 paragraphs.
- If a topic came up earlier in this conversation, build on it — do not re-explain from scratch.
- If the user sends a greeting or very short message, reply briefly and warmly. Do not lecture.
- Be honest when uncertain. End when you've said the essential thing — no padding, no "in summary" closers.

CODE GENERATION RULES:
- Only include code when code IS the answer (e.g. "write me a function", "show me the syntax").
- Never add code to conceptual explanations, history, economics, or social science questions.
- Never include code as a "bonus" at the end of a prose answer.
- When code is appropriate: show a minimal working example — not a full application scaffold.
- Match language to what the user specified, or infer from context.
- Add inline comments only if the code does something non-obvious."""

_GUIDELINES = """\
Guidelines:
- Give clear, structured answers. Use bullet points or code blocks where helpful.
- Tailor complexity to the user's learning stage and stated interests.
- Build on what this session has already covered: go deeper, don't re-explain; connect new questions to prior context.
- Keep responses focused and avoid unnecessary repetition.
- If the user asks about something outside your knowledge, say so honestly."""

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


def _build_profile_section(profile: dict) -> str:
    if not profile:
        return ""

    lines = ["User learning profile:"]
    stage = profile.get("learning_stage")
    if stage:
        lines.append(f"- Learning stage: {stage}")

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


def _build_compact_profile(profile: dict) -> str:
    """One-liner profile hint for natural mode — avoids verbose context dumps."""
    if not profile:
        return ""
    stage     = profile.get("learning_stage", "")
    interests = profile.get("top_interests", [])
    if not stage and not interests:
        return ""
    parts = []
    if interests:
        parts.append(f"interests: {', '.join(interests[:3])}")
    if stage:
        parts.append(f"level: {stage}")
    return f"User context — {'; '.join(parts)}." if parts else ""


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


def _build_conversation_memory_section(conv: dict) -> str:
    if not conv or conv.get("message_count", 0) == 0:
        return ""

    turns   = conv.get("session_turns", 0)
    topics  = conv.get("topics_discussed", [])
    last_qs = conv.get("last_user_messages", [])

    lines = [f"This conversation ({turns} turn{'s' if turns != 1 else ''} so far):"]

    if topics:
        lines.append(f"- Topics discussed: {', '.join(topics)}")
        lines.append(
            "- Do not re-explain these topics from scratch unless the user asks. "
            "Build on what has already been covered."
        )

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


def _build_narrative_section(context: dict, mode: str = "normal") -> str:
    """
    Inject the dynamic narrative rhythm directive.

    Skipped for layman mode (its own structure is complete) and for quick-depth
    responses (greetings, one-liners). The service records the selected mode in
    its session fingerprint so subsequent turns automatically rotate away from it.
    """
    if mode == "layman":
        return ""
    depth = context.get("response_depth", "standard")
    if depth == "quick":
        return ""
    session_id = (context.get("conversation_memory", {}) or {}).get("session_id", "")
    try:
        from .narrative_rhythm_service import build_narrative_directive
        return build_narrative_directive(
            session_id     = session_id,
            intent_profile = context.get("intent_profile", {}),
            domain         = context.get("domain_context", {}).get("domain", ""),
            response_depth = depth,
        )
    except Exception:
        return ""


def _build_tension_section(context: dict, mode: str = "normal") -> str:
    """
    Inject cognitive tension directive from the tension engine.

    Skipped for layman mode, trivial messages, and when no message is in context.
    Short version used for structured modes (web_search, deep_research) since
    the JSON format directive already enforces insight density.
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
