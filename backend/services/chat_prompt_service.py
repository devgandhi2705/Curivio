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
) -> list[dict]:
    """
    Build the full OpenAI-format messages list for the Groq API call.

    - Prepends the mode-aware system prompt.
    - Truncates history to the most recent MAX_HISTORY_TURNS turns.
    - Appends the new user message.
    """
    system_prompt = build_system_prompt(context, mode=mode)

    max_msgs = MAX_HISTORY_TURNS * 2
    truncated_history = history[-max_msgs:] if len(history) > max_msgs else history

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(truncated_history)
    messages.append({"role": "user", "content": user_message})
    return messages


# ═══════════════════════════════════════════════════════════════════════════════
# Mode-specific prompt builders
# ═══════════════════════════════════════════════════════════════════════════════

def _build_format_directive_section(format_intent: str) -> str:
    """
    Return the intent-aware format directive string, or empty string for "default".

    Injected into both natural and structured prompts to give the model
    structural guidance specific to the detected response intent.
    """
    return _FORMAT_DIRECTIVES.get(format_intent, "")


def _build_natural_prompt(context: dict, mode: str) -> str:
    """
    Minimal, natural-feeling system prompt for normal and layman chat.

    Injects: persona + depth instruction + format directive + conversation memory +
             optional layman directive + natural guidelines.
    Omits: research dumps, exploration history, JSON schema.
    """
    parts = [_PERSONA_NATURAL]

    # Depth instruction — calibrates verbosity and structure before anything else
    depth = context.get("response_depth", "standard")
    parts.append(_DEPTH_INSTRUCTIONS.get(depth, _DEPTH_INSTRUCTIONS["standard"]))

    # Intent-aware format directive — structural guidance for detected response shape
    # Skipped in layman mode: the Explain Simply directive is fully self-contained
    if mode != "layman":
        fmt = _build_format_directive_section(context.get("format_intent", "default"))
        if fmt:
            parts.append(fmt)

    # Conversation memory: most important for continuity (always inject if present)
    conv_section = _build_conversation_memory_section(context.get("conversation_memory", {}))
    if conv_section:
        parts.append(conv_section)

    # User profile: only inject a one-liner if interesting
    profile = context.get("user_profile", {})
    profile_line = _build_compact_profile(profile)
    if profile_line:
        parts.append(profile_line)

    # Layman directive when explain-simply mode is active
    if mode == "layman":
        layman = _build_layman_mode_section(context.get("layman_mode_context", {}))
        if layman:
            parts.append(layman)

    parts.append(_NATURAL_GUIDELINES)
    return "\n\n".join(parts)


def _build_structured_prompt(context: dict) -> str:
    """
    Full context injection for specialized research/analysis modes.

    Injects all available sections + structured JSON format directive.
    """
    parts = [_PERSONA]

    profile  = context.get("user_profile", {})
    research = context.get("research", {})
    session  = context.get("session", {})

    for builder, data in (
        (_build_profile_section,               profile),
        (_build_research_section,              research),
        (_build_session_section,               session),
        (_build_conversation_memory_section,   context.get("conversation_memory", {})),
        (_build_exploration_breadth_section,   context.get("exploration_breadth", {})),
        (_build_preference_snapshot_section,   context.get("preference_snapshot", {})),
        (_build_explanation_directive_section, context.get("learner_profile", {})),
        (_build_domain_directive_section,      context.get("domain_context", {})),
        (_build_continuity_section,            context.get("continuity", {})),
        (_build_action_result_section,         context.get("action_result", {})),
    ):
        section = builder(data)
        if section:
            parts.append(section)

    # Intent-aware format directive — guides response structure for the detected intent
    fmt = _build_format_directive_section(context.get("format_intent", "default"))
    if fmt:
        parts.append(fmt)

    parts.append(_GUIDELINES)
    parts.append(_STRUCTURED_FORMAT_DIRECTIVE)
    return "\n\n".join(parts)


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
  parallel items, headers only for 4+ genuinely distinct sections.
- Never add headers to a response that would naturally be 2–3 paragraphs of prose.
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
- When you reference a topic the user has already researched, build on that context rather than re-explaining from scratch.
- If this session already covered a concept, acknowledge it briefly and go deeper.
- Connect new questions to earlier parts of the conversation when relevant.
- Keep responses focused and avoid unnecessary repetition.
- If the user asks about something outside your knowledge, say so honestly."""

_STRUCTURED_FORMAT_DIRECTIVE = """\
OUTPUT FORMAT — MANDATORY:
You MUST respond with ONLY a valid JSON object. No text before or after the JSON. No markdown code fences.

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


_LAYMAN_MODE_DIRECTIVE = """\
ACTIVE RESPONSE MODE — EXPLAIN SIMPLY:
The user wants to understand this without prior expertise. Simple ≠ short. Simple means: easy to intuitively grasp.

THE GOAL: The user finishes reading and thinks "Oh — I finally understand this clearly."

This is INTELLIGENT SIMPLIFICATION — not childish simplification. The user is smart but new to this
specific domain. Do not condescend. Do not oversimplify to the point of misleading.

Structure your response in this sequence:
1. THE CORE IDEA — One plain sentence. What is this, in the simplest honest terms?
2. THE ANALOGY — "Think of it like…" Use something the reader already knows: roads, restaurants,
   sports, cooking. The analogy must carry the MAIN MECHANISM, not just the surface shape.
   Then bridge back explicitly: "In the same way, [the actual concept] works by [mechanism]…"
   — so the analogy clarifies rather than distracts.
3. WHY IT EXISTS — What problem does it solve? What was broken or missing before it?
   This grounds the concept in human motivation.
4. HOW IT WORKS — The actual mechanism, in plain language. Scaffold on the analogy from step 2.
   If a technical term is unavoidable, define it immediately in parentheses:
   "asymmetric encryption (a lock anyone can close, but only you can open)".
5. A REAL EXAMPLE — Name the company, event, or person. Not "some companies do this" —
   say which one, and what specifically happened.
6. THE INSIGHT — The one non-obvious thing worth knowing. What would genuinely surprise someone
   who just learned the basics? What makes this concept actually interesting or counterintuitive?
   This is the most valuable part of the response — do not skip it or bury it.

Tone and style:
- Lead with intuition, not definition. Never start with a Wikipedia-style "X is a Y that Z" sentence.
- Speak like a brilliant friend explaining over coffee — not a textbook, not a professor.
- Never be condescending. The user is intelligent but new to this specific domain.
- Connect to the user's project context and prior interests when relevant.

Do NOT:
- Open with a dictionary definition.
- Use unexplained acronyms or abbreviations.
- Write walls of text with no paragraph breaks.
- Over-simplify to the point of being misleading.
- Skip THE INSIGHT — it is what makes the response genuinely memorable.
"""


def _build_layman_mode_section(layman_context: dict) -> str:
    """Inject the Explain Simply directive when layman mode is active."""
    if not layman_context.get("active"):
        return ""
    return _LAYMAN_MODE_DIRECTIVE.strip()


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
