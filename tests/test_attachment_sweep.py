"""
Tests for chat_service.sweep_expired_attachments() — Chat-R13's admin cleanup
of expired document-attachment original bytes. R2 calls are mocked; DB is
in-memory sqlite (ALL_TABLES replay), same fixture shape as
test_document_memory_service.py.

Extracted text/embeddings (document_chunks_vec) must never be touched by the
sweep — only the R2 object and the chat_messages.attachments JSON reference.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.database.schema import ALL_TABLES
from backend.services import chat_service


@pytest.fixture
def mem_db(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
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

    monkeypatch.setattr(chat_service, "get_connection", _get_conn)
    yield conn
    conn.close()


def _insert_message(conn, session_id, attachments):
    conn.execute("INSERT INTO chat_sessions (session_id, title) VALUES (?, ?)", (session_id, "t"))
    conn.execute(
        "INSERT INTO chat_messages (session_id, role, content, attachments) VALUES (?, ?, ?, ?)",
        (session_id, "user", "hi", json.dumps(attachments) if attachments is not None else None),
    )
    conn.commit()
    return conn.execute("SELECT id FROM chat_messages WHERE session_id = ?", (session_id,)).fetchone()["id"]


def _iso(dt):
    return dt.isoformat()


class TestSweepExpiredAttachments:
    def test_deletes_r2_object_and_clears_expired_doc_attachment(self, mem_db):
        past = _iso(datetime.now(timezone.utc) - timedelta(days=1))
        att = {"uri": "doc://abc123", "mime_type": "application/pdf", "filename": "report.pdf",
               "size_bytes": 100, "expires_at": past}
        msg_id = _insert_message(mem_db, "s1", [att])

        with patch.object(chat_service, "r2_storage_service") as mock_r2:
            result = chat_service.sweep_expired_attachments()

        mock_r2.delete.assert_called_once_with("chat-attachments/abc123.pdf")
        assert result["swept"] == 1
        assert "abc123" in result["attachment_ids"]
        row = mem_db.execute("SELECT attachments FROM chat_messages WHERE id = ?", (msg_id,)).fetchone()
        assert json.loads(row["attachments"]) == []

    def test_non_expired_doc_attachment_untouched(self, mem_db):
        future = _iso(datetime.now(timezone.utc) + timedelta(days=10))
        att = {"uri": "doc://keepme", "mime_type": "text/plain", "filename": "notes.txt",
               "size_bytes": 10, "expires_at": future}
        msg_id = _insert_message(mem_db, "s1", [att])

        with patch.object(chat_service, "r2_storage_service") as mock_r2:
            result = chat_service.sweep_expired_attachments()

        mock_r2.delete.assert_not_called()
        assert result["swept"] == 0
        row = mem_db.execute("SELECT attachments FROM chat_messages WHERE id = ?", (msg_id,)).fetchone()
        assert json.loads(row["attachments"]) == [att]

    def test_expired_and_live_attachments_in_same_row_only_expired_swept(self, mem_db):
        past = _iso(datetime.now(timezone.utc) - timedelta(days=1))
        future = _iso(datetime.now(timezone.utc) + timedelta(days=10))
        expired = {"uri": "doc://old1", "mime_type": "text/plain", "filename": "a.txt",
                   "size_bytes": 5, "expires_at": past}
        live = {"uri": "doc://new1", "mime_type": "text/plain", "filename": "b.txt",
                "size_bytes": 5, "expires_at": future}
        msg_id = _insert_message(mem_db, "s1", [expired, live])

        with patch.object(chat_service, "r2_storage_service") as mock_r2:
            result = chat_service.sweep_expired_attachments()

        mock_r2.delete.assert_called_once_with("chat-attachments/old1.txt")
        assert result["swept"] == 1
        row = mem_db.execute("SELECT attachments FROM chat_messages WHERE id = ?", (msg_id,)).fetchone()
        assert json.loads(row["attachments"]) == [live]

    def test_image_attachment_never_touched_even_when_expired(self, mem_db):
        past = _iso(datetime.now(timezone.utc) - timedelta(days=1))
        img = {"uri": "https://generativelanguage.googleapis.com/files/xyz", "mime_type": "image/png",
               "filename": "shot.png", "size_bytes": 10, "expires_at": past}
        msg_id = _insert_message(mem_db, "s1", [img])

        with patch.object(chat_service, "r2_storage_service") as mock_r2:
            result = chat_service.sweep_expired_attachments()

        mock_r2.delete.assert_not_called()
        assert result["swept"] == 0
        row = mem_db.execute("SELECT attachments FROM chat_messages WHERE id = ?", (msg_id,)).fetchone()
        assert json.loads(row["attachments"]) == [img]

    def test_r2_delete_failure_keeps_reference_and_reports_error(self, mem_db):
        past = _iso(datetime.now(timezone.utc) - timedelta(days=1))
        att = {"uri": "doc://failme", "mime_type": "text/plain", "filename": "c.txt",
               "size_bytes": 5, "expires_at": past}
        msg_id = _insert_message(mem_db, "s1", [att])

        with patch.object(chat_service, "r2_storage_service") as mock_r2:
            mock_r2.delete.side_effect = RuntimeError("boom")
            result = chat_service.sweep_expired_attachments()

        assert result["swept"] == 0
        assert len(result["errors"]) == 1
        row = mem_db.execute("SELECT attachments FROM chat_messages WHERE id = ?", (msg_id,)).fetchone()
        assert json.loads(row["attachments"]) == [att]

    def test_extracted_text_never_touched_by_sweep(self, mem_db):
        past = _iso(datetime.now(timezone.utc) - timedelta(days=1))
        att = {"uri": "doc://withtext", "mime_type": "text/plain", "filename": "d.txt",
               "size_bytes": 5, "expires_at": past}
        _insert_message(mem_db, "s1", [att])
        mem_db.execute(
            "INSERT INTO document_chunks_vec (embedding, attachment_id, filename, chunk_index, chunk_text, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (json.dumps([0.0] * 3072), "withtext", "d.txt", "0", "permanent text", "2026-01-01 00:00:00"),
        )
        mem_db.commit()

        with patch.object(chat_service, "r2_storage_service"):
            chat_service.sweep_expired_attachments()

        row = mem_db.execute(
            "SELECT chunk_text FROM document_chunks_vec WHERE attachment_id = 'withtext'"
        ).fetchone()
        assert row["chunk_text"] == "permanent text"

    def test_no_attachments_rows_returns_zero_swept(self, mem_db):
        _insert_message(mem_db, "s1", None)
        with patch.object(chat_service, "r2_storage_service") as mock_r2:
            result = chat_service.sweep_expired_attachments()
        mock_r2.delete.assert_not_called()
        assert result == {"swept": 0, "attachment_ids": [], "errors": []}

    def test_other_file_scheme_swept_same_as_document(self, mem_db):
        # Chat-R14a: "other" (non-document) files use file://<id>, not doc://<id>,
        # but must be swept identically (full removal) — no document_chunks_vec
        # entry to worry about, so the only cleanup is the R2 object.
        past = _iso(datetime.now(timezone.utc) - timedelta(days=1))
        att = {"uri": "file://archive1", "mime_type": "application/zip", "filename": "a.zip",
               "size_bytes": 5, "expires_at": past}
        msg_id = _insert_message(mem_db, "s1", [att])

        with patch.object(chat_service, "r2_storage_service") as mock_r2:
            result = chat_service.sweep_expired_attachments()

        mock_r2.delete.assert_called_once_with("chat-attachments/archive1.zip")
        assert result["swept"] == 1
        assert "archive1" in result["attachment_ids"]
        row = mem_db.execute("SELECT attachments FROM chat_messages WHERE id = ?", (msg_id,)).fetchone()
        assert json.loads(row["attachments"]) == []

    def test_image_r2_twin_expired_clears_only_r2_fields_keeps_gemini_fields(self, mem_db):
        # Chat-R14a dual-write: r2_attachment_id/r2_expires_at are a separate
        # clock from uri/expires_at (Gemini's own real 48h expiry). Once the R2
        # copy expires, only the R2-specific fields are cleared — the Gemini
        # uri/expires_at/filename/mime_type must survive untouched (still
        # meaningful for the "expired" chip / _load_history_messages checks).
        r2_past = _iso(datetime.now(timezone.utc) - timedelta(days=1))
        gemini_expires = "2026-01-01T00:00:00+00:00"
        att = {
            "uri": "https://generativelanguage.googleapis.com/v1beta/files/xyz",
            "mime_type": "image/png", "filename": "shot.png", "size_bytes": 5,
            "expires_at": gemini_expires,
            "r2_attachment_id": "r2img1", "r2_expires_at": r2_past,
        }
        msg_id = _insert_message(mem_db, "s1", [att])

        with patch.object(chat_service, "r2_storage_service") as mock_r2:
            result = chat_service.sweep_expired_attachments()

        mock_r2.delete.assert_called_once_with("chat-attachments/r2img1.png")
        assert result["swept"] == 1
        assert "r2img1" in result["attachment_ids"]

        row = mem_db.execute("SELECT attachments FROM chat_messages WHERE id = ?", (msg_id,)).fetchone()
        remaining = json.loads(row["attachments"])
        assert len(remaining) == 1
        kept_att = remaining[0]
        assert kept_att["uri"] == att["uri"]
        assert kept_att["expires_at"] == gemini_expires
        assert kept_att["filename"] == "shot.png"
        assert kept_att["r2_attachment_id"] is None
        assert kept_att["r2_expires_at"] is None

    def test_image_r2_twin_not_yet_expired_untouched(self, mem_db):
        r2_future = _iso(datetime.now(timezone.utc) + timedelta(days=10))
        att = {
            "uri": "https://generativelanguage.googleapis.com/v1beta/files/xyz",
            "mime_type": "image/png", "filename": "shot.png", "size_bytes": 5,
            "expires_at": "2026-01-01T00:00:00+00:00",
            "r2_attachment_id": "r2img2", "r2_expires_at": r2_future,
        }
        msg_id = _insert_message(mem_db, "s1", [att])

        with patch.object(chat_service, "r2_storage_service") as mock_r2:
            result = chat_service.sweep_expired_attachments()

        mock_r2.delete.assert_not_called()
        assert result["swept"] == 0
        row = mem_db.execute("SELECT attachments FROM chat_messages WHERE id = ?", (msg_id,)).fetchone()
        assert json.loads(row["attachments"]) == [att]

    def test_image_without_r2_dual_write_still_untouched(self, mem_db):
        # Pre-R14a historical record — no r2_attachment_id at all.
        past = _iso(datetime.now(timezone.utc) - timedelta(days=1))
        att = {"uri": "https://generativelanguage.googleapis.com/v1beta/files/old",
               "mime_type": "image/png", "filename": "old.png", "size_bytes": 5,
               "expires_at": past}
        msg_id = _insert_message(mem_db, "s1", [att])

        with patch.object(chat_service, "r2_storage_service") as mock_r2:
            result = chat_service.sweep_expired_attachments()

        mock_r2.delete.assert_not_called()
        assert result["swept"] == 0
        row = mem_db.execute("SELECT attachments FROM chat_messages WHERE id = ?", (msg_id,)).fetchone()
        assert json.loads(row["attachments"]) == [att]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
