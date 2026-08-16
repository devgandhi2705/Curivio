"""
Journey Planner Service

Decides fixed_sequence vs rotating_theme for a project's learning journey,
then generates day-by-day or theme-based plans in batches.

A batch covers day_start..day_end inclusive. get_today_plan() triggers a new
batch automatically when none covers the requested day.

Public API
----------
plan_journey(project_id, intent_profile, keywords, covered_concepts,
             day_start)                                                -> dict
save_journey_plan(project_id, batch, description_hash)                 -> None
get_today_plan(project_id, day_number, intent_profile, keywords)       -> dict
"""
from __future__ import annotations

import hashlib
import json
import logging
import re

logger = logging.getLogger(__name__)

_MIN_DAYS = 7
_MAX_DAYS = 20

_GEMINI_PRIMARY  = "models/gemini-2.5-flash"
# gemini-3.5-flash disqualified: reproducible response-corruption bug (extra trailing brace)
# observed on fixed_sequence prompts during Phase 2a evaluation — do not reinstate without re-eval.


def _call_llm(prompt: str, project_id: str, day_ref: int, trace_id: str | None = None) -> str:
    """Gemini-primary / Groq-fallback via the shared backend/llm factory."""
    from ..llm import get_chat_model, extract_text
    model = get_chat_model(model=_GEMINI_PRIMARY, json_mode=True)
    resp  = model.invoke(prompt, config={"metadata": {
        "call_type": "feed_journey_planner", "project_id": project_id, "day_ref": day_ref,
        "trace_id": trace_id, "surface": "feed_legacy", "agent_name": "journey_planner",
    }})
    return extract_text(resp)


def _hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def _extract_json(text: str) -> dict:
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start:end + 1])
    return json.loads(text.strip())


_SCHEMA_FIXED = """{
  "shape": "fixed_sequence",
  "day_count": 10,
  "reasoning": "One line on why this is a learnable, reachable subject.",
  "days": [
    {
      "day_number": 1,
      "focus": "Internal retrieval focus — specific enough to guide search queries",
      "display_title": "Short polished title shown to user",
      "frame_hint": "timeline",
      "rationale": "Why this day sits here in the sequence"
    }
  ]
}"""

_SCHEMA_ROTATING = """{
  "shape": "rotating_theme",
  "day_count": 14,
  "reasoning": "One line on why this subject has no learnable endpoint.",
  "themes": [
    {"name": "Funding & M&A",       "description": "Who is raising and acquiring, and why"},
    {"name": "Model Releases",       "description": "New capability jumps and benchmarks"},
    {"name": "Policy & Regulation",  "description": "Regulatory moves affecting the space"}
  ],
  "trusted_sources": ["techcrunch.com", "reuters.com", "arxiv.org"],
  "display_summary": "Currently tracking: Funding & M&A, Model Releases, Policy"
}"""


def _build_prompt(
    intent_profile:   dict,
    keywords:         list[str],
    covered_concepts: list[str] | None,
    day_start:        int,
    locked_shape:     str | None = None,
) -> str:
    name        = intent_profile.get("learning_subject") or ""
    persona     = intent_profile.get("persona")          or "Learner"
    goal        = intent_profile.get("goal")             or ""
    search_lens = intent_profile.get("search_lens")      or "Educational"
    kw_str      = ", ".join(keywords) if keywords else "(none)"

    if covered_concepts:
        covered_str = (
            "Concepts already covered (do NOT repeat these as primary focus):\n"
            + "\n".join(f"  - {c}" for c in covered_concepts[:30])
        )
    else:
        covered_str = "No concepts covered yet — this is the first batch."

    profile_block = (
        f"Subject:      {name}\n"
        f"Persona:      {persona}\n"
        f"Goal:         {goal}\n"
        f"Lens:         {search_lens}\n"
        f"Keywords:     {kw_str}"
    )

    if locked_shape == "fixed_sequence":
        return f"""You are a learning journey architect continuing an existing fixed_sequence learning journey.

THE SHAPE IS ALREADY DECIDED: fixed_sequence
Do NOT redecide this. Generate only the next batch of day entries.

=== LEARNER PROFILE ===
{profile_block}

=== COVERED SO FAR ===
{covered_str}

=== PLAN THE NEXT BATCH ===
Starting from day {day_start}, decide how many days to cover (between {_MIN_DAYS} and {_MAX_DAYS}).
If the subject has many distinct foundational concepts a learner must reach before applied or advanced material (technical subjects like programming, mathematics, or the sciences), prefer the higher end of the range rather than defaulting to a shorter plan that stops before the full scope implied by the request is covered.
Generate exactly that many day entries, numbered starting from {day_start}.
frame_hint must be one of: timeline / comparison / single-discovery-story

Return ONLY a valid JSON object:
{_SCHEMA_FIXED}"""

    if locked_shape == "rotating_theme":
        return f"""You are a learning journey architect refreshing a rotating_theme learning journey.

THE SHAPE IS ALREADY DECIDED: rotating_theme
Do NOT redecide this. Plan the next rotation batch.
You may keep, update, or replace themes based on what has been covered.

=== LEARNER PROFILE ===
{profile_block}

=== COVERED SO FAR ===
{covered_str}

=== PLAN THE NEXT BATCH ===
Starting from day {day_start}, decide how many days this rotation covers (between {_MIN_DAYS} and {_MAX_DAYS}).
List 3–6 themes, update trusted source domains if needed, write a display_summary.

Return ONLY a valid JSON object:
{_SCHEMA_ROTATING}"""

    # Full decision prompt — shape not yet set or description changed
    return f"""You are a learning journey architect. Decide what kind of learning journey this project needs, then plan the next batch of days.

=== LEARNER PROFILE ===
{profile_block}

=== COVERED SO FAR ===
{covered_str}

=== STEP 1: DECIDE THE JOURNEY SHAPE ===

Imagine this learner follows this project for 90 days, then stops.
Would they say "I learned it" — reaching a real endpoint, even though more could always be learned?
Or would they say "I'm staying current on it" — where stopping was the only ending, because the subject has no finish line?

The first case is fixed_sequence. The second is rotating_theme.

A topic having both stable fundamentals and a fast-moving frontier does NOT by itself mean rotating_theme — only the way the request is framed does.
"Teach me AI fundamentals" is fixed_sequence.
"Keep me current on AI" or "latest AI trends" is rotating_theme, even though AI also has stable fundamentals.

=== STEP 2: PLAN THE BATCH ===

Starting from day {day_start}, decide how many days this batch should cover (between {_MIN_DAYS} and {_MAX_DAYS}).
If the subject has many distinct foundational concepts a learner must reach before applied or advanced material (technical subjects like programming, mathematics, or the sciences), prefer the higher end of the range rather than defaulting to a shorter plan that stops before the full scope implied by the request is covered.

If fixed_sequence: generate exactly that many day entries, numbered starting from {day_start}.
  frame_hint must be one of: timeline / comparison / single-discovery-story

If rotating_theme: list 3–6 themes to rotate through, define trusted source domains, write a display_summary.

Return ONLY a valid JSON object matching the schema for your chosen shape:

fixed_sequence schema:
{_SCHEMA_FIXED}

rotating_theme schema:
{_SCHEMA_ROTATING}"""


def plan_journey(
    project_id:       str,
    intent_profile:   dict,
    keywords:         list[str],
    covered_concepts: list[str] | None = None,
    day_start:        int = 1,
    description_hash: str = "",
    trace_id:         str | None = None,
) -> dict:
    """Call the LLM to plan a journey batch. Retries once on JSON parse failure.
    On double failure returns a minimal rotating_theme fallback derived from
    the intent profile — never blocks generation.

    If journey_shape is already set on the project AND description_hash matches
    the last saved batch, skips the 90-day shape-decision test and gives the AI
    a continuation prompt locked to the existing shape."""
    locked_shape: str | None = None
    try:
        from ..utils.db import get_connection
        with get_connection() as conn:
            proj_row = conn.execute(
                "SELECT journey_shape FROM learning_projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            if proj_row and proj_row["journey_shape"]:
                last_batch = conn.execute(
                    """SELECT description_hash FROM journey_plans
                       WHERE project_id = ? ORDER BY created_at DESC LIMIT 1""",
                    (project_id,),
                ).fetchone()
                if last_batch and last_batch["description_hash"] == description_hash:
                    locked_shape = proj_row["journey_shape"]
                else:
                    logger.info(
                        "[journey_planner] project=%r description changed — re-deciding shape",
                        project_id,
                    )
    except Exception:
        pass  # non-fatal: proceed with full decision if DB check fails

    prompt = _build_prompt(intent_profile, keywords, covered_concepts, day_start, locked_shape=locked_shape)
    try:
        text = _call_llm(prompt, project_id, day_start, trace_id=trace_id)
        try:
            batch = _extract_json(text)
        except (json.JSONDecodeError, ValueError):
            logger.warning("[journey_planner] project=%r JSON parse failed — retrying once", project_id)
            text  = _call_llm(
                prompt + "\n\nIMPORTANT: Return ONLY valid JSON, no other text.",
                project_id, day_start, trace_id=trace_id,
            )
            batch = _extract_json(text)

        shape = batch.get("shape")
        if shape not in ("fixed_sequence", "rotating_theme"):
            raise ValueError(f"Unknown shape in LLM response: {shape!r}")

        raw_count = int(batch.get("day_count") or _MIN_DAYS)
        day_count = max(_MIN_DAYS, min(_MAX_DAYS, raw_count))
        batch["day_count"] = day_count
        batch["day_start"] = day_start
        batch["day_end"]   = day_start + day_count - 1

        return batch

    except Exception as e:
        logger.error(
            "[journey_planner] planning failed for %r: %s — returning minimal fallback",
            project_id, e,
        )
        primary_focus = (
            intent_profile.get("primary_focus")
            or (keywords[0] if keywords else "Core Concepts")
        )
        return {
            "shape":         "rotating_theme",
            "day_count":     _MIN_DAYS,
            "day_start":     day_start,
            "day_end":       day_start + _MIN_DAYS - 1,
            "reasoning":     "Fallback — planning call failed.",
            "themes":        [{"name": primary_focus, "description": f"Explore {primary_focus}"}],
            "trusted_sources": [],
            "display_summary": f"Currently tracking: {primary_focus}",
        }


def save_journey_plan(project_id: str, batch: dict, description_hash: str) -> None:
    """Persist batch to journey_plans and update journey_shape on the project row."""
    from ..utils.db import get_connection
    shape     = batch["shape"]
    day_start = batch["day_start"]
    day_end   = batch["day_end"]
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO journey_plans
               (project_id, shape, day_start, day_end, plan_content, description_hash)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (project_id, shape, day_start, day_end, json.dumps(batch), description_hash),
        )
        conn.execute(
            "UPDATE learning_projects SET journey_shape = ? WHERE project_id = ?",
            (shape, project_id),
        )


def get_today_plan(
    project_id:     str,
    day_number:     int,
    intent_profile: dict | None      = None,
    keywords:       list[str] | None = None,
    trace_id:       str | None       = None,
) -> dict:
    """Return the plan entry for day_number.

    If no batch covers this day_number, triggers plan_journey, saves the result,
    then returns the entry. Never returns None.
    """
    from ..utils.db import get_connection

    def _fetch_batch(day_num: int):
        with get_connection() as conn:
            return conn.execute(
                """SELECT * FROM journey_plans
                   WHERE project_id = ? AND day_start <= ? AND day_end >= ?
                   ORDER BY created_at DESC LIMIT 1""",
                (project_id, day_num, day_num),
            ).fetchone()

    row = _fetch_batch(day_number)

    if row is None:
        if intent_profile is None:
            logger.error(
                "[journey_planner] get_today_plan: no batch and no intent_profile for %r — "
                "returning generic entry",
                project_id,
            )
            return _generic_entry(day_number)

        # Find where next batch should start (max day_end across all batches + 1, or 1).
        # If day_number is far beyond that natural next day, jump day_start forward so
        # the new batch can still reach it in one shot, leaving the skipped days as a
        # legitimate gap — the lazy-regen trigger above (day outside any batch range)
        # plans them on demand if ever requested.
        with get_connection() as conn:
            latest = conn.execute(
                "SELECT MAX(day_end) AS max_end FROM journey_plans WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        natural_start = (latest["max_end"] + 1) if (latest and latest["max_end"] is not None) else day_number
        day_start = max(natural_start, day_number - _MAX_DAYS + 1)

        # Pull covered concepts from learning memory (non-fatal if absent)
        covered_concepts: list[str] | None = None
        try:
            with get_connection() as conn:
                mem = conn.execute(
                    "SELECT covered_concepts FROM project_learning_memory WHERE project_id = ?",
                    (project_id,),
                ).fetchone()
            if mem and mem["covered_concepts"]:
                covered_concepts = json.loads(mem["covered_concepts"])
        except Exception:
            pass

        # Use the same description_hash as intent_profile regeneration so the
        # shape-lock check and the intent regeneration check stay in sync.
        desc_hash = (
            intent_profile.get("_meta", {}).get("description_hash", "")
            or _hash(intent_profile.get("intent_summary", ""))
        )
        # Plan a single batch covering day_number. If the LLM returns a shorter
        # day_count than _MAX_DAYS, day_start may still land short of day_number —
        # retry once with day_start = day_number exactly, which always covers it
        # (day_count >= _MIN_DAYS >= 1). Bounded at 2 calls, not one per skipped batch.
        batch = plan_journey(
            project_id, intent_profile, keywords or [],
            covered_concepts=covered_concepts,
            day_start=day_start,
            description_hash=desc_hash,
            trace_id=trace_id,
        )
        save_journey_plan(project_id, batch, desc_hash)
        row = _fetch_batch(day_number)

        if row is None and day_start != day_number:
            batch = plan_journey(
                project_id, intent_profile, keywords or [],
                covered_concepts=covered_concepts,
                day_start=day_number,
                description_hash=desc_hash,
                trace_id=trace_id,
            )
            save_journey_plan(project_id, batch, desc_hash)
            row = _fetch_batch(day_number)

        if row is None:
            logger.warning(
                "[journey_planner] day %d still outside batch after planning for %r",
                day_number, project_id,
            )
            return _generic_entry(day_number)

    batch = json.loads(row["plan_content"])
    shape = row["shape"]

    if shape == "fixed_sequence":
        days = batch.get("days") or []
        for entry in days:
            if entry.get("day_number") == day_number:
                return entry
        # day_number not explicitly in list — return last entry rather than error
        return days[-1] if days else _generic_entry(day_number)

    # rotating_theme — deterministic rotation from batch's day_start
    themes = batch.get("themes") or []
    if not themes:
        return _generic_entry(day_number)
    idx = (day_number - row["day_start"]) % len(themes)
    return {
        "day_number":      day_number,
        "theme":           themes[idx],
        "display_summary": batch.get("display_summary", ""),
        "trusted_sources": batch.get("trusted_sources", []),
    }


def _generic_entry(day_number: int) -> dict:
    return {
        "day_number":    day_number,
        "focus":         "General exploration",
        "display_title": "Today's Learning",
        "frame_hint":    "single-discovery-story",
        "rationale":     "Fallback — no journey plan available",
    }
