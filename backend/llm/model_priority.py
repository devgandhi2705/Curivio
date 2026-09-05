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
    OPENROUTER_NEMOTRON_MODEL,
)

# Chat model routing — OpenRouter/Nemotron addition (Tier 3 recon + this phase).
# Grounded in real llm_call_log data (surface='chat'), not blanket-added to every
# bucket. Real numbers behind each placement below (is_test excluded, real
# production rows only):
#   - routing (call_type='chat_router_classify', clean 1:1 task_type attribution):
#     groq/llama-3.1-8b-instant primary shows 10.0% success over 1523 real calls,
#     dominated by 962 BadRequestError — the ALREADY-documented stringified-boolean
#     structured-output defect (see _build_pooled_leg's docstring below), not a
#     recoverable rate limit. A structural model defect isn't fixed by retrying the
#     same model. tools/model_bakeoff's real bake-off (report.md) independently
#     recommends nemotron-3-nano-30b-a3b as PRIMARY for exactly this
#     "chat_router / classifier" role (0.0% tool-call format failure, 100 steps).
#   - simple_qa / tool_use / complex_reasoning (call_type='chat_turn', blended —
#     these three share gemini-2.5-flash as leg #1 and cannot be separated further
#     from this data; see model_provider.py phase report for the full honest
#     granularity limitation): gemini-2.5-flash shows 16.1% success over 3074 real
#     calls, dominated by 2514 real 429 "Quota exceeded... limit: 20... model:
#     gemini-2.5-flash" errors — a real, ONGOING, ROUTINE daily-quota exhaustion
#     (confirmed across every real day with meaningful volume, not a resolved
#     historical spike), not an occasional bump. A live trace showed all 3 pooled
#     Gemini keys exhausted back-to-back on one real turn before falling through.
#   simple_qa / tool_use get nemotron as PRIMARY (ahead of Gemini): "everyday
#   answers" don't need Gemini's deepest reasoning tier, and tool_use's own bake-off
#   metric (tool-call format reliability) is directly on-point for that bucket.
#   complex_reasoning keeps Gemini's primary model in the #1 slot — the bake-off
#   measured tool-call FORMAT only, never answer quality/reasoning depth (its own
#   report.md says so explicitly), so there's no real evidence to justify demoting
#   Gemini's flagship reasoning model here. Nemotron goes in as an early FALLBACK
#   instead (ahead of Groq, which real data also shows struggling on this task's
#   last-resort leg) — addresses the real reliability gap without an unverified
#   quality tradeoff.
#   - vision: NOT touched despite sharing gemini-2.5-flash's identical pressure.
#     Real, architectural reason: vision turns route through Gemini's Files API
#     (model_provider.upload_attachment, primary-key-only — a file uploaded with
#     key #1 404s under any other key/provider, confirmed live). An OpenRouter text
#     leg would receive no usable reference to the attached file. The bake-off also
#     never tested multimodal/vision input on any OpenRouter model — no real
#     evidence it would even work.
#   - coding: NOT touched. gemini-3.1-flash-lite (primary here) shows 96.8% success
#     (468 real calls) — healthy, not under real pressure. coding's whole point is
#     Gemini-3+ native code EXECUTION (CodeExecutionToolMiddleware gate) — no
#     OpenRouter model in this stack has an equivalent code-execution tool wired in.
TASK_MODEL_PRIORITY: dict[str, list[tuple[str, str]]] = {
    # Real data: groq/llama-3.1-8b-instant's structured-output BadRequestError rate
    # (63% of real attempts) is a model defect, not a quota bump — nemotron goes
    # primary per the bake-off's own recommendation for this exact role. Groq/Gemini
    # stay as the proven fallback chain, unchanged in relative order.
    "routing": [
        ("openrouter", OPENROUTER_NEMOTRON_MODEL),
        ("groq", GROQ_FAST_MODEL),
        ("gemini", GEMINI_LITE_MODEL),
    ],

    # Real data: gemini-2.5-flash's daily quota is routinely (not occasionally)
    # exhausted across its whole key pool for "everyday" answers — nemotron primary
    # avoids paying that 80%+ real failure tax on the common path. Existing chain
    # kept intact as fallback.
    # Phase R. Measured bake-off on the real feed-discussion answer prompt
    # (same card, same question, N=2 each) scoring the ACTUAL reported defect —
    # flat undifferentiated prose:
    #     nemotron-nano-30b   bullets 0.0  bold  0.0  paras 1.0  chars 1024
    #     groq gpt-oss-20b    bullets 4.0  bold 10.5  paras 6.5  chars 1833   953ms
    #     groq gpt-oss-120b   bullets 3.5  bold 11.5  paras 6.5  chars 2833  2031ms
    #     gemini-3.1-lite     bullets 1.0  bold  6.0  paras 5.0  chars 2508  3875ms
    # nemotron produces ONE paragraph with zero structure no matter what the
    # prompt asks for (verified: a dedicated formatting instruction moved it 0.0
    # -> 0.0 bullets). Both Groq legs are FREE tier and already configured here.
    # gpt-oss-20b goes primary on real production evidence (112/112 = 100% on
    # surface='chat') plus the best measured structure score and 2x the speed;
    # gpt-oss-120b sits behind it for the longer, deeper answers. OpenRouter stays
    # in the chain but demoted — it is not merely "cheap" right now, it is
    # HARD-BLOCKED (PaymentRequiredResponseError on every leg in the bake-off).
    "simple_qa": [
        ("groq", GROQ_FAST_MODEL),
        ("groq", GROQ_FALLBACK_MODEL),
        ("gemini", GEMINI_FALLBACK_MODEL),
        ("openrouter", OPENROUTER_NEMOTRON_MODEL),
        ("gemini", GEMINI_MODEL),
    ],

    # Deepest reasoning available — Gemini's flagship model stays primary (the
    # bake-off never measured reasoning quality, only tool-call format, so there's
    # no real evidence to demote it). Nemotron inserted as an early fallback ahead
    # of Groq (which the real data also shows struggling here) to catch the real,
    # routine quota-exhaustion case without an unverified quality downgrade.
    # Phase R: gemini-2.5-flash stays first — it is the deepest reasoning leg and
    # real data shows 517/517 success when it is not daily-quota-exhausted. The
    # change is BELOW it: the 120B Groq leg (free tier, best measured depth at
    # 2833 chars with real structure) moves ahead of nemotron, which on this exact
    # prompt returns one unstructured paragraph and is currently credit-blocked.
    "complex_reasoning": [
        ("gemini", GEMINI_MODEL),
        ("groq", GROQ_FALLBACK_MODEL),
        ("gemini", GEMINI_FALLBACK_MODEL),
        ("openrouter", OPENROUTER_NEMOTRON_MODEL),
    ],

    # code_execution is Gemini-3+-only (CodeExecutionToolMiddleware gate) —
    # that leg goes first so code execution is available on the first
    # attempt; Gemini's primary model still writes correct code (just can't
    # execute it), Groq last as a text-only last resort.
    # Untouched (Chat model routing phase): real data shows this leg healthy
    # (96.8% success) — no OpenRouter model here has an equivalent code-execution
    # tool anyway.
    "coding": [
        ("gemini", GEMINI_FALLBACK_MODEL),
        ("gemini", GEMINI_MODEL),
        ("groq", GROQ_FALLBACK_MODEL),
    ],

    # Function-calling works on both Gemini tiers (confirmed live, R1/R2). Real
    # data: this bucket shares gemini-2.5-flash's routine quota pressure, AND the
    # bake-off's own metric (tool-call format reliability) is directly on-point for
    # this bucket's actual concern — nemotron goes primary.
    # Phase R: nemotron KEPT primary here on purpose. tools/model_bakeoff measured
    # tool-call FORMAT reliability specifically and recommended it for this role;
    # the Phase R bake-off measured prose formatting, which is a different thing,
    # so there is no evidence to demote it on its own metric. The change is that
    # the free Groq 120B leg moves up to #2 — when nemotron is credit-blocked (as
    # it is now) this bucket previously fell through to gemini-2.5-flash, whose
    # daily quota is routinely exhausted, and only then reached Groq.
    "tool_use": [
        ("openrouter", OPENROUTER_NEMOTRON_MODEL),
        ("groq", GROQ_FALLBACK_MODEL),
        ("gemini", GEMINI_MODEL),
        ("gemini", GEMINI_FALLBACK_MODEL),
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
