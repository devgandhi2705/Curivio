"""
Pre-Phase-13: feed_version belongs to the PROJECT, fixed at creation.

A project's feed is the system that owns it: learning_projects rows are 'legacy',
v2_projects rows are 'v2', each with an explicit feed_version column. Which system a
NEW project goes to is decided once, from NEW_PROJECTS_FEED_VERSION. The admin-only
PATCH /auth/me/feed-version only opts that admin's OWN new projects into v2 early
(dev/test); it never changes an existing project. The /v2 project routes gate on
the project (does this user own this v2 project?), not on the user's flag.

Real JWTs, real get_current_user, real routes, throwaway DB. The graph runs on the
offline rig (stub nodes), so no LLM calls.
"""
import json
import sqlite3
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.utils import db as legacy_db
from backend.services.feed_v2 import db as v2db
from backend.services.feed_v2 import graph as G
from backend.services import auth_service

ADMIN_EMAIL = "admin@example.com"


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "pfv.db"
    monkeypatch.setattr(legacy_db, "DB_PATH", path)
    monkeypatch.setattr(v2db, "DB_PATH", str(path))
    legacy_db.init_db()
    with legacy_db.get_connection() as c:
        for uid, email in (("admin-1", ADMIN_EMAIL), ("user-1", "user@example.com"), ("user-2", "u2@example.com")):
            c.execute("INSERT INTO users(user_id,email,name,hashed_pw) VALUES(?,?,?,'x')", (uid, email, uid))
    return path


@pytest.fixture(autouse=True)
def _rig():
    G._reset_rig()
    G.USE_REAL_SOURCE_RANKER = False
    yield
    G._reset_rig()


@pytest.fixture
def client(db):
    from backend.main import app
    with patch("backend.services.auth_service.ADMIN_EMAILS", ADMIN_EMAIL):
        yield TestClient(app, raise_server_exceptions=False)


def _auth(user_id):
    return {"Authorization": f"Bearer {auth_service.create_access_token(user_id)}"}


def _q(db, sql, *args):
    c = sqlite3.connect(db)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def _legacy_project(client, user_id, name="Legacy thing"):
    r = client.post("/projects", json={"name": name, "description": "d", "keywords": [],
                                        "difficulty": "intermediate", "color": "blue"},
                    headers=_auth(user_id))
    assert r.status_code == 200, r.text
    return r.json()


def _ready(db, project_id):
    c = sqlite3.connect(db)
    try:
        c.execute("UPDATE v2_projects SET coverage_mode='open', profile_status='ready' WHERE project_id=?",
                  (project_id,))
        c.commit()
    finally:
        c.close()


def _stream(client, user_id, project_id, **body):
    r = client.post(f"/v2/projects/{project_id}/generate/stream", json={"day_number": 1, **body},
                    headers=_auth(user_id))
    events = [json.loads(x) for x in r.text.splitlines() if x.strip()] if r.status_code == 200 else []
    return r.status_code, events


# ── backfill ──────────────────────────────────────────────────────────────────
def test_existing_projects_are_backfilled_to_legacy(tmp_path, monkeypatch):
    """A DB whose learning_projects predates the column: after startup migrations every
    existing row reads 'legacy' and the column is NOT NULL (no null, nothing inferred)."""
    from backend.database.schema import ALL_TABLES
    path = tmp_path / "old.db"
    monkeypatch.setattr(legacy_db, "DB_PATH", path)
    old = sqlite3.connect(path)
    create = next(s for s in ALL_TABLES if "CREATE TABLE IF NOT EXISTS learning_projects" in s)
    assert "feed_version" not in create            # the pre-existing shape
    old.execute(create)
    old.executemany("INSERT INTO learning_projects(project_id,name) VALUES(?,?)", [("p1", "a"), ("p2", "b")])
    old.commit(); old.close()

    legacy_db.init_db()
    rows = _q(path, "SELECT project_id, feed_version FROM learning_projects ORDER BY project_id")
    notnull = [r[3] for r in _q(path, "PRAGMA table_info(learning_projects)") if r[1] == "feed_version"]
    assert rows == [("p1", "legacy"), ("p2", "legacy")]
    assert notnull == [1]


# ── config 'legacy': a normal user gets legacy, and the PATCH changes nothing ───
def test_normal_user_gets_a_legacy_project_and_patch_has_no_effect(db, client, capsys):
    with patch("backend.services.auth_service.NEW_PROJECTS_FEED_VERSION", "legacy"):
        proj = _legacy_project(client, "user-1")
        patch_resp = client.patch("/auth/me/feed-version", json={"feed_version": "v2"}, headers=_auth("user-1"))
        v2_resp = client.post("/v2/projects", json={"name": "x"}, headers=_auth("user-1"))
    row = _q(db, "SELECT feed_version FROM learning_projects WHERE project_id=?", proj["project_id"])
    with capsys.disabled():
        print(f"\nnormal user: project.feed_version={proj.get('feed_version')} | PATCH -> {patch_resp.status_code}"
              f" | POST /v2/projects -> {v2_resp.status_code} | row after: {row}")
    assert proj["feed_version"] == "legacy"
    assert patch_resp.status_code == 403
    assert v2_resp.status_code == 403
    assert row == [("legacy",)]


def test_admin_patch_only_affects_new_projects(db, client, capsys):
    with patch("backend.services.auth_service.NEW_PROJECTS_FEED_VERSION", "legacy"):
        before = _legacy_project(client, "admin-1", "made before opting in")
        assert client.patch("/auth/me/feed-version", json={"feed_version": "v2"},
                            headers=_auth("admin-1")).status_code == 200
        v2 = client.post("/v2/projects", json={"name": "made after opting in"}, headers=_auth("admin-1"))
    old_row = _q(db, "SELECT feed_version FROM learning_projects WHERE project_id=?", before["project_id"])
    with capsys.disabled():
        print(f"\nadmin opt-in: old project row={old_row} | new POST /v2/projects -> {v2.status_code} "
              f"feed_version={v2.json().get('feed_version')}")
    assert old_row == [("legacy",)]                 # existing project untouched
    assert v2.status_code == 201 and v2.json()["feed_version"] == "v2"


# ── config 'v2': new projects are v2 and reach the v2 graph ─────────────────────
def test_config_v2_new_project_reaches_the_v2_graph_and_legacy_is_untouched(db, client, capsys):
    with patch("backend.services.auth_service.NEW_PROJECTS_FEED_VERSION", "legacy"):
        legacy_a = _legacy_project(client, "user-1")
        legacy_b = _legacy_project(client, "admin-1")
    with patch("backend.services.auth_service.NEW_PROJECTS_FEED_VERSION", "v2"):
        v2 = client.post("/v2/projects", json={"name": "Phase 13 test bed"}, headers=_auth("admin-1"))
        pid = v2.json()["project_id"]
        _ready(db, pid)
        status, events = _stream(client, "admin-1", pid)
    legacy_rows = _q(db, "SELECT project_id, feed_version FROM learning_projects ORDER BY project_id")
    agents = [e.get("agent") or e["t"] for e in events]
    with capsys.disabled():
        print(f"\nconfig v2: POST /v2/projects -> {v2.status_code} feed_version={v2.json()['feed_version']}"
              f"\n  generate/stream -> {status} events={agents}\n  legacy rows={legacy_rows}")
    assert v2.status_code == 201 and v2.json()["feed_version"] == "v2"
    assert status == 200 and agents[-1] == "done" and "assembler" in agents
    assert sorted(legacy_rows) == sorted([(legacy_a["project_id"], "legacy"), (legacy_b["project_id"], "legacy")])


def test_v2_project_keeps_working_after_the_opt_in_is_revoked(db, client):
    """Project-level gate: switching the admin's flag back doesn't strand their v2 project."""
    with patch("backend.services.auth_service.NEW_PROJECTS_FEED_VERSION", "legacy"):
        client.patch("/auth/me/feed-version", json={"feed_version": "v2"}, headers=_auth("admin-1"))
        pid = client.post("/v2/projects", json={"name": "x"}, headers=_auth("admin-1")).json()["project_id"]
        client.patch("/auth/me/feed-version", json={"feed_version": "legacy"}, headers=_auth("admin-1"))
        _ready(db, pid)
        status, events = _stream(client, "admin-1", pid)
    assert status == 200 and events[-1]["t"] == "done"


def test_cannot_touch_or_reattach_to_someone_elses_v2_project(db, client):
    with patch("backend.services.auth_service.NEW_PROJECTS_FEED_VERSION", "v2"):
        pid = client.post("/v2/projects", json={"name": "admin's"}, headers=_auth("admin-1")).json()["project_id"]
        _ready(db, pid)
        _, events = _stream(client, "admin-1", pid)
        admins_trace = events[0]["trace_id"]
        own = client.post("/v2/projects", json={"name": "user-2's"}, headers=_auth("user-2")).json()["project_id"]
        other_project, _ = _stream(client, "user-2", pid)
        other_trace, _ = _stream(client, "user-2", own, trace_id=admins_trace)
        other_trace_on_theirs, _ = _stream(client, "user-2", pid, trace_id=admins_trace)
    assert other_project == 404                     # not their project
    assert other_trace == 404                       # their project, somebody else's run
    assert other_trace_on_theirs == 404


def test_new_project_feed_version_rejects_a_bad_config_value():
    with patch("backend.services.auth_service.NEW_PROJECTS_FEED_VERSION", "V2 "):
        with pytest.raises(ValueError, match="NEW_PROJECTS_FEED_VERSION"):
            auth_service.new_project_feed_version({"email": "x@example.com", "feed_version": "legacy"})
