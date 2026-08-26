"""
Reproduces the exact HF Spaces failure: a persistent SQLite file whose
sqlite_master has a duplicate index entry, which makes every connection fail
with "malformed database schema" at the very first PRAGMA. get_connection()
must quarantine the broken file and transparently rebuild a fresh one.
"""
import multiprocessing
import os
import sqlite3
import threading

import pytest

import backend.utils.db as db


def _corrupt_db_with_duplicate_index(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.execute("CREATE INDEX idx_t ON t (id)")
    # writable_schema bypasses SQLite's own duplicate-name guard so we can
    # manufacture the same catalog corruption seen in production.
    conn.execute("PRAGMA writable_schema=ON")
    conn.execute(
        "INSERT INTO sqlite_master (type, name, tbl_name, rootpage, sql) "
        "SELECT type, name, tbl_name, rootpage, sql FROM sqlite_master WHERE name='idx_t'"
    )
    conn.commit()
    conn.execute("PRAGMA writable_schema=OFF")
    conn.close()


def test_get_connection_quarantines_and_rebuilds(tmp_path, monkeypatch):
    db_path = tmp_path / "curivio.db"
    _corrupt_db_with_duplicate_index(db_path)

    # Confirm the file is actually broken the way production was.
    broken = sqlite3.connect(db_path)
    try:
        broken.execute("PRAGMA journal_mode=WAL")
        assert False, "fixture did not reproduce the malformed-schema corruption"
    except sqlite3.DatabaseError as exc:
        assert "malformed database schema" in str(exc).lower()
    finally:
        broken.close()

    monkeypatch.setattr(db, "DB_PATH", db_path)

    with db.get_connection() as conn:
        conn.execute("SELECT 1")

    quarantined = list(tmp_path.glob("curivio.corrupt-*.db"))
    assert len(quarantined) == 1
    assert db_path.exists()  # fresh file rebuilt in its place


def test_concurrent_requests_dont_stomp_each_others_rebuild(tmp_path, monkeypatch):
    """
    Reproduces the prod regression: FastAPI runs sync deps in a threadpool
    even under --workers 1, so several requests hit the corrupted db at once.
    Without the recovery lock, each thread quarantined independently and the
    last one to finish left a fresh-but-empty db mid-rebuild ("no such table:
    users") behind two-plus orphaned .corrupt- files instead of one.
    """
    db_path = tmp_path / "curivio.db"
    _corrupt_db_with_duplicate_index(db_path)
    monkeypatch.setattr(db, "DB_PATH", db_path)

    barrier = threading.Barrier(8)
    errors = []

    def worker():
        try:
            barrier.wait(timeout=5)
            with db.get_connection() as conn:
                conn.execute("SELECT COUNT(*) FROM users")
        except Exception as exc:  # noqa: BLE001 - collecting for the assert below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert errors == []
    assert len(list(tmp_path.glob("curivio.corrupt-*.db"))) == 1


@pytest.mark.skipif(os.name != "posix", reason="flock is POSIX-only; protects the Docker/Linux deploy target")
def test_cross_process_recovery_is_mutually_exclusive(tmp_path, monkeypatch):
    """
    The threading.Lock above only serializes threads in one process. Prod was
    hit by a second *process* (an old container still shutting down, or a
    stuck restart loop) racing the same rebuild — that needs an OS-level
    lock, which only a real multi-process test can exercise.
    """
    db_path = tmp_path / "curivio.db"
    _corrupt_db_with_duplicate_index(db_path)
    monkeypatch.setattr(db, "DB_PATH", db_path)

    def _worker(q):
        try:
            with db.get_connection() as conn:
                conn.execute("SELECT COUNT(*) FROM users")
            q.put("ok")
        except Exception as exc:  # noqa: BLE001 - collecting for the assert below
            q.put(f"error: {exc}")

    ctx = multiprocessing.get_context("fork")  # fork inherits the monkeypatched DB_PATH directly
    q = ctx.Queue()
    procs = [ctx.Process(target=_worker, args=(q,)) for _ in range(4)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=15)

    results = [q.get(timeout=5) for _ in procs]
    assert results == ["ok"] * len(procs)
    assert len(list(tmp_path.glob("curivio.corrupt-*.db"))) == 1


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "curivio.db"
        _corrupt_db_with_duplicate_index(p)
        with patch.object(db, "DB_PATH", p):
            with db.get_connection() as conn:
                conn.execute("SELECT 1")
            assert list(Path(tmp).glob("curivio.corrupt-*.db")), "quarantine file missing"
    print("ok")
