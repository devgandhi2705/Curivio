"""
Feed v2 claim validator (Phase 13). Checks the writer's claims against the sources it cited.

TWO CHECKS:
  1. CITATION CHECK (no LLM): every [sN] a beat cites (its `citations` list AND inline
     markers in the body) must be a source that beat's writer GROUP was actually shown.
     "Shown" is recomputed with the writer's own _assign_ids -> _route -> _pack, never a
     reimplementation, so it is exactly what the writer's prompt listed. Anything else is
     an invented citation and goes straight into the verdicts.
  2. SUPPORT CHECK (LLM, one call per writer group, at most 4 per run): the group's beats
     that carry a valid citation, judged against ONLY the sources cited in that group.
     Per claim:
       verdict        supported | unsupported                 (Job 1)
       evidence_weak  cited evidence is thin/indirect/partial  (Job 2)
       conflict       the provided sources disagree on it      (Job 3, section 4b's gate)

WHAT IT DOES WITH THEM: unsupported claims, invented citations and unchecked groups are
summarised in degraded_reason (-> mas_runs); every verdict stays in state["verdicts"], and
each group's raw model output is in llm_call_log. Jobs 2 and 3 are computed and logged only:
writing_weak and evidence_weak stay False (both loops are blind re-rolls today), and
section 4b stays unrendered. Degrade, never fail: a group whose call fails on every leg is
"unchecked", not a failed run.

Beats with no citation are not sent (nothing to check them against) but they are NOT
silent: each is a "no_citations" verdict and counted as unchecked_no_citations in
degraded_reason, so "verified fine" and "nothing here was checkable" read differently. A
group routed zero sources (section 8-9 when the pool is small) writes only uncited beats.

Isolation: imports only feed_v2's own provider/budget and the writer's routing.
"""
from __future__ import annotations

import logging
import re

from ..budget import input_budget
from ..llm.provider import AGENT_ROUTING, AllLegsFailed, call_agent
from .section_writer import GROUPS, _assign_ids, _call_budget, _pack, _route, _source_text

logger = logging.getLogger(__name__)

_MARKER_RE = re.compile(r"\[(s\d+)\]")
# Both legs see the same packed sources, sized by the smaller one (the :free fallback,
# ~107k input) so a fallback never overflows and verdicts don't depend on which leg ran.
# 8k reserve covers the prompt scaffold + the group's beats.
_SOURCE_BUDGET_TOKENS = input_budget(AGENT_ROUTING["claim_validator"][1]) - 8000

_SYSTEM = ("You fact-check a daily micro-lesson against the sources it cites. Judge each claim "
           "ONLY against the source text given, never your own knowledge. Return ONLY JSON.")


def _cited(beat: dict) -> set[str]:
    ids = {str(c).strip("[] ") for c in beat.get("citations") or []}
    return {i for i in ids if i} | set(_MARKER_RE.findall(beat.get("body") or ""))


def _shown_ids(ranked_sources: list) -> tuple[dict[str, dict], dict[str, set[str]]]:
    """(source by id, ids each group was shown) — the writer's exact routing + packing."""
    sources = _assign_ids(ranked_sources)
    routed = _route(sources)
    shown = {g: {s["source_id"] for s in _pack(routed.get(g, []), _call_budget())} for g in GROUPS}
    return {s["source_id"]: s for s in sources}, shown


def _check_group(group: str, beats: list[tuple], by_id: dict, meta: dict | None) -> list[dict]:
    """One LLM call over the group's cited beats. beats: [(section_n, beat_idx, beat, valid_ids)]."""
    cited = set().union(*(ids for *_, ids in beats))
    packed = _pack([s for s in by_id.values() if s["source_id"] in cited], _SOURCE_BUDGET_TOKENS)
    seen = {s["source_id"] for s in packed}
    keyed = {f"B{i + 1}": b for i, b in enumerate(beats)}
    prompt = (
        "SOURCES:\n" + "\n\n".join(f"[{s['source_id']}] {_source_text(s)}" for s in packed) +
        "\n\nLESSON BEATS (inline [id] markers show which source each claim cites):\n" +
        "\n\n".join(f"[{k}] {b[2].get('heading') or ''}\n{b[2].get('body') or ''}" for k, b in keyed.items()) +
        "\n\nFor every factual claim in these beats, return one verdict:\n"
        '{"beat": "<B-id>", "claim": "<the claim, short>", "cited": ["<source id>", ...], '
        '"verdict": "supported" | "unsupported", "evidence_weak": true|false, "conflict": true|false, '
        '"reason": "<one sentence>"}\n'
        "supported = the cited source(s) state it or directly imply it. unsupported = they don't "
        "say it, or say otherwise.\n"
        "evidence_weak = the support is thin: mentioned in passing, vague, or covering only part "
        "of the claim.\n"
        "conflict = two or more of the SOURCES above disagree on this point (not the claim vs a "
        "source).\n"
        'Return JSON: {"verdicts": [...]}.')
    call_meta = {"call_type": f"feed_v2_claims_{group.lower()}", "surface": "feed_v2",
                 "agent_name": "claim_validator", "step_index": 7}
    call_meta.update(meta or {})
    obj = call_agent("claim_validator", [{"role": "user", "content": prompt}], system=_SYSTEM, meta=call_meta)

    out = []
    for v in obj.get("verdicts") or []:
        if not isinstance(v, dict):
            continue
        n, idx, beat, ids = keyed.get(str(v.get("beat")), (None, None, {}, set()))
        verdict = v.get("verdict")
        # the model never saw a source packing dropped: 'unsupported' against it isn't a verdict
        if verdict == "unsupported" and ids - seen:
            verdict = "unchecked"
        out.append({"kind": "claim", "group": group, "section": n, "beat": idx,
                    "heading": beat.get("heading"), "claim": v.get("claim"), "cited": v.get("cited") or [],
                    "verdict": verdict, "evidence_weak": bool(v.get("evidence_weak")),
                    "conflict": bool(v.get("conflict")), "reason": v.get("reason")})
    return out


def run_claim_validator(*, section_drafts: list, ranked_sources: list, meta: dict | None = None) -> dict:
    """Returns {"verdicts", "writing_weak": False, "evidence_weak": False} plus
    "degraded_reason" when anything needs a human look."""
    by_id, shown = _shown_ids(ranked_sources or [])
    verdicts: list[dict] = []
    to_check: dict[str, list[tuple]] = {g: [] for g in GROUPS}
    for sec in section_drafts or []:
        g = sec.get("group")
        for i, beat in enumerate(sec.get("beats") or []):
            cited = _cited(beat)
            if not cited:
                verdicts.append({"kind": "no_citations", "group": g, "section": sec.get("n"),
                                 "beat": i, "heading": beat.get("heading")})
                continue
            bad = sorted(cited - shown.get(g, set()), key=lambda x: int(x[1:]))
            if bad:
                verdicts.append({"kind": "invented_citation", "group": g, "section": sec.get("n"),
                                 "beat": i, "heading": beat.get("heading"), "ids": bad})
            if cited - set(bad) and g in to_check:
                to_check[g].append((sec.get("n"), i, beat, cited - set(bad)))

    unchecked = []
    for g in GROUPS:
        if not to_check[g]:
            continue
        try:
            verdicts.extend(_check_group(g, to_check[g], by_id, meta))
        except AllLegsFailed as exc:
            unchecked.append(g)
            verdicts.append({"kind": "unchecked", "group": g, "reason": str(exc)})

    claims = [v for v in verdicts if v["kind"] == "claim"]
    unsupported = [v for v in claims if v["verdict"] == "unsupported"]
    invented = [v for v in verdicts if v["kind"] == "invented_citation"]
    uncited = [v for v in verdicts if v["kind"] == "no_citations"]
    logger.info("[feed_v2.claims] claims=%d unsupported=%d evidence_weak=%d conflict=%d "
                "invented_citations=%d unchecked_no_citations=%d unchecked_groups=%s", len(claims),
                len(unsupported), sum(v["evidence_weak"] for v in claims),
                sum(v["conflict"] for v in claims), len(invented), len(uncited), unchecked)

    out: dict = {"verdicts": verdicts, "writing_weak": False, "evidence_weak": False}
    parts = []
    if unsupported:
        parts.append(f"unsupported={len(unsupported)} ["
                     + ", ".join(f"{v['group']}:{v['section']}.{v['beat']}" for v in unsupported) + "]")
    if invented:
        parts.append(f"invented_citations={len(invented)} ["
                     + ", ".join(f"{v['group']}:{v['section']}.{v['beat']}:{','.join(v['ids'])}"
                                 for v in invented) + "]")
    if uncited:
        parts.append(f"unchecked_no_citations={len(uncited)} ["
                     + ", ".join(f"{v['group']}:{v['section']}.{v['beat']}" for v in uncited) + "]")
    if unchecked:
        parts.append("unchecked_groups=" + ",".join(unchecked))
    if parts:
        out["degraded_reason"] = "claim_validator: " + "; ".join(parts)
    return out
