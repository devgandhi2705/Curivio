"""
Covers the parts of backup_service that can silently lose or leak data:

  * per-user scoping derived from the schema (does it find chat_messages via
    chat_sessions? does it refuse to link on a meaningless INTEGER id?)
  * schema drift — an old snapshot restoring into a newer table
  * idempotency — the bug that duplicated production rows once already
  * the empty-rebuild guard that stops the scheduler eating real snapshots

Uses the REAL schema via db.init_db() rather than a hand-rolled subset, since
the whole point of deriving scope from the schema is that it must track the
actual tables as they change.
"""

import sqlite3
from pathlib import Path

import pytest

import backend.utils.db as db
import backend.services.backup_service as backup


@pytest.fixture
def live(tmp_path, monkeypatch):
    """A live DB on the real schema, with backup_service pointed at it."""
    db_path = tmp_path / "curivio.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(backup, "DB_PATH", db_path)
    monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(backup, "_PREFIX", "curivio-")
    db.init_db()
    return db_path


def _seed(conn, user_id, email, *, sessions=1, messages=3, projects=1):
    conn.execute(
        "INSERT INTO users (user_id, email, name, hashed_pw) VALUES (?,?,?,?)",
        (user_id, email, email.split("@")[0], "hash"),
    )
    for s in range(sessions):
        sid = f"{user_id}-sess-{s}"
        conn.execute(
            "INSERT INTO chat_sessions (session_id, title, user_id) VALUES (?,?,?)",
            (sid, f"Session {s}", user_id),
        )
        for m in range(messages):
            conn.execute(
                "INSERT INTO chat_messages (session_id, role, content) VALUES (?,?,?)",
                (sid, "user" if m % 2 == 0 else "assistant", f"msg {m}"),
            )
    for p in range(projects):
        conn.execute(
            "INSERT INTO learning_projects (project_id, name, user_id) VALUES (?,?,?)",
            (f"{user_id}-proj-{p}", f"Project {p}", user_id),
        )
        conn.execute(
            "INSERT INTO project_insights (project_id, insight_json) VALUES (?,?)",
            (f"{user_id}-proj-{p}", '{"x":1}'),
        )


# ── scoping derivation ───────────────────────────────────────────────────────

def test_scope_finds_direct_user_id_tables(live):
    with db.get_connection() as conn:
        scope = backup.derive_user_scope(conn)
    assert scope["users"] == '"user_id" = ?'
    assert scope["chat_sessions"] == '"user_id" = ?'
    assert scope["learning_projects"] == '"user_id" = ?'


def test_scope_reaches_children_with_no_foreign_key_declared(live):
    """chat_messages.session_id has NO REFERENCES clause in this schema, so FK
    introspection would miss the single biggest user-owned table. Name-based
    linking must still find it."""
    with db.get_connection() as conn:
        scope = backup.derive_user_scope(conn)
    assert "chat_messages" in scope
    assert 'FROM main."chat_sessions"' in scope["chat_messages"]
    assert scope["chat_messages"].count("?") == 1


def test_scope_reaches_children_through_a_real_foreign_key(live):
    with db.get_connection() as conn:
        scope = backup.derive_user_scope(conn)
    assert 'FROM main."learning_projects"' in scope["project_insights"]


def test_scope_leaves_global_tables_alone(live):
    """Caches and shared infrastructure are nobody's personal data — a per-user
    restore must not drag them in."""
    with db.get_connection() as conn:
        scope = backup.derive_user_scope(conn)
    for table in ("feed_cache", "search_cache", "unpack_cache"):
        assert table not in scope


def test_scope_never_links_on_a_surrogate_integer_id(live):
    """Two independently created DBs both auto-assign id=1 to their first row.
    Linking tables on that would join completely unrelated records together, so
    only TEXT primary keys are allowed as parents."""
    with db.get_connection() as conn:
        for table in backup._real_tables(conn):
            assert backup.linkable_pk_column(conn, table) != "id"
        scope = backup.derive_user_scope(conn)
    assert not any('"id" IN' in pred for pred in scope.values())


def test_auth_state_tables_are_never_restored(live):
    """A consumed password-reset token that comes back looking unused is a
    downgrade, not a recovery. revoked_tokens is the deliberate exception:
    restoring a blocklist only ever rejects more, so it fails safe."""
    filename = _snapshot_then_wipe(lambda c: _seed(c, "u1", "a@example.com"))
    result = backup.restore(filename)
    for table in ("password_reset_tokens", "pending_signups",
                  "verification_lockouts", "resend_cooldowns"):
        assert table not in result["tables"]
    assert "revoked_tokens" in result["tables"]


def test_scope_predicate_actually_selects_only_that_users_rows(live):
    with db.get_connection() as conn:
        _seed(conn, "u1", "a@example.com")
        _seed(conn, "u2", "b@example.com", sessions=2)
    with db.get_connection() as conn:
        scope = backup.derive_user_scope(conn)
        n = conn.execute(
            f'SELECT COUNT(*) FROM chat_messages WHERE {scope["chat_messages"]}', ("u1",)
        ).fetchone()[0]
    assert n == 3          # u1 has 1 session x 3 messages; u2's 6 must not leak in


# ── snapshots ────────────────────────────────────────────────────────────────

def test_snapshot_roundtrip(live):
    with db.get_connection() as conn:
        _seed(conn, "u1", "a@example.com")
    result = backup.create_snapshot("test", force=True)
    assert result["ok"], result
    snap = backup.BACKUP_DIR / result["filename"]
    conn = sqlite3.connect(snap)
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == 3
    conn.close()


def test_scheduler_refuses_to_snapshot_over_an_empty_rebuild(live):
    """The exact production incident: corruption self-heal rebuilds the DB
    empty, and the interval scheduler must NOT then snapshot the empty file
    repeatedly until every real snapshot is pruned away."""
    with db.get_connection() as conn:
        _seed(conn, "u1", "a@example.com")
    assert backup.create_snapshot("good", force=True)["ok"]

    with db.get_connection() as conn:          # simulate the wipe
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("DELETE FROM users")

    auto = backup.create_snapshot("auto")
    assert auto["ok"] is False
    assert "0 accounts" in auto["reason"]
    # an admin can still override deliberately
    assert backup.create_snapshot("manual", force=True)["ok"] is True


def test_automatic_snapshot_skipped_when_one_was_just_taken(live, monkeypatch):
    """A Space that restarts often (sleep/wake, or a burst of redeploys) must
    not take a near-duplicate premigration snapshot on every single boot —
    each one is a real local write and a real remote push for zero new data."""
    monkeypatch.setattr(backup, "MIN_GAP_SECONDS", 3600)
    with db.get_connection() as conn:
        _seed(conn, "u1", "a@example.com")
    first = backup.create_snapshot("premigration", force=True)
    assert first["ok"] is True

    second = backup.create_snapshot("premigration", force=False)
    assert second["ok"] is False
    assert "gap" in second["reason"]


def test_force_bypasses_the_minimum_gap(live, monkeypatch):
    """Admin's explicit 'take snapshot now' and the pre-restore snapshot both
    pass force=True — they must never be silently skipped."""
    monkeypatch.setattr(backup, "MIN_GAP_SECONDS", 3600)
    with db.get_connection() as conn:
        _seed(conn, "u1", "a@example.com")
    first = backup.create_snapshot("t", force=True)
    second = backup.create_snapshot("manual", force=True)
    assert first["ok"] is True
    assert second["ok"] is True


def test_automatic_snapshot_allowed_once_the_gap_has_passed(live, monkeypatch):
    monkeypatch.setattr(backup, "MIN_GAP_SECONDS", 0)
    with db.get_connection() as conn:
        _seed(conn, "u1", "a@example.com")
    first = backup.create_snapshot("premigration", force=True)
    second = backup.create_snapshot("auto", force=False)
    assert first["ok"] is True
    assert second["ok"] is True


def test_prune_keeps_the_newest(live, monkeypatch):
    monkeypatch.setattr(backup, "LOCAL_MAX_SNAPSHOTS", 3)
    with db.get_connection() as conn:
        _seed(conn, "u1", "a@example.com")
    names = []
    for i in range(5):
        monkeypatch.setattr(backup, "_snapshot_name", lambda label, i=i: f"curivio-2026010{i}-000000-t.db")
        names.append(backup.create_snapshot("t", force=True)["filename"])
    remaining = sorted(p.name for p in backup.BACKUP_DIR.glob("curivio-*.db"))
    assert remaining == sorted(names[-3:])


def _make_fake_quarantine_file(live, epoch: int) -> Path:
    path = live.parent / f"{live.stem}.corrupt-{epoch}.db"
    sqlite3.connect(path).close()      # just needs to exist and be a real sqlite file
    return path


def test_quarantined_files_are_pruned_to_the_newest(live, monkeypatch):
    """Quarantined files sit on the same tight local disk budget as everything
    else and, unlike snapshots, were never bounded at all — left alone they
    accumulate forever. Now capped like everything else in BACKUP_DIR."""
    monkeypatch.setattr(backup, "QUARANTINE_MAX_FILES", 1)
    older = _make_fake_quarantine_file(live, 1000)
    newer = _make_fake_quarantine_file(live, 2000)
    with db.get_connection() as conn:
        _seed(conn, "u1", "a@example.com")
    backup.create_snapshot("t", force=True)

    assert not older.exists()
    assert newer.exists()


def test_list_snapshots_no_longer_shows_quarantined_files(live):
    """Quarantined files are still fully restorable via resolve_source/restore
    (and via routes/db_recovery.py's own separate emergency listing) — they
    just don't clutter the routine admin panel's snapshot list any more."""
    _make_fake_quarantine_file(live, 12345)
    kinds = {r["kind"] for r in backup.list_snapshots()}
    assert "quarantined" not in kinds


def test_resolve_source_rejects_path_traversal(live):
    for bad in ("../../etc/passwd", "/etc/passwd", "curivio.db", "", ".."):
        with pytest.raises(ValueError):
            backup.resolve_source(bad)


# ── restore ──────────────────────────────────────────────────────────────────

def _snapshot_then_wipe(seed_fn):
    """Seed, snapshot, then empty the live DB — the corruption-rebuild shape."""
    with db.get_connection() as conn:
        seed_fn(conn)
    filename = backup.create_snapshot("t", force=True)["filename"]
    with db.get_connection() as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        for t in ("chat_messages", "chat_sessions", "project_insights",
                  "learning_projects", "users"):
            conn.execute(f"DELETE FROM {t}")
    return filename


def test_full_restore_brings_everything_back(live):
    filename = _snapshot_then_wipe(lambda c: (_seed(c, "u1", "a@example.com"),
                                              _seed(c, "u2", "b@example.com")))
    result = backup.restore(filename)
    assert result["rows_restored"] > 0
    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == 6
        assert conn.execute("SELECT COUNT(*) FROM project_insights").fetchone()[0] == 2


def test_per_user_restore_brings_back_only_that_user(live):
    filename = _snapshot_then_wipe(lambda c: (_seed(c, "u1", "a@example.com"),
                                              _seed(c, "u2", "b@example.com", sessions=2)))
    backup.restore(filename, user_id="u1")
    with db.get_connection() as conn:
        emails = [r[0] for r in conn.execute("SELECT email FROM users").fetchall()]
        msgs = conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]
        insights = conn.execute("SELECT COUNT(*) FROM project_insights").fetchone()[0]
    assert emails == ["a@example.com"]
    assert msgs == 3        # u1's only; u2's 6 stayed out
    assert insights == 1


def test_restore_is_idempotent(live):
    """The regression that actually duplicated production data: tables with no
    UNIQUE constraint of their own (chat_messages) cannot be deduped by
    INSERT OR IGNORE, so a second restore must be stopped by restore_log."""
    filename = _snapshot_then_wipe(lambda c: _seed(c, "u1", "a@example.com"))
    first = backup.restore(filename)
    second = backup.restore(filename)

    assert second["rows_restored"] == 0
    assert second["tables"]["chat_messages"]["status"] == "already_restored"
    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == 3
    assert first["rows_restored"] > 0


def test_full_and_per_user_restores_do_not_mask_each_other(live):
    """Different scopes are logged separately: having restored user u1 must not
    make a later full restore think it has already run."""
    filename = _snapshot_then_wipe(lambda c: (_seed(c, "u1", "a@example.com"),
                                              _seed(c, "u2", "b@example.com")))
    backup.restore(filename, user_id="u1")
    full = backup.restore(filename)
    assert full["rows_restored"] > 0
    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
        # u1's rows were already back and must not have doubled
        assert conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == 6


def test_restore_never_overwrites_a_newer_live_row(live):
    filename = _snapshot_then_wipe(lambda c: _seed(c, "u1", "a@example.com"))
    with db.get_connection() as conn:
        conn.execute("INSERT INTO users (user_id, email, name, hashed_pw) VALUES (?,?,?,?)",
                     ("u1", "a@example.com", "NEWER NAME", "newhash"))
    backup.restore(filename)
    with db.get_connection() as conn:
        assert conn.execute("SELECT name FROM users WHERE user_id='u1'").fetchone()[0] == "NEWER NAME"


def test_restore_survives_schema_drift_in_both_directions(live, monkeypatch):
    """An old snapshot restoring into a newer table, and a snapshot holding a
    column the live schema has since dropped. Neither may fail the table."""
    with db.get_connection() as conn:
        _seed(conn, "u1", "a@example.com")
        conn.execute("ALTER TABLE learning_projects ADD COLUMN since_removed TEXT")
        conn.execute("UPDATE learning_projects SET since_removed = 'old value'")
    filename = backup.create_snapshot("t", force=True)["filename"]

    with db.get_connection() as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("DELETE FROM learning_projects")
        conn.execute("ALTER TABLE learning_projects DROP COLUMN since_removed")   # drift A
        conn.execute("ALTER TABLE learning_projects ADD COLUMN added_later TEXT DEFAULT 'dflt'")  # drift B

    result = backup.restore(filename)
    assert result["tables"]["learning_projects"]["status"] == "ok"
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT name, added_later FROM learning_projects WHERE user_id='u1'"
        ).fetchone()
    assert row["name"] == "Project 0"
    assert row["added_later"] == "dflt"     # new column took its default


def test_preview_writes_nothing(live):
    filename = _snapshot_then_wipe(lambda c: _seed(c, "u1", "a@example.com"))
    preview = backup.restore(filename, dry_run=True)
    assert preview["dry_run"] is True
    assert preview["rows_available"] > 0
    assert preview["tables"]["chat_messages"]["in_snapshot"] == 3
    assert preview["tables"]["chat_messages"]["in_live_db"] == 0
    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_preview_counts_live_rows_against_the_live_db_not_the_snapshot(live):
    """Regression: the per-user live count has to resolve its subquery against
    `main`, not `backup`. Using the snapshot's predicate for both made the live
    count mean 'live rows whose session exists in the snapshot' — wrong, and
    wrong in the flattering direction."""
    with db.get_connection() as conn:
        _seed(conn, "u1", "a@example.com")
    filename = backup.create_snapshot("t", force=True)["filename"]
    preview = backup.restore(filename, user_id="u1", dry_run=True)
    assert preview["tables"]["chat_messages"]["in_live_db"] == 3


def test_preview_flags_rows_no_per_user_restore_can_claim(live):
    """user_id was added to several tables as a NULLABLE column by a later
    migration, so pre-migration rows carry NULL and belong to nobody. An admin
    must be able to see that a per-user restore will not find them."""
    with db.get_connection() as conn:
        _seed(conn, "u1", "a@example.com")
        conn.execute(
            "INSERT INTO chat_sessions (session_id, title, user_id) VALUES (?,?,NULL)",
            ("orphan-sess", "pre-migration session"),
        )
    filename = backup.create_snapshot("t", force=True)["filename"]
    preview = backup.restore(filename, user_id="u1", dry_run=True)
    assert preview["tables"]["chat_sessions"]["unattributed_in_snapshot"] == 1


def test_vec_tables_are_skipped(live):
    filename = _snapshot_then_wipe(lambda c: _seed(c, "u1", "a@example.com"))
    result = backup.restore(filename)
    vec = {n: r for n, r in result["tables"].items() if "vec" in n.lower()}
    assert vec, "real schema should contain vec0 tables"
    assert all(r["status"] == "skipped_vec_table" for r in vec.values())


def test_restore_of_a_quarantined_corrupt_file(live, tmp_path):
    """The file db.py leaves behind after a corruption event is unopenable by
    SQLite. Restore must repair a copy of it rather than refusing."""
    with db.get_connection() as conn:
        _seed(conn, "u1", "a@example.com")
    quarantined = live.parent / "curivio.corrupt-999.db"
    src = sqlite3.connect(live)
    dst = sqlite3.connect(quarantined)
    src.backup(dst)
    dst.close()
    src.close()

    conn = sqlite3.connect(quarantined)      # reproduce the exact corruption
    conn.execute("PRAGMA writable_schema=ON")
    conn.execute(
        "INSERT INTO sqlite_master (type, name, tbl_name, rootpage, sql) "
        "SELECT type, name, tbl_name, rootpage, sql FROM sqlite_master "
        "WHERE name='idx_chat_messages_session'"
    )
    conn.commit()
    conn.close()
    with pytest.raises(sqlite3.DatabaseError):
        sqlite3.connect(quarantined).execute("SELECT COUNT(*) FROM users")

    with db.get_connection() as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("DELETE FROM chat_messages")
        conn.execute("DELETE FROM chat_sessions")
        conn.execute("DELETE FROM users")

    result = backup.restore("curivio.corrupt-999.db")
    assert result["integrity_ok"] is True
    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == 3


# ── remote mirror ────────────────────────────────────────────────────────────
# backup_remote_service pushes snapshots off-volume (see its own module
# docstring for why). These tests fake it out with a plain in-memory dict —
# matching this file's existing "monkeypatch a module attribute" convention
# rather than unittest.mock — so they exercise backup_service's own logic
# (what it does with success/failure/absence) without real network calls.

class _FakeRemote:
    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.uploaded: list[str] = []

    def upload_snapshot(self, path):
        self.files[path.name] = path.read_bytes()
        self.uploaded.append(path.name)

    def list_remote(self):
        return [{"filename": n, "size_bytes": len(b)} for n, b in self.files.items()]

    def download_to(self, filename, dest_dir):
        if filename not in self.files:
            raise FileNotFoundError(filename)
        dest = dest_dir / filename
        dest.write_bytes(self.files[filename])
        return dest

    def prune_remote(self, keep):
        names = sorted(self.files)
        removed = names[:-keep] if len(names) > keep else []
        for n in removed:
            del self.files[n]
        return removed


@pytest.fixture
def fake_remote(monkeypatch):
    fake = _FakeRemote()
    monkeypatch.setattr(backup.backup_remote_service, "upload_snapshot", fake.upload_snapshot)
    monkeypatch.setattr(backup.backup_remote_service, "list_remote", fake.list_remote)
    monkeypatch.setattr(backup.backup_remote_service, "download_to", fake.download_to)
    monkeypatch.setattr(backup.backup_remote_service, "prune_remote", fake.prune_remote)
    return fake


def test_snapshot_still_ok_when_remote_is_not_configured(live, monkeypatch):
    """No HF_TOKEN in this environment (the common case: local dev, or a
    deploy that hasn't set it up yet) must not stop the local snapshot from
    succeeding — it just can't also go off-volume."""
    monkeypatch.delenv("HF_TOKEN", raising=False)
    result = backup.create_snapshot("t", force=True)
    assert result["ok"] is True
    assert result["remote_ok"] is False
    assert "HF_TOKEN" in result["remote_error"]


def test_snapshot_pushes_to_remote_and_prunes_it(live, fake_remote, monkeypatch):
    monkeypatch.setattr(backup, "REMOTE_MAX_SNAPSHOTS", 1)
    first = backup.create_snapshot("t", force=True)
    assert first["remote_ok"] is True
    assert first["filename"] in fake_remote.files

    second = backup.create_snapshot("t", force=True)
    assert second["remote_ok"] is True
    # remote retention is independent of local: only the newest is kept remotely
    assert list(fake_remote.files) == [second["filename"]]


def test_snapshot_remote_failure_does_not_fail_the_local_snapshot(live, fake_remote, monkeypatch):
    def _boom(path):
        raise RuntimeError("network down")
    monkeypatch.setattr(backup.backup_remote_service, "upload_snapshot", _boom)

    result = backup.create_snapshot("t", force=True)
    assert result["ok"] is True
    assert (backup.BACKUP_DIR / result["filename"]).exists()
    assert result["remote_ok"] is False
    assert "network down" in result["remote_error"]


def test_push_remote_false_skips_remote_entirely(live, fake_remote):
    result = backup.create_snapshot("t", force=True, push_remote=False)
    assert result["ok"] is True
    assert "remote_ok" not in result
    assert fake_remote.uploaded == []


def test_push_remote_snapshot_can_be_called_directly(live, fake_remote):
    """main.py's boot path calls this on its own, in a background thread, so
    the boot-time local snapshot isn't held up by network I/O."""
    result = backup.create_snapshot("t", force=True, push_remote=False)
    dest = backup.BACKUP_DIR / result["filename"]
    outcome = backup.push_remote_snapshot(dest)
    assert outcome == {"remote_ok": True}
    assert dest.name in fake_remote.files


def test_list_snapshots_includes_remote_only_entries(live, fake_remote):
    fake_remote.files["curivio-20260101-000000-remoteonly.db"] = b"x"
    kinds = {r["filename"]: r["kind"] for r in backup.list_snapshots()}
    assert kinds["curivio-20260101-000000-remoteonly.db"] == "remote"


def test_list_snapshots_prefers_local_when_a_file_exists_in_both(live, fake_remote):
    result = backup.create_snapshot("t", force=True)
    filename = result["filename"]
    assert filename in fake_remote.files          # pushed by create_snapshot
    rows = [r for r in backup.list_snapshots() if r["filename"] == filename]
    assert len(rows) == 1
    assert rows[0]["kind"] == "snapshot"           # not duplicated as "remote"


def test_list_snapshots_survives_a_remote_listing_failure(live, monkeypatch):
    def _boom():
        raise RuntimeError("network down")
    monkeypatch.setattr(backup.backup_remote_service, "list_remote", _boom)
    with db.get_connection() as conn:
        _seed(conn, "u1", "a@example.com")
    backup.create_snapshot("t", force=True)
    # local listing still works even though the remote call blew up
    assert any(r["kind"] == "snapshot" for r in backup.list_snapshots())


def test_resolve_source_does_not_require_local_existence_for_a_snapshot_name(live):
    """A snapshot name may exist only remotely (local retention dropped it, or
    local disk was wiped) — resolve_source is a fast path-safety check, not
    the thing that decides whether the file is actually reachable."""
    path = backup.resolve_source("curivio-20260101-000000-remoteonly.db")
    assert path.parent == backup.BACKUP_DIR
    assert not path.exists()


def test_resolve_source_still_requires_local_existence_for_a_quarantined_name(live, tmp_path):
    with pytest.raises(ValueError):
        backup.resolve_source("curivio.corrupt-12345.db")


def test_restore_falls_back_to_remote_when_not_local(live, fake_remote):
    """The actual disaster-recovery scenario: local BACKUP_DIR is empty (fresh
    volume) but the file still exists in the remote mirror."""
    filename = _snapshot_then_wipe(lambda c: _seed(c, "u1", "a@example.com"))
    assert filename in fake_remote.files
    for f in backup.BACKUP_DIR.glob(f"{backup._PREFIX}*"):
        f.unlink()                                  # simulate local-only loss

    result = backup.restore(filename)
    assert result["rows_restored"] > 0
    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


def test_users_in_snapshot_falls_back_to_remote_when_not_local(live, fake_remote):
    filename = _snapshot_then_wipe(lambda c: _seed(c, "u1", "a@example.com"))
    for f in backup.BACKUP_DIR.glob(f"{backup._PREFIX}*"):
        f.unlink()

    users = backup.users_in_snapshot(filename)
    assert [u["email"] for u in users] == ["a@example.com"]


def test_restore_of_a_filename_that_exists_nowhere_raises_value_error(live, fake_remote):
    with pytest.raises(ValueError):
        backup.restore("curivio-20260101-000000-doesnotexist.db")


def test_remote_download_temp_files_are_cleaned_up(live, fake_remote):
    """_prepare_source's remote branch downloads into a temp dir — confirm it
    doesn't leak that directory once the caller is done with it."""
    filename = _snapshot_then_wipe(lambda c: _seed(c, "u1", "a@example.com"))
    for f in backup.BACKUP_DIR.glob(f"{backup._PREFIX}*"):
        f.unlink()
    import tempfile
    before = set(Path(tempfile.gettempdir()).iterdir())
    backup.restore(filename)
    after = set(Path(tempfile.gettempdir()).iterdir())
    assert after - before == set(), f"leaked temp entries: {after - before}"
