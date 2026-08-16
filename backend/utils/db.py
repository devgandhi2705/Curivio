"""
SQLite database utilities.

Usage:
    from backend.utils.db import get_connection, init_db
    from backend.utils.db import upsert_preference, get_preference, list_preferences, record_feedback
"""

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import sqlite_vec

logger = logging.getLogger(__name__)

from ..database.schema import ALL_TABLES, MIGRATIONS
# Feed v2 owns its DDL in feed_v2/schema.py (kept out of database/schema.py so the
# two feed generations never share table defs). It's a pure-SQL module — no
# backend.services/backend.llm imports — so pulling it in here creates no cycle.
from ..services.feed_v2.schema import run_v2_migrations

# DB_PATH is configurable via environment variable for deployment portability.
# HF Spaces: set DB_PATH=/data/curivio.db — /data is the only persistent volume.
# Default falls back to the project root data/ directory for local development.
_db_path_env = os.getenv("DB_PATH", "")
DB_PATH = Path(_db_path_env) if _db_path_env else Path(__file__).resolve().parents[2] / "data" / "curivio.db"


def init_db() -> None:
    """Create all tables and run additive migrations."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        for statement in ALL_TABLES:
            conn.execute(statement)
        # Migrations are additive-only. OperationalError with "already exists" /
        # "duplicate column" is expected on re-runs and silently skipped.
        # Any other error is loud: logged at ERROR with traceback and re-raised.
        # A migration may be a single SQL string or a list of strings that must
        # all execute together (used for table-recreation migrations).
        for migration in MIGRATIONS:
            try:
                if isinstance(migration, (list, tuple)):
                    for stmt in migration:
                        conn.execute(stmt)
                else:
                    conn.execute(migration)
            except sqlite3.OperationalError as exc:
                msg = str(exc).lower()
                # "already exists" / "duplicate column" → ADD already applied.
                # "no such column" → DROP on a column that was never added (fresh DB).
                # Both are expected idempotency outcomes; anything else is a real error.
                if any(p in msg for p in ("already exists", "duplicate column", "no such column")):
                    logger.debug("Migration skipped (already applied): %s", exc)
                else:
                    logger.error("Migration failed: %s", exc, exc_info=True)
                    raise
            except Exception:
                logger.error("Migration failed with unexpected error", exc_info=True)
                raise

        # Feed v2 tables (Phase 4 wire-in). Every statement is CREATE ... IF NOT
        # EXISTS, so this is idempotent on repeat startup — same "already exists"
        # guard as the legacy migrations above, reused not reinvented.
        try:
            run_v2_migrations(conn)
        except sqlite3.OperationalError as exc:
            if any(p in str(exc).lower() for p in ("already exists", "duplicate column", "no such column")):
                logger.debug("v2 migration skipped (already applied): %s", exc)
            else:
                logger.error("v2 migration failed: %s", exc, exc_info=True)
                raise

    # Feed v2 reaper (Phase 7): after migrations (so mas_runs exists) and OUTSIDE the
    # init connection, sweep any 'running' run whose lease expired — a crashed prior
    # run left a stale 'running' row; this fails it so its (project,day) slot frees up.
    # Lazy import keeps langgraph off the import path until startup. Non-fatal.
    try:
        from ..services.feed_v2.graph import reap_expired_runs
        reaped = reap_expired_runs()
        if reaped:
            logger.info("v2 reaper: failed %d expired run(s) on startup", reaped)
    except Exception:
        logger.error("v2 reaper failed on startup", exc_info=True)


def build_set_clause(keys) -> str:
    """Join column names into a 'col = ?' clause for use in an UPDATE ... SET statement."""
    return ", ".join(f"{k} = ?" for k in keys)


@contextmanager
def get_connection():
    """Yield a sqlite3 connection that auto-commits on success and rolls back on error."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row          # rows accessible as dicts
    conn.execute("PRAGMA journal_mode=WAL") # safe for concurrent reads
    conn.execute("PRAGMA foreign_keys=ON")
    conn.enable_load_extension(True)        # extensions load per-connection, not globally
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── user_preferences helpers ──────────────────────────────────────────────────

def upsert_preference(topic: str, difficulty: str | None = None) -> dict:
    """
    Insert a new topic preference or increment times_recommended if it already exists.
    Returns the updated row as a dict.
    """
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO user_preferences (topic, times_recommended, difficulty_preference, last_updated)
            VALUES (?, 1, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(topic) DO UPDATE SET
                times_recommended    = times_recommended + 1,
                difficulty_preference = COALESCE(excluded.difficulty_preference, difficulty_preference),
                last_updated         = CURRENT_TIMESTAMP
            """,
            (topic, difficulty),
        )
        row = conn.execute(
            "SELECT * FROM user_preferences WHERE topic = ?", (topic,)
        ).fetchone()
    return dict(row)


_DIFFICULTY_DOWN = {"advanced": "intermediate", "intermediate": "beginner",    "beginner": "beginner"}
_DIFFICULTY_UP   = {"beginner": "intermediate", "intermediate": "advanced",    "advanced": "advanced"}

def record_feedback(topic: str, feedback: str, user_id: str) -> dict:
    """
    Process one of four feedback signals for a topic, scoped to user_id.

    liked        → times_liked++,    score = (liked - disliked) / max(1, recommended)
    disliked     → times_disliked++, score = (liked - disliked) / max(1, recommended)
    too_advanced → step difficulty_preference down one level (advanced→intermediate→beginner)
    too_basic    → step difficulty_preference up one level   (beginner→intermediate→advanced)

    Auto-creates the row if this user hasn't tracked this topic before.

    Chat-R7a: user_id is required, not optional — this is the write side of
    the personalization-context leak (memory_injection_service read this
    table with no scope; every existing row had a NULL user_id because
    nothing ever wrote one). Table uniqueness is (topic, user_id), not topic
    alone (migrated in schema.py), so two users liking the same topic no
    longer collide on the same row via ON CONFLICT.
    """
    if feedback not in {"liked", "disliked", "too_advanced", "too_basic"}:
        raise ValueError(f"Unknown feedback type: '{feedback}'")
    if not user_id:
        raise ValueError("user_id must not be empty")

    with get_connection() as conn:
        # Ensure the row exists before we try to update it
        conn.execute(
            "INSERT OR IGNORE INTO user_preferences (topic, user_id) VALUES (?, ?)",
            (topic, user_id),
        )

        row = dict(
            conn.execute(
                "SELECT * FROM user_preferences WHERE topic = ? AND user_id = ?",
                (topic, user_id),
            ).fetchone()
        )

        if feedback == "liked":
            new_liked = row["times_liked"] + 1
            new_score = (new_liked - row["times_disliked"]) / max(1, row["times_recommended"])
            conn.execute(
                """UPDATE user_preferences
                   SET times_liked = ?, preference_score = ?, last_updated = CURRENT_TIMESTAMP
                   WHERE topic = ? AND user_id = ?""",
                (new_liked, round(new_score, 4), topic, user_id),
            )

        elif feedback == "disliked":
            new_disliked = row["times_disliked"] + 1
            new_score    = (row["times_liked"] - new_disliked) / max(1, row["times_recommended"])
            conn.execute(
                """UPDATE user_preferences
                   SET times_disliked = ?, preference_score = ?, last_updated = CURRENT_TIMESTAMP
                   WHERE topic = ? AND user_id = ?""",
                (new_disliked, round(new_score, 4), topic, user_id),
            )

        else:  # too_advanced | too_basic
            table  = _DIFFICULTY_DOWN if feedback == "too_advanced" else _DIFFICULTY_UP
            current   = row["difficulty_preference"] or "intermediate"
            new_diff  = table[current]
            conn.execute(
                """UPDATE user_preferences
                   SET difficulty_preference = ?, last_updated = CURRENT_TIMESTAMP
                   WHERE topic = ? AND user_id = ?""",
                (new_diff, topic, user_id),
            )

        return dict(
            conn.execute(
                "SELECT * FROM user_preferences WHERE topic = ? AND user_id = ?",
                (topic, user_id),
            ).fetchone()
        )


def get_preference(topic: str) -> dict | None:
    """Return the preference row for a topic, or None if not tracked yet."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM user_preferences WHERE topic = ?", (topic,)
        ).fetchone()
    return dict(row) if row else None


def list_preferences(order_by: str = "preference_score", limit: int = 20, user_id: str | None = None) -> list[dict]:
    """
    Return tracked topics sorted by the given column (descending).
    Safe columns: preference_score, times_recommended, times_liked, last_updated.

    Chat-R7a: user_id is optional and defaults to None (unchanged, global
    behavior) — this function is shared by Feed's recommendation/timeline
    reads (out of this fix's scope, left exactly as before) and chat's
    personalization context (which always passes a real user_id now, never
    silently omitting it). No global fallback on the chat code path — only
    callers that don't pass user_id at all get the old unscoped behavior.
    """
    allowed = {"preference_score", "times_recommended", "times_liked", "last_updated"}
    if order_by not in allowed:
        raise ValueError(f"order_by must be one of {allowed}")
    with get_connection() as conn:
        if user_id is not None:
            rows = conn.execute(
                f"SELECT * FROM user_preferences WHERE user_id = ? ORDER BY {order_by} DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT * FROM user_preferences ORDER BY {order_by} DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def delete_preference(topic: str) -> bool:
    """Remove a topic from tracking. Returns True if a row was deleted."""
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM user_preferences WHERE topic = ?", (topic,)
        )
    return cursor.rowcount > 0
