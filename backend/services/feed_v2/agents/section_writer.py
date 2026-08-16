"""
Feed v2 section writer (Phase 11) — writes today's lesson in FOUR groups, each its own
LLM call, all sharing the SAME lesson-plan contract (Task 1) so they don't drift.

GROUPS (this phase writes sections 1-9 except 4b):
  A: sections 1-3  — why today / where this sits / prerequisites (3 only if the plan says)
  B: sections 4-5  — the core explanation + worked example (order from the plan's mode)
  C: sections 6-7  — 2-3 retrieval questions + expected answers, ALSO written to
                     v2_retrieval_checks (machine-readable Q/A alongside the beats)
  D: sections 8-9  — going deeper + curiosity threads
NOT written here (stated boundary): section 4b (source conflict) waits on claim_validator
(Phase 13); section 10 (sources) is the assembler's job (Phase 14) reading final tiers.

BEATS: every section's content is an ARRAY OF BEATS — {heading, body, visual?, citations}
— not flat text. Reading mode concatenates beats; slide mode paginates them (Phase 16).
This shape exists from the start, not retrofitted.

CONTENT CONSUMPTION: each group receives ONLY the sources relevant to ITS sections, not
the full ranked list. Routing (see _route): protected (material_bound) findings are FORCED
into the framing + core groups regardless of rank — Phase 10c lets a protected corpus
source keep an honest low score, which would otherwise sort it into "deeper" (D) and leave
the learner's own material uncited. Full content is used (web = Phase 9c deduped `content`,
corpus = real chunk text), bounded to the writer model's input budget with budget.py — one
narrative per section, so an oversized group packs rank-ordered (dropping the lowest-ranked
in-group source) instead of splitting prose across calls; overflow never fires at ~225k.

CITATIONS: sources get ids s1..sN by final rank order (s1 = top). Every claim carries inline
[sid] markers AND the beat lists those ids in `citations` — the machine-checkable form
claim_validator (Phase 13) validates and the assembler (Phase 14) reverse-maps.

PERSIST PER GROUP: each group writes to v2_section_drafts the instant it finishes (keyed by
project/day/attempt/group). A crash after group B re-runs the node, loads A/B from the DB,
and writes only C/D — sub-node crash-resume without a graph structure change. `attempt` =
section_writer_runs+1 at entry: stable across a crash, incremented on a rewrite.

Isolation: imports only feed_v2's own db/provider/budget. Never backend.services.* /
backend.llm.*.
"""
from __future__ import annotations

import json
import logging

from ..budget import count_tokens, input_budget
from ..db import get_connection
from ..llm.provider import AllLegsFailed, call_agent  # noqa: F401  (re-exported for callers)

logger = logging.getLogger(__name__)

GROUPS = ["A", "B", "C", "D"]
WRITER_MODEL = "gemini-3-flash-preview"   # section_writer primary; per-group source budget sized by it
_WRITE_OVERHEAD_TOKENS = 4000             # reserve for the prompt scaffold + beats JSON output
_CORE_TOP_K = 6                           # non-protected sources routed to the core group by rank

# None ⇒ derive per-call source budget from budget.py. Tests set a small int to force packing.
_WRITE_CALL_TOKENS: int | None = None

_BEATS_SCHEMA = {"type": "object", "required": ["sections"], "properties": {
    "sections": {"type": "array", "items": {"type": "object",
        "required": ["n", "title", "beats"], "properties": {
            "n": {"type": "integer"},
            "title": {"type": "string"},
            "beats": {"type": "array", "items": {"type": "object",
                "required": ["heading", "body", "citations"], "properties": {
                    "heading": {"type": "string"},
                    "body": {"type": "string"},
                    "visual": {"type": "string"},
                    "citations": {"type": "array", "items": {"type": "string"}}}}}}}},
    "checks": {"type": "array", "items": {"type": "object", "properties": {
        "question": {"type": "string"}, "expected": {"type": "string"}}}}}}

_SYS = {
    "A": ("You write the OPENING of a daily micro-lesson: why this matters today, where it "
          "sits in the bigger picture, and (only when asked) a quick prerequisite refresher. "
          "Framing and motivation, not deep teaching. Return ONLY JSON."),
    "B": ("You write the CORE of a daily micro-lesson: the main explanation and one worked "
          "example. This is the teaching heart — concrete, rigorous, clear. Return ONLY JSON."),
    "C": ("You write ACTIVE-RECALL checks: 2-3 retrieval questions with expected answers that "
          "test the core idea just taught. Force recall, not recognition. Return ONLY JSON."),
    "D": ("You write the CONTINUATION: going deeper and curiosity threads that point a "
          "motivated learner onward. Suggestive and open, not exhaustive. Return ONLY JSON."),
}


# ── source id + routing ───────────────────────────────────────────────────────
def _source_text(s: dict) -> str:
    """The full content a group writes FROM: web → Phase 9c deduped `content`, else the
    best available text field."""
    if s.get("src") == "web":
        c = s.get("content")
        if isinstance(c, str) and c.strip():
            return c.strip()
    for k in ("text", "title", "snippet", "url"):
        v = s.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _assign_ids(ranked: list) -> list[dict]:
    """s1..sN by final rank order (input is already sorted by source_ranker)."""
    out: list[dict] = []
    n = 0
    for s in ranked or []:
        if isinstance(s, dict) and _source_text(s):
            n += 1
            out.append({**s, "source_id": s.get("source_id") or f"s{n}"})
    return out


def _route(sources: list[dict]) -> dict[str, list[dict]]:
    """Assign each source to the group(s) that cover its topic. protected sources are FORCED
    into framing (A) + core (B/C) regardless of rank so the learner's own material is always
    cited where it's covered — the whole point of Phase 10c's protected flag."""
    protected = [s for s in sources if s.get("protected")]
    rest = [s for s in sources if not s.get("protected")]
    core = protected + rest[:_CORE_TOP_K]
    deeper = rest[_CORE_TOP_K:]
    # framing: protected + the couple top-ranked, de-duped by id, order preserved
    framing, seen = [], set()
    for s in protected + rest[:2]:
        if s["source_id"] not in seen:
            seen.add(s["source_id"])
            framing.append(s)
    return {"A": framing, "B": core, "C": core, "D": deeper}


# ── budget packing (one narrative per section — pack, don't split the prose) ──
def _call_budget() -> int:
    if _WRITE_CALL_TOKENS is not None:
        return _WRITE_CALL_TOKENS
    return max(1, input_budget(WRITER_MODEL) - _WRITE_OVERHEAD_TOKENS)


def _pack(sources: list[dict], budget_tokens: int) -> list[dict]:
    """Bound a group's source payload to the writer's input budget, rank-ordered. Overflow
    drops the lowest-ranked in-group source (never seen at ~225k; forced in tests)."""
    kept, used = [], 0
    for s in sources:
        t = count_tokens(_source_text(s))
        if kept and used + t > budget_tokens:
            break
        kept.append(s)
        used += t
    return kept


# ── section spec per group (gating lives here) ───────────────────────────────
def _sections_for(group: str, plan: dict) -> list[str]:
    mode = plan.get("worked_example_mode") or "example-first"
    if group == "A":
        secs = ["1. Why this matters today", "2. Where this sits in the bigger picture"]
        if plan.get("render_prerequisites"):
            secs.append("3. Prerequisite refresher (the learner has a real gap here)")
        return secs
    if group == "B":
        ex = ("Give a concrete worked example FIRST, then generalize (example-first)"
              if mode == "example-first" else
              "Pose a problem FIRST, then work toward its solution (problem-first)")
        return ["4. The core explanation", f"5. Worked example — {ex}"]
    if group == "C":
        return ["6. Check yourself — 2-3 retrieval questions", "7. Expected answers"]
    if group == "D":
        return ["8. Going deeper", "9. Curiosity threads"]
    return []


def _listing(sources: list[dict]) -> str:
    return "\n\n".join(
        f"[{s['source_id']}] ({s.get('rank_origin') or s.get('src')}) {_source_text(s)}"
        for s in sources)


def _clean_sections(sections) -> list[dict]:
    out = []
    for sec in sections or []:
        if not isinstance(sec, dict):
            continue
        beats = [b for b in (sec.get("beats") or []) if isinstance(b, dict)]
        out.append({"n": sec.get("n"), "title": sec.get("title") or "",
                    "beats": [{"heading": b.get("heading") or "", "body": b.get("body") or "",
                               "visual": b.get("visual"),
                               "citations": [c for c in (b.get("citations") or [])
                                             if isinstance(c, str)]} for b in beats]})
    return out


def _write_group(group: str, plan: dict, sources: list[dict], meta: dict | None):
    """One writing LLM call for a group → (sections, checks|None). Propagates AllLegsFailed
    (a writer outage is a real failure — no silent fake lesson)."""
    packed = _pack(sources, _call_budget())
    listing = _listing(packed) if packed else "(no sources routed here — write from the plan)"
    secs = _sections_for(group, plan)
    focus = plan.get("focus") or ""
    objectives = "; ".join(plan.get("objectives") or [])
    checks_ask = ('\nALSO return "checks": a list of 2-3 {"question": "...", "expected": "..."} '
                  "matching the retrieval questions." if group == "C" else "")
    prompt = (f"TODAY'S FOCUS: {focus or '(general overview)'}\nOBJECTIVES: {objectives}\n\n"
              "WRITE THESE SECTIONS:\n" + "\n".join(secs) + "\n\n"
              f"SOURCES you may cite (reference by their [id]):\n{listing}\n\n"
              "Each section's content is an ARRAY OF BEATS. A beat is "
              '{"heading": "...", "body": "...", "visual": null, "citations": ["<id>", ...]}. '
              "Put inline [id] markers in the body for every factual claim AND list those ids "
              "in that beat's citations. Cite ONLY ids listed above; if a beat needs no source, "
              "use an empty citations list." + checks_ask + "\n"
              'Return JSON: {"sections": [{"n": <int>, "title": "...", "beats": [...]}]'
              + (', "checks": [...]' if group == "C" else "") + "}.")
    call_meta = {"call_type": f"feed_v2_write_{group.lower()}", "surface": "feed_v2",
                 "agent_name": "section_writer", "step_index": 4}
    call_meta.update(meta or {})
    obj = call_agent("section_writer", [{"role": "user", "content": prompt}],
                     system=_SYS[group], schema=_BEATS_SCHEMA, meta=call_meta)
    sections = _clean_sections(obj.get("sections"))
    checks = obj.get("checks") if group == "C" else None
    return sections, checks


# ── per-group persistence (crash-resume) ─────────────────────────────────────
def _load_completed(project_id: str, day: int, attempt: int) -> dict[str, list]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT group_key, sections_json FROM v2_section_drafts "
            "WHERE project_id = ? AND day_number = ? AND attempt = ?",
            (project_id, day, attempt)).fetchall()
    return {r["group_key"]: json.loads(r["sections_json"] or "[]") for r in rows}


def _persist_group(user_id, project_id, day, attempt, group, sections) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO v2_section_drafts"
            "(user_id, project_id, day_number, attempt, group_key, sections_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, project_id, day, attempt, group, json.dumps(sections)))


def _persist_checks(user_id, project_id, checks) -> None:
    rows = [(user_id, project_id, (c.get("question") or "").strip(), (c.get("expected") or "").strip())
            for c in (checks or []) if (c.get("question") or "").strip()]
    if not rows:
        return
    with get_connection() as conn:
        conn.executemany(
            "INSERT INTO v2_retrieval_checks(user_id, project_id, question, expected) "
            "VALUES (?, ?, ?, ?)", rows)


def _tag(sections: list, group: str) -> list[dict]:
    return [{**s, "group": group} for s in sections]


def run_section_writer(*, project_id: str, user_id: str, day_number: int, coverage_mode: str,
                       lesson_plan: dict, ranked_sources: list, section_writer_runs: int = 0,
                       meta: dict | None = None) -> dict:
    """Write (or resume) the four groups. Returns the SAME state keys the stub did:
    {"section_drafts", "section_writer_runs", "rewrite_iters"} — so the rewrite loop
    (claim_validator → section_writer, MAX_REWRITES) keeps working unchanged."""
    attempt = (section_writer_runs or 0) + 1
    plan = lesson_plan or {}
    sources = _assign_ids(ranked_sources or [])
    routed = _route(sources)

    completed = _load_completed(project_id, day_number, attempt)
    drafts: list[dict] = []
    for group in GROUPS:
        if group in completed:                       # crash-resume: already written this attempt
            drafts.extend(_tag(completed[group], group))
            continue
        sections, checks = _write_group(group, plan, routed.get(group, []), meta)
        _persist_group(user_id, project_id, day_number, attempt, group, sections)  # durable NOW
        if group == "C":
            _persist_checks(user_id, project_id, checks)
        drafts.extend(_tag(sections, group))

    logger.info("[feed_v2.write] attempt=%d wrote=%d resumed=%d sections=%d",
                attempt, len(GROUPS) - len(completed), len(completed), len(drafts))
    return {"section_drafts": drafts, "section_writer_runs": attempt, "rewrite_iters": attempt - 1}


def _demo() -> None:
    """ponytail self-check: id assignment, protected routing, budget packing — no network."""
    ranked = [{"src": "web", "content": "aaa", "rank_score": 0.9},
              {"src": "corpus", "text": "own material", "protected": True, "rank_score": 0.0}]
    ided = _assign_ids(ranked)
    assert [s["source_id"] for s in ided] == ["s1", "s2"]
    routed = _route(ided)
    prot = ided[1]
    # protected (bottom-scored) still lands in framing (A) AND core (B), never only deeper
    assert prot in routed["A"] and prot in routed["B"]
    # forced tiny budget → packing keeps only what fits
    global _WRITE_CALL_TOKENS
    _WRITE_CALL_TOKENS = 1
    packed = _pack([{"src": "web", "content": "aaaa"}, {"src": "web", "content": "bbbb"}], _call_budget())
    _WRITE_CALL_TOKENS = None
    assert len(packed) == 1     # second source overflows the 1-token budget
    print("section_writer._demo OK")


if __name__ == "__main__":
    _demo()
