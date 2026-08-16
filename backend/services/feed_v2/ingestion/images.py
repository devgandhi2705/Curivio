"""
Feed v2 standalone image ingestion — a plain uploaded image (png/jpg), not an
image embedded in a document. Routed through the image_ingestor vision agent
(provider.py routing table, Phase 4) to produce a text description + OCR text,
which becomes the material's extracted content — the same slot a document's
extracted text fills, so downstream chunking/embedding treats it identically.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ..llm import provider

logger = logging.getLogger(__name__)

_MIME_FOR_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}

_SYSTEM = (
    "You are a vision extraction agent. Look at the image and return a JSON object "
    "with two fields: 'description' (a detailed prose description of what the image "
    "shows) and 'ocr_text' (every piece of readable text in the image, transcribed "
    "verbatim; empty string if there is none)."
)


@dataclass
class ImageResult:
    text: str | None = None       # description + OCR, the material's extracted content
    description: str = ""
    ocr_text: str = ""
    error: str | None = None


def mime_for_ext(ext: str) -> str | None:
    return _MIME_FOR_EXT.get(ext.lower())


def describe_image(image_bytes: bytes, ext: str, meta: dict | None = None) -> ImageResult:
    """Vision-extract description + OCR for a standalone image. Returns text OR error."""
    mime = mime_for_ext(ext)
    if mime is None:
        return ImageResult(error=f"Unsupported image type: {ext}")
    try:
        result = provider.call_agent(
            "image_ingestor",
            messages=[{"role": "user", "content": "Describe this image and transcribe all visible text."}],
            system=_SYSTEM,
            images=[(image_bytes, mime)],
            meta=meta,
        )
    except Exception as exc:  # AllLegsFailed / key missing — non-fatal to the caller
        logger.warning("[feed_v2.images] vision extraction failed (non-fatal): %s", exc)
        return ImageResult(error=str(exc))

    description = (result.get("description") or "").strip()
    ocr_text = (result.get("ocr_text") or "").strip()
    combined = "\n\n".join(p for p in (description, f"Text in image:\n{ocr_text}" if ocr_text else "") if p)
    return ImageResult(text=combined or description or ocr_text, description=description, ocr_text=ocr_text)
