"""
Unified LangChain chat-model provider — Gemini key pool -> Groq fallback chain.

The Feed pipeline (persona, journey planner, retrieval planner, writer,
synthesis) is migrated onto this module — see intent_profile_service.py,
journey_planner_service.py, retrieval_planner.py, writer_provider_router.py,
generation_orchestrator.py, package_synthesizer_service.py. grok_service.py
and unpack_service.py are unrelated features (chat, notes/bookmarks) and
still use their own raw OpenAI-compatible clients — untouched, out of scope.

Chain shape, built with .with_fallbacks(): one ChatGoogleGenerativeAI instance per
key in GEMINI_API_KEYS (comma-separated pool), then ChatGroq last. The final pooled
Gemini key uses GEMINI_FALLBACK_MODEL instead of GEMINI_MODEL — a lighter model on a
separate quota bucket, tried before giving up on Gemini entirely (mirrors the
primary/fallback model pattern already used in journey_planner_service.py). Each
leg is independently retried with exponential backoff on rate-limit errors before
the chain moves to the next leg.

Public API
----------
get_chat_model(model=None, legs="all", json_mode=False) -> Runnable   plain chat completions
get_structured_chat_model(schema, model=None, legs="all") -> Runnable  same chain, typed
                                                              output via .with_structured_output(schema)
extract_text(response) -> str   normalizes AIMessage.content — Gemini sometimes
                                 returns a list of content parts instead of a
                                 plain string; Groq always returns a string.
upload_attachment(file_bytes, mime_type, filename) -> dict   Gemini Files API upload,
                                 primary key only (see docstring on the function —
                                 files are scoped to the uploading API key/project,
                                 so a fallback Gemini key cannot read a primary-key
                                 upload; Groq has no Files API and no vision model
                                 configured here either).

`model` overrides GEMINI_MODEL for the primary-tier Gemini legs only (the last
pooled key keeps GEMINI_FALLBACK_MODEL as the universal safety-net model) — lets
a call site request a specific primary model (e.g. journey planner's
gemini-2.5-flash, writer's gemini-3.1-flash-lite) without forking the chain.

`legs` restricts which legs get built: "all" (default, full Gemini-pool ->
Gemini-fallback -> Groq chain), "gemini" (Gemini legs only, no Groq), or "groq"
(Groq leg only — `model` overrides GROQ_FALLBACK_MODEL in this case). Used by
callers that need to send a different prompt per provider (see
writer_provider_router.route_writer_call) instead of one input across a single
.with_fallbacks() chain.
"""
from __future__ import annotations

import io
import itertools
import logging
import os
import time
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai.errors import ClientError as GeminiClientError
from groq import BadRequestError as GroqBadRequestError
from groq import RateLimitError as GroqRateLimitError
from langchain_core.runnables.retry import RunnableRetry
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError
from langchain_groq import ChatGroq
from langchain_openrouter import ChatOpenRouter
from openrouter.errors import TooManyRequestsResponseError
from tenacity import retry_if_exception

load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")

from ..config import GEMINI_MODEL, GEMINI_FALLBACK_MODEL, GROQ_FALLBACK_MODEL
from . import rate_limits
from .call_logger import LLMCallLogger

logger = logging.getLogger(__name__)

_RETRY_ATTEMPTS = 3
_TEMPERATURE = 0.7


def _gemini_keys() -> list[str]:
    # Accept GEMINI_API_KEYS (comma-separated pool) or single GEMINI_API_KEY —
    # mirrors _groq_keys() so one secret name works everywhere (HF Spaces set
    # both because the resolvers disagreed; they no longer do).
    raw = os.getenv("GEMINI_API_KEYS", "") or os.getenv("GEMINI_API_KEY", "")
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise RuntimeError("GEMINI_API_KEYS or GEMINI_API_KEY environment variable is not set")
    return keys


def _groq_keys() -> list[str]:
    """GROQ_API_KEYS (comma-separated pool), falling back to single GROQ_API_KEY — same
    shape as _gemini_keys(), backward-compatible with every existing GROQ_API_KEY-only .env."""
    raw = os.getenv("GROQ_API_KEYS", "")
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if keys:
        return keys
    single = os.getenv("GROQ_API_KEY")
    if single:
        return [single]
    raise RuntimeError("GROQ_API_KEYS or GROQ_API_KEY environment variable is not set")


def _groq_key() -> str:
    return _groq_keys()[0]


def _openrouter_keys() -> list[str]:
    """OPENROUTER_API_KEY (comma-separated pool) — same shape as
    _gemini_keys()/_groq_keys(). Only consumed by task_types model_priority.py
    actually assigns an openrouter leg to (Chat model routing phase); every
    other caller of this module is unaffected."""
    raw = os.getenv("OPENROUTER_API_KEY", "")
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise RuntimeError("OPENROUTER_API_KEY environment variable is not set")
    return keys


def upload_attachment(file_bytes: bytes, mime_type: str, filename: str) -> dict:
    """
    Upload an image/PDF to Gemini's Files API using the PRIMARY Gemini key only
    (first key in GEMINI_API_KEYS) — deliberately never one of the pooled
    fallback keys.

    Files API uploads are scoped to the API key/project that created them:
    verified live that a file uploaded with key #1 returns 403 PERMISSION_DENIED
    when read by key #2. Since the Gemini fallback-tier leg and the Groq leg can
    therefore never serve an attached file anyway (Groq also has no vision model
    configured here), chat_agent.py builds a primary-key-only agent for any turn
    carrying attachments instead of pretending the pool still applies.

    Returns {uri, mime_type, filename, size_bytes, expires_at} — never the raw
    bytes; callers persist this dict, not the file itself. `expires_at` mirrors
    Gemini's real Files API expiry (confirmed live: exactly 48h after upload).
    """
    key = _gemini_keys()[0]
    client = genai.Client(api_key=key)

    f = client.files.upload(
        file=io.BytesIO(file_bytes),
        config={"mime_type": mime_type, "display_name": filename},
    )
    while f.state.name == "PROCESSING":
        time.sleep(1)
        f = client.files.get(name=f.name)
    if f.state.name != "ACTIVE":
        raise RuntimeError(f"Gemini file upload did not become ACTIVE (state={f.state.name})")

    return {
        "uri":         f.uri,
        "mime_type":   f.mime_type,
        "filename":    filename,
        "size_bytes":  f.size_bytes,
        "expires_at":  f.expiration_time.isoformat() if f.expiration_time else None,
    }


def _is_gemini_3_plus(model_name: str) -> bool:
    """Gemini 3+ models use thinking_level; Gemini 2.5 uses thinking_budget (verified live, see chat_agent.py)."""
    return "gemini-3" in (model_name or "").lower().replace("models/", "")


def _is_gemini_leg(model_name: str) -> bool:
    """True for any Gemini leg (2.5 or 3+); False means Groq — the only other
    provider in this pool. Same ls_model_name signal _is_gemini_3_plus reads."""
    return "gemini" in (model_name or "").lower()


def _thinking_kwargs(model_name: str) -> dict:
    """
    Per-leg thinking config — Gemini generations take different params, confirmed
    live (see chat_agent.py module docstring for the recon). Always the baseline
    (visible reasoning, modest cost) — the "think harder" toggle that used to
    request a deeper budget/level here was removed.
    """
    if _is_gemini_3_plus(model_name):
        return {"thinking_level": "low", "include_thoughts": True}
    return {"thinking_budget": 1024, "include_thoughts": True}


# ── chat_models.toml — the editable chat model lists ──────────────────────────
# The one file a human edits to change which models chat uses. Parsed once per
# process and validated loudly: an unknown provider, an empty list or a code
# list that does not start with a Gemini 3.x model is a configuration bug that
# must surface at startup, not as a 400 mid-turn.

_CHAT_MODELS_PATH = Path(__file__).with_name("chat_models.toml")
_PROVIDERS = ("gemini", "groq", "openrouter")
_ROUTES = ("classifier", "simple", "complex", "code", "image", "explain")
_RETRY_FIELDS = ("retries_per_model", "skip_after_rate_limit_sec",
                 "skip_after_daily_quota_sec", "skip_after_no_credit_sec")


class ChatModelsConfigError(ValueError):
    """chat_models.toml is missing, malformed, or names something unusable."""


@dataclass(frozen=True)
class ModelRef:
    provider: str
    model: str

    def __str__(self) -> str:
        return f"{self.provider}/{self.model}"


@dataclass(frozen=True)
class RouteConfig:
    name: str
    models: tuple[ModelRef, ...]
    max_tokens: int
    reasoning: str                    # "low" | "off"
    timeout_seconds: float | None


@dataclass(frozen=True)
class RetryConfig:
    retries_per_model: int
    skip_after_rate_limit_sec: int
    skip_after_daily_quota_sec: int
    skip_after_no_credit_sec: int


@dataclass(frozen=True)
class ChatModelsConfig:
    routes: dict[str, RouteConfig]
    retry: RetryConfig


def _parse_model_ref(raw, route: str) -> ModelRef:
    if not isinstance(raw, str) or "/" not in raw:
        raise ChatModelsConfigError(f"[{route}] model {raw!r} must look like 'provider/model-id'")
    provider, model = raw.split("/", 1)
    if provider not in _PROVIDERS:
        raise ChatModelsConfigError(
            f"[{route}] unknown provider {provider!r} in {raw!r} — known: {', '.join(_PROVIDERS)}")
    if not model.strip():
        raise ChatModelsConfigError(f"[{route}] model id missing in {raw!r}")
    return ModelRef(provider, model.strip())


def _parse_route(name: str, table: dict) -> RouteConfig:
    models = table.get("models")
    if not isinstance(models, list) or not models:
        raise ChatModelsConfigError(f"[{name}] needs a non-empty models list")
    refs = tuple(_parse_model_ref(m, name) for m in models)

    max_tokens = table.get("max_tokens")
    if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens <= 0:
        raise ChatModelsConfigError(f"[{name}] max_tokens must be a positive integer")

    reasoning = table.get("reasoning", "off")
    if reasoning not in ("low", "off"):
        raise ChatModelsConfigError(f'[{name}] reasoning must be "low" or "off", got {reasoning!r}')

    timeout = table.get("timeout_seconds")
    if timeout is not None and (not isinstance(timeout, (int, float)) or timeout <= 0):
        raise ChatModelsConfigError(f"[{name}] timeout_seconds must be a positive number")

    if name == "code" and not (refs[0].provider == "gemini" and _is_gemini_3_plus(refs[0].model)):
        raise ChatModelsConfigError(
            "[code] the first model must be a Gemini 3.x model — it is the only one that runs code")
    if name == "image" and any(ref.provider != "gemini" for ref in refs):
        raise ChatModelsConfigError("[image] only Gemini can read an attached image")

    return RouteConfig(name=name, models=refs, max_tokens=max_tokens, reasoning=reasoning,
                       timeout_seconds=float(timeout) if timeout else None)


def load_chat_models(path: Path = _CHAT_MODELS_PATH) -> ChatModelsConfig:
    """Parse and validate chat_models.toml. Raises ChatModelsConfigError on
    anything a running server could not act on."""
    try:
        raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ChatModelsConfigError(f"{path} is missing") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ChatModelsConfigError(f"{path} is not valid TOML: {exc}") from exc

    missing = [name for name in (*_ROUTES, "retry") if name not in raw]
    if missing:
        raise ChatModelsConfigError(f"missing section(s) {missing}")
    unknown = sorted(set(raw) - set(_ROUTES) - {"retry"})
    if unknown:
        raise ChatModelsConfigError(
            f"unknown section(s) {unknown} — expected {list(_ROUTES) + ['retry']}")

    retry_table = raw["retry"]
    for field_name in _RETRY_FIELDS:
        value = retry_table.get(field_name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ChatModelsConfigError(f"[retry] {field_name} must be a non-negative integer")

    return ChatModelsConfig(
        routes={name: _parse_route(name, raw[name]) for name in _ROUTES},
        retry=RetryConfig(**{field_name: retry_table[field_name] for field_name in _RETRY_FIELDS}),
    )


@lru_cache(maxsize=1)
def chat_models() -> ChatModelsConfig:
    """The parsed chat_models.toml, read once per process — edit the file, restart."""
    return load_chat_models()


# ── Legs and the fallback loop ────────────────────────────────────────────────
# Every chat call (classifier, answer, explain) walks a route's list the same
# way, so the walking lives here once: skip parked legs, retry a transient
# error, park what failed, move on. Callers only say what one attempt does.

@dataclass(frozen=True)
class LegSpec:
    """One (model, API key) attempt inside a route's list."""
    route: str
    step: int                 # 1-based position of this model in the route's list
    provider: str
    model: str
    key_index: int

    def __str__(self) -> str:
        return f"{self.provider}/{self.model}"


class AllLegsFailed(RuntimeError):
    """Every model in a route's list failed or was already parked."""

    def __init__(self, route: str, notes: list[str]) -> None:
        self.route = route
        self.notes = list(notes)
        super().__init__(f"[{route}] every model failed: {'; '.join(notes) or 'no models available'}")


class PromptTooLargeError(RuntimeError):
    """This prompt cannot fit this leg's budget — try the next leg, don't call it."""
    kind = "budget"


class InvalidOutputError(RuntimeError):
    """The model answered, but not in the shape the caller needs (classifier JSON)."""
    kind = "invalid_output"


def route_legs(route: str) -> list[LegSpec]:
    """Every (model, key) pair for a route, in try order: a model is tried on
    every key of its provider before the next model contributes a leg."""
    config = chat_models().routes[route]
    legs: list[LegSpec] = []
    for step, ref in enumerate(config.models, 1):
        key_count = len(_keys_for_provider(ref.provider))
        if route == "image":
            key_count = 1     # Gemini's Files API scopes an upload to the key that made it
        legs.extend(LegSpec(route, step, ref.provider, ref.model, index) for index in range(key_count))
    return legs


def reasoning_kwargs(provider: str, model: str, reasoning: str) -> dict:
    """The TOML's low/off mapped onto each provider's own parameter — the only
    place this mapping exists. Gemini 3.x and Groq gpt-oss have no off switch."""
    if provider == "gemini":
        if _is_gemini_3_plus(model):
            return {"thinking_level": "low"}
        return {"thinking_budget": 1024 if reasoning == "low" else 0}
    if provider == "groq":
        return {"reasoning_effort": "low"} if "gpt-oss" in model else {}
    if provider == "openrouter":
        return {"reasoning": {"effort": "low"} if reasoning == "low" else {"enabled": False}}
    return {}


def registry_model_name(spec: LegSpec) -> str:
    """The model_registry key for this leg — Gemini entries carry the models/ prefix."""
    if spec.provider == "gemini" and not spec.model.startswith("models/"):
        return f"models/{spec.model}"
    return spec.model


def build_leg(spec: LegSpec, *, streaming: bool = False, thinking: bool = False,
              temperature: float = _TEMPERATURE):
    """One bare chat model for this leg. Bare on purpose: callers attach
    LLMCallLogger per call, because a callback baked onto the model collapses
    per-token streaming (verified live, see this module's history)."""
    config = chat_models().routes[spec.route]
    key = _keys_for_provider(spec.provider)[spec.key_index]
    kwargs: dict = dict(model=spec.model, temperature=temperature, max_retries=0, streaming=streaming)
    kwargs.update(reasoning_kwargs(spec.provider, spec.model, config.reasoning))

    if spec.provider == "gemini":
        kwargs.update(api_key=key, max_output_tokens=config.max_tokens)
        if thinking:
            kwargs["include_thoughts"] = True
        if config.timeout_seconds:
            kwargs["timeout"] = config.timeout_seconds
        return ChatGoogleGenerativeAI(**kwargs)

    if spec.provider == "groq":
        kwargs.update(api_key=key, max_tokens=config.max_tokens)
        if config.timeout_seconds:
            kwargs["request_timeout"] = config.timeout_seconds
        return ChatGroq(**kwargs)

    kwargs.update(openrouter_api_key=key, max_tokens=config.max_tokens)
    if config.timeout_seconds:
        kwargs["request_timeout"] = config.timeout_seconds
    return ChatOpenRouter(**kwargs)


def route_label(route: str, reason: str, notes: list[str]) -> str:
    """The llm_call_log `route` value: what was chosen, why, and what it fell past."""
    label = f"{route} ← {reason}" if reason else route
    return f"{label} · {'; '.join(notes)}" if notes else label


def run_route(route: str, attempt, *, notes: list[str], legs=None):
    """Walk a route's list until one leg starts producing output.

    `attempt(spec)` returns an iterator — a .stream() generator, or a generator
    yielding one parsed result. A failure BEFORE its first item falls through to
    the next leg; a failure after it propagates to the caller, because a
    half-streamed answer must never be silently replaced by a second one.

    `legs` lets a caller keep its own position across calls (the explain popover
    resumes at the next leg after an unparseable answer).

    Returns (spec, iterator) with the first item put back, and appends one note
    per leg it gave up on so the caller can log why it landed where it did.
    """
    retries = chat_models().retry.retries_per_model
    last_exc: BaseException | None = None

    for spec in (legs if legs is not None else iter(route_legs(route))):
        parked = rate_limits.is_skipped(spec.provider, spec.model, spec.key_index)
        if parked:
            notes.append(f"skipped {spec} ({parked})")
            continue
        for try_number in range(retries + 1):
            try:
                iterator = iter(attempt(spec))
                first = next(iterator)
            except StopIteration:
                return spec, iter(())
            except Exception as exc:
                last_exc = exc
                kind = rate_limits.classify_error(exc)
                if kind == "transient" and try_number < retries:
                    logger.warning("[llm] %s leg %s transient (%s) — retrying", route, spec, exc)
                    continue
                rate_limits.record_failure(spec.provider, spec.model, spec.key_index, kind)
                notes.append(f"skipped {spec} ({kind})")
                logger.warning("[llm] %s leg %s failed (%s): %s", route, spec, kind, exc)
                break
            return spec, itertools.chain([first], iterator)

    raise AllLegsFailed(route, notes) from last_exc


def _build_raw_models(
    model: str | None = None, legs: str = "all", streaming: bool = False,
    thinking: bool = False,
) -> list[tuple]:
    """
    One raw model per Gemini key, then Groq — list order is fallback order.
    Returns (model, retry_exception_types) pairs; retry is applied by the caller
    so it can wrap either the plain model or its .with_structured_output() form —
    with_retry() returns a generic Runnable that has no with_structured_output().

    `legs` selects a subset: "all" (default), "gemini" (pool + fallback tier,
    no Groq), or "groq" (Groq leg only). `model` overrides the primary-tier
    model name (Gemini: all but the last pooled key; Groq: the single leg,
    only when legs=="groq").

    `streaming`: when True, each leg is built with streaming=True so
    LangGraph's stream_mode="messages" (and any other token-callback-driven
    consumer) gets real per-token deltas instead of one chunk per call —
    BaseChatModel._should_stream() only routes .invoke()/.stream() through the
    incremental code path when the instance has streaming=True (or an explicit
    stream=True kwarg). Default False preserves every existing non-streaming
    caller's behavior unchanged.

    `thinking`: when True, each Gemini leg gets Gemini's native thinking enabled
    (see _thinking_kwargs) — default False so every existing caller (journey
    planner, writer_provider_router, retrieval_planner, etc.) is unaffected;
    only chat_agent.py opts in.
    """
    pairs = []

    if legs in ("all", "gemini"):
        keys = _gemini_keys()
        for i, key in enumerate(keys):
            is_last_gemini_leg = i == len(keys) - 1
            model_name = GEMINI_FALLBACK_MODEL if is_last_gemini_leg else (model or GEMINI_MODEL)
            gem_kwargs = dict(
                model=model_name,
                api_key=key,
                temperature=_TEMPERATURE,
                max_retries=0,  # our own .with_retry() controls backoff instead
                streaming=streaming,
            )
            if thinking:
                gem_kwargs.update(_thinking_kwargs(model_name))
            gem_model = ChatGoogleGenerativeAI(**gem_kwargs)
            # ChatGoogleGenerativeAI catches google.genai.errors.ClientError internally
            # and re-raises ChatGoogleGenerativeAIError (chained via `from e`) — the raw
            # ClientError never escapes invoke(), so with_retry() must match the wrapper
            # type. GeminiClientError kept too, defensively, in case some path leaks it.
            pairs.append((gem_model, (ChatGoogleGenerativeAIError, GeminiClientError)))
            logger.debug("[llm] registered gemini leg #%d model=%s", i + 1, model_name)

    if legs in ("all", "groq"):
        groq_model_name = model if (legs == "groq" and model) else GROQ_FALLBACK_MODEL
        groq_model = ChatGroq(
            model=groq_model_name,
            api_key=_groq_key(),
            temperature=_TEMPERATURE,
            max_retries=0,
            streaming=streaming,
        )
        pairs.append((groq_model, (GroqRateLimitError,)))
        logger.debug("[llm] registered groq leg model=%s", groq_model_name)

    if not pairs:
        raise ValueError(f"No legs built for legs={legs!r}")

    return pairs


def extract_text(response) -> str:
    """
    Normalize AIMessage.content to a plain string. Groq always returns str;
    Gemini sometimes returns a list of content parts (e.g. [{"type": "text",
    "text": "..."}]) instead — callers doing json.loads(resp.content) need a
    plain string regardless of which leg answered.
    """
    content = response.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(item.get("text", "") or "")
        return "".join(parts)
    return str(content)

    return pairs


def _is_daily_quota_exhausted(exc: BaseException) -> bool:
    """
    Distinguishes a DAILY quota exhaustion (can't recover within any backoff
    window — waiting before retrying/falling through is pure wasted latency)
    from a genuine short-term RPM/TPM rate limit (worth waiting out).

    Gemini: confirmed live (real 429s hit this session) that the error body's
    QuotaFailure.violations[].quotaId names the exact window hit, e.g.
    'GenerateRequestsPerDayPerProjectPerModel-FreeTier' for the daily
    free-tier cap — "PerDay" is Google's own stable substring. A genuine
    RPM/TPM limit would show "...PerMinute..." instead (not seen live this
    session — every real 429 hit was the daily cap).

    Groq: NOT live-verified this session (only ever hit BadRequestError, the
    unrelated schema quirk — see _build_pooled_leg — never a real
    RateLimitError). Best-effort per Groq's documented OpenAI-compatible
    rate-limit message convention (names RPD/TPD for daily caps, RPM/TPM for
    per-minute). Unmatched text keeps today's backoff behavior — a false
    negative here just retries as before; it can never falsely skip backoff
    on a still-recoverable case.
    """
    text = str(exc)
    return "PerDay" in text or "RPD" in text or "TPD" in text or "per day" in text.lower()


class _QuotaAwareRetry(RunnableRetry):
    """
    Same as RunnableRetry, but the retry predicate additionally excludes
    confirmed daily-quota-exhaustion errors (_is_daily_quota_exhausted) — a
    daily cap can't recover between attempts, let alone within a backoff
    window, so retrying it at all (waiting or not) is pure waste; this skips
    straight to _handle_failure/re-raise, no sleep, immediate fallthrough to
    the next fallback leg. Genuine transient errors (RPM/TPM rate limits,
    network hiccups) keep today's exponential-jitter backoff and full retry
    budget, completely unchanged.
    """

    @property
    def _kwargs_retrying(self) -> dict:
        kwargs = super()._kwargs_retrying
        retry_types = self.retry_exception_types

        def _should_retry(exc: BaseException) -> bool:
            # Only a genuinely transient failure is worth a backoff sleep: a
            # daily cap cannot recover inside one, an empty account never will,
            # and a 400 will fail identically on every attempt.
            return isinstance(exc, retry_types) and rate_limits.classify_error(exc) in ("rate_limit", "transient")

        kwargs["retry"] = retry_if_exception(_should_retry)
        return kwargs


def _with_retry(runnable, retry_exception_types: tuple):
    return _QuotaAwareRetry(
        bound=runnable,
        kwargs={},
        config={},
        retry_exception_types=retry_exception_types,
        wait_exponential_jitter=True,
        max_attempt_number=_RETRY_ATTEMPTS,
    )


def get_chat_model(
    model: str | None = None, legs: str = "all", json_mode: bool = False,
    streaming: bool = False,
):
    """
    Gemini key #1 -> key #2 -> ... -> Groq (or a restricted subset per `legs`),
    each leg retried with backoff first. A logging callback is attached by
    default — every call is recorded in llm_call_log. Pass
    call_type/user_id/project_id/day_ref via LangChain's standard
    config={"metadata": {...}} on invoke(); no extra plumbing needed.

    `json_mode=True` requests an OpenAI-style JSON object response on every
    leg (translated internally per-provider).

    `streaming=True` builds each leg with streaming=True so callers using
    .stream()/.astream() (or a LangGraph "messages" stream mode built on top
    of this chain) get real per-token deltas. Default False — every existing
    .invoke()-only caller is unaffected.
    """
    raw_pairs = _build_raw_models(model=model, legs=legs, streaming=streaming)
    built = []
    for m, exc_types in raw_pairs:
        if json_mode:
            m = m.bind(response_format={"type": "json_object"})
        built.append(_with_retry(m, exc_types))
    primary, *fallbacks = built
    chain = primary.with_fallbacks(fallbacks) if fallbacks else primary
    return chain.with_config(callbacks=[LLMCallLogger()])


def get_structured_chat_model(schema, model: str | None = None, legs: str = "all"):
    """Same fallback chain (and default logging) as get_chat_model(), each leg bound to a typed schema."""
    legs_built = [
        _with_retry(m.with_structured_output(schema), exc_types)
        for m, exc_types in _build_raw_models(model=model, legs=legs)
    ]
    primary, *fallbacks = legs_built
    chain = primary.with_fallbacks(fallbacks) if fallbacks else primary
    return chain.with_config(callbacks=[LLMCallLogger()])


# ── Task-based model priority pool (Chat-R3/R4) ──────────────────────────────
# R4 wires this live: chat_agent._build_agent() calls build_pooled_legs()
# directly (bare legs, for its ModelFallbackMiddleware/ModelRetryMiddleware
# construction) when a turn has a task_type; get_chat_model()/
# get_structured_chat_model() above (and every existing caller: Feed's
# writer/journey-planner/retrieval-planner services) are untouched — they
# never pass through this section.
#
# Deliberately NOT sharing _build_raw_models()'s per-leg construction: that
# function bakes in this file's one fixed chain ("last Gemini key uses the
# fallback-tier model" special case) which stays exactly as-is for every
# existing caller. _build_pooled_leg() below is a smaller, separate
# leg-builder for an arbitrary (provider, model_name, key) triple — accepting
# a little duplication of the kwargs dict over risking any change to the
# proven chain above. streaming/thinking kwargs mirror _build_raw_models()'s
# signature so a task-routed leg behaves identically (real per-token deltas,
# Gemini native thinking) to the default chain's legs.

def _keys_for_provider(provider: str) -> list[str]:
    if provider == "gemini":
        return _gemini_keys()
    if provider == "groq":
        return _groq_keys()
    if provider == "openrouter":
        return _openrouter_keys()
    raise ValueError(f"Unknown provider {provider!r}")


def _build_pooled_leg(
    provider: str, model_name: str, key: str, *,
    streaming: bool = False, thinking: bool = False,
    max_tokens: int | None = None,
) -> tuple:
    """One (model_instance, retry_exception_types) leg for a single provider/model/key.

    `max_tokens`: per-call output ceiling override. None (default) leaves every
    provider's own implicit default untouched — unchanged behavior for every
    existing caller. Only chat_router.py's classifier passes an explicit value
    (its structured decision is a handful of short fields; the provider default
    is a generic large-completion ceiling with no relation to that output size).
    """
    if provider == "gemini":
        gem_kwargs = dict(
            model=model_name, api_key=key, temperature=_TEMPERATURE,
            max_retries=0, streaming=streaming,
        )
        if thinking:
            gem_kwargs.update(_thinking_kwargs(model_name))
        if max_tokens is not None:
            gem_kwargs["max_output_tokens"] = max_tokens
        model = ChatGoogleGenerativeAI(**gem_kwargs)
        return model, (ChatGoogleGenerativeAIError, GeminiClientError)
    if provider == "groq":
        groq_kwargs = dict(
            model=model_name, api_key=key, temperature=_TEMPERATURE,
            max_retries=0, streaming=streaming,
        )
        if max_tokens is not None:
            groq_kwargs["max_tokens"] = max_tokens
        model = ChatGroq(**groq_kwargs)
        # groq.BadRequestError: confirmed live (Chat-R4 recon) that small/fast
        # Groq models occasionally stringify a boolean in a structured-output
        # tool call ("false" not false) — Groq's own server-side schema
        # validator 400s before the response reaches LangChain at all (~50% of
        # routing-classifier calls on llama-3.1-8b-instant in the recon
        # sample). Retrying the SAME leg gives the model another generation
        # attempt instead of paying for a fallback leg that (also confirmed
        # live) classifies less reliably for this task.
        return model, (GroqRateLimitError, GroqBadRequestError)
    if provider == "openrouter":
        # openrouter_api_key/openrouter_api_base are ChatOpenRouter's real
        # per-instance fields (confirmed via model_fields introspection —
        # langchain-openrouter, not the older ChatOpenAI+base_url pattern).
        # Exceptions propagate UNWRAPPED from the raw `openrouter` SDK
        # (confirmed live: bad model -> BadRequestResponseError, bad key ->
        # UnauthorizedResponseError, both raw openrouter.errors types, no
        # LangChain-side wrapper) — TooManyRequestsResponseError is that
        # same raw SDK's real 429 class.
        or_kwargs = dict(
            model=model_name, openrouter_api_key=key, temperature=_TEMPERATURE,
            max_retries=0, streaming=streaming,
        )
        if max_tokens is not None:
            or_kwargs["max_tokens"] = max_tokens
        model = ChatOpenRouter(**or_kwargs)
        return model, (TooManyRequestsResponseError,)
    raise ValueError(f"Unknown provider {provider!r}")


def build_pooled_legs(
    model_priority_list: list[tuple[str, str]], *,
    streaming: bool = False, thinking: bool = False,
    max_tokens: int | None = None,
) -> list[tuple]:
    """
    Flatten a (provider, model_name) priority list (see model_priority.
    get_model_priority_list()) into fallback legs, keys-within-model before
    model-drop: every key in a model's pool becomes its own leg, in pool
    order, before the next model in the list contributes any legs. Each leg
    still gets its own retry budget via _with_retry() — a model is only
    "dropped" once every one of its keys has exhausted retries.

    `max_tokens`: see _build_pooled_leg — None (default) is a no-op for every
    caller except chat_router.py's classifier.
    """
    legs = []
    for provider, model_name in model_priority_list:
        for key in _keys_for_provider(provider):
            legs.append(_build_pooled_leg(
                provider, model_name, key,
                streaming=streaming, thinking=thinking,
                max_tokens=max_tokens,
            ))
    return legs


def get_chat_model_for_task(task_type: str):
    """
    Build the model-priority chain for task_type (see model_priority.
    get_model_priority_list()), rotating every key of a model before falling
    to the next model. Same _with_retry()/.with_fallbacks()/LLMCallLogger
    composition as get_chat_model() — admin panel logging and call-tree
    grouping work identically, no new logging code needed.
    """
    from .model_priority import get_model_priority_list

    legs = build_pooled_legs(get_model_priority_list(task_type))
    built = [_with_retry(m, exc_types) for m, exc_types in legs]
    primary, *fallbacks = built
    chain = primary.with_fallbacks(fallbacks) if fallbacks else primary
    return chain.with_config(callbacks=[LLMCallLogger()])


_GROQ_BAD_REQUEST_RETRY_ATTEMPTS = 2  # confirmed live (Chat-R4 verify), see below


def _build_structured_legs(
    schema, task_type: str, *, streaming: bool = False, max_tokens: int | None = None,
    include_raw: bool = False,
) -> list:
    """
    Shared leg-construction for get_structured_chat_model_for_task() and
    get_structured_chat_model_legs_for_task() — same per-leg schema binding
    and Groq stringified-boolean retry treatment either way; only the return
    shape (combined chain vs. individual legs) and with_structured_output's
    include_raw differ between the two public callers.

    `include_raw`: False (default, matches prior behavior) returns the parsed
    schema instance directly and RAISES if the leg's completion doesn't yield
    a valid tool-call for it. True returns {"raw", "parsed", "parsing_error"}
    instead — parsed is None (not a raised exception) on that same failure.
    Needed by get_structured_chat_model_legs_for_task (Phase W): confirmed
    live that at least one model in this pool (nemotron-3-nano) regularly
    completes successfully at the raw-HTTP level but doesn't emit a valid
    tool-call — with include_raw=False that's indistinguishable from every
    other call outcome once wrapped in .with_fallbacks() (no exception means
    no fallback attempt, confirmed live: exactly one llm_call_log row per
    such call), so a caller needing to actually detect and react to this
    failure mode needs the raw dict, not the chain's all-or-nothing shape.
    """
    from .model_priority import get_model_priority_list

    legs = build_pooled_legs(
        get_model_priority_list(task_type), streaming=streaming, max_tokens=max_tokens,
    )
    built = []
    for m, exc_types in legs:
        # Captured before wrapping — every _build_pooled_leg model instance
        # (ChatGoogleGenerativeAI/ChatGroq/ChatOpenRouter) sets .model to the
        # real model_name; tag carried alongside so a caller can dedupe
        # same-model-different-key legs (see get_structured_chat_model_legs_
        # for_task) without introspecting the wrapped Runnable afterward.
        provider = {"ChatGoogleGenerativeAI": "gemini", "ChatGroq": "groq", "ChatOpenRouter": "openrouter"}.get(
            type(m).__name__, type(m).__name__,
        )
        model_name = getattr(m, "model", None)
        structured = m.with_structured_output(schema, include_raw=include_raw)
        if GroqBadRequestError in exc_types:
            structured = structured.with_retry(
                retry_if_exception_type=(GroqBadRequestError,),
                wait_exponential_jitter=False,
                stop_after_attempt=_GROQ_BAD_REQUEST_RETRY_ATTEMPTS,
            )
            exc_types = tuple(t for t in exc_types if t is not GroqBadRequestError)
        if exc_types:
            structured = _with_retry(structured, exc_types)
        built.append((provider, model_name, structured))
    return built


def get_structured_chat_model_for_task(
    schema, task_type: str, *, streaming: bool = False, max_tokens: int | None = None,
):
    """
    Same as get_chat_model_for_task() but each leg bound to a typed schema —
    mirrors get_structured_chat_model()'s pattern.

    Groq legs get a SHORTER, separate retry budget for GroqBadRequestError
    than for GroqRateLimitError, with NO exponential backoff: confirmed live
    (real timestamp gaps, not just latency_ms sums) that the stringified-
    boolean schema quirk (see _build_pooled_leg) is often systematic per
    message, not transient, AND that with_retry()'s default
    wait_exponential_jitter=True inserts a real ~2-3s sleep before each retry
    — irrelevant for a generation quirk (no server-side reason to wait) and
    the dominant cost, not the extra attempt itself. Real session data: the
    original 3-attempt/backoff-on version cost ~7s wall-clock in the worst
    case (attempts summed to ~700ms, backoff gaps ~5s) before still falling
    through to Gemini; 1 retry with backoff still cost ~3.6-4s; 1 retry with
    NO backoff (this version) keeps the ~600-900ms win for transient cases
    and caps the worst case at roughly attempt+attempt+gemini-leg, no
    multi-second sleep in between. GroqRateLimitError (real quota exhaustion)
    keeps the standard _RETRY_ATTEMPTS budget WITH backoff — genuinely
    transient and worth waiting out.
    """
    built = [leg for _, _, leg in _build_structured_legs(schema, task_type, streaming=streaming, max_tokens=max_tokens)]
    primary, *fallbacks = built
    chain = primary.with_fallbacks(fallbacks) if fallbacks else primary
    return chain.with_config(callbacks=[LLMCallLogger()])


def get_structured_chat_model_legs_for_task(
    schema, task_type: str, *, streaming: bool = False, max_tokens: int | None = None,
) -> list[tuple[str, str, object]]:
    """
    Phase W: same legs as get_structured_chat_model_for_task, as an ordered
    list of (provider, model_name, leg) instead of one combined
    .with_fallbacks() chain — each leg already carries its own per-leg retry
    for transient network errors (unchanged) and its own LLMCallLogger, and
    each returns {"raw", "parsed", "parsing_error"} (include_raw=True) rather
    than raising on a structurally-invalid completion. Lets a caller
    (chat_router.py) genuinely retry a DIFFERENT MODEL specifically on that
    failure mode, which .with_fallbacks() cannot react to (see
    _build_structured_legs docstring).

    Deduplicated to (provider, model_name) — first key kept per model,
    subsequent keys of an already-seen model dropped. Confirmed live
    (2026-08-25): OPENROUTER_API_KEY currently holds a 2-key pool, so the raw
    leg list is [nemotron/key1, nemotron/key2, gpt-oss-20b/groq, gemini-lite,
    ...] — a caller retrying "the next leg" positionally would silently
    retry the SAME model that just failed on a different key, which does
    nothing for a structural/generation-shape failure (the failure mode this
    function exists for). Used by chat_router.py's classifier.
    """
    built = _build_structured_legs(
        schema, task_type, streaming=streaming, max_tokens=max_tokens, include_raw=True,
    )
    deduped: list[tuple[str, str, object]] = []
    seen_models: set[tuple[str, str]] = set()
    for provider, model_name, leg in built:
        key = (provider, model_name)
        if key in seen_models:
            continue
        seen_models.add(key)
        deduped.append((provider, model_name, leg.with_config(callbacks=[LLMCallLogger()])))
    return deduped
