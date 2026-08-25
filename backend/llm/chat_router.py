"""
Chat-R4 — LLM-based turn router: classifies one chat message into a task_type
(model_priority.py) so chat_agent.py can pick a model-priority chain suited to
the turn, plus a tool bias for chat_agent.build_mode_hint's shaped_query.

Runs ONLY when chat_mode == "normal" (chat_service.chat_stream) — an explicit
web_search toggle always wins outright, matching R1's proven 10/10
explicit-toggle hit rate; the router targets the "normal"-mode gap R1
measured at 2/10. Never consulted for attachment turns (vision hard gate,
Chat-5) — chat_service checks has_attachments before calling this at all.

Classification is non-fatal: any failure (both attempted legs exhausted)
returns None, and the caller keeps today's default behavior (task_type=None,
no hint) — an unavailable router must never break a chat turn. Confirmed
against chat_service.py: when classify_message() returns None, mode_hint
stays whatever resolve_tools_and_hint(chat_mode) already set before the
router ran ("normal" mode -> None, no hint at all) — there is no fallback
anywhere that echoes the raw user message as a search query. tools stay
bound either way, so the model can still call web_search itself, just
without the router's bias/rephrasing.

Phase W — real success validation
----------------------------------
Confirmed live (real llm_call_log rows, real re-invocation): the classifier's
primary leg (nemotron-3-nano, OpenRouter — model_priority.py's documented
choice for this role) regularly completes at the raw-HTTP level but doesn't
emit a valid tool-call for RoutingDecision — either empty content (a real,
separate LangChain structured-output shape, not a failure by itself) or
literal garbled text ("<tool_call>", a truncated/malformed attempt, or a full
JSON blob dumped into .content instead of a proper tool call). Because
with_structured_output(..., include_raw=False) (the old default) returns
`None` from .invoke() on this failure rather than raising, .with_fallbacks()
never sees it as a failure and never tries the next leg — confirmed live:
exactly one llm_call_log row per such call, always success=1 (accurately —
the raw completion DID succeed), regardless of whether a usable
RoutingDecision came out of it. A live 10-call probe on 2026-08-25 measured
5/10 (50%) of calls landing on this failure mode with the un-fixed code.

get_structured_chat_model_legs_for_task's include_raw=True surfaces this
directly ({"raw", "parsed", "parsing_error"}) so classify_message() below can
tell real success from this failure mode and react to it — retrying once on
the classifier's second DISTINCT model (deduplicated by (provider,
model_name) in get_structured_chat_model_legs_for_task — OPENROUTER_API_KEY
is actually a 2-key pool, so the raw leg list has nemotron twice before the
next model; retrying the same model on a different key does nothing for a
structural/generation-shape failure) before giving up. A genuine structural
failure additionally gets its own explicit llm_call_log row (write_call_row,
success=False, error_type="StructuredOutputInvalid") — same call_type so
existing success-rate queries now reflect it, without touching the original
raw-completion row (which stays a true, separate record of what the model
actually returned).

Phase U — crisis field
-----------------------
RoutingDecision now also carries `crisis: bool`, computed by the same call
(no second LLM round-trip). This is the classification input to
chat_service.py's conditional CRISIS AND DISTRESS SUPPORT injection — but
classify_message() itself makes no safety promise beyond "a real, valid
answer, if we got one": the code-level fail-safe (any leg exhaustion here
returns None; the caller treats None as crisis=True unconditionally) lives
in chat_service.py, not here, because this module has no way to know
whether a None came from a real crisis message or a benign one that
happened to hit a bad completion — and it must not guess.

Public API
----------
classify_message(message, metadata=None) -> RoutingDecision | None
map_to_task_type(decision) -> str
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationError

from .call_logger import write_call_row
from .model_provider import extract_text, get_structured_chat_model_legs_for_task

logger = logging.getLogger(__name__)

_TASK_TYPE = "routing"

_SYSTEM_PROMPT = (
    "Classify this chat message for routing purposes. Decide whether it needs "
    "a live-data tool, how complex the answer is, whether it requires writing "
    "AND executing code (not just explaining code), whether it signals a real "
    "crisis, and — if a tool is needed — a clean, search-ready rephrasing of "
    "the request.\n\n"
    "crisis: true if the message signals the person is thinking about suicide, "
    "self-harm, or not wanting to be alive — recognize it however it's phrased: "
    "plainly, sideways, hypothetically, bitterly, as a threat, as a joke, or as "
    "leverage in an argument they're losing. You cannot always tell whether "
    "they mean it — treat it as real regardless. False for everything else, "
    "including ordinary frustration, dark humor with nothing behind it, or a "
    "message that discusses crisis/mental health as a topic rather than as a "
    "personal signal."
)


class RoutingDecision(BaseModel):
    needs_tool: bool = Field(description="True if answering requires live web data or deep multi-source research")
    tool_name: Literal["web_search", "none"] = Field(description="Which tool to bias toward, or 'none'")
    complexity: Literal["simple", "complex"] = Field(description="'simple' = direct factual/conversational answer; 'complex' = multi-step reasoning or synthesis")
    requires_code_execution: bool = Field(description="True only if the answer requires actually running code, not just writing/explaining it")
    shaped_query: str = Field(description="Clean, search-engine-ready rephrasing of the message; empty string if needs_tool is False")
    crisis: bool = Field(description="True if the message signals real personal distress (suicide, self-harm, not wanting to be alive), however it's phrased. False otherwise, including academic/topical discussion of the subject.")


_classifier_legs: list | None = None

# RoutingDecision is 5 short fields (2 bools, 2 short literals, one short
# search phrase) — a real answer is under 100 tokens. Provider defaults for
# this pool are otherwise unset (65536 for the Gemini leg) — a bare output
# ceiling with no relation to this call's actual output size. 1024 gives
# >10x headroom (covers the Groq stringified-boolean retry noted below)
# without inheriting a ceiling sized for full chat generations.
_ROUTER_MAX_TOKENS = 1024

# Phase W — retry once, on the classifier's second leg specifically (a
# different provider/model — see module docstring), not the same leg again:
# a structurally-invalid completion is a generation-shape problem, and
# nothing about retrying the identical model changes that shape.
_MAX_LEG_ATTEMPTS = 2

_CALL_TYPE = "chat_router_classify"


def _get_classifier_legs() -> list[tuple[str, str, object]]:
    """
    (provider, model_name, leg) triples, already deduplicated to one leg per
    distinct model (see get_structured_chat_model_legs_for_task — the raw
    pool has 2 OpenRouter keys, so without dedup "the next leg" would just be
    nemotron again on a different key, not a different model).
    """
    global _classifier_legs
    if _classifier_legs is None:
        _classifier_legs = get_structured_chat_model_legs_for_task(
            RoutingDecision, _TASK_TYPE, max_tokens=_ROUTER_MAX_TOKENS,
        )
    return _classifier_legs


def _recover_from_content(raw) -> RoutingDecision | None:
    """
    Phase W (2026-08-25 follow-up) — a leg that lands a complete, correctly-
    shaped JSON object in .content instead of a proper tool call still
    computed a real answer; the model just used the wrong channel.
    with_structured_output only ever looks at tool_calls, so this used to be
    logged as StructuredOutputInvalid and cost a full second-leg retry.
    Real data: of the first 21 StructuredOutputInvalid rows logged since the
    validation fix landed, 17 (81%) were exactly this — genuine, complete
    RoutingDecision JSON sitting in .content. Recovering it here still goes
    through full Pydantic validation (RoutingDecision(**data)) — same
    schema-conformance bar as a real tool-call parse, not a loose accept —
    so this doesn't weaken Task 1's validation, it just widens where a valid
    answer is allowed to have come from. Returns None (not a failure by
    itself; caller still logs it as one) when content isn't JSON at all, or
    doesn't validate — real failure modes confirmed to still exist (raw
    reasoning text, or the leg answering the user's question instead of
    classifying it).
    """
    if raw is None:
        return None
    content = getattr(raw, "content", None)
    if not isinstance(content, str) or not content.strip():
        return None
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return RoutingDecision(**data)
    except (ValidationError, TypeError):
        return None


def _log_structured_output_invalid(
    *, provider: str, raw, parsing_error, messages: list[dict], metadata: dict, attempt: int,
) -> None:
    """
    Phase W: an explicit, honest failure row for a completion that arrived
    fine at the raw-HTTP level (already logged success=True by LLMCallLogger
    for that same call) but didn't yield a valid RoutingDecision. Same
    call_type as the real calls so success-rate queries reflect this;
    error_type is a distinct, greppable marker so it's never confused with a
    genuine network/provider error.
    """
    now = datetime.now(timezone.utc).isoformat()
    model_used = None
    output_text = ""
    if raw is not None:
        model_used = (getattr(raw, "response_metadata", None) or {}).get("model_name")
        try:
            output_text = extract_text(raw)
        except Exception:
            output_text = str(getattr(raw, "content", "") or "")
    write_call_row(
        run_id=uuid4().hex,
        parent_run_id=None,
        timestamp_start=now,
        timestamp_end=now,
        latency_ms=0,
        provider=provider,
        model_requested=None,
        model_used=model_used,
        call_type=_CALL_TYPE,
        user_id=metadata.get("user_id"),
        project_id=metadata.get("project_id"),
        day_ref=metadata.get("day_ref"),
        input_text="\n".join(f"{m['role']}: {m['content']}" for m in messages),
        output=output_text,
        success=False,
        error_type="StructuredOutputInvalid",
        error_message=(
            f"with_structured_output returned parsed=None for RoutingDecision "
            f"(attempt {attempt + 1}/{_MAX_LEG_ATTEMPTS}); parsing_error={parsing_error!r}"
        ),
        retry_count=attempt,
        created_at=now,
        trace_id=metadata.get("trace_id"),
        agent_name=metadata.get("agent_name"),
        surface=metadata.get("surface"),
        is_test=bool(metadata.get("is_test", False)),
    )


def _normalize_history_content(content) -> str:
    """History from _load_history_messages can carry multipart content
    (text + Gemini "media" parts, for an image turn) — the classifier only
    ever needs the text; images are irrelevant to a routing decision and
    are Gemini-file-uri dicts that would mean nothing to a different leg's
    provider anyway."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
        )
    return ""


def classify_message(
    message: str, metadata: dict | None = None, history: list[dict] | None = None,
) -> RoutingDecision | None:
    """
    Classify one user message. Returns None (never raises) if both attempted
    legs fail — either a raised exception (network/provider error, logged by
    LLMCallLogger as normal) or a structurally-invalid completion (logged
    explicitly here — see _log_structured_output_invalid).

    `history` (Phase W, 2026-08-25 follow-up): the same already-truncated
    recent-turns window chat_turn itself is about to see (chat_service.py
    slices it before submitting the router job — see chat_prompt_service.
    MAX_HISTORY_TURNS) — the classifier judges tool need and shapes
    search-ready queries with the exact context the generator answers with,
    not a context-blind guess. Previously always []: real, confirmed via
    both exactly_what_change_I_want.md and fuck_it.md — the classifier's own
    input carried only the system prompt and the current message, regardless
    of how much prior conversation existed. Latency is not the constraint
    here (explicit), so no attempt is made to trim this further than
    chat_turn's own window.
    """
    meta = {"call_type": _CALL_TYPE, **(metadata or {})}
    messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
    for turn in (history or []):
        text = _normalize_history_content(turn.get("content"))
        if text:
            messages.append({"role": turn.get("role", "user"), "content": text})
    messages.append({"role": "user", "content": message})
    legs = _get_classifier_legs()[:_MAX_LEG_ATTEMPTS]

    for attempt, (provider, model_name, leg) in enumerate(legs):
        try:
            result = leg.invoke(messages, config={"metadata": meta})
        except Exception:
            logger.warning(
                "[chat_router] leg %d/%d (%s/%s) raised (non-fatal)",
                attempt + 1, len(legs), provider, model_name, exc_info=True,
            )
            continue

        parsed = result.get("parsed") if isinstance(result, dict) else result
        if isinstance(parsed, RoutingDecision):
            return parsed

        parsing_error = result.get("parsing_error") if isinstance(result, dict) else None
        raw = result.get("raw") if isinstance(result, dict) else None

        recovered = _recover_from_content(raw)
        if recovered is not None:
            logger.info(
                "[chat_router] leg %d/%d (%s/%s) landed valid JSON in .content instead of a "
                "tool call — recovered, not a real failure, no retry needed",
                attempt + 1, len(legs), provider, model_name,
            )
            return recovered

        logger.warning(
            "[chat_router] leg %d/%d (%s/%s) completed but produced no valid RoutingDecision (non-fatal)",
            attempt + 1, len(legs), provider, model_name,
        )
        _log_structured_output_invalid(
            provider=provider, raw=raw, parsing_error=parsing_error,
            messages=messages, metadata=meta, attempt=attempt,
        )

    return None


def map_to_task_type(decision: RoutingDecision) -> str:
    """
    requires_code_execution -> coding; else needs_tool -> tool_use; else
    complexity=="complex" -> complex_reasoning; else simple_qa.

    requires_code_execution checked FIRST (Chat-R5a — was needs_tool first,
    silently dropping code execution whenever both were True): tool binding
    (web_search) is decided by chat_mode at the chat_service
    call site, entirely independent of task_type — "coding"'s model-priority
    list (model_priority.py) already puts a Gemini 3+ leg first, and that leg
    supports code_execution AND function-calling tools together (chat_agent.
    CodeExecutionToolMiddleware sets the required tool_config flag whenever
    the leg is Gemini 3+, regardless of task_type). So "coding" is already
    both code-capable and tool-capable on its first leg — no new registry
    entry needed, just checking this signal first so a message needing both
    doesn't lose code execution to "tool_use"'s Gemini-2.5-first ordering.

    Vision is never produced here — has_attachments is a structural gate the
    caller checks before this module is even invoked.
    """
    if decision.requires_code_execution:
        return "coding"
    if decision.needs_tool:
        return "tool_use"
    if decision.complexity == "complex":
        return "complex_reasoning"
    return "simple_qa"
