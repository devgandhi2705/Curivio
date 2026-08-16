"""
Feed v2 LLM provider — a COPY of the concepts in backend/llm/model_provider.py,
never an import (feed_v2 must not reach into backend.llm.*). Legacy's
model_provider.py is untouched.

Key differences from legacy, per the Phase-3 spec:

  * ROUND-ROBIN key rotation with a per-key cooldown on 429 — NOT LangChain's
    ordered .with_fallbacks(). Rotation logic ported from
    tools/model_bakeoff/providers.py (_call_rotating). Cooldown is stateful
    across calls: a key that 429s is parked for _COOLDOWN_SECONDS, so the NEXT
    call skips it instead of failing through it again.
  * Per-agent routing table, primary + fallback on a DIFFERENT provider.
  * Fallback ALWAYS ON — no env flag, no config switch disables it.
  * Chain per agent: rotate ALL primary-provider keys, then hop to the fallback
    model on the other provider (rotate its keys), then fail with a logged reason.
  * Structured JSON per agent: Gemini legs use native response_schema; OpenRouter
    legs get schema-in-prompt + a tolerant parser.

SDK-direct (google-genai + openai→OpenRouter), same two SDKs the bake-off uses.
Every attempt (success or failure) is logged to llm_call_log via
call_logger.write_call_row, carrying trace_id/agent_name/step_index/surface.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

from . import call_logger

load_dotenv(dotenv_path=Path(__file__).resolve().parents[4] / ".env")

logger = logging.getLogger(__name__)

_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
# A key that 429s is parked this long so the next call rotates past it instead of
# re-hitting it. ponytail: fixed 60s cooldown; make it per-key adaptive only if a
# real quota-window signal proves 60s wrong.
_COOLDOWN_SECONDS = float(os.getenv("FEED_V2_KEY_COOLDOWN_SECONDS", "60"))
_TEMPERATURE = 0.7

# ── Model registry: short name -> (provider, real API model id) ───────────────
# Real ids confirmed from tools/model_bakeoff/bakeoff.py CANDIDATES.
MODEL_REGISTRY: dict[str, tuple[str, str]] = {
    "gemini-3-flash-preview": ("google",     "gemini-3-flash-preview"),
    "gemini-3.1-flash-lite":  ("google",     "gemini-3.1-flash-lite"),
    "nemotron-nano-30b":      ("openrouter", "nvidia/nemotron-3-nano-30b-a3b"),
    "nemotron-super-120b":    ("openrouter", "nvidia/nemotron-3-super-120b-a12b"),
}

# ── Per-agent routing: agent -> (primary short name, fallback short name) ──────
# Fallback is ALWAYS on a different provider than primary (verified against the
# registry in AGENT_ROUTING's module-load self-check below).
AGENT_ROUTING: dict[str, tuple[str, str]] = {
    # Phase 5: persona + coverage_mode inference from project + material signals.
    # Cross-provider (Gemini primary / nemotron fallback) — the normal rule; no
    # vision needed here, so no _SAME_PROVIDER_OK exception.
    "profile":           ("gemini-3-flash-preview", "nemotron-nano-30b"),
    # Phase 6: batch curriculum planner. Runs ONCE PER BATCH (7-20 days), far less
    # often than the daily lesson_planner/section_writer — so its primary sits on
    # OpenRouter (nemotron) to balance load away from Gemini, which the daily agents
    # already lean on. Fallback hops to Gemini (cross-provider). Documented exception
    # to the "primary usually Gemini" habit, same as image_ingestor's note.
    "journey_planner":   ("nemotron-nano-30b",      "gemini-3-flash-preview"),
    "lesson_planner":    ("gemini-3-flash-preview", "nemotron-nano-30b"),
    "web_researcher":    ("nemotron-nano-30b",      "gemini-3-flash-preview"),
    "corpus_researcher": ("gemini-3.1-flash-lite",  "nemotron-nano-30b"),
    "source_ranker":     ("nemotron-nano-30b",      "gemini-3.1-flash-lite"),
    "section_writer":    ("gemini-3-flash-preview", "nemotron-super-120b"),
    "visual_director":   ("gemini-3-flash-preview", "nemotron-nano-30b"),
    "claim_validator":   ("nemotron-nano-30b",      "gemini-3.1-flash-lite"),
    # Phase 4: standalone image ingestion (vision + OCR). DELIBERATE same-provider
    # exception to the cross-provider fallback rule — no model in MODEL_REGISTRY on
    # the OpenRouter side is vision-capable (nemotron is text-only), so both legs
    # are vision-capable Gemini models on separate key pools + model tiers. Add a
    # vision-capable OpenRouter model here later to restore cross-provider fallback.
    "image_ingestor":    ("gemini-3-flash-preview", "gemini-3.1-flash-lite"),
}

# Agents exempt from the "fallback on a different provider" rule (see above).
_SAME_PROVIDER_OK = {"image_ingestor"}

# One declared JSON schema per agent. Phase 3 ships minimal-but-valid schemas
# (each an object with the fields the agent must emit); later phases tighten them.
# Every leg must satisfy the agent's schema — Gemini via response_schema,
# OpenRouter via schema-in-prompt + tolerant parse + required-key check.
AGENT_SCHEMAS: dict[str, dict] = {
    # Phase 5 profile: legacy's 7 persona fields + 3 new coverage fields.
    # coverage_mode is constrained to the three inference outcomes.
    "profile":           {"type": "object",
                          "required": ["learning_subject", "persona", "primary_focus",
                                       "industry_context", "material_scope",
                                       "coverage_mode", "coverage_reasoning"],
                          "properties": {
                              "learning_subject": {"type": "string"},
                              "persona":          {"type": "string"},
                              "goal":             {"type": "string"},
                              "industry_context": {"type": "string"},
                              "primary_focus":    {"type": "string"},
                              "search_lens":      {"type": "string"},
                              "intent_summary":   {"type": "string"},
                              "material_scope":   {"type": "string"},
                              "coverage_mode":    {"type": "string",
                                                   "enum": ["material_bound", "material_anchored", "open"]},
                              "coverage_reasoning": {"type": "string"}}},
    # Phase 6 journey_planner: both shapes carry shape + day_count at top level; the
    # shape-specific body (days[] for fixed_sequence, themes[] for rotating_theme) is
    # validated in the agent after parse. Arrays are FULLY specified (items schemas)
    # because Gemini's native response_schema rejects a bare `{"type":"array"}` with
    # a 400 (missing `items`) — and it is strict, so any field the model must emit
    # has to be declared here or Gemini drops it. (source_section is added by the
    # agent post-parse, not by the model, so it is intentionally not declared.)
    "journey_planner":   {"type": "object", "required": ["shape", "day_count"],
                          "properties": {
                              "shape": {"type": "string",
                                        "enum": ["fixed_sequence", "rotating_theme"]},
                              "day_count": {"type": "integer"},
                              "reasoning": {"type": "string"},
                              "days": {"type": "array", "items": {"type": "object", "properties": {
                                  "day_number": {"type": "integer"},
                                  "focus": {"type": "string"},
                                  "display_title": {"type": "string"},
                                  "frame_hint": {"type": "string"},
                                  "prerequisite_concepts": {"type": "array", "items": {"type": "string"}},
                                  "rationale": {"type": "string"}}}},
                              "themes": {"type": "array", "items": {"type": "object", "properties": {
                                  "name": {"type": "string"},
                                  "description": {"type": "string"}}}},
                              "trusted_sources": {"type": "array", "items": {"type": "string"}},
                              "display_summary": {"type": "string"}}},
    "lesson_planner":    {"type": "object", "required": ["objectives"],
                          "properties": {"objectives": {"type": "array"}}},
    "web_researcher":    {"type": "object", "required": ["findings"],
                          "properties": {"findings": {"type": "array"}}},
    # Phase 8 corpus_researcher: EXTRACTION step. The model receives numbered
    # candidate chunks (retrieved by vector search) and selects the ones actually
    # relevant to the day's focus, optionally quoting the pertinent span. It emits
    # only the candidate INDEX + a quote/why — the citation metadata (material_id,
    # chunk_index, filename) is joined from the DB row by index, never trusted from
    # the model. Array items fully specified because gemini-3.1-flash-lite (primary)
    # uses native response_schema, which 400s on a bare {"type":"array"} and drops
    # any undeclared field (same lesson as journey_planner).
    "corpus_researcher": {"type": "object", "required": ["passages"],
                          "properties": {"passages": {"type": "array", "items": {
                              "type": "object", "properties": {
                                  "index": {"type": "integer"},
                                  "quote": {"type": "string"},
                                  "why_relevant": {"type": "string"}}}}}},
    "source_ranker":     {"type": "object", "required": ["ranking"],
                          "properties": {"ranking": {"type": "array"}}},
    "section_writer":    {"type": "object", "required": ["sections"],
                          "properties": {"sections": {"type": "array"}}},
    "visual_director":   {"type": "object", "required": ["figures"],
                          "properties": {"figures": {"type": "array"}}},
    "claim_validator":   {"type": "object", "required": ["verdicts"],
                          "properties": {"verdicts": {"type": "array"}}},
    "image_ingestor":    {"type": "object", "required": ["description", "ocr_text"],
                          "properties": {"description": {"type": "string"},
                                         "ocr_text": {"type": "string"}}},
}


class ProviderKeyMissing(Exception):
    """The API key pool for a provider is not configured — leg is unrunnable."""


class AllLegsFailed(Exception):
    """Every primary key AND every fallback key failed. Carries the logged reason."""


# ── Key pools (ported from model_bakeoff._split_pool) ─────────────────────────
def _split_pool(*env_names: str) -> list[str]:
    keys: list[str] = []
    for name in env_names:
        for k in os.getenv(name, "").split(","):
            k = k.strip()
            if k and k not in keys:
                keys.append(k)
    return keys


def _gemini_keys() -> list[str]:
    keys = _split_pool("GEMINI_API_KEYS", "GEMINI_API_KEY", "GEMINI_BACKUP_API_KEY")
    if not keys:
        raise ProviderKeyMissing("no Gemini key (GEMINI_API_KEYS / GEMINI_API_KEY / GEMINI_BACKUP_API_KEY)")
    return keys


def _openrouter_keys() -> list[str]:
    keys = _split_pool("OPENROUTER_API_KEY")
    if not keys:
        raise ProviderKeyMissing("OPENROUTER_API_KEY not set")
    return keys


def _keys_for_provider(provider: str) -> list[str]:
    if provider == "google":
        return _gemini_keys()
    if provider == "openrouter":
        return _openrouter_keys()
    raise ValueError(f"unknown provider {provider!r}")


# ── 429 detection + stateful per-key cooldown (ported from model_bakeoff) ─────
def _is_rate_limit(exc: Exception) -> bool:
    text = str(exc).lower()
    if any(s in text for s in ("429", "rate limit", "quota", "resource_exhausted", "resourceexhausted")):
        return True
    return type(exc).__name__ in ("ResourceExhausted", "RateLimitError", "TooManyRequests")


# Module-level cooldown state: key -> monotonic timestamp until which it's parked.
_cooldowns: dict[str, float] = {}


def _in_cooldown(key: str, now: float) -> bool:
    return _cooldowns.get(key, 0.0) > now


def _park(key: str, now: float) -> None:
    _cooldowns[key] = now + _COOLDOWN_SECONDS


def _rotate_call(keys: list[str], make_call, *, now_fn=time.monotonic):
    """Try keys once each, SKIPPING any still in cooldown. On a 429, park that
    key and rotate immediately. A non-rate-limit error propagates at once. If
    every key is currently cooled down, fall back to trying them all (better a
    likely-429 than serving nothing). Returns (result, key, attempt_index).

    This is the ported model_bakeoff rotation, made stateful: because a 429 parks
    the key across calls, the NEXT call rotates past it without re-hitting it.
    """
    now = now_fn()
    live = [k for k in keys if not _in_cooldown(k, now)] or list(keys)
    last_exc: Exception | None = None
    for attempt, key in enumerate(live):
        try:
            return make_call(key), key, attempt
        except ProviderKeyMissing:
            raise
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if _is_rate_limit(exc):
                _park(key, now_fn())
                continue
            raise
    raise last_exc  # type: ignore[misc]


# ── Tolerant JSON parser (for legs without native structured output) ──────────
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_json_tolerant(text: str) -> dict:
    """Extract a JSON object from model text. Strips ``` fences, then falls back
    to the first '{' … matching-depth '}' span. Raises ValueError if none parses."""
    if not text:
        raise ValueError("empty response")
    fence = _JSON_FENCE_RE.search(text)
    candidates = []
    if fence:
        candidates.append(fence.group(1).strip())
    candidates.append(text.strip())
    # first-brace-to-balanced-close span
    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start:i + 1])
                    break
    for c in candidates:
        try:
            obj = json.loads(c)
            if isinstance(obj, dict):
                return obj
        except (ValueError, TypeError):
            continue
    raise ValueError("no parseable JSON object in response")


def _validate_schema(obj: dict, schema: dict) -> None:
    """Tolerant required-key check — the declared schema's contract every leg
    must satisfy. Not a full JSON-Schema validator (YAGNI); just presence of
    top-level required keys, which is what the pipeline depends on."""
    for key in schema.get("required", []):
        if key not in obj:
            raise ValueError(f"missing required key {key!r}")


# ── SDK legs ──────────────────────────────────────────────────────────────────
def _call_google(api_model_id: str, messages: list[dict], system: str,
                 schema: dict, key: str, images: list[tuple[bytes, str]] | None = None) -> dict:
    from google import genai
    from google.genai import types

    contents = [
        {"role": "model" if m["role"] == "assistant" else "user",
         "parts": [{"text": m["content"]}]}
        for m in messages
    ]
    # Vision: attach image bytes as inline parts on the last user turn (image_ingestor).
    if images:
        last_user = next((c for c in reversed(contents) if c["role"] == "user"), None)
        if last_user is None:
            last_user = {"role": "user", "parts": []}
            contents.append(last_user)
        for img_bytes, mime in images:
            last_user["parts"].append(types.Part.from_bytes(data=img_bytes, mime_type=mime))
    config = types.GenerateContentConfig(
        system_instruction=system, temperature=_TEMPERATURE,
        response_mime_type="application/json",
        response_schema=schema or None,
    )
    client = genai.Client(api_key=key)
    t0 = time.monotonic()
    resp = client.models.generate_content(model=api_model_id, contents=contents, config=config)
    latency_ms = int((time.monotonic() - t0) * 1000)
    usage = getattr(resp, "usage_metadata", None)
    return {
        "text": getattr(resp, "text", None) or "",
        "in_tokens": getattr(usage, "prompt_token_count", 0) or 0,
        "out_tokens": getattr(usage, "candidates_token_count", 0) or 0,
        "latency_ms": latency_ms,
        "model_used": api_model_id,
    }


def _call_openrouter(api_model_id: str, messages: list[dict], system: str,
                    schema: dict, key: str, images: list[tuple[bytes, str]] | None = None) -> dict:
    # images ignored: OpenRouter legs in this registry are text-only. image_ingestor
    # never routes here (both its legs are Gemini). Param kept for a uniform sdk signature.
    from openai import OpenAI

    # No guaranteed native structured output → schema-in-prompt + tolerant parse.
    sys_with_schema = system + (
        "\n\nRespond with ONLY a JSON object matching this schema:\n"
        + json.dumps(schema) if schema else ""
    )
    payload = [{"role": "system", "content": sys_with_schema}] + [
        {"role": m["role"], "content": m["content"]} for m in messages
    ]
    client = OpenAI(base_url=_OPENROUTER_BASE, api_key=key)
    t0 = time.monotonic()
    # No response_format=json_object: it's redundant with the schema-in-prompt +
    # tolerant-parse path above (structure is enforced there for every OpenRouter
    # role), and some OpenRouter upstreams for these models (e.g. DeepInfra for
    # nemotron) reject it with a 405 — Phase 5b removed it provider-wide.
    resp = client.chat.completions.create(
        model=api_model_id, messages=payload, temperature=_TEMPERATURE,
    )
    latency_ms = int((time.monotonic() - t0) * 1000)
    text = (resp.choices[0].message.content or "") if resp.choices else ""
    usage = getattr(resp, "usage", None)
    return {
        "text": text,
        "in_tokens": getattr(usage, "prompt_tokens", 0) or 0,
        "out_tokens": getattr(usage, "completion_tokens", 0) or 0,
        "latency_ms": latency_ms,
        "model_used": api_model_id,
    }


_SDK_FOR_PROVIDER = {"google": _call_google, "openrouter": _call_openrouter}


def call_agent(agent: str, messages: list[dict], system: str = "", *,
              schema: dict | None = None, meta: dict | None = None,
              images: list[tuple[bytes, str]] | None = None) -> dict:
    """Run one agent call through its routing chain: rotate all primary-provider
    keys, then hop to the fallback model on the other provider, then fail with a
    logged reason. Returns the parsed+validated JSON dict.

    meta carries trace_id/agent_name/step_index/surface/call_type/user_id/
    project_id/day_number for the log rows (agent_name defaults to `agent`).
    images: optional [(bytes, mime_type)] for vision agents (image_ingestor) —
    attached to Gemini legs only.
    """
    if agent not in AGENT_ROUTING:
        raise ValueError(f"unknown agent {agent!r}")
    schema = schema if schema is not None else AGENT_SCHEMAS.get(agent, {})
    meta = dict(meta or {})
    meta.setdefault("agent_name", agent)

    primary_short, fallback_short = AGENT_ROUTING[agent]
    input_text = system + "\n" + "\n".join(f"{m['role']}: {m['content']}" for m in messages)

    reasons: list[str] = []
    for leg_short in (primary_short, fallback_short):
        provider, api_model_id = MODEL_REGISTRY[leg_short]
        sdk = _SDK_FOR_PROVIDER[provider]
        try:
            keys = _keys_for_provider(provider)
        except ProviderKeyMissing as exc:
            reasons.append(f"{leg_short}: {exc}")
            continue

        def make_call(key: str, _pmi=provider, _mid=api_model_id, _sdk=sdk):
            return _sdk(_mid, messages, system, schema, key, images)

        try:
            result, key, attempt = _rotate_call(keys, make_call)
        except Exception as exc:  # noqa: BLE001 — whole pool failed this leg
            self_reason = f"{leg_short} ({provider}): {type(exc).__name__}: {exc}"
            reasons.append(self_reason)
            _log_attempt(meta, provider, api_model_id, input_text, result=None,
                         success=False, error=exc, retry_count=0)
            continue

        # Parse + validate against the declared schema.
        try:
            obj = parse_json_tolerant(result["text"])
            _validate_schema(obj, schema)
        except ValueError as exc:
            reasons.append(f"{leg_short} ({provider}): schema/{exc}")
            _log_attempt(meta, provider, api_model_id, input_text, result=result,
                         success=False, error=exc, retry_count=attempt)
            continue

        _log_attempt(meta, provider, api_model_id, input_text, result=result,
                     success=True, error=None, retry_count=attempt)
        return obj

    reason = " | ".join(reasons)
    logger.error("[feed_v2.provider] agent %s: all legs failed: %s", agent, reason)
    raise AllLegsFailed(f"agent {agent}: {reason}")


def _log_attempt(meta: dict, provider: str, api_model_id: str, input_text: str, *,
                result: dict | None, success: bool, error: Exception | None,
                retry_count: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    call_logger.write_call_row(
        run_id=str(uuid4()),
        parent_run_id=meta.get("trace_id"),
        timestamp_start=now,
        timestamp_end=now,
        latency_ms=(result or {}).get("latency_ms", 0),
        provider={"google": "gemini", "openrouter": "openrouter"}.get(provider, provider),
        model_requested=api_model_id,
        model_used=(result or {}).get("model_used"),
        call_type=meta.get("call_type"),
        user_id=meta.get("user_id"),
        project_id=meta.get("project_id"),
        day_ref=meta.get("day_ref", meta.get("day_number")),
        input_text=input_text,
        output=(result or {}).get("text"),
        input_tokens=(result or {}).get("in_tokens"),
        output_tokens=(result or {}).get("out_tokens"),
        total_tokens=((result or {}).get("in_tokens") or 0) + ((result or {}).get("out_tokens") or 0) if result else None,
        success=success,
        error_type=type(error).__name__ if error else None,
        error_message=str(error) if error else None,
        retry_count=retry_count,
        trace_id=meta.get("trace_id"),
        agent_name=meta.get("agent_name"),
        step_index=meta.get("step_index"),
        surface=meta.get("surface"),
        is_test=bool(meta.get("is_test", False)),
    )


def _self_check_routing() -> None:
    """Fallback must be a different provider than primary — except the documented
    vision-only agents in _SAME_PROVIDER_OK (no cross-provider vision model exists)."""
    for agent, (p, f) in AGENT_ROUTING.items():
        if agent in _SAME_PROVIDER_OK:
            continue
        pp = MODEL_REGISTRY[p][0]
        fp = MODEL_REGISTRY[f][0]
        assert pp != fp, f"agent {agent}: primary+fallback share provider {pp}"


_self_check_routing()
