"""
SQLite database utilities.

Usage:
    from backend.utils.db import get_connection, init_db
    from backend.utils.db import upsert_preference, get_preference, list_preferences, record_feedback
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from ..database.schema import ALL_TABLES, MIGRATIONS

# DB_PATH is configurable via environment variable for deployment portability.
# Docker/HF Spaces: set DB_PATH=/data/memory.db for persistent storage.
# Default falls back to the project root data/ directory for local development.
_db_path_env = os.getenv("DB_PATH", "")
DB_PATH = Path(_db_path_env) if _db_path_env else Path(__file__).resolve().parents[2] / "data" / "memory.db"


def init_db() -> None:
    """Create all tables and run additive migrations."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        for statement in ALL_TABLES:
            conn.execute(statement)
        # Migrations are additive-only and safe to re-run; errors are silently
        # ignored (e.g. duplicate column on an existing DB).
        # A migration may be a single SQL string or a list of strings that must
        # all execute together (used for table-recreation migrations).
        for migration in MIGRATIONS:
            try:
                if isinstance(migration, (list, tuple)):
                    for stmt in migration:
                        conn.execute(stmt)
                else:
                    conn.execute(migration)
            except Exception:
                pass


@contextmanager
def get_connection():
    """Yield a sqlite3 connection that auto-commits on success and rolls back on error."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row          # rows accessible as dicts
    conn.execute("PRAGMA journal_mode=WAL") # safe for concurrent reads
    conn.execute("PRAGMA foreign_keys=ON")
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

def record_feedback(topic: str, feedback: str) -> dict:
    """
    Process one of four feedback signals for a topic.

    liked        → times_liked++,    score = (liked - disliked) / max(1, recommended)
    disliked     → times_disliked++, score = (liked - disliked) / max(1, recommended)
    too_advanced → step difficulty_preference down one level (advanced→intermediate→beginner)
    too_basic    → step difficulty_preference up one level   (beginner→intermediate→advanced)

    Auto-creates the row if the topic has not been tracked before.
    """
    if feedback not in {"liked", "disliked", "too_advanced", "too_basic"}:
        raise ValueError(f"Unknown feedback type: '{feedback}'")

    with get_connection() as conn:
        # Ensure the row exists before we try to update it
        conn.execute(
            "INSERT OR IGNORE INTO user_preferences (topic) VALUES (?)", (topic,)
        )

        row = dict(
            conn.execute(
                "SELECT * FROM user_preferences WHERE topic = ?", (topic,)
            ).fetchone()
        )

        if feedback == "liked":
            new_liked = row["times_liked"] + 1
            new_score = (new_liked - row["times_disliked"]) / max(1, row["times_recommended"])
            conn.execute(
                """UPDATE user_preferences
                   SET times_liked = ?, preference_score = ?, last_updated = CURRENT_TIMESTAMP
                   WHERE topic = ?""",
                (new_liked, round(new_score, 4), topic),
            )

        elif feedback == "disliked":
            new_disliked = row["times_disliked"] + 1
            new_score    = (row["times_liked"] - new_disliked) / max(1, row["times_recommended"])
            conn.execute(
                """UPDATE user_preferences
                   SET times_disliked = ?, preference_score = ?, last_updated = CURRENT_TIMESTAMP
                   WHERE topic = ?""",
                (new_disliked, round(new_score, 4), topic),
            )

        else:  # too_advanced | too_basic
            table  = _DIFFICULTY_DOWN if feedback == "too_advanced" else _DIFFICULTY_UP
            current   = row["difficulty_preference"] or "intermediate"
            new_diff  = table[current]
            conn.execute(
                """UPDATE user_preferences
                   SET difficulty_preference = ?, last_updated = CURRENT_TIMESTAMP
                   WHERE topic = ?""",
                (new_diff, topic),
            )

        return dict(
            conn.execute(
                "SELECT * FROM user_preferences WHERE topic = ?", (topic,)
            ).fetchone()
        )


def get_preference(topic: str) -> dict | None:
    """Return the preference row for a topic, or None if not tracked yet."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM user_preferences WHERE topic = ?", (topic,)
        ).fetchone()
    return dict(row) if row else None


def list_preferences(order_by: str = "preference_score", limit: int = 20) -> list[dict]:
    """
    Return all tracked topics sorted by the given column (descending).
    Safe columns: preference_score, times_recommended, times_liked, last_updated.
    """
    allowed = {"preference_score", "times_recommended", "times_liked", "last_updated"}
    if order_by not in allowed:
        raise ValueError(f"order_by must be one of {allowed}")
    with get_connection() as conn:
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
