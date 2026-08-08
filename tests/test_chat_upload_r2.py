"""
Tests for POST /chat/upload's Chat-R13 wiring: document attachments now also
upload their raw bytes to R2 and get a real expires_at (previously always
None). document_memory_service.store_document and r2_storage_service.upload
are mocked — real-R2 verification is a separate live script (STEP 3).
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


class TestChatUploadR2Wiring:
    def test_document_upload_calls_r2_upload_and_sets_expires_at(self, client):
        with patch("backend.services.document_memory_service.store_document", return_value="fixed-id-123") as mock_store, \
             patch("backend.services.r2_storage_service.upload") as mock_upload:
            resp = client.post(
                "/chat/upload",
                files={"file": ("notes.txt", io.BytesIO(b"hello world"), "text/plain")},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["uri"] == "doc://fixed-id-123"
        assert body["size_bytes"] == len(b"hello world")

        mock_upload.assert_called_once_with(b"hello world", "chat-attachments/fixed-id-123.txt", content_type="text/plain")
        mock_store.assert_called_once()

        expires_at = datetime.fromisoformat(body["expires_at"])
        expected = datetime.now(timezone.utc) + timedelta(days=cfg.ATTACHMENT_RETENTION_DAYS)
        assert abs((expires_at - expected).total_seconds()) < 30

    def test_r2_upload_failure_returns_502(self, client):
        with patch("backend.services.document_memory_service.store_document", return_value="fixed-id-456"), \
             patch("backend.services.r2_storage_service.upload", side_effect=RuntimeError("r2 down")):
            resp = client.post(
                "/chat/upload",
                files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")},
            )
        assert resp.status_code == 502


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
