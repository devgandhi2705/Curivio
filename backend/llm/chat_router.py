"""
Chat-R4 — LLM-based turn router: classifies one chat message into a task_type
(model_priority.py) so chat_agent.py can pick a model-priority chain suited to
the turn, plus a tool bias for chat_agent.build_mode_hint's shaped_query.

Runs ONLY when chat_mode == "normal" (chat_service.chat_stream) — an explicit
web_search/deep_research toggle always wins outright, matching R1's proven
10/10 explicit-toggle hit rate; the router targets the "normal"-mode gap R1
measured at 2/10. Never consulted for attachment turns (vision hard gate,
Chat-5) — chat_service checks has_attachments before calling this at all.

Classification is non-fatal: any failure (every pooled leg exhausted) returns
None, and the caller keeps today's default behavior (task_type=None, no
hint) — an unavailable router must never break a chat turn.

Public API
----------
classify_message(message, metadata=None) -> RoutingDecision | None
map_to_task_type(decision) -> str
"""
from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

from .model_provider import get_structured_chat_model_for_task

logger = logging.getLogger(__name__)

_TASK_TYPE = "routing"

_SYSTEM_PROMPT = (
    "Classify this chat message for routing purposes. Decide whether it needs "
    "a live-data tool, how complex the answer is, whether it requires writing "
    "AND executing code (not just explaining code), and — if a tool is needed "
    "— a clean, search-ready rephrasing of the request."
)


class RoutingDecision(BaseModel):
    needs_tool: bool = Field(description="True if answering requires live web data or deep multi-source research")
    tool_name: Literal["web_search", "deep_research", "none"] = Field(description="Which tool to bias toward, or 'none'")
    complexity: Literal["simple", "complex"] = Field(description="'simple' = direct factual/conversational answer; 'complex' = multi-step reasoning or synthesis")
    requires_code_execution: bool = Field(description="True only if the answer requires actually running code, not just writing/explaining it")
    shaped_query: str = Field(description="Clean, search-engine-ready rephrasing of the message; empty string if needs_tool is False")


_classifier = None


def _get_classifier():
    global _classifier
    if _classifier is None:
        _classifier = get_structured_chat_model_for_task(RoutingDecision, _TASK_TYPE)
    return _classifier


def classify_message(message: str, metadata: dict | None = None) -> RoutingDecision | None:
    """Classify one user message. Returns None (never raises) if every pooled leg fails."""
    try:
        config = {"metadata": {"call_type": "chat_router_classify", **(metadata or {})}}
        return _get_classifier().invoke(
            [{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": message}],
            config=config,
        )
    except Exception:
        logger.warning("[chat_router] classification failed (non-fatal)", exc_info=True)
        return None


def map_to_task_type(decision: RoutingDecision) -> str:
    """
    requires_code_execution -> coding; else needs_tool -> tool_use; else
    complexity=="complex" -> complex_reasoning; else simple_qa.

    requires_code_execution checked FIRST (Chat-R5a — was needs_tool first,
    silently dropping code execution whenever both were True): tool binding
    (web_search/deep_research) is decided by chat_mode at the chat_service
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
