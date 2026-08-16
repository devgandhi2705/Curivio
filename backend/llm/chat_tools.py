"""
Model-invoked retrieval tools for chat_agent.py's LangGraph agent.

Both wrap EXISTING retrieval/research code — this module only adapts their
call/return shape into LangChain @tool functions the model can invoke on its
own turn-by-turn, replacing the old backend-orchestrated mode-flag pre-fetch
(chat_modes_service.prepare_mode_context, still used unchanged by the sync
chat() path; stream_research_progress, the per-stage-status generator
chat_stream used to call for deep_research, was confirmed genuinely orphaned
after Chat-4.1 and deleted in Chat-4.2 — see deep_research_service.py).

web_search reuses web_search_reasoning_service.fetch_reasoned_results() —
the same reasoning-augmented Tavily search chat used before. deep_research
reuses deep_research_service.run_deep_research() as one opaque callable —
its stages 4-6 (extract_viewpoints/generate/persist) stay an unchanged linear
chain; stages 1-3 now run as a bounded plan->act->replan subgraph inside
deep_research_service.py (Chat-4.2) — opaque from here either way.

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
deep_research   LangChain tool — multi-source structured research report
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
        reasoning = fetch_reasoned_results(query, meta=meta)
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

    content = format_reasoning_search_note(reasoning)
    artifact = [
        {"title": a.get("title", "").strip(), "url": a.get("url", "")}
        for a in articles if a.get("url")
    ]
    _log_tool_call("chat_web_search", "web_search", query, t0,
                   output=content, success=True, error=None, meta=meta)
    return content, artifact


@tool(response_format="content_and_artifact")
def deep_research(topic: str, config: RunnableConfig) -> tuple[str, list[dict]]:
    """
    Run a comprehensive multi-source research pipeline on one topic: expands
    search angles, gathers and ranks sources, extracts competing viewpoints,
    and synthesizes findings, tensions, and open questions. Slower than
    web_search — use for genuine deep-dive / analysis requests, not quick
    fact lookups.
    """
    from ..services.chat_modes_service import format_research_note
    from ..services.deep_research_service import run_deep_research

    meta = _tool_meta(config)
    t0 = time.monotonic()
    try:
        result = run_deep_research(topic, meta=meta)
    except Exception as exc:
        _log_tool_call("chat_deep_research", "deep_research", topic, t0,
                       output="", success=False, error=exc, meta=meta)
        raise

    if not result:
        content = "[DEEP RESEARCH]: No research data available for this topic."
        _log_tool_call("chat_deep_research", "deep_research", topic, t0,
                       output=content, success=True, error=None, meta=meta)
        return content, []

    content = format_research_note(result)
    # ponytail: url-only — run_deep_research()'s public contract exposes only
    # result["sources"] (urls, no titles); per-article titles live in the
    # pipeline's internal workflow state, out of reach without touching its
    # internals (Chat-4.2 scope). Upgrade when the subgraph restructure lands.
    artifact = [{"title": "", "url": u} for u in result.get("sources", [])]
    _log_tool_call("chat_deep_research", "deep_research", topic, t0,
                   output=content, success=True, error=None, meta=meta)
    return content, artifact
