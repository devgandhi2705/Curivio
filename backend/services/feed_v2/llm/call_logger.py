"""
Feed v2 call logger — a COPY of backend/llm/call_logger.py's write path (never an
import; feed_v2 must not reach into backend.llm.*). Writes one row per LLM call to
the SAME llm_call_log table, same columns, same success/error-row and retry_count
semantics. ADDS the four Phase-3 columns (trace_id, agent_name, step_index,
surface) read from call metadata.

write_call_row(...) is the single write path — the SDK-direct v2 provider calls it
per attempt. (Phase 5 removed the legacy LangChain BaseCallbackHandler variant:
the v2 provider is SDK-direct, so that callback never fired — write_call_row was
already the only live path, confirmed dead across two Phase 4b reports.)
"""
from __future__ import annotations

import logging

from ..db import get_connection

logger = logging.getLogger(__name__)


def write_call_row(
    *,
    run_id: str,
    parent_run_id: str | None,
    timestamp_start: str,
    timestamp_end: str,
    latency_ms: int,
    provider: str | None,
    model_requested: str | None,
    model_used: str | None,
    call_type: str | None,
    user_id: str | None,
    project_id: str | None,
    day_ref: int | None,
    input_text: str,
    output: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    total_tokens: int | None,
    success: bool,
    error_type: str | None,
    error_message: str | None,
    retry_count: int,
    trace_id: str | None,
    agent_name: str | None,
    step_index: int | None,
    surface: str | None,
    is_test: bool = False,
) -> None:
    """Single INSERT into llm_call_log — 21 legacy columns + 4 Phase-3 columns +
    Phase-B1's is_test. Never raises: a logging failure must not break an LLM
    call (copied from legacy _write_row's swallow-and-log behaviour).

    created_at is written explicitly as timestamp_end (same ISO+offset format
    timestamp_start/timestamp_end already use) instead of SQLite's
    CURRENT_TIMESTAMP default — Phase B1: keeps this table's created_at format
    consistent across every writer, legacy and v2 alike."""
    try:
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO llm_call_log (
                    run_id, parent_run_id, timestamp_start, timestamp_end, latency_ms,
                    provider, model_requested, model_used, call_type,
                    user_id, project_id, day_ref,
                    input, output, input_tokens, output_tokens, total_tokens,
                    success, error_type, error_message, retry_count, created_at,
                    trace_id, agent_name, step_index, surface, is_test
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id, parent_run_id, timestamp_start, timestamp_end, latency_ms,
                    provider, model_requested, model_used, call_type,
                    user_id, project_id, day_ref,
                    input_text, output, input_tokens, output_tokens, total_tokens,
                    int(success), error_type, error_message, retry_count, timestamp_end,
                    trace_id, agent_name, step_index, surface, int(is_test),
                ),
            )
    except Exception:
        logger.error("[feed_v2.call_logger] failed to write log row for run_id=%s", run_id, exc_info=True)
