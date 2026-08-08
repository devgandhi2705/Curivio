"""
Tests for Chat-R16's files panel data source:

- chat_service.list_session_attachments (unit-level, real in-memory db) —
  proves it's unbounded (unlike get_history's `limit`), flattens every
  message's attachments, most-recent first, and skips messages with none.
- GET /chat/attachments/{session_id} (endpoint-level) — same ownership gate
  as GET /chat/history/{session_id} (_require_session_access), always 404
  never 403 for another user's session.
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


class TestListSessionAttachments:
    def test_flattens_attachments_across_multiple_messages(self, mem_db):
        mem_db.execute("INSERT INTO chat_sessions (session_id, title) VALUES (?, ?)", ("s1", "t"))
        mem_db.commit()
        att1 = {"uri": "doc://a1", "mime_type": "application/pdf", "filename": "one.pdf", "size_bytes": 1}
        att2 = {"uri": "file://a2", "mime_type": "application/zip", "filename": "two.zip", "size_bytes": 2}
        chat_service._save_message("s1", "user", "hi",   None, "2026-01-01 00:00:00", attachments=[att1])
        chat_service._save_message("s1", "user", "more", None, "2026-01-01 00:01:00", attachments=[att2])

        result = chat_service.list_session_attachments("s1")
        filenames = {a["filename"] for a in result}
        assert filenames == {"one.pdf", "two.zip"}

    def test_unbounded_beyond_a_50_message_cap(self, mem_db):
        # get_history/fetchHistory cap at 50 messages — this must not.
        mem_db.execute("INSERT INTO chat_sessions (session_id, title) VALUES (?, ?)", ("s1", "t"))
        mem_db.commit()
        for i in range(60):
            atts = [{"uri": f"doc://msg{i}", "mime_type": "application/pdf", "filename": f"f{i}.pdf"}] if i in (0, 59) else None
            chat_service._save_message("s1", "user", f"msg {i}", None, f"2026-01-01 00:{i:02d}:00", attachments=atts)

        result = chat_service.list_session_attachments("s1")
        filenames = {a["filename"] for a in result}
        assert filenames == {"f0.pdf", "f59.pdf"}  # first AND 60th message both present

    def test_most_recent_first(self, mem_db):
        mem_db.execute("INSERT INTO chat_sessions (session_id, title) VALUES (?, ?)", ("s1", "t"))
        mem_db.commit()
        att_early = {"uri": "doc://early", "mime_type": "application/pdf", "filename": "early.pdf"}
        att_late  = {"uri": "doc://late",  "mime_type": "application/pdf", "filename": "late.pdf"}
        chat_service._save_message("s1", "user", "hi",   None, "2026-01-01 00:00:00", attachments=[att_early])
        chat_service._save_message("s1", "user", "more", None, "2026-01-01 00:05:00", attachments=[att_late])

        result = chat_service.list_session_attachments("s1")
        assert [a["filename"] for a in result] == ["late.pdf", "early.pdf"]

    def test_carries_owning_message_created_at(self, mem_db):
        mem_db.execute("INSERT INTO chat_sessions (session_id, title) VALUES (?, ?)", ("s1", "t"))
        mem_db.commit()
        att = {"uri": "doc://a1", "mime_type": "application/pdf", "filename": "one.pdf"}
        chat_service._save_message("s1", "user", "hi", None, "2026-01-01 00:00:00", attachments=[att])

        result = chat_service.list_session_attachments("s1")
        assert result[0]["created_at"] == "2026-01-01 00:00:00"

    def test_skips_messages_with_no_attachments(self, mem_db):
        mem_db.execute("INSERT INTO chat_sessions (session_id, title) VALUES (?, ?)", ("s1", "t"))
        mem_db.commit()
        chat_service._save_message("s1", "user", "text only", None, "2026-01-01 00:00:00")
        chat_service._save_message("s1", "assistant", "reply", None, "2026-01-01 00:01:00")

        assert chat_service.list_session_attachments("s1") == []

    def test_other_sessions_attachments_not_included(self, mem_db):
        mem_db.execute("INSERT INTO chat_sessions (session_id, title) VALUES (?, ?)", ("s1", "t"))
        mem_db.execute("INSERT INTO chat_sessions (session_id, title) VALUES (?, ?)", ("s2", "t"))
        mem_db.commit()
        att = {"uri": "doc://other", "mime_type": "application/pdf", "filename": "other.pdf"}
        chat_service._save_message("s2", "user", "hi", None, "2026-01-01 00:00:00", attachments=[att])

        assert chat_service.list_session_attachments("s1") == []

    def test_unknown_session_returns_empty_list(self, mem_db):
        assert chat_service.list_session_attachments("no-such-session") == []


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from backend.main import app
    return TestClient(app, raise_server_exceptions=False)


class TestChatAttachmentsEndpoint:
    def test_owner_gets_the_list(self, client):
        from backend.main import app, get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        try:
            with patch("backend.services.chat_title_service.get_session_owner", return_value="u1"), \
                 patch("backend.services.chat_service.list_session_attachments", return_value=[
                     {"uri": "doc://a1", "mime_type": "application/pdf", "filename": "one.pdf",
                      "created_at": "2026-01-01 00:00:00"},
                 ]):
                resp = client.get("/chat/attachments/s1")
        finally:
            app.dependency_overrides.pop(get_current_user, None)
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["filename"] == "one.pdf"
        assert body[0]["created_at"] == "2026-01-01 00:00:00"

    def test_other_users_session_returns_404_not_403(self, client):
        from backend.main import app, get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "attacker"}
        try:
            with patch("backend.services.chat_title_service.get_session_owner", return_value="u1"), \
                 patch("backend.services.chat_service.list_session_attachments") as mock_list:
                resp = client.get("/chat/attachments/s1")
        finally:
            app.dependency_overrides.pop(get_current_user, None)
        assert resp.status_code == 404
        mock_list.assert_not_called()

    def test_unauthenticated_request_rejected(self, client):
        resp = client.get("/chat/attachments/s1")
        assert resp.status_code in (401, 403)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
