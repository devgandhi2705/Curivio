"""
Reproduces the exact HF Spaces failure: a persistent SQLite file whose
sqlite_master has a duplicate index entry, which makes every connection fail
with "malformed database schema" at the very first PRAGMA. get_connection()
must quarantine the broken file and transparently rebuild a fresh one.
"""
import sqlite3

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
