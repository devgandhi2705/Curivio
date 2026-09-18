"""
Feed v2 database connection factory.

Deliberately SEPARATE from backend/utils/db.py: v2 owns its own connection
entry point so the isolation boundary (tests/test_v2_isolation.py) holds —
feed_v2 must not import backend.services.* or backend.llm.*. It points at the
SAME curivio.db file, using the same DB_PATH env override as legacy, but the
connection logic is duplicated here on purpose, not imported.
"""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import sqlite_vec

# backend/services/feed_v2/db.py -> parents[3] is the project root (same
# curivio.db that backend/utils/db.py resolves to via its own parents[2]).
_db_path_env = os.getenv("DB_PATH", "")
DB_PATH = Path(_db_path_env) if _db_path_env else Path(__file__).resolve().parents[3] / "data" / "curivio.db"


# Rollback-journal writers queue behind each other; under concurrent feed_v2 runs + app
# traffic sqlite3's 5s default expired (measured 5.18s). A writer waits its turn instead.
_BUSY_TIMEOUT_S = 30.0


@contextmanager
def get_connection():
    """Yield a sqlite3 connection that auto-commits on success and rolls back on error.

    Mirrors backend/utils/db.py's get_connection (WAL, foreign keys, sqlite-vec)
    but is a standalone function — v2 does not import the legacy db module.
    """
    conn = sqlite3.connect(DB_PATH, timeout=_BUSY_TIMEOUT_S)
    try:
        conn.row_factory = sqlite3.Row
        # DELETE, not WAL: WAL needs a memory-mapped -shm file shared between
        # connections, which doesn't work on network-backed storage (HF Spaces'
        # persistent /data volume) and was corrupting curivio.db's schema catalog.
        # Matches backend/utils/db.py's get_connection — same shared file.
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except Exception:
        # A connection that failed its setup must not outlive this call: if the file is
        # in WAL, it stays attached and keeps every later journal_mode switch locked.
        conn.close()
        raise
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
