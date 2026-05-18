"""
Conversational AI chat orchestration and message storage.

Coordinates context retrieval, prompt construction, AI response generation,
and persistent storage of the conversation in chat_messages.

Public API
----------
chat(session_id, message, topic_hint=None) -> dict
get_history(session_id, limit=20) -> list[dict]
clear_history(session_id) -> int
list_sessions(limit=20) -> list[dict]
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from ..utils.db import get_connection
from .memory_injection_service import inject_memory
from .chat_prompt_service import build_messages

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

_FEED_ACTION_TO_MODE: dict[str, str] = {
    "ask_about":         "normal",
    "continue_research": "web_search",
    "deep_research":     "deep_research",
    "explain_simply":    "layman",
}


def chat(
    session_id:   str,
    message:      str,
    topic_hint:   str | None = None,
    chat_mode:    str        = "normal",
    feed_context: dict | None = None,
) -> dict:
    """
    Process one conversational turn and return the assistant's response.

    Steps
    -----
    1. Detect topic hint from message if not supplied.
    2. Fetch conversation history for this session.
    3. Build memory-injected context (user profile + research + session memory
       + conversation memory + exploration breadth + preference snapshot).
    4. Build OpenAI-format messages list.
    5. Call Groq.
    6. Persist both user message and assistant response.
    7. Detect and dispatch a research action if the message contains one.
    8. Generate follow-up recommendations from stored expansion data.
    9. Return structured response dict.

    Return shape
    ------------
    {
      "session_id":    str,
      "message_id":    int,       # row ID of the assistant message
      "response":      str,
      "topic_hint":    str | None,
      "action":        str | None, # detected action key, e.g. "show_repos"
      "recommendations": {
        "based_on_topic":  str | None,
        "source":          "stored" | "empty",
        "next_topics":     [{"topic": str, "reason": str}],
        "prerequisites":   [{"topic": str, "reason": str}],
        "advanced_topics": [{"topic": str, "reason": str}],
      },
      "context_used": {
        "has_deep_research":   bool,
        "has_learning_path":   bool,
        "has_topic_expansion": bool,
        "has_github_repos":    bool,
        "interests_count":     int,
        "history_turns":       int,
      },
      "created_at": str,
    }
    """
    session_id = session_id.strip()
    message    = message.strip()
    if not session_id:
        raise ValueError("session_id must not be empty")
    if not message:
        raise ValueError("message must not be empty")

    # ── Feed context: override topic and mode before intent detection ─────────
    if feed_context:
        if topic_hint is None:
            topic_hint = feed_context.get("insight_title") or _detect_topic_hint(message)
        if chat_mode == "normal":
            chat_mode = _FEED_ACTION_TO_MODE.get(
                feed_context.get("action", "ask_about"), "normal"
            )
    elif topic_hint is None:
        topic_hint = _detect_topic_hint(message)

    # ── Layman mode: restore from session if request didn't override ─────────
    if chat_mode == "normal":
        try:
            from .chat_title_service import get_session_conversation_mode
            if get_session_conversation_mode(session_id) == "layman":
                chat_mode = "layman"
        except Exception:
            pass

    # Auto-upgrade mode based on conversational research intent
    # (only fires when the user has left the mode on "normal" and no feed context)
    from .chat_intent_service import detect_intent
    intent      = detect_intent(message)
    auto_mode   = False
    query_type  = "default"
    subjects: list[str] = []

    if not feed_context and chat_mode == "normal" and intent["intent"] != "normal":
        chat_mode  = intent["recommended_mode"]
        auto_mode  = True
        query_type = intent["query_type"]
        subjects   = intent["subjects"]
        if intent["topic"] and not topic_hint:
            topic_hint = intent["topic"]

    # Load history
    history = _load_history_messages(session_id, limit=50)
    history_turns = len(history) // 2

    # Build memory-injected context
    context = inject_memory(session_id, topic_hint)

    # ── Inject layman mode flag into context for system prompt ────────────────
    if chat_mode == "layman":
        context["layman_mode_context"] = {"active": True}

    # Classify domain — prefer feed_context domain when available
    from .domain_classifier_service import get_domain_context as _get_domain
    context["domain_context"] = _get_domain(
        feed_context.get("domain") or topic_hint or message
        if feed_context else topic_hint or message
    )

    # Detect and dispatch research action (non-blocking; enriches context)
    from .action_router_service import route as route_action
    action_result = route_action(message, topic_hint, context)
    if action_result:
        context["action_result"] = action_result

    # Depth detection — calibrates response verbosity before prompt assembly
    from .chat_prompt_service import detect_depth
    context["response_depth"] = detect_depth(message, chat_mode)

    # Mode-specific retrieval
    # ask_about / explain_simply / layman: skip retrieval — context already provided
    from .chat_modes_service import prepare_mode_context, build_mode_system_note, build_feed_context_note
    skip_retrieval = (
        (feed_context and feed_context.get("action") in ("ask_about", "explain_simply"))
        or chat_mode == "layman"
    )
    if skip_retrieval:
        mode_context = {}
    else:
        mode_context = prepare_mode_context(
            chat_mode, message, topic_hint,
            query_type=query_type, subjects=subjects,
        )

    # Build messages for Groq
    messages_payload = build_messages(history, message, context, mode=chat_mode)

    # Inject feed context note first (background knowledge)
    if feed_context:
        feed_note = build_feed_context_note(feed_context)
        messages_payload = _inject_mode_note(messages_payload, feed_note)

    # Inject mode/retrieval note on top (live data, when present)
    mode_note = build_mode_system_note(mode_context)
    if mode_note:
        messages_payload = _inject_mode_note(messages_payload, mode_note)

    # Inject title extraction note for first message of new sessions
    _is_new = len(history) == 0
    if _is_new:
        from .chat_title_service import make_title_system_note
        messages_payload = _inject_mode_note(messages_payload, make_title_system_note())

    # Call AI
    from .grok_service import ask_grok_chat
    raw_response = ask_grok_chat(messages_payload)

    # Extract and strip [TITLE: ...] prefix for new sessions
    if _is_new:
        from .chat_title_service import (
            extract_title, strip_title_prefix, save_session_title, generate_fallback_title,
        )
        _title = extract_title(raw_response)
        response_text = strip_title_prefix(raw_response)
        if not _title:
            _title = generate_fallback_title(message, topic_hint)
        if _title:
            save_session_title(session_id, _title)
    else:
        response_text = raw_response

    # Persist conversation
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    _save_message(session_id, "user",      message,       topic_hint, now)
    msg_id = _save_message(session_id, "assistant", response_text, topic_hint, now)

    # Persist layman conversation mode so subsequent turns stay simplified
    if chat_mode == "layman":
        try:
            from .chat_title_service import set_session_conversation_mode
            set_session_conversation_mode(session_id, "layman")
        except Exception:
            logger.exception("chat_service: layman mode persistence failed (non-fatal)")

    research = context.get("research", {})
    profile  = context.get("user_profile", {})
    conv_mem = context.get("conversation_memory", {})
    breadth  = context.get("exploration_breadth", {})
    learner  = context.get("learner_profile", {})

    # Follow-up recommendations (non-blocking; falls back to empty on error)
    from .follow_up_service import get_recommendations
    recommendations = get_recommendations(
        topic           = topic_hint or "",
        explored_topics = breadth.get("all_topics", []),
        learner_level   = learner.get("inferred_level", "intermediate"),
    )

    # Record continuity data for future sessions (non-blocking; errors are silent)
    if topic_hint:
        try:
            from .continuity_service import record_concepts, record_recommendations
            concepts = _extract_concepts_from_context(context)
            record_concepts(topic_hint, concepts, session_id)
            record_recommendations(session_id, topic_hint, recommendations)
        except Exception:
            logger.exception("chat_service: continuity recording failed (non-fatal)")

    return {
        "session_id":         session_id,
        "message_id":         msg_id,
        "response":           response_text,
        "topic_hint":         topic_hint,
        "chat_mode":          chat_mode,
        "auto_mode":          auto_mode,
        "action":             action_result.get("action") if action_result else None,
        "recommendations":    recommendations,
        "structured_response": _parse_structured_response(response_text),
        "context_used": {
            "has_deep_research":    research.get("has_deep_research",    False),
            "has_learning_path":    research.get("has_learning_path",    False),
            "has_topic_expansion":  research.get("has_topic_expansion",  False),
            "has_github_repos":     research.get("has_github_repos",     False),
            "interests_count":      len(profile.get("top_interests", [])),
            "history_turns":        history_turns,
            "topics_in_session":    len(conv_mem.get("topics_discussed", [])),
            "total_topics_explored": breadth.get("total_explored", 0),
        },
        "created_at": now,
    }


def chat_stream(
    session_id:   str,
    message:      str,
    topic_hint:   str | None  = None,
    chat_mode:    str         = "normal",
    feed_context: dict | None = None,
):
    """
    Sync generator — yields NDJSON lines for a single conversational turn.

    Line types
    ----------
    {"t": "chunk", "v": "<text>"}          — AI text arriving incrementally
    {"t": "done",  <full metadata>}        — final metadata after stream ends
    {"t": "error", "message": "<reason>"}  — unrecoverable error; stream stops

    Callers should iterate until exhaustion or until an "error" event is seen.
    """
    session_id = session_id.strip()
    message    = message.strip()
    if not session_id:
        yield json.dumps({"t": "error", "message": "session_id must not be empty"}) + "\n"
        return
    if not message:
        yield json.dumps({"t": "error", "message": "message must not be empty"}) + "\n"
        return

    # ── Context preparation ───────────────────────────────────────────────────
    auto_mode   = False
    query_type  = "default"
    subjects: list[str] = []

    try:
        # Feed context: override topic and mode before intent detection
        if feed_context:
            if topic_hint is None:
                topic_hint = feed_context.get("insight_title") or _detect_topic_hint(message)
            if chat_mode == "normal":
                chat_mode = _FEED_ACTION_TO_MODE.get(
                    feed_context.get("action", "ask_about"), "normal"
                )
        elif topic_hint is None:
            topic_hint = _detect_topic_hint(message)

        # Layman mode: restore from session if request didn't override
        if chat_mode == "normal":
            try:
                from .chat_title_service import get_session_conversation_mode
                if get_session_conversation_mode(session_id) == "layman":
                    chat_mode = "layman"
            except Exception:
                pass

        # Auto-upgrade mode from intent when user left it on "normal" and no feed context
        from .chat_intent_service import detect_intent as _detect_intent
        intent = _detect_intent(message)
        if not feed_context and chat_mode == "normal" and intent["intent"] != "normal":
            chat_mode  = intent["recommended_mode"]
            auto_mode  = True
            query_type = intent["query_type"]
            subjects   = intent["subjects"]
            if intent["topic"] and not topic_hint:
                topic_hint = intent["topic"]

        history       = _load_history_messages(session_id, limit=50)
        history_turns = len(history) // 2

        from .memory_injection_service import inject_memory as _inject
        context = _inject(session_id, topic_hint)

        # Inject layman mode flag into context for system prompt
        if chat_mode == "layman":
            context["layman_mode_context"] = {"active": True}

        from .domain_classifier_service import get_domain_context as _get_domain
        context["domain_context"] = _get_domain(
            feed_context.get("domain") or topic_hint or message
            if feed_context else topic_hint or message
        )

        from .action_router_service import route as route_action
        action_result = route_action(message, topic_hint, context)
        if action_result:
            context["action_result"] = action_result

        # Depth detection — calibrates response verbosity before prompt assembly
        from .chat_prompt_service import detect_depth as _detect_depth
        context["response_depth"] = _detect_depth(message, chat_mode)

        from .chat_prompt_service import build_messages as _build
        messages_payload = _build(history, message, context, mode=chat_mode)

        # Inject feed context note first (background knowledge)
        if feed_context:
            from .chat_modes_service import build_feed_context_note
            feed_note = build_feed_context_note(feed_context)
            messages_payload = _inject_mode_note(messages_payload, feed_note)

    except Exception:
        logger.exception("chat_stream: context preparation failed")
        yield json.dumps({"t": "error", "message": "Failed to prepare context"}) + "\n"
        return

    # ── Mode-specific retrieval ───────────────────────────────────────────────
    from .chat_modes_service import (
        prepare_mode_context,
        build_mode_system_note,
        stream_status_event,
        stream_research_progress,
    )

    # ask_about / explain_simply / layman: skip retrieval — context already provided
    skip_retrieval = (
        (feed_context and feed_context.get("action") in ("ask_about", "explain_simply"))
        or chat_mode == "layman"
    )
    mode_context: dict = {}

    try:
        if skip_retrieval:
            pass  # no retrieval, mode_context stays empty
        elif chat_mode == "deep_research":
            for event_type, event_val in stream_research_progress(
                message, topic_hint, query_type=query_type
            ):
                if event_type == "status":
                    yield json.dumps({"t": "status", "v": event_val}) + "\n"
                elif event_type == "result":
                    mode_context = event_val
        else:
            status = stream_status_event(chat_mode)
            if status:
                yield status
            mode_context = prepare_mode_context(
                chat_mode, message, topic_hint,
                query_type=query_type, subjects=subjects,
            )

        mode_note = build_mode_system_note(mode_context)
        if mode_note:
            messages_payload = _inject_mode_note(messages_payload, mode_note)
    except Exception:
        logger.exception("chat_stream: mode context preparation failed (non-fatal)")

    is_new_session = len(history) == 0

    # ── Inject title extraction note for new sessions ─────────────────────────
    if is_new_session:
        from .chat_title_service import make_title_system_note
        messages_payload = _inject_mode_note(messages_payload, make_title_system_note())

    # ── Stream AI response ────────────────────────────────────────────────────
    # Emit a status event before blocking on Groq so HF Spaces proxies don't
    # close the connection during the cold-start delay before the first chunk.
    yield json.dumps({"t": "status", "v": "Generating response…"}) + "\n"

    from .chat_title_service import stream_extract_state, advance_stream_state
    title_state     = stream_extract_state() if is_new_session else None
    collected:       list[str]  = []
    extracted_title: str | None = None

    try:
        from .grok_service import ask_grok_chat_stream
        for chunk in ask_grok_chat_stream(messages_payload):
            if title_state is not None:
                result = advance_stream_state(title_state, chunk)
                if result["title"] and not extracted_title:
                    extracted_title = result["title"]
                    yield json.dumps({"t": "title", "v": extracted_title}) + "\n"
                if result["forward"] is not None:
                    collected.append(result["forward"])
                    yield json.dumps({"t": "chunk", "v": result["forward"]}) + "\n"
            else:
                collected.append(chunk)
                yield json.dumps({"t": "chunk", "v": chunk}) + "\n"
    except Exception as exc:
        logger.exception("chat_stream: AI generation failed")
        yield json.dumps({"t": "error", "message": str(exc)}) + "\n"
        return

    response_text = "".join(collected)

    # ── Extract sources to include in done event ─────────────────────────────
    sources: list[dict] = []
    try:
        if mode_context.get("mode") == "web_search":
            sources = [
                {"title": a.get("title", "").strip(), "url": a.get("url", "")}
                for a in mode_context.get("web_search_results", [])
                if a.get("url")
            ]
        elif mode_context.get("mode") == "deep_research":
            sources = [
                {"title": a.get("title", "").strip(), "url": a.get("url", "")}
                for a in mode_context.get("articles", [])
                if a.get("url")
            ]
    except Exception:
        pass

    # ── Persist messages ──────────────────────────────────────────────────────
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    user_msg_id = 0
    try:
        user_msg_id = _save_message(session_id, "user",      message,       topic_hint, now)
        msg_id      = _save_message(session_id, "assistant", response_text, topic_hint, now)
    except Exception:
        logger.exception("chat_stream: message persistence failed")
        msg_id = 0

    if is_new_session and not extracted_title:
        # LLM didn't output [TITLE: ...] — derive title from the user's message
        try:
            from .chat_title_service import generate_fallback_title, save_session_title
            extracted_title = generate_fallback_title(message, topic_hint)
            save_session_title(session_id, extracted_title)
            yield json.dumps({"t": "title", "v": extracted_title}) + "\n"
        except Exception:
            logger.exception("chat_stream: fallback title generation failed (non-fatal)")
    elif extracted_title:
        try:
            from .chat_title_service import save_session_title
            save_session_title(session_id, extracted_title)
        except Exception:
            logger.exception("chat_stream: title persistence failed (non-fatal)")

    # Persist layman conversation mode so subsequent turns stay simplified
    if chat_mode == "layman":
        try:
            from .chat_title_service import set_session_conversation_mode
            set_session_conversation_mode(session_id, "layman")
        except Exception:
            logger.exception("chat_stream: layman mode persistence failed (non-fatal)")

    # ── Post-stream enrichment ────────────────────────────────────────────────
    research = context.get("research", {})
    profile  = context.get("user_profile", {})
    conv_mem = context.get("conversation_memory", {})
    breadth  = context.get("exploration_breadth", {})
    learner  = context.get("learner_profile", {})

    try:
        from .follow_up_service import get_recommendations
        recommendations = get_recommendations(
            topic           = topic_hint or "",
            explored_topics = breadth.get("all_topics", []),
            learner_level   = learner.get("inferred_level", "intermediate"),
        )
    except Exception:
        logger.exception("chat_stream: recommendations failed (non-fatal)")
        recommendations = {
            "based_on_topic": None, "source": "empty",
            "next_topics": [], "prerequisites": [], "advanced_topics": [],
        }

    if topic_hint:
        try:
            from .continuity_service import record_concepts, record_recommendations
            concepts = _extract_concepts_from_context(context)
            record_concepts(topic_hint, concepts, session_id)
            record_recommendations(session_id, topic_hint, recommendations)
        except Exception:
            logger.exception("chat_stream: continuity recording failed (non-fatal)")

    yield json.dumps({
        "t":                   "done",
        "message_id":          msg_id,
        "user_message_id":     user_msg_id,
        "topic_hint":          topic_hint,
        "title":               extracted_title,
        "sources":             sources,
        "chat_mode":           chat_mode,
        "auto_mode":           auto_mode,
        "action":              action_result.get("action") if action_result else None,
        "recommendations":     recommendations,
        "structured_response": _parse_structured_response(response_text),
        "context_used": {
            "has_deep_research":     research.get("has_deep_research",    False),
            "has_learning_path":     research.get("has_learning_path",    False),
            "has_topic_expansion":   research.get("has_topic_expansion",  False),
            "has_github_repos":      research.get("has_github_repos",     False),
            "interests_count":       len(profile.get("top_interests", [])),
            "history_turns":         history_turns,
            "topics_in_session":     len(conv_mem.get("topics_discussed", [])),
            "total_topics_explored": breadth.get("total_explored", 0),
        },
        "created_at": now,
    }) + "\n"


def get_history(session_id: str, limit: int = 20) -> list[dict]:
    """
    Return the most recent *limit* messages for *session_id*, oldest first.

    Each entry: {id, session_id, role, content, topic_hint, created_at}
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, session_id, role, content, topic_hint, created_at
            FROM   chat_messages
            WHERE  session_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT  ?
            """,
            (session_id, limit),
        ).fetchall()

    return [
        {
            "id":         r["id"],
            "session_id": r["session_id"],
            "role":       r["role"],
            "content":    r["content"],
            "topic_hint": r["topic_hint"],
            "created_at": r["created_at"],
        }
        for r in reversed(rows)
    ]


def clear_history(session_id: str) -> int:
    """Delete all messages for *session_id* and return the number of rows deleted."""
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM chat_messages WHERE session_id = ?",
            (session_id,),
        )
        return cur.rowcount


def list_sessions(limit: int = 20, user_id: str | None = None) -> list[dict]:
    """
    Return a summary of recent chat sessions, most-recently-active first.

    Each entry: {session_id, message_count, last_active_at, first_topic_hint, title}
    """
    from .chat_title_service import list_sessions_with_titles
    return list_sessions_with_titles(limit, user_id=user_id)


# ═══════════════════════════════════════════════════════════════════════════════
# Internals
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_structured_response(text: str) -> dict | None:
    """
    Try to extract a structured JSON response from the LLM output.

    Handles:
    - Clean JSON
    - JSON wrapped in ```json...``` fences
    - JSON embedded after introductory prose

    Returns the parsed dict if it contains a 'response_type' key, else None.
    """
    import re as _re

    cleaned = text.strip()
    # Strip markdown fences
    cleaned = _re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = _re.sub(r"\s*```\s*$", "", cleaned).strip()

    def _valid(d: dict) -> bool:
        return isinstance(d, dict) and "response_type" in d

    try:
        data = json.loads(cleaned)
        if _valid(data):
            return data
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: find first {...} block spanning the whole string
    match = _re.search(r"\{.*\}", cleaned, _re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            if _valid(data):
                return data
        except (json.JSONDecodeError, ValueError):
            pass

    return None


def _save_message(
    session_id: str,
    role: str,
    content: str,
    topic_hint: str | None,
    created_at: str,
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO chat_messages (session_id, role, content, topic_hint, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, role, content, topic_hint, created_at),
        )
        return cur.lastrowid


def _load_history_messages(session_id: str, limit: int = 50) -> list[dict]:
    """Return up to *limit* messages as OpenAI-format dicts (role + content)."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT role, content
            FROM   chat_messages
            WHERE  session_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT  ?
            """,
            (session_id, limit),
        ).fetchall()

    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def _detect_topic_hint(message: str) -> str | None:
    """
    Scan *message* for known topics from user preferences and research sessions.
    Returns the best-matching topic name or None.
    """
    try:
        from ..utils.db import get_connection as _gc
        message_lower = message.lower()

        with _gc() as conn:
            pref_rows = conn.execute(
                "SELECT topic FROM user_preferences ORDER BY preference_score DESC LIMIT 30"
            ).fetchall()
            session_rows = conn.execute(
                "SELECT DISTINCT topic FROM research_sessions ORDER BY recorded_at DESC LIMIT 30"
            ).fetchall()

        candidates = [r["topic"] for r in pref_rows] + [r["topic"] for r in session_rows]

        for topic in candidates:
            if topic.lower() in message_lower:
                return topic

        return None
    except Exception:
        return None


def _inject_mode_note(messages: list[dict], note: str) -> list[dict]:
    """
    Insert *note* as a system message immediately before the last user message
    so the LLM sees retrieval data just before answering.
    """
    result = list(messages)
    # Find the last user message index
    last_user = max(
        (i for i, m in enumerate(result) if m.get("role") == "user"),
        default=None,
    )
    insert_at = last_user if last_user is not None else len(result)
    result.insert(insert_at, {"role": "system", "content": note})
    return result


def _extract_concepts_from_context(context: dict) -> list[str]:
    """
    Pull concept names from the injected context for continuity recording.

    Sources (in priority order):
      1. Deep research key_concepts for the current topic
      2. Action result key_concepts / beginner step concepts
    Returns up to 12 unique, non-empty strings.
    """
    seen: set[str] = set()
    result: list[str] = []

    def _add(text: str) -> None:
        t = text.strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            result.append(t)

    # 1. Deep research key_concepts
    deep = context.get("research", {}).get("deep_research", {})
    if isinstance(deep, dict):
        for c in deep.get("key_concepts", []):
            if isinstance(c, str):
                _add(c)

    # 2. Action result data
    action_data = context.get("action_result", {}).get("data", {})
    for c in action_data.get("key_concepts", []):
        if isinstance(c, str):
            _add(c)
    for step in action_data.get("beginner_steps", []):
        if isinstance(step, dict):
            _add(step.get("concept", ""))

    return result[:12]
