"""
Chat-R6a — direct text extraction for uploaded documents (pdf/docx/csv/text/code).

Images stay entirely on the existing native Gemini vision path (chat_agent.py's
Chat-5 has_attachments gate) — this module is never invoked for image uploads.

Scanned/image-only PDFs are NOT OCR'd (R6b, separate/unresolved phase) — pypdf's
extracted text is measured against a real <100 chars/page threshold (live-verified:
a hand-built PDF with real text content extracted to 73 chars over 2 short lines;
a page with no text content stream extracted to exactly 0 chars) and a clear,
specific error is returned instead of a silent wrong answer or a fake OCR attempt.

Routes by file extension, not content_type: browsers send unreliable/missing MIME
types for code files (live-verified via mimetypes.guess_type as a proxy — .ts
guesses as a video MIME, .tsx/.jsx/.yaml/.yml/.java/.go/.rs/.cpp all guess None).
docx/pdf have consistent MIME types across browsers so main.py's image-vs-document
routing can still use content_type; extraction itself uses the extension.

Public API
----------
DOCUMENT_EXTENSIONS: set[str]   every extension this module can extract
extract_document_text(file_bytes, filename, ext) -> (text, error)
    Exactly one of the two return values is populated.
"""
from __future__ import annotations

import io
import logging

import pypdf
from docx import Document

logger = logging.getLogger(__name__)

# Real digital PDF pages run into the hundreds of chars/page; a scanned/image-only
# page extracts to 0 chars (pypdf has nothing to read — no OCR). Threshold sits
# comfortably below real prose while staying well above the scanned-page floor.
_MIN_CHARS_PER_PAGE = 100

_PLAIN_TEXT_EXTENSIONS = {
    ".txt", ".md", ".csv",
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".c", ".cpp",
    ".h", ".hpp", ".cs", ".rb", ".php", ".sh", ".sql", ".json", ".yaml", ".yml",
    ".html", ".css", ".xml",
}

DOCUMENT_EXTENSIONS = _PLAIN_TEXT_EXTENSIONS | {".pdf", ".docx"}


def _extract_pdf(file_bytes: bytes, filename: str) -> tuple[str | None, str | None]:
    try:
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
    except Exception as exc:
        return None, f"Couldn't read '{filename}' as a PDF: {exc}"

    if not reader.pages:
        return None, f"'{filename}' has no pages."

    page_texts = [(p.extract_text() or "") for p in reader.pages]
    total_chars = sum(len(t) for t in page_texts)
    if total_chars / len(page_texts) < _MIN_CHARS_PER_PAGE:
        return None, (
            f"Couldn't extract text from '{filename}' — this looks like a "
            f"scanned or image-only PDF. OCR support isn't available yet "
            f"(coming in a future update)."
        )
    return "\n\n".join(page_texts), None


def _extract_docx(file_bytes: bytes, filename: str) -> tuple[str | None, str | None]:
    try:
        doc = Document(io.BytesIO(file_bytes))
    except Exception as exc:
        return None, f"Couldn't read '{filename}' as a .docx file: {exc}"

    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text for cell in row.cells))
    text = "\n".join(parts)
    if not text.strip():
        return None, f"'{filename}' has no extractable text."
    return text, None


def _extract_plain(file_bytes: bytes, filename: str) -> tuple[str | None, str | None]:
    try:
        text = file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = file_bytes.decode("latin-1")
        except Exception as exc:
            return None, f"Couldn't decode '{filename}' as text: {exc}"
    if not text.strip():
        return None, f"'{filename}' is empty."
    return text, None


def extract_document_text(file_bytes: bytes, filename: str, ext: str) -> tuple[str | None, str | None]:
    """Returns (text, error) — exactly one is populated."""
    ext = ext.lower()
    if ext == ".pdf":
        return _extract_pdf(file_bytes, filename)
    if ext == ".docx":
        return _extract_docx(file_bytes, filename)
    if ext in _PLAIN_TEXT_EXTENSIONS:
        return _extract_plain(file_bytes, filename)
    return None, f"Unsupported file type: {ext or 'unknown'}"
