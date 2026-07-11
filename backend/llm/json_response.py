"""
Shared JSON-response parsing + malformed-JSON retry for writer/synthesis LLM calls.

Baseline parse logic (fence-strip, outer-brace extraction, raw parse) is the
same three-strategy approach project_service._extract_json() used — the most
robust of the three previously-independent implementations across
project_service.py, generation_orchestrator.py, and package_synthesizer_service.py.

model_provider.py's own .with_retry() only covers transport/quota errors
(ChatGoogleGenerativeAIError, GroqRateLimitError, ...) raised by the model
call itself — a response that comes back 200 OK but isn't valid JSON never
triggers that retry. call_and_parse_json() adds that missing coverage: on
parse failure it re-invokes the caller's model call up to `max_retries`
additional times before raising.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Callable

logger = logging.getLogger(__name__)


def extract_json(text: str) -> dict:
    """Extract a JSON object from LLM output using multiple fallback strategies."""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start : end + 1])
    return json.loads(text.strip())


def call_and_parse_json(
    call_fn:     Callable[[], tuple[str, str]],
    call_type:   str,
    max_retries: int = 2,
) -> tuple[dict, str]:
    """
    Invoke call_fn(), parse its text response as JSON, retrying on parse
    failure only (transport/quota errors are already retried inside call_fn
    by the shared model factory).

    call_fn takes no arguments and returns (text, provider) — the same shape
    route_writer_call() returns. Called fresh on every attempt so each retry
    is a genuine new model invocation, not a re-parse of the same text.

    Returns (parsed_dict, provider_of_successful_attempt).
    Raises RuntimeError (chained from the last JSONDecodeError/ValueError) if
    every attempt fails.
    """
    attempts = max_retries + 1
    last_exc: Exception | None = None
    last_provider = "unknown"

    for attempt in range(1, attempts + 1):
        text, provider = call_fn()
        last_provider = provider
        try:
            return extract_json(text), provider
        except (json.JSONDecodeError, ValueError) as exc:
            last_exc = exc
            logger.warning(
                "[json_response] %s: malformed JSON on attempt %d/%d (provider=%s) — %s",
                call_type, attempt, attempts, provider, exc,
            )

    raise RuntimeError(
        f"[json_response] {call_type}: LLM returned malformed JSON after "
        f"{attempts} attempt(s), last provider={last_provider}: {last_exc}"
    ) from last_exc
