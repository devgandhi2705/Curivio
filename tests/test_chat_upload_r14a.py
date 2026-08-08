"""
Tests for Chat-R14a's /chat/upload changes: the "other file" branch (not
image, not a known document extension), the image dual-write to R2, and the
raised 50MB cap. External calls (Gemini, R2, embeddings) are mocked — real
verification is a separate live script (STEP 3).
"""
from __future__ import annotations

import io
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import app_config as cfg


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


class TestUploadCap:
    def test_default_cap_is_50mb(self):
        assert cfg.CHAT_UPLOAD_MAX_BYTES == 50 * 1024 * 1024

    def test_oversize_file_rejected_with_413_and_real_limit_in_message(self, client):
        # One byte over the cap — don't allocate the whole 50MB+1 in the test,
        # just prove the cap constant (not a stale hardcoded 20MB) drives the check.
        with patch("backend.main.cfg.CHAT_UPLOAD_MAX_BYTES", 10):
            resp = client.post(
                "/chat/upload",
                files={"file": ("notes.txt", io.BytesIO(b"x" * 11), "text/plain")},
            )
        assert resp.status_code == 413
        assert "0MB limit" in resp.json()["detail"]  # 10 // (1024*1024) == 0, proves it reads the patched cap


class TestOtherFileBranch:
    def test_unknown_extension_accepted_uploads_to_r2_no_extraction(self, client):
        with patch("backend.services.r2_storage_service.upload") as mock_upload, \
             patch("backend.services.document_memory_service.store_document") as mock_store, \
             patch("backend.services.document_extraction_service.extract_document_text") as mock_extract:
            resp = client.post(
                "/chat/upload",
                files={"file": ("archive.zip", io.BytesIO(b"PK\x03\x04fakezip"), "application/zip")},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["uri"].startswith("file://")
        assert body["mime_type"] == "application/zip"
        assert body["size_bytes"] == len(b"PK\x03\x04fakezip")

        attachment_id = body["uri"].removeprefix("file://")
        mock_upload.assert_called_once_with(b"PK\x03\x04fakezip", f"chat-attachments/{attachment_id}.zip", content_type="application/zip")
        mock_store.assert_not_called()
        mock_extract.assert_not_called()

    def test_xlsx_treated_as_other_file_not_document(self, client):
        with patch("backend.services.r2_storage_service.upload"), \
             patch("backend.services.document_memory_service.store_document") as mock_store:
            resp = client.post(
                "/chat/upload",
                files={"file": ("sheet.xlsx", io.BytesIO(b"fake xlsx bytes"),
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["uri"].startswith("file://")
        mock_store.assert_not_called()

    def test_missing_extension_falls_back_to_octet_stream_mime(self, client):
        with patch("backend.services.r2_storage_service.upload"):
            resp = client.post(
                "/chat/upload",
                files={"file": ("noext", io.BytesIO(b"data"), "")},
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["mime_type"] == "application/octet-stream"


class TestImageDualWrite:
    def test_image_upload_also_writes_to_r2_with_own_id_and_expiry(self, client):
        gemini_result = {
            "uri": "https://generativelanguage.googleapis.com/v1beta/files/abc123",
            "mime_type": "image/png",
            "filename": "shot.png",
            "size_bytes": 5,
            "expires_at": "2026-07-20T00:00:00+00:00",  # Gemini's real 48h clock
        }
        with patch("backend.llm.model_provider.upload_attachment", return_value=gemini_result) as mock_gemini, \
             patch("backend.services.r2_storage_service.upload") as mock_r2:
            resp = client.post(
                "/chat/upload",
                files={"file": ("shot.png", io.BytesIO(b"12345"), "image/png")},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()

        # Gemini's own uri/expires_at pass through untouched.
        assert body["uri"] == gemini_result["uri"]
        assert body["expires_at"] == gemini_result["expires_at"]

        # A separate R2 identity + clock, not reusing the Gemini fields.
        assert body["r2_attachment_id"]
        assert body["r2_attachment_id"] not in body["uri"]
        r2_expires = datetime.fromisoformat(body["r2_expires_at"])
        expected = datetime.now(timezone.utc) + timedelta(days=cfg.ATTACHMENT_RETENTION_DAYS)
        assert abs((r2_expires - expected).total_seconds()) < 30

        mock_gemini.assert_called_once()
        mock_r2.assert_called_once_with(b"12345", f"chat-attachments/{body['r2_attachment_id']}.png", content_type="image/png")

    def test_gemini_failure_short_circuits_before_any_r2_call(self, client):
        with patch("backend.llm.model_provider.upload_attachment", side_effect=RuntimeError("gemini down")), \
             patch("backend.services.r2_storage_service.upload") as mock_r2:
            resp = client.post(
                "/chat/upload",
                files={"file": ("shot.png", io.BytesIO(b"12345"), "image/png")},
            )
        assert resp.status_code == 502
        mock_r2.assert_not_called()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
