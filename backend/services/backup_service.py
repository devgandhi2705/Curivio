"""
Automatic snapshots + admin-driven restore.

Why this exists: the live DB lives on HF Spaces' network-backed /data volume,
which is what corrupted sqlite_master badly enough that backend/utils/db.py had
to quarantine the file and rebuild empty. That self-heal keeps the app UP but
loses everything until someone manually merges a quarantined file back in.
This module makes the recovery path routine instead of an incident:

  * a snapshot is taken on startup (before migrations touch anything) and on a
    fixed interval while the process runs
  * an admin can merge any snapshot back into the live DB, whole or scoped to
    one user, from the Admin panel

Snapshots use sqlite3's native online-backup API, NOT a file copy: it is
transactionally consistent against concurrent writers, where shutil.copy2 of a
live SQLite file can capture a torn page mid-write.

Restore is MERGE-ONLY (INSERT OR IGNORE), never overwrite and never truncate.
A restore can therefore only ever add rows back — it cannot destroy newer live
data, which is the property that makes it safe to expose in a UI at all.

Schema drift across phases is handled by intersecting columns per table at
restore time (see _merge_table), so an old snapshot restores cleanly into a
newer schema: columns added since the snapshot take their DEFAULT, columns
dropped since are ignored. No per-version migration code to maintain.

Local snapshots alone don't survive losing the /data volume itself (storage
issue, quota, Space rebuild) — they're on the same volume as the live db.
Every successful snapshot is also pushed to a private HF Hub dataset repo via
backup_remote_service (see its module docstring), which is where real
retention lives; local BACKUP_DIR keeps only a couple of recent copies for a
fast restore path when the volume is healthy.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import backup_remote_service
from ..utils.db import DB_PATH, get_connection

logger = logging.getLogger(__name__)

BACKUP_DIR = DB_PATH.parent / "backups"
_PREFIX = f"{DB_PATH.stem}-"
_SUFFIX = DB_PATH.suffix or ".db"

# Local retention is small on purpose — it's a fast path, not the safety net.
# The real retention window lives in the remote mirror (backup_remote_service),
# which isn't constrained by the Space's own disk budget the way /data is.
LOCAL_MAX_SNAPSHOTS = int(os.getenv("BACKUP_LOCAL_MAX_SNAPSHOTS", "2"))
REMOTE_MAX_SNAPSHOTS = int(os.getenv("BACKUP_REMOTE_MAX_SNAPSHOTS", "20"))
INTERVAL_SECONDS = int(os.getenv("BACKUP_INTERVAL_SECONDS", str(2 * 24 * 3600)))

# Floor under the boot-time premigration snapshot (and the scheduler, though
# that one is already time-driven and rarely bumps into this). A Space that
# restarts often — HF Spaces free-tier sleep/wake, or a burst of redeploys —
# would otherwise take a near-duplicate snapshot on every single boot: each
# one a real local write and a real remote push for zero new data.
MIN_GAP_SECONDS = int(os.getenv("BACKUP_MIN_GAP_SECONDS", str(3600)))

# Unlike snapshots, quarantined files (db.py's corruption self-heal artifact)
# were never bounded at all — left alone they accumulate on the same tight
# local disk budget forever. One is enough: it's a stopgap for an immediate
# recovery, not the durable backup (that's the remote mirror now).
QUARANTINE_MAX_FILES = int(os.getenv("BACKUP_QUARANTINE_MAX_FILES", "1"))


def _user_count(path: Path) -> int | None:
    """Number of accounts in a database file, or None if it can't be read."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return None


def _looks_like_a_wipe() -> str | None:
    """Reason to refuse a snapshot, or None if it's safe to take one.

    The failure mode this guards against is specific and has already happened
    once: db.py's corruption self-heal quarantines the DB and rebuilds it EMPTY,
    the app keeps serving, and nobody notices for hours. Left unguarded, the
    interval scheduler would happily take LOCAL_MAX_SNAPSHOTS worth of snapshots of
    that empty DB and evict every real one — turning a recoverable incident into
    permanent loss. Comparing account counts against the newest existing
    snapshot catches it precisely; comparing file sizes would not, since SQLite
    does not shrink a file when rows are deleted."""
    snaps = sorted(BACKUP_DIR.glob(f"{_PREFIX}*{_SUFFIX}")) if BACKUP_DIR.exists() else []
    if not snaps:
        return None                      # nothing to compare against yet
    live_users = _user_count(DB_PATH)
    if live_users is None:
        return "live database is unreadable"
    prev_users = _user_count(snaps[-1])
    if prev_users is None:
        return None
    if live_users == 0 and prev_users > 0:
        return (f"live db has 0 accounts but the last snapshot has {prev_users} — "
                f"this looks like a corruption rebuild, refusing to snapshot over it")
    return None


def _too_soon_since_last_snapshot() -> str | None:
    """Reason to skip an automatic snapshot, or None if enough time has
    passed since the newest existing one. See MIN_GAP_SECONDS."""
    snaps = sorted(BACKUP_DIR.glob(f"{_PREFIX}*{_SUFFIX}")) if BACKUP_DIR.exists() else []
    if not snaps:
        return None
    age = time.time() - snaps[-1].stat().st_mtime
    if age < MIN_GAP_SECONDS:
        return f"a snapshot was taken {int(age)}s ago, under the {MIN_GAP_SECONDS}s minimum gap"
    return None


# ── snapshot creation ────────────────────────────────────────────────────────

def _snapshot_name(label: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    safe = "".join(c for c in label if c.isalnum() or c in "-_")[:24] or "auto"
    return f"{_PREFIX}{stamp}-{safe}{_SUFFIX}"


def push_remote_snapshot(dest: Path) -> dict:
    """Upload one local snapshot to the remote mirror and prune old remote
    copies. Never raises: both create_snapshot (synchronously) and main.py's
    boot path (in a background thread, so a slow/failed push can't add to
    startup latency) need this to fail loudly in the logs but never break
    their caller."""
    try:
        backup_remote_service.upload_snapshot(dest)
        backup_remote_service.prune_remote(REMOTE_MAX_SNAPSHOTS)
        return {"remote_ok": True}
    except Exception as exc:
        logger.error("[backup] remote push failed for %s: %s", dest.name, exc, exc_info=True)
        return {"remote_ok": False, "remote_error": str(exc)}


def create_snapshot(label: str = "auto", force: bool = False, push_remote: bool = True) -> dict:
    """Take one consistent snapshot of the live DB. Returns a status dict
    rather than raising: this runs from a background thread and from startup,
    where a failed backup must never take the app down with it.

    push_remote=False skips the remote mirror entirely — used only by the
    boot-time premigration snapshot, which pushes remotely itself afterward
    in a background thread (see main.py) so a network hiccup can't delay the
    migrations that must run right after this returns."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    if not DB_PATH.exists():
        return {"ok": False, "reason": "no live database yet"}

    if not force:
        refusal = _looks_like_a_wipe()
        if refusal:
            logger.error("[backup] refusing automatic snapshot: %s", refusal)
            return {"ok": False, "reason": refusal}
        too_soon = _too_soon_since_last_snapshot()
        if too_soon:
            logger.info("[backup] skipping automatic snapshot: %s", too_soon)
            return {"ok": False, "reason": too_soon}

    dest = BACKUP_DIR / _snapshot_name(label)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    src = dst = None
    try:
        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(tmp)
        src.backup(dst)          # native online backup — consistent under writers
        dst.close()
        src.close()
        src = dst = None
        tmp.replace(dest)        # atomic publish: readers never see a partial file
    except Exception as exc:
        for c in (src, dst):
            try:
                if c is not None:
                    c.close()
            except Exception:
                pass
        tmp.unlink(missing_ok=True)
        logger.error("[backup] snapshot failed: %s", exc, exc_info=True)
        return {"ok": False, "reason": str(exc)}

    pruned = _prune()
    _prune_quarantined()
    logger.info("[backup] snapshot %s (%d bytes), pruned %d old", dest.name,
                dest.stat().st_size, len(pruned))
    result = {"ok": True, "filename": dest.name, "size_bytes": dest.stat().st_size,
              "pruned": pruned}
    if push_remote:
        result.update(push_remote_snapshot(dest))
    return result


def _prune() -> list[str]:
    """Drop the oldest snapshots beyond LOCAL_MAX_SNAPSHOTS. Sorted by filename,
    which is chronological by construction (UTC timestamp is the first field)."""
    files = sorted(BACKUP_DIR.glob(f"{_PREFIX}*{_SUFFIX}"))
    removed = []
    for old in files[:-LOCAL_MAX_SNAPSHOTS] if len(files) > LOCAL_MAX_SNAPSHOTS else []:
        try:
            old.unlink()
            removed.append(old.name)
        except OSError:
            logger.warning("[backup] could not prune %s", old, exc_info=True)
    return removed


def _prune_quarantined() -> list[str]:
    """Drop quarantined files beyond QUARANTINE_MAX_FILES. Sorted by filename,
    which sorts chronologically here too (the epoch suffix db.py writes is a
    fixed-width-enough decimal timestamp). Called alongside _prune() so this
    doesn't need its own schedule — a corruption event is rare enough that
    piggybacking on the regular snapshot cadence cleans it up promptly."""
    files = sorted(DB_PATH.parent.glob(f"{DB_PATH.stem}.corrupt-*{_SUFFIX}"))
    removed = []
    for old in files[:-QUARANTINE_MAX_FILES] if len(files) > QUARANTINE_MAX_FILES else []:
        try:
            old.unlink()
            removed.append(old.name)
        except OSError:
            logger.warning("[backup] could not prune quarantined %s", old, exc_info=True)
    return removed


def _mtime_from_snapshot_name(filename: str) -> float:
    """The UTC timestamp _snapshot_name() embeds, as a Unix epoch float — used
    for remote entries, which have no local filesystem mtime to read."""
    stamp = filename[len(_PREFIX):len(_PREFIX) + 15]  # YYYYMMDD-HHMMSS
    return datetime.strptime(stamp, "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc).timestamp()


def list_snapshots() -> list[dict]:
    """Snapshots newest-first: local snapshots, and remote-only entries
    (pushed to the mirror but no longer — or not yet — present locally, e.g.
    after local retention dropped them, or a full local volume loss). A
    filename present both locally and remotely is listed once, as local —
    it's directly usable with no download.

    Quarantined curivio.corrupt-* files are deliberately NOT listed here —
    they're a rare emergency-recovery artifact, not routine admin-panel
    inventory (see routes/db_recovery.py for that path). They're still fully
    restorable via resolve_source/restore for anyone who has the filename."""
    out = []
    local_names = set()
    if BACKUP_DIR.exists():
        for f in BACKUP_DIR.glob(f"{_PREFIX}*{_SUFFIX}"):
            st = f.stat()
            local_names.add(f.name)
            out.append({"filename": f.name, "kind": "snapshot",
                        "size_bytes": st.st_size, "mtime": st.st_mtime})
    try:
        for r in backup_remote_service.list_remote():
            if r["filename"] in local_names:
                continue
            out.append({"filename": r["filename"], "kind": "remote",
                        "size_bytes": r["size_bytes"],
                        "mtime": _mtime_from_snapshot_name(r["filename"])})
    except Exception:
        logger.warning("[backup] could not list remote snapshots", exc_info=True)
    return sorted(out, key=lambda r: r["mtime"], reverse=True)


def resolve_source(filename: str) -> Path:
    """Map a caller-supplied filename to a real restore source, or raise
    ValueError. Rejects anything that isn't a plain basename matching one of the
    two naming schemes we write ourselves, so this can never be turned into an
    arbitrary-file read off the container.

    A snapshot-scheme name is NOT required to exist locally — it may only live
    in the remote mirror (local retention is small, or local was wiped). This
    is a fast, local-only path-safety check; _prepare_source is what actually
    fetches the file, from wherever it lives. A quarantined-file name has no
    remote counterpart (see backup_remote_service — quarantine artifacts are
    never pushed), so it must exist locally or there's nothing to recover."""
    if "/" in filename or "\\" in filename or filename in ("", ".", ".."):
        raise ValueError("not a recognized backup filename")
    if filename.startswith(_PREFIX):
        path = BACKUP_DIR / filename
        root = BACKUP_DIR
        require_local = False
    elif filename.startswith(f"{DB_PATH.stem}.corrupt-"):
        path = DB_PATH.parent / filename
        root = DB_PATH.parent
        require_local = True
    else:
        raise ValueError("not a recognized backup filename")
    if path.resolve().parent != root.resolve():
        raise ValueError("backup file not found")
    if require_local and not path.exists():
        raise ValueError("backup file not found")
    return path


# ── shared table introspection (also used by routes/db_recovery.py) ──────────

def surrogate_pk_column(conn: sqlite3.Connection, table: str) -> str | None:
    """The column name if `table` has a single-column INTEGER PRIMARY KEY
    (SQLite's rowid alias, almost always AUTOINCREMENT) — else None. That id is
    meaningless outside its own database: two independently created DBs both
    auto-assign 1 to their first row, so copying it verbatim makes an unrelated
    live row falsely "collide" with a snapshot row that isn't a duplicate,
    silently dropping real data. Real keys (users.user_id TEXT, ...) are never
    touched — only a single-column INTEGER PK is ever a bare surrogate here."""
    pk_cols = [
        (r[1], r[2]) for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall() if r[5] > 0
    ]
    if len(pk_cols) == 1 and pk_cols[0][1].upper() == "INTEGER":
        return pk_cols[0][0]
    return None


def linkable_pk_column(conn: sqlite3.Connection, table: str) -> str | None:
    """The primary key of `table` if it is safe to use as a join key for
    deriving ownership, else None. Two conditions, both load-bearing:

      1. a single-column, NON-integer PK — an INTEGER pk is a per-database
         auto-assigned surrogate (see surrogate_pk_column), so joining on it
         would match completely unrelated rows across two databases;
      2. named `<something>_id`, never a bare `id`.

    Condition 2 exists because article_provenance really does declare
    `id TEXT PRIMARY KEY`. Without the check it qualifies as a parent, and then
    every one of the dozen-odd tables that has an `id` column (project_insights,
    retrieval_metrics, api_usage_log, ... all `id INTEGER PRIMARY KEY`) links to
    it — silently scoping an autoincrement integer against a TEXT uuid and
    pulling in a nonsense row set. Every genuine cross-table key in this schema
    (session_id, project_id, collection_id, user_id, ...) follows the `_id`
    convention, so requiring it costs nothing and closes the hole.
    """
    pk_cols = [
        (r[1], r[2]) for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall() if r[5] > 0
    ]
    if len(pk_cols) != 1:
        return None
    name, decltype = pk_cols[0]
    if decltype.upper() == "INTEGER" or not name.endswith("_id") or name == "_id":
        return None
    return name


def vec_table_prefixes(conn: sqlite3.Connection) -> list[str]:
    """Base names of any sqlite-vec (vec0) virtual tables. Their shadow tables
    share packed internal binary state that a naive per-table row copy would
    leave inconsistent. Embeddings are derived data — regenerable by
    reprocessing the source documents — so restore skips them rather than risk
    corrupting the live vector index to recover something reproducible."""
    return [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE sql LIKE '%USING vec0%'"
        ).fetchall()
    ]


# Never restored, at any scope. These hold short-lived authentication state, and
# putting an old row back is at best pointless and at worst a downgrade: a
# password-reset token or pending signup that was deleted because it had been
# CONSUMED would come back looking unused, and a stale lockout/cooldown row would
# re-apply a rate limit that has long since expired. None of it is user data —
# nobody is missing their reset tokens. Note revoked_tokens is deliberately NOT
# here: restoring a revocation blocklist fails safe (it only ever rejects more),
# and dropping it is what would be unsafe.
NEVER_RESTORE = frozenset({
    "password_reset_tokens",
    "pending_signups",
    "verification_lockouts",
    "resend_cooldowns",
    "restore_log",
    "_recovery_log",
})


def _real_tables(conn: sqlite3.Connection, schema: str = "main") -> list[str]:
    return [
        r[0] for r in conn.execute(
            f"SELECT name FROM {schema}.sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]


def _columns(conn: sqlite3.Connection, table: str, schema: str = "main") -> list[str]:
    return [r[1] for r in conn.execute(f'PRAGMA {schema}.table_info("{table}")').fetchall()]


# ── per-user scoping ─────────────────────────────────────────────────────────

def derive_user_scope(conn: sqlite3.Connection, schema: str = "main") -> dict[str, str]:
    """Work out, from the schema itself, which tables hold per-user rows and how
    to select just one user's.

    Returns {table: predicate}, where each predicate is a SQL fragment carrying
    exactly one `?` placeholder to be bound to a user_id.

    Derived, not hardcoded, because a hardcoded table list is exactly the thing
    that silently rots as new phases add tables — a table added next month and
    forgotten here would simply never be restored, and nobody would notice until
    a user reported it missing. Two rules, applied to a fixpoint:

      1. the table has its own `user_id` column           → user_id = ?
      2. the table carries a scoped parent's TEXT primary
         key as a column (chat_messages.session_id,
         project_insights.project_id, ...)                → col IN (SELECT ...)

    Rule 2 matches on column NAME rather than a declared FOREIGN KEY on purpose:
    chat_messages.session_id has no REFERENCES clause in this schema, so FK
    introspection would miss the single biggest user-owned table. Parents are
    restricted to single-column TEXT primary keys (see text_pk_column) —
    matching on an INTEGER `id` would join unrelated tables together.

    Tables matching neither rule are global/derived (feed_cache, search_cache,
    unpack_cache, article_provenance, ...) and are left out: they are shared
    infrastructure, not one user's data.
    """
    tables = _real_tables(conn, schema)
    cols = {t: _columns(conn, t, schema) for t in tables}

    scoped: dict[str, str] = {}
    for t in tables:
        if "user_id" in cols[t]:
            scoped[t] = '"user_id" = ?'
    # `users` itself keys on user_id as its PRIMARY KEY, which the rule above
    # already catches — it is listed here so a per-user restore also brings the
    # account row back, not just the data hanging off it.

    # Fixpoint so two-level chains resolve too (parent scoped on this pass
    # becomes a valid parent on the next). Bounded by table count; each pass
    # must scope at least one new table or we stop.
    changed = True
    while changed:
        changed = False
        parents = sorted(scoped)  # deterministic: same input schema, same links
        for t in tables:
            if t in scoped:
                continue
            for p in parents:
                pk = linkable_pk_column(conn, p)
                if not pk or pk not in cols[t]:
                    continue
                scoped[t] = (
                    f'"{pk}" IN (SELECT "{pk}" FROM {schema}."{p}" WHERE {scoped[p]})'
                )
                changed = True
                break
    return scoped


# ── repairing a quarantined source ───────────────────────────────────────────

def integrity_ok(integrity_check_rows: list[tuple]) -> bool:
    return integrity_check_rows == [("ok",)]


def repair_copy(src: Path) -> tuple[Path, bool]:
    """Copy `src`, drop duplicate sqlite_master catalog rows on the COPY, and
    return (copy path, integrity_ok). Never touches `src` itself.

    The quarantine corruption is always the same shape: a duplicate sqlite_master
    row for an index, which makes SQLite refuse to open the file at all even
    though every byte of table data is intact. Deleting the extra catalog row via
    writable_schema — SQLite's own supported mechanism for exactly this — makes
    the copy a fully valid database again.

    integrity_ok=False does not mean "give up": some files have real btree page
    damage on top of the catalog duplicate, yet the great majority of their
    tables still read perfectly. Callers should attempt the read and let
    individual tables fail.
    """
    import shutil
    import tempfile

    fd, tmp_name = tempfile.mkstemp(suffix=".db")
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
            for rowid in rowids[1:]:      # keep the first, drop the rest
                conn.execute("DELETE FROM sqlite_master WHERE rowid = ?", (rowid,))
        conn.commit()
        conn.execute("PRAGMA writable_schema=OFF")
    finally:
        conn.close()

    check = sqlite3.connect(tmp)
    result = check.execute("PRAGMA integrity_check").fetchall()
    check.close()
    return tmp, integrity_ok(result)


def _cleanup_temp(temp: Path) -> None:
    """Remove whatever _prepare_source handed back as its temp path — a bare
    file for a repaired quarantine copy, or a directory for a remote
    download (see _prepare_source's remote branch)."""
    if temp.is_dir():
        import shutil
        shutil.rmtree(temp, ignore_errors=True)
    else:
        temp.unlink(missing_ok=True)


def _prepare_source(src: Path) -> tuple[Path, bool, Path | None]:
    """Return (attachable path, integrity_ok, temp path/dir to clean up via
    _cleanup_temp, or None).

    A snapshot we wrote ourselves is already consistent — attach it directly
    rather than burning a full file copy on every restore. A quarantined file
    is corrupt by construction and must be repaired onto a temp copy first.
    A snapshot name resolve_source found but that isn't present locally (local
    retention dropped it, or the volume was wiped) is fetched from the remote
    mirror into a temp dir first — this is the one place in this module that
    does network I/O; every other reader of a resolved source stays local.
    """
    if src.name.startswith(f"{DB_PATH.stem}.corrupt-"):
        repaired, ok = repair_copy(src)
        return repaired, ok, repaired
    if not src.exists():
        import tempfile
        tmp_dir = Path(tempfile.mkdtemp(prefix=f"{DB_PATH.stem}-remote-"))
        try:
            downloaded = backup_remote_service.download_to(src.name, tmp_dir)
        except FileNotFoundError:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise ValueError("backup file not found") from None
        return downloaded, True, tmp_dir
    return src, True, None


def users_in_snapshot(filename: str) -> list[dict]:
    """Accounts a given snapshot holds, so a per-user restore can be picked from
    what the file actually contains rather than typed from memory. Repairs a
    copy first when the source is a quarantined file."""
    src = resolve_source(filename)
    attachable, ok, temp = _prepare_source(src)
    try:
        conn = sqlite3.connect(f"file:{attachable}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT user_id, email, name, created_at FROM users ORDER BY email"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        logger.warning("[backup] cannot read users from %s: %s", filename, exc)
        return []
    finally:
        if temp is not None:
            _cleanup_temp(temp)


# ── restore ──────────────────────────────────────────────────────────────────

def _has_unique_constraint(live: sqlite3.Connection, table: str) -> bool:
    """Whether `table` can dedupe itself. True if it has a non-surrogate PRIMARY
    KEY (users.user_id, chat_sessions.session_id, ...) or any UNIQUE index."""
    if linkable_pk_column(live, table):
        return True
    return any(r[2] for r in live.execute(f'PRAGMA index_list("{table}")').fetchall())


def _merge_table(live: sqlite3.Connection, table: str, user_id: str | None,
                 predicate: str | None) -> dict:
    """Copy one table's rows from the attached `backup` schema into `main`.

    Column intersection is what makes this survive schema drift: only columns
    present in BOTH the snapshot and the live table are copied, so a snapshot
    taken before a migration restores into the post-migration table with the new
    columns taking their DEFAULT, and a column dropped since the snapshot is
    simply not selected.

    Tables with no unique constraint of their own (chat_messages, api_usage_log,
    project_insights — everything keyed only by an AUTOINCREMENT id) get an
    explicit content anti-join, because INSERT OR IGNORE has nothing to ignore ON
    for them. Without it, restoring user u1 and then restoring the whole file
    inserts u1's rows a second time: the restore_log's per-scope key correctly
    lets the second call through (it still has u2 to recover), and nothing else
    would stop the overlap from doubling. That is the exact shape of the
    duplication incident this feature exists to prevent, so the guard lives in
    the copy itself rather than relying on the log alone.

    Uses IS, not =, to compare: SQLite's = is never true for NULL, and these
    tables are full of nullable columns, so = would treat every row with a NULL
    as new on every run.
    """
    backup_cols = _columns(live, table, "backup")
    if not backup_cols:
        return {"status": "not_in_snapshot"}

    live_cols = _columns(live, table, "main")
    common = [c for c in live_cols if c in backup_cols]
    surrogate = surrogate_pk_column(live, table)
    if surrogate in common:
        common.remove(surrogate)          # let SQLite assign a fresh id
    if not common:
        return {"status": "no_common_columns"}

    col_list = ", ".join(f'"{c}"' for c in common)
    conditions = []
    params: tuple = ()
    if user_id is not None:
        if not predicate:
            return {"status": "not_user_scoped"}
        conditions.append(predicate)
        params = (user_id,)

    if not _has_unique_constraint(live, table):
        # ponytail: correlated NOT EXISTS, no index — fine at this DB's scale
        # (largest table is a few hundred rows). If a table ever grows past
        # ~100k rows, give it a real UNIQUE constraint instead of widening this.
        match = " AND ".join(f'm."{c}" IS b."{c}"' for c in common)
        conditions.append(f'NOT EXISTS (SELECT 1 FROM main."{table}" AS m WHERE {match})')

    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    cur = live.execute(
        f'INSERT OR IGNORE INTO main."{table}" ({col_list}) '
        f'SELECT {col_list} FROM backup."{table}" AS b{where}',
        params,
    )
    return {"status": "ok", "rows_inserted": cur.rowcount}


def _count_available(live: sqlite3.Connection, table: str, user_id: str | None,
                     backup_predicate: str | None, main_predicate: str | None) -> dict:
    """Dry-run counterpart to _merge_table: how many rows this table WOULD
    contribute, without writing anything.

    Takes the backup-schema and main-schema predicates separately — they are NOT
    interchangeable. A scoped predicate like `session_id IN (SELECT ... FROM
    chat_sessions ...)` must resolve its subquery against the same database it
    is counting, or the live count silently reports "live rows whose session
    exists in the snapshot" instead of "live rows this user has".
    """
    if not _columns(live, table, "backup"):
        return {"status": "not_in_snapshot"}
    sql = f'SELECT COUNT(*) FROM backup."{table}"'
    params: tuple = ()
    if user_id is not None:
        if not backup_predicate:
            return {"status": "not_user_scoped"}
        sql += f" WHERE {backup_predicate}"
        params = (user_id,)
    in_snapshot = live.execute(sql, params).fetchone()[0]

    live_sql = f'SELECT COUNT(*) FROM main."{table}"'
    if user_id is not None:
        if not main_predicate:
            return {"status": "not_user_scoped"}
        live_sql += f" WHERE {main_predicate}"
    live_count = live.execute(live_sql, params).fetchone()[0]

    out = {"status": "ok", "in_snapshot": in_snapshot, "in_live_db": live_count}

    # Rows in the snapshot that no per-user restore can ever claim, because
    # nothing attributes them to anyone. Real and worth surfacing: user_id was
    # added to several tables by a later migration as a NULLABLE column, so rows
    # written before that migration carry NULL. Without this an admin sees
    # "restored 12 of 12" and assumes complete, when a full restore would have
    # brought back 400 more.
    if user_id is not None and "user_id" in _columns(live, table, "backup"):
        out["unattributed_in_snapshot"] = live.execute(
            f'SELECT COUNT(*) FROM backup."{table}" WHERE "user_id" IS NULL'
        ).fetchone()[0]
    return out


def restore(filename: str, user_id: str | None = None, dry_run: bool = False) -> dict:
    """Merge a snapshot into the live DB — everything, or one user's rows.

    Never overwrites and never deletes: INSERT OR IGNORE only. Idempotent per
    (filename, table, scope) via the restore_log table, because INSERT OR IGNORE
    alone cannot dedupe tables that have no UNIQUE constraint of their own —
    chat_messages and api_usage_log have none, so without the log a second
    restore of the same file would blindly re-insert every row again.

    dry_run reports what WOULD be restored and writes nothing, so an admin can
    look before committing.
    """
    src = resolve_source(filename)
    scope = user_id or "*"
    tables: dict[str, dict] = {}

    # A quarantined file is corrupt by definition — SQLite refuses to ATTACH it
    # at all. Repair a COPY (never the original, which stays as the last-resort
    # source of truth) before reading anything out of it.
    attachable, integrity_ok, temp = _prepare_source(src)

    try:
        with get_connection() as live:
            vec_prefixes = vec_table_prefixes(live)
            already = {
                r[0] for r in live.execute(
                    "SELECT table_name FROM restore_log WHERE filename = ? AND scope = ?",
                    (filename, scope),
                ).fetchall()
            }

            # Table order here is alphabetical, not dependency-sorted, so a child
            # can land before its parent. FKs off for the duration; restored in
            # the finally below so a mid-restore error can't leave them off.
            live.execute("PRAGMA foreign_keys=OFF")
            # `backup` is attached read-write only because sqlite3's ATTACH
            # cannot take a mode=ro URI on a non-URI connection. Every statement
            # issued against it below MUST stay a pure SELECT — these files are
            # the last-resort copy of the user's data, and a stray write here
            # would corrupt the thing we are recovering from.
            live.execute("ATTACH DATABASE ? AS backup", (str(attachable),))
            try:
                backup_preds = derive_user_scope(live, "backup") if user_id else {}
                main_preds = derive_user_scope(live, "main") if user_id else {}
                for table in _real_tables(live, "main"):
                    if any(table.startswith(p) for p in vec_prefixes):
                        tables[table] = {"status": "skipped_vec_table"}
                        continue
                    if table in NEVER_RESTORE:
                        continue
                    if table in already and not dry_run:
                        tables[table] = {"status": "already_restored"}
                        continue
                    bp, mp = backup_preds.get(table), main_preds.get(table)
                    try:
                        if dry_run:
                            row = _count_available(live, table, user_id, bp, mp)
                            if table in already:
                                row["already_restored"] = True
                            tables[table] = row
                        else:
                            result = _merge_table(live, table, user_id, bp)
                            tables[table] = result
                            if result["status"] in ("ok", "not_in_snapshot"):
                                live.execute(
                                    "INSERT OR IGNORE INTO restore_log "
                                    "(filename, table_name, scope, rows_inserted) VALUES (?,?,?,?)",
                                    (filename, table, scope, result.get("rows_inserted", 0)),
                                )
                    except sqlite3.DatabaseError as exc:
                        # One unreadable table (deeper page damage in a
                        # quarantined file) must not abort the other 40 that are
                        # perfectly readable.
                        tables[table] = {"status": "error", "detail": str(exc)}
            finally:
                live.commit()   # DETACH refuses while a transaction on `backup` is open
                live.execute("DETACH DATABASE backup")
                live.execute("PRAGMA foreign_keys=ON")
    finally:
        if temp is not None:
            _cleanup_temp(temp)

    return {
        "filename": filename,
        "scope": scope,
        "dry_run": dry_run,
        "integrity_ok": integrity_ok,
        "rows_restored": sum(t.get("rows_inserted", 0) for t in tables.values()),
        "rows_available": sum(t.get("in_snapshot", 0) for t in tables.values()),
        "tables": {k: v for k, v in sorted(tables.items())},
    }


# ── scheduler ────────────────────────────────────────────────────────────────

_scheduler_started = threading.Event()


def start_scheduler() -> None:
    """Snapshot once now, then every INTERVAL_SECONDS, on a daemon thread.

    The startup snapshot runs BEFORE this process's migrations have had any
    chance to modify data, which is what makes a bad migration recoverable
    rather than terminal — requirement (5). Idempotent: a second call is a
    no-op, so an autoreloading dev server doesn't stack threads."""
    if _scheduler_started.is_set():
        return
    _scheduler_started.set()

    def _loop():
        while True:
            # Sleep first: startup already took a "premigration" snapshot moments
            # ago (see main.py's lifespan), so snapshotting immediately here
            # would just duplicate it on every restart.
            time.sleep(INTERVAL_SECONDS)
            try:
                create_snapshot("auto")
            except Exception:
                logger.error("[backup] scheduled snapshot crashed", exc_info=True)

    threading.Thread(target=_loop, daemon=True, name="backup-scheduler").start()
    logger.info("[backup] scheduler started — every %ds, keeping %d local / %d remote snapshots in %s",
                INTERVAL_SECONDS, LOCAL_MAX_SNAPSHOTS, REMOTE_MAX_SNAPSHOTS, BACKUP_DIR)
