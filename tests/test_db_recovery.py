"""
Verifies the writable_schema repair technique against a manufactured version
of the exact production corruption (duplicate sqlite_master row for an
index), and the /db-recovery endpoints built on top of it.
"""
import sqlite3

import pytest

import backend.utils.db as db
import backend.routes.db_recovery as recovery


def _make_corrupt_backup(path, users):
    """A db with a real users table + real rows, corrupted the same way
    production was: a duplicate sqlite_master row for an unrelated index."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE users (user_id TEXT PRIMARY KEY, email TEXT UNIQUE, "
        "name TEXT, hashed_pw TEXT, created_at TEXT)"
    )
    conn.execute("CREATE TABLE llm_call_log (trace_id TEXT)")
    conn.execute("CREATE INDEX idx_llm_call_log_trace_id ON llm_call_log (trace_id)")
    for row in users:
        conn.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?)", row)
    conn.commit()
    conn.execute("PRAGMA writable_schema=ON")
    conn.execute(
        "INSERT INTO sqlite_master (type, name, tbl_name, rootpage, sql) "
        "SELECT type, name, tbl_name, rootpage, sql FROM sqlite_master "
        "WHERE name='idx_llm_call_log_trace_id'"
    )
    conn.commit()
    conn.execute("PRAGMA writable_schema=OFF")
    conn.close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    db_path = tmp_path / "curivio.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(recovery, "DB_PATH", db_path)
    db.init_db()  # live db starts with the normal empty schema
    return db_path


def test_repair_copy_recovers_a_manufactured_corruption(env, tmp_path):
    backup = tmp_path / "curivio.corrupt-111.db"
    _make_corrupt_backup(backup, [("u1", "alice@example.com", "Alice", "h1", "2026-01-01")])

    repaired = recovery._repair_copy(backup)
    try:
        conn = sqlite3.connect(repaired)
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert conn.execute("SELECT email FROM users").fetchall() == [("alice@example.com",)]
        conn.close()
        # original backup is untouched
        untouched = sqlite3.connect(backup)
        with pytest.raises(sqlite3.DatabaseError):
            untouched.execute("PRAGMA journal_mode")
        untouched.close()
    finally:
        repaired.unlink(missing_ok=True)


def test_recover_users_merges_without_clobbering_live_accounts(env, tmp_path):
    live_path = env
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO users (user_id, email, name, hashed_pw, created_at) VALUES (?, ?, ?, ?, ?)",
            ("live-1", "carol@example.com", "Carol (already live)", "hlive", "2026-02-01"),
        )

    backup = tmp_path / "curivio.corrupt-222.db"
    _make_corrupt_backup(backup, [
        ("u1", "alice@example.com", "Alice", "h1", "2026-01-01"),
        ("live-1", "carol@example.com", "Carol (stale copy)", "hstale", "2026-01-01"),
    ])

    result = recovery.recover_users(filename="curivio.corrupt-222.db", _=None)

    assert result["rows_in_backup"] == 2
    assert result["rows_inserted"] == 1  # alice is new, carol already exists live

    with db.get_connection() as conn:
        rows = {r["email"]: r["name"] for r in conn.execute("SELECT email, name FROM users").fetchall()}
    assert rows["alice@example.com"] == "Alice"
    assert rows["carol@example.com"] == "Carol (already live)"  # untouched, not overwritten by stale copy


def test_inspect_reports_counts_without_mutating_live_db(env, tmp_path):
    backup = tmp_path / "curivio.corrupt-333.db"
    _make_corrupt_backup(backup, [("u1", "alice@example.com", "Alice", "h1", "2026-01-01")])

    result = recovery.inspect_backup(filename="curivio.corrupt-333.db", _=None)
    assert result == {
        "filename": "curivio.corrupt-333.db",
        "users_in_backup": 1,
        "already_in_live_db": 0,
        "recoverable_new_accounts": 1,
    }
    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_resolve_backup_rejects_path_traversal(env, tmp_path):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        recovery._resolve_backup("../../etc/passwd")
    assert exc.value.status_code == 400


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        live = tmp / "curivio.db"
        with patch.object(db, "DB_PATH", live), patch.object(recovery, "DB_PATH", live):
            db.init_db()
            backup = tmp / "curivio.corrupt-999.db"
            _make_corrupt_backup(backup, [("u1", "alice@example.com", "Alice", "h1", "2026-01-01")])
            result = recovery.recover_users(filename="curivio.corrupt-999.db", _=None)
            assert result["rows_inserted"] == 1
    print("ok")
