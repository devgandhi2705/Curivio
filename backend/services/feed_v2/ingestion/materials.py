"""
Feed v2 ingestion orchestrator — the single entry the rest of v2 calls to turn a
document / image / link into a v2_materials row plus its chunks, embeddings, and
figures.

Per-material failure isolation (step 7): a material that fails extraction is
written with extraction_status='failed' + extraction_error and returns normally —
it never raises out of here, so one corrupt file can't wedge the project or block
the next material. This is the same class of bug as the legacy never-reaped
'generating' stub; a failed material is a terminal 'failed' row, not a hang.

coverage_mode SIGNAL (step 6): document count (COUNT(*) per project), type
(the `type` column), and whether real structure was found (has_structure /
section_count) are stored as QUERYABLE COLUMNS on v2_materials — not buried in
structure_json — so Phase 5's profile agent can filter material_bound vs
material_anchored without parsing JSON.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..db import get_connection
from . import chunking, documents, figures, images, links

logger = logging.getLogger(__name__)

_DOC_EXTS = documents.DOCUMENT_EXTENSIONS
_IMAGE_EXTS = {".png", ".jpg", ".jpeg"}


def _insert_material(*, material_id, user_id, project_id, type_, filename, url, sha256,
                     status, byte_size, structure, error, storage_status=None):
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO v2_materials
                   (material_id, user_id, project_id, type, filename, url, sha256,
                    extraction_status, byte_size, structure_json, has_structure,
                    section_count, extraction_error, storage_status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (material_id, user_id, project_id, type_, filename, url, sha256,
             status, byte_size, json.dumps(structure) if structure else None,
             1 if structure else 0, len(structure) if structure else 0, error, storage_status,
             datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")),
        )


def _set_storage_status(material_id, storage_status):
    with get_connection() as conn:
        conn.execute("UPDATE v2_materials SET storage_status = ? WHERE material_id = ?",
                     (storage_status, material_id))


def _figure_storage_status(figs) -> str:
    """FLAG 2: 'ok' when there's nothing to store or every figure image stored;
    'degraded' when ≥1 figure image failed to upload to R2 (text fine, some assets
    unretrievable). Distinct from extraction_status/extraction_error."""
    if not figs:
        return "ok"
    return "degraded" if any(not f.get("image_stored") for f in figs) else "ok"


def _chunk_safe(material_id, user_id, project_id, text, pages=None) -> dict:
    """Chunk+embed, but a failure here (e.g. embedding rate-limit exhaustion) is
    non-fatal to the material — extraction already succeeded and is durable.

    `pages` (Phase 8b): per-page structure for PDFs → page-aware chunking that carries
    a real page_no into each chunk. Absent (docx/txt/md/image/link) → flat chunking,
    page_no stays NULL."""
    try:
        if pages:
            return chunking.chunk_and_embed_pages(material_id, user_id, project_id, pages)
        return chunking.chunk_and_embed(material_id, user_id, project_id, text)
    except Exception:
        logger.warning("[feed_v2.materials] chunk/embed failed for %s (non-fatal)", material_id, exc_info=True)
        return {"chunk_count": 0, "embedding_count": 0, "chunk_error": True}


def ingest_document(user_id: str, project_id: str | None, file_bytes: bytes, filename: str) -> dict:
    material_id = uuid.uuid4().hex
    ext = Path(filename).suffix.lower()
    res = documents.extract(file_bytes, filename, ext)
    if res.error:
        _insert_material(material_id=material_id, user_id=user_id, project_id=project_id,
                         type_="document", filename=filename, url=None, sha256=res.sha256,
                         status="failed", byte_size=res.byte_size, structure=None, error=res.error)
        logger.info("[feed_v2.materials] document '%s' failed extraction: %s", filename, res.error)
        return {"material_id": material_id, "type": "document", "status": "failed", "error": res.error}

    # Insert first (figures FK v2_materials), then run figures, then record whether
    # every figure image actually stored — file storage is a distinct outcome.
    _insert_material(material_id=material_id, user_id=user_id, project_id=project_id,
                     type_="document", filename=filename, url=None, sha256=res.sha256,
                     status="done", byte_size=res.byte_size, structure=res.structure, error=None)
    figs = figures.extract_figures(material_id, user_id, project_id, file_bytes, filename, ext)
    storage_status = _figure_storage_status(figs)
    _set_storage_status(material_id, storage_status)
    # Original file bytes are not stored in R2 — only extracted text/chunks and
    # figure images persist. Whether a learner can retrieve an original uploaded
    # file is an undecided product question, not yet built. Revisit when the
    # Sources/citation rendering phase defines what "view original" needs to mean,
    # if anything. (storage_status above tracks figure-image storage only.)
    stats = _chunk_safe(material_id, user_id, project_id, res.text, pages=res.pages)
    return {"material_id": material_id, "type": "document", "status": "done",
            "storage_status": storage_status,
            "has_structure": res.has_structure, "section_count": res.section_count,
            "page_count": res.page_count, "figure_count": len(figs), "figures": figs, **stats}


def ingest_image(user_id: str, project_id: str | None, file_bytes: bytes, filename: str) -> dict:
    material_id = uuid.uuid4().hex
    ext = Path(filename).suffix.lower()
    sha = hashlib.sha256(file_bytes).hexdigest()
    res = images.describe_image(file_bytes, ext, meta={"call_type": "feed_v2_image_ingest",
                                                       "surface": "feed_v2", "user_id": user_id,
                                                       "project_id": project_id})
    if res.error:
        _insert_material(material_id=material_id, user_id=user_id, project_id=project_id,
                         type_="image", filename=filename, url=None, sha256=sha,
                         status="failed", byte_size=len(file_bytes), structure=None, error=res.error)
        return {"material_id": material_id, "type": "image", "status": "failed", "error": res.error}

    _insert_material(material_id=material_id, user_id=user_id, project_id=project_id,
                     type_="image", filename=filename, url=None, sha256=sha,
                     status="done", byte_size=len(file_bytes), structure=None, error=None,
                     storage_status="ok")  # no figures/R2 for a standalone image
    stats = _chunk_safe(material_id, user_id, project_id, res.text)
    return {"material_id": material_id, "type": "image", "status": "done",
            "description_len": len(res.description), "ocr_len": len(res.ocr_text), **stats}


def ingest_link(user_id: str, project_id: str | None, url: str) -> dict:
    material_id = uuid.uuid4().hex
    res = links.fetch_link(url)
    if res.error:
        _insert_material(material_id=material_id, user_id=user_id, project_id=project_id,
                         type_="link", filename=None, url=url, sha256="",
                         status="failed", byte_size=0, structure=None, error=res.error)
        return {"material_id": material_id, "type": "link", "status": "failed", "error": res.error}

    text = res.text
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    _insert_material(material_id=material_id, user_id=user_id, project_id=project_id,
                     type_="link", filename=res.title or None, url=url, sha256=sha,
                     status="done", byte_size=len(text.encode("utf-8")), structure=None, error=None,
                     storage_status="ok")  # link text is the material; no file to store
    stats = _chunk_safe(material_id, user_id, project_id, text)
    return {"material_id": material_id, "type": "link", "status": "done", "title": res.title, **stats}


def ingest(user_id: str, project_id: str | None = None, *,
           file_bytes: bytes | None = None, filename: str | None = None,
           url: str | None = None) -> dict:
    """Route an upload to the right ingester by kind. Exactly one of (file_bytes+
    filename) or url must be given."""
    if url is not None:
        return ingest_link(user_id, project_id, url)
    if file_bytes is None or filename is None:
        raise ValueError("provide either url, or both file_bytes and filename")
    ext = Path(filename).suffix.lower()
    if ext in _IMAGE_EXTS:
        return ingest_image(user_id, project_id, file_bytes, filename)
    if ext in _DOC_EXTS:
        return ingest_document(user_id, project_id, file_bytes, filename)
    # Unknown type → a terminal 'failed' row, never a raise.
    material_id = uuid.uuid4().hex
    err = f"Unsupported file type: {ext or 'unknown'}"
    _insert_material(material_id=material_id, user_id=user_id, project_id=project_id,
                     type_="document", filename=filename, url=None,
                     sha256=hashlib.sha256(file_bytes).hexdigest(), status="failed",
                     byte_size=len(file_bytes), structure=None, error=err)
    return {"material_id": material_id, "type": "unknown", "status": "failed", "error": err}
