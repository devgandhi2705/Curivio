"""
Feed v2 journey service (Phase 6).

The v2-owned journey-plan path the app layer calls. Owns:

  * plan_next_batch   — gather the project's profile + coverage_mode + material
                        structure, apply the shape LOCK (skip re-deciding when the
                        description is unchanged), run the planner agent, and APPEND
                        the batch. On failure: journey_status='failed', NO plan row
                        written, exception re-raised (no silent fake plan).
  * get_day_entry     — read the NEWEST batch covering a requested day (append-only:
                        re-planning inserts a new batch; the latest wins).

APPEND-ONLY: v2_journey_plans is only ever INSERTed (never UPDATE/DELETE), ported
directly from legacy where it was confirmed correct. Only v2_projects.journey_shape/
journey_status are updated.

Isolation: imports feed_v2's own db + agent + projects service only.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone

from .agents.journey_planner import AllLegsFailed, run_journey_plan
from .db import get_connection
from .projects import get_project

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _hash(text: str) -> str:
    return hashlib.md5((text or "").encode("utf-8", errors="replace")).hexdigest()[:16]


def _chapters_for_project(project_id: str, user_id: str) -> list[str]:
    """Ordered section titles across the project's successfully-extracted materials
    (created_at order). This is the material_bound curriculum — chapter order becomes
    day order."""
    titles: list[str] = []
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT structure_json FROM v2_materials
                   WHERE project_id = ? AND user_id = ? AND extraction_status = 'done'
                   ORDER BY created_at""",
            (project_id, user_id),
        ).fetchall()
    for r in rows:
        try:
            for s in json.loads(r["structure_json"] or "[]"):
                t = s.get("title")
                if t:
                    titles.append(t)
        except Exception:
            continue
    return titles


def _covered_concepts(project_id: str, user_id: str) -> list[str]:
    """Focus strings from prior fixed_sequence batches, so a continuation batch does
    not repeat earlier days. Empty for the first batch."""
    out: list[str] = []
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT plan_content FROM v2_journey_plans WHERE project_id = ? AND user_id = ? ORDER BY created_at",
            (project_id, user_id),
        ).fetchall()
    for r in rows:
        try:
            for d in (json.loads(r["plan_content"]).get("days") or []):
                if d.get("focus"):
                    out.append(d["focus"])
        except Exception:
            continue
    return out


def _locked_shape(project_id: str, user_id: str, desc_hash: str) -> str | None:
    """The shape lock: reuse journey_shape when it's set AND the last batch was
    planned under the same description_hash. A changed description clears the lock."""
    proj = get_project(user_id, project_id)
    if not proj or not proj.get("journey_shape"):
        return None
    with get_connection() as conn:
        last = conn.execute(
            "SELECT description_hash FROM v2_journey_plans WHERE project_id = ? AND user_id = ? ORDER BY created_at DESC LIMIT 1",
            (project_id, user_id),
        ).fetchone()
    if last and last["description_hash"] == desc_hash:
        return proj["journey_shape"]
    logger.info("[feed_v2.journeys] project=%s description changed — re-deciding shape", project_id)
    return None


def _next_day_start(project_id: str, user_id: str) -> int:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT MAX(day_end) AS m FROM v2_journey_plans WHERE project_id = ? AND user_id = ?",
            (project_id, user_id),
        ).fetchone()
    return (row["m"] + 1) if row and row["m"] is not None else 1


def _save_batch(user_id: str, project_id: str, batch: dict, desc_hash: str) -> None:
    """APPEND the batch (INSERT only) and update the project's shape lock + status."""
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO v2_journey_plans
                   (plan_id, user_id, project_id, day_start, day_end, plan_content,
                    shape, description_hash, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (uuid.uuid4().hex, user_id, project_id, batch["day_start"], batch["day_end"],
             json.dumps(batch), batch["shape"], desc_hash, _now()),
        )
        conn.execute(
            "UPDATE v2_projects SET journey_shape = ?, journey_status = 'ready', updated_at = ? WHERE project_id = ? AND user_id = ?",
            (batch["shape"], _now(), project_id, user_id),
        )


def plan_next_batch(user_id: str, project_id: str, day_start: int | None = None) -> dict:
    """Plan and append the next batch for a project. Raises ValueError if the project
    has no ready profile; re-raises the planner's failure (marking journey_status=
    'failed', writing no plan) if generation fails."""
    proj = get_project(user_id, project_id)
    if proj is None:
        raise ValueError(f"project {project_id} not found for user {user_id}")
    coverage_mode = proj.get("coverage_mode")
    profile = proj.get("profile") or {}
    if not coverage_mode or not profile:
        raise ValueError("project has no ready profile/coverage_mode — run the profile agent first")

    desc_hash = _hash(proj.get("description") or "")
    locked = _locked_shape(project_id, user_id, desc_hash)
    start = day_start if day_start is not None else _next_day_start(project_id, user_id)

    try:
        batch = run_journey_plan(
            coverage_mode=coverage_mode, profile=profile,
            difficulty=proj.get("difficulty") or "intermediate",
            chapters=_chapters_for_project(project_id, user_id),
            material_scope=proj.get("material_scope") or profile.get("material_scope") or "",
            keywords=[], covered_concepts=_covered_concepts(project_id, user_id),
            day_start=start, locked_shape=locked,
            meta={"user_id": user_id, "project_id": project_id},
        )
    except (AllLegsFailed, ValueError):
        # Visible, no fake plan — same reversal as the profile agent.
        with get_connection() as conn:
            conn.execute(
                "UPDATE v2_projects SET journey_status = 'failed', updated_at = ? WHERE project_id = ? AND user_id = ?",
                (_now(), project_id, user_id),
            )
        logger.warning("[feed_v2.journeys] planning failed for %s — marked failed, no plan written", project_id)
        raise

    _save_batch(user_id, project_id, batch, desc_hash)
    logger.info("[feed_v2.journeys] appended batch for %s: shape=%s days %d-%d",
                project_id, batch["shape"], batch["day_start"], batch["day_end"])
    return batch


def get_day_entry(user_id: str, project_id: str, day_number: int) -> dict | None:
    """Read the NEWEST batch covering day_number and return that day's entry, or None
    if no batch covers it (append-only: the latest batch wins)."""
    with get_connection() as conn:
        row = conn.execute(
            """SELECT * FROM v2_journey_plans
                   WHERE project_id = ? AND user_id = ? AND day_start <= ? AND day_end >= ?
                   ORDER BY created_at DESC LIMIT 1""",
            (project_id, user_id, day_number, day_number),
        ).fetchone()
    if row is None:
        return None
    batch = json.loads(row["plan_content"])
    if row["shape"] == "fixed_sequence":
        for entry in batch.get("days") or []:
            if entry.get("day_number") == day_number:
                return entry
        days = batch.get("days") or []
        return days[-1] if days else None
    # rotating_theme — deterministic rotation from the batch's day_start
    themes = batch.get("themes") or []
    if not themes:
        return None
    idx = (day_number - row["day_start"]) % len(themes)
    return {"day_number": day_number, "theme": themes[idx],
            "display_summary": batch.get("display_summary", ""),
            "trusted_sources": batch.get("trusted_sources", [])}
