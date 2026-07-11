"""
Shared pytest fixtures for all test modules.
"""

import sqlite3

import pytest
import sqlite_vec

# Test fixtures across the suite create raw sqlite3.connect(":memory:") connections
# and replay ALL_TABLES directly, bypassing backend.utils.db.get_connection() (which
# always loads the sqlite_vec extension per-connection). Since ALL_TABLES now includes
# a CREATE VIRTUAL TABLE ... USING vec0 statement (Chat-3), any raw connection that
# skips loading the extension fails with "no such module: vec0". Patching
# sqlite3.connect here — once — makes every test connection match real production
# connections instead of updating the same fixture in 17 separate test files.
_real_connect = sqlite3.connect


def _connect_with_vec(*args, **kwargs):
    conn = _real_connect(*args, **kwargs)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


sqlite3.connect = _connect_with_vec


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """
    Clear slowapi's in-memory rate-limit counters before every test so that
    tests cannot hit limits set for production (e.g. 10/minute).
    """
    from backend.main import limiter
    limiter._storage.reset()
    yield
