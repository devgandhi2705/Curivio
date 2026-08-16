"""
Feed v2 source ranker (Phase 10) — multi-call, origin-aware ranking.

Ranks by ORIGIN in two separate passes instead of one call over everything:
  - corpus pass: scores the material passages Phase 8 produced (full `text`),
  - web pass:   Phase 10b scores the FULL deduped page (Phase 9c `content`), not the
    distilled claim — so relevance the claim missed still counts (falls back to the
    claim/title/snippet/url when a fetch failed and there is no content),
both on the SAME 0.0-1.0 relevance scale so the merge is purely MECHANICAL — sort the
combined list by score, no reconciliation LLM call. Output is one merged, ranked,
UNCAPPED list; tiering into primary/secondary/other is the assembler's job (Phase 13).

BATCHING is budget-driven, not a guessed count: budget.py's input_budget(model) gives
the per-call token ceiling and count_tokens() the per-source cost, so a pool that would
overflow one call is split into as few batches as fit. Sized by the source_ranker
PRIMARY model (nemotron-nano-30b, the smaller 128k window) so either provider leg is
safe. In practice input_budget is ~107k tokens, so typical pools rank in ONE batch per
origin; batching is exercised (and tested) by forcing a small budget.

material_bound PROTECTION (Phase 10c): corpus-origin findings carry protected=True in
material_bound mode. Scores stay HONEST — no floor, a near-zero score is kept as-is — but
protected=True is a hard bypass any downstream filter/cut MUST honor: a protected finding
is never dropped on the basis of its score. (No cut exists yet — the merge is uncapped —
so today the flag is the forward contract the assembler/tiering phase will read.)

FLOOR: fewer than 6 valid sources across the MERGED output sets a degraded signal in
state (degraded_reason). Writing that through to mas_runs.degraded_reason is DEFERRED —
run finalization (finalize_run) doesn't read state's degraded_reason yet; no phase has
wired it. The state field is the contract the assembler/finalization phase will read.

Isolation: imports only feed_v2's own provider + budget. Never backend.services.* /
backend.llm.*.
"""
from __future__ import annotations

import logging

from ..budget import count_tokens, input_budget
from ..llm.provider import AllLegsFailed, call_agent  # noqa: F401  (re-exported for callers)

logger = logging.getLogger(__name__)

PRIMARY_MODEL = "nemotron-nano-30b"     # source_ranker primary; batches sized by its budget
_RANK_OVERHEAD_TOKENS = 2000            # reserve for the prompt scaffold + JSON scores output
FLOOR_MIN_SOURCES = 6                   # < this many merged valid sources ⇒ degraded signal
_FAILED_CALL_SCORE = 0.5                # a scoring outage → neutral score, sources RETAINED not dropped

# None ⇒ derive the per-call token budget from budget.py. Tests set a small int to force
# multi-batch behaviour without needing hundreds of real sources.
_RANK_CALL_TOKENS: int | None = None

_SCORES_SCHEMA = {"type": "object", "required": ["scores"],
                  "properties": {"scores": {"type": "array", "items": {
                      "type": "object", "properties": {
                          "index": {"type": "integer"},
                          "score": {"type": "number"}}}}}}

_SYSTEM = "You score how relevant each candidate source is to a lesson's focus. Return ONLY JSON."


def _call_budget() -> int:
    if _RANK_CALL_TOKENS is not None:
        return _RANK_CALL_TOKENS
    return max(1, input_budget(PRIMARY_MODEL) - _RANK_OVERHEAD_TOKENS)


def _rank_text(s: dict) -> str:
    for k in ("text", "title", "snippet", "url"):
        v = s.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _origin_text(s: dict, origin: str) -> str:
    """Text the model actually SCORES. Phase 10b: a web source is scored against the FULL
    fetched page (Phase 9c `content`) — the ranker catches relevance the distilled claim
    missed — falling back to the claim/title/snippet/url when a fetch failed (no content).
    A corpus source is already real chunk text (`_rank_text`), unchanged."""
    if origin == "web":
        c = s.get("content")
        if isinstance(c, str) and c.strip():
            return c.strip()
    return _rank_text(s)


def _valid_dedup(sources: list[dict]) -> list[dict]:
    """Mechanical filter (not judgment): drop non-dicts, entries with no rankable content,
    and exact duplicates (same url, else same text)."""
    out: list[dict] = []
    seen: set = set()
    for s in sources:
        if not isinstance(s, dict):
            continue
        txt = _rank_text(s)
        if not txt:
            continue
        key = (s.get("url") or "").strip().lower() or txt
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _batches(sources: list[dict], budget_tokens: int, origin: str = "corpus") -> list[list[dict]]:
    """Pack sources into as few batches as fit `budget_tokens` of ranking text each. Sizing
    uses the origin's actual scored text — so web batches shrink automatically once they
    carry full page content (Phase 10b) instead of the short claim."""
    batches: list[list[dict]] = []
    cur: list[dict] = []
    cur_tokens = 0
    for s in sources:
        t = count_tokens(_origin_text(s, origin))
        if cur and cur_tokens + t > budget_tokens:
            batches.append(cur)
            cur, cur_tokens = [], 0
        cur.append(s)
        cur_tokens += t
    if cur:
        batches.append(cur)
    return batches


def _score_batch(batch: list[dict], focus: str, origin: str, meta: dict | None) -> dict[int, float]:
    """One ranking LLM call over a batch → {local_index: score in 0..1}. A total leg
    failure returns neutral scores (sources retained, never dropped)."""
    origin_note = ("These passages are from the learner's OWN uploaded material."
                   if origin == "corpus" else
                   "These are web sources discovered for today's focus.")
    # Phase 10b: send the origin's full scored text (web = full deduped page). No per-source
    # cap — Phase 9c dedup bounds a page to input_budget//4 and _batches bounds the batch, so
    # no single source can overflow one call.
    listing = "\n\n".join(f"[{i}] {_origin_text(s, origin)}" for i, s in enumerate(batch))
    prompt = (f"TODAY'S FOCUS:\n{focus or '(general overview)'}\n\n{origin_note}\n\n"
              f"SOURCES ({len(batch)}):\n{listing}\n\n"
              "Score EACH source's relevance to today's focus from 0.0 (irrelevant) to 1.0 "
              '(directly on-topic). Return JSON: {"scores": [{"index": <n>, "score": <0.0-1.0>}]}.')
    call_meta = {"call_type": f"feed_v2_rank_{origin}", "surface": "feed_v2",
                 "agent_name": "source_ranker", "step_index": 3}
    call_meta.update(meta or {})
    try:
        obj = call_agent("source_ranker", [{"role": "user", "content": prompt}],
                         system=_SYSTEM, schema=_SCORES_SCHEMA, meta=call_meta)
    except AllLegsFailed as exc:  # infra must not wedge / drop sources on a ranking outage
        logger.warning("[feed_v2.rank] %s batch scoring failed, neutral scores: %s", origin, exc)
        return {i: _FAILED_CALL_SCORE for i in range(len(batch))}
    scores: dict[int, float] = {}
    for r in obj.get("scores") or []:
        idx = r.get("index")
        if isinstance(idx, int) and 0 <= idx < len(batch):
            try:
                scores[idx] = max(0.0, min(1.0, float(r.get("score"))))
            except (TypeError, ValueError):
                continue
    return scores


def _rank_origin(sources: list[dict], focus: str, origin: str, meta: dict | None) -> tuple[list[dict], int]:
    """Score every source of one origin (batched), returning (scored_sources, batch_count).
    A source the model omitted gets 0.0 (retained, ranks low) — never dropped."""
    budget = _call_budget()
    batches = _batches(sources, budget, origin)
    scored: list[dict] = []
    for batch in batches:
        local = _score_batch(batch, focus, origin, meta)
        for i, s in enumerate(batch):
            scored.append({**s, "rank_score": local.get(i, 0.0), "rank_origin": origin})
    return scored, len(batches)


def run_source_ranker(*, coverage_mode: str, web_findings: list, corpus_findings: list,
                      journey_entry: dict, meta: dict | None = None) -> dict:
    """Two origin-aware ranking passes → one merged, mechanically-sorted, uncapped list.

    Returns {"ranked_sources": [...]} (each source gains rank_score + rank_origin), plus
    "degraded_reason" when the merged valid pool is below FLOOR_MIN_SOURCES."""
    focus = (journey_entry or {}).get("focus") or ""
    corpus = _valid_dedup(corpus_findings or [])
    web = _valid_dedup(web_findings or [])

    corpus_scored, nb_corpus = _rank_origin(corpus, focus, "corpus", meta)
    web_scored, nb_web = _rank_origin(web, focus, "web", meta)

    # material_bound protection (Phase 10c): flag corpus findings protected instead of
    # flooring their score. Scores stay honest (a near-zero stays near-zero and sorts low);
    # protected=True is the bypass any later filter/cut must honor — score is never grounds
    # to drop the learner's own material. No score mutation, no cut here (merge is uncapped).
    if coverage_mode == "material_bound":
        for s in corpus_scored:
            s["protected"] = True

    # MECHANICAL merge: single sort by the shared 0-1 score, no reconciliation call.
    merged = sorted(corpus_scored + web_scored, key=lambda s: -float(s["rank_score"]))

    logger.info("[feed_v2.rank] corpus=%d (%d batch) web=%d (%d batch) merged=%d",
                len(corpus_scored), nb_corpus, len(web_scored), nb_web, len(merged))

    out: dict = {"ranked_sources": merged}
    if len(merged) < FLOOR_MIN_SOURCES:
        out["degraded_reason"] = f"only {len(merged)} valid sources (< {FLOOR_MIN_SOURCES})"
    return out


def _demo() -> None:
    """ponytail self-check: validation/dedup + budget batching + mechanical sort, no network."""
    assert _rank_text({"text": "hi"}) == "hi" and _rank_text({"stub": True}) == ""
    dd = _valid_dedup([{"url": "u", "text": "a"}, {"url": "u", "text": "a2"}, {"text": ""}, {"text": "b"}])
    assert len(dd) == 2   # dup url collapsed, empty dropped
    # forced tiny budget → each source its own batch
    global _RANK_CALL_TOKENS
    _RANK_CALL_TOKENS = 1
    b = _batches([{"text": "aaaa"}, {"text": "bbbb"}, {"text": "cccc"}], _call_budget())
    _RANK_CALL_TOKENS = None
    assert len(b) == 3
    merged = sorted([{"rank_score": 0.2}, {"rank_score": 0.9}, {"rank_score": 0.5}],
                    key=lambda s: -s["rank_score"])
    assert [s["rank_score"] for s in merged] == [0.9, 0.5, 0.2]
    print("source_ranker._demo OK")


if __name__ == "__main__":
    _demo()
