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
