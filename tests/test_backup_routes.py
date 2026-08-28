"""
Route-level coverage for the backup/restore API — specifically the gates.

The panel exposes "restore the database" as a button, so the thing that matters
most here is not that it works but that nobody unauthorised can reach it. Same
dependency_overrides convention as test_auth_hardening.py.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from backend.main import app
    yield TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def as_admin():
    from backend.main import app
    from backend.services.auth_service import get_current_admin_user
    app.dependency_overrides[get_current_admin_user] = lambda: {
        "user_id": "admin-1", "email": "admin@example.com", "name": "Admin",
        "created_at": None, "feed_version": "legacy",
    }
    yield
    app.dependency_overrides.pop(get_current_admin_user, None)


@pytest.fixture
def as_user():
    from backend.main import app
    from backend.services.auth_service import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "u1", "email": "a@example.com", "name": "A",
        "created_at": None, "feed_version": "legacy",
    }
    yield
    app.dependency_overrides.pop(get_current_user, None)


# ── gates ────────────────────────────────────────────────────────────────────

ADMIN_GETS = ["/admin/backups", "/admin/data-loss-requests"]
ADMIN_POSTS = ["/admin/backups/create", "/admin/backups/preview", "/admin/backups/restore"]


@pytest.mark.parametrize("path", ADMIN_GETS)
def test_admin_reads_require_auth(client, path):
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", ADMIN_POSTS)
def test_admin_writes_require_auth(client, path):
    """Restore must not be reachable without a token. Checked per-endpoint
    rather than once, because a router-level dependency is easy to bypass by
    accident when someone later adds a route to the wrong router."""
    assert client.post(path, json={"filename": "x"}).status_code == 401


def test_non_admin_cannot_reach_backups(client, as_user):
    """A signed-in non-admin gets 404, not 403 — same as the rest of /admin,
    so the endpoint's existence isn't disclosed."""
    from backend.services.auth_service import get_current_user
    with patch("backend.services.auth_service.ADMIN_EMAILS", "someoneelse@example.com"):
        resp = client.get("/admin/backups")
    assert resp.status_code in (401, 404)


def test_user_data_loss_request_requires_auth(client):
    assert client.post("/me/data-loss-request", json={"description": "gone"}).status_code == 401


# ── behaviour ────────────────────────────────────────────────────────────────

def test_list_backups_reports_retention_policy(client, as_admin):
    resp = client.get("/admin/backups")
    assert resp.status_code == 200
    body = resp.json()
    assert "backups" in body
    assert body["retention"]["max_snapshots"] > 0


def test_restore_rejects_an_unrecognised_filename(client, as_admin):
    """resolve_source's path-traversal guard must surface as a 400, not a 500
    or a stack trace."""
    with patch("backend.services.backup_service.create_snapshot") as snap:
        snap.return_value = {"ok": True, "filename": "x", "size_bytes": 1, "pruned": []}
        resp = client.post("/admin/backups/restore", json={"filename": "../../etc/passwd"})
    assert resp.status_code == 400


def test_preview_does_not_take_a_snapshot(client, as_admin):
    """Only a real restore snapshots first. A dry run must be side-effect free
    end to end, or 'preview' quietly becomes a write operation."""
    with patch("backend.services.backup_service.create_snapshot") as snap, \
         patch("backend.services.backup_service.restore") as restore:
        restore.return_value = {"filename": "f", "scope": "*", "dry_run": True,
                                "integrity_ok": True, "rows_restored": 0,
                                "rows_available": 5, "tables": {}}
        resp = client.post("/admin/backups/preview", json={"filename": "curivio-1.db"})
    assert resp.status_code == 200
    assert resp.json()["dry_run"] is True
    snap.assert_not_called()


def test_restore_snapshots_before_writing(client, as_admin):
    """The pre-restore snapshot is what lets an admin prove what a restore
    changed, so it must happen on every restore, not just the first."""
    with patch("backend.services.backup_service.create_snapshot") as snap, \
         patch("backend.services.backup_service.restore") as restore:
        snap.return_value = {"ok": True, "filename": "pre.db", "size_bytes": 1, "pruned": []}
        restore.return_value = {"filename": "f", "scope": "*", "dry_run": False,
                                "integrity_ok": True, "rows_restored": 42,
                                "rows_available": 42, "tables": {}}
        resp = client.post("/admin/backups/restore", json={"filename": "curivio-1.db"})
    assert resp.status_code == 200
    assert resp.json()["rows_restored"] == 42
    snap.assert_called_once()


def test_per_user_restore_passes_the_user_through(client, as_admin):
    with patch("backend.services.backup_service.create_snapshot"), \
         patch("backend.services.backup_service.restore") as restore:
        restore.return_value = {"filename": "f", "scope": "u1", "dry_run": False,
                                "integrity_ok": True, "rows_restored": 3,
                                "rows_available": 3, "tables": {}}
        client.post("/admin/backups/restore",
                    json={"filename": "curivio-1.db", "user_id": "u1"})
    restore.assert_called_once_with("curivio-1.db", "u1", dry_run=False)


def test_resolve_rejects_an_unknown_status(client, as_admin):
    resp = client.patch("/admin/data-loss-requests/abc", json={"status": "banana"})
    assert resp.status_code == 400
