"""
LangChain callback handler that writes one row per LLM call (success or
failure) to llm_call_log. Attached by default inside get_chat_model()/
get_structured_chat_model() (see model_provider.py) — callers don't attach
anything themselves.

Callers pass call_type/user_id/project_id/day_ref/trace_id/agent_name/
step_index/surface/is_test through LangChain's standard config={"metadata": {...}}
on invoke(); this handler reads them off the on_chat_model_start `metadata`
kwarg — no separate ID/metadata plumbing.

retry_count comes from LangChain's own retry tagging (Runnable.with_retry()
tags each retry attempt "retry:attempt:N" for N>=2, all sharing one
parent_run_id) — not a hand-rolled counter.

write_call_row() below is also the generic, non-callback insert path shared
by code that logs to llm_call_log without going through a LangChain callback
at all (chat tool calls, explain/translate/read-aloud) — same 27-column
shape LLMCallLogger writes, one INSERT, reused rather than duplicated.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult

from ..utils.db import get_connection

logger = logging.getLogger(__name__)

_RETRY_TAG_RE = re.compile(r"^retry:attempt:(\d+)$")
_PROVIDER_MAP = {"google_genai": "gemini", "groq": "groq"}


def _retry_count(tags: list[str] | None) -> int:
    for tag in tags or []:
        m = _RETRY_TAG_RE.match(tag)
        if m:
            return int(m.group(1)) - 1
    return 0


def write_call_row(
    *,
    run_id: str,
    parent_run_id: str | None,
    timestamp_start: str,
    timestamp_end: str,
    latency_ms: int,
    provider: str,
    model_requested: str | None = None,
    model_used: str | None = None,
    call_type: str | None = None,
    user_id: str | None = None,
    project_id: str | None = None,
    day_ref: int | None = None,
    input_text: str = "",
    output: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    success: bool = True,
    error_type: str | None = None,
    error_message: str | None = None,
    retry_count: int = 0,
    created_at: str | None = None,
    trace_id: str | None = None,
    agent_name: str | None = None,
    step_index: int | None = None,
    surface: str | None = None,
    is_test: bool = False,
    target_language: str | None = None,
) -> None:
    """Single INSERT into llm_call_log — every column, including the Phase-3
    (trace_id/agent_name/step_index/surface), Phase-B1 (is_test), and
    Phase-B2 (target_language, translate-only) additions.

    created_at defaults to timestamp_end when omitted, so every writer emits
    the same ISO+offset format the timestamp_start/timestamp_end columns use
    instead of SQLite's CURRENT_TIMESTAMP default (space-separated, no zone).

    Never raises: a logging failure must not break the call it's logging.
    """
    if created_at is None:
        created_at = timestamp_end
    try:
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO llm_call_log (
                    run_id, parent_run_id, timestamp_start, timestamp_end, latency_ms,
                    provider, model_requested, model_used, call_type,
                    user_id, project_id, day_ref,
                    input, output, input_tokens, output_tokens, total_tokens,
                    success, error_type, error_message, retry_count, created_at,
                    trace_id, agent_name, step_index, surface, is_test, target_language
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id, parent_run_id, timestamp_start, timestamp_end, latency_ms,
                    provider, model_requested, model_used, call_type,
                    user_id, project_id, day_ref,
                    input_text, output, input_tokens, output_tokens, total_tokens,
                    int(success), error_type, error_message, retry_count, created_at,
                    trace_id, agent_name, step_index, surface, int(is_test), target_language,
                ),
            )
    except Exception:
        logger.error("[call_logger] failed to write log row for run_id=%s", run_id, exc_info=True)


class LLMCallLogger(BaseCallbackHandler):
    """One row per LLM call in llm_call_log, keyed by LangChain's own run_id."""

    def __init__(self) -> None:
        self._starts: dict[UUID, dict[str, Any]] = {}

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        meta = metadata or {}
        flat = [m for batch in messages for m in batch]
        self._starts[run_id] = {
            "parent_run_id": str(parent_run_id) if parent_run_id else None,
            "timestamp_start": datetime.now(timezone.utc).isoformat(),
            "t0": time.monotonic(),
            "provider": _PROVIDER_MAP.get(meta.get("ls_provider"), meta.get("ls_provider")),
            "model_requested": meta.get("ls_model_name"),
            "call_type": meta.get("call_type"),
            "user_id": meta.get("user_id"),
            "project_id": meta.get("project_id"),
            "day_ref": meta.get("day_ref"),
            "input": "\n".join(f"{m.type}: {m.content}" for m in flat),
            "trace_id": meta.get("trace_id"),
            "agent_name": meta.get("agent_name"),
            "step_index": meta.get("step_index"),
            "surface": meta.get("surface"),
            "is_test": bool(meta.get("is_test", False)),
        }

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        start = self._starts.pop(run_id, None)
        if start is None:
            return
        gen = response.generations[0][0] if response.generations and response.generations[0] else None
        message = getattr(gen, "message", None)
        usage = (getattr(message, "usage_metadata", None) or {}) if message is not None else {}
        model_used = message.response_metadata.get("model_name") if message is not None else None
        # message.content isn't always a plain string — extended-thinking legs
        # (Claude/Gemini) return a list of content blocks (thinking + text,
        # each carrying provider plumbing like signature/index). The old
        # `str(content)` fallback dumped that whole Python repr into the
        # logged row's output. extract_text() (already used everywhere else
        # in this codebase for exactly this) pulls only the real text parts;
        # lazy import to avoid a circular import (model_provider imports
        # LLMCallLogger from this module at top level).
        from .model_provider import extract_text
        output = extract_text(message) if message is not None else (getattr(gen, "text", "") if gen else "")
        self._write_row(
            run_id=run_id,
            start=start,
            output=output,
            model_used=model_used,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            total_tokens=usage.get("total_tokens"),
            success=True,
            error_type=None,
            error_message=None,
            retry_count=_retry_count(tags),
        )

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        start = self._starts.pop(run_id, None)
        if start is None:
            return
        self._write_row(
            run_id=run_id,
            start=start,
            output=None,
            model_used=None,
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            success=False,
            error_type=type(error).__name__,
            error_message=str(error),
            retry_count=_retry_count(tags),
        )

    def _write_row(
        self,
        *,
        run_id: UUID,
        start: dict[str, Any],
        output: str | None,
        model_used: str | None,
        input_tokens: int | None,
        output_tokens: int | None,
        total_tokens: int | None,
        success: bool,
        error_type: str | None,
        error_message: str | None,
        retry_count: int,
    ) -> None:
        timestamp_end = datetime.now(timezone.utc).isoformat()
        latency_ms = int((time.monotonic() - start["t0"]) * 1000)
        write_call_row(
            run_id=str(run_id),
            parent_run_id=start["parent_run_id"],
            timestamp_start=start["timestamp_start"],
            timestamp_end=timestamp_end,
            latency_ms=latency_ms,
            provider=start["provider"],
            model_requested=start["model_requested"],
            model_used=model_used,
            call_type=start["call_type"],
            user_id=start["user_id"],
            project_id=start["project_id"],
            day_ref=start["day_ref"],
            input_text=start["input"],
            output=output,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            success=success,
            error_type=error_type,
            error_message=error_message,
            retry_count=retry_count,
            created_at=timestamp_end,
            trace_id=start["trace_id"],
            agent_name=start["agent_name"],
            step_index=start["step_index"],
            surface=start["surface"],
            is_test=start["is_test"],
        )
