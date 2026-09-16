"""
Unpack "Explain" service — select-to-explain popover backend.

Pipeline: cache check -> LLM (the shared [explain] model list, streaming) with
one retry on JSON-parse failure -> dictionary-only degrade if the LLM path
fails entirely. Words, phrases, and sentences all go through the same LLM
path with full surrounding context — no separate word-only fast path.

The LLM half runs on the same shared provider layer as chat (route_legs /
build_leg / run_route in model_provider.py): the [explain] list in
chat_models.toml, the shared skip policy in rate_limits.py, and every row
LLMCallLogger writes carries a route/route_step like the rest of chat.

Translation is a separate action/path (translate_service.py, Google Cloud
Translation API) — not part of this module.

Public API
----------
explain_stream(term, user_id, sentence, prev_sentence, next_sentence) -> generator[str]
    Yields NDJSON lines:
      {"t":"chunk","v":"<text>"}                        — incremental meaning_in_context text
      {"t":"done", term, definition_general,
       meaning_in_context, confidence,
       source, provider}                                 — final result
      {"t":"error","message":"<reason>"}                  — unrecoverable error
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from uuid import uuid4

from ..llm.call_logger import LLMCallLogger
from .unpack_cache_service import build_unpack_key, get_cached_unpack, cache_unpack
from .dictionary_service import is_dictionary_fast_path_eligible, dictionary_lookup
from ..prompts.unpack_prompt import build_unpack_messages

logger = logging.getLogger(__name__)

_ACTION = "explain"

_REQUIRED_KEYS    = ("term", "definition_general", "meaning_in_context", "confidence")
_VALID_CONFIDENCE = {"high", "medium", "low"}


def _parse_response(raw: str | None) -> dict | None:
    """Validate + defensively parse the model's JSON output. None on any failure."""
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or not all(k in data for k in _REQUIRED_KEYS):
        return None
    if data.get("confidence") not in _VALID_CONFIDENCE:
        data["confidence"] = "medium"
    return data


_MEANING_KEY = '"meaning_in_context"'


def _extract_partial_meaning(buffer: str) -> str | None:
    """
    Best-effort incremental extraction of meaning_in_context's string value
    while the JSON is still streaming in (the closing quote may not have
    arrived yet) — lets the popover reveal the explanation progressively
    without a full streaming-JSON parser.
    """
    idx = buffer.find(_MEANING_KEY)
    if idx == -1:
        return None
    rest = buffer[idx + len(_MEANING_KEY):]
    colon = rest.find(":")
    if colon == -1:
        return None
    rest = rest[colon + 1:].lstrip()
    if not rest.startswith('"'):
        return None
    rest = rest[1:]

    end = -1
    i = 0
    while i < len(rest):
        if rest[i] == "\\":
            i += 2
            continue
        if rest[i] == '"':
            end = i
            break
        i += 1

    text = rest[:end] if end != -1 else rest
    return text.replace('\\"', '"').replace("\\n", "\n")


# The popover has a ~5s budget and a 200-token answer; both live in
# chat_models.toml's [explain] list, not here. 0.3 keeps the JSON shape stable
# (the chat default of 0.7 is tuned for prose, not for a small strict schema).
_TEMPERATURE = 0.3
_CALL_TYPE = "explain"


def _stream_leg(spec, messages, strict_messages, base_meta, notes):
    """One [explain] leg: stream the JSON, reveal meaning_in_context as it
    arrives, then parse. A model that answers in the wrong shape gets one
    stricter, non-streaming retry on the same leg — that is a formatting slip,
    not an unavailable model. Yields ("chunk", text), then ("done", parsed) or
    ("invalid", raw)."""
    from ..llm.model_provider import build_leg, extract_text, route_label

    # One build for this leg, reused for both the stream and (if needed) the
    # retry invoke() below — a second build_leg() call here would count as a
    # second leg attempt to callers walking `built`/call-log rows per leg.
    model = build_leg(spec, streaming=True, temperature=_TEMPERATURE)
    # Gemini honours an OpenAI-style json_object request; Groq streams the
    # JSON as plain text, which _extract_partial_meaning already reads.
    if spec.provider == "gemini":
        model = model.bind(response_format={"type": "json_object"})

    config = {"callbacks": [LLMCallLogger()],
              "metadata": {**base_meta, "agent_name": "explain_stream",
                           "route": route_label("explain", "", notes), "route_step": spec.step}}

    buffer, sent = "", 0
    for chunk in model.stream(messages, config=config):
        buffer += extract_text(chunk)
        partial = _extract_partial_meaning(buffer)
        if partial and len(partial) > sent:
            yield "chunk", partial[sent:]
            sent = len(partial)

    parsed = _parse_response(buffer)
    if parsed is None:
        retry_config = {**config, "metadata": {**config["metadata"], "agent_name": "explain_strict_retry"}}
        parsed = _parse_response(extract_text(model.invoke(strict_messages, config=retry_config)))
    if parsed is None:
        yield "invalid", buffer
        return
    yield "done", parsed


def _line(t: str, **fields) -> str:
    return json.dumps({"t": t, **fields}) + "\n"


def _done_line(result: dict, source: str, provider: str | None = None) -> str:
    return _line(
        "done",
        term=result.get("term", ""),
        definition_general=result.get("definition_general", ""),
        meaning_in_context=result.get("meaning_in_context"),
        confidence=result.get("confidence", "low"),
        source=source,
        provider=provider,
    )


def _fmt_messages(messages: list[dict]) -> str:
    return "\n".join(f"{m['role']}: {m['content']}" for m in messages)


def _log_explain(
    trace_id: str, agent_name: str, provider: str, input_text: str, t0: float,
    *, output: str | None, success: bool, user_id: str, error: Exception | None = None,
) -> None:
    """Writer for the cache-hit and dictionary-fallback rows only — each
    [explain] LLM leg now logs its own row via LLMCallLogger (attached as a
    callback in _stream_leg), the same shared writer chat uses. Never raises.

    Phase N-fix: user_id threaded from the route's authenticated caller —
    previously never passed here at all (N-recon)."""
    from ..llm.call_logger import write_call_row
    now = datetime.now(timezone.utc).isoformat()
    write_call_row(
        run_id=uuid4().hex,
        parent_run_id=None,
        timestamp_start=now,
        timestamp_end=now,
        latency_ms=int((time.monotonic() - t0) * 1000),
        provider=provider,
        call_type="explain",
        user_id=user_id,
        input_text=input_text,
        output=output,
        success=success,
        error_type=type(error).__name__ if error else None,
        error_message=str(error) if error else None,
        trace_id=trace_id,
        agent_name=agent_name,
        surface="explain",
    )


def explain_stream(
    term: str,
    user_id: str,
    sentence: str = "",
    prev_sentence: str = "",
    next_sentence: str = "",
):
    term     = (term or "").strip()
    sentence = (sentence or "").strip()

    if not term:
        yield _line("error", message="term must not be empty")
        return

    trace_id = uuid4().hex

    key    = build_unpack_key(term, sentence, _ACTION, None)
    t0     = time.monotonic()
    cached = get_cached_unpack(key)
    if cached:
        _log_explain(trace_id, "cache", "cache", f"term={term!r} sentence={sentence!r}", t0,
                    output=json.dumps(cached), success=True, user_id=user_id)
        yield _done_line(cached, source="cache")
        return

    # ── LLM path: the [explain] list, top to bottom ────────────────────────
    messages = build_unpack_messages(term, sentence, prev_sentence, next_sentence)
    strict_messages = build_unpack_messages(term, sentence, prev_sentence, next_sentence, strict=True)
    base_meta = {"call_type": _CALL_TYPE, "surface": "explain", "trace_id": trace_id,
                 "user_id": user_id}

    from ..llm.model_provider import AllLegsFailed, route_legs, run_route
    legs = iter(route_legs("explain"))     # shared: each attempt resumes where the last stopped
    notes: list[str] = []
    result: dict | None = None
    provider_used: str | None = None

    while result is None:
        try:
            spec, events = run_route(
                "explain", lambda s: _stream_leg(s, messages, strict_messages, base_meta, notes),
                notes=notes, legs=legs)
        except AllLegsFailed:
            break
        try:
            for kind, payload in events:
                if kind == "chunk":
                    yield _line("chunk", v=payload)
                elif kind == "done":
                    result, provider_used = payload, spec.provider
                elif kind == "invalid":
                    notes.append(f"skipped {spec} (invalid_output)")
        except Exception:
            # A failure after the first chunk: the next leg answers instead.
            logger.warning("[unpack] %s failed mid-stream — trying the next leg", spec, exc_info=True)

    if result:
        cache_unpack(key, term, None, result)
        yield _done_line(result, source="llm", provider=provider_used)
        return

    # ── Total LLM failure: degrade to dictionary-only, never a blank error ──
    t_dict   = time.monotonic()
    fallback = dictionary_lookup(term) if is_dictionary_fast_path_eligible(term) else None
    if fallback:
        _log_explain(trace_id, "dictionary_fallback", "dictionary", f"term={term!r}", t_dict,
                    output=json.dumps(fallback), success=True, user_id=user_id)
        yield _done_line(fallback, source="dictionary_fallback")
    else:
        _log_explain(trace_id, "dictionary_fallback", "dictionary", f"term={term!r}", t_dict,
                    output=None, success=False, user_id=user_id)
        yield _done_line(
            {"term": term, "definition_general": "", "meaning_in_context": None, "confidence": "low"},
            source="unavailable",
        )
