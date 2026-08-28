"""
One-time recovery tool for accounts trapped in quarantined curivio.corrupt-*.db
backups (see backend/utils/db.py's WAL-corruption self-heal). Gated by
AUTH_SECRET_KEY directly via a header, not get_current_admin_user — a
corruption event wipes the live users table, including the admin's own
account, so a login-based admin check can't gate the tool that recovers it.

The corruption is always the same shape: one duplicate sqlite_master row for
an index, which makes SQLite refuse to open the file at all. The underlying
table data is untouched — deleting the extra catalog row on a COPY of the
backup (never the original) makes it a fully valid, fully readable database
again. See tests/test_db_recovery.py for the repair technique verified
against a manufactured version of the exact production corruption.
"""
import hmac
import shutil
import sqlite3
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException

from ..services.auth_service import SECRET_KEY
from ..utils.db import DB_PATH, get_connection

router = APIRouter(prefix="/db-recovery", tags=["db-recovery"])


def _require_secret(x_recovery_secret: str | None = Header(default=None)) -> None:
    if not x_recovery_secret or not hmac.compare_digest(x_recovery_secret, SECRET_KEY):
        raise HTTPException(status_code=403, detail="invalid recovery secret")


def _resolve_backup(filename: str) -> Path:
    # filename comes from an HTTP caller — reject anything that isn't a plain
    # basename inside DB_PATH.parent matching the exact backup naming scheme
    # _recover_from_corruption() writes, so this can't be used to read an
    # arbitrary file off the container.
    if "/" in filename or "\\" in filename or not filename.startswith(f"{DB_PATH.stem}.corrupt-"):
        raise HTTPException(status_code=400, detail="not a recognized backup filename")
    path = DB_PATH.parent / filename
    if path.resolve().parent != DB_PATH.parent.resolve() or not path.exists():
        raise HTTPException(status_code=404, detail="backup file not found")
    return path


@router.get("/list")
def list_backups(_: None = Depends(_require_secret)):
    files = sorted(DB_PATH.parent.glob(f"{DB_PATH.stem}.corrupt-*{DB_PATH.suffix}"))
    return [
        {"filename": f.name, "size_bytes": f.stat().st_size, "mtime": f.stat().st_mtime}
        for f in files
    ]


def _repair_copy(src: Path) -> tuple[Path, bool]:
    """Copy src, delete duplicate sqlite_master catalog rows on the copy, and
    return (repaired copy's path, integrity_ok). Never touches src itself.

    Some backups have deeper damage than the one known corruption shape (a
    few had raw btree page errors on top of it — likely from write attempts
    that landed after the catalog duplicate but before the app crashed).
    integrity_ok reflects that, but callers should still attempt to read
    `users` directly: it's a tiny table created early, almost always on
    completely different pages than whatever else is damaged."""
    fd, tmp_name = tempfile.mkstemp(suffix=".db")
    import os
    os.close(fd)
    tmp = Path(tmp_name)
    shutil.copy2(src, tmp)

    conn = sqlite3.connect(tmp)
    try:
        conn.execute("PRAGMA writable_schema=ON")
        dup_names = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master GROUP BY type, name HAVING COUNT(*) > 1"
            ).fetchall()
        ]
        for name in dup_names:
            rowids = [
                r[0] for r in conn.execute(
                    "SELECT rowid FROM sqlite_master WHERE name = ?", (name,)
                ).fetchall()
            ]
            for rowid in rowids[1:]:  # keep the first, drop the rest
                conn.execute("DELETE FROM sqlite_master WHERE rowid = ?", (rowid,))
        conn.commit()
        conn.execute("PRAGMA writable_schema=OFF")
    finally:
        conn.close()

    check_conn = sqlite3.connect(tmp)
    result = check_conn.execute("PRAGMA integrity_check").fetchall()
    check_conn.close()
    return tmp, _integrity_ok(result)


def _integrity_ok(integrity_check_rows: list[tuple]) -> bool:
    return integrity_check_rows == [("ok",)]


def _read_users(path: Path) -> list[tuple]:
    """Best-effort: pull whatever users rows are readable off a repaired
    copy, even if integrity_check flagged unrelated damage elsewhere in the
    file. Raises sqlite3.DatabaseError if the users table itself is what's
    actually broken — that's the real "nothing recoverable here" case."""
    conn = sqlite3.connect(path)
    try:
        return conn.execute(
            "SELECT user_id, email, name, hashed_pw, created_at FROM users"
        ).fetchall()
    finally:
        conn.close()


@router.post("/inspect")
def inspect_backup(filename: str, _: None = Depends(_require_secret)):
    """Dry run: repair a copy, report what's recoverable, touch nothing live."""
    src = _resolve_backup(filename)
    repaired, integrity_ok = _repair_copy(src)
    try:
        try:
            backup_users = _read_users(repaired)
        except sqlite3.DatabaseError as exc:
            return {"filename": filename, "integrity_ok": integrity_ok,
                    "users_readable": False, "error": str(exc)}
        with get_connection() as live:
            live_emails = {r["email"] for r in live.execute("SELECT email FROM users").fetchall()}
        backup_emails = {row[1] for row in backup_users}
        return {
            "filename": filename,
            "integrity_ok": integrity_ok,
            "users_readable": True,
            "users_in_backup": len(backup_emails),
            "already_in_live_db": len(backup_emails & live_emails),
            "recoverable_new_accounts": len(backup_emails - live_emails),
        }
    finally:
        repaired.unlink(missing_ok=True)


def _surrogate_pk_column(conn: sqlite3.Connection, table: str) -> str | None:
    """The column name if `table` has a single-column INTEGER PRIMARY KEY
    (SQLite's rowid alias, almost always paired with AUTOINCREMENT) — else
    None. That id is meaningless outside its own database: two independently
    created dbs both auto-assign 1 to their first row, so copying it verbatim
    makes an unrelated live row with id=1 falsely "collide" with a backup row
    that isn't actually a duplicate, silently dropping real data. Real keys
    (users.user_id TEXT, etc.) aren't touched — only a single-column INTEGER
    PK is ever a bare auto-assigned surrogate in this schema."""
    pk_cols = [
        (r[1], r[2]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall() if r[5] > 0
    ]
    if len(pk_cols) == 1 and pk_cols[0][1].upper() == "INTEGER":
        return pk_cols[0][0]
    return None


def _vec_table_prefixes(conn: sqlite3.Connection) -> list[str]:
    """Base names of any sqlite-vec virtual tables (vec0) — their shadow
    tables share internal binary state that a naive per-table copy would
    leave inconsistent. Embeddings are derived data (regenerable by
    reprocessing documents), so recover-all skips anything under these
    names rather than risk corrupting the live vector index."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE sql LIKE '%USING vec0%'"
    ).fetchall()
    return [r[0] for r in rows]


def _ensure_recovery_log(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS _recovery_log ("
        "filename TEXT NOT NULL, table_name TEXT NOT NULL, "
        "recovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "PRIMARY KEY (filename, table_name))"
    )


@router.post("/recover-all")
def recover_all(filename: str, _: None = Depends(_require_secret)):
    """Repair a copy and merge every real table's rows into the live db —
    chats, projects, feeds, bookmarks, everything, not just accounts. Uses
    INSERT OR IGNORE per table (never overwrites an existing live row) via
    ATTACH DATABASE, so SQLite does the row copying natively instead of a
    Python round-trip per row. Foreign keys are off for the duration since
    table order isn't dependency-sorted; restored afterward. sqlite-vec
    tables are skipped — see _vec_table_prefixes.

    Idempotent per (filename, table) via _recovery_log: INSERT OR IGNORE
    only actually dedupes tables that have their own unique constraint
    (email, topic, ...) — plain history tables like chat_messages have none,
    so a second run on the same file would blindly re-insert every row a
    second time. _recovery_log makes a repeat call on an already-recovered
    file a no-op instead."""
    src = _resolve_backup(filename)
    repaired, integrity_ok = _repair_copy(src)
    results: dict[str, dict] = {}
    try:
        with get_connection() as live:
            _ensure_recovery_log(live)
            already_done = {
                r[0] for r in live.execute(
                    "SELECT table_name FROM _recovery_log WHERE filename = ?", (filename,)
                ).fetchall()
            }
            vec_prefixes = _vec_table_prefixes(live)
            live.execute("PRAGMA foreign_keys=OFF")
            live.execute("ATTACH DATABASE ? AS backup", (str(repaired),))
            try:
                tables = [
                    r[0] for r in live.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    ).fetchall()
                ]
                for table in tables:
                    if any(table.startswith(p) for p in vec_prefixes):
                        results[table] = {"status": "skipped_vec_table"}
                        continue
                    if table == "_recovery_log":
                        continue
                    if table in already_done:
                        results[table] = {"status": "already_recovered_from_this_file"}
                        continue
                    try:
                        backup_cols = [
                            r[1] for r in live.execute(f"PRAGMA backup.table_info({table})").fetchall()
                        ]
                        if not backup_cols:
                            results[table] = {"status": "not_in_backup"}
                            live.execute(
                                "INSERT INTO _recovery_log (filename, table_name) VALUES (?, ?)",
                                (filename, table),
                            )
                            continue
                        live_cols = [r[1] for r in live.execute(f"PRAGMA table_info({table})").fetchall()]
                        common = [c for c in live_cols if c in backup_cols]
                        surrogate = _surrogate_pk_column(live, table)
                        if surrogate in common:
                            common.remove(surrogate)  # let SQLite assign a fresh id
                        col_list = ", ".join(f'"{c}"' for c in common)
                        cur = live.execute(
                            f'INSERT OR IGNORE INTO main."{table}" ({col_list}) '
                            f'SELECT {col_list} FROM backup."{table}"'
                        )
                        results[table] = {"status": "ok", "rows_inserted": cur.rowcount}
                        live.execute(
                            "INSERT INTO _recovery_log (filename, table_name) VALUES (?, ?)",
                            (filename, table),
                        )
                    except sqlite3.DatabaseError as exc:
                        results[table] = {"status": "error", "detail": str(exc)}
            finally:
                live.commit()  # DETACH requires no open transaction on the attached db
                live.execute("DETACH DATABASE backup")
                live.execute("PRAGMA foreign_keys=ON")
        return {"filename": filename, "integrity_ok": integrity_ok, "tables": results}
    finally:
        repaired.unlink(missing_ok=True)


@router.post("/dedupe-recent")
def dedupe_recent(filename: str, _: None = Depends(_require_secret)):
    """One-time fix for calling recover_all twice on the same file before
    _recovery_log existed: tables with no natural unique constraint (plain
    history tables — chat_messages, api_usage_log, ...) got every row
    inserted a second time. For each table this backup covers, the correct
    live row count is exactly the backup's own row count (these tables were
    fully empty before recovery started) — deletes the highest-rowid excess
    down to that count, and backfills _recovery_log so recover_all won't
    re-duplicate this file again."""
    src = _resolve_backup(filename)
    repaired, integrity_ok = _repair_copy(src)
    results: dict[str, dict] = {}
    try:
        backup_conn = sqlite3.connect(repaired)
        vec_prefixes = _vec_table_prefixes(backup_conn)
        backup_tables = [
            r[0] for r in backup_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        backup_counts = {}
        for t in backup_tables:
            if any(t.startswith(p) for p in vec_prefixes) or t == "_recovery_log":
                continue
            try:
                backup_counts[t] = backup_conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            except sqlite3.DatabaseError:
                pass
        backup_conn.close()

        with get_connection() as live:
            _ensure_recovery_log(live)
            for table, backup_count in backup_counts.items():
                try:
                    live_count = live.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                except sqlite3.DatabaseError:
                    continue
                excess = live_count - backup_count
                if excess > 0:
                    live.execute(
                        f'DELETE FROM "{table}" WHERE rowid IN '
                        f'(SELECT rowid FROM "{table}" ORDER BY rowid DESC LIMIT ?)',
                        (excess,),
                    )
                    results[table] = {"deleted": excess, "live_count_after": backup_count}
                live.execute(
                    "INSERT OR IGNORE INTO _recovery_log (filename, table_name) VALUES (?, ?)",
                    (filename, table),
                )
        return {"filename": filename, "results": results}
    finally:
        repaired.unlink(missing_ok=True)


@router.post("/recover-users")
def recover_users(filename: str, _: None = Depends(_require_secret)):
    """Repair a copy and merge missing accounts into the live db. Uses
    INSERT OR IGNORE keyed on users' PRIMARY KEY/UNIQUE constraints (user_id,
    email) — never overwrites an existing row, so newer live accounts created
    since the backup are untouched."""
    src = _resolve_backup(filename)
    repaired, integrity_ok = _repair_copy(src)
    try:
        try:
            rows = _read_users(repaired)
        except sqlite3.DatabaseError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"users table unreadable in this backup even after repair: {exc}",
            )

        inserted = 0
        with get_connection() as live:
            for row in rows:
                cur = live.execute(
                    "INSERT OR IGNORE INTO users (user_id, email, name, hashed_pw, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    row,
                )
                inserted += cur.rowcount
        return {"filename": filename, "integrity_ok": integrity_ok,
                "rows_in_backup": len(rows), "rows_inserted": inserted}
    finally:
        repaired.unlink(missing_ok=True)
