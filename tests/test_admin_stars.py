"""
Admin log stars — star any operation group or single call, and filter the log to
starred items (docs/superpowers/specs/2026-10-03-admin-log-stars-design.md).

Seed:
  tA — two calls (rA1 ok, rA2 ok)
  tB — one call (rB ok)
  C  — one call with NO trace_id, so its group key is 'row-<id>'
  tD — one call that failed
"""
from __future__ import annotations

import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.database.schema import ALL_TABLES, MIGRATIONS
from backend.services import admin_service


@pytest.fixture
def db(monkeypatch):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    for stmt in ALL_TABLES:
        conn.execute(stmt)
    for migration in MIGRATIONS:
        try:
            for stmt in (migration if isinstance(migration, (list, tuple)) else [migration]):
                conn.execute(stmt)
        except sqlite3.OperationalError:
            pass
    conn.execute("INSERT INTO users (user_id, email, hashed_pw, name) VALUES ('u1', 'a@example.com', 'x', 'u1')")
    for run_id, trace_id, success, ts in [
        ("rA1", "tA", 1, "2026-09-01 10:00:00"),
        ("rA2", "tA", 1, "2026-09-01 10:00:05"),
        ("rB",  "tB", 1, "2026-09-02 10:00:00"),
        ("rC",  None, 1, "2026-09-03 10:00:00"),
        ("rD",  "tD", 0, "2026-09-04 10:00:00"),
    ]:
        conn.execute(
            """INSERT INTO llm_call_log
                   (run_id, trace_id, timestamp_start, timestamp_end, latency_ms, provider,
                    call_type, user_id, input, success, created_at, surface, is_test, total_tokens)
               VALUES (?, ?, ?, ?, 100, 'gemini', 'x', 'u1', '', ?, ?, 'explain', 0, 10)""",
            (run_id, trace_id, ts, ts, success, ts),
        )
    conn.commit()

    @contextmanager
    def _conn():
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    monkeypatch.setattr(admin_service, "get_connection", _conn)
    yield conn
    conn.close()


def _id(db, run_id):
    return str(db.execute("SELECT id FROM llm_call_log WHERE run_id = ?", (run_id,)).fetchone()["id"])


def _groups(starred=False, **kw):
    args = dict(date_from=None, date_to=None, project_id=None, user_id=None, include_test_data=True,
                status=None, action_type=None, day_ref=None, target_language=None, limit=20, offset=0)
    args.update(kw)
    return admin_service.list_grouped_calls(**args, starred=starred)


def _key(g):
    return g["trace_id"] or f"row-{g['rows'][0]['id']}"


class TestStarring:
    def test_star_and_unstar_are_idempotent(self, db):
        admin_service.star_log("group", "tA", "admin")
        admin_service.star_log("group", "tA", "admin")
        assert db.execute("SELECT COUNT(*) FROM admin_log_stars").fetchone()[0] == 1
        admin_service.unstar_log("group", "tA")
        admin_service.unstar_log("group", "tA")
        assert db.execute("SELECT COUNT(*) FROM admin_log_stars").fetchone()[0] == 0

    def test_groups_and_rows_carry_their_own_flags(self, db):
        admin_service.star_log("group", "tA", "admin")
        admin_service.star_log("row", _id(db, "rB"), "admin")
        _, groups = _groups()
        by_key = {_key(g): g for g in groups}
        assert by_key["tA"]["starred"] is True
        assert [r["starred"] for r in by_key["tA"]["rows"]] == [False, False]
        assert by_key["tB"]["starred"] is False
        assert by_key["tB"]["rows"][0]["starred"] is True
        assert by_key["tD"]["starred"] is False


class TestStarredFilter:
    def test_off_by_default_changes_nothing(self, db):
        admin_service.star_log("group", "tA", "admin")
        assert _groups()[0] == 4

    def test_a_group_star_surfaces_the_whole_group(self, db):
        admin_service.star_log("group", "tA", "admin")
        total, groups = _groups(starred=True)
        assert total == 1 and _key(groups[0]) == "tA" and len(groups[0]["rows"]) == 2

    def test_a_row_star_surfaces_its_whole_group(self, db):
        admin_service.star_log("row", _id(db, "rA1"), "admin")
        total, groups = _groups(starred=True)
        assert total == 1 and _key(groups[0]) == "tA" and len(groups[0]["rows"]) == 2

    def test_a_single_call_without_trace_is_starred_by_its_row_key(self, db):
        key = f"row-{_id(db, 'rC')}"
        admin_service.star_log("group", key, "admin")
        total, groups = _groups(starred=True)
        assert total == 1 and _key(groups[0]) == key and groups[0]["starred"] is True

    def test_combines_with_other_filters(self, db):
        admin_service.star_log("group", "tA", "admin")
        admin_service.star_log("group", "tD", "admin")
        total, groups = _groups(starred=True, status="failed")
        assert total == 1 and _key(groups[0]) == "tD"

    def test_pages_count_starred_groups_only(self, db):
        for t in ("tA", "tB", "tD"):
            admin_service.star_log("group", t, "admin")
        total, groups = _groups(starred=True, limit=2)
        assert total == 3 and len(groups) == 2

    def test_summary_volume_and_export_follow_the_filter(self, db):
        admin_service.star_log("group", "tA", "admin")
        summary = admin_service.get_call_summary(None, None, True, starred=True)
        assert summary["total_calls"] == 2
        ops = admin_service.get_operation_summary(None, None, None, None, True, None, None, None, None, starred=True)
        assert ops["total_operations"] == 1
        _, by_day = admin_service.get_daily_volume(None, None, None, None, None, True, starred=True)
        assert sum(d["count"] for d in by_day) == 2
        total, _, groups = admin_service.export_grouped_calls(None, None, None, None, True, None, None, None, None, starred=True)
        assert total == 1 and groups[0]["starred"] is True

    def test_flat_list_follows_the_filter_and_marks_rows(self, db):
        admin_service.star_log("row", _id(db, "rB"), "admin")
        total, rows = admin_service.list_call_logs(None, None, None, None, None, True, 20, 0, starred=True)
        assert total == 1 and rows[0]["starred"] is True


@pytest.fixture
def admin_client(db):
    from fastapi.testclient import TestClient
    from backend.main import app, get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "admin-user", "email": "admin@example.com"}
    try:
        with patch("backend.services.auth_service.ADMIN_EMAILS", "admin@example.com"):
            yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


class TestStarRoutes:
    def test_put_then_delete(self, admin_client, db):
        assert admin_client.put("/admin/stars", json={"kind": "group", "key": "tA"}).status_code == 204
        assert db.execute("SELECT starred_by FROM admin_log_stars").fetchone()[0] == "admin-user"
        assert admin_client.put("/admin/stars", json={"kind": "group", "key": "tA"}).status_code == 204
        assert admin_client.delete("/admin/stars", params={"kind": "group", "key": "tA"}).status_code == 204
        assert db.execute("SELECT COUNT(*) FROM admin_log_stars").fetchone()[0] == 0

    @pytest.mark.parametrize("body", [
        {"kind": "trace", "key": "tA"},
        {"kind": "group", "key": ""},
        {"kind": "group", "key": "x" * 201},
        {"kind": "row", "key": "abc"},
    ])
    def test_bad_input_is_refused(self, admin_client, body):
        assert admin_client.put("/admin/stars", json=body).status_code in (400, 422)
        assert admin_client.delete("/admin/stars", params=body).status_code in (400, 422)

    def test_grouped_route_takes_the_filter(self, admin_client, db):
        admin_client.put("/admin/stars", json={"kind": "row", "key": _id(db, "rD")})
        data = admin_client.get("/admin/calls/grouped", params={"starred": "true", "include_test_data": "true"}).json()
        assert data["total"] == 1 and data["groups"][0]["rows"][0]["starred"] is True

    def test_non_admin_is_refused(self, db):
        from fastapi.testclient import TestClient
        from backend.main import app, get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u", "email": "someone@example.com"}
        try:
            with patch("backend.services.auth_service.ADMIN_EMAILS", "admin@example.com"):
                resp = TestClient(app, raise_server_exceptions=False).put("/admin/stars", json={"kind": "group", "key": "tA"})
        finally:
            app.dependency_overrides.pop(get_current_user, None)
        assert resp.status_code in (403, 404)
        assert db.execute("SELECT COUNT(*) FROM admin_log_stars").fetchone()[0] == 0
