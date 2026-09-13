"""The chat system prompt — one builder for every turn.

There used to be two: a "natural" prompt and a Feed-linked "structured" one
that forced a JSON card schema. The JSON format had zero real uses since
2026-08-01, and the split let one prompt carry both _GUIDELINES ("use bullet
points") and RESPONSE PRINCIPLES ("decide the shape yourself") — a real logged
Feed turn carried both against a 6-token question and the model resolved the
contradiction by doing neither. One builder, one set of rules.

Order (static text first, so a provider can cache the prefix):
  1. Persona (with the user's name when known)
  2. Response principles — one copy; the simple-tone variant is the same list
     minus the two rules that contradict a mandated structure
  3. Simple-tone directive — only when the turn answers in that tone
  4. Memory, profile, Feed anchor, attachment awareness — only when present
  5. Crisis support — only when flagged, and always last, because it is the one
     block allowed to override everything above it

Public API
----------
build_response_principles(simple_tone) -> str
build_system_prompt(context, simple_tone=False) -> str
build_messages(history, user_message, context, simple_tone=False, attachments=None) -> list[dict]
MAX_HISTORY_TURNS
"""

from __future__ import annotations

from ..prompts.prompt_composer import PromptComposer
# Imported at module scope on purpose: a swallowed ImportError here would
# silently strip crisis support out of every prompt.
from .crisis_support_service import build_crisis_support_section

# Real data (665 turns): an average turn pair is ~439 tokens and a p95 assistant
# reply ~1200. The smallest prompt budget in the pool is ~16-17.5K tokens, so
# ~10K left for history is ~8 turns without risking the weakest leg.
MAX_HISTORY_TURNS = 8

_PERSONA = """\
You are Curivio — an intelligent research and learning companion.
Help the user understand ideas, explore topics, and think more clearly.
Be direct, thoughtful, and conversational. Match your depth to what the user needs.

You're a learning companion this person comes back to, not a one-off chatbot — lean on
what you know about how they think and what they've explored before, the way someone
who's worked with them for a while would. When you know their name, use it where it
feels human — greeting them by name when a conversation opens, or in a genuinely warm
or personal moment — not stapled onto the start of every reply."""

# One list, two renderings. `keep_when_simple=False` marks the two rules that
# structurally contradict the simple-tone directive's mandated 5-step shape
# ("decide the length yourself", "decide the shape yourself") — the old code
# kept a second 2,495-char copy of the whole block just to drop those two.
# Every other rule applies in both tones, so it exists once.
_PRINCIPLES: tuple[tuple[bool, str], ...] = (
    (True, 'Lead with the actual answer — not a definition, not throat-clearing, not "great question." '
           "Don't open by naming yourself."),
    (False, 'Decide length and depth from what this question needs. A quick factual question gets a few '
            'sentences; a real "explain this" gets the full teach-through, reasoned FROM any real material '
            'in front of you (prior discussion, a document, extracted source text) rather than staying '
            'generic. Depth means more real content — a named example, a concrete number, one more step of '
            'mechanism, a tension between sources — never longer sentences about the same thing, and never '
            'a restatement of what the user already has.'),
    (True, "Explain WHY, not just WHAT. Name specifics and surface the non-obvious — the company, the "
           "event, the mechanism, the second-order effect — rather than restating what they likely "
           "already know."),
    (False, "Decide the shape the same way: a genuine comparison can be a table, a process numbered, a set "
            "of options bulleted, a short answer plain prose. When an answer is long enough to need "
            "structure, open with the sentence that answers the question and give list-like material "
            "bullets with bolded lead-ins. A wall of undifferentiated paragraphs is the common failure; "
            "bulleting what is really one idea is the opposite one."),
    (True, "End on the open tension — the second-order effect, the thing that breaks, the reason a "
           "practitioner would care — never on a summary of what you just said."),
    (True, "Write code when it is genuinely the clearest answer, whatever the subject, and never tack it "
           "on as a bonus. Always fence it with a language tag (unfenced Python loses its indentation). "
           "Give it a sentence or two of framing unless the user asked for code only or it is one "
           "self-explanatory line."),
    (True, 'Say plainly what you are sure of. When you are inferring or working from memory, say so ("as '
           'far as I know", "I\'d want to check this"), and never invent a source or citation.'),
    (True, "If the user says your last answer missed the mark, change your approach — don't apologise and "
           "repeat it with more words."),
    (True, "Continuity: build on what this conversation already covered instead of re-explaining it. When "
           "a short or fragmentary message could plausibly extend the current thread, answer it as part of "
           "that thread; treat it as standalone only when the wording clearly changes the subject."),
)

_ATTACHMENT_AWARENESS = """\
ATTACHMENT AWARENESS:
- Images: when this turn includes an image, you genuinely receive and see its actual visual
  content through this interface — describe what you actually observe. Never say you cannot
  process, view, or see images; you can, and one may be attached right now.
- Documents: extracted document text in your context is labeled either "full text" (the complete
  file) or "showing the N most relevant excerpts out of M total" (a partial, retrieval-trimmed
  selection). When you were given excerpts, say so — "based on the visible excerpts" or similar —
  never claim to have read the entire document when you were only shown a portion of it."""


def build_response_principles(simple_tone: bool = False) -> str:
    """The principles block. Simple tone drops the two rules that contradict the
    directive's mandated structure and keeps every other one, unreworded."""
    lines = [f"- {text}" for keep_when_simple, text in _PRINCIPLES
             if keep_when_simple or not simple_tone]
    return "RESPONSE PRINCIPLES:\n" + "\n".join(lines)


def _build_persona_section(user_name: str = "") -> str:
    if user_name:
        return f"{_PERSONA}\n\nThe user's name is {user_name}."
    return _PERSONA


def _build_simple_tone_section(context: dict) -> str:
    """The mechanism-preserving simplification directive, with a domain-tailored
    analogy bank. The card's own mechanism sentence is NOT repeated here — it is
    already in the Feed note, and it used to appear up to four times per prompt."""
    from .layman_mode_service import build_layman_directive
    return build_layman_directive(
        domain=context.get("domain_context", {}).get("domain", ""),
        topic_hint=context.get("research", {}).get("topic") or None,
    )


def build_system_prompt(context: dict, simple_tone: bool = False) -> str:
    composer = PromptComposer()
    composer.add_section("persona", _build_persona_section(context.get("user_name", "")),
                         priority=1, required=True, source_pack="")
    composer.add_section("response_principles", build_response_principles(simple_tone),
                         priority=1, required=True, source_pack="")

    if simple_tone:
        composer.add_section("simple_tone", _build_simple_tone_section(context),
                             priority=2, required=False, source_pack="core_learning_pack")
        # Phase 4.6: concept anchors so a simplification can bridge from what
        # this user already learned in this project.
        shared = context.get("shared_learning_context", "")
        if shared and "ANALOGY ANCHORS" in shared:
            composer.add_section("simple_tone_anchors", shared,
                                 priority=2, required=False, source_pack="dynamic")

    # Continuity context — aggregated across the session, so genuinely additive
    # to the last-N-turns array build_messages sends alongside this prompt.
    composer.add_section("conversation_memory", _build_conversation_memory_section(
        context.get("conversation_memory", {}), include_recency=False),
        priority=2, required=False, source_pack="dynamic")
    composer.add_section("knowledge_state", _build_knowledge_state_section(
        context.get("conversation_knowledge", {})),
        priority=2, required=False, source_pack="dynamic")
    composer.add_section("vector_memory", context.get("vector_memory", ""),
                         priority=2, required=False, source_pack="dynamic")
    composer.add_section("feed_entry_anchor", context.get("feed_entry_anchor", ""),
                         priority=2, required=False, source_pack="dynamic")
    composer.add_section("user_profile", _build_compact_profile(context),
                         priority=3, required=False, source_pack="dynamic")

    if context.get("has_attachment"):
        composer.add_section("attachment_awareness", _ATTACHMENT_AWARENESS,
                             priority=3, required=True, source_pack="")

    # Gated on the classifier's crisis field with a code-level fail-safe and a
    # few-turn carry-forward (chat_service). Deliberately last: it is the one
    # block allowed to override what precedes it — specifically the principle
    # that pushback means "change your approach", which is what turned a real
    # crisis follow-up into an apology and a retraction.
    if context.get("crisis_active"):
        composer.add_section("crisis_support",
                             build_crisis_support_section(context.get("client_timezone")),
                             priority=1, required=True, source_pack="")
    return composer.build()


def build_messages(history: list[dict], user_message: str, context: dict,
                   simple_tone: bool = False, attachments: list[dict] | None = None) -> list[dict]:
    """System prompt + the last MAX_HISTORY_TURNS turns + this message.

    `attachments` (images only): the final user message becomes a list of parts
    (text + Gemini "media" file_uri parts), the real SDK content-block format.
    """
    messages = [{"role": "system", "content": build_system_prompt(context, simple_tone=simple_tone)}]
    max_messages = MAX_HISTORY_TURNS * 2
    messages.extend(history[-max_messages:] if len(history) > max_messages else history)

    if attachments:
        parts = [{"type": "text", "text": user_message}] if user_message else []
        parts += [{"type": "media", "file_uri": a["uri"], "mime_type": a["mime_type"]}
                  for a in attachments]
        messages.append({"role": "user", "content": parts})
    else:
        messages.append({"role": "user", "content": user_message})
    return messages


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
