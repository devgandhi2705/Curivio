"""
Task-based model priority registry (Chat-R3) — config-driven, no routing logic.

Maps each task type to an ordered list of (provider, model_name) legs. This is
data + a lookup function only: nothing in the codebase consumes it for live
routing yet (chat_agent.py and every Feed call site are untouched) — R4 wires
task-based selection into live chat turns using get_model_priority_list() and
model_provider.build_pooled_legs()/get_chat_model_for_task().

Ordering per task type is driven by real, already-measured constraints in this
codebase, not guesses:
  - Gemini free tier: 20 requests/day per API key per model (see
    docs/chat-reliability/chat-r2-fix.md) — a hard, easily-exhausted ceiling
    on any high-volume task.
  - Groq on-demand tier TPM ceilings (backend/services/model_registry.py):
    llama-3.1-8b-instant = 20,000 tpm (fastest/cheapest), llama-3.3-70b-versatile
    = 12,000 tpm.
  - code_execution is a Gemini-3+-only capability (chat_agent.py's
    CodeExecutionToolMiddleware, Chat-7/Chat-R2) — coding puts the Gemini 3+
    leg first so code execution is available on the first attempt.
  - Groq has no vision model configured anywhere in this stack
    (model_provider.upload_attachment's docstring) — vision is Gemini-only.
"""
from __future__ import annotations

from ..config import (
    GEMINI_FALLBACK_MODEL,
    GEMINI_LITE_MODEL,
    GEMINI_MODEL,
    GROQ_FALLBACK_MODEL,
    GROQ_FAST_MODEL,
)

TASK_MODEL_PRIORITY: dict[str, list[tuple[str, str]]] = {
    # Every chat turn hits this first — highest volume of any task type.
    # Groq's fastest/cheapest on-demand model (20k tpm) goes first so Gemini's
    # scarce 20-req/day/key/model quota isn't burned on internal classification;
    # Gemini's lightweight tier is the fallback only.
    "routing": [
        ("groq", GROQ_FAST_MODEL),
        ("gemini", GEMINI_LITE_MODEL),
    ],

    # Everyday user-facing answers — Gemini's primary model (native thinking)
    # first for quality, Groq's cheapest model second to survive Gemini's
    # daily quota, Gemini's lighter tier last resort.
    "simple_qa": [
        ("gemini", GEMINI_MODEL),
        ("groq", GROQ_FAST_MODEL),
        ("gemini", GEMINI_FALLBACK_MODEL),
    ],

    # Deepest reasoning available — Gemini primary (thinking_budget) first,
    # Gemini 3+ tier (thinking_level, still real native thinking) second,
    # Groq's biggest model last since Groq has no native thinking mechanism.
    "complex_reasoning": [
        ("gemini", GEMINI_MODEL),
        ("gemini", GEMINI_FALLBACK_MODEL),
        ("groq", GROQ_FALLBACK_MODEL),
    ],

    # code_execution is Gemini-3+-only (CodeExecutionToolMiddleware gate) —
    # that leg goes first so code execution is available on the first
    # attempt; Gemini's primary model still writes correct code (just can't
    # execute it), Groq last as a text-only last resort.
    "coding": [
        ("gemini", GEMINI_FALLBACK_MODEL),
        ("gemini", GEMINI_MODEL),
        ("groq", GROQ_FALLBACK_MODEL),
    ],

    # Function-calling works on both Gemini tiers (confirmed live, R1/R2) —
    # same order as today's proven-working chat tool chain: primary, then
    # Gemini 3+ tier, then Groq.
    "tool_use": [
        ("gemini", GEMINI_MODEL),
        ("gemini", GEMINI_FALLBACK_MODEL),
        ("groq", GROQ_FALLBACK_MODEL),
    ],

    # Groq has no vision model configured anywhere in this stack — Gemini
    # only, matches the existing has_attachments hard gate in chat_agent.py.
    "vision": [
        ("gemini", GEMINI_MODEL),
        ("gemini", GEMINI_FALLBACK_MODEL),
    ],
}


def get_model_priority_list(task_type: str) -> list[tuple[str, str]]:
    """Ordered (provider, model_name) legs for task_type. Returns a copy — callers must not mutate the registry."""
    try:
        return list(TASK_MODEL_PRIORITY[task_type])
    except KeyError:
        raise ValueError(
            f"Unknown task_type {task_type!r} — must be one of {sorted(TASK_MODEL_PRIORITY)}"
        ) from None
