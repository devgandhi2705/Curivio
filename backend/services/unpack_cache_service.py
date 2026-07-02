"""
Unpack cache — SHA-256-keyed, SQLite-backed, TTL-expiring cache for Unpack
results: "explain" (dictionary/LLM) and "translate" (Google Translate), kept
as independent entries via the `action` dimension in the key.

Avoids re-calling the LLM/Translate API when multiple users select the same
phrase in the same piece of content.

TTL
---
Controlled by UNPACK_CACHE_TTL_HOURS (default: 720h / 30 days) — definitions
and translations don't go stale the way news does.

Public API
----------
build_unpack_key(term, sentence, action, target_language) -> str
get_cached_unpack(key)                                     -> dict | None
cache_unpack(key, term, target_language, result)           -> None
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone

from ..utils.db import get_connection
from ..config import UNPACK_CACHE_TTL_HOURS


def _normalize(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def build_unpack_key(term: str, sentence: str, action: str, target_language: str | None) -> str:
    """
    SHA-256 of the normalised term + surrounding sentence + action + target
    language. `action` ("explain" | "translate") keeps the two paths' cache
    entries independent even for the same selected text.
    """
    raw = f"{_normalize(term)}|{_normalize(sentence)}|{action}|{_normalize(target_language or '')}"
    return hashlib.sha256(raw.encode()).hexdigest()


def get_cached_unpack(key: str) -> dict | None:
    """Return the cached result if present and unexpired. Increments hit_count on a hit."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=UNPACK_CACHE_TTL_HOURS)

    with get_connection() as conn:
        row = conn.execute(
            "SELECT response_json, created_at FROM unpack_cache WHERE cache_key = ?",
            (key,),
        ).fetchone()

        if row is None:
            return None

        if _parse_ts(row["created_at"]) < cutoff:
            return None  # expired

        conn.execute(
            "UPDATE unpack_cache SET hit_count = hit_count + 1 WHERE cache_key = ?",
            (key,),
        )

    return json.loads(row["response_json"])


def cache_unpack(key: str, term: str, target_language: str | None, result: dict) -> None:
    """Upsert an Unpack cache entry, resetting the TTL and hit_count."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO unpack_cache (cache_key, term, target_language, response_json, hit_count, created_at)
            VALUES (?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
            ON CONFLICT(cache_key) DO UPDATE SET
                response_json = excluded.response_json,
                hit_count     = 0,
                created_at    = CURRENT_TIMESTAMP
            """,
            (key, term.strip(), (target_language or "").strip(), json.dumps(result)),
        )


def _parse_ts(value: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Unrecognised timestamp format: {value!r}")
