"""
Three chat/feed-link security bugs, fixed for the feed:

  1. /chat/stream trusted feed_context.project_id: chat_service reads that project's
     learning memory and shared learning context into the prompt, so a crafted request
     could pull another user's project history into its own answer. Now the project
     must be a project the caller owns — strictly: a NULL-owner (pre-auth) row is
     rejected too.
  2. POST /feed-chat-links checked the project but not the session, so a caller could
     attach someone else's chat session to their own project. Now the session must
     exist and belong to the caller.
  3. feed_chat_links had no UNIQUE constraint though create_link claims to be
     idempotent per (session_id, article_key). The constraint now lives in the table
     definition the always-rerun rebuild migration uses, whose INSERT OR IGNORE copy
     also drops pre-existing duplicates.

No LLM calls: chat_stream_generator is stubbed where a request is expected to pass.
"""
import json
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.utils import db as legacy_db
from backend.services import auth_service
from backend.services.feed_chat_link_service import create_link


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "sec.db"
    monkeypatch.setattr(legacy_db, "DB_PATH", path)
    legacy_db.init_db()
    with legacy_db.get_connection() as c:
        for uid in ("user-1", "user-2"):
            c.execute("INSERT INTO users(user_id,email,name,hashed_pw) VALUES(?,?,?,'x')",
                      (uid, f"{uid}@example.com", uid))
    return path


@pytest.fixture
def client(db):
    from backend.main import app
    yield TestClient(app, raise_server_exceptions=False)


def _auth(user_id):
    return {"Authorization": f"Bearer {auth_service.create_access_token(user_id)}"}


def _legacy_project(user_id):
    pid = uuid.uuid4().hex
    with legacy_db.get_connection() as c:
        c.execute("INSERT INTO learning_projects (project_id, name, user_id) VALUES (?, 'P', ?)",
                  (pid, user_id))
    return pid


def _session(session_id, user_id):
    with legacy_db.get_connection() as c:
        c.execute("INSERT INTO chat_sessions (session_id, user_id) VALUES (?, ?)", (session_id, user_id))


def _stream(client, user, feed_context):
    return client.post("/chat/stream", headers=_auth(user), json={
        "session_id": f"s-{uuid.uuid4().hex}", "message": "hi", "feed_context": feed_context})


def _fake_stream(**kwargs):
    yield json.dumps({"t": "done"}) + "\n"


# ── 1. feed_context.project_id ownership ────────────────────────────────────────
def test_feed_context_with_own_legacy_project_passes(db, client):
    pid = _legacy_project("user-1")
    with patch("backend.main.chat_stream_generator", side_effect=_fake_stream) as gen:
        resp = _stream(client, "user-1", {"action": "ask_about", "insight_title": "t", "project_id": pid})
    assert resp.status_code == 200
    assert gen.call_args.kwargs["feed_context"]["project_id"] == pid


@pytest.mark.parametrize("owner", ["user-2", None])
def test_feed_context_with_foreign_or_ownerless_project_404s(db, client, owner):
    pid = _legacy_project(owner)
    with patch("backend.main.chat_stream_generator", side_effect=_fake_stream) as gen:
        resp = _stream(client, "user-1", {"action": "ask_about", "insight_title": "t", "project_id": pid})
    assert resp.status_code == 404
    gen.assert_not_called()          # nothing reached the prompt-building path


def test_feed_context_with_unknown_project_id_404s(db, client):
    with patch("backend.main.chat_stream_generator", side_effect=_fake_stream) as gen:
        resp = _stream(client, "user-1", {"action": "ask_about", "insight_title": "t", "project_id": uuid.uuid4().hex})
    assert resp.status_code == 404
    gen.assert_not_called()


# ── 2. POST /feed-chat-links session ownership ───────────────────────────
def _link(client, user, pid, sid):
    return client.post("/feed-chat-links", headers=_auth(user), json={
        "session_id": sid, "project_id": pid, "article_key": "a-card", "article_title": "A card"})


def test_feed_chat_link_own_session_passes(db, client):
    pid = _legacy_project("user-1")
    _session("s-mine", "user-1")
    assert _link(client, "user-1", pid, "s-mine").status_code == 200


@pytest.mark.parametrize("owner", ["user-2", None, "missing"])
def test_feed_chat_link_rejects_foreign_ownerless_or_missing_session(db, client, owner):
    pid = _legacy_project("user-1")
    if owner != "missing":
        _session("s-x", owner)
    assert _link(client, "user-1", pid, "s-x").status_code == 404
    with legacy_db.get_connection() as c:
        assert c.execute("SELECT COUNT(*) FROM feed_chat_links").fetchone()[0] == 0


# ── 3. UNIQUE(session_id, article_key) ──────────────────────────────────────────
def test_create_link_is_really_idempotent(db):
    first = create_link("s1", "p1", "k1", "T", "ask_about")
    again = create_link("s1", "p1", "k1", "T", "ask_about")
    assert first["id"] == again["id"]
    with legacy_db.get_connection() as c:
        assert c.execute("SELECT COUNT(*) FROM feed_chat_links").fetchone()[0] == 1


def test_restart_dedupes_existing_duplicates_and_keeps_the_constraint(db):
    """An existing DB has the old constraint-less table with real duplicates in it."""
    with legacy_db.get_connection() as c:
        c.execute("DROP TABLE feed_chat_links")
        c.execute("""CREATE TABLE feed_chat_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, project_id TEXT NOT NULL,
            insight_id INTEGER, article_key TEXT NOT NULL, article_title TEXT NOT NULL DEFAULT '',
            interaction_type TEXT NOT NULL DEFAULT 'ask_about', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        for _ in range(3):
            c.execute("INSERT INTO feed_chat_links (session_id, project_id, article_key) VALUES ('s1','p1','k1')")
        c.execute("INSERT INTO feed_chat_links (session_id, project_id, article_key) VALUES ('s1','p1','k2')")

    legacy_db.init_db()          # every startup re-runs the feed_chat_links rebuild

    with legacy_db.get_connection() as c:
        rows = c.execute("SELECT id, article_key FROM feed_chat_links ORDER BY id").fetchall()
        assert [(r["id"], r["article_key"]) for r in rows] == [(1, "k1"), (4, "k2")]   # earliest kept
        c.execute("INSERT OR IGNORE INTO feed_chat_links (session_id, project_id, article_key) VALUES ('s1','p1','k1')")
        assert c.execute("SELECT COUNT(*) FROM feed_chat_links").fetchone()[0] == 2
