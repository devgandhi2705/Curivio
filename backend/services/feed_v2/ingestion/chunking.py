"""
Feed v2 chunking + embedding — extracted text (documents, image descriptions,
link content) → v2_material_chunks rows with embeddings in the
v2_material_chunks_vec shadow (Phase 3).

Chunking mirrors the chat path's paragraph-bounded 800-char strategy. Embedding
is BATCHED via ingestion.embeddings.embed_texts (25/batch — see that module for
the 1,554-call rationale). Each batch's chunk rows + vec rows commit together in
ONE get_connection() block, so a failed batch loses only its own chunks and
never a batch already persisted — and chunk count always equals embedding count
(they're written in the same transaction, or neither is).
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from ..db import get_connection
from .embeddings import embed_texts

logger = logging.getLogger(__name__)

_CHUNK_CHARS = 800  # ~200 tokens/chunk at the project's 4-chars/token heuristic


def chunk_text(text: str) -> list[str]:
    """Paragraph-bounded chunks up to _CHUNK_CHARS; hard-splits any single
    paragraph that alone exceeds the limit (e.g. a minified file)."""
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
    return chunks or ([text[:_CHUNK_CHARS]] if text.strip() else [])


def _store_chunks(material_id: str, user_id: str, project_id: str | None,
                  pairs: list[tuple[int | None, str]]) -> dict:
    """Embed + store a list of (page_no, chunk_text) pairs. One transaction per batch
    so a failed batch loses only its own chunks. Returns {"chunk_count",
    "embedding_count"} — equal by construction. page_no is NULL for sources with no
    page concept (docx/txt/md/image/link)."""
    if not pairs:
        return {"chunk_count": 0, "embedding_count": 0}

    page_nos = [p for p, _ in pairs]
    chunks = [c for _, c in pairs]
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    written = 0
    for start, batch, embeddings in embed_texts(chunks):
        with get_connection() as conn:
            for offset, (chunk, embedding) in enumerate(zip(batch, embeddings)):
                idx = start + offset
                chunk_id = uuid.uuid4().hex
                conn.execute(
                    """INSERT INTO v2_material_chunks
                           (chunk_id, user_id, material_id, project_id, chunk_index, page_no, chunk_text, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (chunk_id, user_id, material_id, project_id, idx, page_nos[idx], chunk, created_at),
                )
                conn.execute(
                    """INSERT INTO v2_material_chunks_vec
                           (embedding, chunk_id, material_id, project_id, user_id, chunk_text, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (json.dumps(embedding), chunk_id, material_id, project_id, user_id, chunk, created_at),
                )
        written += len(batch)

    # chunk_count == embedding_count by construction (same transaction per batch).
    return {"chunk_count": written, "embedding_count": written}


def chunk_and_embed(material_id: str, user_id: str, project_id: str | None, text: str) -> dict:
    """Flat text, no page info — docx / txt / md / image-description / link. Every
    chunk stores page_no=NULL (no false precision where the source has no pages)."""
    return _store_chunks(material_id, user_id, project_id,
                         [(None, c) for c in chunk_text(text)])


def chunk_and_embed_pages(material_id: str, user_id: str, project_id: str | None,
                          pages: list[dict]) -> dict:
    """Page-aware path for PDFs. Chunks WITHIN each page's text so a chunk never spans
    a page boundary and its page_no is exact. Tradeoff (Phase 8b, deliberate): a
    page's final chunk may fall short of _CHUNK_CHARS rather than being padded with
    the next page's text — an exact page_no per chunk is worth an occasional small
    trailing chunk. pypdf already splits a paragraph that crosses pages into two
    pages, so no real paragraph is reconstructed across the boundary here."""
    pairs = [(pg.get("page_no"), c)
             for pg in pages for c in chunk_text(pg.get("text") or "")]
    return _store_chunks(material_id, user_id, project_id, pairs)
