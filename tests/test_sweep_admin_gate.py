"""
Tests that POST /admin/attachments/sweep is gated by get_current_admin_user(),
same shape as test_admin_gate.py's coverage of /projects/generate-all
(Chat-R13 GOAL: "reuses get_current_admin_user() verbatim, same pattern as
/projects/generate-all").
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from backend.main import app, get_current_user
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "test-user", "email": "not-admin@example.com",
    }
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


class TestSweepAttachmentsAdminGate:
    def test_non_admin_blocked_404(self, client):
        with patch("backend.services.auth_service.ADMIN_EMAILS", "admin@example.com"), \
             patch("backend.services.chat_service.sweep_expired_attachments") as mock_sweep:
            resp = client.post("/admin/attachments/sweep")
        assert resp.status_code == 404
        mock_sweep.assert_not_called()

    def test_admin_allowed_200(self, client):
        from backend.main import app, get_current_user
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "admin-user", "email": "admin@example.com",
        }
        summary = {"swept": 2, "attachment_ids": ["a", "b"], "errors": []}
        try:
            with patch("backend.services.auth_service.ADMIN_EMAILS", "admin@example.com"), \
                 patch("backend.services.chat_service.sweep_expired_attachments", return_value=summary) as mock_sweep:
                resp = client.post("/admin/attachments/sweep")
        finally:
            app.dependency_overrides.pop(get_current_user, None)
        assert resp.status_code == 200
        assert resp.json() == summary
        mock_sweep.assert_called_once()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
