"""
Chat's LangGraph agent, built on model_provider._build_raw_models()
(Gemini key-pool -> Groq fallback), driven by ModelFallbackMiddleware +
ModelRetryMiddleware so create_agent's stream_mode="messages" gives real
per-token deltas end to end. Replaces grok_service.ask_grok_chat_stream() for
the /chat/stream path only — sync /chat stays on grok_service.

Why middleware, not model_provider.get_chat_model()'s wrapped chain directly:
create_agent's model node calls model_.invoke(messages) internally. Verified
live that when the model passed to create_agent carries baked-in callbacks
(chain.with_config(callbacks=[...]), which is exactly what get_chat_model()
does), LangGraph's message-mode streaming collapses to one chunk per turn.
Neither .with_retry() nor .with_fallbacks() alone (nor combined) cause this —
isolated with fake-model tests, both stream fine untouched. Bare, unwrapped
model instances (what the middleware below operates on) preserve full
per-token streaming. LLMCallLogger is baked onto the compiled AGENT via
agent.with_config(callbacks=[...]) in _build_agent (not the model, and not
passed per-call) — still populates on_chat_model_start's metadata
(call_type/user_id) fine from per-call config={"metadata": {...}}. See
_build_agent's comment for why it has to be agent-level, not per-call —
Chat-6 found a further wrinkle here (below).
Verified this holds with tools bound too (Chat-4.1) — text before/after a
tool call streams in separate deltas, doesn't collapse.

Middleware order matters: [ModelFallbackMiddleware(...), ModelRetryMiddleware(...)]
(fallback OUTER, retry INNER) gives per-leg retry — each model exhausts its own
retry budget before the next leg is tried — matching today's per-leg
.with_retry()-then-.with_fallbacks() semantics (verified: primary retried its
full budget, THEN fell over to fallback, never the reverse). Also required:
on_failure="error" on ModelRetryMiddleware — its default ("continue") converts
an exhausted retry budget into a fake successful AIMessage instead of raising,
which would silently disable fallback entirely (ModelFallbackMiddleware only
reacts to a raised exception).

retry_count in llm_call_log will read 0 on every row: ModelRetryMiddleware
doesn't use LangChain's "retry:attempt:N" tag convention (each attempt fires as
a fully separate on_chat_model_start/on_llm_end run rather than one tagged
run) — confirmed, accepted tradeoff. All attempts for one chat turn (retries
and fallbacks alike) share one parent_run_id (the graph's model-node run), so
admin_service.get_call_tree() already groups them for free, no new code needed.

Chat-4.1 — real tool binding (was tools=None)
----------------------------------------------
Two cached agents, not one: layman mode needs tools genuinely unbound (a hard
structural gate, not a prompt instruction the model could ignore), so it gets
its own zero-tool agent — everything else shares one agent with both tools
bound. web_search/deep_research mode is now just a hint (an extra system
note biasing which tool to prefer) injected by the caller — it does not
change which agent or tools are used, so it needs no separate cached agent.

resolve_tools_and_hint(chat_mode) is the single place that translates a
chat_mode string into (tools_enabled, hint) — pure, no I/O, unit-testable
without touching any API.

ask_chat_stream now yields dicts instead of plain strings so tool activity
can be surfaced to the caller without disturbing chat_title_service's
[TITLE: ...] parser, which only ever sees the "text" events' text:
  {"type": "text", "text": "..."}
  {"type": "thinking", "text": "..."}
  {"type": "thinking_gap", "text": "..."}
  {"type": "tool_start", "tool": "web_search" | "deep_research"}
  {"type": "tool_end", "tool": "...", "sources": [{"title","url"}, ...]}
  {"type": "code", "text": "<source>", "language": "python"}
  {"type": "code_output", "text": "<stdout>", "success": true}

Chat-6 — native thinking
-------------------------
Every Gemini leg is built with thinking on (include_thoughts=True) and a
per-generation param — verified live that GEMINI_MODEL (gemini-2.5-flash)
takes thinking_budget (int token count) while GEMINI_FALLBACK_MODEL
(gemini-3.1-flash-lite, Gemini 3+) takes thinking_level ("low"/"high");
passing both together makes the library silently drop thinking_budget, so
model_provider._thinking_kwargs picks exactly one per leg by model name.
Thinking streams incrementally through stream_mode="messages" as its own
list-item type ("thinking" pre-v1 / "reasoning" under output_version="v1")
before the answer text — never merged into the same chunk — confirmed with
the bare-model + ModelRetryMiddleware stack and with a tool bound (thinking
arrives before the tool_call_chunks, not after the tool result). Reasoning
tokens are billed as part of output_tokens (usage_metadata.output_token_details
.reasoning is a subset, not additive) — real llm_call_log rows show this
directly via output_tokens, no schema change needed. extended_thinking=True
("think harder") raises the budget/level; only chat_agent.py opts individual
Gemini legs into thinking at all — model_provider.get_chat_model() and
get_structured_chat_model()'s other ~20 call sites are unaffected (thinking
defaults off in _build_raw_models).

Third framework wrinkle (see the module-docstring's opening section): verified
live that agent.stream(..., stream_mode="messages", config={"callbacks":[...]})
— an EXTERNAL callback passed per-call — silently drops "thinking"/"reasoning"
content blocks from the chunks LangGraph yields (plain text chunks stream
fine; reproduced with a bare no-op BaseCallbackHandler too, so it's not
LLMCallLogger-specific). on_llm_end's own aggregated result is unaffected —
llm_call_log rows still capture thinking correctly either way — the gap is
only in what reaches this generator live. Baking the callback onto the agent
(_build_agent's agent.with_config(...)) instead of passing it per-call
avoids this entirely; confirmed with a real run before landing this.

Followup — Gemini 3+ thinking is invisible on stream, confirmed upstream, not
a LangChain bug: bypassed LangChain entirely and hit google-genai's raw SDK
directly with an identical ThinkingConfig — client.models.generate_content()
returns a thought=True part (thoughts_token_count populated); the streaming
twin, generate_content_stream(), never emits one, on any chunk, though the
same thoughts_token_count is still billed. output_version="v1" does not
change this (tested standalone and with tools bound) — the block simply never
leaves Google's streaming endpoint for thinking_level-configured models.
thinking_budget-configured (Gemini 2.5) models don't have this restriction.
Not fixable from here, so _stream_agent surfaces a one-shot "thinking_gap"
event instead of a panel that silently never fills in — see _THINKING_GAP_TEXT.

Chat-5 — multimodal (image/PDF via Gemini Files API)
------------------------------------------------------
has_attachments=True builds (and caches) a PRIMARY-KEY-ONLY agent: only
ModelRetryMiddleware, no ModelFallbackMiddleware. Verified live that this is
required, not a defensive guess: model_provider.upload_attachment() uploads
via the first Gemini key only, and Gemini's Files API scopes a file to the
uploading key/project — key #2 gets 403 PERMISSION_DENIED reading a file key
#1 uploaded, then Groq gets a 400 on the "media" content type regardless (no
vision model configured there anyway). Falling through both dead legs before
failing wastes ~2 round trips of retries for a guaranteed-fail outcome, so
attachment turns skip straight to a clean, defined failure (see
VisionUnavailableError below) instead of leaking Groq's raw schema error.

Chat-7 — native code execution
--------------------------------
CodeExecutionToolMiddleware adds Gemini's built-in code_execution tool
({"code_execution": {}}, langchain_google_genai's dict form for server-side
tools) on top of whichever custom tools are already bound — Gemini legs
only, added per-call via wrap_model_call so it sees the CURRENT leg
(request.model), not the agent's original model. Two things verified live,
neither guessable from the docs:

1. Combining code_execution with a custom function-calling tool (web_search/
   deep_research) in the same request 400s ("Please enable
   tool_config.include_server_side_tool_invocations to use Built-in tools
   with Function calling") unless that tool_config flag is set — so this
   middleware sets it on every Gemini call, not just ones that end up using
   code execution.
2. ChatGroq.bind_tools([{"code_execution": {}}]) raises a client-side
   ValueError ("Unsupported function") before any network call — Groq's
   convert_to_openai_tool has no concept of a provider built-in tool dict.
   Unlike Chat-5's vision case (a clean 400 from Google), this would be an
   unhandled crash inside create_agent's tool-binding step, so the
   middleware never adds the dict for a non-Gemini request.model — Groq
   turns fall through to answering in prose without code execution, a soft
   degrade rather than VisionUnavailableError's hard block (code execution
   isn't structurally required to answer, unlike an attached image).

Middleware order: CodeExecutionToolMiddleware sits between
ModelFallbackMiddleware (outer) and ModelRetryMiddleware (inner) — see
_build_agent — so by the time it runs, request.model already reflects
whichever leg is being attempted for this call.

_split_content_chunks gained two new block kinds for this: Gemini streams
code execution as its own list-item types ("executable_code" /
"code_execution_result", raw dict keys — NOT surfaced via tool_call_chunks
or a ToolMessage, since it's a server-side tool, not a client-executed
LangChain @tool) — each arrives as one complete chunk (not token-streamed
like text), interleaved before the model's own follow-up prose. Google's own
client warns this shape "may vary each run" (execution_result can be absent
even when code ran) — a documented upstream quirk, not a bug here.

Public API
----------
resolve_tools_and_hint(chat_mode) -> (bool, str | None)
ask_chat_stream(messages, metadata=None, tools_enabled=True, has_attachments=False,
                 extended_thinking=False) -> Iterator[dict]
"""
from __future__ import annotations

import logging

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelFallbackMiddleware, ModelRetryMiddleware
from langchain_google_genai import ChatGoogleGenerativeAI

from ..config import GEMINI_MODEL as MODEL_NAME
from .call_logger import LLMCallLogger
from .model_provider import _build_raw_models, _is_gemini_3_plus, _RETRY_ATTEMPTS

logger = logging.getLogger(__name__)


class VisionUnavailableError(RuntimeError):
    """Raised when the primary Gemini key fails on a turn carrying attachments.

    Deliberately NOT retried across the Gemini fallback key or Groq — both are
    guaranteed to fail for a file-attached turn (see module docstring) — so
    callers should show this as a clear, immediate error rather than a generic
    "AI generation failed".
    """


_agent_cache: dict[tuple[bool, bool, bool], object] = {}

_MODE_HINTS: dict[str, str] = {
    "web_search": (
        "[MODE HINT] The user has Web Search mode active for this turn — prefer "
        "calling the web_search tool for this question unless it is already "
        "fully answerable from the conversation context above."
    ),
    "deep_research": (
        "[MODE HINT] The user has Deep Research mode active for this turn — "
        "prefer calling the deep_research tool for this question for thorough "
        "multi-source analysis, unless it is already fully answerable from the "
        "conversation context above."
    ),
}


def resolve_tools_and_hint(chat_mode: str) -> tuple[bool, str | None]:
    """
    Translate chat_mode into (tools_enabled, hint_or_None) for one chat turn.

    layman         -> (False, None)  tools genuinely unbound this call, not
                                      just discouraged in the prompt.
    web_search /
    deep_research  -> (True, hint)   tools bound; hint biases which one, the
                                      model still decides.
    normal (or
    anything else) -> (True, None)   tools bound, no bias, model decides freely.
    """
    if chat_mode == "layman":
        return False, None
    return True, _MODE_HINTS.get(chat_mode)


class CodeExecutionToolMiddleware(AgentMiddleware):
    """Adds Gemini's code_execution tool to Gemini legs only — see Chat-7 in
    this module's docstring for why (Groq crashes client-side on the dict
    form, and combining it with a custom tool needs an explicit tool_config
    flag)."""

    def __init__(self, enabled: bool = True) -> None:
        super().__init__()
        self._enabled = enabled

    def wrap_model_call(self, request, handler):
        if not self._enabled or not isinstance(request.model, ChatGoogleGenerativeAI):
            return handler(request)
        return handler(request.override(
            tools=[*request.tools, {"code_execution": {}}],
            model_settings={
                **request.model_settings,
                "tool_config": {"include_server_side_tool_invocations": True},
            },
        ))


def _build_agent(tools, vision_only: bool = False, extended_thinking: bool = False):
    pairs = _build_raw_models(
        streaming=True, legs="gemini" if vision_only else "all",
        thinking=True, extended_thinking=extended_thinking,
    )
    if vision_only:
        pairs = pairs[:1]  # primary Gemini key only — see module docstring
    primary, *fallback_models = [m for m, _ in pairs]
    retry_on = tuple({exc for _, exc_types in pairs for exc in exc_types})
    middleware = [
        CodeExecutionToolMiddleware(enabled=tools is not None),
        ModelRetryMiddleware(
            max_retries=_RETRY_ATTEMPTS - 1,
            retry_on=retry_on,
            on_failure="error",
        ),
    ]
    if fallback_models:
        middleware.insert(0, ModelFallbackMiddleware(*fallback_models))
    agent = create_agent(model=primary, tools=tools, middleware=middleware)
    # Baked onto the agent (graph level), not passed per-call via
    # config={"callbacks": [...]} — verified live that passing ANY external
    # callback through agent.stream(config=...) with stream_mode="messages"
    # silently drops Gemini's "thinking" content blocks from the yielded
    # chunks (plain text chunks are unaffected) while on_llm_end's final
    # aggregated result still has them intact — a LangGraph-specific
    # interaction, reproduced with a no-op BaseCallbackHandler too, so it's
    # not particular to LLMCallLogger. Baking the callback in here instead
    # (this is the opposite of Chat-2's finding, which was about baking
    # callbacks onto the raw MODEL collapsing streaming entirely) avoids it;
    # per-call metadata still flows through fine via config={"metadata": {...}}
    # in ask_chat_stream. One shared LLMCallLogger per cached agent is safe —
    # its state is keyed by run_id, which LangChain guarantees unique per call.
    return agent.with_config(callbacks=[LLMCallLogger()])


def _get_agent(tools_enabled: bool, vision_only: bool = False, extended_thinking: bool = False):
    key = (tools_enabled, vision_only, extended_thinking)
    if key not in _agent_cache:
        tools = None
        if tools_enabled:
            from .chat_tools import web_search, deep_research
            tools = [web_search, deep_research]
        _agent_cache[key] = _build_agent(tools, vision_only=vision_only, extended_thinking=extended_thinking)
    return _agent_cache[key]


def _preflight_check(messages: list[dict]) -> None:
    """
    Active budget preflight before every chat agent call.

    Evaluated against the primary model (Gemini) since that's who answers
    first in the fallback chain — mirrors grok_service._preflight_check's
    contract (raises RuntimeError on OVER_LIMIT, swallows estimation errors).
    """
    try:
        from ..services.token_budget import (
            estimate_total_request, evaluate, log_budget_plan, BudgetStatus,
        )
        from ..services.model_registry import get_model_config
        tokens       = estimate_total_request(messages=messages)
        default_tier = get_model_config(MODEL_NAME).default_provider_tier
        plan         = evaluate(tokens, MODEL_NAME, provider_tier=default_tier)
        log_budget_plan(plan, logger)
        if plan.status == BudgetStatus.OVER_LIMIT:
            raise RuntimeError(
                f"[chat_agent] Prompt exceeds effective budget: "
                f"{plan.current_prompt_tokens:,} tokens > "
                f"{plan.available_input_budget:,} effective "
                f"(model={plan.model_limit:,}, provider={plan.provider_limit or plan.model_limit:,}) "
                f"+{plan.overflow_tokens:,} overflow."
            )
    except RuntimeError:
        raise   # budget overflow — never swallow
    except Exception:
        logger.debug("[chat_agent] Budget pre-check failed (non-fatal)", exc_info=True)


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


def ask_chat_stream(
    messages: list[dict], metadata: dict | None = None, tools_enabled: bool = True,
    has_attachments: bool = False, extended_thinking: bool = False,
):
    """
    Streaming version of the chat turn, answered by the Gemini-primary /
    Groq-fallback agent instead of a raw Groq client.

    Yields dicts (see module docstring for the shapes) instead of plain
    strings — chat_title_service's [TITLE: ...] parser only ever sees the
    "text" events' text field, so it needs no changes.

    `metadata` is passed via config={"metadata": {...}} at call time (not baked
    into the model) so LLMCallLogger records call_type/user_id without breaking
    per-token streaming (see module docstring).

    `tools_enabled=False` (layman mode) uses a separate agent with tools=None —
    a structural gate, not a prompt instruction.

    `has_attachments=True` uses the primary-key-only agent (see module
    docstring's Chat-5 section) and re-raises any failure as
    VisionUnavailableError instead of letting it fall through to a fallback
    leg that's guaranteed to fail anyway.

    `extended_thinking=True` is the "think harder" toggle (Chat-6) — deeper
    reasoning budget/level per Gemini leg, off by default. Baseline (visible)
    thinking is always on regardless of this flag; see model_provider._thinking_kwargs.
    """
    _preflight_check(messages)
    agent = _get_agent(tools_enabled, vision_only=has_attachments, extended_thinking=extended_thinking)

    # LLMCallLogger is baked onto the agent itself, not passed here — see
    # _build_agent's comment for why a per-call callbacks= config breaks
    # streamed thinking content.
    config: dict = {}
    if metadata:
        config["metadata"] = metadata

    try:
        yield from _stream_agent(agent, messages, config)
    except Exception as exc:
        if has_attachments:
            raise VisionUnavailableError(
                "Vision is temporarily unavailable — please try again in a moment."
            ) from exc
        raise


_THINKING_GAP_TEXT = (
    "Extended reasoning ran but isn't visible for this response — a known "
    "streaming limitation on this model tier. It still happened (and was "
    "billed), it just can't be shown."
)


def _stream_agent(agent, messages: list[dict], config: dict):
    seen_tool_call_ids: set[str] = set()
    thinking_gap_sent = False
    for msg_chunk, meta in agent.stream(
        {"messages": messages}, stream_mode="messages", config=config,
    ):
        # meta["ls_model_name"] is populated from chunk #1 (same key
        # LLMCallLogger reads at on_chat_model_start) — cheapest possible
        # point to know which leg is answering. Gemini 3+ legs (thinking_level)
        # never surface streamed thinking content — confirmed upstream API
        # limitation, not fixable here (see module docstring) — so tell the
        # user once, as early as possible, instead of a panel that just never
        # appears. Gemini 2.5 legs (thinking_budget) are unaffected.
        if not thinking_gap_sent and _is_gemini_3_plus(meta.get("ls_model_name") or ""):
            thinking_gap_sent = True
            yield {"type": "thinking_gap", "text": _THINKING_GAP_TEXT}

        tool_call_chunks = getattr(msg_chunk, "tool_call_chunks", None)
        if tool_call_chunks:
            for tc in tool_call_chunks:
                tc_id = tc.get("id")
                name  = tc.get("name")
                if name and tc_id and tc_id not in seen_tool_call_ids:
                    seen_tool_call_ids.add(tc_id)
                    yield {"type": "tool_start", "tool": name}

        if type(msg_chunk).__name__ == "ToolMessage":
            yield {
                "type":    "tool_end",
                "tool":    getattr(msg_chunk, "name", None),
                "sources": getattr(msg_chunk, "artifact", None) or [],
            }
            continue

        for kind, text, meta in _split_content_chunks(getattr(msg_chunk, "content", "")):
            event = {"type": kind, "text": text}
            if meta:
                event.update(meta)
            yield event
