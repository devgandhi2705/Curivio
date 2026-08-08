"""
Tests for GET /chat/attachment/file/{attachment_id}/{filename} — Chat-R14a's
real binary-serving endpoint. r2_storage_service.download_stream is mocked;
real-R2 verification (byte-exact, real Content-Type) is a separate live
script (STEP 3).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from backend.main import app, get_current_user
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "test-user", "email": "user@example.com",
    }
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def _not_found():
    return ClientError({"Error": {"Code": "NoSuchKey", "Message": "nope"}}, "GetObject")


class TestChatAttachmentFileEndpoint:
    def test_streams_bytes_with_correct_content_type(self, client):
        with patch("backend.services.r2_storage_service.download_stream",
                   return_value=(iter([b"%PDF-1.4 fake", b"more bytes"]), 23)) as mock_stream:
            resp = client.get("/chat/attachment/file/abc123/report.pdf")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.content == b"%PDF-1.4 fakemore bytes"
        assert "content-disposition" not in resp.headers  # inline, safe type
        mock_stream.assert_called_once_with("chat-attachments/abc123.pdf")

    def test_image_also_served_inline_no_disposition(self, client):
        with patch("backend.services.r2_storage_service.download_stream",
                   return_value=(iter([b"\x89PNG"]), 4)):
            resp = client.get("/chat/attachment/file/some-id-999/photo.png")
        assert resp.headers["content-type"] == "image/png"
        assert "content-disposition" not in resp.headers

    def test_reconstructs_key_from_attachment_id_and_extension(self, client):
        with patch("backend.services.r2_storage_service.download_stream",
                   return_value=(iter([b"x"]), 1)) as mock_stream:
            client.get("/chat/attachment/file/some-id-999/photo.png")
        mock_stream.assert_called_once_with("chat-attachments/some-id-999.png")

    def test_unknown_extension_falls_back_to_octet_stream_content_type(self, client):
        with patch("backend.services.r2_storage_service.download_stream",
                   return_value=(iter([b"data"]), 4)):
            resp = client.get("/chat/attachment/file/abc123/mystery.xyz123")
        assert resp.headers["content-type"] == "application/octet-stream"

    def test_non_safe_type_forced_to_attachment_disposition_and_octet_stream(self, client):
        # Security: docx/zip/csv/etc — anything outside the inline-safe image+PDF
        # allowlist — must never be served with its guessed real mime_type
        # inline (stored-XSS via e.g. evil.html/evil.svg through the "other
        # file" branch, which accepts any extension and has no ownership check).
        with patch("backend.services.r2_storage_service.download_stream",
                   return_value=(iter([b"data"]), 4)):
            resp = client.get("/chat/attachment/file/abc123/report.docx")
        assert resp.headers["content-type"] == "application/octet-stream"
        assert resp.headers["content-disposition"] == 'attachment; filename="report.docx"'
        assert resp.headers["x-content-type-options"] == "nosniff"

    def test_html_upload_never_rendered_inline(self, client):
        with patch("backend.services.r2_storage_service.download_stream",
                   return_value=(iter([b"<script>alert(1)</script>"]), 26)):
            resp = client.get("/chat/attachment/file/evil123/evil.html")
        assert resp.headers["content-type"] == "application/octet-stream"
        assert resp.headers["content-disposition"].startswith("attachment;")

    def test_svg_upload_never_rendered_inline(self, client):
        with patch("backend.services.r2_storage_service.download_stream",
                   return_value=(iter([b"<svg onload=alert(1)>"]), 21)):
            resp = client.get("/chat/attachment/file/evil456/evil.svg")
        assert resp.headers["content-type"] == "application/octet-stream"
        assert resp.headers["content-disposition"].startswith("attachment;")

    def test_filename_with_quote_is_sanitized_in_disposition_header(self, client):
        with patch("backend.services.r2_storage_service.download_stream",
                   return_value=(iter([b"data"]), 4)):
            resp = client.get('/chat/attachment/file/abc123/weird"name.docx')
        # exactly the two wrapping quotes the endpoint itself adds — none from
        # the attacker-controlled filename (which contained one internally)
        disposition = resp.headers["content-disposition"]
        assert disposition == 'attachment; filename="weirdname.docx"'
        assert disposition.count('"') == 2

    def test_nosniff_header_always_present(self, client):
        with patch("backend.services.r2_storage_service.download_stream",
                   return_value=(iter([b"data"]), 4)):
            resp = client.get("/chat/attachment/file/abc123/report.pdf")
        assert resp.headers["x-content-type-options"] == "nosniff"

    def test_missing_object_returns_404(self, client):
        with patch("backend.services.r2_storage_service.download_stream", side_effect=_not_found()):
            resp = client.get("/chat/attachment/file/gone/report.pdf")
        assert resp.status_code == 404

    def test_r2_error_other_than_not_found_returns_502(self, client):
        access_denied = ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "GetObject")
        with patch("backend.services.r2_storage_service.download_stream", side_effect=access_denied):
            resp = client.get("/chat/attachment/file/abc123/report.pdf")
        assert resp.status_code == 502


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
