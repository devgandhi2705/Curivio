import os
import time
import logging
from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")

from ..config import GROQ_MODEL as MODEL_NAME, GROQ_BASE_URL as BASE_URL

_client: OpenAI | None = None

def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY environment variable is not set")
        _client = OpenAI(api_key=api_key, base_url=BASE_URL, timeout=120.0)
    return _client

logger = logging.getLogger(__name__)


def ask_grok(prompt: str, json_mode: bool = False) -> str:
    # Deferred import avoids a circular dependency at module load time.
    from .api_usage_service import log_api_call, estimate_groq_cost

    t0 = time.monotonic()
    kwargs: dict = dict(
        model=MODEL_NAME,
        messages=[
            {
                "role": "system",
                "content": "You are an AI-powered personalized learning and research assistant.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    try:
        response = _get_client().chat.completions.create(**kwargs)
    except Exception as exc:
        raise RuntimeError(
            f"API request failed for model '{MODEL_NAME}' at '{BASE_URL}': {exc}."
        ) from exc

    duration_ms   = int((time.monotonic() - t0) * 1000)
    usage         = getattr(response, "usage", None)
    input_tokens  = usage.prompt_tokens     if usage else None
    output_tokens = usage.completion_tokens if usage else None
    cost          = estimate_groq_cost(input_tokens or 0, output_tokens or 0)

    log_api_call(
        service="groq",
        operation="chat_completion",
        model=MODEL_NAME,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_ms=duration_ms,
        cache_hit=False,
        query_hint=prompt[:120],
        estimated_cost_usd=cost,
    )

    logger.info(
        "[groq] %dms | in=%s out=%s | cost=$%.6f",
        duration_ms, input_tokens, output_tokens, cost,
    )

    return response.choices[0].message.content


def ask_grok_chat(messages: list[dict]) -> str:
    """
    Send a full OpenAI-format messages list to Groq and return the reply text.
    Unlike ask_grok, the caller is responsible for the system message and history.
    """
    from .api_usage_service import log_api_call, estimate_groq_cost

    t0 = time.monotonic()
    try:
        response = _get_client().chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=0.7,
        )
    except Exception as exc:
        raise RuntimeError(
            f"API request failed for model '{MODEL_NAME}' at '{BASE_URL}': {exc}."
        ) from exc

    duration_ms   = int((time.monotonic() - t0) * 1000)
    usage         = getattr(response, "usage", None)
    input_tokens  = usage.prompt_tokens     if usage else None
    output_tokens = usage.completion_tokens if usage else None
    cost          = estimate_groq_cost(input_tokens or 0, output_tokens or 0)

    log_api_call(
        service="groq",
        operation="chat_conversation",
        model=MODEL_NAME,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_ms=duration_ms,
        cache_hit=False,
        query_hint=(messages[-1].get("content", "") if messages else "")[:120],
        estimated_cost_usd=cost,
    )

    logger.info(
        "[groq_chat] %dms | in=%s out=%s | cost=$%.6f",
        duration_ms, input_tokens, output_tokens, cost,
    )

    return response.choices[0].message.content


def ask_grok_chat_stream(messages: list[dict]):
    """
    Streaming version of ask_grok_chat.

    Yields text chunks as they arrive from the Groq API.
    Logs usage after the stream is fully consumed.
    """
    from .api_usage_service import log_api_call, estimate_groq_cost

    t0 = time.monotonic()
    try:
        stream = _get_client().chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=0.7,
            stream=True,
            stream_options={"include_usage": True},
        )
    except Exception as exc:
        raise RuntimeError(
            f"API request failed for model '{MODEL_NAME}' at '{BASE_URL}': {exc}."
        ) from exc

    input_tokens  = None
    output_tokens = None

    for chunk in stream:
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta and delta.content:
            yield delta.content
        # Usage arrives in the final chunk when stream_options include_usage is set
        if getattr(chunk, "usage", None):
            usage         = chunk.usage
            input_tokens  = getattr(usage, "prompt_tokens",     None)
            output_tokens = getattr(usage, "completion_tokens", None)

    duration_ms = int((time.monotonic() - t0) * 1000)
    cost        = estimate_groq_cost(input_tokens or 0, output_tokens or 0)

    log_api_call(
        service="groq",
        operation="chat_stream",
        model=MODEL_NAME,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_ms=duration_ms,
        cache_hit=False,
        query_hint=(messages[-1].get("content", "") if messages else "")[:120],
        estimated_cost_usd=cost,
    )

    logger.info(
        "[groq_stream] %dms | in=%s out=%s | cost=$%.6f",
        duration_ms, input_tokens, output_tokens, cost,
    )
