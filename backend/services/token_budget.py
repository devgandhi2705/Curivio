"""
Token estimation and prompt budget reporting.

Accuracy: approximate (chars / 4 heuristic + per-message overhead).
Purpose:  visibility and diagnostics only — never enforces or modifies prompts.

Environment flags
-----------------
ENABLE_PROMPT_BUDGET_DEBUG=true   Full section-level reports logged at DEBUG.
ENABLE_PROMPT_BUDGET_DEBUG=false  (default) Compact summary only, at INFO.
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

# Task 9: debug flag — full reports only when explicitly enabled
_DEBUG: bool = os.getenv("ENABLE_PROMPT_BUDGET_DEBUG", "false").lower() in ("true", "1", "yes")

# Chars-per-token heuristic (English prose ≈ 4 chars/token)
_CHARS_PER_TOKEN: int = 4

# Per-message overhead in the OpenAI messages format (role field + framing)
_MESSAGE_OVERHEAD: int = 4

# System message used by ask_grok() — counted toward prompt token estimate
_ASK_GROK_SYSTEM_MSG: str = (
    "You are an AI-powered personalized learning and research assistant."
)


# ── Task 2 — Estimation ───────────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """
    Approximate token count for a text string.
    Heuristic: 1 token ≈ 4 characters (reliable for English prose).
    """
    if not text:
        return 0
    return max(1, len(text) // _CHARS_PER_TOKEN)


def estimate_messages(messages: list[dict]) -> int:
    """
    Approximate total tokens for an OpenAI-format messages list.
    Each message adds per-message overhead for role + framing.
    """
    total = 0
    for msg in messages:
        content = msg.get("content") or ""
        total += estimate_tokens(content) + _MESSAGE_OVERHEAD
    return total


def estimate_prompt_sections(sections: dict[str, str]) -> dict[str, int]:
    """
    Estimate token count for each named section independently.
    Returns {section_name: estimated_token_count}.
    """
    return {name: estimate_tokens(text) for name, text in sections.items()}


def estimate_total_request(
    prompt: str | None = None,
    messages: list[dict] | None = None,
) -> int:
    """
    Estimate input token count for a pending API request.

    prompt:   use for ask_grok()-style calls (single string, wrapped in 2 messages internally).
    messages: use for ask_grok_chat()-style calls (full OpenAI messages list).
    """
    if messages is not None:
        return estimate_messages(messages)
    if prompt is not None:
        # ask_grok wraps the prompt in: system message + user message
        system_tokens = estimate_tokens(_ASK_GROK_SYSTEM_MSG) + _MESSAGE_OVERHEAD
        user_tokens   = estimate_tokens(prompt) + _MESSAGE_OVERHEAD
        return system_tokens + user_tokens
    return 0


# ── Task 3 — Budget Report ────────────────────────────────────────────────────

@dataclass
class BudgetReport:
    """
    Complete token budget snapshot for a single LLM request.
    Built before the request is sent; never modifies the request.
    """
    operation:       str
    model_name:      str
    context_window:  int
    safe_budget:     int            # prompt_budget from ModelConfig
    output_reserve:  int
    prompt_tokens:   int            # estimated input tokens
    remaining_budget: int           # safe_budget - prompt_tokens
    utilization_pct: float          # prompt_tokens / safe_budget * 100
    sections: dict[str, int] = field(default_factory=dict)   # section → tokens
    warnings: list[str]      = field(default_factory=list)


def build_budget_report(
    operation:  str,
    model_name: str,
    prompt:     str | None        = None,
    messages:   list[dict] | None = None,
    sections:   dict[str, str] | None = None,
) -> BudgetReport:
    """
    Build a BudgetReport for a pending LLM request.

    Provide one of:
      prompt    — single string (ask_grok-style)
      messages  — OpenAI messages list (ask_grok_chat-style)
      sections  — named string segments (service-level detail)

    Does not modify, truncate, or block any request.
    """
    from .model_registry import get_model_config  # deferred: avoids circular import at load time

    cfg            = get_model_config(model_name)
    safe_budget    = cfg.prompt_budget
    output_reserve = cfg.output_budget

    # Compute estimated prompt tokens
    if sections is not None:
        prompt_tokens = sum(estimate_tokens(t) for t in sections.values())
        section_counts = estimate_prompt_sections(sections)
    else:
        prompt_tokens  = estimate_total_request(prompt=prompt, messages=messages)
        section_counts = {}

    remaining    = safe_budget - prompt_tokens
    utilization  = (prompt_tokens / safe_budget * 100) if safe_budget > 0 else 0.0

    # ── Generate warnings ─────────────────────────────────────────────────────
    warnings: list[str] = []

    if remaining < 0:
        warnings.append(
            f"OVER SAFE BUDGET: prompt ({prompt_tokens:,} tok) exceeds safe budget "
            f"({safe_budget:,} tok) by {-remaining:,} tokens"
        )
    elif utilization > 85.0:
        warnings.append(
            f"HIGH UTILIZATION: {utilization:.1f}% of safe prompt budget consumed"
        )

    # Groq on_demand tier: hard per-request TPM cap (causes 413 on free accounts)
    on_demand = cfg.tier_limits.get("on_demand", {})
    od_tpm    = on_demand.get("tpm")
    if od_tpm and prompt_tokens > od_tpm:
        warnings.append(
            f"EXCEEDS GROQ ON_DEMAND TIER LIMIT: {prompt_tokens:,} tokens > "
            f"{od_tpm:,} TPM limit (delta: +{prompt_tokens - od_tpm:,} tokens) "
            f"— will fail with HTTP 413 on free tier"
        )

    return BudgetReport(
        operation        = operation,
        model_name       = model_name,
        context_window   = cfg.context_window,
        safe_budget      = safe_budget,
        output_reserve   = output_reserve,
        prompt_tokens    = prompt_tokens,
        remaining_budget = remaining,
        utilization_pct  = utilization,
        sections         = section_counts,
        warnings         = warnings,
    )


# ── Task 4 — Centralized Budget Logger ───────────────────────────────────────

def log_budget_report(
    report:      BudgetReport,
    logger_inst: logging.Logger | None = None,
) -> None:
    """
    Log a BudgetReport.

    Always logs a compact one-line summary at INFO.
    Logs full section breakdown at DEBUG when ENABLE_PROMPT_BUDGET_DEBUG=true.
    Warnings always surface at WARNING level regardless of debug flag.

    Never modifies prompts. Never blocks requests. Diagnostics only.
    """
    _log = logger_inst or logger

    # Compact summary — always logged
    _log.info(
        "[budget] %-38s  model=%-30s  prompt=%6d  remaining=%7d  util=%5.1f%%",
        report.operation,
        report.model_name,
        report.prompt_tokens,
        report.remaining_budget,
        report.utilization_pct,
    )

    # Warnings always surface regardless of debug mode
    for w in report.warnings:
        _log.warning("[budget] ⚠  %s  [op: %s]", w, report.operation)

    # Full section breakdown — only when debug mode enabled
    if _DEBUG:
        section_lines = (
            "\n".join(
                f"    {k:<32}: {v:>7,} tokens"
                for k, v in sorted(report.sections.items(), key=lambda x: -x[1])
            )
            if report.sections
            else "    (no section breakdown available)"
        )
        _log.debug(
            "[budget] FULL REPORT — %s\n"
            "  Model          : %s\n"
            "  Provider       : (see model_registry)\n"
            "  Context Window : %d\n"
            "  Safe Budget    : %d\n"
            "  Prompt Tokens  : %d\n"
            "  Output Reserve : %d\n"
            "  Remaining      : %d\n"
            "  Utilization    : %.1f%%\n"
            "  Sections:\n%s",
            report.operation,
            report.model_name,
            report.context_window,
            report.safe_budget,
            report.prompt_tokens,
            report.output_reserve,
            report.remaining_budget,
            report.utilization_pct,
            section_lines,
        )
