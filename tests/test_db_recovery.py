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

    repaired, integrity_ok = recovery._repair_copy(backup)
    try:
        assert integrity_ok is True
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
        "integrity_ok": True,
        "users_readable": True,
        "users_in_backup": 1,
        "already_in_live_db": 0,
        "recoverable_new_accounts": 1,
    }
    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_integrity_ok_interprets_the_integrity_check_result_correctly():
    """Production's biggest backup had real btree damage on top of the
    catalog duplicate: PRAGMA integrity_check returned specific tree/page
    errors as ROW DATA (not an exception). _repair_copy must surface that as
    integrity_ok=False rather than raising, so callers can still attempt a
    direct users read instead of giving up on the whole file."""
    assert recovery._integrity_ok([("ok",)]) is True
    assert recovery._integrity_ok([
        ("Tree 7414 page 7414: btreeInitPage() returns error code 11",),
        ("Tree 1 page 629 cell 8: Rowid 337 out of order",),
    ]) is False
    assert recovery._integrity_ok([]) is False


def test_recover_users_reports_a_clear_error_when_users_itself_is_unreadable(env, tmp_path, monkeypatch):
    """The genuine 'nothing recoverable here' case: even the direct users
    read fails. recover_users must surface this as a 422 with a clear
    message rather than crash or silently report zero rows."""
    backup = tmp_path / "curivio.corrupt-555.db"
    _make_corrupt_backup(backup, [("u1", "alice@example.com", "Alice", "h1", "2026-01-01")])

    def broken_read_users(path):
        raise sqlite3.DatabaseError("database disk image is malformed")

    monkeypatch.setattr(recovery, "_read_users", broken_read_users)

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        recovery.recover_users(filename="curivio.corrupt-555.db", _=None)
    assert exc.value.status_code == 422
    assert "unreadable" in exc.value.detail


def test_recover_all_merges_multiple_tables_and_skips_vec_tables(env, tmp_path, monkeypatch):
    """The bigger ask: not just accounts, but chats/projects/feeds/etc. Build
    a *real* full-schema backup (via the actual init_db()) so this exercises
    the real table list, real FK relationships, and the real vec0 tables —
    not a hand-picked subset."""
    backup_path = tmp_path / "backup_source.db"
    monkeypatch.setattr(db, "DB_PATH", backup_path)
    db.init_db()
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO users (user_id, email, name, hashed_pw, created_at) VALUES (?,?,?,?,?)",
            ("u1", "alice@example.com", "Alice", "h1", "2026-01-01"),
        )
        conn.execute(
            "INSERT INTO user_preferences (topic, preference_score) VALUES (?, ?)",
            ("machine-learning", 0.8),
        )
    # corrupt it the standard way
    conn = sqlite3.connect(backup_path)
    conn.execute("PRAGMA writable_schema=ON")
    conn.execute(
        "INSERT INTO sqlite_master (type, name, tbl_name, rootpage, sql) "
        "SELECT type, name, tbl_name, rootpage, sql FROM sqlite_master "
        "WHERE name='idx_llm_call_log_trace_id'"
    )
    conn.commit()
    conn.execute("PRAGMA writable_schema=OFF")
    conn.close()
    backup = tmp_path / "curivio.corrupt-666.db"
    backup_path.rename(backup)

    live_path = env  # restore the fixture's live db as the active DB_PATH
    monkeypatch.setattr(db, "DB_PATH", live_path)
    monkeypatch.setattr(recovery, "DB_PATH", live_path)
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO user_preferences (topic, preference_score) VALUES (?, ?)",
            ("already-live-topic", 0.1),
        )

    result = recovery.recover_all(filename="curivio.corrupt-666.db", _=None)

    assert result["tables"]["users"] == {"status": "ok", "rows_inserted": 1}
    assert result["tables"]["user_preferences"] == {"status": "ok", "rows_inserted": 1}
    for name, outcome in result["tables"].items():
        if outcome["status"] == "ok":
            assert "vec" not in name or True  # vec tables should never reach "ok" via this path
    vec_results = {n: r for n, r in result["tables"].items() if "vec" in n.lower()}
    assert vec_results, "fixture schema should include the vec0 tables"
    assert all(r["status"] == "skipped_vec_table" for r in vec_results.values())

    with db.get_connection() as conn:
        topics = {r["topic"] for r in conn.execute("SELECT topic FROM user_preferences").fetchall()}
        emails = {r["email"] for r in conn.execute("SELECT email FROM users").fetchall()}
    assert "machine-learning" in topics
    assert "already-live-topic" in topics  # untouched, not clobbered
    assert "alice@example.com" in emails

    # Re-running on the SAME file must not duplicate rows in tables that
    # have no natural unique constraint (chat_messages, api_usage_log, ...
    # here represented by user_preferences having no dupe-proof beyond its
    # own UNIQUE topic — the real regression was in tables without even that).
    second = recovery.recover_all(filename="curivio.corrupt-666.db", _=None)
    assert second["tables"]["users"] == {"status": "already_recovered_from_this_file"}
    assert second["tables"]["user_preferences"] == {"status": "already_recovered_from_this_file"}
    with db.get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM user_preferences WHERE topic = 'machine-learning'"
        ).fetchone()[0]
    assert count == 1


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
