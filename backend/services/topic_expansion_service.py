"""
Related-topic expansion engine for the AI learning agent.

Given a topic, generates a structured knowledge graph slice:
  - prerequisites      : concepts required before tackling the topic
  - related_topics     : peer-level sibling concepts at the same difficulty tier
  - advanced_follow_ups: topics that become accessible after mastering this one
  - learning_progression: ordered path from foundations to advanced (includes the topic)
  - progression_rationale: explanation of the sequencing logic

Results are cached in the topic_expansions DB table with a configurable TTL.

Public API
----------
expand_topic(topic)          — cache-first expansion; runs generation on a miss
get_stored_expansion(topic)  — retrieve cached result or None
list_expansions(limit)       — list stored expansions newest-first

Correct patch targets for tests (all imports are deferred)
----------------------------------------------------------
  ask_grok   → backend.services.grok_service.ask_grok
  get_connection (service) → backend.services.topic_expansion_service.get_connection
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

from ..utils.db import get_connection
from ..prompts.topic_expansion_prompt import TOPIC_EXPANSION_PROMPT

logger = logging.getLogger(__name__)

TOPIC_EXPANSION_TTL_HOURS: int = int(os.getenv("TOPIC_EXPANSION_TTL_HOURS", "72"))

_REQUIRED_LIST_FIELDS = (
    "prerequisites",
    "related_topics",
    "advanced_follow_ups",
    "learning_progression",
)


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def expand_topic(topic: str) -> dict:
    """Return expansion for topic, running generation on a cache miss."""
    cached = get_stored_expansion(topic)
    if cached is not None:
        logger.info("[topic_expansion] cache hit for %r", topic)
        return cached
    logger.info("[topic_expansion] generating expansion for %r", topic)
    result = _generate_expansion(topic)
    _store_expansion(topic, result)
    return result


def get_stored_expansion(topic: str) -> dict | None:
    """Return stored expansion if it exists and has not expired."""
    key = _topic_key(topic)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=TOPIC_EXPANSION_TTL_HOURS)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT expansion_json, generated_at FROM topic_expansions WHERE topic_key = ?",
            (key,),
        ).fetchone()
    if row is None:
        return None
    if _parse_ts(row["generated_at"]) < cutoff:
        return None
    return json.loads(row["expansion_json"])


def list_expansions(limit: int = 20) -> list[dict]:
    """Return stored expansions newest-first (id, topic, generated_at)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, topic, generated_at FROM topic_expansions "
            "ORDER BY generated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════════════
# Internal implementation
# ═══════════════════════════════════════════════════════════════════════════════

def _generate_expansion(topic: str) -> dict:
    from .grok_service import ask_grok  # deferred to avoid circular import

    prompt = TOPIC_EXPANSION_PROMPT.format(topic=topic.strip())
    raw    = ask_grok(prompt)
    result = _parse_json_response(raw)

    # Guarantee all required fields exist
    for field in _REQUIRED_LIST_FIELDS:
        result.setdefault(field, [])
    result.setdefault("progression_rationale", "")

    # Inject metadata
    result["topic"]        = topic.strip()
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    return result


def _store_expansion(topic: str, result: dict) -> int:
    """Upsert result for a topic; return the DB row id."""
    key = _topic_key(topic)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO topic_expansions (topic, topic_key, expansion_json, generated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(topic_key) DO UPDATE SET
                topic          = excluded.topic,
                expansion_json = excluded.expansion_json,
                generated_at   = CURRENT_TIMESTAMP
            """,
            (topic.strip(), key, json.dumps(result)),
        )
        row = conn.execute(
            "SELECT id FROM topic_expansions WHERE topic_key = ?", (key,)
        ).fetchone()
    return row["id"]


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers (exposed for unit tests)
# ═══════════════════════════════════════════════════════════════════════════════

def _topic_key(topic: str) -> str:
    return topic.strip().lower()


def _parse_json_response(raw: str) -> dict:
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    raise ValueError(
        f"LLM response could not be parsed as JSON. "
        f"Raw output (first 300 chars): {cleaned[:300]}"
    )


def _parse_ts(value: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Unrecognised timestamp format: {value!r}")
