"""
LangChain callback handler that writes one row per LLM call (success or
failure) to llm_call_log. Attached by default inside get_chat_model()/
get_structured_chat_model() (see model_provider.py) — callers don't attach
anything themselves.

Callers pass call_type/user_id/project_id/day_ref through LangChain's standard
config={"metadata": {...}} on invoke(); this handler reads them off the
on_chat_model_start `metadata` kwarg — no separate ID/metadata plumbing.

retry_count comes from LangChain's own retry tagging (Runnable.with_retry()
tags each retry attempt "retry:attempt:N" for N>=2, all sharing one
parent_run_id) — not a hand-rolled counter.
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
        content = message.content if message is not None else (getattr(gen, "text", "") if gen else "")
        usage = (getattr(message, "usage_metadata", None) or {}) if message is not None else {}
        model_used = message.response_metadata.get("model_name") if message is not None else None
        self._write_row(
            run_id=run_id,
            start=start,
            output=content if isinstance(content, str) else str(content),
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
        try:
            with get_connection() as conn:
                conn.execute(
                    """INSERT INTO llm_call_log (
                        run_id, parent_run_id, timestamp_start, timestamp_end, latency_ms,
                        provider, model_requested, model_used, call_type,
                        user_id, project_id, day_ref,
                        input, output, input_tokens, output_tokens, total_tokens,
                        success, error_type, error_message, retry_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(run_id), start["parent_run_id"], start["timestamp_start"], timestamp_end, latency_ms,
                        start["provider"], start["model_requested"], model_used, start["call_type"],
                        start["user_id"], start["project_id"], start["day_ref"],
                        start["input"], output, input_tokens, output_tokens, total_tokens,
                        int(success), error_type, error_message, retry_count,
                    ),
                )
        except Exception:
            logger.error("[llm_call_logger] failed to write log row for run_id=%s", run_id, exc_info=True)
