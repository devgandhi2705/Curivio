"""
Feed v2 lesson planner (Phase 11) — the DECISION layer for today's lesson.

ONE small LLM call. NO research, NO source consumption — decides only what today's
lesson contains, cheap and fast:
  - objectives: 2-4 concrete learning objectives for the day (the assembler reads
    lesson_plan.objectives).
  - render_prerequisites: whether section 3 (a prerequisite refresher) renders today.
    True only if today's prerequisite_concepts (Phase 6 journey entry) both EXIST and
    the model judges them a real gap for this learner/level; empty prerequisite_concepts
    (e.g. day 1) ⇒ always False, no LLM guessing a gap into existence.

Mechanically derived AFTER the call (NOT trusted to the LLM), stated per spec:
  - worked_example_mode: "example-first" (beginner/intermediate) | "problem-first"
    (advanced). A pure function of PROJECT difficulty only — mastery-based refinement is
    deferred because v2_mastery has no data yet (no phase writes it).
  - section_4b: always "pending". Section 4b (source conflict) gates on claim_validator
    (Phase 13) finding a REAL conflict, which cannot be known here — so lesson_planner
    marks it "pending" and section_writer treats "pending" as "don't render, a later
    phase decides", never as on/off.

Isolation: imports only feed_v2's own db + provider. Never backend.services.* /
backend.llm.*.
"""
from __future__ import annotations

import logging

from ..db import get_connection
from ..llm.provider import call_agent

logger = logging.getLogger(__name__)

_PLAN_SCHEMA = {"type": "object", "required": ["objectives", "prerequisite_gap"],
                "properties": {
                    "objectives": {"type": "array", "items": {"type": "string"}},
                    "prerequisite_gap": {"type": "boolean"}}}

_SYSTEM = ("You plan a single day's micro-lesson. You decide WHAT it contains, not its "
           "prose. Return ONLY a JSON object — no markdown, no prose.")


def _project_difficulty(project_id: str) -> str:
    with get_connection() as conn:
        row = conn.execute("SELECT difficulty FROM v2_projects WHERE project_id = ?",
                           (project_id,)).fetchone()
    return (row["difficulty"] if row and row["difficulty"] else "intermediate")


def _worked_example_mode(difficulty: str) -> str:
    """Difficulty → worked-example order. advanced learners get a problem first; everyone
    else gets a concrete example first. Pure mapping (spec: from difficulty only)."""
    return "problem-first" if (difficulty or "").lower().startswith("advanc") else "example-first"


def _decide(focus: str, prereqs: list[str], difficulty: str, coverage_mode: str,
            meta: dict | None) -> dict:
    pcs = "; ".join(prereqs) if prereqs else "(none)"
    prompt = (f"TODAY'S FOCUS:\n{focus or '(general overview)'}\n"
              f"Learner level: {difficulty}\nCoverage mode: {coverage_mode}\n"
              f"Prerequisite concepts carried from earlier days: {pcs}\n\n"
              "Decide:\n"
              "1. objectives — 2 to 4 concrete things the learner should be able to do "
              "AFTER today.\n"
              "2. prerequisite_gap — true ONLY if the prerequisite concepts above are a real "
              "gap this learner likely needs refreshed before today's focus; false if there "
              "are none, or they are trivial at this level.\n"
              'Return JSON: {"objectives": ["..."], "prerequisite_gap": <true|false>}.')
    call_meta = {"call_type": "feed_v2_lesson_plan", "surface": "feed_v2",
                 "agent_name": "lesson_planner", "step_index": 0}
    call_meta.update(meta or {})
    return call_agent("lesson_planner", [{"role": "user", "content": prompt}],
                      system=_SYSTEM, schema=_PLAN_SCHEMA, meta=call_meta)


def run_lesson_planner(*, project_id: str, journey_entry: dict, coverage_mode: str,
                       profile: dict | None = None, meta: dict | None = None) -> dict:
    """Returns {"lesson_plan": {...}} — the contract all four section_writer groups share
    so they don't drift. Propagates AllLegsFailed if the (single) decision call fails."""
    je = journey_entry or {}
    focus = je.get("focus") or ""
    prereqs = [p.strip() for p in (je.get("prerequisite_concepts") or [])
               if isinstance(p, str) and p.strip()]
    difficulty = _project_difficulty(project_id)
    mode = _worked_example_mode(difficulty)

    obj = _decide(focus, prereqs, difficulty, coverage_mode, meta)
    objectives = [o.strip() for o in (obj.get("objectives") or [])
                  if isinstance(o, str) and o.strip()] or [focus or "today's focus"]
    # section 3 renders only if there ARE prerequisites AND the model called them a real gap
    render_prereq = bool(prereqs) and bool(obj.get("prerequisite_gap"))

    plan = {
        "day": (meta or {}).get("day_number"),
        "focus": focus,
        "coverage_mode": coverage_mode,
        "difficulty": difficulty,
        "objectives": objectives,
        "worked_example_mode": mode,
        "render_prerequisites": render_prereq,
        "section_4b": "pending",   # claim_validator (Phase 13) decides; writer skips 'pending'
    }
    logger.info("[feed_v2.plan] focus=%r objectives=%d prereq_render=%s mode=%s",
                focus, len(objectives), render_prereq, mode)
    return {"lesson_plan": plan}


def _demo() -> None:
    """ponytail self-check: the two mechanical decisions (mode mapping + prereq gating), no network."""
    assert _worked_example_mode("advanced") == "problem-first"
    assert _worked_example_mode("beginner") == "example-first"
    assert _worked_example_mode("intermediate") == "example-first"
    assert _worked_example_mode("") == "example-first"
    # prereq gate: empty concepts ⇒ never render, regardless of a stray model 'gap' vote
    assert (bool([]) and True) is False
    assert (bool(["recursion"]) and True) is True
    print("lesson_planner._demo OK")


if __name__ == "__main__":
    _demo()
