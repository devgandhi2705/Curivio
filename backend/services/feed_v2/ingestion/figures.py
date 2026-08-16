"""
Feed v2 figure extraction — the NEW work (not in the legacy chat path).

For PDF and DOCX: pull embedded images with page/location + a caption (explicit
"Figure N" line / alt text where present, else the nearest text block), store
the image bytes in R2 (boto3 reached directly — r2_storage_service sits behind
the isolation boundary), embed the caption text (ingestion.embeddings), and
write one v2_material_figures row per figure.

Zero extractable figures is a NORMAL outcome (logged, not an error). A failed R2
upload degrades gracefully: the figure row is still written with image_key=None
so a storage hiccup never wedges ingestion.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from functools import lru_cache

import pypdf
from docx import Document

from ..db import get_connection
from .embeddings import embed_query

logger = logging.getLogger(__name__)

_FIG_RE = re.compile(r"^\s*(figure|fig\.?|table)\s*\d+", re.IGNORECASE)


# ── R2 (boto3 direct — same client shape as r2_storage_service, not imported) ──
@lru_cache(maxsize=1)
def _r2_client():
    import boto3
    from botocore.config import Config
    account_id = os.getenv("R2_ACCOUNT_ID")
    access_key = os.getenv("R2_ACCESS_KEY_ID")
    secret_key = os.getenv("R2_SECRET_ACCESS_KEY")
    if not (account_id and access_key and secret_key):
        raise RuntimeError("R2 credentials not configured")
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key, aws_secret_access_key=secret_key,
        region_name="auto", config=Config(signature_version="s3v4"),
    )


def _r2_upload(data: bytes, key: str, content_type: str) -> bool:
    """Best-effort. Returns True on success; logs and returns False otherwise so
    a storage failure never aborts figure extraction."""
    try:
        bucket = os.getenv("R2_BUCKET_NAME")
        if not bucket:
            raise RuntimeError("R2_BUCKET_NAME not set")
        _r2_client().put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
        return True
    except Exception as exc:
        logger.warning("[feed_v2.figures] R2 upload skipped for %s: %s", key, exc)
        return False


def _pdf_caption(page_text: str) -> tuple[str, str]:
    """Returns (caption, which) where which is 'explicit' (a Figure/Table line) or
    'nearest_text' (fallback: first non-empty line on the page)."""
    lines = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
    for ln in lines:
        if _FIG_RE.match(ln):
            return ln[:300], "explicit"
    return (lines[0][:300] if lines else ""), "nearest_text"


def _write_figure(conn, *, material_id, user_id, project_id, page_no, caption, image_key):
    figure_id = uuid.uuid4().hex
    embedding_ref = None
    if caption:
        try:
            # ponytail: store the caption vector as JSON in embedding_ref. Figures
            # per doc are few (<dozens) — no dedicated vec index needed; linear scan
            # is fine. Add a figure vec0 table only if figure semantic search grows.
            embedding_ref = json.dumps(embed_query(caption))
        except Exception:
            logger.warning("[feed_v2.figures] caption embed failed (non-fatal)", exc_info=True)
    conn.execute(
        """INSERT INTO v2_material_figures
               (figure_id, user_id, material_id, project_id, page_no, caption, image_key, embedding_ref, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (figure_id, user_id, material_id, project_id, page_no, caption, image_key, embedding_ref,
         datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")),
    )
    return figure_id


def _extract_pdf_figures(material_id, user_id, project_id, file_bytes) -> list[dict]:
    reader = pypdf.PdfReader(io.BytesIO(file_bytes))
    figs: list[dict] = []
    with get_connection() as conn:
        for page_no, page in enumerate(reader.pages):
            try:
                images = list(page.images)
            except Exception:
                logger.debug("pdf page %d image read failed", page_no, exc_info=True)
                continue
            if not images:
                continue
            caption, which = _pdf_caption(page.extract_text() or "")
            for img in images:
                key = f"v2/figures/{material_id}/p{page_no}_{img.name}"
                stored = _r2_upload(img.data, key, "image/png")
                _write_figure(conn, material_id=material_id, user_id=user_id, project_id=project_id,
                              page_no=page_no, caption=caption, image_key=key if stored else None)
                figs.append({"page_no": page_no, "caption": caption, "caption_source": which,
                             "image_stored": stored})
    return figs


def _extract_docx_figures(material_id, user_id, project_id, file_bytes) -> list[dict]:
    doc = Document(io.BytesIO(file_bytes))
    # First heading as a coarse caption fallback (DOCX image rels carry no page/caption).
    headings = [p.text.strip() for p in doc.paragraphs
                if (p.style.name if p.style else "").startswith("Heading") and p.text.strip()]
    fallback_caption = headings[0][:300] if headings else ""
    figs: list[dict] = []
    with get_connection() as conn:
        for rel in doc.part.rels.values():
            if "image" not in rel.reltype:
                continue
            try:
                blob = rel.target_part.blob
            except Exception:
                continue
            key = f"v2/figures/{material_id}/{uuid.uuid4().hex}.img"
            stored = _r2_upload(blob, key, "image/png")
            _write_figure(conn, material_id=material_id, user_id=user_id, project_id=project_id,
                          page_no=None, caption=fallback_caption, image_key=key if stored else None)
            figs.append({"page_no": None, "caption": fallback_caption,
                         "caption_source": "nearest_text" if fallback_caption else "none",
                         "image_stored": stored})
    return figs


def extract_figures(material_id: str, user_id: str, project_id: str | None,
                   file_bytes: bytes, filename: str, ext: str) -> list[dict]:
    """Extract + persist figures. Returns a list of figure descriptors (possibly
    empty — zero figures is normal)."""
    ext = ext.lower()
    try:
        if ext == ".pdf":
            figs = _extract_pdf_figures(material_id, user_id, project_id, file_bytes)
        elif ext == ".docx":
            figs = _extract_docx_figures(material_id, user_id, project_id, file_bytes)
        else:
            figs = []
    except Exception:
        logger.warning("[feed_v2.figures] extraction failed for %s (non-fatal)", filename, exc_info=True)
        figs = []
    if not figs:
        logger.info("[feed_v2.figures] no figures extracted from %s", filename)
    return figs
