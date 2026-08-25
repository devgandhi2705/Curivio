"""
Model-invoked retrieval tools for chat_agent.py's LangGraph agent.

This module wraps EXISTING retrieval code — it only adapts its call/return
shape into a LangChain @tool function the model can invoke on its own
turn-by-turn, replacing the old backend-orchestrated mode-flag pre-fetch
(chat_modes_service.prepare_mode_context, still used unchanged by the sync
chat() path).

web_search reuses web_search_reasoning_service.fetch_reasoned_results() —
the same reasoning-augmented Tavily search chat used before.

response_format="content_and_artifact": `content` is what the model reads
(a formatted synthesis-ready note, via the same formatters chat_modes_service
used for its old system-note injection); `artifact` is the raw {title,url}
source list — never shown to the model, read back off the ToolMessage by
chat_agent.ask_chat_stream for the stream's `sources` metadata.

Phase B1 — tool-call logging
-----------------------------
Neither tool went through model_provider.py's LLMCallLogger (that only fires
on chat-model nodes, not tool nodes), so before this phase neither tool ever
wrote a llm_call_log row at all. Both now take a `config: RunnableConfig`
param — LangChain auto-injects this from the graph's invocation config
(the SAME config={"metadata": {...}} chat_agent.ask_chat_stream passes to
agent.stream()) and excludes it from the tool's args_schema, so the model
never sees it as a callable parameter (verified live: args_schema only ever
exposes `query`/`topic`). meta.get("trace_id") is the parent chat turn's
trace_id (chat_service.chat_stream mints it before either LLM call path), so
a tool-call row always nests under its parent turn's group. provider="none":
neither row represents a model completion — call_type distinguishes them
from actual LLM rows.

Public API
----------
web_search      LangChain tool — live/current web search
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from .call_logger import write_call_row


def _tool_meta(config: RunnableConfig | None) -> dict:
    return (config or {}).get("metadata", {}) or {}


def _log_tool_call(
    call_type: str, agent_name: str, input_text: str, t0: float,
    *, output: str, success: bool, error: Exception | None, meta: dict,
) -> None:
    """One row per tool invocation — latency, success/failure, the query sent,
    and the formatted note actually delivered back to the model. Never raises."""
    now = datetime.now(timezone.utc).isoformat()
    write_call_row(
        run_id=uuid4().hex,
        parent_run_id=None,
        timestamp_start=now,
        timestamp_end=now,
        latency_ms=int((time.monotonic() - t0) * 1000),
        provider="none",
        call_type=call_type,
        user_id=meta.get("user_id"),
        input_text=input_text,
        output=output,
        success=success,
        error_type=type(error).__name__ if error else None,
        error_message=str(error) if error else None,
        trace_id=meta.get("trace_id"),
        agent_name=agent_name,
        surface=meta.get("surface", "chat"),
        is_test=bool(meta.get("is_test", False)),
    )


@tool(response_format="content_and_artifact")
def web_search(query: str, config: RunnableConfig) -> tuple[str, list[dict]]:
    """
    Search the live web for current information, news, or facts beyond your
    training data. Use for: recent events, comparisons ("X vs Y"), current
    prices/stats, or any claim that needs up-to-date verification. Do not use
    for topics already fully answerable from the conversation so far.
    """
    from ..services.chat_modes_service import format_reasoning_search_note
    from ..services.web_search_reasoning_service import fetch_reasoned_results

    meta = _tool_meta(config)
    t0 = time.monotonic()
    try:
        # Phase M: meta["complexity"] is the router's real RoutingDecision
        # .complexity for this turn, put on the agent's call metadata by
        # chat_service. It rides the metadata dict that already carries
        # trace_id/user_id/surface, so there is no new plumbing — and it is
        # absent whenever the router failed or wasn't run, which
        # fetch_reasoned_results reads as "use today's fixed 3+3".
        reasoning = fetch_reasoned_results(query, meta=meta, complexity=meta.get("complexity"))
    except Exception as exc:
        _log_tool_call("chat_web_search", "web_search", query, t0,
                       output="", success=False, error=exc, meta=meta)
        raise

    articles = reasoning.get("all_articles", [])
    if not articles:
        content = "[WEB SEARCH]: No results retrieved for this query."
        _log_tool_call("chat_web_search", "web_search", query, t0,
                       output=content, success=True, error=None, meta=meta)
        return content, []

    # Phase E — citation numbering: format_reasoning_search_note() numbers
    # each real source [1], [2], … by enumerating reasoning["supporting"]
    # then reasoning["complicating"], in that order — the model cites those
    # exact numbers inline. artifact (below) is what the frontend resolves
    # [N] against, so artifact[N-1] must be the SAME article the note
    # labelled [N]. Filtering supporting/complicating for a real url ONCE,
    # here, before either is built — rather than only filtering when
    # building artifact (the old shape) — is what guarantees that: a
    # url-less article no longer silently shifts every later number out of
    # alignment between what the model reads and what the frontend can link.
    supporting_cited   = [a for a in reasoning.get("supporting",   []) if a.get("url")]
    complicating_cited = [a for a in reasoning.get("complicating", []) if a.get("url")]
    cited_reasoning = {**reasoning, "supporting": supporting_cited, "complicating": complicating_cited}

    content = format_reasoning_search_note(cited_reasoning)
    artifact = [
        {"title": a.get("title", "").strip(), "url": a.get("url", "")}
        for a in supporting_cited + complicating_cited
    ]
    _log_tool_call("chat_web_search", "web_search", query, t0,
                   output=content, success=True, error=None, meta=meta)
    return content, artifact
