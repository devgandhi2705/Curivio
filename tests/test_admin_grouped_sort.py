"""
Phase Q — /admin/calls/grouped sort support. admin_service.list_grouped_calls
previously hardcoded ORDER BY started_at DESC (P-recon confirmed: no sort
parameter existed). GROUP_SORT_COLUMNS + sort_by/sort_order add real,
allowlisted ORDER BY support, mirroring the flat /admin/calls route's
existing SORT_COLUMNS precedent.

Three groups (each its own trace_id, so group-level == row-level here,
avoiding any tie-break ambiguity beyond what's explicitly tested) with
DELIBERATELY misaligned latency/tokens/action orderings, so a test that
accidentally reads the wrong column would fail loudly instead of coincidentally
passing.
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
def mem_db(monkeypatch):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    for stmt in ALL_TABLES:
        conn.execute(stmt)
    for migration in MIGRATIONS:
        try:
            if isinstance(migration, (list, tuple)):
                for stmt in migration:
                    conn.execute(stmt)
            else:
                conn.execute(migration)
        except sqlite3.OperationalError:
            pass
    conn.commit()

    @contextmanager
    def _get_conn():
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    monkeypatch.setattr(admin_service, "get_connection", _get_conn)
    yield conn
    conn.close()


# A: explain,   alice, 2026-08-10, latency=100, tokens=30, success=1
# B: feed_legacy, bob, 2026-08-11, latency=300, tokens=10, success=0
# C: chat_upload, carol, 2026-08-12, latency=200, tokens=20, success=1
#
# Label order (what 'action' must sort by): "Chat Upload"(C) < "Daily Feed
# (Legacy)"(B) < "Explain"(A) -> C, B, A.
# Raw surface order (what it must NOT sort by): chat_upload(C) < explain(A) <
# feed_legacy(B) -> C, A, B. A and B swap between the two — a real,
# falsifiable distinction, not a coincidence.
_ROWS = [
    dict(run_id="rA", trace_id="tA", surface="explain", user_id="u1",
         created_at="2026-08-10 10:00:00", latency_ms=100, total_tokens=30, success=1),
    dict(run_id="rB", trace_id="tB", surface="feed_legacy", user_id="u2",
         created_at="2026-08-11 10:00:00", latency_ms=300, total_tokens=10, success=0),
    dict(run_id="rC", trace_id="tC", surface="chat_upload", user_id="u3",
         created_at="2026-08-12 10:00:00", latency_ms=200, total_tokens=20, success=1),
]


@pytest.fixture
def seeded(mem_db):
    for uid, email in [("u1", "alice@example.com"), ("u2", "bob@example.com"), ("u3", "carol@example.com")]:
        mem_db.execute(
            "INSERT INTO users (user_id, email, hashed_pw, name) VALUES (?, ?, ?, ?)",
            (uid, email, "x", uid),
        )
    for r in _ROWS:
        mem_db.execute(
            """INSERT INTO llm_call_log
                   (run_id, trace_id, timestamp_start, timestamp_end, latency_ms, provider,
                    call_type, user_id, input, success, created_at, surface, is_test, total_tokens)
               VALUES (?, ?, ?, ?, ?, 'gemini', 'x', ?, '', ?, ?, ?, 0, ?)""",
            (r["run_id"], r["trace_id"], r["created_at"], r["created_at"], r["latency_ms"],
             r["user_id"], r["success"], r["created_at"], r["surface"], r["total_tokens"]),
        )
    mem_db.commit()
    return mem_db


def _order(sort_by, sort_order):
    total, groups = admin_service.list_grouped_calls(
        None, None, None, None, True, None, None, None, None,
        limit=10, offset=0, sort_by=sort_by, sort_order=sort_order,
    )
    assert total == 3
    return [g["trace_id"] for g in groups]


class TestTimestampSort:
    def test_asc_is_oldest_first(self, seeded):
        assert _order("timestamp", "asc") == ["tA", "tB", "tC"]

    def test_desc_is_newest_first(self, seeded):
        assert _order("timestamp", "desc") == ["tC", "tB", "tA"]

    def test_default_matches_old_hardcoded_behavior(self, seeded):
        # Phase Q must not change the OLD default (started_at DESC) — only add
        # the ability to override it.
        total, groups = admin_service.list_grouped_calls(
            None, None, None, None, True, None, None, None, None, limit=10, offset=0,
        )
        assert [g["trace_id"] for g in groups] == ["tC", "tB", "tA"]


class TestUserSort:
    def test_asc_is_alice_bob_carol(self, seeded):
        assert _order("user", "asc") == ["tA", "tB", "tC"]

    def test_desc_is_carol_bob_alice(self, seeded):
        assert _order("user", "desc") == ["tC", "tB", "tA"]


class TestActionSortsByLabelNotRawId:
    def test_asc_follows_label_order_not_surface_order(self, seeded):
        # Label order: Chat Upload < Daily Feed (Legacy) < Explain -> C, B, A.
        # Raw surface order would be C, A, B — this proves it's actually C, B, A.
        assert _order("action", "asc") == ["tC", "tB", "tA"]

    def test_desc_is_reverse_label_order(self, seeded):
        assert _order("action", "desc") == ["tA", "tB", "tC"]


class TestLatencySortUsesGroupLevelSum:
    def test_asc_100_200_300(self, seeded):
        assert _order("latency", "asc") == ["tA", "tC", "tB"]

    def test_desc_300_200_100(self, seeded):
        assert _order("latency", "desc") == ["tB", "tC", "tA"]


class TestTokensSortIsIndependentOfLatency:
    def test_asc_10_20_30_is_a_different_permutation_than_latency(self, seeded):
        # tokens: B=10, C=20, A=30 — deliberately NOT the same order as
        # latency's A,C,B, so a test that silently read latency instead of
        # tokens would fail here.
        assert _order("tokens", "asc") == ["tB", "tC", "tA"]

    def test_desc(self, seeded):
        assert _order("tokens", "desc") == ["tA", "tC", "tB"]


class TestStatusSort:
    def test_asc_failed_group_first(self, seeded):
        order = _order("status", "asc")
        assert order[0] == "tB"  # the one all_succeeded=0 group

    def test_desc_failed_group_last(self, seeded):
        order = _order("status", "desc")
        assert order[-1] == "tB"


class TestInvalidSortKeyRejected:
    def test_bad_sort_by_raises_keyerror_at_service_level(self, seeded):
        with pytest.raises(KeyError):
            admin_service.list_grouped_calls(
                None, None, None, None, True, None, None, None, None,
                limit=10, offset=0, sort_by="not_a_real_column", sort_order="asc",
            )


# ── Route-level: the allowlist validation actually rejects a bad param over HTTP ──

@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from backend.main import app, get_current_user
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "admin-user", "email": "admin@example.com",
    }
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


class TestGroupedRouteSortValidation:
    def test_bad_sort_by_is_400(self, seeded, client):
        with patch("backend.services.auth_service.ADMIN_EMAILS", "admin@example.com"):
            resp = client.get("/admin/calls/grouped?sort_by=not_a_column")
        assert resp.status_code == 400
        assert "sort_by" in resp.json()["detail"]

    def test_bad_sort_order_is_400(self, seeded, client):
        with patch("backend.services.auth_service.ADMIN_EMAILS", "admin@example.com"):
            resp = client.get("/admin/calls/grouped?sort_order=sideways")
        assert resp.status_code == 400
        assert "sort_order" in resp.json()["detail"]

    def test_real_tokens_sort_over_http(self, seeded, client):
        with patch("backend.services.auth_service.ADMIN_EMAILS", "admin@example.com"):
            resp = client.get("/admin/calls/grouped?sort_by=tokens&sort_order=asc&include_test_data=true")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert [g["trace_id"] for g in body["groups"]] == ["tB", "tC", "tA"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
