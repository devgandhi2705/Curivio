"""Chat's answer stream: one model list, tried top to bottom, no agent.

Replaces the LangGraph create_agent stack (ModelFallbackMiddleware +
ModelRetryMiddleware + CodeExecutionToolMiddleware + a web_search tool). What
that stack bought is now: model_provider.run_route for fallback and retry, a
bare model's .stream() for per-token output, and one bind_tools call for
Gemini's own code execution. The search runs in chat_service before the answer
starts, so no client-side tool is bound at all.

Rules carried over, each verified live when it was found:
  - Callbacks are passed PER CALL, never baked onto the model: a model built
    with callbacks collapses per-token streaming into one chunk per turn.
  - Gemini 3.x never streams its thinking (reproduced against google-genai's
    raw SDK, so not a LangChain bug) - say so once instead of showing a panel
    that never fills.
  - code_execution is a Gemini-3-only capability. On any other leg the model
    still writes code, it just cannot run it: a soft degrade with one note.
  - An image turn uses the primary Gemini key only - a file uploaded with key
    #1 is 403 for key #2 - and fails with a clear message rather than falling
    through legs that structurally cannot see it. route_legs() enforces the
    key; VisionUnavailableError carries the message.

Event shapes (unchanged; chat_service adds seq/block_id):
  {"type": "text",        "text": str}
  {"type": "thinking",    "text": str}
  {"type": "code",        "text": str, "language": str}
  {"type": "code_output", "text": str, "success": bool}
  {"type": "status" | "thinking_gap" | "code_execution_gap", "text": str}

Public API
----------
ask_chat_stream(messages, *, route, route_reason="", metadata=None) -> Iterator[dict]
VisionUnavailableError
"""
from __future__ import annotations

import logging

from .call_logger import LLMCallLogger
from .model_provider import (
    AllLegsFailed,
    PromptTooLargeError,
    _is_gemini_3_plus,
    build_leg,
    registry_model_name,
    route_label,
    run_route,
)

logger = logging.getLogger(__name__)


class VisionUnavailableError(RuntimeError):
    """Every Gemini leg failed on a turn carrying an image. Deliberately not
    retried anywhere else: Groq has no vision model in this stack, and a second
    Gemini key cannot read a file the first one uploaded."""


_THINKING_GAP_TEXT = (
    "Extended reasoning ran but isn't visible for this response — a known "
    "streaming limitation on this model tier. It still happened (and was "
    "billed), it just can't be shown."
)

_CODE_EXECUTION_GAP_TEXT = (
    "Code execution wasn't available for this response — the model wrote "
    "code but couldn't run it. The code below is unexecuted."
)


def _check_budget(spec, messages: list[dict]) -> None:
    """Skip a leg this prompt cannot fit instead of paying for a guaranteed 413.
    Matters because the free Groq legs are capped by tokens-per-minute (8K), not
    by context window. Estimation failures are non-fatal: a broken estimate must
    never block a turn that would have worked."""
    from ..services.model_registry import get_model_config
    from ..services.token_budget import BudgetStatus, estimate_total_request, evaluate, log_budget_plan

    try:
        name = registry_model_name(spec)
        tokens = estimate_total_request(messages=messages)
        plan = evaluate(tokens, name, provider_tier=get_model_config(name).default_provider_tier)
        log_budget_plan(plan, logger)
    except Exception:
        logger.debug("[chat_agent] budget pre-check failed (non-fatal)", exc_info=True)
        return
    if plan.status == BudgetStatus.OVER_LIMIT:
        raise PromptTooLargeError(
            f"{plan.current_prompt_tokens:,} prompt tokens > "
            f"{plan.available_input_budget:,} effective budget for {name}")


def _split_content_chunks(content):
    """
    Yield (kind, text, meta) triples from a streamed message-chunk's content.
    kind is "thinking", "text", "code", or "code_output"; meta is None except
    for "code" ({"language": ...}) and "code_output" ({"success": bool}).

    Gemini's thinking blocks arrive as their own list items (type "thinking"
    pre-v1 / "reasoning" under output_version="v1", verified live) interleaved
    with plain text items in content, never merged into one block — mirrors
    model_provider.extract_text's list-flattening but keeps thinking and
    answer text apart instead of collapsing both to "". Code execution blocks
    (type "executable_code" / "code_execution_result", Chat-7) are the same
    idea — each arrives as one complete chunk, not token-streamed.
    """
    if isinstance(content, str):
        if content:
            yield "text", content, None
        return
    if isinstance(content, list):
        for item in content:
            if isinstance(item, str):
                if item:
                    yield "text", item, None
            elif isinstance(item, dict):
                item_type = item.get("type")
                if item_type == "executable_code":
                    code = item.get("executable_code", "")
                    if code:
                        # language is a google.genai.types.Language enum member
                        # (e.g. Language.PYTHON) — str() on it gives "Language.PYTHON",
                        # not "PYTHON" (confirmed live), so read .value explicitly.
                        lang_raw = item.get("language") or "python"
                        language = str(getattr(lang_raw, "value", lang_raw)).lower()
                        yield "code", code, {"language": language}
                elif item_type == "code_execution_result":
                    output = item.get("code_execution_result", "")
                    if output:
                        # outcome 1 == OUTCOME_OK per langchain_google_genai's own
                        # raw-content mapping (verified live) — anything else is a failure.
                        yield "code_output", output, {"success": item.get("outcome") == 1}
                else:
                    is_thinking = item_type in ("thinking", "reasoning")
                    text = (item.get("thinking") or item.get("reasoning") or "") if is_thinking else (item.get("text", "") or "")
                    if text:
                        yield ("thinking" if is_thinking else "text"), text, None


def ask_chat_stream(messages: list[dict], *, route: str, route_reason: str = "",
                    metadata: dict | None = None):
    """Stream one chat turn through `route`'s model list.

    `route` / `route_reason` come from the TurnPlan and are written to every
    llm_call_log row this turn makes, so the admin log says which list answered
    and what it fell past.
    """
    notes: list[str] = []
    base_meta = dict(metadata or {})

    def attempt(spec):
        model = build_leg(spec, streaming=True, thinking=True)
        _check_budget(spec, messages)
        if route == "code" and spec.provider == "gemini" and _is_gemini_3_plus(spec.model):
            # Gemini's own server-side tool. No tool_config flag needed now that
            # chat binds no function-calling tool alongside it.
            model = model.bind_tools([{"code_execution": {}}])
        return model.stream(messages, config={
            "callbacks": [LLMCallLogger()],
            "metadata": {**base_meta,
                         "route": route_label(route, route_reason, notes),
                         "route_step": spec.step},
        })

    if route == "image":
        yield {"type": "status", "text": "Reading attachment…"}

    try:
        spec, chunks = run_route(route, attempt, notes=notes)
    except AllLegsFailed as exc:
        if route == "image":
            raise VisionUnavailableError(
                "Vision is temporarily unavailable — please try again in a moment.") from exc
        raise

    answered_on_gemini_3 = spec.provider == "gemini" and _is_gemini_3_plus(spec.model)
    if answered_on_gemini_3:
        yield {"type": "thinking_gap", "text": _THINKING_GAP_TEXT}
    if route == "code" and not answered_on_gemini_3:
        yield {"type": "code_execution_gap", "text": _CODE_EXECUTION_GAP_TEXT}

    for chunk in chunks:
        for kind, text, meta in _split_content_chunks(getattr(chunk, "content", "")):
            event = {"type": kind, "text": text}
            if meta:
                event.update(meta)
            yield event
