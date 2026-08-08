"""
Chat-R19c-backend smoke test — /chat/upload as NDJSON streaming.

Drives the real HTTP endpoint via FastAPI's TestClient — the actual
StreamingResponse wire shape, not a direct function call — since this phase
is specifically about the transport. Real DB (sqlite3 :memory: + ALL_TABLES,
same technique as tests/test_r19b_embedding_batching.py's mem_db fixture),
real R2 upload (live credentials confirmed present), real Gemini embedding
calls for tests 1-2. Test 3 forces Gemini's RESOURCE_EXHAUSTED specifically
(reproducing it organically isn't reliable on demand) by making the real
get_embedding_model()'s embed_documents raise the exact exception shape
langchain_google_genai's embed_documents wraps a real 429 into (confirmed by
reading its source) — same mocking boundary tests/test_r19b already uses.

Run
---
  python scripts/smoke_test_r19c_upload_stream.py
"""
from __future__ import annotations

import io
import json
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sqlite_vec
from fastapi.testclient import TestClient

from backend.database.schema import ALL_TABLES
from backend.llm import embeddings
from backend.main import app, get_current_user
from backend.services import document_memory_service
from google.genai.errors import ClientError
from langchain_google_genai._common import GoogleGenerativeAIError


@contextmanager
def _client():
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "smoke-r19c-user", "email": "smoke@example.com"}
    try:
        yield TestClient(app, raise_server_exceptions=True)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@contextmanager
def _mem_db():
    # Same technique as tests/test_r19b_embedding_batching.py's mem_db fixture.
    # check_same_thread=False: Starlette iterates a sync generator via
    # anyio's threadpool, so document_memory_service.store_document_stream
    # runs on a worker thread, not the one that opened this connection.
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA journal_mode=WAL")
    for stmt in ALL_TABLES:
        conn.execute(stmt)
    conn.commit()

    @contextmanager
    def _get_conn():
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    with patch.object(document_memory_service, "get_connection", _get_conn):
        yield conn
    conn.close()


def _upload(client, filename: str, content: bytes, content_type: str) -> tuple[int, list[dict]]:
    resp = client.post(
        "/chat/upload",
        files={"file": (filename, io.BytesIO(content), content_type)},
    )
    lines = [json.loads(l) for l in resp.text.strip().split("\n") if l.strip()]
    return resp.status_code, lines


def _paragraphs(n: int) -> str:
    # Each paragraph alone is under _CHUNK_CHARS (800) but any two combined
    # exceed it, so _chunk_text puts exactly one paragraph per chunk —
    # matches test_r19b_embedding_batching.py's own helper exactly.
    return "\n\n".join(f"Paragraph {i} " + ("x" * 500) for i in range(n))


def test_small_document_single_batch():
    print("\n=== 1. Real small document (single batch) ===")
    with _mem_db(), _client() as client:
        text = "Hello from Chat-R19c. This is a small real document, well under one embedding batch."
        status, lines = _upload(client, "small.txt", text.encode(), "text/plain")
    print(f"status={status}")
    for l in lines:
        print(" ", l)
    assert status == 200
    assert [l["t"] for l in lines] == ["stage", "done"], "expected exactly one stage event + done"
    assert lines[0] == {"t": "stage", "stage": "embedding", "batch": 1, "total_batches": 1}
    assert lines[1]["uri"].startswith("doc://")
    assert lines[1]["filename"] == "small.txt"
    print("PASS: minimal real event sequence, no fabricated intermediate stages, correct done payload")


def test_large_document_1554_chunks():
    print("\n=== 2. Real large document (1554-chunk case — R19a's crash case) ===")
    text = _paragraphs(1554)
    with _mem_db(), _client() as client:
        status, lines = _upload(client, "huge.txt", text.encode(), "text/plain")
    stage_lines = [l for l in lines if l["t"] == "stage"]
    done_lines = [l for l in lines if l["t"] == "done"]
    print(f"status={status}  total lines={len(lines)}  stage events={len(stage_lines)}")
    print("first 3 stage events:", stage_lines[:3])
    print("last 3 stage events:", stage_lines[-3:])
    assert status == 200
    assert len(done_lines) == 1
    # ceil(1554/25) = 63 batches
    assert len(stage_lines) == 63, f"expected 63 embedding-batch events, got {len(stage_lines)}"
    assert all(l["stage"] == "embedding" for l in stage_lines), "no organic rate-limit hit expected at this volume"
    assert [l["batch"] for l in stage_lines] == list(range(1, 64)), "batch numbers must be in order"
    assert all(l["total_batches"] == 63 for l in stage_lines)
    print("PASS: 63 real batch-progress events, accurate numbers, in order, matching what actually processed")


def test_forced_rate_limit_wall():
    print("\n=== 3. Real forced rate-limit wall — distinct event, separate from generic retry ===")
    cause = ClientError(429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "Resource exhausted."}})
    rate_limit_exc = GoogleGenerativeAIError(f"Error embedding content ({cause.status}): {cause}")
    rate_limit_exc.__cause__ = cause

    fake_model = MagicMock()
    fake_model.embed_documents.side_effect = [rate_limit_exc, [[0.0] * 3072]]

    with _mem_db(), _client() as client, patch.object(embeddings, "get_embedding_model", return_value=fake_model):
        status, lines = _upload(client, "rate_limited.txt", b"Small doc, forced rate limit on first attempt.", "text/plain")
    print(f"status={status}")
    for l in lines:
        print(" ", l)
    assert status == 200
    assert [l.get("stage", l["t"]) for l in lines] == ["rate_limited", "embedding", "done"], (
        "rate_limited must be its own distinct event, ordered before the batch's embedding event, "
        "not merged into it"
    )
    assert lines[0] == {"t": "stage", "stage": "rate_limited", "batch": 1, "total_batches": 1}
    assert lines[1] == {"t": "stage", "stage": "embedding", "batch": 1, "total_batches": 1}
    assert fake_model.embed_documents.call_count == 2, "one failed attempt + one successful retry"
    print("PASS: distinct rate_limited event fired, separate from the (invisible) generic retry path, accurate batch info")


def test_image_upload_unchanged():
    print("\n=== 4a. Real image upload — transport wrapper only, no new events ===")
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color=(200, 30, 30)).save(buf, format="PNG")
    with _client() as client:
        status, lines = _upload(client, "square.png", buf.getvalue(), "image/png")
    print(f"status={status}")
    for l in lines:
        print(" ", {k: v for k, v in l.items() if k != "uri"} | {"uri": str(l.get("uri"))[:40] + "…"})
    assert status == 200
    assert [l["t"] for l in lines] == ["done"], "image path must emit exactly one line — no stage events"
    assert lines[0]["mime_type"] == "image/png"
    assert lines[0]["r2_attachment_id"], "R14a dual-write must still run"
    print("PASS: image upload unchanged apart from transport wrapper — one done event, same payload shape")


def test_other_file_upload_unchanged():
    print("\n=== 4b. Real 'other' file upload — transport wrapper only, no new events ===")
    with _client() as client:
        status, lines = _upload(client, "archive.bin", b"\x00\x01\x02random-bytes-not-a-known-doc-type", "application/octet-stream")
    print(f"status={status}")
    for l in lines:
        print(" ", l)
    assert status == 200
    assert [l["t"] for l in lines] == ["done"], "other-file path must emit exactly one line — no stage events"
    assert lines[0]["uri"].startswith("file://")
    print("PASS: other-file upload unchanged apart from transport wrapper — one done event, same payload shape")


def test_old_frontend_compatibility():
    print("\n=== 5. Old (not-yet-updated) frontend compatibility — fetch().then(res.json()) ===")
    print("Simulates chat.js's uploadAttachment(): res.json() === JSON.parse(full body text).")

    with _mem_db(), _client() as client:
        status, _ = _upload(client, "compat_doc.txt", b"A short document.", "text/plain")
        raw_doc = client.post("/chat/upload", files={"file": ("compat_doc2.txt", io.BytesIO(b"Another short document."), "text/plain")}).text

    with _client() as client:
        buf = io.BytesIO()
        __import__("PIL.Image", fromlist=["Image"]).new("RGB", (16, 16)).save(buf, format="PNG")
        raw_image = client.post("/chat/upload", files={"file": ("tiny.png", io.BytesIO(buf.getvalue()), "image/png")}).text
        raw_other = client.post("/chat/upload", files={"file": ("x.bin", io.BytesIO(b"abc"), "application/octet-stream")}).text

    def _try_parse(label, raw):
        try:
            json.loads(raw)
            print(f"  {label}: res.json() SUCCEEDS — old frontend shows this upload as done, unchanged")
            return True
        except json.JSONDecodeError as e:
            print(f"  {label}: res.json() THROWS ({e}) — old frontend's uploadAttachment() promise "
                  f"rejects, ChatInput.jsx's .catch() marks this attachment status:'error' even though "
                  f"the backend fully succeeded and the file IS stored")
            return False

    doc_ok = _try_parse("document upload (2 NDJSON lines)", raw_doc)
    image_ok = _try_parse("image upload (1 NDJSON line)", raw_image)
    other_ok = _try_parse("other-file upload (1 NDJSON line)", raw_other)

    assert image_ok and other_ok, "image/other-file uploads must stay fully compatible with the old frontend"
    assert not doc_ok, (
        "documented finding: document uploads now ALWAYS emit >=2 NDJSON lines (>=1 embedding stage + done), "
        "so the old frontend's res.json() will reject on every real document upload until R19c-frontend lands"
    )
    print("CONFIRMED (not a pass/fail on my code — a real compatibility finding to report):")
    print("  - image/other-file uploads: fully backward compatible, zero visible change")
    print("  - document uploads: BREAK the old frontend's res.json() parse — shows as failed upload")
    print("    even though the backend succeeded and the document IS extracted+embedded+stored.")


if __name__ == "__main__":
    test_small_document_single_batch()
    test_large_document_1554_chunks()
    test_forced_rate_limit_wall()
    test_image_upload_unchanged()
    test_other_file_upload_unchanged()
    test_old_frontend_compatibility()
    print("\nAll Chat-R19c-backend upload-stream smoke tests ran.")
