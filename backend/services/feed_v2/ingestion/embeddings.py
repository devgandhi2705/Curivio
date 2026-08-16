"""
Feed v2 embeddings — the raw google-genai SDK (client.models.embed_content),
the SAME client provider.py uses for chat legs. Phase 4b switched off the
LangChain wrapper (GoogleGenerativeAIEmbeddings): Phase 3 chose the raw SDK on
purpose so LangChain's own retry/fallback machinery never sits underneath v2's
own retry logic; the embedding path now matches.

Model gemini-embedding-001 at output_dimensionality=3072 → matches the
v2_material_chunks_vec float[3072] shadow (live-verified: 3072-dim, one embedding
per input, order preserved).

BATCHING (Phase 4 step 5): EMBED_BATCH_SIZE=25 — the size the chat path settled
on after its 1,554-sequential-call incident. Unrelated to which client makes the
call, so it's unchanged. embed_content sends the whole batch in ONE request, so N
chunks cost ceil(N/25) requests; 25 caps a failed batch's lost-progress at 25
chunks.
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ....config import GEMINI_EMBEDDING_MODEL

load_dotenv(dotenv_path=Path(__file__).resolve().parents[4] / ".env")

logger = logging.getLogger(__name__)

EMBED_BATCH_SIZE = int(os.getenv("FEED_V2_EMBED_BATCH_SIZE", "25"))
_OUTPUT_DIM = 3072  # matches v2_material_chunks_vec float[3072]


def _gemini_key() -> str:
    raw = os.getenv("GEMINI_API_KEYS", "") or os.getenv("GEMINI_API_KEY", "")
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise RuntimeError("GEMINI_API_KEYS or GEMINI_API_KEY is not set")
    return keys[0]


@lru_cache(maxsize=1)
def _client() -> genai.Client:
    return genai.Client(api_key=_gemini_key())


_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(genai_errors.APIError),  # 4xx/5xx incl. 429 — bounded to 3
    reraise=True,
)


@_retry
def _embed_one_batch(chunks: list[str]) -> list[list[float]]:
    resp = _client().models.embed_content(
        model=GEMINI_EMBEDDING_MODEL,
        contents=chunks,
        config=types.EmbedContentConfig(output_dimensionality=_OUTPUT_DIM),
    )
    # One embedding per input, in order (live-verified).
    return [list(e.values) for e in resp.embeddings]


def embed_texts(texts: list[str]):
    """Yield (batch_start_index, batch_texts, batch_embeddings) for each batch of
    up to EMBED_BATCH_SIZE texts. A generator so callers can persist each batch
    incrementally (one commit per batch)."""
    for start in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[start:start + EMBED_BATCH_SIZE]
        yield start, batch, _embed_one_batch(batch)


def embed_query(text: str) -> list[float]:
    return _embed_one_batch([text])[0]
