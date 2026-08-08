"""
Chat-R6a — document chunk storage + retrieval-trimmed context for uploaded
PDF/docx/csv/text/code attachments.

Mirrors vector_memory_service.py's schema convention (vec0 virtual table,
embedding + TEXT aux columns, cosine-distance search) but scoped by
attachment_id instead of user_id — the upload endpoint (main.py's
/chat/upload) runs before a session_id exists, so attachment_id (minted here)
is the only real scope available at storage time.

Storage: document_chunks_vec (vec0 virtual table, backend/database/schema.py)

Public API
----------
store_document(filename, text) -> attachment_id
store_document_stream(filename, text) -> generator yielding progress dicts
    Chat-R19c: same work as store_document (which just drains this), but
    yields a dict after each embedding batch — for /chat/upload's NDJSON
    stream. See its docstring for the exact event shapes.
get_context(attachment_id, filename, query_text, token_budget=3000) -> str
    Full extracted text when it fits token_budget; otherwise the top
    semantically-relevant chunks for query_text (Chat-3's get_embedding/search
    pattern, reused not reimplemented).
get_full_text(attachment_id) -> str | None
    Full extracted text, chunks rejoined in reading order, no budget trim —
    for preview/download (Chat-R10), not prompt injection. None if the
    attachment_id has no stored chunks.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from ..llm.embeddings import get_embedding, get_embeddings_batch, rate_limited_last_call, reset_rate_limit_flag
from ..utils.db import get_connection
from .token_budget import estimate_tokens

logger = logging.getLogger(__name__)

_CHUNK_CHARS = 800    # ~200 tokens/chunk at the project's 4-chars/token heuristic
# Chat-R19b: chunks per get_embeddings_batch() call. A 1554-chunk document
# (the real one that crashed R19a) needs ceil(1554/25)=63 requests at this
# size — comfortably under Gemini's confirmed 100 req/min free-tier ceiling
# with margin for retries — while keeping a single failed batch's lost-
# progress blast radius to 25 chunks, not the library's max of 100.
_EMBED_BATCH_SIZE = 25
_TOP_K = 5
# Looser than vector_memory_service's 0.35 — retrieval here only ever competes
# against chunks of the SAME document (attachment_id-scoped), not the whole
# corpus, so a marginal chunk merely lacks relevance rather than crossing documents.
_MAX_DISTANCE = 0.6


def _chunk_text(text: str) -> list[str]:
    """Paragraph-bounded chunks up to _CHUNK_CHARS; hard-splits any paragraph
    that alone exceeds the limit (e.g. a minified file with no blank lines)."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if current and len(current) + len(para) + 2 > _CHUNK_CHARS:
            chunks.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
        while len(current) > _CHUNK_CHARS:
            chunks.append(current[:_CHUNK_CHARS])
            current = current[_CHUNK_CHARS:]
    if current:
        chunks.append(current)
    return chunks or [text[:_CHUNK_CHARS]]


def store_document_stream(filename: str, text: str):
    """
    Chunk, embed, and store extracted document text — yields progress dicts
    as each embedding batch completes, for /chat/upload's NDJSON stream
    (Chat-R19c). store_document() below just drains this and returns the
    final attachment_id, so every pre-existing caller is unaffected.

    Yields, in order:
      {"stage": "rate_limited", "batch": N, "total_batches": M}
          Only when that batch's get_embeddings_batch call retried at least
          once due to Gemini's RESOURCE_EXHAUSTED ceiling (R19b) — omitted
          entirely on a normal batch, so it stays a genuinely distinct
          signal rather than noise on every batch.
      {"stage": "embedding", "batch": N, "total_batches": M}
          After batch N's embeddings are committed. One per batch, always.
      {"stage": "done", "attachment_id": <id>}
          Exactly once, last.

    Chat-R19b: embeds+inserts in groups of _EMBED_BATCH_SIZE chunks via
    get_embeddings_batch (real server-side batching — one embed_content
    request per group, not one per chunk) instead of R19a's one-request-
    per-chunk loop. Same request cost now buys _EMBED_BATCH_SIZE chunks
    instead of 1 — the 1554-chunk document that crashed R19a on Gemini's
    100 req/min free-tier ceiling needs ~63 requests at this batch size.

    Each group's embeddings are inserted together in one get_connection()
    call/commit — get_connection() rolls back everything inside its own
    `with` block on exception, so a group failing its embedding call loses
    only that group's chunks, never a group that already committed. Same
    incremental-persistence philosophy as R19a, now at batch granularity
    (a failed batch's chunks are lost together — embed_documents has no
    partial-batch-failure result — instead of R19a's per-chunk granularity;
    _EMBED_BATCH_SIZE=25 keeps that loss small even in the worst case).
    """
    attachment_id = uuid.uuid4().hex
    chunks = _chunk_text(text)
    total_batches = -(-len(chunks) // _EMBED_BATCH_SIZE)  # ceil division
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    for batch_start in range(0, len(chunks), _EMBED_BATCH_SIZE):
        batch = chunks[batch_start:batch_start + _EMBED_BATCH_SIZE]
        batch_num = batch_start // _EMBED_BATCH_SIZE + 1
        reset_rate_limit_flag()
        embeddings = get_embeddings_batch(batch)
        if rate_limited_last_call():
            yield {"stage": "rate_limited", "batch": batch_num, "total_batches": total_batches}
        with get_connection() as conn:
            for offset, (chunk, embedding) in enumerate(zip(batch, embeddings)):
                conn.execute(
                    """INSERT INTO document_chunks_vec
                           (embedding, attachment_id, filename, chunk_index, chunk_text, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (json.dumps(embedding), attachment_id, filename, str(batch_start + offset), chunk, created_at),
                )
        yield {"stage": "embedding", "batch": batch_num, "total_batches": total_batches}
    yield {"stage": "done", "attachment_id": attachment_id}


def store_document(filename: str, text: str) -> str:
    """Chunk, embed, and store extracted document text. Returns a new
    attachment_id. Drains store_document_stream() — see its docstring for
    the real batching/durability behavior; this just discards the progress
    events."""
    *_, last = store_document_stream(filename, text)
    return last["attachment_id"]


def _all_chunks(attachment_id: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT chunk_index, chunk_text FROM document_chunks_vec
               WHERE attachment_id = ? ORDER BY CAST(chunk_index AS INTEGER)""",
            (attachment_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _search_chunks(attachment_id: str, query_text: str, top_k: int = _TOP_K) -> list[dict]:
    query_vec = get_embedding(query_text)
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT chunk_index, chunk_text,
                      vec_distance_cosine(embedding, ?) AS distance
               FROM   document_chunks_vec
               WHERE  attachment_id = ?
               ORDER  BY distance ASC
               LIMIT  ?""",
            (json.dumps(query_vec), attachment_id, top_k),
        ).fetchall()
    return [dict(r) for r in rows if r["distance"] < _MAX_DISTANCE]


def get_full_text(attachment_id: str) -> str | None:
    """Full extracted text for preview/download — no query bias, no token_budget
    trim (unlike get_context, which exists to fit a prompt). None if this
    attachment_id has no stored chunks."""
    chunks = _all_chunks(attachment_id)
    if not chunks:
        return None
    return "\n\n".join(c["chunk_text"] for c in chunks)


def get_context(attachment_id: str, filename: str, query_text: str, token_budget: int = 3000) -> str:
    """
    Full document text when it fits token_budget; otherwise the top
    semantically-relevant chunks for query_text, restored to reading order.
    Non-fatal: returns an honest note instead of raising on any error.
    """
    try:
        chunks = _all_chunks(attachment_id)
        if not chunks:
            return f"[Document '{filename}': no extracted content found.]"

        full_text = "\n\n".join(c["chunk_text"] for c in chunks)
        if estimate_tokens(full_text) <= token_budget:
            return f"[Document '{filename}', full text:]\n{full_text}"

        hits = _search_chunks(attachment_id, query_text) or chunks[:_TOP_K]
        hits = sorted(hits, key=lambda c: int(c["chunk_index"]))
        excerpt = "\n\n".join(c["chunk_text"] for c in hits)
        return (
            f"[Document '{filename}' is long — showing the {len(hits)} most "
            f"relevant excerpts out of {len(chunks)} total:]\n{excerpt}"
        )
    except Exception:
        logger.exception(
            "document_memory_service: get_context failed for attachment %r (non-fatal)", attachment_id
        )
        return f"[Document '{filename}': content temporarily unavailable.]"
