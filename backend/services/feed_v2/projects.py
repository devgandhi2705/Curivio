"""
Feed v2 project service (Phase 5).

The v2-owned project CRUD the app layer calls — a NEW v2 path, never a call into
legacy project_service. Owns:

  * create_project        — insert a v2_projects row BEFORE any material can
                            reference it (materials FK v2_projects).
  * generate_profile      — run the profile agent over the project's materials and
                            persist the result. On agent failure it marks
                            profile_status='failed' and writes NO fake profile, then
                            re-raises — a visible, retryable state, NOT legacy's
                            silent {"persona":"Learner"} default.
  * set_coverage_mode     — the user's one-write override of the inferred
                            coverage_mode, and the intent_confirmed flip.

Isolation: imports feed_v2's own db + profile agent only; no backend.services.* /
backend.llm.*.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from .agents.profile import AllLegsFailed, run_profile
from .db import get_connection

logger = logging.getLogger(__name__)

_VALID_COVERAGE = {"material_bound", "material_anchored", "open"}
_EXCERPT_CHARS = 600


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _row(project_id: str, user_id: str) -> dict | None:
    with get_connection() as conn:
        r = conn.execute(
            "SELECT * FROM v2_projects WHERE project_id = ? AND user_id = ?",
            (project_id, user_id),
        ).fetchone()
    return _shape(r) if r else None


def _shape(r) -> dict:
    """Row → API dict: parse profile_json so callers get the persona inline."""
    d = dict(r)
    raw = d.pop("profile_json", None)
    try:
        d["profile"] = json.loads(raw) if raw else None
    except Exception:
        d["profile"] = None
    return d


def create_project(user_id: str, name: str, description: str = "",
                   difficulty: str = "intermediate") -> dict:
    """Create a v2 project. profile_status stays NULL — the profile is generated
    in a separate step, after materials are attached (it reads them)."""
    project_id = uuid.uuid4().hex
    now = _now()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO v2_projects
                   (project_id, user_id, name, description, difficulty,
                    intent_confirmed, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 0, ?, ?)""",
            (project_id, user_id, name, description, difficulty or "intermediate", now, now),
        )
    logger.info("[feed_v2.projects] created %s for user %s", project_id, user_id)
    return _row(project_id, user_id)


def get_project(user_id: str, project_id: str) -> dict | None:
    return _row(project_id, user_id)


def _materials_for_profile(project_id: str, user_id: str) -> list[dict]:
    """Successfully-extracted materials with the QUERYABLE Phase-4 signal columns
    the profile agent reasons over (type / has_structure / section_count) plus
    section titles + a first-chunk excerpt for scope. Failed materials are excluded
    — a corrupt upload must not shape the persona."""
    out: list[dict] = []
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT material_id, type, filename, url, has_structure, section_count, structure_json
                   FROM v2_materials
                   WHERE project_id = ? AND user_id = ? AND extraction_status = 'done'
                   ORDER BY created_at""",
            (project_id, user_id),
        ).fetchall()
        for m in rows:
            excerpt = conn.execute(
                """SELECT chunk_text FROM v2_material_chunks
                       WHERE material_id = ? ORDER BY chunk_index LIMIT 1""",
                (m["material_id"],),
            ).fetchone()
            try:
                titles = [s.get("title") for s in json.loads(m["structure_json"] or "[]") if s.get("title")]
            except Exception:
                titles = []
            out.append({
                "type": m["type"],
                "label": m["filename"] or m["url"],
                "has_structure": m["has_structure"],
                "section_count": m["section_count"],
                "section_titles": titles,
                "excerpt": (excerpt["chunk_text"] if excerpt else "")[:_EXCERPT_CHARS],
            })
    return out


def generate_profile(user_id: str, project_id: str) -> dict:
    """Run the profile agent for a project and persist the result.

    Success → profile_json + coverage_mode/material_scope/coverage_reasoning +
    profile_status='ready'. Failure (AllLegsFailed) → profile_status='failed', NO
    profile written, exception re-raised so the route surfaces a retryable error.
    """
    proj = get_project(user_id, project_id)
    if proj is None:
        raise ValueError(f"project {project_id} not found for user {user_id}")

    materials = _materials_for_profile(project_id, user_id)
    try:
        profile = run_profile(
            name=proj["name"], description=proj["description"],
            keywords=[], difficulty=proj.get("difficulty") or "intermediate",
            materials=materials,
            meta={"user_id": user_id, "project_id": project_id},
        )
    except AllLegsFailed:
        # Visible, retryable failure — NO fake profile. This is the explicit reversal
        # of legacy's silent "Learner" default.
        with get_connection() as conn:
            conn.execute(
                "UPDATE v2_projects SET profile_status = 'failed', updated_at = ? WHERE project_id = ? AND user_id = ?",
                (_now(), project_id, user_id),
            )
        logger.warning("[feed_v2.projects] profile generation failed for %s — marked retryable", project_id)
        raise

    with get_connection() as conn:
        conn.execute(
            """UPDATE v2_projects
                   SET profile_json = ?, coverage_mode = ?, material_scope = ?,
                       coverage_reasoning = ?, profile_status = 'ready', updated_at = ?
                   WHERE project_id = ? AND user_id = ?""",
            (json.dumps(profile), profile["coverage_mode"], profile["material_scope"],
             profile["coverage_reasoning"], _now(), project_id, user_id),
        )
    logger.info("[feed_v2.projects] profile ready for %s: persona=%r coverage=%s",
                project_id, profile.get("persona"), profile.get("coverage_mode"))
    return get_project(user_id, project_id)


def set_coverage_mode(user_id: str, project_id: str, coverage_mode: str,
                     confirmed: bool = True) -> dict:
    """User override of the inferred coverage_mode (one write), optionally flipping
    intent_confirmed. Reuses the intent_confirmed boolean SHAPE from legacy but on
    v2_projects' own column."""
    if coverage_mode not in _VALID_COVERAGE:
        raise ValueError(f"coverage_mode must be one of {_VALID_COVERAGE}")
    proj = get_project(user_id, project_id)
    if proj is None:
        raise ValueError(f"project {project_id} not found for user {user_id}")
    with get_connection() as conn:
        conn.execute(
            "UPDATE v2_projects SET coverage_mode = ?, intent_confirmed = ?, updated_at = ? WHERE project_id = ? AND user_id = ?",
            (coverage_mode, 1 if confirmed else 0, _now(), project_id, user_id),
        )
    return get_project(user_id, project_id)
