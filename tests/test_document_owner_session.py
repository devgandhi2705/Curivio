"""
Tests for Chat-R15c: real session-ownership check on
GET /chat/attachment/document/{attachment_id} — closing the bug class
R7a/R10c already closed elsewhere (login-only was never enough).

- chat_service.get_document_owner_session (unit-level, real in-memory db)
- _save_message's new permanent-record write (unit-level)
- chat_attachment_document_endpoint (endpoint-level, mocked service boundary)

Deliberately proves the permanent record survives sweep — the whole reason
this isn't just a call to attachment_belongs_to_session, which scans the
mutable chat_messages.attachments JSON that sweep_expired_attachments prunes.
"""
from __future__ import annotations

import sqlite3
import sys
from contextlib import contextmanager
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


class TestSaveMessageRecordsDocumentOwner:
    def test_doc_attachment_records_permanent_session_owner(self, mem_db):
        mem_db.execute("INSERT INTO chat_sessions (session_id, title) VALUES (?, ?)", ("s1", "t"))
        mem_db.commit()
        att = {"uri": "doc://abc123", "mime_type": "application/pdf", "filename": "r.pdf", "size_bytes": 4}
        chat_service._save_message("s1", "user", "hi", None, "2026-01-01 00:00:00", attachments=[att])

        row = mem_db.execute(
            "SELECT session_id FROM document_attachment_sessions WHERE attachment_id = ?", ("abc123",)
        ).fetchone()
        assert row["session_id"] == "s1"

    def test_file_scheme_other_attachment_not_recorded(self, mem_db):
        # Only doc:// (text-extraction) attachments need this table — "other"
        # files have no analogous authenticated text endpoint.
        mem_db.execute("INSERT INTO chat_sessions (session_id, title) VALUES (?, ?)", ("s1", "t"))
        mem_db.commit()
        att = {"uri": "file://archive1", "mime_type": "application/zip", "filename": "a.zip", "size_bytes": 4}
        chat_service._save_message("s1", "user", "hi", None, "2026-01-01 00:00:00", attachments=[att])

        row = mem_db.execute(
            "SELECT session_id FROM document_attachment_sessions WHERE attachment_id = ?", ("archive1",)
        ).fetchone()
        assert row is None

    def test_no_attachments_records_nothing(self, mem_db):
        mem_db.execute("INSERT INTO chat_sessions (session_id, title) VALUES (?, ?)", ("s1", "t"))
        mem_db.commit()
        chat_service._save_message("s1", "assistant", "hello", None, "2026-01-01 00:00:00")
        count = mem_db.execute("SELECT COUNT(*) AS c FROM document_attachment_sessions").fetchone()["c"]
        assert count == 0

    def test_resaving_same_attachment_id_keeps_first_owner(self, mem_db):
        mem_db.execute("INSERT INTO chat_sessions (session_id, title) VALUES (?, ?)", ("s1", "t"))
        mem_db.execute("INSERT INTO chat_sessions (session_id, title) VALUES (?, ?)", ("s2", "t"))
        mem_db.commit()
        att = {"uri": "doc://shared1", "mime_type": "application/pdf", "filename": "r.pdf", "size_bytes": 4}
        chat_service._save_message("s1", "user", "hi", None, "2026-01-01 00:00:00", attachments=[att])
        chat_service._save_message("s2", "user", "hi again", None, "2026-01-01 00:00:01", attachments=[att])

        row = mem_db.execute(
            "SELECT session_id FROM document_attachment_sessions WHERE attachment_id = ?", ("shared1",)
        ).fetchone()
        assert row["session_id"] == "s1"


class TestGetDocumentOwnerSession:
    def test_returns_session_id_for_known_attachment(self, mem_db):
        mem_db.execute(
            "INSERT INTO document_attachment_sessions (attachment_id, session_id) VALUES (?, ?)",
            ("abc123", "s1"),
        )
        mem_db.commit()
        assert chat_service.get_document_owner_session("abc123") == "s1"

    def test_returns_none_for_unknown_attachment(self, mem_db):
        assert chat_service.get_document_owner_session("no-such-id") is None

    def test_survives_a_real_sweep_of_the_chat_messages_json(self, mem_db):
        # The whole point of this table: it must still resolve the owner even
        # after sweep_expired_attachments has dropped the JSON entry entirely.
        import json
        from datetime import datetime, timedelta, timezone

        mem_db.execute("INSERT INTO chat_sessions (session_id, title) VALUES (?, ?)", ("s1", "t"))
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        att = {"uri": "doc://swept1", "mime_type": "application/pdf", "filename": "r.pdf",
               "size_bytes": 4, "expires_at": past}
        chat_service._save_message("s1", "user", "hi", None, "2026-01-01 00:00:00", attachments=[att])

        with patch.object(chat_service, "r2_storage_service") as mock_r2:
            result = chat_service.sweep_expired_attachments()
        assert result["swept"] == 1

        row = mem_db.execute("SELECT attachments FROM chat_messages WHERE session_id = ?", ("s1",)).fetchone()
        assert json.loads(row["attachments"]) == []  # JSON entry really is gone

        assert chat_service.get_document_owner_session("swept1") == "s1"  # but this survives


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from backend.main import app
    return TestClient(app, raise_server_exceptions=False)


class TestChatAttachmentDocumentEndpointOwnership:
    def test_owner_gets_real_text(self, client):
        from backend.main import app, get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        try:
            with patch("backend.services.chat_service.get_document_owner_session", return_value="s1"), \
                 patch("backend.services.chat_title_service.get_session_owner", return_value="u1"), \
                 patch("backend.services.document_memory_service.get_full_text", return_value="real text"):
                resp = client.get("/chat/attachment/document/abc123")
        finally:
            app.dependency_overrides.pop(get_current_user, None)
        assert resp.status_code == 200
        assert resp.json() == {"text": "real text"}

    def test_other_users_document_returns_404_not_403(self, client):
        from backend.main import app, get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "attacker"}
        try:
            with patch("backend.services.chat_service.get_document_owner_session", return_value="s1"), \
                 patch("backend.services.chat_title_service.get_session_owner", return_value="u1"), \
                 patch("backend.services.document_memory_service.get_full_text") as mock_text:
                resp = client.get("/chat/attachment/document/abc123")
        finally:
            app.dependency_overrides.pop(get_current_user, None)
        assert resp.status_code == 404
        mock_text.assert_not_called()

    def test_unknown_attachment_returns_404_before_any_ownership_check(self, client):
        from backend.main import app, get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        try:
            with patch("backend.services.chat_service.get_document_owner_session", return_value=None) as mock_owner, \
                 patch("backend.services.chat_title_service.get_session_owner") as mock_sess_owner, \
                 patch("backend.services.document_memory_service.get_full_text") as mock_text:
                resp = client.get("/chat/attachment/document/gone")
        finally:
            app.dependency_overrides.pop(get_current_user, None)
        assert resp.status_code == 404
        mock_owner.assert_called_once_with("gone")
        mock_sess_owner.assert_not_called()
        mock_text.assert_not_called()

    def test_legacy_null_owner_session_allowed_through(self, client):
        # Matches the app-wide _require_owner convention: a session that
        # predates per-session ownership tracking (NULL user_id) is not
        # blocked for anyone — same behavior as _require_session_access.
        from backend.main import app, get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "anyone"}
        try:
            with patch("backend.services.chat_service.get_document_owner_session", return_value="legacy-session"), \
                 patch("backend.services.chat_title_service.get_session_owner", return_value=None), \
                 patch("backend.services.document_memory_service.get_full_text", return_value="legacy text"):
                resp = client.get("/chat/attachment/document/legacy1")
        finally:
            app.dependency_overrides.pop(get_current_user, None)
        assert resp.status_code == 200
        assert resp.json() == {"text": "legacy text"}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
