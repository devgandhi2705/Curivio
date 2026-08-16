"""
Phase P — /chat/upload now writes an llm_call_log row for every real step of
an upload attempt (reject_too_large, gemini_upload, r2_upload, extract,
embed, unexpected), all sharing one trace_id, surface='chat_upload'.
Previously nothing here was logged at all (P-recon).

External network boundaries are mocked (R2, Gemini embeddings) same as
test_chat_upload_r14a.py already does — extraction itself is real pypdf/
docx/decode, not mocked, so the 8 real failure reasons stay real.
"""
from __future__ import annotations

import io
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import app_config as cfg
from backend.database.schema import ALL_TABLES, MIGRATIONS
from backend.llm import call_logger
from backend.services import admin_service, document_memory_service


def _real_text_pdf_bytes() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 750, "Hello world, this is a real extractable PDF text line.")
    c.drawString(100, 730, "A second line so the page clears the 100 chars/page floor.")
    c.save()
    return buf.getvalue()


def _blank_pdf_bytes() -> bytes:
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.fixture
def mem_db(monkeypatch):
    # check_same_thread=False: TestClient runs the ASGI app (and this
    # monkeypatched get_connection) in a worker thread, not the test's own
    # thread — the default same-thread guard would reject every DB call the
    # endpoint makes. conftest.py's patched sqlite3.connect still vec0-loads
    # this connection.
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    for stmt in ALL_TABLES:
        conn.execute(stmt)
    # llm_call_log's trace_id/agent_name/surface/is_test/target_language and
    # learning_projects.user_id are all migration-added columns (ALTER TABLE),
    # not in the base CREATE — real init_db() runs both; this fixture must too.
    for migration in MIGRATIONS:
        try:
            if isinstance(migration, (list, tuple)):
                for stmt in migration:
                    conn.execute(stmt)
            else:
                conn.execute(migration)
        except sqlite3.OperationalError:
            pass
    conn.commit()

    @contextmanager
    def _get_conn():
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    monkeypatch.setattr(call_logger, "get_connection", _get_conn)
    monkeypatch.setattr(document_memory_service, "get_connection", _get_conn)
    monkeypatch.setattr(admin_service, "get_connection", _get_conn)
    yield conn
    conn.close()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from backend.main import app, get_current_user
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "phase-p-user", "email": "phasep@example.com",
    }
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def _chat_upload_rows(conn, **where) -> list[sqlite3.Row]:
    clauses = " AND ".join(f"{k} = ?" for k in where)
    sql = "SELECT * FROM llm_call_log WHERE surface = 'chat_upload'"
    if clauses:
        sql += f" AND {clauses}"
    sql += " ORDER BY id ASC"
    return conn.execute(sql, list(where.values())).fetchall()


class TestSuccessfulPdfUpload:
    def test_real_pdf_upload_logs_extract_and_embed_rows_with_real_user_id(self, mem_db, client):
        fake_vectors_call = lambda chunks: [[0.0] * 3072 for _ in chunks]
        with patch("backend.services.r2_storage_service.upload") as mock_r2, \
             patch("backend.services.document_memory_service.get_embeddings_batch", side_effect=fake_vectors_call):
            resp = client.post(
                "/chat/upload",
                files={"file": ("notes.pdf", io.BytesIO(_real_text_pdf_bytes()), "application/pdf")},
            )

        assert resp.status_code == 200, resp.text
        lines = [l for l in resp.text.strip().split("\n") if l]
        import json
        done = json.loads(lines[-1])
        assert done["t"] == "done"
        assert done["uri"].startswith("doc://")
        mock_r2.assert_called_once()

        rows = _chat_upload_rows(mem_db)
        by_agent = {r["agent_name"]: r for r in rows}
        assert set(by_agent) == {"extract", "embed", "r2_upload"}, [dict(r) for r in rows]

        # One shared trace_id across every step of this one attempt.
        trace_ids = {r["trace_id"] for r in rows}
        assert len(trace_ids) == 1

        extract_row = by_agent["extract"]
        assert extract_row["success"] == 1
        assert extract_row["provider"] == "local"
        assert extract_row["user_id"] == "phase-p-user"
        assert "chars extracted" in extract_row["output"]

        embed_row = by_agent["embed"]
        assert embed_row["success"] == 1
        assert embed_row["provider"] == "gemini"
        assert embed_row["model_used"] == cfg.GEMINI_EMBEDDING_MODEL
        assert embed_row["user_id"] == "phase-p-user"

        r2_row = by_agent["r2_upload"]
        assert r2_row["success"] == 1
        assert r2_row["provider"] == "r2"


class TestFailedExtractionIsLoggedWithRealReason:
    def test_corrupt_pdf_logs_pdf_unreadable(self, mem_db, client):
        resp = client.post(
            "/chat/upload",
            files={"file": ("bad.pdf", io.BytesIO(b"not a pdf at all"), "application/pdf")},
        )
        assert resp.status_code == 200
        import json
        body = json.loads(resp.text.strip())
        assert body["t"] == "error"

        rows = _chat_upload_rows(mem_db, agent_name="extract")
        assert len(rows) == 1
        assert rows[0]["success"] == 0
        assert rows[0]["error_type"] == "pdf_unreadable"
        assert rows[0]["error_message"] == body["message"]  # same real reason, not a generic one

    def test_scanned_image_only_pdf_logs_pdf_scanned(self, mem_db, client):
        resp = client.post(
            "/chat/upload",
            files={"file": ("scan.pdf", io.BytesIO(_blank_pdf_bytes()), "application/pdf")},
        )
        assert resp.status_code == 200
        import json
        body = json.loads(resp.text.strip())
        assert body["t"] == "error"

        rows = _chat_upload_rows(mem_db, agent_name="extract")
        assert len(rows) == 1
        assert rows[0]["success"] == 0
        assert rows[0]["error_type"] == "pdf_scanned"
        assert rows[0]["error_message"] == body["message"]

    def test_empty_text_file_logs_text_empty(self, mem_db, client):
        resp = client.post(
            "/chat/upload",
            files={"file": ("blank.txt", io.BytesIO(b"   \n\t  "), "text/plain")},
        )
        assert resp.status_code == 200
        import json
        body = json.loads(resp.text.strip())
        assert body["t"] == "error"

        rows = _chat_upload_rows(mem_db, agent_name="extract")
        assert len(rows) == 1
        assert rows[0]["success"] == 0
        assert rows[0]["error_type"] == "text_empty"
        assert rows[0]["error_message"] == body["message"]

    def test_three_reasons_are_actually_distinct_rows(self, mem_db, client):
        client.post("/chat/upload", files={"file": ("bad.pdf", io.BytesIO(b"nope"), "application/pdf")})
        client.post("/chat/upload", files={"file": ("scan.pdf", io.BytesIO(_blank_pdf_bytes()), "application/pdf")})
        client.post("/chat/upload", files={"file": ("blank.txt", io.BytesIO(b"  "), "text/plain")})

        rows = _chat_upload_rows(mem_db, agent_name="extract")
        assert len(rows) == 3
        error_types = [r["error_type"] for r in rows]
        assert error_types == ["pdf_unreadable", "pdf_scanned", "text_empty"]
        # 3 distinct rows, 3 distinct trace_ids — not one generic bucket.
        assert len({r["trace_id"] for r in rows}) == 3


class TestFileTooLargeIsLogged:
    def test_oversize_upload_now_leaves_a_real_row(self, mem_db, client):
        with patch("backend.main.cfg.CHAT_UPLOAD_MAX_BYTES", 10):
            resp = client.post(
                "/chat/upload",
                files={"file": ("notes.txt", io.BytesIO(b"x" * 11), "text/plain")},
            )
        assert resp.status_code == 413

        rows = _chat_upload_rows(mem_db, agent_name="reject_too_large")
        assert len(rows) == 1
        assert rows[0]["success"] == 0
        assert rows[0]["error_type"] == "file_too_large"
        assert rows[0]["user_id"] == "phase-p-user"


class TestAdminGroupedListMachinery:
    def test_chat_upload_rows_resolve_through_list_grouped_calls(self, mem_db, client):
        fake_vectors_call = lambda chunks: [[0.0] * 3072 for _ in chunks]
        with patch("backend.services.r2_storage_service.upload"), \
             patch("backend.services.document_memory_service.get_embeddings_batch", side_effect=fake_vectors_call):
            client.post(
                "/chat/upload",
                files={"file": ("notes.pdf", io.BytesIO(_real_text_pdf_bytes()), "application/pdf")},
            )
        mem_db.execute(
            "INSERT INTO users (user_id, email, hashed_pw, name) VALUES (?, ?, ?, ?)",
            ("phase-p-user", "phasep@example.com", "x", "Phase P"),
        )
        mem_db.commit()

        total, groups = admin_service.list_grouped_calls(
            date_from=None, date_to=None, project_id=None, user_id=None,
            include_test_data=True, status=None, action_type="chat_upload",
            day_ref=None, target_language=None, limit=10, offset=0,
        )
        assert total == 1
        assert len(groups) == 1
        group = groups[0]
        assert group["surface"] == "chat_upload"
        assert group["user_email"] == "phasep@example.com"
        assert group["row_count"] == 3  # extract + embed + r2_upload
        # list_grouped_calls' per-row SELECT (_ROW_COLUMNS) doesn't project
        # agent_name today — providers are the distinguishing field available
        # at this level (local=extract, gemini=embed, r2=r2_upload).
        assert {r["provider"] for r in group["rows"]} == {"local", "gemini", "r2"}
        assert {r["call_type"] for r in group["rows"]} == {"chat_upload"}
        assert all(r["success"] for r in group["rows"])


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
