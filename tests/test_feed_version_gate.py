"""
PATCH /auth/me/feed-version is admin-only.

Before this, any signed-in user could switch themselves to Feed v2 with one API call
and reach the unfinished v2 pipeline (claim_validator is still a stub). Only the
signed-in identity is stubbed here: the admin check (ADMIN_EMAILS) and the DB write
are real, against a throwaway DB.
"""
import sqlite3
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.utils import db as legacy_db

ADMIN = {"user_id": "admin-1", "email": "admin@example.com", "name": "Admin", "created_at": None,
         "feed_version": "legacy"}
USER = {"user_id": "user-1", "email": "user@example.com", "name": "User", "created_at": None,
        "feed_version": "legacy"}


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(legacy_db, "DB_PATH", tmp_path / "gate.db")
    legacy_db.init_db()
    with legacy_db.get_connection() as c:
        for u in (ADMIN, USER):
            c.execute("INSERT INTO users(user_id,email,name,hashed_pw) VALUES(?,?,?,'x')",
                      (u["user_id"], u["email"], u["name"]))
    return tmp_path / "gate.db"


@pytest.fixture
def client():
    from backend.main import app
    yield TestClient(app, raise_server_exceptions=False)
    from backend.services.auth_service import get_current_user
    app.dependency_overrides.pop(get_current_user, None)


def _signed_in_as(user):
    from backend.main import app
    from backend.services.auth_service import get_current_user
    app.dependency_overrides[get_current_user] = lambda: dict(user)


def _feed_version(db, user_id):
    c = sqlite3.connect(db)
    try:
        return c.execute("SELECT feed_version FROM users WHERE user_id=?", (user_id,)).fetchone()[0]
    finally:
        c.close()


def test_non_admin_cannot_switch_themselves_to_v2(db, client, capsys):
    _signed_in_as(USER)
    with patch("backend.services.auth_service.ADMIN_EMAILS", "admin@example.com"):
        resp = client.patch("/auth/me/feed-version", json={"feed_version": "v2"})
    with capsys.disabled():
        print(f"\nnon-admin PATCH -> {resp.status_code} {resp.json()} | row: {_feed_version(db, 'user-1')}")
    assert resp.status_code == 403
    assert _feed_version(db, "user-1") == "legacy"      # nothing written


def test_admin_can_still_switch_feed_version(db, client, capsys):
    _signed_in_as(ADMIN)
    with patch("backend.services.auth_service.ADMIN_EMAILS", "admin@example.com"):
        resp = client.patch("/auth/me/feed-version", json={"feed_version": "v2"})
    with capsys.disabled():
        print(f"\nadmin PATCH -> {resp.status_code} feed_version={resp.json().get('feed_version')} "
              f"| row: {_feed_version(db, 'admin-1')}")
    assert resp.status_code == 200
    assert resp.json()["feed_version"] == "v2"
    assert _feed_version(db, "admin-1") == "v2"


def test_signed_out_is_still_401(client):
    assert client.patch("/auth/me/feed-version", json={"feed_version": "v2"}).status_code == 401
