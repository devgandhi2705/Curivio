"""
Phase 3 schema tests: v2 migrations apply clean, trace_id JOIN groups a run's
child calls, and the partial unique index blocks a second concurrent 'running'
row for the same (project_id, day_number).
"""
import shutil
import sqlite3
from pathlib import Path

import pytest

from backend.database.schema import ALL_TABLES, MIGRATIONS
from backend.services.feed_v2.schema import run_v2_migrations

REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_DB = REPO_ROOT / "data" / "curivio.db"


def _apply_migrations(conn) -> None:
    """Replicate init_db()'s apply order, then layer v2's own migrations on top."""
    for stmt in ALL_TABLES:
        conn.execute(stmt)
    for migration in MIGRATIONS:
        try:
            if isinstance(migration, (list, tuple)):
                for s in migration:
                    conn.execute(s)
            else:
                conn.execute(migration)
        except sqlite3.OperationalError as exc:
            if not any(p in str(exc).lower() for p in ("already exists", "duplicate column", "no such column")):
                raise
    run_v2_migrations(conn)
    conn.commit()


def _fresh_db(tmp_path) -> str:
    db = str(tmp_path / "fresh.db")
    conn = sqlite3.connect(db)  # conftest patches connect to load sqlite_vec
    _apply_migrations(conn)
    conn.close()
    return db


def _seed_user(conn, uid="u1"):
    conn.execute(
        "INSERT OR IGNORE INTO users (user_id, email, name, hashed_pw) VALUES (?, ?, ?, ?)",
        (uid, f"{uid}@t.com", uid, "x"),
    )


def test_v2_migrations_apply_clean_on_live_copy(tmp_path):
    if not LIVE_DB.exists():
        pytest.skip("live curivio.db not present")
    copy = tmp_path / "curivio_copy.db"
    shutil.copy(LIVE_DB, copy)
    conn = sqlite3.connect(str(copy))
    _apply_migrations(conn)
    # llm_call_log gained the 4 Phase-3 columns.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(llm_call_log)").fetchall()}
    assert {"trace_id", "agent_name", "step_index", "surface"} <= cols
    # Every v2 table exists.
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    for t in ("mas_runs", "v2_projects", "v2_materials", "v2_material_chunks",
              "v2_material_figures", "v2_journey_plans", "v2_packages",
              "v2_package_sources", "v2_retrieval_checks", "v2_mastery"):
        assert t in tables, f"missing v2 table {t}"
    # vec shadow + both required indexes exist.
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='v2_material_chunks_vec'").fetchone()
    idx = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
    assert "idx_mas_runs_running_unique" in idx
    assert "idx_llm_call_log_trace_id" in idx
    conn.close()


def test_mas_run_join_by_trace_id(tmp_path):
    conn = sqlite3.connect(_fresh_db(tmp_path))
    _seed_user(conn)
    conn.execute(
        "INSERT INTO mas_runs (trace_id, surface, user_id, project_id, day_number, status, started_at) "
        "VALUES ('trace-A', 'feed_v2', 'u1', 'p1', 3, 'running', '2026-08-11T00:00:00Z')"
    )
    for i in range(3):
        conn.execute(
            "INSERT INTO llm_call_log (run_id, timestamp_start, timestamp_end, latency_ms, provider, "
            "input, success, trace_id, agent_name, step_index, surface) "
            "VALUES (?, '2026-08-11T00:00:00Z', '2026-08-11T00:00:01Z', 10, 'gemini', 'in', 1, "
            "'trace-A', ?, ?, 'feed_v2')",
            (f"run-{i}", f"agent{i}", i),
        )
    conn.commit()
    rows = conn.execute(
        "SELECT c.run_id, c.agent_name, c.step_index FROM mas_runs r "
        "JOIN llm_call_log c ON c.trace_id = r.trace_id "
        "WHERE r.trace_id = 'trace-A' ORDER BY c.step_index"
    ).fetchall()
    conn.close()
    assert len(rows) == 3
    assert [r[0] for r in rows] == ["run-0", "run-1", "run-2"]


def test_running_unique_index_blocks_second_row(tmp_path):
    db = _fresh_db(tmp_path)
    conn_a = sqlite3.connect(db)
    _seed_user(conn_a)
    conn_a.execute(
        "INSERT INTO mas_runs (trace_id, surface, user_id, project_id, day_number, status, started_at) "
        "VALUES ('run-1', 'feed_v2', 'u1', 'proj', 5, 'running', 't0')"
    )
    conn_a.commit()

    conn_b = sqlite3.connect(db)
    with pytest.raises(sqlite3.IntegrityError):
        conn_b.execute(
            "INSERT INTO mas_runs (trace_id, surface, user_id, project_id, day_number, status, started_at) "
            "VALUES ('run-2', 'feed_v2', 'u1', 'proj', 5, 'running', 't1')"
        )
        conn_b.commit()
    conn_b.rollback()  # release conn_b's failed-write lock before conn_a writes again
    conn_b.close()

    # A non-running duplicate (project, day) is allowed — partial index only guards 'running'.
    conn_a.execute(
        "INSERT INTO mas_runs (trace_id, surface, user_id, project_id, day_number, status, started_at) "
        "VALUES ('run-3', 'feed_v2', 'u1', 'proj', 5, 'done', 't2')"
    )
    conn_a.commit()
    conn_a.close()
