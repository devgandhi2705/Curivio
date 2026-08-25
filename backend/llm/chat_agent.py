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
its own zero-tool agent — everything else shares one agent with the tool
bound. web_search mode is now just a hint (an extra system note biasing
which tool to prefer) injected by the caller — it does not change which
agent or tools are used, so it needs no separate cached agent.

resolve_tools_and_hint(chat_mode) is the single place that translates a
chat_mode string into (tools_enabled, hint) — pure, no I/O, unit-testable
without touching any API.

ask_chat_stream now yields dicts instead of plain strings so tool activity
can be surfaced to the caller without disturbing chat_title_service's
[TITLE: ...] parser, which only ever sees the "text" events' text. Every
event below except the three one-shot gap notes also carries "seq" (a flat
per-turn counter) and "block_id" (Chat-R10d — groups contiguous same-kind
chunks into one logical block; a tool_start/tool_end pair for the same call
shares one block_id) — see _stream_agent's _emit for the exact rule:
  {"type": "text", "text": "...", "seq": int, "block_id": int}
  {"type": "thinking", "text": "...", "seq": int, "block_id": int}
  {"type": "thinking_gap", "text": "..."}
  {"type": "code_execution_gap", "text": "..."}
  {"type": "tool_start", "tool": "web_search", "query": str | None, "seq": int, "block_id": int}
  {"type": "tool_end", "tool": "...", "sources": [{"title","url"}, ...], "seq": int, "block_id": int}
  {"type": "code", "text": "<source>", "language": "python", "seq": int, "block_id": int}
  {"type": "code_output", "text": "<stdout>", "success": true, "seq": int, "block_id": int}

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
directly via output_tokens, no schema change needed. Only chat_agent.py opts
individual Gemini legs into thinking at all — model_provider.get_chat_model()
and get_structured_chat_model()'s other ~20 call sites are unaffected
(thinking defaults off in _build_raw_models); chat_agent.py's own legs always
run at the baseline (low/1024) budget — the "think harder" toggle that used
to escalate it was removed, no code path raises it anymore.

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

1. Combining code_execution with a custom function-calling tool (web_search)
   in the same request 400s ("Please enable
   tool_config.include_server_side_tool_invocations to use Built-in tools
   with Function calling") unless that tool_config flag is set.
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

Chat-R2 — leg-aware gating (was: unconditional on every Gemini call)
----------------------------------------------------------------------
Originally the middleware set the tool_config flag on every Gemini leg once
any tools were bound. Confirmed live (and in Google's own docs — ai.google.dev/
gemini-api/docs/tool-combination: "supported for Gemini 3 models only") that
combining a built-in tool with function calling is a Gemini-3-only capability
— gemini-2.5-flash 400s even with the flag correctly set, with a distinct,
model-specific error ("Tool call context circulation is not enabled for
models/gemini-2.5-flash"), not the generic "flag missing" error Gemini 3 legs
give without it. That's a hard generation gate, not a fixable config gap: no
alternate flag/config makes 2.5 accept the combination. This meant every
tool-enabled turn burned 2 pooled gemini-2.5-flash keys x _RETRY_ATTEMPTS
guaranteed-fail calls before falling through to the one Gemini leg
(gemini-3.1-flash-lite) that accepts the flag — see docs/chat-reliability/
chat-r1-recon.md Step 3 for the real timings this cost.

Fix: wrap_model_call now also checks _is_gemini_3_plus(request.model.model)
(model_provider's existing helper, already used elsewhere in this module)
before adding code_execution/the tool_config override — Gemini 2.5 legs skip
the override entirely and proceed with just their agent-bound custom tool
(web_search), confirmed live to work fine standalone since it's a plain
function-calling tool with no built-in-tool conflict.
code_execution is simply unavailable on 2.5 legs as a result — not a
fallback trigger, not degraded, just absent for that leg (mirrors Chat-7's
Groq soft-degrade, same reasoning: code execution isn't structurally
required to answer).

_split_content_chunks gained two new block kinds for this: Gemini streams
code execution as its own list-item types ("executable_code" /
"code_execution_result", raw dict keys — NOT surfaced via tool_call_chunks
or a ToolMessage, since it's a server-side tool, not a client-executed
LangChain @tool) — each arrives as one complete chunk (not token-streamed
like text), interleaved before the model's own follow-up prose. Google's own
client warns this shape "may vary each run" (execution_result can be absent
even when code ran) — a documented upstream quirk, not a bug here.

Chat-R4 — task-based routing (chat_router.py + model_priority.py)
--------------------------------------------------------------------
chat_service.chat_stream() runs an LLM classifier (chat_router.classify_message,
model_priority task_type "routing") ONLY for chat_mode=="normal" turns with no
attachments — an explicit web_search toggle always wins outright
(R1: proven 10/10 explicit-toggle hit rate; the classifier targets the
"normal"-mode gap R1 measured at 2/10), and has_attachments turns never
consult it (vision hard gate, Chat-5, untouched). The classification maps to
a task_type (chat_router.map_to_task_type) threaded through ask_chat_stream's
new task_type param -> _get_agent (cache key gained a 4th element) ->
_build_agent, which calls model_provider.build_pooled_legs(model_priority.
get_model_priority_list(task_type), streaming=True, thinking=True, ...)
instead of _build_raw_models() — same bare-legs shape, so it plugs into the
identical ModelFallbackMiddleware/ModelRetryMiddleware construction below.
task_type=None (layman/explicit-toggle/vision/no-classification) uses the
default fixed chain, byte-identical to pre-R4 behavior.

_MODE_HINTS became build_mode_hint(tool_name, shaped_query="") — same static
text for the explicit-toggle path (shaped_query defaults to "", producing the
old byte-identical string); the router additionally passes its own
shaped_query to bias which search terms the model uses, not just which tool.

Public API
----------
resolve_tools_and_hint(chat_mode) -> (bool, str | None)
build_mode_hint(tool_name, shaped_query="") -> str | None
ask_chat_stream(messages, metadata=None, tools_enabled=True, has_attachments=False,
                 task_type=None) -> Iterator[dict]
"""
from __future__ import annotations

import json
import logging

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelFallbackMiddleware, ModelRetryMiddleware
from langchain_google_genai import ChatGoogleGenerativeAI

from ..config import GEMINI_MODEL as MODEL_NAME
from .call_logger import LLMCallLogger
from .model_provider import (
    _build_raw_models,
    _is_daily_quota_exhausted,
    _is_gemini_3_plus,
    _RETRY_ATTEMPTS,
    build_pooled_legs,
)

logger = logging.getLogger(__name__)


class VisionUnavailableError(RuntimeError):
    """Raised when the primary Gemini key fails on a turn carrying attachments.

    Deliberately NOT retried across the Gemini fallback key or Groq — both are
    guaranteed to fail for a file-attached turn (see module docstring) — so
    callers should show this as a clear, immediate error rather than a generic
    "AI generation failed".
    """


_agent_cache: dict[tuple[bool, bool, str | None], object] = {}

# Phase W: task-routed chat_turn legs (build_pooled_legs below) never set
# max_tokens, so every provider's own implicit default applied — 65536 for
# the OpenRouter/Nemotron leg, confirmed live and in real llm_call_log rows
# (PaymentRequiredResponseError: "requested up to 65536 tokens, but can only
# afford ~25000"). Real data (1573 successful chat_turn rows): median 159,
# p90 1079, p95 1531, p99 2392, max ever observed 4824 output tokens. 8192
# gives >1.7x headroom over the largest real answer ever produced and >3x
# over p99, while staying well clear of the ~24-25K OpenRouter has actually
# been affording — unlike 65536, which was never a deliberate choice for
# either the classifier or this call, just an unset default.
_CHAT_TURN_MAX_TOKENS = 8192

_MODE_HINT_TEMPLATES: dict[str, str] = {
    "web_search": (
        "[MODE HINT] The user has Web Search mode active for this turn — prefer "
        "calling the web_search tool for this question unless it is already "
        "fully answerable from the conversation context above."
    ),
}


def build_mode_hint(tool_name: str | None, shaped_query: str = "") -> str | None:
    """
    Bias text for the model toward a specific tool this turn. tool_name is
    either an explicit chat_mode toggle ("web_search") or the Chat-R4
    router's classified tool_name — same hint either way. shaped_query
    (router only) appends a suggested, search-ready query; empty for the
    explicit-toggle path, which stays byte-identical to the old static
    _MODE_HINTS text.
    """
    base = _MODE_HINT_TEMPLATES.get(tool_name or "")
    if base is None:
        return None
    if shaped_query:
        base = f"{base} Suggested search query: {shaped_query!r}."
    return base


def resolve_tools_and_hint(chat_mode: str) -> tuple[bool, str | None]:
    """
    Translate chat_mode into (tools_enabled, hint_or_None) for one chat turn.

    layman         -> (False, None)  tools genuinely unbound this call, not
                                      just discouraged in the prompt.
    web_search     -> (True, hint)   tools bound; hint biases the tool, the
                                      model still decides. Explicit toggle —
                                      Chat-R4's router is never consulted here.
    normal (or
    anything else) -> (True, None)   tools bound, no bias by default; Chat-R4's
                                      router (chat_service.chat_stream) may
                                      still layer a hint on top for this mode.
    """
    if chat_mode == "layman":
        return False, None
    return True, build_mode_hint(chat_mode)


class CodeExecutionToolMiddleware(AgentMiddleware):
    """Adds Gemini's code_execution tool to Gemini 3+ legs only — see Chat-7
    in this module's docstring for why (Groq crashes client-side on the dict
    form, and combining it with a custom tool needs an explicit tool_config
    flag), and Chat-R2 for why it's gated to Gemini 3+ specifically:
    combining a built-in tool with function calling is a Gemini-3-only
    capability (confirmed live and in Google's own docs — ai.google.dev/
    gemini-api/docs/tool-combination: "supported for Gemini 3 models only").
    Gemini 2.5 legs 400 with a model-specific error ("Tool call context
    circulation is not enabled for models/gemini-2.5-flash") even with the
    flag set — a hard generation gate, not a config mistake. Skipping the
    override on 2.5 legs leaves web_search untouched (a plain function-calling
    tool, verified live to work fine on 2.5-flash alone) and simply omits
    code_execution for that leg, not a fallback trigger."""

    def __init__(self, enabled: bool = True) -> None:
        super().__init__()
        self._enabled = enabled

    def wrap_model_call(self, request, handler):
        if (
            not self._enabled
            or not isinstance(request.model, ChatGoogleGenerativeAI)
            or not _is_gemini_3_plus(request.model.model)
        ):
            return handler(request)
        return handler(request.override(
            tools=[*request.tools, {"code_execution": {}}],
            model_settings={
                **request.model_settings,
                "tool_config": {"include_server_side_tool_invocations": True},
            },
        ))


def _build_agent(tools, vision_only: bool = False, task_type: str | None = None):
    if vision_only or task_type is None:
        # Default fixed chain — unchanged for layman/explicit-toggle/vision
        # turns and for any caller that doesn't pass a task_type.
        pairs = _build_raw_models(
            streaming=True, legs="gemini" if vision_only else "all",
            thinking=True,
        )
        if vision_only:
            pairs = pairs[:1]  # primary Gemini key only — see module docstring
    else:
        # Chat-R4: task-routed chain — model priority list per model_priority.
        # get_model_priority_list(task_type), keys-within-model before
        # model-drop (model_provider.build_pooled_legs). Same bare-legs shape
        # as _build_raw_models() above, so it plugs into the identical
        # ModelFallbackMiddleware/ModelRetryMiddleware construction below.
        from .model_priority import get_model_priority_list
        pairs = build_pooled_legs(
            get_model_priority_list(task_type),
            streaming=True, thinking=True, max_tokens=_CHAT_TURN_MAX_TOKENS,
        )
    primary, *fallback_models = [m for m, _ in pairs]
    retry_on_types = tuple({exc for _, exc_types in pairs for exc in exc_types})

    def _retry_on(exc: Exception) -> bool:
        # Same quota-aware exclusion as model_provider._QuotaAwareRetry: a
        # confirmed daily-quota exhaustion can't recover between attempts, so
        # ModelRetryMiddleware's should_retry_exception() returning False here
        # skips straight to re-raising (on_failure="error") with NO backoff
        # sleep at all — immediate fallthrough to the next leg via
        # ModelFallbackMiddleware. Genuine transient errors (RPM/TPM, network)
        # keep the normal exponential backoff below, unchanged.
        return isinstance(exc, retry_on_types) and not _is_daily_quota_exhausted(exc)

    middleware = [
        CodeExecutionToolMiddleware(enabled=tools is not None),
        ModelRetryMiddleware(
            max_retries=_RETRY_ATTEMPTS - 1,
            retry_on=_retry_on,
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


def _get_agent(tools_enabled: bool, vision_only: bool = False, task_type: str | None = None):
    key = (tools_enabled, vision_only, task_type)
    if key not in _agent_cache:
        tools = None
        if tools_enabled:
            from .chat_tools import web_search
            tools = [web_search]
        _agent_cache[key] = _build_agent(
            tools, vision_only=vision_only, task_type=task_type,
        )
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
    has_attachments: bool = False, task_type: str | None = None,
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

    Visible (baseline) thinking is always on for every Gemini leg — see
    model_provider._thinking_kwargs.

    `task_type` (Chat-R4) selects a model-priority chain from model_priority.
    get_model_priority_list() instead of the default fixed chain — None uses
    the default chain unchanged. Forced to None whenever has_attachments=True
    regardless of what's passed: the vision hard gate (Chat-5) is never
    subject to task-based routing.
    """
    _preflight_check(messages)
    effective_task_type = None if has_attachments else task_type
    agent = _get_agent(
        tools_enabled, vision_only=has_attachments,
        task_type=effective_task_type,
    )

    # LLMCallLogger is baked onto the agent itself, not passed here — see
    # _build_agent's comment for why a per-call callbacks= config breaks
    # streamed thinking content.
    config: dict = {}
    if metadata:
        config["metadata"] = metadata

    try:
        yield from _stream_agent(
            agent, messages, config,
            task_type=effective_task_type,
            has_attachments=has_attachments,
        )
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

# Fires when task_type=="coding" but the leg isn't Gemini 3+ (every
# coding-capable leg exhausted, or landed on Gemini 2.5's write-only tier) —
# CodeExecutionToolMiddleware only adds code_execution on Gemini 3+ legs (see
# this module's Chat-7/Chat-R2 sections). Not an error — the model still
# answered, it just couldn't run the code it wrote.
_CODE_EXECUTION_GAP_TEXT = (
    "Code execution wasn't available for this response — the model wrote "
    "code but couldn't run it. The code below is unexecuted."
)


_TOOL_QUERY_ARG_KEYS = {
    # tc["args"] key holding the actual query text, per chat_tools.py's real
    # per-tool parameter name (web_search(query: str)) — kept as a dict since
    # a future tool's arg name isn't guaranteed to match.
    "web_search": "query",
}


def _stream_agent(
    agent, messages: list[dict], config: dict, *,
    task_type: str | None = None,
    has_attachments: bool = False,
):
    seen_tool_call_ids: set[str] = set()
    thinking_gap_sent = False
    if has_attachments:
        yield {"type": "status", "text": "Reading attachment…"}
    code_execution_gap_sent = False

    # Chat-R10d — explicit ordering for blocks[] reconstruction downstream
    # (chat_service.py folds thinking/tool_call/text runs using these).
    # seq is a flat per-event counter across the whole turn (excludes the
    # three one-shot gap-note events, which stay untouched/exempt). block_id
    # groups contiguous same-kind chunks into one logical block, advancing
    # on every kind change — a tool_start/tool_end pair for the SAME call
    # shares one block_id (matched via tool_call_id), confirmed live to
    # arrive as one complete chunk each (not token-streamed), so no
    # cross-chunk args accumulation is needed on the Gemini leg this was
    # verified against; Groq-fallback tool calls that stream args
    # incrementally across multiple chunks would see an incomplete/empty
    # query on this first-sight extraction — a soft degrade (query=None),
    # not a crash, same tradeoff class as Chat-7's Groq code_execution gap.
    _seq = 0
    _block_id = -1
    _last_kind: str | None = None
    _tool_call_blocks: dict[str, int] = {}

    def _emit(kind: str, event: dict, tool_call_id: str | None = None) -> dict:
        nonlocal _seq, _block_id, _last_kind
        _seq += 1
        if tool_call_id is not None and tool_call_id in _tool_call_blocks:
            bid = _tool_call_blocks[tool_call_id]
        elif kind == _last_kind and kind != "tool_call":
            bid = _block_id
        else:
            _block_id += 1
            bid = _block_id
            if tool_call_id is not None:
                _tool_call_blocks[tool_call_id] = bid
        _last_kind = kind
        event["seq"] = _seq
        event["block_id"] = bid
        return event

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
        model_name = meta.get("ls_model_name") or ""
        if not thinking_gap_sent and _is_gemini_3_plus(model_name):
            thinking_gap_sent = True
            yield {"type": "thinking_gap", "text": _THINKING_GAP_TEXT}
        if (
            task_type == "coding" and not code_execution_gap_sent
            and model_name and not _is_gemini_3_plus(model_name)
        ):
            code_execution_gap_sent = True
            yield {"type": "code_execution_gap", "text": _CODE_EXECUTION_GAP_TEXT}

        tool_call_chunks = getattr(msg_chunk, "tool_call_chunks", None)
        if tool_call_chunks:
            for tc in tool_call_chunks:
                tc_id = tc.get("id")
                name  = tc.get("name")
                if name and tc_id and tc_id not in seen_tool_call_ids:
                    seen_tool_call_ids.add(tc_id)
                    query = None
                    try:
                        args = json.loads(tc.get("args") or "{}")
                        query = args.get(_TOOL_QUERY_ARG_KEYS.get(name, ""))
                    except (json.JSONDecodeError, TypeError, AttributeError):
                        pass
                    status_text = {
                        "web_search": "Searching…",
                    }.get(name, f"Running {name}…")
                    yield _emit(
                        "tool_call", {"type": "tool_start", "tool": name, "query": query, "status_text": status_text},
                        tool_call_id=tc_id,
                    )

        if type(msg_chunk).__name__ == "ToolMessage":
            yield _emit(
                "tool_call", {
                    "type":    "tool_end",
                    "tool":    getattr(msg_chunk, "name", None),
                    "sources": getattr(msg_chunk, "artifact", None) or [],
                    "status_text": "Reviewing results…",
                },
                tool_call_id=getattr(msg_chunk, "tool_call_id", None),
            )
            continue

        for kind, text, meta in _split_content_chunks(getattr(msg_chunk, "content", "")):
            event = {"type": kind, "text": text}
            if meta:
                event.update(meta)
            yield _emit(kind, event)
