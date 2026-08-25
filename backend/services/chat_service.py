"""
Conversational AI chat orchestration and message storage.

Coordinates context retrieval, prompt construction, AI response generation,
and persistent storage of the conversation in chat_messages.

Public API
----------
chat_stream(session_id, message, topic_hint=None) -> Iterator[str]
get_history(session_id, limit=20) -> list[dict]
clear_history(session_id) -> int
list_sessions(limit=20) -> list[dict]
sweep_expired_attachments() -> dict   Chat-R13 admin cleanup — see docstring below.
attachment_belongs_to_session(session_id, attachment_id) -> bool   Chat-R15a ownership check.
get_document_owner_session(attachment_id) -> str | None   Chat-R15c permanent owner lookup, survives sweep.
list_session_attachments(session_id) -> list[dict]   Chat-R16 files panel — every attachment, unbounded.
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import PurePosixPath
from uuid import uuid4

from ..utils.db import get_connection
from . import r2_storage_service
from .memory_injection_service import inject_memory
from .chat_prompt_service import build_messages

logger = logging.getLogger(__name__)

# Chat-R4b: classify_message() is a real, blocking LLM round-trip (1-8s) with
# no data dependency on anything context-prep computes (message text is its
# only real input) — submitted here as soon as chat_mode is final (Chat-R4b
# insertion point below) so it overlaps with context prep instead of
# following it serially. Module-level pool so a thread isn't spun up fresh
# per turn; sized well above realistic concurrent-turn counts since each
# task is network-bound, not CPU-bound.
_ROUTER_EXECUTOR = ThreadPoolExecutor(max_workers=16, thread_name_prefix="chat-router")

# Phase U: how many turns AFTER a crisis turn (fresh or fail-safe) still get
# CRISIS AND DISTRESS SUPPORT injected regardless of that turn's own
# classification. See the set_session_crisis_expiry call site for the full
# reasoning (generous but bounded, not permanent-for-session).
_CRISIS_WINDOW_TURNS = 5


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

_FEED_ACTION_TO_MODE: dict[str, str] = {
    "ask_about":         "normal",
    "continue_research": "web_search",
    "explain_simply":    "layman",
}

# Layman-fix pass: chat_mode=="normal" alone can't distinguish an explicit exit
# (the frontend's mode toggle really does send "normal" when the user picks it)
# from a stale default (frontend's local sticky state lost on reload, message
# sent with whatever chat_mode defaults to, session still mid-layman server-side)
# — both produce the exact same request. Message text is the only reliable
# unambiguous signal available without a frontend wire-protocol change, so an
# explicit exit phrase is what actually clears the sticky flag; a bare "normal"
# with no such phrase still restores layman, preserving the original "stay
# simplified without re-asking every message" intent.
_LAYMAN_EXIT_RE = re.compile(
    r'\b(back to normal|stop simplifying|exit (?:layman|simple) mode|'
    r'normal mode|regular mode|stop explaining simply)\b',
    re.I,
)


def _requests_layman_exit(message: str) -> bool:
    return bool(_LAYMAN_EXIT_RE.search(message))


# Document persistence: real minimal-excerpt size for the budget gate — one
# document_memory_service chunk (_CHUNK_CHARS=800) at the project's 4-chars/
# token heuristic. If less than this remains in the real prompt budget, a
# session document is marked unavailable rather than injected.
_MIN_EXCERPT_TOKENS = 200


def chat_stream(
    session_id:   str,
    message:      str,
    topic_hint:   str | None  = None,
    chat_mode:    str         = "normal",
    feed_context: dict | None = None,
    user_id:      str | None  = None,
    user_name:    str | None  = None,
    attachments:  list[dict] | None = None,
    is_test:      bool       = False,
    client_timezone: str | None = None,
):
    """
    Sync generator — yields NDJSON lines for a single conversational turn.

    Line types
    ----------
    {"t": "chunk",    "v": "<text>", "seq": int, "block_id": int}       — AI text arriving incrementally
    {"t": "thinking", "v": "<text>", "seq": int, "block_id": int}       — Gemini reasoning arriving incrementally (Chat-6)
    {"t": "thinking_gap", "v": "<text>"}   — one-shot note: reasoning ran but can't stream (Chat-6 followup)
    {"t": "status", "v": "<label>", "seq": int, "block_id": int, "tool": str, "query": str|None}  — tool_start (others below are plain {"t":"status","v":...}, no tool/seq/block_id)
    {"t": "status", "v": "<label>", "seq": int, "block_id": int, "tool": str, "sources": [...]}    — tool_end (Chat-R10e; same block_id as the tool_start status above)
    {"t": "code", "v": "<source>", "language": "python"}       — executed code (Chat-7)
    {"t": "code_output", "v": "<stdout>", "success": true}     — its execution result (Chat-7)
    {"t": "done",  <full metadata>}        — final metadata after stream ends
    {"t": "error", "message": "<reason>"}  — unrecoverable error; stream stops

    seq/block_id (Chat-R10d) let a consumer reconstruct the ordered
    thinking/tool_call/text blocks server-side already builds into the
    persisted `blocks` column (see get_history) — order is otherwise only
    implicit in arrival. tool/query/sources on the status events (Chat-R10e)
    let the frontend build the same tool_call block live, without waiting
    for reload. R5's gap-note events (thinking_gap/code_execution_gap) are
    exempt: one-shot, no ordering concept needed.

    Callers should iterate until exhaustion or until an "error" event is seen.
    """
    session_id = session_id.strip()
    message    = message.strip()
    if not session_id:
        yield json.dumps({"t": "error", "message": "session_id must not be empty"}) + "\n"
        return
    if not message and not attachments:
        yield json.dumps({"t": "error", "message": "message must not be empty"}) + "\n"
        return

    # Phase B1: one trace_id per turn, generated before either LLM call path
    # (router classify, agent turn) so both — and any tool calls the agent
    # makes — land in llm_call_log under the same group. Chat has no existing
    # per-turn identifier that predates the LLM calls (message_id is only
    # assigned after the stream finishes, see _save_message below), so this is
    # always a fresh id, never reused from anywhere else.
    trace_id = uuid4().hex

    # Chat-R6a: images stay on the existing Gemini vision/Files-API path
    # (has_attachments hard gate, Chat-5) — documents (pdf/docx/csv/text/code)
    # go through text extraction instead (document_memory_service) and are
    # injected as context, never as a build_messages "media" part. mime_type
    # startswith "image/" is the discriminator used everywhere in this stack
    # (main.py's ChatAttachment docstring, frontend ChatMessage.jsx).
    image_attachments    = [a for a in (attachments or []) if (a.get("mime_type") or "").startswith("image/")]
    document_attachments = [a for a in (attachments or []) if not (a.get("mime_type") or "").startswith("image/")]

    # ── Context preparation ───────────────────────────────────────────────────
    # auto_mode is resolved after the model call now (Chat-4.1): True only when
    # chat_mode was "normal" and the model chose to call a tool on its own.
    auto_mode = False

    try:
        # Feed context: enrich + override topic and mode before intent detection
        if feed_context:
            _enrich_feed_context(feed_context)
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
                from .chat_title_service import get_session_conversation_mode, set_session_conversation_mode
                if get_session_conversation_mode(session_id) == "layman":
                    if _requests_layman_exit(message):
                        # Real exit, not a stale default — clear the sticky flag so
                        # later plain turns in this session don't fall back into it.
                        set_session_conversation_mode(session_id, "normal")
                    else:
                        chat_mode = "layman"
            except Exception:
                pass
        elif chat_mode == "web_search":
            # An explicit tool-mode toggle is never ambiguous (unlike bare "normal")
            # — clear any stale layman stickiness now so a later plain message
            # doesn't silently fall back into it either.
            try:
                from .chat_title_service import set_session_conversation_mode
                set_session_conversation_mode(session_id, "normal")
            except Exception:
                pass

        # History load moved ahead of the router submission below (Phase W,
        # 2026-08-25 follow-up) — classify_message() now takes a slice of it
        # (see that submit call). Still a plain SQLite read, not an LLM call,
        # so this doesn't meaningfully cost the concurrency Chat-R4b set up
        # (the router's own LLM latency still overlaps every LLM-dependent
        # step below — detect_intent/inject_memory/domain_context/
        # action_router/detect_depth/build_messages).
        history       = _load_history_messages(session_id, limit=50)
        history_turns = len(history) // 2

        # Chat-R4b: submit the task-based router NOW — chat_mode is final as of
        # the block above, so the exact same gate the old call site used
        # ("normal" mode, no image attachment) can be evaluated here instead,
        # letting classify_message() run on a background thread concurrently
        # with the context-prep work below (detect_intent/inject_memory/
        # domain_context/action_router/detect_depth/build_messages). Joined at
        # the original call site further down. Still runs unconditionally for
        # every qualifying turn — only WHEN it runs moved, not WHETHER.
        router_future = None
        if chat_mode == "normal" and not image_attachments:
            from ..llm.chat_router import classify_message
            from .chat_prompt_service import MAX_HISTORY_TURNS
            _router_metadata = {
                "trace_id": trace_id, "surface": "chat", "is_test": is_test,
            }
            if user_id:
                _router_metadata["user_id"] = user_id
            # Phase W (2026-08-25 follow-up): the same recent-turns window
            # chat_turn itself is about to answer with (build_messages()
            # applies the identical MAX_HISTORY_TURNS slice) — real,
            # session-consistent context for the classifier's tool/query
            # judgment, not a context-blind guess. Confirmed previously
            # empty in both exactly_what_change_I_want.md and fuck_it.md.
            _router_history = history[-(MAX_HISTORY_TURNS * 2):]
            router_future = _ROUTER_EXECUTOR.submit(
                classify_message, message, _router_metadata, _router_history,
            )

        # Chat-4.1: regex mode auto-upgrade retired (the model decides via real
        # tools now, see resolve_tools_and_hint below); detect_intent() still
        # runs for format_intent/intent_profile, which drive response structure
        # independently of mode/retrieval routing.
        from .chat_intent_service import detect_intent as _detect_intent
        intent = _detect_intent(message)
        # format_intent drives response structure regardless of mode-switching
        _format_intent = intent.get("format_intent", "default")

        from .memory_injection_service import inject_memory as _inject
        context = _inject(session_id, topic_hint, user_id=user_id)

        # Inject format intent so system prompt can apply structural guidance
        context["format_intent"]   = _format_intent
        context["intent_profile"]  = intent.get("intent_profile", {})
        context["current_message"] = message
        # Chat identity pass: threaded through for _build_persona_section's
        # "use their name naturally" instruction — natural mode only reads this;
        # structured mode's persona (_PERSONA) never looks at it.
        context["user_name"]       = (user_name or "").strip()
        # Phase K: the browser's IANA timezone for this turn — the app's only
        # locale signal, and the one crisis_support_service resolves to a country
        # so a distressed user gets their own country's helplines instead of a US
        # default. Request-scoped and never persisted; validated by exact lookup
        # against pytz's zone table there, so an unrecognised value degrades to
        # "we don't know where you are" rather than reaching the prompt.
        context["client_timezone"]  = (client_timezone or "").strip()

        # Phase T: whether this turn genuinely carries attachment content —
        # this turn's own image/document upload, or a still-relevant document
        # from earlier in the session that document-reinjection (below) will
        # pull back in. chat_prompt_service only emits ATTACHMENT AWARENESS
        # when this is true — previously unconditional on every turn, image
        # or not (confirmed live: the section is real text weight on 100% of
        # turns for a feature most turns never use).
        context["has_attachment"] = bool(image_attachments) or bool(document_attachments)
        if not context["has_attachment"]:
            try:
                from .document_memory_service import list_session_documents as _list_docs, is_relevant as _doc_relevant
                context["has_attachment"] = any(
                    _doc_relevant(d["attachment_id"], message) for d in _list_docs(session_id)
                )
            except Exception:
                pass

        # Inject layman mode flag into context for system prompt
        if chat_mode == "layman":
            context["layman_mode_context"] = {
                "active":    True,
                "mechanism": (feed_context or {}).get("mechanism", ""),
            }

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
        context["response_depth"] = _detect_depth(message)

        # Phase 4.6: shared learning context (stream path)
        _pid_slc = (feed_context or {}).get("project_id", "") if feed_context else ""
        if _pid_slc:
            try:
                from .shared_learning_context import get_shared_prompt_block as _gslc
                _slc = _gslc(_pid_slc, mode=chat_mode)
                if _slc:
                    context["shared_learning_context"] = _slc
            except Exception:
                pass

        # Chat-3: semantic long-term memory recall (additive third layer,
        # alongside conversation_memory/knowledge_state) — hard-scoped to
        # user_id, never crosses users. Non-fatal on any error.
        if user_id:
            try:
                from .vector_memory_service import search as _vec_search, format_for_prompt as _vec_fmt
                _vec_hits = _vec_search(user_id, topic_hint or message)
                _vec_block = _vec_fmt(_vec_hits)
                if _vec_block:
                    context["vector_memory"] = _vec_block
            except Exception:
                logger.debug("[chat_service] vector_memory recall failed (non-fatal)")

        # Chat-3: Feed-entry persistent anchor — resolved from feed_chat_links,
        # independent of feed_context/shared_learning_context. Present on every
        # turn of a Feed-linked session, not just the first.
        try:
            from .feed_entry_anchor_service import get_anchor_for_session
            _anchor = get_anchor_for_session(session_id)
            if _anchor:
                context["feed_entry_anchor"] = _anchor
        except Exception:
            logger.debug("[chat_service] feed_entry_anchor failed (non-fatal)")

        # Chat-R7b: genuine Feed-context link, the sole signal for structured
        # JSON output (chat_prompt_service.build_system_prompt) — a union of
        # both signals, not either alone. feed_context is request-scoped and
        # only present on the turn right after a Feed-card action; the
        # feed_chat_links row backing feed_entry_anchor isn't created until
        # AFTER that first turn's response completes (ChatWorkspace.jsx
        # persists it in the onDone callback), so feed_entry_anchor is empty
        # on turn 1 of a Feed-linked session. feed_context covers turn 1;
        # feed_entry_anchor covers every turn after — together, no gap.
        context["feed_linked"] = bool(feed_context) or bool(context.get("feed_entry_anchor"))

        # Structured-mode fix (Task 1): real feed action + card title, only
        # present on the same turn feed_context itself is (see union comment
        # above) — learning_system_context_service uses these instead of
        # hardcoding mode="deep_research" when building its LEARNING SYSTEM
        # section, so the composer's own copy and the note this file used to
        # append separately can't disagree. On turns 2+ (feed_context absent,
        # feed_entry_anchor carries the link instead) these stay unset and
        # that section falls back to its generic depth-hierarchy framing.
        if feed_context:
            context["feed_action"] = feed_context.get("action", "ask_about")
            context["feed_topic"]  = feed_context.get("insight_title", "")

        # Phase U: join the router now, before build_messages() — the crisis
        # field decides whether CRISIS AND DISTRESS SUPPORT even goes into the
        # prompt, so build_messages() needs it up front, not after. Still
        # overlaps with everything submitted-to-here above (detect_intent/
        # inject_memory/domain_context/action_router/detect_depth/feed
        # context/vector_memory/feed_entry_anchor) — only the tail (document
        # reinjection, token-budget instrumentation) loses the overlap, and
        # latency is explicitly not a priority here (Phase W). Future.result()
        # is safe to call again later (idempotent) for the task_type/mode_hint
        # block further down, which reuses this same `decision`.
        decision = router_future.result() if router_future is not None else None

        # HARD CONSTRAINT (Phase U): a real, valid classification is required
        # to say "no crisis this turn". Anything else — both legs exhausted,
        # or the router never ran at all (web_search/layman mode, an image
        # attachment turn: none of those are a classify FAILURE, but none of
        # them produced a real answer either) — defaults to True at the code
        # level. This must never depend on the model successfully reasoning
        # its way to true.
        fresh_crisis = decision.crisis if decision is not None else True

        # Session persistence (Task 3): a crisis turn keeps the section alive
        # for the next few turns even if a follow-up ("fuck you", a topic
        # swerve) wouldn't independently classify as crisis on its own — see
        # chat_prompt_service._CRISIS_CONDUCT's AFTER A DISTRESS TURN section,
        # which exists specifically because that's the ordinary shape distress
        # comes back out in. Turn-count decay, not wall-clock: a long pause
        # mid-conversation shouldn't silently expire it, and a slow reply
        # shouldn't race it either.
        from .chat_title_service import get_session_crisis_expiry, set_session_crisis_expiry
        turn_number = history_turns + 1
        persisted_expiry = get_session_crisis_expiry(session_id)
        persisted_active = persisted_expiry is not None and turn_number <= persisted_expiry
        context["crisis_active"] = fresh_crisis or persisted_active
        if context["crisis_active"]:
            # _CRISIS_WINDOW_TURNS: generous on purpose — a false continue costs
            # a slightly warmer tone and one skipped structured-output turn; a
            # premature cutoff mid-distress is exactly the failure AFTER A
            # DISTRESS TURN exists to prevent. NOT permanent-for-session: that
            # would silently disable JSON/structured output (crisis_support
            # overrides format rules) for the rest of a long conversation over
            # one early turn. Refreshed every turn the window is live, so it
            # keeps rolling forward as long as it stays active.
            set_session_crisis_expiry(session_id, turn_number + _CRISIS_WINDOW_TURNS)

        from .chat_prompt_service import build_messages as _build
        messages_payload = _build(history, message, context, mode=chat_mode, attachments=image_attachments or None)

        # Inject feed context note first (background knowledge)
        #
        # Structured-mode fix (Task 1, was a KNOWN BUG): build_feed_context_note() used
        # to append its own second LEARNING SYSTEM-labeled note here, on top of the one
        # _build_structured_prompt's composer already adds — double injection. Fixed at
        # the source: context["feed_action"]/["feed_topic"] (set above) feed the
        # composer's own "learning_system" section the real action, and
        # build_feed_context_note() no longer appends a second copy.
        if feed_context:
            from .chat_modes_service import build_feed_context_note
            feed_note = build_feed_context_note(feed_context)
            messages_payload = _inject_mode_note(messages_payload, feed_note)

        # Chat-R6a: extracted document text, injected as context — never as a
        # build_messages "media" part (that path is Gemini-vision-only, images
        # only). Retrieval-trimmed automatically by document_memory_service
        # when a document's full text exceeds its token budget.
        _turn_attachment_ids: set[str] = set()
        for doc in document_attachments:
            attachment_id = (doc.get("uri") or "").removeprefix("doc://")
            if not attachment_id:
                continue
            _turn_attachment_ids.add(attachment_id)
            from .document_memory_service import get_context as _doc_context
            doc_note = _doc_context(attachment_id, doc.get("filename") or "document", message or topic_hint or "")
            messages_payload = _inject_mode_note(messages_payload, doc_note)

        # Document persistence: reinject documents attached on EARLIER turns of
        # this session (not this turn's own attachments, handled above), gated
        # on genuine relevance to the current message so an unrelated later
        # question doesn't silently drag in a document from three turns ago.
        # unavailable_documents (real, code-level signal — see the "done" event
        # below) covers the two things that can stop a genuinely relevant
        # document from being included: no room left in the real prompt budget,
        # or its chunks are missing. Never relies on the model to mention this.
        unavailable_documents: list[dict] = []
        try:
            from .document_memory_service import (
                list_session_documents as _list_session_docs,
                is_relevant as _doc_is_relevant,
                get_context as _doc_context2,
            )
            from .token_budget import estimate_messages as _estimate_messages
            from .model_registry import get_model_config as _get_model_cfg
            from ..config import GEMINI_MODEL as _budget_model

            _session_docs = _list_session_docs(session_id)
            if _session_docs:
                _budget_cfg = _get_model_cfg(_budget_model)
                for _doc in _session_docs:
                    _aid, _fname = _doc["attachment_id"], _doc["filename"]
                    if _aid in _turn_attachment_ids:
                        continue  # already injected above via this turn's own attachments
                    if not _doc_is_relevant(_aid, message):
                        continue  # not relevant to this message — correctly not reinjected

                    # Real budget gate: room left for even one minimal chunk-sized
                    # excerpt (_MIN_EXCERPT_TOKENS ~= document_memory_service's own
                    # _CHUNK_CHARS at the project's 4-chars/token heuristic)?
                    _remaining = _budget_cfg.prompt_budget - _estimate_messages(messages_payload)
                    if _remaining < _MIN_EXCERPT_TOKENS:
                        unavailable_documents.append({
                            "attachment_id": _aid, "filename": _fname, "reason": "budget",
                        })
                        continue

                    _note = _doc_context2(_aid, _fname, message)
                    if "no extracted content found" in _note or "content temporarily unavailable" in _note:
                        unavailable_documents.append({
                            "attachment_id": _aid, "filename": _fname, "reason": "missing",
                        })
                        continue

                    messages_payload = _inject_mode_note(messages_payload, _note)
        except Exception:
            logger.debug("[chat_service] session document reinjection failed (non-fatal)", exc_info=True)

    except Exception:
        logger.exception("chat_stream: context preparation failed")
        yield json.dumps({"t": "error", "message": "Failed to prepare context"}) + "\n"
        return

    # ── Tool policy (Chat-4.1) ────────────────────────────────────────────────
    # Retired backend pre-fetch (prepare_mode_context/stream_research_progress,
    # still used unchanged by the sync chat() path above). chat_mode now only
    # decides tool availability + an optional bias hint — web_search is a real
    # tool the model calls itself; layman gets tools=None structurally.
    from ..llm.chat_agent import resolve_tools_and_hint, build_mode_hint
    tools_enabled, mode_hint = resolve_tools_and_hint(chat_mode)

    # ── Chat-R4: task-based router ────────────────────────────────────────────
    # Only for "normal" mode (no explicit web_search toggle) and
    # never for IMAGE attachment turns — an explicit toggle always wins outright
    # (R1: 10/10 hit rate), and the vision hard gate (Chat-5) is untouched by
    # task-based routing. Document-only turns route normally (Chat-R6a) — a
    # document isn't a structural gate the way an image is. Non-fatal:
    # classify_message returns None on any failure, leaving task_type=None
    # (today's default fixed chain, no hint).
    # Chat-R4b/Phase U: classify_message() itself already ran and was already
    # joined (right before build_messages() above, so the crisis field could
    # gate the prompt) — `decision` is that same result, reused here for
    # routing. Still gated to "normal" mode only: decision is real for every
    # mode now (crisis needs it everywhere), but an explicit web_search/layman
    # toggle must keep winning outright regardless of what routing fields it
    # carries (R1: 10/10 explicit-toggle hit rate) — unchanged from before.
    task_type = None
    # Phase M: the router already computes RoutingDecision.complexity on every
    # message, but map_to_task_type() below never consults it on a tool-using
    # turn (needs_tool wins first and returns "tool_use"), so on exactly the
    # web_search turns this phase cares about the signal was computed and then
    # discarded. Captured here and forwarded on the agent call metadata so
    # chat_tools.web_search can size that turn's source count with it. Stays
    # None whenever the router failed — the fixed 3+3 fallback.
    router_complexity: str | None = None
    if chat_mode == "normal" and decision is not None:
        from ..llm.chat_router import map_to_task_type
        task_type = map_to_task_type(decision)
        router_complexity = decision.complexity
        if decision.needs_tool:
            mode_hint = build_mode_hint(decision.tool_name, decision.shaped_query)

    if mode_hint:
        messages_payload = _inject_mode_note(messages_payload, mode_hint)

    is_new_session = len(history) == 0

    # ── Inject title extraction note for new sessions ─────────────────────────
    if is_new_session:
        from .chat_title_service import make_title_system_note
        messages_payload = _inject_mode_note(messages_payload, make_title_system_note())

    # ── Token budget instrumentation (diagnostics only, non-fatal) ───────────
    try:
        from .token_budget import estimate_tokens, estimate_messages, BudgetReport, log_budget_report
        from .model_registry import get_model_config
        from ..config import GEMINI_MODEL as _MODEL_CS
        _cfg_cs   = get_model_config(_MODEL_CS)
        _sys_cs   = sum(estimate_tokens(m.get("content","")) for m in messages_payload if m.get("role") == "system")
        _hist_cs  = sum(estimate_tokens(m.get("content","")) for m in messages_payload[:-1] if m.get("role") in ("user","assistant"))
        _cur_cs   = estimate_tokens(messages_payload[-1].get("content","")) if messages_payload else 0
        _total_cs = estimate_messages(messages_payload)
        _remain_cs = _cfg_cs.prompt_budget - _total_cs
        log_budget_report(BudgetReport(
            operation        = "chat/stream",
            model_name       = _MODEL_CS,
            context_window   = _cfg_cs.context_window,
            safe_budget      = _cfg_cs.prompt_budget,
            output_reserve   = _cfg_cs.output_budget,
            prompt_tokens    = _total_cs,
            remaining_budget = _remain_cs,
            utilization_pct  = (_total_cs / _cfg_cs.prompt_budget * 100) if _cfg_cs.prompt_budget > 0 else 0.0,
            sections         = {
                "system_prompt":   _sys_cs,
                "history":         _hist_cs,
                "current_message": _cur_cs,
            },
            warnings = [
                f"OVER SAFE BUDGET: {_total_cs:,} > {_cfg_cs.prompt_budget:,}"
            ] if _remain_cs < 0 else [],
        ), logger)
    except Exception:
        logger.debug("[chat_service] stream budget instrumentation failed (non-fatal)", exc_info=True)

    # ── Stream AI response ────────────────────────────────────────────────────
    # Keep the frontend loading indicator quiet until the model emits a
    # meaningful step or the first answer chunk. The generic filler is now
    # omitted for the default path to avoid redundant dots + text.
    from .chat_title_service import stream_extract_state, advance_stream_state
    title_state     = stream_extract_state() if is_new_session else None
    collected:       list[str]  = []
    thinking_chunks: list[str]  = []
    extracted_title: str | None = None
    sources:         list[dict] = []
    tool_used:       str | None = None
    _TOOL_STATUS_LABELS = {
        "web_search":    "Searching the web…",
    }

    # Chat-R10d: ordered {type: "thinking"|"tool_call"|"text", ...} segments,
    # built alongside (not instead of) the flat thinking_chunks/collected
    # accumulators above — thinking_chunks still becomes the `thinking`
    # column exactly as before. `blocks` folds chat_agent's block_id-tagged
    # events into one entry per contiguous run: a tool_start/tool_end pair
    # for the same call shares a block_id (see chat_agent._stream_agent),
    # so this dict lookup — not positional "last entry" — is what lets
    # tool_end's sources land back on the same entry tool_start opened.
    blocks:       list[dict]   = []
    _block_index: dict[int, int] = {}

    def _block_entry(block_id, factory):
        if block_id in _block_index:
            return blocks[_block_index[block_id]]
        _block_index[block_id] = len(blocks)
        entry = factory()
        blocks.append(entry)
        return entry

    try:
        from ..llm.chat_agent import ask_chat_stream
        _call_metadata: dict = {
            "call_type": "chat_turn",
            "trace_id": trace_id, "surface": "chat", "is_test": is_test,
        }
        if user_id:
            _call_metadata["user_id"] = user_id
        # Phase M — read by chat_tools.web_search via _tool_meta(config).
        # Only set when the router actually produced a decision; absent means
        # "unknown", which web_search_reasoning_service maps to today's 3+3.
        if router_complexity:
            _call_metadata["complexity"] = router_complexity
        for event in ask_chat_stream(
            messages_payload, metadata=_call_metadata, tools_enabled=tools_enabled,
            has_attachments=bool(image_attachments),
            task_type=task_type,
        ):
            if event["type"] == "status":
                yield json.dumps({"t": "status", "v": event.get("text") or "Working…"}) + "\n"
                continue
            if event["type"] == "tool_start":
                label = event.get("status_text") or _TOOL_STATUS_LABELS.get(event["tool"], f"Running {event['tool']}…")
                # Chat-R10e: tool/query on the wire (additive fields on the
                # existing "status" type, no new NDJSON type) — R10d's
                # seq/block_id alone don't give the frontend enough to render
                # a live tool_call block; the persisted blocks column already
                # had tool/query, this just also puts it on the stream.
                yield json.dumps({
                    "t": "status", "v": label,
                    "seq": event.get("seq"), "block_id": event.get("block_id"),
                    "tool": event["tool"], "query": event.get("query"),
                }) + "\n"
                _block_entry(event["block_id"], lambda: {
                    "type": "tool_call", "tool": event["tool"],
                    "query": event.get("query"), "sources": [],
                })
                continue
            if event["type"] == "tool_end":
                tool_used = event["tool"]
                sources.extend(event.get("sources", []))
                entry = _block_entry(event["block_id"], lambda: {
                    "type": "tool_call", "tool": event["tool"],
                    "query": None, "sources": [],
                })
                entry["sources"] = event.get("sources", [])
                # Chat-R10e: second "status" emission (same type, same block_id)
                # for the wire — no tool_end signal existed on the wire before
                # this; carries sources so the live tool_call block can fill in
                # without waiting for reload.
                yield json.dumps({
                    "t": "status", "v": event.get("status_text") or _TOOL_STATUS_LABELS.get(event["tool"], f"Running {event['tool']}…"),
                    "seq": event.get("seq"), "block_id": event.get("block_id"),
                    "tool": event["tool"], "sources": event.get("sources", []),
                }) + "\n"
                if entry.get("tool") is None:
                    entry["tool"] = event["tool"]
                continue
            if event["type"] == "thinking":
                # Bypasses title extraction — that parser only ever needs to see
                # visible answer text (see ask_chat_stream's module docstring).
                thinking_chunks.append(event["text"])
                entry = _block_entry(event["block_id"], lambda: {"type": "thinking", "text": ""})
                entry["text"] += event["text"]
                yield json.dumps({
                    "t": "thinking", "v": event["text"],
                    "seq": event.get("seq"), "block_id": event.get("block_id"),
                }) + "\n"
                continue
            if event["type"] == "thinking_gap":
                # One-shot honest note when the Gemini 3+ leg answers — see
                # chat_agent._THINKING_GAP_TEXT for why thinking never arrives here.
                yield json.dumps({"t": "thinking_gap", "v": event["text"]}) + "\n"
                continue
            if event["type"] == "code_execution_gap":
                # Chat-R5b: one-shot note when task_type=="coding" but the leg
                # answering isn't Gemini 3+ (code_execution unavailable there).
                yield json.dumps({"t": "code_execution_gap", "v": event["text"]}) + "\n"
                continue
            if event["type"] == "code":
                # Bypasses title extraction and collected/response_text, same as
                # thinking — this is the model's executed source, not its answer.
                yield json.dumps({"t": "code", "v": event["text"], "language": event.get("language", "python")}) + "\n"
                continue
            if event["type"] == "code_output":
                yield json.dumps({"t": "code_output", "v": event["text"], "success": event.get("success", True)}) + "\n"
                continue

            chunk = event["text"]
            if title_state is not None:
                result = advance_stream_state(title_state, chunk)
                if result["title"] and not extracted_title:
                    extracted_title = result["title"]
                    yield json.dumps({"t": "title", "v": extracted_title}) + "\n"
                if result["forward"] is not None:
                    collected.append(result["forward"])
                    entry = _block_entry(event["block_id"], lambda: {"type": "text", "text": ""})
                    entry["text"] += result["forward"]
                    yield json.dumps({
                        "t": "chunk", "v": result["forward"],
                        "seq": event.get("seq"), "block_id": event.get("block_id"),
                    }) + "\n"
            else:
                collected.append(chunk)
                entry = _block_entry(event["block_id"], lambda: {"type": "text", "text": ""})
                entry["text"] += chunk
                yield json.dumps({
                    "t": "chunk", "v": chunk,
                    "seq": event.get("seq"), "block_id": event.get("block_id"),
                }) + "\n"
    except Exception as exc:
        logger.exception("chat_stream: AI generation failed")
        yield json.dumps({"t": "error", "message": str(exc)}) + "\n"
        return

    response_text = "".join(collected)
    thinking_text = "".join(thinking_chunks) or None
    blocks_data   = blocks or None

    try:
        from .tension_engine import score_tension as _score_tension
        tension_scores = _score_tension(response_text)
    except Exception:
        tension_scores = {}

    # Chat-4.1: sources/chat_mode/auto_mode reflect which tool the model
    # actually called this turn, not which mode was pre-selected.
    resolved_mode = tool_used or chat_mode
    auto_mode     = (chat_mode == "normal") and (tool_used is not None)

    # ── Persist messages ──────────────────────────────────────────────────────
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    user_msg_id = 0
    try:
        user_msg_id = _save_message(session_id, "user",      message,       topic_hint, now, attachments=attachments)
        msg_id      = _save_message(session_id, "assistant", response_text, topic_hint, now, thinking=thinking_text, blocks=blocks_data)
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

    # Update conversation knowledge state (non-blocking; enables compound reasoning)
    try:
        from .conversation_state_service import update_state as _update_ks, get_state as _get_ks
        _update_ks(
            session_id          = session_id,
            user_message        = message,
            response_text       = response_text,
            topic_hint          = topic_hint,
            structured_response = _parse_structured_response(response_text),
            domain              = context.get("domain_context", {}).get("domain"),
        )
        # Chat-3: embed the just-updated state for semantic recall — same
        # trigger point conversation_knowledge_state itself updates on.
        if user_id:
            try:
                from .vector_memory_service import record_entry as _vec_record
                _vec_record(user_id, session_id, _get_ks(session_id))
            except Exception:
                logger.debug("[chat_stream] vector_memory record failed (non-fatal)")
    except Exception:
        logger.exception("chat_stream: knowledge state update failed (non-fatal)")

    # Enrich recommendations with thread-aware, category-specific follow-ups
    try:
        from .conversation_state_service import get_state as _get_ks, enrich_with_thread_followups
        recommendations = enrich_with_thread_followups(
            recommendations,
            _get_ks(session_id),
            intent_profile = context.get("intent_profile", {}),
            domain         = context.get("domain_context", {}).get("domain", ""),
        )
    except Exception:
        pass

    yield json.dumps({
        "t":                   "done",
        "message_id":          msg_id,
        "user_message_id":     user_msg_id,
        "topic_hint":          topic_hint,
        "title":               extracted_title,
        "sources":             sources,
        "chat_mode":           resolved_mode,
        "auto_mode":           auto_mode,
        "action":              action_result.get("action") if action_result else None,
        "recommendations":     recommendations,
        "structured_response": _parse_structured_response(response_text),
        "tension_scores":      tension_scores,
        # Document persistence: real, deterministic signal for a session
        # document that was genuinely relevant to this message but couldn't be
        # reinjected (budget or missing chunks) — the frontend can render this
        # directly instead of relying on the model to mention it (the existing
        # "no extracted content found" in-context note is model-relayed only;
        # this is the code-level counterpart for this specific mechanism).
        "unavailable_documents": unavailable_documents,
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

    Each entry: {id, session_id, role, content, topic_hint, created_at, attachments, thinking, blocks}
    `attachments` is the raw stored list (uri/mime_type/filename/size_bytes/expires_at)
    — the frontend decides how to render an expired one, this layer doesn't filter it.
    `blocks` (Chat-R10d) is the ordered thinking/tool_call/text segment list,
    coexisting with the flat `thinking` string — both come from the same turn.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, session_id, role, content, topic_hint, created_at, attachments, thinking, blocks
            FROM   chat_messages
            WHERE  session_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT  ?
            """,
            (session_id, limit),
        ).fetchall()

    return [
        {
            "id":          r["id"],
            "session_id":  r["session_id"],
            "role":        r["role"],
            "content":     r["content"],
            "topic_hint":  r["topic_hint"],
            "created_at":  r["created_at"],
            "attachments": json.loads(r["attachments"]) if r["attachments"] else None,
            "thinking":    r["thinking"],
            "blocks":      json.loads(r["blocks"]) if r["blocks"] else None,
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
    - Truncated JSON (stream interrupted mid-object) — attempts structural repair

    Returns the parsed dict if it contains a 'response_type' key, else None.
    """
    import re as _re

    cleaned = text.strip()
    # Strip markdown fences
    cleaned = _re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = _re.sub(r"\s*```\s*$", "", cleaned).strip()

    def _valid(d: dict) -> bool:
        return isinstance(d, dict) and "response_type" in d

    def _repair_truncated(s: str) -> str:
        """
        Close unclosed JSON structures caused by stream truncation.

        Uses a stack to determine correct closing order for nested objects/arrays,
        handling the case where a truncated string ends mid-string-value.
        """
        # Pass 1: detect and close open string
        in_str = False
        esc = False
        for ch in s:
            if esc:
                esc = False
                continue
            if ch == '\\':
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
        if in_str:
            s = s + '"'

        # Pass 2: build closing sequence via stack
        stack: list[str] = []
        in_str = False
        esc = False
        for ch in s:
            if esc:
                esc = False
                continue
            if ch == '\\':
                esc = True
                continue
            if in_str:
                if ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == '{':
                stack.append('}')
            elif ch == '[':
                stack.append(']')
            elif ch in ('}', ']'):
                if stack and stack[-1] == ch:
                    stack.pop()

        return s + ''.join(reversed(stack))

    try:
        data = json.loads(cleaned)
        if _valid(data):
            return data
    except (json.JSONDecodeError, ValueError):
        pass

    # Try repairing truncated JSON before giving up
    try:
        repaired = _repair_truncated(cleaned)
        if repaired != cleaned:
            data = json.loads(repaired)
            if _valid(data):
                return data
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: find first {...} block spanning the whole string
    match = _re.search(r"\{.*\}", cleaned, _re.DOTALL)
    if match:
        candidate = match.group()
        try:
            data = json.loads(candidate)
            if _valid(data):
                return data
        except (json.JSONDecodeError, ValueError):
            pass
        # Try repairing the extracted block too
        try:
            repaired = _repair_truncated(candidate)
            data = json.loads(repaired)
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
    attachments: list[dict] | None = None,
    thinking: str | None = None,
    blocks: list[dict] | None = None,
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO chat_messages (session_id, role, content, topic_hint, created_at, attachments, thinking, blocks) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, role, content, topic_hint, created_at,
             json.dumps(attachments) if attachments else None, thinking,
             json.dumps(blocks) if blocks else None),
        )
        msg_id = cur.lastrowid
        # Chat-R15c: permanent attachment_id -> session_id record for document
        # (doc://) attachments — the ONLY point this co-occurs with attachments,
        # and it must be written here (not derived later from the attachments
        # JSON), since sweep_expired_attachments drops that JSON entry once the
        # original file expires. See CREATE_DOCUMENT_ATTACHMENT_SESSIONS.
        for attachment in (attachments or []):
            uri = attachment.get("uri") or ""
            if uri.startswith("doc://"):
                conn.execute(
                    "INSERT OR IGNORE INTO document_attachment_sessions (attachment_id, session_id) VALUES (?, ?)",
                    (uri.split("://", 1)[1], session_id),
                )
        return msg_id


def _load_history_messages(session_id: str, limit: int = 50) -> list[dict]:
    """
    Return up to *limit* messages as OpenAI-format dicts (role + content).

    A message with live (non-expired) IMAGE attachments gets a list-of-parts
    content (text + Gemini "media" file_uri parts) instead of a plain string,
    so the model can still see an image attached on an earlier turn. Expired
    attachments are silently dropped — the file_uri is dead on Google's side
    (verified live: cross-key access already 403s, and Google deletes the file
    server-side after 48h), so re-sending it would just fail the whole turn.

    Chat-R6a: document attachments (pdf/docx/csv/text/code) are excluded here
    regardless of expires_at — their "doc://<id>" uri is never a real Gemini
    file_uri, and expires_at is always None for them (our own storage doesn't
    expire), which would otherwise make _attachment_is_live() treat them as
    permanently "live" and re-send a broken media part on every future turn.
    Their extracted text was already injected as context on the turn it was
    uploaded (chat_stream's document_attachments block) — it doesn't need to
    be re-injected on every subsequent turn of the same session.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT role, content, attachments
            FROM   chat_messages
            WHERE  session_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT  ?
            """,
            (session_id, limit),
        ).fetchall()

    now = datetime.now(timezone.utc)
    messages = []
    for r in reversed(rows):
        attachments = json.loads(r["attachments"]) if r["attachments"] else None
        live = [
            a for a in attachments
            if (a.get("mime_type") or "").startswith("image/") and _attachment_is_live(a, now)
        ] if attachments else []
        if not live:
            messages.append({"role": r["role"], "content": r["content"]})
            continue
        parts = [{"type": "text", "text": r["content"]}] if r["content"] else []
        parts += [{"type": "media", "file_uri": a["uri"], "mime_type": a["mime_type"]} for a in live]
        messages.append({"role": r["role"], "content": parts})
    return messages


def _past_expiry(expires_at: str | None, now: datetime) -> bool:
    """True if expires_at is set and has passed. None/unparseable -> not expired (permanent)."""
    if not expires_at:
        return False
    try:
        return datetime.fromisoformat(expires_at.replace("Z", "+00:00")) <= now
    except ValueError:
        return False


def _attachment_is_live(attachment: dict, now: datetime) -> bool:
    return not _past_expiry(attachment.get("expires_at"), now)


def _r2_key_for(attachment_id: str, filename: str | None) -> str:
    ext = PurePosixPath(filename or "").suffix.lower()
    return f"chat-attachments/{attachment_id}{ext}"


def get_document_owner_session(attachment_id: str) -> str | None:
    """
    Chat-R15c: permanent session_id for a document (doc://) attachment_id, or
    None if it was never persisted to a message (upload-only, orphaned) or
    predates this record (written by _save_message going forward).

    Deliberately NOT attachment_belongs_to_session's JSON-liveness scan —
    that table (chat_messages.attachments) is pruned once the original file
    is swept, which would incorrectly 404 the OWNER's permanent access to
    their own extracted text. This table is never touched by sweep.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT session_id FROM document_attachment_sessions WHERE attachment_id = ?",
            (attachment_id,),
        ).fetchone()
    return row["session_id"] if row else None


def attachment_belongs_to_session(session_id: str, attachment_id: str) -> bool:
    """
    Chat-R15a ownership check: True if attachment_id genuinely appears
    somewhere in session_id's own messages. Needed so share-scoped attachment
    access can't become a skeleton key (any valid token + any attachment_id).

    Reuses sweep_expired_attachments's exact id-extraction shape: doc://<id>
    and file://<id> from uri (documents/"other" files), r2_attachment_id
    (Chat-R14a image dual-write) — the same three places a real attachment_id
    can live.
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT attachments FROM chat_messages "
            "WHERE session_id = ? AND attachments IS NOT NULL AND attachments != ''",
            (session_id,),
        ).fetchall()

    for row in rows:
        for attachment in json.loads(row["attachments"]):
            uri = attachment.get("uri") or ""
            if uri.startswith(("doc://", "file://")) and uri.split("://", 1)[1] == attachment_id:
                return True
            if attachment.get("r2_attachment_id") == attachment_id:
                return True
    return False


def list_session_attachments(session_id: str) -> list[dict]:
    """
    Chat-R16 files panel: every attachment across every message in
    session_id, most-recent first, unbounded (no LIMIT) — unlike get_history,
    which caps at `limit` messages. Reuses attachment_belongs_to_session's
    scan shape (same WHERE clause) but returns the full attachment dicts
    instead of a boolean membership check.

    Each entry is the raw stored attachment dict plus `created_at` (its
    owning message's timestamp), so a panel can render/sort without a
    second per-message lookup.
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT attachments, created_at FROM chat_messages "
            "WHERE session_id = ? AND attachments IS NOT NULL AND attachments != '' "
            "ORDER BY created_at DESC, id DESC",
            (session_id,),
        ).fetchall()

    result: list[dict] = []
    for row in rows:
        for attachment in json.loads(row["attachments"]):
            result.append({**attachment, "created_at": row["created_at"]})
    return result


def sweep_expired_attachments() -> dict:
    """
    Chat-R13/R14a admin cleanup: delete the R2 object backing every R2-backed
    attachment whose retention window has passed, and update
    chat_messages.attachments accordingly. Two disposal shapes, by type:

    - Documents (doc://<id>) and "other" files (file://<id>, Chat-R14a):
      expires_at IS the R2-only clock here. Once past it, the R2 object is
      deleted and the whole attachment entry is dropped — nothing else
      references it.
    - Images (Chat-R14a dual-write): r2_attachment_id/r2_expires_at are a
      SEPARATE clock from uri/expires_at (which stay Gemini's own real 48h
      expiry, checked elsewhere by _attachment_is_live/_load_history_messages
      — see ChatAttachment's docstring for why they can't be reused). Once
      r2_expires_at has passed, only the R2 object + those two fields are
      cleared — the rest of the entry (Gemini uri, its own expires_at,
      filename, mime_type) is kept, since it's independently meaningful
      regardless of R2 state (e.g. the frontend's "expired" chip badge).

    Extracted text/embeddings (document_chunks_vec, document_memory_service.py)
    are never written to here — permanent regardless of original-file retention.

    A failed R2 delete is reported in "errors" and the reference is left in
    place (not lost) — retried on the next sweep. Returns
    {"swept": int, "attachment_ids": list[str], "errors": list[dict]}.
    """
    now = datetime.now(timezone.utc)
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, attachments FROM chat_messages WHERE attachments IS NOT NULL AND attachments != ''"
        ).fetchall()

    swept_ids: list[str] = []
    errors: list[dict] = []

    for row in rows:
        attachments = json.loads(row["attachments"])
        if not attachments:
            continue

        kept = []
        row_changed = False
        for attachment in attachments:
            uri = attachment.get("uri") or ""
            is_r2_original = uri.startswith("doc://") or uri.startswith("file://")

            if is_r2_original and _past_expiry(attachment.get("expires_at"), now):
                attachment_id = uri.split("://", 1)[1]
                key = _r2_key_for(attachment_id, attachment.get("filename"))
                try:
                    r2_storage_service.delete(key)
                    swept_ids.append(attachment_id)
                    row_changed = True
                    continue  # drop the whole entry
                except Exception as exc:
                    logger.error("[chat] sweep: R2 delete failed for key=%r: %s", key, exc)
                    errors.append({"attachment_id": attachment_id, "key": key, "error": str(exc)})
                    kept.append(attachment)
                    continue

            r2_attachment_id = attachment.get("r2_attachment_id")
            if r2_attachment_id and _past_expiry(attachment.get("r2_expires_at"), now):
                key = _r2_key_for(r2_attachment_id, attachment.get("filename"))
                try:
                    r2_storage_service.delete(key)
                    swept_ids.append(r2_attachment_id)
                    row_changed = True
                    attachment = {**attachment, "r2_attachment_id": None, "r2_expires_at": None}
                except Exception as exc:
                    logger.error("[chat] sweep: R2 delete failed for key=%r: %s", key, exc)
                    errors.append({"attachment_id": r2_attachment_id, "key": key, "error": str(exc)})

            kept.append(attachment)

        if row_changed:
            with get_connection() as conn:
                conn.execute(
                    "UPDATE chat_messages SET attachments = ? WHERE id = ?",
                    (json.dumps(kept), row["id"]),
                )

    return {"swept": len(swept_ids), "attachment_ids": swept_ids, "errors": errors}


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


def _enrich_feed_context(feed_context: dict) -> None:
    """
    Enrich feed_context in-place with mechanism extract + project learning state.

    Adds:
      mechanism          — first sentence of why_it_matters (or summary)
      progression_stage  — current learning stage from project memory
      recent_mechanisms  — last 3 mechanisms covered in this project
      difficulty_level   — project difficulty setting

    All keys are only set if not already present.  Non-fatal — errors silently ignored.
    """
    try:
        # Extract mechanism from why_it_matters; fall back to summary
        why  = (feed_context.get("why_it_matters")    or "").strip()
        summ = (feed_context.get("insight_summary")   or "").strip()
        mechanism = (why or summ).split(".")[0].strip()
        if mechanism:
            feed_context.setdefault("mechanism", mechanism)

        # Load project learning state when project_id is available
        project_id = feed_context.get("project_id", "")
        if project_id:
            from .learning_memory_service import get_memory as _get_mem  # noqa: PLC0415
            memory = _get_mem(project_id)
            feed_context.setdefault("progression_stage",  memory.get("progression_stage", "foundation"))
            feed_context.setdefault("recent_mechanisms",  memory.get("covered_mechanisms", [])[-3:])
    except Exception:
        logger.debug("[chat_service] _enrich_feed_context failed (non-fatal)")
