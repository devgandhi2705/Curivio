"""
Gemini embedding helper — LangChain foundation, Step 3.

Additive-only, parallel to the existing hand-rolled call sites. Plumbing for
later vector-search phases; no application vector schema lives here.

Chat-R19a: get_embedding_model() is cached (@lru_cache) — mirrors
r2_storage_service._client()'s convention for the same problem (expensive
client, no per-call reason to rebuild it: the key isn't rotated, nothing
about this client is request-scoped). Before this fix every get_embedding()
call opened a fresh connection, paying a full handshake each time — real
measured cost, see backend/services/document_memory_service.py's docstring.

get_embedding()/get_embeddings_batch() retry on GoogleGenerativeAIError
(transient connection failures — real-world observed: "Server disconnected
without sending a response") via tenacity, not model_provider.py's
RunnableRetry: confirmed GoogleGenerativeAIEmbeddings is not a Runnable and
has no with_retry(), so that machinery doesn't apply here. tenacity is
already a project dependency (model_provider.py). Both functions share the
same _embedding_retry decorator — one retry policy, not two copies of it.

Chat-R19b: get_embeddings_batch() is the real fix for R19a's still-real
per-chunk request volume — embed_documents() sends up to `batch_size` texts
in ONE embed_content request (confirmed by reading langchain_google_genai's
source: it calls self.client.models.embed_content once per batch with
contents=<the whole batch>, not once per text). document_memory_service
calls this per group of chunks instead of get_embedding() per chunk.

Public API
----------
get_embedding_model() -> GoogleGenerativeAIEmbeddings
get_embedding(text)   -> list[float]
get_embeddings_batch(chunks) -> list[list[float]]
"""
from __future__ import annotations

import contextvars
import logging
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_google_genai._common import GoogleGenerativeAIError
from tenacity import before_sleep_log, retry, retry_if_exception_type, stop_after_attempt, wait_exponential

load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")

from ..config import GEMINI_EMBEDDING_MODEL

logger = logging.getLogger(__name__)


def _gemini_key() -> str:
    raw = os.getenv("GEMINI_API_KEYS", "")
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise RuntimeError("GEMINI_API_KEYS environment variable is not set")
    return keys[0]


@lru_cache(maxsize=1)
def get_embedding_model() -> GoogleGenerativeAIEmbeddings:
    return GoogleGenerativeAIEmbeddings(model=GEMINI_EMBEDDING_MODEL, google_api_key=_gemini_key())


_rate_limited = contextvars.ContextVar("embeddings_rate_limited", default=False)


def _is_rate_limit_error(exc: BaseException) -> bool:
    """Gemini's RESOURCE_EXHAUSTED (R19b's 100 req/min free-tier ceiling).
    Checked on __cause__.status first — langchain_google_genai's
    embed_documents wraps the real google.genai ClientError into
    GoogleGenerativeAIError via `raise GoogleGenerativeAIError(f"Error
    embedding content ({e.status}): {e}") from e` (confirmed by reading its
    source), so the original ClientError.status ("RESOURCE_EXHAUSTED" for a
    429) survives as __cause__. Message-string check as a fallback in case
    __cause__ isn't preserved."""
    cause = exc.__cause__
    if getattr(cause, "status", None) == "RESOURCE_EXHAUSTED":
        return True
    return "RESOURCE_EXHAUSTED" in str(exc)


def _before_sleep(retry_state) -> None:
    exc = retry_state.outcome.exception()
    if exc is not None and _is_rate_limit_error(exc):
        _rate_limited.set(True)
    before_sleep_log(logger, logging.WARNING)(retry_state)


_embedding_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(GoogleGenerativeAIError),
    before_sleep=_before_sleep,
    reraise=True,
)


@_embedding_retry
def get_embedding(text: str) -> list[float]:
    return get_embedding_model().embed_query(text)


@_embedding_retry
def get_embeddings_batch(chunks: list[str]) -> list[list[float]]:
    """One real embed_content request for the whole batch (order-preserving,
    one embedding per chunk) — batch_size=len(chunks) so embed_documents
    doesn't further split what's already been pre-sized by the caller."""
    return get_embedding_model().embed_documents(chunks, batch_size=len(chunks))


def reset_rate_limit_flag() -> None:
    """Chat-R19c: call immediately before a get_embeddings_batch() whose
    rate-limit status the caller wants to check afterward via
    rate_limited_last_call() — both calls happen in the same call stack
    (tenacity's retry loop is synchronous, no thread handoff), so this is
    safe without any locking."""
    _rate_limited.set(False)


def rate_limited_last_call() -> bool:
    """True if the get_embeddings_batch() call since the last
    reset_rate_limit_flag() retried at least once because of Gemini's
    RESOURCE_EXHAUSTED ceiling (R19b) — regardless of whether it eventually
    succeeded. Lets streaming callers (document_memory_service.
    store_document_stream) tell a real rate-limit pause apart from a
    generic transient retry, which stays invisible."""
    return _rate_limited.get()
