"""
Feed v2 journey planner agent (Phase 6).

Produces one day-wise batch of a project's curriculum. Runs once per batch
(7-20 days, or a document's chapter count in material_bound mode), NOT once per
lesson — a different frequency and role from the Phase-7 daily lesson_planner.

Ported from legacy journey_planner_service, with the parts that worked kept and
the parts Phase 6 changes rebuilt:

  * SHAPE DECISION — legacy's "would they say I learned it, or I'm staying current
    on it" 90-day test is ported verbatim in spirit (it worked); it decides
    fixed_sequence vs rotating_theme.
  * SHAPE LOCK — handled by the caller (journeys.py): once journey_shape is set and
    the description is unchanged, it passes locked_shape and we skip re-deciding.
  * COVERAGE_MODE CHANGES WHAT FEEDS THE PLANNER (the new Phase-6 work, not in
    legacy): see _build_prompt.
      - material_bound   : the document's structure_json IS the curriculum — one day
                           per section, in the section's own order. Mapping, not
                           inventing. Shape is fixed_sequence by definition (a bounded
                           document has an endpoint) and day_count = the actual section
                           count, UNCLAMPED (see journeys.py note on the [7,20] call).
      - material_anchored: material_scope seeds the plan; the planner expands BEYOND it
                           with its own knowledge. Clamped [7,20].
      - open             : legacy behavior — planner's own curriculum knowledge, no
                           material constraint. Clamped [7,20].
  * PREREQUISITE_CONCEPTS per day (new field, feeds Phase 10 later): concepts a
    learner should already know before this day, drawn from EARLIER days in the same
    plan. Day 1 has none; a day never references a later day.
  * NO SILENT FALLBACK — legacy wrote a fake minimal rotating_theme plan on any
    failure. This does NOT. Provider failure (AllLegsFailed) or an invalid/parse
    failure (ValueError) propagates; the caller records journey_status='failed' and
    writes no plan row.

Isolation: imports only ..llm.provider; never backend.services.* / backend.llm.*.
"""
from __future__ import annotations

import logging

from ..llm.provider import AllLegsFailed, call_agent  # noqa: F401 (AllLegsFailed re-exported)

logger = logging.getLogger(__name__)

MIN_DAYS = 7
MAX_DAYS = 20
_FRAME_HINTS = "timeline / comparison / single-discovery-story"

_SYSTEM = (
    "You are a learning journey architect. You design the day-by-day shape of a "
    "learning project. Return ONLY a JSON object — no prose, no markdown fences."
)

_DAY_SCHEMA = """Each day entry has this shape:
{
  "day_number": <int>,
  "focus": "internal retrieval focus — specific enough to guide search queries",
  "display_title": "short polished title shown to the learner",
  "frame_hint": "one of: timeline / comparison / single-discovery-story",
  "prerequisite_concepts": ["concepts from EARLIER days in THIS plan the learner should already know; day 1 is []; never reference a later day"],
  "rationale": "why this day sits here in the sequence"
}"""


def _profile_block(profile: dict, difficulty: str) -> str:
    return (
        f"Subject:  {profile.get('learning_subject') or ''}\n"
        f"Persona:  {profile.get('persona') or 'Learner'}\n"
        f"Goal:     {profile.get('goal') or ''}\n"
        f"Focus:    {profile.get('primary_focus') or ''}\n"
        f"Lens:     {profile.get('search_lens') or 'Educational'}\n"
        f"Level:    {difficulty or 'intermediate'}"
    )


def _covered_block(covered_concepts: list[str] | None) -> str:
    if covered_concepts:
        return ("Concepts already covered (do NOT repeat as primary focus):\n"
                + "\n".join(f"  - {c}" for c in covered_concepts[:30]))
    return "No concepts covered yet — this is the first batch."


def _build_prompt(*, coverage_mode: str, profile: dict, difficulty: str,
                  chapters: list[str], material_scope: str, keywords: list[str],
                  covered_concepts: list[str] | None, day_start: int,
                  locked_shape: str | None) -> str:
    prof = _profile_block(profile, difficulty)
    covered = _covered_block(covered_concepts)
    kw = ", ".join(keywords) if keywords else "(none)"

    # ── material_bound: MAP the document structure to days, in order ──────────────
    if coverage_mode == "material_bound" and chapters:
        listing = "\n".join(f"  Day {day_start + i}: {title}" for i, title in enumerate(chapters))
        return f"""You are MAPPING an existing structured document into a day-by-day sequence.
The learner's uploaded material defines the curriculum. Follow its section order
EXACTLY — one day per section, in the SAME order. Do NOT add, drop, merge, split,
or reorder sections. This is mapping, not inventing.

=== LEARNER PROFILE ===
{prof}
Keywords: {kw}

=== DOCUMENT SECTIONS IN ORDER ({len(chapters)} sections) ===
{listing}

Produce exactly {len(chapters)} day entries, one per section above, numbered from
{day_start} in that order. shape = "fixed_sequence". day_count = {len(chapters)}.
frame_hint must be one of: {_FRAME_HINTS}
prerequisite_concepts: concepts from EARLIER days in this plan; day {day_start} is [].

{_DAY_SCHEMA}

Return ONLY valid JSON:
{{"shape": "fixed_sequence", "day_count": {len(chapters)}, "reasoning": "one line",
  "days": [ ...{len(chapters)} entries... ]}}"""

    # ── locked continuation (shape already decided, description unchanged) ─────────
    if locked_shape == "fixed_sequence":
        anchor = _anchor_block(coverage_mode, material_scope)
        return f"""You are continuing an existing fixed_sequence learning journey.
THE SHAPE IS ALREADY DECIDED: fixed_sequence. Do NOT re-decide. Plan only the next batch.

=== LEARNER PROFILE ===
{prof}
Keywords: {kw}
{anchor}
=== COVERED SO FAR ===
{covered}

Starting from day {day_start}, choose how many days to cover (between {MIN_DAYS} and {MAX_DAYS}).
Generate exactly that many day entries, numbered from {day_start}.
frame_hint must be one of: {_FRAME_HINTS}

{_DAY_SCHEMA}

Return ONLY valid JSON:
{{"shape": "fixed_sequence", "day_count": <int>, "reasoning": "one line", "days": [ ... ]}}"""

    if locked_shape == "rotating_theme":
        return f"""You are refreshing an existing rotating_theme learning journey.
THE SHAPE IS ALREADY DECIDED: rotating_theme. Do NOT re-decide. Plan the next rotation.

=== LEARNER PROFILE ===
{prof}
Keywords: {kw}

=== COVERED SO FAR ===
{covered}

Starting from day {day_start}, choose how many days this rotation covers (between {MIN_DAYS} and {MAX_DAYS}).
List 3-6 themes, set trusted source domains, write a display_summary.

Return ONLY valid JSON:
{{"shape": "rotating_theme", "day_count": <int>, "reasoning": "one line",
  "themes": [{{"name": "...", "description": "..."}}],
  "trusted_sources": ["example.com"], "display_summary": "Currently tracking: ..."}}"""

    # ── full decision (shape not set yet, or description changed) ──────────────────
    anchor = _anchor_block(coverage_mode, material_scope)
    return f"""You are a learning journey architect. Decide what KIND of journey this
project needs, then plan the next batch of days.

=== LEARNER PROFILE ===
{prof}
Keywords: {kw}
{anchor}
=== COVERED SO FAR ===
{covered}

=== STEP 1: DECIDE THE JOURNEY SHAPE ===
Imagine this learner follows this project for 90 days, then stops.
Would they say "I learned it" — reaching a real endpoint, even though more could
always be learned? Or "I'm staying current on it" — where stopping was the only
ending, because the subject has no finish line?
The first is fixed_sequence. The second is rotating_theme.
A subject having both stable fundamentals and a fast-moving frontier does NOT by
itself mean rotating_theme — only the way the request is framed does.
"Teach me AI fundamentals" is fixed_sequence. "Keep me current on AI" or
"stay current on AI research" is rotating_theme, even though AI has stable
fundamentals too.

=== STEP 2: PLAN THE BATCH ===
Starting from day {day_start}, choose how many days this batch covers (between {MIN_DAYS} and {MAX_DAYS}).
For technical subjects with many foundational concepts, prefer the higher end
rather than stopping short of the scope the request implies.

If fixed_sequence: generate exactly that many day entries, numbered from {day_start}.
  frame_hint one of: {_FRAME_HINTS}
{_DAY_SCHEMA}

If rotating_theme: list 3-6 themes, define trusted source domains, write display_summary.

Return ONLY valid JSON for your chosen shape:
fixed_sequence: {{"shape":"fixed_sequence","day_count":<int>,"reasoning":"...","days":[ ... ]}}
rotating_theme: {{"shape":"rotating_theme","day_count":<int>,"reasoning":"...","themes":[{{"name":"...","description":"..."}}],"trusted_sources":["example.com"],"display_summary":"..."}}"""


def _anchor_block(coverage_mode: str, material_scope: str) -> str:
    if coverage_mode == "material_anchored" and material_scope:
        return (f"\n=== MATERIAL ANCHOR (seed, then EXPAND beyond it) ===\n"
                f"The learner uploaded material covering: {material_scope}\n"
                f"Use this as the STARTING anchor, then expand BEYOND it with your own "
                f"knowledge of the subject to build a complete journey — do not stop at "
                f"what the uploaded material alone covers.\n")
    return ""


def run_journey_plan(*, coverage_mode: str, profile: dict, difficulty: str,
                     chapters: list[str], material_scope: str, keywords: list[str],
                     covered_concepts: list[str] | None, day_start: int,
                     locked_shape: str | None = None, meta: dict | None = None) -> dict:
    """Plan one batch. Returns a batch dict with shape/day_count/day_start/day_end +
    body (days[] or themes[]). Raises on failure — NO fake fallback plan."""
    prompt = _build_prompt(
        coverage_mode=coverage_mode, profile=profile, difficulty=difficulty,
        chapters=chapters, material_scope=material_scope, keywords=keywords or [],
        covered_concepts=covered_concepts, day_start=day_start, locked_shape=locked_shape)

    call_meta = {"call_type": "feed_v2_journey_planner", "surface": "feed_v2",
                 "agent_name": "journey_planner", "day_number": day_start}
    call_meta.update(meta or {})

    batch = call_agent("journey_planner", [{"role": "user", "content": prompt}],
                       system=_SYSTEM, meta=call_meta)

    shape = batch.get("shape")
    if shape not in ("fixed_sequence", "rotating_theme"):
        raise ValueError(f"journey_planner returned unknown shape {shape!r}")

    material_mapped = coverage_mode == "material_bound" and bool(chapters)
    if material_mapped:
        # material_bound: the DOCUMENT defines length + order. day_count = section
        # count, UNCLAMPED. Bind each day to its section by position so day order
        # provably tracks structure_json order regardless of the model's phrasing.
        shape = "fixed_sequence"
        batch["shape"] = shape
        # One day per section, in section order. Truncate any extra days the model
        # emitted beyond the section count (the document defines the length).
        days = (batch.get("days") or [])[:len(chapters)]
        for i, title in enumerate(chapters):
            if i < len(days):
                days[i]["day_number"] = day_start + i
                days[i]["source_section"] = title
        # material_bound ONLY: dropping chapters is not a degraded success, it's a
        # wrong plan — the mode's whole premise is document fidelity. If the model
        # under-emits, fail loudly (caller marks journey_status='failed', writes no
        # plan, and a re-POST retries the whole generation) rather than silently
        # repeating the last entry for the missing days. (truncation above means
        # len(days) can only be < or == len(chapters), never >.)
        if len(days) < len(chapters):
            raise ValueError(
                f"material_bound plan dropped chapters: {len(days)} day entries for "
                f"{len(chapters)} sections")
        batch["days"] = days
        day_count = len(chapters)
    else:
        day_count = max(MIN_DAYS, min(MAX_DAYS, int(batch.get("day_count") or MIN_DAYS)))

    # Body must be real — an empty fixed_sequence / themeless rotation is a failure,
    # not a plan. (No silent acceptance of a shell.)
    if shape == "fixed_sequence" and not batch.get("days"):
        raise ValueError("fixed_sequence plan has no day entries")
    if shape == "rotating_theme" and not batch.get("themes"):
        raise ValueError("rotating_theme plan has no themes")

    if shape == "fixed_sequence":
        # The batch covers day_start..day_end — enforce that numbering rather than
        # trusting the model's day_number, and drop any days past day_count.
        days = batch["days"][:day_count]
        for i, entry in enumerate(days):
            entry["day_number"] = day_start + i
            entry.setdefault("prerequisite_concepts", [])
        batch["days"] = days

    batch["day_count"] = day_count
    batch["day_start"] = day_start
    batch["day_end"] = day_start + day_count - 1
    logger.info("[feed_v2.journey_planner] shape=%s day_count=%d (%s) days %d-%d",
                shape, day_count, coverage_mode, batch["day_start"], batch["day_end"])
    return batch
