"""
Centralized model registry — single source of truth for model metadata.

Add a new model here and all budget logic inherits it automatically.
No changes required in grok_service, project_service, or any caller.

Supported providers: groq, openai, anthropic, google.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ModelConfig:
    model_name: str
    provider: str                           # "groq" | "openai" | "anthropic" | "google"
    context_window: int                     # maximum context window (tokens)
    safe_utilization: float                 # fraction of context to use safely (0.0–1.0)
    output_reserve: int                     # tokens reserved for model output
    safety_buffer: int                      # extra safety margin on top of safe_utilization
    # Per-tier rate / request limits — provider-specific.
    # Groq example: {"on_demand": {"tpm": 12000}, "dev": {"tpm": 500000}}
    tier_limits: dict[str, dict] = field(default_factory=dict)

    # ── Derived budget properties ─────────────────────────────────────────────

    @property
    def safe_context_window(self) -> int:
        """Total tokens safely available for input + output combined."""
        return int(self.context_window * self.safe_utilization) - self.safety_buffer

    @property
    def prompt_budget(self) -> int:
        """Maximum tokens available for the input prompt."""
        return self.safe_context_window - self.output_reserve

    @property
    def output_budget(self) -> int:
        """Tokens reserved for the model's output (completion)."""
        return self.output_reserve


# ── Registry ──────────────────────────────────────────────────────────────────

_REGISTRY: dict[str, ModelConfig] = {

    # ── Groq ──────────────────────────────────────────────────────────────────
    # Context windows are large, but the on_demand (free) tier caps each
    # individual request to a hard TPM limit — this is what causes the 413.

    "llama-3.3-70b-versatile": ModelConfig(
        model_name       = "llama-3.3-70b-versatile",
        provider         = "groq",
        context_window   = 128_000,
        safe_utilization = 0.80,
        output_reserve   = 8_000,
        safety_buffer    = 2_000,
        tier_limits      = {
            "on_demand": {"tpm": 12_000},   # free tier — hard per-request cap
            "dev":       {"tpm": 500_000},
        },
    ),
    "llama-3.1-70b-versatile": ModelConfig(
        model_name       = "llama-3.1-70b-versatile",
        provider         = "groq",
        context_window   = 128_000,
        safe_utilization = 0.80,
        output_reserve   = 8_000,
        safety_buffer    = 2_000,
        tier_limits      = {
            "on_demand": {"tpm": 12_000},
            "dev":       {"tpm": 500_000},
        },
    ),
    "llama-3.1-8b-instant": ModelConfig(
        model_name       = "llama-3.1-8b-instant",
        provider         = "groq",
        context_window   = 128_000,
        safe_utilization = 0.80,
        output_reserve   = 4_000,
        safety_buffer    = 2_000,
        tier_limits      = {
            "on_demand": {"tpm": 20_000},
            "dev":       {"tpm": 500_000},
        },
    ),
    "gemma2-9b-it": ModelConfig(
        model_name       = "gemma2-9b-it",
        provider         = "groq",
        context_window   = 8_192,
        safe_utilization = 0.80,
        output_reserve   = 2_000,
        safety_buffer    = 500,
        tier_limits      = {
            "on_demand": {"tpm": 15_000},
            "dev":       {"tpm": 500_000},
        },
    ),

    # ── OpenAI ────────────────────────────────────────────────────────────────
    "gpt-4o": ModelConfig(
        model_name       = "gpt-4o",
        provider         = "openai",
        context_window   = 128_000,
        safe_utilization = 0.80,
        output_reserve   = 8_000,
        safety_buffer    = 2_000,
    ),
    "gpt-4o-mini": ModelConfig(
        model_name       = "gpt-4o-mini",
        provider         = "openai",
        context_window   = 128_000,
        safe_utilization = 0.80,
        output_reserve   = 4_000,
        safety_buffer    = 2_000,
    ),
    "o3-mini": ModelConfig(
        model_name       = "o3-mini",
        provider         = "openai",
        context_window   = 200_000,
        safe_utilization = 0.80,
        output_reserve   = 8_000,
        safety_buffer    = 2_000,
    ),

    # ── Anthropic ─────────────────────────────────────────────────────────────
    "claude-opus-4-8": ModelConfig(
        model_name       = "claude-opus-4-8",
        provider         = "anthropic",
        context_window   = 200_000,
        safe_utilization = 0.80,
        output_reserve   = 8_000,
        safety_buffer    = 2_000,
    ),
    "claude-sonnet-4-6": ModelConfig(
        model_name       = "claude-sonnet-4-6",
        provider         = "anthropic",
        context_window   = 200_000,
        safe_utilization = 0.80,
        output_reserve   = 8_000,
        safety_buffer    = 2_000,
    ),
    "claude-haiku-4-5-20251001": ModelConfig(
        model_name       = "claude-haiku-4-5-20251001",
        provider         = "anthropic",
        context_window   = 200_000,
        safe_utilization = 0.80,
        output_reserve   = 4_000,
        safety_buffer    = 2_000,
    ),

    # ── Google ────────────────────────────────────────────────────────────────
    "gemini-1.5-pro": ModelConfig(
        model_name       = "gemini-1.5-pro",
        provider         = "google",
        context_window   = 1_000_000,
        safe_utilization = 0.80,
        output_reserve   = 8_000,
        safety_buffer    = 2_000,
    ),
    "gemini-1.5-flash": ModelConfig(
        model_name       = "gemini-1.5-flash",
        provider         = "google",
        context_window   = 1_000_000,
        safe_utilization = 0.80,
        output_reserve   = 4_000,
        safety_buffer    = 2_000,
    ),
    "gemini-2.0-flash": ModelConfig(
        model_name       = "gemini-2.0-flash",
        provider         = "google",
        context_window   = 1_000_000,
        safe_utilization = 0.80,
        output_reserve   = 4_000,
        safety_buffer    = 2_000,
    ),
}

# Safe fallback for unknown models (conservative limits)
_DEFAULT_CONFIG = ModelConfig(
    model_name       = "unknown",
    provider         = "unknown",
    context_window   = 32_000,
    safe_utilization = 0.70,
    output_reserve   = 4_000,
    safety_buffer    = 2_000,
)


# ── Public helpers ────────────────────────────────────────────────────────────

def get_model_config(model_name: str) -> ModelConfig:
    """Return ModelConfig for model_name. Falls back to conservative defaults."""
    cfg = _REGISTRY.get(model_name)
    if cfg is None:
        logger.warning("[model_registry] Unknown model '%s' — using default config", model_name)
        return _DEFAULT_CONFIG
    return cfg


def get_prompt_budget(model_name: str) -> int:
    """Maximum input tokens for this model's safe prompt."""
    return get_model_config(model_name).prompt_budget


def get_output_budget(model_name: str) -> int:
    """Tokens reserved for this model's output."""
    return get_model_config(model_name).output_budget


def get_safe_context_window(model_name: str) -> int:
    """Total safe tokens (input + output) for this model."""
    return get_model_config(model_name).safe_context_window
