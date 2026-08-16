"""
Phase R — free-text search across llm_call_log.input/output.

DESIGN DECISION (see admin_service.py's Phase R comments for the full recon):
real EXPLAIN QUERY PLAN + timing on the live DB (6,453 rows, avg input/output
~1.9KB/2.6KB, 18.5MB combined text) showed naive LIKE at 42-149ms across every
query shape tested (flat scan, sibling-OR, and the full grouped CTE with the
has_search_match aggregate) — nowhere near the ~1s naive-vs-FTS5 threshold, so
no FTS5 virtual table was built. search is additive (ANDed) with every other
active filter, and matches at the GROUP level: a hit on ANY row of a trace_id
group surfaces the WHOLE group, same "always show the whole group" precedent
already established by the web_search filter (has_web_search).
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.database.schema import ALL_TABLES, MIGRATIONS
from backend.services import admin_service

REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_DB = REPO_ROOT / "data" / "curivio.db"


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


# tGroup: 2 rows sharing one trace_id. Only rG1's input contains the search
# term — rG2 is an unrelated sibling. A group-level search must surface BOTH
# rows (the whole group), not just rG1 — the web_search filter precedent.
# row-<id> (no trace_id): its own input contains the term (singleton group).
# tOther: matches the term but success=0 — used for the AND-with-status test.
# tNoMatch: never matches — proves search actually filters, not a no-op.
_ROWS = [
    dict(run_id="rG1", trace_id="tGroup", user_id="u1",
         created_at="2026-08-10 10:00:00", input="find the lazarus-marker here",
         output="", success=1, total_tokens=10),
    dict(run_id="rG2", trace_id="tGroup", user_id="u1",
         created_at="2026-08-10 10:01:00", input="unrelated sibling content",
         output="", success=1, total_tokens=10),
    dict(run_id="rSingle", trace_id=None, user_id="u2",
         created_at="2026-08-11 10:00:00", input="a lazarus-marker singleton",
         output="", success=1, total_tokens=5),
    dict(run_id="rFailed", trace_id="tOther", user_id="u3",
         created_at="2026-08-12 10:00:00", input="lazarus-marker but failed",
         output="", success=0, total_tokens=5),
    dict(run_id="rNoMatch", trace_id="tNoMatch", user_id="u4",
         created_at="2026-08-13 10:00:00", input="totally different text",
         output="", success=1, total_tokens=5),
]


@pytest.fixture
def seeded(mem_db):
    for uid, email in [("u1", "a@x.com"), ("u2", "b@x.com"), ("u3", "c@x.com"), ("u4", "d@x.com")]:
        mem_db.execute(
            "INSERT INTO users (user_id, email, hashed_pw, name) VALUES (?, ?, ?, ?)",
            (uid, email, "x", uid),
        )
    for r in _ROWS:
        mem_db.execute(
            """INSERT INTO llm_call_log
                   (run_id, trace_id, timestamp_start, timestamp_end, latency_ms, provider,
                    call_type, user_id, input, output, success, created_at, surface, is_test, total_tokens)
               VALUES (?, ?, ?, ?, 100, 'gemini', 'x', ?, ?, ?, ?, ?, 'chat', 0, ?)""",
            (r["run_id"], r["trace_id"], r["created_at"], r["created_at"],
             r["user_id"], r["input"], r["output"], r["success"], r["created_at"], r["total_tokens"]),
        )
    mem_db.commit()
    return mem_db


class TestGroupedSearchSurfacesWholeGroup:
    def test_matches_group_singleton_and_failed_row_only(self, seeded):
        total, groups = admin_service.list_grouped_calls(
            None, None, None, None, True, None, None, None, None,
            limit=10, offset=0, search="lazarus-marker",
        )
        assert total == 3
        assert {g["trace_id"] for g in groups if g["trace_id"]} == {"tGroup", "tOther"}

    def test_whole_group_surfaces_even_though_only_one_row_matched(self, seeded):
        total, groups = admin_service.list_grouped_calls(
            None, None, None, None, True, None, None, None, None,
            limit=10, offset=0, search="lazarus-marker",
        )
        group = next(g for g in groups if g["trace_id"] == "tGroup")
        assert group["row_count"] == 2
        assert {r["run_id"] for r in group["rows"]} == {"rG1", "rG2"}

    def test_no_match_term_excludes_everything(self, seeded):
        total, groups = admin_service.list_grouped_calls(
            None, None, None, None, True, None, None, None, None,
            limit=10, offset=0, search="does-not-exist-anywhere",
        )
        assert total == 0
        assert groups == []

    def test_empty_search_is_a_no_op(self, seeded):
        total, groups = admin_service.list_grouped_calls(
            None, None, None, None, True, None, None, None, None,
            limit=10, offset=0, search=None,
        )
        assert total == 4  # tGroup, singleton, tOther, tNoMatch — all present


class TestSearchAndsWithOtherFilters:
    def test_search_plus_status_success_excludes_failed_match(self, seeded):
        # rFailed matches the term but success=0 -> tOther must drop out once
        # status=success is ALSO active; AND semantics, not OR.
        total, groups = admin_service.list_grouped_calls(
            None, None, None, None, True, "success", None, None, None,
            limit=10, offset=0, search="lazarus-marker",
        )
        trace_ids = {g["trace_id"] for g in groups if g["trace_id"]}
        assert "tOther" not in trace_ids
        assert "tGroup" in trace_ids

    def test_search_plus_date_range_excludes_out_of_range_match(self, seeded):
        total, groups = admin_service.list_grouped_calls(
            "2026-08-10", "2026-08-10", None, None, True, None, None, None, None,
            limit=10, offset=0, search="lazarus-marker",
        )
        trace_ids = {g["trace_id"] for g in groups if g["trace_id"]}
        assert trace_ids == {"tGroup"}


class TestFlatListSearch:
    def test_flat_route_surfaces_sibling_row_of_a_matching_group(self, seeded):
        # rG2 doesn't itself contain the term, but shares tGroup's trace_id
        # with rG1 which does -> the flat /admin/calls view (list_call_logs)
        # must ALSO return rG2, same trace-sibling-OR shape as web_search's
        # existing filter.
        total, rows = admin_service.list_call_logs(
            None, None, None, None, None, True, 10, 0,
            search="lazarus-marker",
        )
        run_ids = {r["run_id"] for r in rows}
        assert run_ids == {"rG1", "rG2", "rSingle", "rFailed"}
        assert total == 4


class TestSummaryAndVolumeHonorSearch:
    def test_get_call_summary_total_reflects_search(self, seeded):
        summary = admin_service.get_call_summary(None, None, True, search="lazarus-marker")
        assert summary["total_calls"] == 4  # rG1, rG2 (sibling), rSingle, rFailed

    def test_get_operation_summary_total_reflects_search(self, seeded):
        summary = admin_service.get_operation_summary(
            None, None, None, None, True, None, None, None, None,
            search="lazarus-marker",
        )
        assert summary["total_operations"] == 3  # tGroup, singleton, tOther

    def test_export_grouped_calls_honors_search(self, seeded):
        total, truncated, groups = admin_service.export_grouped_calls(
            None, None, None, None, True, None, None, None, None,
            search="lazarus-marker",
        )
        assert total == 3
        assert not truncated


# ── Route-level: HTTP query param actually reaches the service layer ─────────

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


class TestSearchRouteHTTP:
    def test_grouped_route_search_param(self, seeded, client):
        with patch("backend.services.auth_service.ADMIN_EMAILS", "admin@example.com"):
            resp = client.get("/admin/calls/grouped?search=lazarus-marker&include_test_data=true")
        assert resp.status_code == 200, resp.text
        assert resp.json()["total"] == 3

    def test_whitespace_only_search_normalizes_to_no_filter(self, seeded, client):
        with patch("backend.services.auth_service.ADMIN_EMAILS", "admin@example.com"):
            resp = client.get("/admin/calls/grouped?search=%20%20&include_test_data=true")
        assert resp.status_code == 200, resp.text
        assert resp.json()["total"] == 4

    def test_flat_calls_route_search_param(self, seeded, client):
        with patch("backend.services.auth_service.ADMIN_EMAILS", "admin@example.com"):
            resp = client.get("/admin/calls?search=lazarus-marker&include_test_data=true")
        assert resp.status_code == 200, resp.text
        assert resp.json()["total"] == 4

    def test_search_combines_with_status_over_http(self, seeded, client):
        with patch("backend.services.auth_service.ADMIN_EMAILS", "admin@example.com"):
            resp = client.get(
                "/admin/calls/grouped?search=lazarus-marker&status=success&include_test_data=true"
            )
        assert resp.status_code == 200, resp.text
        trace_ids = {g["trace_id"] for g in resp.json()["groups"] if g["trace_id"]}
        assert "tOther" not in trace_ids


# ── Real-DB checks: known content, and real timing (Phase R's own bar) ──────

@pytest.fixture(scope="module")
def live_copy(tmp_path_factory, request):
    if not LIVE_DB.exists():
        pytest.skip("live curivio.db not present")
    copy_dir = tmp_path_factory.mktemp("admin_search_live")
    copy = copy_dir / "curivio_copy.db"
    shutil.copy(LIVE_DB, copy)
    conn = sqlite3.connect(str(copy))
    conn.row_factory = sqlite3.Row

    @contextmanager
    def _get_conn():
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # module-scoped fixture -> monkeypatch directly (function-scoped
    # `monkeypatch` can't be used here) and restore on teardown.
    original = admin_service.get_connection
    admin_service.get_connection = _get_conn
    yield conn
    admin_service.get_connection = original
    conn.close()


class TestRealDbSearch:
    """Term 'serendipity' hits the exact rows Phase K's _TARGET_LANGUAGE_EXPR
    comment in admin_service.py already documents (id 5848/5849 — real Hindi/
    French DeepL translate calls whose `input` ends with
    "target_language='hi'"/"'fr'") — an already-referenced known real group,
    not a synthetic fixture. 'audit challenges' hits a real 23-row trace_id
    group (trace_id 9e09cbe1d2e34cffa16e601859113361) via only ONE of its 23
    rows (id 5861), proving whole-group surfacing on real production-shaped
    data, not just the small synthetic seed above.
    """

    def test_known_translate_rows_match_by_search_term(self, live_copy):
        total, groups = admin_service.list_grouped_calls(
            None, None, None, None, True, None, None, None, None,
            limit=50, offset=0, search="serendipity",
        )
        row_ids = {r["id"] for g in groups for r in g["rows"]}
        assert 5848 in row_ids
        assert 5849 in row_ids

    def test_known_23row_group_surfaces_whole_group_via_single_matching_row(self, live_copy):
        total, groups = admin_service.list_grouped_calls(
            None, None, None, None, True, None, None, None, None,
            limit=50, offset=0, search="audit challenges",
        )
        group = next(
            (g for g in groups if g["trace_id"] == "9e09cbe1d2e34cffa16e601859113361"), None
        )
        assert group is not None, "known 23-row group did not surface"
        assert group["row_count"] == 23
        row_ids = {r["id"] for r in group["rows"]}
        assert len(row_ids) == 23
        assert 5861 in row_ids  # the one row whose input actually contains the term
        assert 5879 in row_ids  # a sibling that does NOT — proves the whole group came through

    def test_grouped_search_timing_stays_under_threshold(self, live_copy):
        # Real measured range during Phase R recon: 115-149ms warm for this
        # exact query shape on the live DB (6,453 rows). Asserted loosely
        # (<1s, the design threshold) to stay robust under CI/cold-cache
        # variance — see the module docstring for the precise numbers.
        t0 = time.perf_counter()
        total, groups = admin_service.list_grouped_calls(
            None, None, None, None, True, None, None, None, None,
            limit=100, offset=0, search="python",
        )
        elapsed = time.perf_counter() - t0
        assert elapsed < 1.0, f"search took {elapsed*1000:.0f}ms, over the 1s design threshold"
        assert total > 0

    def test_grouped_search_timing_with_other_filters_active(self, live_copy):
        t0 = time.perf_counter()
        admin_service.list_grouped_calls(
            "2026-07-01", None, None, None, False, "success", None, None, None,
            limit=100, offset=0, search="python",
        )
        elapsed = time.perf_counter() - t0
        assert elapsed < 1.0, f"search+filters took {elapsed*1000:.0f}ms, over the 1s design threshold"

    def test_baseline_no_search_timing_unaffected(self, live_copy):
        # Phase N's own regression bar, using a REALISTIC call shape — a real
        # date range, same as AdminPage's own default preset always sends
        # (frontend never calls this with zero filters at all). A truly
        # filter-less call (no date range, nothing else) is a separate,
        # pre-existing edge case: with nothing to narrow candidates by, Phase
        # N's optimization has no leverage and it legitimately touches the
        # whole table (measured ~1.9s, identical whether search is used or
        # not — search=None costs a literal `0 AS has_search_match` column,
        # not a scan) — that's not something Phase R changed either way.
        t0 = time.perf_counter()
        admin_service.list_grouped_calls(
            "2026-07-17", "2026-08-17", None, None, False, None, None, None, None,
            limit=20, offset=0,
        )
        elapsed = time.perf_counter() - t0
        assert elapsed < 1.0, f"no-search baseline took {elapsed*1000:.0f}ms"

    def test_fully_unfiltered_call_unaffected_by_search_being_unused(self, live_copy):
        # Not a speed assertion (a zero-filter call has nothing for Phase N's
        # candidate narrowing to narrow by, so it's inherently a full-table
        # scan — ~1.9s measured, same before and after Phase R). This only
        # confirms search=None doesn't make that pre-existing shape WORSE.
        t0 = time.perf_counter()
        admin_service.list_grouped_calls(
            None, None, None, None, True, None, None, None, None,
            limit=20, offset=0,
        )
        elapsed = time.perf_counter() - t0
        assert elapsed < 3.0, f"fully-unfiltered call took {elapsed*1000:.0f}ms, unexpectedly slower"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
