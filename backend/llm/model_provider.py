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
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai.errors import ClientError as GeminiClientError
from groq import RateLimitError as GroqRateLimitError
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError
from langchain_groq import ChatGroq

load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")

from ..config import GEMINI_MODEL, GEMINI_FALLBACK_MODEL, GROQ_FALLBACK_MODEL
from .call_logger import LLMCallLogger

logger = logging.getLogger(__name__)

_RETRY_ATTEMPTS = 3
_TEMPERATURE = 0.7


def _gemini_keys() -> list[str]:
    raw = os.getenv("GEMINI_API_KEYS", "")
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise RuntimeError("GEMINI_API_KEYS environment variable is not set")
    return keys


def _groq_key() -> str:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY environment variable is not set")
    return api_key


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


def _thinking_kwargs(model_name: str, extended: bool) -> dict:
    """
    Per-leg thinking config — Gemini generations take different params, confirmed
    live (see chat_agent.py module docstring for the recon). `extended=False` is
    the always-on baseline (visible reasoning, modest cost); `extended=True` is
    the opt-in "think harder" toggle.
    """
    if _is_gemini_3_plus(model_name):
        return {"thinking_level": "high" if extended else "low", "include_thoughts": True}
    return {"thinking_budget": -1 if extended else 1024, "include_thoughts": True}


def _build_raw_models(
    model: str | None = None, legs: str = "all", streaming: bool = False,
    thinking: bool = False, extended_thinking: bool = False,
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
    only chat_agent.py opts in. `extended_thinking` selects the deeper budget/
    level within that (ignored when thinking=False).
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
                gem_kwargs.update(_thinking_kwargs(model_name, extended_thinking))
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


def _with_retry(runnable, retry_exception_types: tuple):
    return runnable.with_retry(
        retry_if_exception_type=retry_exception_types,
        wait_exponential_jitter=True,
        stop_after_attempt=_RETRY_ATTEMPTS,
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
