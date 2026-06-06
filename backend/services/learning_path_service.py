"""
Structured learning path generation for the AI learning agent.

Given a topic and the learner's current profile, generates a three-tier learning path:
  beginner     : foundational concepts — mechanics and mental models
  intermediate : applied engineering — building, patterns, trade-offs
  advanced     : specialist depth — internals, production failure modes, research

Each concept carries: name, explanation, why_it_matters, recommended resources.

Results are cached per topic (48 h TTL). The learner profile at generation time is
embedded in the result so the frontend can show it alongside the path.

Public API
----------
get_learning_path(topic)      — cache-first; generates on a miss
get_stored_path(topic)        — retrieve cached result or None
list_learning_paths(limit)    — stored paths newest-first

Correct patch targets for tests (all imports are deferred)
----------------------------------------------------------
  ask_grok                          → backend.services.grok_service.ask_grok
  get_learning_stage                → backend.services.recommendation_service.get_learning_stage
  get_overall_difficulty_preference → backend.services.recommendation_service.get_overall_difficulty_preference
  get_connection (service)          → backend.services.learning_path_service.get_connection
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

from ..utils.db import get_connection
from ..prompts.learning_path_prompt import build_learning_path_prompt

logger = logging.getLogger(__name__)

from ..config import LEARNING_PATH_TTL_HOURS

_TIERS = ("beginner", "intermediate", "advanced")
_STEP_FIELDS = ("concept", "explanation", "why_it_matters", "resources")


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def get_learning_path(topic: str) -> dict:
    """Return learning path for topic, generating on a cache miss."""
    cached = get_stored_path(topic)
    if cached is not None:
        logger.info("[learning_path] cache hit for %r", topic)
        return cached
    logger.info("[learning_path] generating path for %r", topic)
    result = _generate_learning_path(topic)
    _store_path(topic, result)
    return result


def get_stored_path(topic: str) -> dict | None:
    """Return stored path if it exists and has not expired."""
    key = _topic_key(topic)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LEARNING_PATH_TTL_HOURS)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT path_json, generated_at FROM learning_paths WHERE topic_key = ?",
            (key,),
        ).fetchone()
    if row is None:
        return None
    if _parse_ts(row["generated_at"]) < cutoff:
        return None
    return json.loads(row["path_json"])


def list_learning_paths(limit: int = 20) -> list[dict]:
    """Return stored paths newest-first (id, topic, learning_stage, generated_at)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, topic, learning_stage, generated_at FROM learning_paths "
            "ORDER BY generated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════════════
# Internal implementation
# ═══════════════════════════════════════════════════════════════════════════════

def _generate_learning_path(topic: str) -> dict:
    from .grok_service import ask_grok  # deferred to avoid circular import
    from .recommendation_service import (  # deferred to avoid circular import
        get_learning_stage,
        get_overall_difficulty_preference,
    )

    learning_stage        = get_learning_stage()
    difficulty_preference = get_overall_difficulty_preference() or "no preference"

    prompt = build_learning_path_prompt(
        topic=topic.strip(),
        learning_stage=learning_stage,
        difficulty_preference=difficulty_preference,
    )

    raw    = ask_grok(prompt)
    result = _parse_json_response(raw)

    # Guarantee all tiers exist and each step has the required fields
    for tier in _TIERS:
        result.setdefault(tier, [])
        for step in result[tier]:
            for field in _STEP_FIELDS:
                step.setdefault(field, [] if field == "resources" else "")

    # Inject metadata
    result["topic"]          = topic.strip()
    result["learning_stage"] = learning_stage
    result["generated_at"]   = datetime.now(timezone.utc).isoformat()
    return result


def _store_path(topic: str, result: dict) -> int:
    """Upsert path for a topic; return the DB row id."""
    key   = _topic_key(topic)
    stage = result.get("learning_stage", "beginner")
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO learning_paths (topic, topic_key, learning_stage, path_json, generated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(topic_key) DO UPDATE SET
                topic          = excluded.topic,
                learning_stage = excluded.learning_stage,
                path_json      = excluded.path_json,
                generated_at   = CURRENT_TIMESTAMP
            """,
            (topic.strip(), key, stage, json.dumps(result)),
        )
        row = conn.execute(
            "SELECT id FROM learning_paths WHERE topic_key = ?", (key,)
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
