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
store_document(filename, text, pages=None) -> attachment_id
store_document_stream(filename, text, pages=None) -> generator yielding progress dicts
    Chat-R19c: same work as store_document (which just drains this), but
    yields a dict after each embedding batch — for /chat/upload's NDJSON
    stream. See its docstring for the exact event shapes.
    pages: citation grounding (same fix pattern as feed_v2 Phase 8b) —
    [{"page_no": int, "text": str}, ...] for PDFs, chunked WITHIN each page
    so page_no is exact. None (the default) -> flat chunking, page_no=NULL
    for every chunk — used for docx/plain-text (no real page concept) and
    by any caller that doesn't have per-page extraction.
get_context(attachment_id, filename, query_text, token_budget=3000) -> str
    Full extracted text when it fits token_budget; otherwise the top
    semantically-relevant chunks for query_text (Chat-3's get_embedding/search
    pattern, reused not reimplemented). Inserts a "--- Page N ---" marker on
    each page transition so the model can cite a real page number; chunks
    with page_no=NULL join exactly as before, no markers.
get_full_text(attachment_id) -> str | None
    Full extracted text, chunks rejoined in reading order, no budget trim —
    for preview/download (Chat-R10), not prompt injection. None if the
    attachment_id has no stored chunks.
list_session_documents(session_id) -> list[dict]
    Document persistence: every document ever attached to session_id
    ({attachment_id, filename}), oldest first — for reinjecting on later
    turns without re-upload.
is_relevant(attachment_id, query_text) -> bool
    Document persistence: True if query_text has at least one chunk within
    _MAX_DISTANCE for this document — the gate for WHETHER to reinject a
    prior-turn document, not just how much of it (get_context's own
    fallback always returns something once called; this decides whether
    to call it at all).
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


def _chunk_pairs(text: str, pages: list[dict] | None) -> list[tuple[int | None, str]]:
    """
    Citation grounding: (page_no, chunk_text) pairs. Same fix shape as
    feed_v2's Phase 8b chunk_and_embed_pages — chunk WITHIN each page's text
    so a chunk never spans a page boundary and its page_no is exact. A
    page's final chunk may fall short of _CHUNK_CHARS rather than being
    padded with the next page's text (deliberate, same tradeoff Phase 8b
    made: exact page numbers over evenly-sized chunks).

    pages=None (docx/plain-text — no real page concept, or PDF extraction
    predating this fix) -> flat chunking, every chunk page_no=None. No
    fabricated precision.
    """
    if not pages:
        return [(None, c) for c in _chunk_text(text)]
    pairs: list[tuple[int | None, str]] = []
    for page in pages:
        page_text = (page.get("text") or "").strip()
        if not page_text:
            continue  # blank/image-only page within an otherwise-fine PDF — nothing to chunk
        page_no = page.get("page_no")
        pairs.extend((page_no, c) for c in _chunk_text(page_text))
    return pairs


def store_document_stream(filename: str, text: str, pages: list[dict] | None = None):
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
    pairs = _chunk_pairs(text, pages)
    total_batches = -(-len(pairs) // _EMBED_BATCH_SIZE)  # ceil division
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    for batch_start in range(0, len(pairs), _EMBED_BATCH_SIZE):
        batch = pairs[batch_start:batch_start + _EMBED_BATCH_SIZE]
        batch_num = batch_start // _EMBED_BATCH_SIZE + 1
        reset_rate_limit_flag()
        embeddings = get_embeddings_batch([chunk for _, chunk in batch])
        if rate_limited_last_call():
            yield {"stage": "rate_limited", "batch": batch_num, "total_batches": total_batches}
        with get_connection() as conn:
            for offset, ((page_no, chunk), embedding) in enumerate(zip(batch, embeddings)):
                conn.execute(
                    """INSERT INTO document_chunks_vec
                           (embedding, attachment_id, filename, chunk_index, page_no, chunk_text, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (json.dumps(embedding), attachment_id, filename, str(batch_start + offset), page_no, chunk, created_at),
                )
        yield {"stage": "embedding", "batch": batch_num, "total_batches": total_batches}
    yield {"stage": "done", "attachment_id": attachment_id}


def store_document(filename: str, text: str, pages: list[dict] | None = None) -> str:
    """Chunk, embed, and store extracted document text. Returns a new
    attachment_id. Drains store_document_stream() — see its docstring for
    the real batching/durability behavior; this just discards the progress
    events."""
    *_, last = store_document_stream(filename, text, pages=pages)
    return last["attachment_id"]


def _all_chunks(attachment_id: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT chunk_index, page_no, chunk_text FROM document_chunks_vec
               WHERE attachment_id = ? ORDER BY CAST(chunk_index AS INTEGER)""",
            (attachment_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _search_chunks(attachment_id: str, query_text: str, top_k: int = _TOP_K) -> list[dict]:
    query_vec = get_embedding(query_text)
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT chunk_index, page_no, chunk_text,
                      vec_distance_cosine(embedding, ?) AS distance
               FROM   document_chunks_vec
               WHERE  attachment_id = ?
               ORDER  BY distance ASC
               LIMIT  ?""",
            (json.dumps(query_vec), attachment_id, top_k),
        ).fetchall()
    return [dict(r) for r in rows if r["distance"] < _MAX_DISTANCE]


def _join_with_page_markers(chunks: list[dict]) -> str:
    """Join chunk_text in order, inserting a '--- Page N ---' marker whenever
    page_no changes so the model can cite a real page number. Chunks with
    page_no=None (non-PDF, or pre-citation-grounding data) join exactly as
    before — no markers, byte-identical to the pre-fix output."""
    parts: list[str] = []
    last_page: object = "_unset_"
    for c in chunks:
        page_no = c.get("page_no")
        if page_no is not None and page_no != last_page:
            parts.append(f"--- Page {page_no} ---")
        last_page = page_no
        parts.append(c["chunk_text"])
    return "\n\n".join(parts)


def get_full_text(attachment_id: str) -> str | None:
    """Full extracted text for preview/download — no query bias, no token_budget
    trim (unlike get_context, which exists to fit a prompt). None if this
    attachment_id has no stored chunks."""
    chunks = _all_chunks(attachment_id)
    if not chunks:
        return None
    return "\n\n".join(c["chunk_text"] for c in chunks)


def list_session_documents(session_id: str) -> list[dict]:
    """
    Document persistence: every document ever attached to session_id, oldest
    first — [{"attachment_id": str, "filename": str}, ...].

    Sourced from document_attachment_sessions, NOT chat_messages.attachments —
    the latter is pruned by chat_service.sweep_expired_attachments() once the
    original file's R2 retention window passes, even though this document's
    chunks below survive forever (see CREATE_DOCUMENT_ATTACHMENT_SESSIONS in
    schema.py). Using the JSON column here would silently stop listing a
    document the moment its original upload expired, despite its extracted
    text remaining fully queryable.
    """
    if not session_id:
        return []
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT attachment_id FROM document_attachment_sessions "
            "WHERE session_id = ? ORDER BY rowid ASC",
            (session_id,),
        ).fetchall()
        result: list[dict] = []
        for r in rows:
            aid = r["attachment_id"]
            fn_row = conn.execute(
                "SELECT filename FROM document_chunks_vec WHERE attachment_id = ? LIMIT 1",
                (aid,),
            ).fetchone()
            if fn_row:
                result.append({"attachment_id": aid, "filename": fn_row["filename"]})
    return result


def is_relevant(attachment_id: str, query_text: str) -> bool:
    """
    Document persistence: True if query_text has at least one chunk within
    _MAX_DISTANCE for this document. The same signal _search_chunks/get_context
    already use internally, exposed standalone so a caller can decide WHETHER
    to reinject a prior-turn document before spending a get_context() call —
    get_context() itself always returns something once called (full text, or
    its own chunks[:_TOP_K] last-resort fallback when nothing matches), which
    is correct for a document attached this turn but wrong for silently
    reinjecting an unrelated document from three turns ago.
    """
    if not attachment_id or not query_text or not query_text.strip():
        return False
    try:
        return bool(_search_chunks(attachment_id, query_text, top_k=1))
    except Exception:
        logger.exception(
            "document_memory_service: is_relevant failed for attachment %r (non-fatal)", attachment_id
        )
        return False


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

        full_text = _join_with_page_markers(chunks)
        if estimate_tokens(full_text) <= token_budget:
            return f"[Document '{filename}', full text:]\n{full_text}"

        hits = _search_chunks(attachment_id, query_text) or chunks[:_TOP_K]
        hits = sorted(hits, key=lambda c: int(c["chunk_index"]))
        excerpt = _join_with_page_markers(hits)
        return (
            f"[Document '{filename}' is long — showing the {len(hits)} most "
            f"relevant excerpts out of {len(chunks)} total:]\n{excerpt}"
        )
    except Exception:
        logger.exception(
            "document_memory_service: get_context failed for attachment %r (non-fatal)", attachment_id
        )
        return f"[Document '{filename}': content temporarily unavailable.]"
