"""
Feed v2 visual director (Phase 12) — decides, per beat, whether a visual would
genuinely help and what kind. Emits a SPEC, not an image: {visual_type, topic}.
visual_sourcing (Task 2/3) turns each spec into a real asset; visual_validator
(Task 4) checks whatever comes out.

ONE call for the whole day's beats (like lesson_planner: cheap, single decision
pass) — a day's beat count is small and fixed (4 groups, a handful of beats
each), so no budget packing is needed here (unlike section_writer's source
packing, which is genuinely unbounded).

INDEX, NOT TRUST: the model sees beats as a numbered list and returns a
decision per index. section_n/beat_index are joined back from the REAL beat
list by that index afterward, never trusted from the model — same pattern
corpus_researcher uses for citation metadata (the model can't hallucinate a
beat that doesn't exist).

Isolation: imports only feed_v2's own provider. Never backend.services.* /
backend.llm.*.
"""
from __future__ import annotations

import logging

from ..llm.provider import AllLegsFailed, call_agent  # noqa: F401  (re-exported for callers)

logger = logging.getLogger(__name__)

VISUAL_TYPES = ("timeline", "comparison", "process", "hierarchy", "before_after", "labelled_parts")

_BODY_PREVIEW_CHARS = 400  # enough for the model to judge visual-worthiness, not a content budget

_SPECS_SCHEMA = {"type": "object", "required": ["specs"],
                 "properties": {"specs": {"type": "array", "items": {
                     "type": "object", "required": ["index", "needs_visual"],
                     "properties": {
                         "index": {"type": "integer"},
                         "needs_visual": {"type": "boolean"},
                         "visual_type": {"type": "string", "enum": list(VISUAL_TYPES)},
                         "topic": {"type": "string"}}}}}}

_SYSTEM = (
    "You decide which beats of a daily micro-lesson genuinely need a visual, and what "
    "kind. A visual EARNS its place only when it would show something a reader grasps "
    "faster from a picture than from the prose already there — a real sequence, a real "
    "comparison, a real structure. Most beats need none. "
    f"visual_type must be one of: {', '.join(VISUAL_TYPES)}. "
    "topic is a short, concrete description of what the visual should depict (used later "
    "to search for a matching figure) — omit it when needs_visual is false. "
    "Return ONLY a JSON object — no prose, no markdown fences."
)


def _flat_beats(section_drafts: list[dict]) -> list[tuple[int, int, str, str, str, list]]:
    """(section_n, beat_index, heading, body, writer_visual_hint, citations) for every
    real beat, in section_drafts order. beat_index is the beat's position WITHIN its
    section. citations passes through untouched — visual_sourcing's Tier 2 uses it to
    find the beat's own cited web sources (never model-decided)."""
    out = []
    for sec in section_drafts or []:
        if not isinstance(sec, dict):
            continue
        n = sec.get("n")
        for bi, b in enumerate(sec.get("beats") or []):
            if not isinstance(b, dict):
                continue
            out.append((n, bi, b.get("heading") or "", b.get("body") or "", b.get("visual") or "",
                        b.get("citations") or []))
    return out


def _listing(beats: list[tuple[int, int, str, str, str, list]]) -> str:
    lines = []
    for i, (n, bi, heading, body, hint, _citations) in enumerate(beats):
        entry = f"[{i}] {heading}\n{body[:_BODY_PREVIEW_CHARS]}"
        if hint:
            entry += f"\nWRITER'S HINT: {hint}"
        lines.append(entry)
    return "\n\n".join(lines)


def run_visual_director(*, section_drafts: list[dict], meta: dict | None = None) -> dict:
    """Decide needs-visual + type per beat. Returns {"visual_specs": [...]}, one entry
    per beat that needs a visual: {section_n, beat_index, visual_type, topic}. Zero
    beats (e.g. an empty draft) is a clean no-op — no LLM call, matching
    corpus_researcher's "no materials -> no call" behaviour. Propagates AllLegsFailed
    if the LLM leg fails (no silent fake specs)."""
    beats = _flat_beats(section_drafts)
    if not beats:
        return {"visual_specs": []}

    prompt = (f"BEATS ({len(beats)}):\n{_listing(beats)}\n\n"
              'Return JSON: {"specs": [{"index": <int>, "needs_visual": <bool>, '
              '"visual_type": "...", "topic": "..."}, ...]} — one entry per beat index above.')
    call_meta = {"call_type": "feed_v2_visual_director", "surface": "feed_v2",
                 "agent_name": "visual_director", "step_index": 5}
    call_meta.update(meta or {})
    obj = call_agent("visual_director", [{"role": "user", "content": prompt}],
                     system=_SYSTEM, schema=_SPECS_SCHEMA, meta=call_meta)

    specs = []
    for s in obj.get("specs") or []:
        idx = s.get("index")
        if not isinstance(idx, int) or not (0 <= idx < len(beats)) or not s.get("needs_visual"):
            continue
        vtype = s.get("visual_type")
        if vtype not in VISUAL_TYPES:
            continue
        n, bi, heading, _body, hint, citations = beats[idx]
        specs.append({"section_n": n, "beat_index": bi, "visual_type": vtype,
                      "topic": (s.get("topic") or "").strip() or hint or heading,
                      "citations": citations})

    logger.info("[feed_v2.visual] %d/%d beats need a visual", len(specs), len(beats))
    return {"visual_specs": specs}


def _demo() -> None:
    """ponytail self-check: index-join is correct, malformed model output is dropped."""
    drafts = [{"n": 1, "beats": [{"heading": "A", "body": "x"}, {"heading": "B", "body": "y"}]},
              {"n": 2, "beats": [{"heading": "C", "body": "z", "visual": "a timeline"}]}]
    beats = _flat_beats(drafts)
    assert beats == [(1, 0, "A", "x", "", []), (1, 1, "B", "y", "", []), (2, 0, "C", "z", "a timeline", [])]

    def _fake_call(agent, messages, system="", **k):
        return {"specs": [
            {"index": 1, "needs_visual": True, "visual_type": "timeline", "topic": "steps"},
            {"index": 0, "needs_visual": False},
            {"index": 99, "needs_visual": True, "visual_type": "timeline"},   # out of range -> dropped
            {"index": 2, "needs_visual": True, "visual_type": "not-a-real-type"},  # bad enum -> dropped
        ]}
    global call_agent
    orig, call_agent = call_agent, _fake_call
    try:
        out = run_visual_director(section_drafts=drafts)
    finally:
        call_agent = orig
    assert out["visual_specs"] == [{"section_n": 1, "beat_index": 1, "visual_type": "timeline",
                                    "topic": "steps", "citations": []}]
    print("visual_director._demo OK")


if __name__ == "__main__":
    _demo()
