"""
Tests for Chat-R15a's share-scoped attachment access:
- chat_service.attachment_belongs_to_session (ownership join, unit-level)
- share_service.resolve_chat_session_id (token -> session_id, unit-level)
- GET /share/{token}/attachment/{attachment_id}/{filename} (endpoint-level)

Endpoint tests mock the two service functions above plus
r2_storage_service.download_stream — same convention test_chat.py already
uses for endpoint tests (patch at the service-function boundary, not the DB
layer), which also sidesteps TestClient's request thread not matching an
in-memory sqlite connection's owning thread. DB-touching logic itself is
covered directly against a real in-memory db in the unit-level test classes.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.database.schema import ALL_TABLES
from backend.services import chat_service, share_service
from backend.utils import db as db_module


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

    # chat_service imports get_connection at module load time (top-level
    # import) -> patch its own bound name. share_service imports it fresh
    # inside each function body -> patch the source module instead, per the
    # project's own patch-target convention for lazy/deferred imports.
    monkeypatch.setattr(chat_service, "get_connection", _get_conn)
    monkeypatch.setattr(db_module, "get_connection", _get_conn)
    yield conn
    conn.close()


def _seed_session(conn, session_id, attachments):
    conn.execute("INSERT INTO chat_sessions (session_id, title) VALUES (?, ?)", (session_id, "t"))
    conn.execute(
        "INSERT INTO chat_messages (session_id, role, content, attachments) VALUES (?, ?, ?, ?)",
        (session_id, "user", "hi", json.dumps(attachments) if attachments is not None else None),
    )
    conn.commit()


def _seed_share_link(conn, token, type_, resource_id, created_by="u1"):
    conn.execute(
        "INSERT INTO share_links (id, type, resource_id, created_by) VALUES (?, ?, ?, ?)",
        (token, type_, resource_id, created_by),
    )
    conn.commit()


class TestAttachmentBelongsToSession:
    def test_true_for_document_or_other_file_uri(self, mem_db):
        att = {"uri": "file://real1", "mime_type": "application/zip", "filename": "a.zip", "size_bytes": 4}
        _seed_session(mem_db, "sessA", [att])
        assert chat_service.attachment_belongs_to_session("sessA", "real1") is True

    def test_true_for_doc_scheme(self, mem_db):
        att = {"uri": "doc://real2", "mime_type": "application/pdf", "filename": "a.pdf", "size_bytes": 4}
        _seed_session(mem_db, "sessA", [att])
        assert chat_service.attachment_belongs_to_session("sessA", "real2") is True

    def test_true_for_image_r2_attachment_id(self, mem_db):
        att = {"uri": "https://generativelanguage.googleapis.com/v1beta/files/xyz",
               "mime_type": "image/png", "filename": "shot.png", "size_bytes": 4,
               "r2_attachment_id": "r2img1"}
        _seed_session(mem_db, "sessA", [att])
        assert chat_service.attachment_belongs_to_session("sessA", "r2img1") is True

    def test_false_when_attachment_belongs_to_a_different_session(self, mem_db):
        att_a = {"uri": "file://ownedbyA", "mime_type": "application/zip", "filename": "a.zip", "size_bytes": 4}
        att_b = {"uri": "file://ownedbyB", "mime_type": "application/zip", "filename": "b.zip", "size_bytes": 4}
        _seed_session(mem_db, "sessA", [att_a])
        _seed_session(mem_db, "sessB", [att_b])
        assert chat_service.attachment_belongs_to_session("sessA", "ownedbyB") is False

    def test_false_for_session_with_no_attachments(self, mem_db):
        _seed_session(mem_db, "sessA", None)
        assert chat_service.attachment_belongs_to_session("sessA", "anything") is False

    def test_false_for_nonexistent_session(self, mem_db):
        assert chat_service.attachment_belongs_to_session("no-such-session", "anything") is False


class TestResolveChatSessionId:
    def test_returns_session_id_for_valid_chat_token(self, mem_db):
        _seed_share_link(mem_db, "tok-a", "chat", "sessA")
        assert share_service.resolve_chat_session_id("tok-a") == "sessA"

    def test_returns_none_for_unknown_token(self, mem_db):
        assert share_service.resolve_chat_session_id("nope") is None

    def test_returns_none_for_non_chat_type(self, mem_db):
        _seed_share_link(mem_db, "tok-feed", "feed", "proj1/2026-01-01")
        assert share_service.resolve_chat_session_id("tok-feed") is None


class TestResolveShareLinkIncludesAttachments:
    """Chat-R15a: resolve_share_link's chat branch must now surface
    attachments — same convention as chat_service.get_history (raw stored
    list, or None when absent, no filtering here)."""

    def test_chat_share_messages_include_attachments_list(self, mem_db):
        att = {"uri": "file://real1", "mime_type": "application/zip", "filename": "a.zip", "size_bytes": 4}
        _seed_session(mem_db, "sessA", [att])
        _seed_share_link(mem_db, "tok-a", "chat", "sessA")

        result = share_service.resolve_share_link("tok-a")
        assert result["type"] == "chat"
        assert result["messages"][0]["attachments"] == [att]

    def test_chat_share_message_with_no_attachments_is_none(self, mem_db):
        _seed_session(mem_db, "sessA", None)
        _seed_share_link(mem_db, "tok-a", "chat", "sessA")

        result = share_service.resolve_share_link("tok-a")
        assert result["messages"][0]["attachments"] is None


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from backend.main import app
    return TestClient(app, raise_server_exceptions=False)


class TestShareAttachmentEndpoint:
    def test_valid_join_streams_bytes_no_login(self, client):
        with patch("backend.services.share_service.resolve_chat_session_id", return_value="sessA"), \
             patch("backend.services.chat_service.attachment_belongs_to_session", return_value=True), \
             patch("backend.services.r2_storage_service.download_stream",
                   return_value=(iter([b"data"]), 4)) as mock_stream:
            resp = client.get("/share/tok-a/attachment/real1/a.zip")

        assert resp.status_code == 200
        assert resp.content == b"data"
        mock_stream.assert_called_once_with("chat-attachments/real1.zip")

    def test_skeleton_key_attack_blocked_bad_join_returns_404(self, client):
        # Real attack scenario R15 recon flagged: a valid token resolves to a
        # real session, but the requested attachment_id isn't actually in it.
        with patch("backend.services.share_service.resolve_chat_session_id", return_value="sessA"), \
             patch("backend.services.chat_service.attachment_belongs_to_session", return_value=False), \
             patch("backend.services.r2_storage_service.download_stream") as mock_stream:
            resp = client.get("/share/tok-a/attachment/ownedbyB/b.zip")

        assert resp.status_code == 404
        mock_stream.assert_not_called()

    def test_invalid_token_returns_404_before_any_streaming(self, client):
        with patch("backend.services.share_service.resolve_chat_session_id", return_value=None) as mock_resolve, \
             patch("backend.services.chat_service.attachment_belongs_to_session") as mock_owns, \
             patch("backend.services.r2_storage_service.download_stream") as mock_stream:
            resp = client.get("/share/does-not-exist/attachment/whatever/f.txt")

        assert resp.status_code == 404
        mock_resolve.assert_called_once_with("does-not-exist")
        mock_owns.assert_not_called()
        mock_stream.assert_not_called()

    def test_r2_object_gone_returns_404_same_as_authenticated_path(self, client):
        # Same honest "expired/swept" outcome as chat_attachment_file_endpoint
        # — no separate expiry logic needed, it falls out of the shared streamer.
        not_found = ClientError({"Error": {"Code": "NoSuchKey", "Message": "nope"}}, "GetObject")
        with patch("backend.services.share_service.resolve_chat_session_id", return_value="sessA"), \
             patch("backend.services.chat_service.attachment_belongs_to_session", return_value=True), \
             patch("backend.services.r2_storage_service.download_stream", side_effect=not_found):
            resp = client.get("/share/tok-a/attachment/expired1/e.txt")
        assert resp.status_code == 404

    def test_non_inline_type_still_forced_to_download_disposition(self, client):
        # Shared streaming core's XSS-prevention allowlist applies identically
        # on the share-scoped path.
        with patch("backend.services.share_service.resolve_chat_session_id", return_value="sessA"), \
             patch("backend.services.chat_service.attachment_belongs_to_session", return_value=True), \
             patch("backend.services.r2_storage_service.download_stream",
                   return_value=(iter([b"data"]), 4)):
            resp = client.get("/share/tok-a/attachment/doc1/report.docx")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/octet-stream"
        assert resp.headers["content-disposition"] == 'attachment; filename="report.docx"'

    def test_image_served_inline(self, client):
        with patch("backend.services.share_service.resolve_chat_session_id", return_value="sessA"), \
             patch("backend.services.chat_service.attachment_belongs_to_session", return_value=True), \
             patch("backend.services.r2_storage_service.download_stream",
                   return_value=(iter([b"\x89PNG"]), 4)):
            resp = client.get("/share/tok-a/attachment/r2img1/shot.png")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert "content-disposition" not in resp.headers

    def test_no_auth_header_required(self, client):
        # Sanity: no Authorization header is sent anywhere in this file, and
        # every request above already succeeds/fails purely on the token join
        # — confirms the route has no Depends(get_current_user).
        with patch("backend.services.share_service.resolve_chat_session_id", return_value="sessA"), \
             patch("backend.services.chat_service.attachment_belongs_to_session", return_value=True), \
             patch("backend.services.r2_storage_service.download_stream",
                   return_value=(iter([b"data"]), 4)):
            resp = client.get("/share/tok-a/attachment/real1/a.zip")
        assert resp.status_code == 200


class TestShareAttachmentDocumentEndpoint:
    """Chat-R15b: GET /share/{token}/attachment/document/{attachment_id} —
    mirrors share_attachment_file_endpoint's ownership join verbatim."""

    def test_valid_join_returns_text(self, client):
        with patch("backend.services.share_service.resolve_chat_session_id", return_value="sessA"), \
             patch("backend.services.chat_service.attachment_belongs_to_session", return_value=True), \
             patch("backend.services.document_memory_service.get_full_text", return_value="real extracted text"):
            resp = client.get("/share/tok-a/attachment/document/doc1")
        assert resp.status_code == 200
        assert resp.json() == {"text": "real extracted text"}

    def test_skeleton_key_attack_blocked_bad_join_returns_404(self, client):
        # Same attack shape as R15a's binary-endpoint test: valid token for
        # session A, real document attachment_id that belongs to session B.
        with patch("backend.services.share_service.resolve_chat_session_id", return_value="sessA"), \
             patch("backend.services.chat_service.attachment_belongs_to_session", return_value=False) as mock_owns, \
             patch("backend.services.document_memory_service.get_full_text") as mock_text:
            resp = client.get("/share/tok-a/attachment/document/ownedbyB")
        assert resp.status_code == 404
        mock_owns.assert_called_once_with("sessA", "ownedbyB")
        mock_text.assert_not_called()

    def test_invalid_token_returns_404_before_any_text_lookup(self, client):
        with patch("backend.services.share_service.resolve_chat_session_id", return_value=None), \
             patch("backend.services.chat_service.attachment_belongs_to_session") as mock_owns, \
             patch("backend.services.document_memory_service.get_full_text") as mock_text:
            resp = client.get("/share/does-not-exist/attachment/document/whatever")
        assert resp.status_code == 404
        mock_owns.assert_not_called()
        mock_text.assert_not_called()

    def test_document_gone_returns_404_same_as_authenticated_path(self, client):
        with patch("backend.services.share_service.resolve_chat_session_id", return_value="sessA"), \
             patch("backend.services.chat_service.attachment_belongs_to_session", return_value=True), \
             patch("backend.services.document_memory_service.get_full_text", return_value=None):
            resp = client.get("/share/tok-a/attachment/document/gone1")
        assert resp.status_code == 404

    def test_no_auth_header_required(self, client):
        with patch("backend.services.share_service.resolve_chat_session_id", return_value="sessA"), \
             patch("backend.services.chat_service.attachment_belongs_to_session", return_value=True), \
             patch("backend.services.document_memory_service.get_full_text", return_value="text"):
            resp = client.get("/share/tok-a/attachment/document/doc1")
        assert resp.status_code == 200


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
