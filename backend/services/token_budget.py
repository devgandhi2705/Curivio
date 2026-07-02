"""
Token estimation, prompt budget reporting, and preflight evaluation.

Accuracy: approximate (chars / 4 heuristic + per-message overhead).

BudgetReport  — diagnostics only, never enforces.
BudgetPlan    — authoritative go/no-go status; OVER_LIMIT triggers repair or raise.

Provider-aware budgeting (Phase 9.2B)
--------------------------------------
evaluate() accepts an optional provider_tier argument.  When provided the
effective budget is MIN(model_context_budget, provider_tpm × safety_factor).
Groq free-tier models auto-default to "on_demand" (12K TPM) via the registry;
non-Groq models are unaffected (no tier limits registered).

Environment flags
-----------------
ENABLE_PROMPT_BUDGET_DEBUG=true   Full section-level reports logged at DEBUG.
ENABLE_PROMPT_BUDGET_DEBUG=false  (default) Compact summary only, at INFO.
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from enum import Enum

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

# Measured from grok_service.ask_grok(): system message (~15 tok) + 2×message
# overhead (4 tok each) = 23 tokens added around the assembled prompt.
# Used as reserved_system_budget in provider-aware BudgetPlan instances.
_FEED_SYSTEM_RESERVE: int = 23


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


# ── Active budget controller ──────────────────────────────────────────────────


class BudgetStatus(str, Enum):
    """Authoritative go/no-go signal for a pending LLM request."""
    SAFE       = "SAFE"        # < 85% utilization — proceed
    NEAR_LIMIT = "NEAR_LIMIT"  # 85–99% utilization — log warning
    OVER_LIMIT = "OVER_LIMIT"  # ≥ 100% — must repair or raise before sending


@dataclass
class BudgetPlan:
    """
    Single authoritative budget status object for one LLM request.

    Existing fields (all callers must still provide these positionally):
      model_name             — model identifier from the registry
      context_limit          — model's full context window in tokens
      reserved_output        — tokens reserved for model output
      safety_margin          — safety buffer subtracted from budget
      available_input_budget — effective budget (= effective_limit; provider-capped
                               when evaluate() is called with a provider_tier)
      current_prompt_tokens  — estimated tokens for the pending prompt
      overflow_tokens        — max(0, current_prompt_tokens - available_input_budget)
      status                 — SAFE / NEAR_LIMIT / OVER_LIMIT

    Provider-aware fields (Phase 9.2B, have defaults for backward compat):
      provider_name          — provider string from registry ("groq", "openai", …)
      provider_tier          — active tier ("on_demand", "dev", "" if none)
      model_limit            — context-window-only prompt budget (ignores provider)
      provider_limit         — floor(tier_tpm × safety_factor), 0 = no tier limit
      effective_limit        — MIN(model_limit, provider_limit or model_limit)
      reserved_output_budget — tokens reserved for model output (= reserved_output)
      reserved_system_budget — system message + per-message overhead (feed path ≈ 23)
    """
    # ── Core fields — no defaults, must be supplied ────────────────────────────
    model_name:             str
    context_limit:          int
    reserved_output:        int
    safety_margin:          int
    available_input_budget: int
    current_prompt_tokens:  int
    overflow_tokens:        int
    status:                 BudgetStatus
    # ── Provider-aware fields — defaults preserve backward compat ─────────────
    provider_name:          str = ""
    provider_tier:          str = ""
    model_limit:            int = 0   # model context budget before provider cap
    provider_limit:         int = 0   # provider TPM safe budget (0 = no limit)
    effective_limit:        int = 0   # = min(model_limit, provider_limit or model_limit)
    reserved_output_budget: int = 0   # = reserved_output (explicit alias)
    reserved_system_budget: int = 0   # system + message overhead (feed: 23 tok)


def evaluate(
    prompt_tokens: int,
    model_name: str,
    provider_tier: str | None = None,
) -> BudgetPlan:
    """
    Build a BudgetPlan for a given token count and model.

    Does NOT modify or truncate anything — purely evaluates whether
    the prompt fits and returns a structured status object.

    prompt_tokens  — estimated tokens for the prompt (use estimate_total_request)
    model_name     — model identifier from the registry
    provider_tier  — optional tier name (e.g. "on_demand").  When provided,
                     effective budget = MIN(model_budget, tpm × safety_factor).
                     When None, model context budget only (backward compat).
                     Pass the model's default_provider_tier for production checks.
    """
    from .model_registry import get_model_config, PROVIDER_SAFETY_FACTOR
    cfg        = get_model_config(model_name)
    model_bud  = cfg.prompt_budget

    # Resolve provider budget when a tier is specified
    provider_bud = 0
    active_tier  = provider_tier or ""
    if active_tier:
        tier_cfg = cfg.tier_limits.get(active_tier, {})
        tpm = tier_cfg.get("tpm")
        if tpm is not None:
            provider_bud = int(tpm * PROVIDER_SAFETY_FACTOR)

    # Effective = min(model, provider) when provider limit exists
    if provider_bud > 0:
        available = min(model_bud, provider_bud)
    else:
        available = model_bud

    overflow = max(0, prompt_tokens - available)
    util     = (prompt_tokens / available * 100) if available > 0 else 0.0

    if overflow > 0:
        status = BudgetStatus.OVER_LIMIT
    elif util >= 85.0:
        status = BudgetStatus.NEAR_LIMIT
    else:
        status = BudgetStatus.SAFE

    return BudgetPlan(
        model_name             = model_name,
        context_limit          = cfg.context_window,
        reserved_output        = cfg.output_reserve,
        safety_margin          = cfg.safety_buffer,
        available_input_budget = available,
        current_prompt_tokens  = prompt_tokens,
        overflow_tokens        = overflow,
        status                 = status,
        # Provider-aware fields (Phase 9.2B)
        provider_name          = cfg.provider,
        provider_tier          = active_tier,
        model_limit            = model_bud,
        provider_limit         = provider_bud,
        effective_limit        = available,
        reserved_output_budget = cfg.output_reserve,
        reserved_system_budget = _FEED_SYSTEM_RESERVE if active_tier else 0,
    )


def log_budget_plan(plan: BudgetPlan, logger_inst: logging.Logger | None = None) -> None:
    """
    Log a BudgetPlan as a compact one-liner; warn on NEAR_LIMIT / OVER_LIMIT.

    When provider_tier is set, the log includes model vs provider limits so the
    effective ceiling is always visible.
    """
    _log = logger_inst or logger
    util = (plan.current_prompt_tokens / plan.available_input_budget * 100) if plan.available_input_budget > 0 else 0.0

    if plan.provider_tier:
        # Provider-aware log: show both model and provider limits
        _log.info(
            "[budget] model=%-28s  provider=%s/%s  model_limit=%d  provider_limit=%d  "
            "effective=%d  prompt=%d  util=%.1f%%  status=%s",
            plan.model_name,
            plan.provider_name,
            plan.provider_tier,
            plan.model_limit,
            plan.provider_limit,
            plan.effective_limit,
            plan.current_prompt_tokens,
            util,
            plan.status,
        )
    else:
        _log.info(
            "[budget] model=%-30s  prompt=%6d  available=%7d  util=%5.1f%%  status=%s",
            plan.model_name,
            plan.current_prompt_tokens,
            plan.available_input_budget,
            util,
            plan.status,
        )

    if plan.status == BudgetStatus.OVER_LIMIT:
        _log.warning(
            "[budget] OVER BUDGET: +%d tokens (%d > %d effective)",
            plan.overflow_tokens, plan.current_prompt_tokens, plan.available_input_budget,
        )
    elif plan.status == BudgetStatus.NEAR_LIMIT:
        _log.warning("[budget] NEAR LIMIT: %.1f%% of effective prompt budget consumed", util)
