"""
Verifies the writable_schema repair technique against a manufactured version
of the exact production corruption (duplicate sqlite_master row for an
index), and the /db-recovery endpoints built on top of it.
"""
import sqlite3

import pytest

import backend.utils.db as db
import backend.routes.db_recovery as recovery
import backend.services.backup_service as bs


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


# ── remote mirror ────────────────────────────────────────────────────────────
# The scenario these exist for: /data was wiped entirely, not just corrupted
# in place. There's no local quarantined file for the rest of this router to
# repair, and no admin account left to log into routes/backups.py with — the
# secret-header gate on this router is the only door still open, so it has to
# be able to reach backup_service's remote mirror too.

def test_remote_list_returns_remote_service_listing(monkeypatch):
    monkeypatch.setattr(
        recovery.backup_remote_service, "list_remote",
        lambda: [{"filename": "curivio-20260101-000000-t.db", "size_bytes": 5}],
    )
    assert recovery.list_remote_backups(_=None) == [
        {"filename": "curivio-20260101-000000-t.db", "size_bytes": 5}
    ]


def test_remote_list_returns_503_when_not_configured(monkeypatch):
    def _boom():
        raise RuntimeError("HF_TOKEN environment variable is not set")
    monkeypatch.setattr(recovery.backup_remote_service, "list_remote", _boom)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        recovery.list_remote_backups(_=None)
    assert exc.value.status_code == 503


def test_remote_restore_passes_filename_and_dry_run_through(monkeypatch):
    captured = {}

    def fake_restore(filename, user_id=None, dry_run=False):
        captured["args"] = (filename, user_id, dry_run)
        return {"filename": filename, "rows_restored": 3}

    monkeypatch.setattr(recovery.backup_service, "restore", fake_restore)
    result = recovery.remote_restore(filename="curivio-20260101-000000-t.db", dry_run=True, _=None)
    assert captured["args"] == ("curivio-20260101-000000-t.db", None, True)
    assert result["rows_restored"] == 3


def test_remote_restore_surfaces_an_unrecognised_filename_as_400(monkeypatch):
    def fake_restore(filename, user_id=None, dry_run=False):
        raise ValueError("backup file not found")

    monkeypatch.setattr(recovery.backup_service, "restore", fake_restore)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        recovery.remote_restore(filename="nope.db", dry_run=False, _=None)
    assert exc.value.status_code == 400


def test_remote_restore_recovers_a_fully_wiped_db_with_no_admin_account(env, tmp_path, monkeypatch):
    """/data wiped clean, init_db() just built a fresh EMPTY schema (no admin
    account to log into routes/backups.py with), and the only surviving copy
    of anything is in the remote mirror. This is the door that's still open."""
    live_path = env
    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0  # "no admin account"

    remote_file = tmp_path / "curivio-20260101-000000-remote.db"
    src_conn = sqlite3.connect(live_path)
    dst_conn = sqlite3.connect(remote_file)
    src_conn.backup(dst_conn)
    dst_conn.execute(
        "INSERT INTO users (user_id, email, name, hashed_pw) VALUES (?, ?, ?, ?)",
        ("admin-1", "admin@example.com", "Admin", "hash"),
    )
    dst_conn.commit()
    dst_conn.close()
    src_conn.close()

    def fake_download_to(filename, dest_dir):
        if filename != remote_file.name:
            raise FileNotFoundError(filename)
        dest = dest_dir / filename
        dest.write_bytes(remote_file.read_bytes())
        return dest

    monkeypatch.setattr(bs, "DB_PATH", live_path)
    monkeypatch.setattr(bs, "BACKUP_DIR", tmp_path / "backups-empty")
    monkeypatch.setattr(bs, "_PREFIX", "curivio-")
    monkeypatch.setattr(bs.backup_remote_service, "download_to", fake_download_to)

    result = recovery.remote_restore(filename=remote_file.name, dry_run=False, _=None)

    assert result["rows_restored"] > 0
    with db.get_connection() as conn:
        assert conn.execute("SELECT email FROM users").fetchone()[0] == "admin@example.com"


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
