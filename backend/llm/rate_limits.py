"""One place that names a provider error, one place that parks a model.

Replaces: model_provider._is_daily_quota_exhausted and its retry predicate,
chat_agent._retry_on, the Groq-400 special retry, writer_provider_router.
_is_quota_error, unpack_service._is_quota_error, embeddings._is_rate_limit_error.

Five kinds, and what each one means for the caller:
  rate_limit   a per-minute ceiling      -> next model now; park this model+key briefly
  daily_quota  a per-day ceiling         -> next model now; park this model+key for an hour
  no_credit    402, the account is empty -> next model now; park the whole provider
  transient    network / 5xx / timeout   -> retry this model, then the next one
  fatal        400/401/404 and friends   -> next model, park nothing

The table is in memory, per process, and is cleared by a restart: a skip is a
short-lived hint, never state anything else depends on.

Public API
----------
classify_error(exc) -> str
skip(provider, model, key_index, kind)              park a model+key, or a provider
record_failure(provider, model, key_index, kind)    apply the rule for that kind
is_skipped(provider, model, key_index) -> str | None
clear()                                             forget everything (tests)
"""
from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)

# (provider, model | None, key_index | None) -> (expires_at_monotonic, kind).
# model/key None means the whole provider is parked.
_skips: dict[tuple[str, str | None, int | None], tuple[float, str]] = {}
_lock = threading.Lock()

# Google names the window in quotaId ("...PerDay..." / "...PerMinute..."); Groq
# spells it out in the message ("requests per day (RPD)", "tokens per minute").
_DAILY_MARKERS = ("perday", "per day", "(rpd)", "(tpd)")
_TRANSIENT_NAMES = ("timeout", "connect", "connection", "protocol", "readerror", "writeerror")


def _now() -> float:
    """Monotonic clock, indirected so tests can move time without sleeping."""
    return time.monotonic()


def _chain(exc: BaseException):
    """The exception and everything it was raised from — LangChain wraps the
    provider's real error (ChatGoogleGenerativeAIError ... from ClientError),
    so the status code and quota id live on __cause__, not the top exception."""
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        yield exc
        exc = exc.__cause__ or exc.__context__


def _status_code(exc: BaseException) -> int | None:
    for err in _chain(exc):
        for attr in ("status_code", "code"):
            value = getattr(err, attr, None)
            if isinstance(value, int) and 100 <= value < 600:
                return value
        for attr in ("response", "raw_response"):
            value = getattr(getattr(err, attr, None), "status_code", None)
            if isinstance(value, int):
                return value
    return None


def classify_error(exc: BaseException) -> str:
    """"rate_limit" | "daily_quota" | "no_credit" | "transient" | "fatal"."""
    own_kind = getattr(exc, "kind", None)      # our own errors label themselves
    if isinstance(own_kind, str):
        return own_kind

    text = " ".join(str(err) for err in _chain(exc)).lower()
    names = " ".join(type(err).__name__ for err in _chain(exc)).lower()
    code = _status_code(exc)

    if code == 402 or "paymentrequired" in names or "more credits" in text:
        return "no_credit"
    if code == 429 or "resource_exhausted" in text or "ratelimit" in names or "toomanyrequests" in names:
        return "daily_quota" if any(marker in text for marker in _DAILY_MARKERS) else "rate_limit"
    if (code is not None and code >= 500) or "unavailable" in text or any(n in names for n in _TRANSIENT_NAMES):
        return "transient"
    return "fatal"


def _durations() -> dict[str, int]:
    # Imported here, not at module scope: model_provider imports this module.
    from .model_provider import chat_models
    retry = chat_models().retry
    return {
        "rate_limit":  retry.skip_after_rate_limit_sec,
        "daily_quota": retry.skip_after_daily_quota_sec,
        "no_credit":   retry.skip_after_no_credit_sec,
    }


def skip(provider: str, model: str | None, key_index: int | None, kind: str) -> None:
    """Park a model+key — or the whole provider when model/key_index are None —
    for the [retry] duration of `kind`."""
    seconds = _durations().get(kind)
    if not seconds:
        return
    with _lock:
        _skips[(provider, model, key_index)] = (_now() + seconds, kind)
    logger.info("[rate_limits] parked %s/%s key#%s for %ss (%s)",
                provider, model or "*", "*" if key_index is None else key_index, seconds, kind)


def record_failure(provider: str, model: str, key_index: int, kind: str) -> None:
    """Apply the skip rule for one failure kind. transient and fatal park nothing:
    a transient error is worth retrying, and a fatal one (bad request, missing
    model) says nothing about the model's availability a minute from now."""
    if kind == "no_credit":
        skip(provider, None, None, kind)
    elif kind in ("rate_limit", "daily_quota"):
        skip(provider, model, key_index, kind)


def is_skipped(provider: str, model: str, key_index: int) -> str | None:
    """The kind this leg is parked for, or None. Truthy means 'do not call it'."""
    now = _now()
    with _lock:
        for key in ((provider, None, None), (provider, model, key_index)):
            entry = _skips.get(key)
            if entry is None:
                continue
            expires_at, kind = entry
            if expires_at > now:
                return kind
            del _skips[key]
    return None


def clear() -> None:
    with _lock:
        _skips.clear()
