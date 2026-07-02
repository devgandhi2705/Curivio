"""
Knowledge State Service

Compressed, bounded snapshot of what a project has learned.
Updated after every feed generation. Read before every feed generation.

Day 100 costs the same context tokens as Day 1 — all lists are size-bounded.
No package history is ever read; the state is the only continuity mechanism.

Public API
----------
get_state(project_id)             -> dict
update_state(project_id, package) -> None
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

# ── Size bounds — keep prompt cost flat regardless of project age ──────────────
_MAX_COVERED_TOPICS   = 60
_MAX_RECENT_TOPICS    = 8
_MAX_ACTIVE_TOPICS    = 10
_MAX_COVERED_ENTITIES = 50
_MAX_COVERED_KEYWORDS = 40
_MAX_KNOWLEDGE_GAPS   = 20

_EMPTY: dict = {
    "covered_topics":   [],
    "active_topics":    [],
    "knowledge_gaps":   [],
    "recent_topics":    [],
    "covered_entities": [],
    "covered_keywords": [],
}


# ── Public API ─────────────────────────────────────────────────────────────────

def get_state(project_id: str) -> dict:
    """Return the current knowledge state, or an empty state for new projects."""
    from ..utils.db import get_connection
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM project_learning_state WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    if not row:
        return dict(_EMPTY)
    return {
        "covered_topics":   _load(row["covered_topics"]),
        "active_topics":    _load(row["active_topics"]),
        "knowledge_gaps":   _load(row["knowledge_gaps"]),
        "recent_topics":    _load(row["recent_topics"]),
        "covered_entities": _load(row["covered_entities"]),
        "covered_keywords": _load(row["covered_keywords"]),
    }


def update_state(project_id: str, package: dict) -> None:
    """
    Extract learning metadata from the package via LLM (concept_extractor_service),
    merge into the stored state, and persist. All lists are size-bounded so
    prompt cost stays flat regardless of project age.
    """
    from .concept_extractor_service import extract as _extract
    existing  = get_state(project_id)
    extracted = _extract(package)

    covered_topics   = _merge(existing["covered_topics"],   extracted["new_topics"],    _MAX_COVERED_TOPICS)
    covered_entities = _merge(existing["covered_entities"], extracted["new_entities"],  _MAX_COVERED_ENTITIES)
    covered_keywords = _merge(existing["covered_keywords"], extracted["new_keywords"],  _MAX_COVERED_KEYWORDS)
    knowledge_gaps   = _merge(existing["knowledge_gaps"],   extracted["new_gaps"],      _MAX_KNOWLEDGE_GAPS)

    active_topics    = extracted["new_topics"][:_MAX_ACTIVE_TOPICS]
    recent_topics    = covered_topics[-_MAX_RECENT_TOPICS:]

    from ..utils.db import get_connection
    now = _now()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO project_learning_state
               (project_id, covered_topics, active_topics, knowledge_gaps,
                recent_topics, covered_entities, covered_keywords, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(project_id) DO UPDATE SET
                 covered_topics   = excluded.covered_topics,
                 active_topics    = excluded.active_topics,
                 knowledge_gaps   = excluded.knowledge_gaps,
                 recent_topics    = excluded.recent_topics,
                 covered_entities = excluded.covered_entities,
                 covered_keywords = excluded.covered_keywords,
                 updated_at       = excluded.updated_at""",
            (
                project_id,
                json.dumps(covered_topics),
                json.dumps(active_topics),
                json.dumps(knowledge_gaps),
                json.dumps(recent_topics),
                json.dumps(covered_entities),
                json.dumps(covered_keywords),
                now,
            ),
        )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _merge(existing: list[str], new: list[str], limit: int) -> list[str]:
    """Append new items, dedup case-insensitively, cap at limit (newest kept)."""
    seen   = {s.lower() for s in existing}
    added  = [v for v in new if v.lower() not in seen]
    merged = existing + added
    return merged[-limit:]


def _load(raw) -> list[str]:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return []
    if isinstance(raw, list):
        return raw
    return []


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
