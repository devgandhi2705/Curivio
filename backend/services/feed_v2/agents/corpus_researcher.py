"""
Feed v2 corpus researcher (Phase 8) — real RAG over the project's uploaded
materials. First of the Phase-7 stub agents to become real.

TWO steps, ONE LLM call:

  1. RETRIEVAL (no LLM). Embed the day's focus (+ keywords) with the SAME model
     the materials were embedded with — ingestion.embeddings.embed_query reuses
     _embed_one_batch, so query and document embeddings are gemini-embedding-001
     @ 3072-d by construction (no dimension mismatch possible). Vector-search
     v2_material_chunks_vec scoped to project_id, top-k nearest by cosine distance.
     Nearest-neighbour ≠ relevant, so this is only a candidate set.

  2. EXTRACTION (the one LLM call). The corpus_researcher agent reads the numbered
     candidates and selects the ones actually on today's focus, discarding retrieved-
     but-irrelevant noise. It emits only the candidate INDEX (+ a quote/why); the
     citation metadata (material_id, chunk_index, filename) is joined from the DB
     row by index and NEVER trusted from the model — the model can't hallucinate a
     material_id or a page number.

CITATION PRECISION (honest, not invented): chunks carry a real chunk_index and
material_id. They do NOT carry a page number — _extract_pdf joins all pages into
flat text before chunking (documents.py), so page boundaries are lost and
v2_material_chunks.page_no is never populated. We carry page_no only if it is
actually present (None today); we do not fabricate "page 4". chunk_index is the
honest offset.

COVERAGE_MODE: retrieval/extraction is identical across modes — this phase does
NOT implement cross-agent weighting (that's section_writer/source_ranker later).
It only TAGS each finding with coverage_mode so those later phases can weight
material_bound corpus output as near-primary vs. supplementary in anchored/open.

NO MATERIALS: a project with zero chunks for its project_id (legitimately, e.g.
coverage_mode='open' with nothing uploaded) is a clean no-op — empty results, no
embedding call, no LLM call — never an error that would break the fan-in barrier.

Isolation: imports only feed_v2's own db/provider/embeddings, never
backend.services.* / backend.llm.*.
"""
from __future__ import annotations

import json
import logging

from ..db import get_connection
from ..ingestion.embeddings import embed_query
from ..llm.provider import AllLegsFailed, call_agent  # noqa: F401  (re-exported for callers)

logger = logging.getLogger(__name__)

# top-k: retrieve a slightly-wide candidate set so the day's genuinely-relevant
# chunks land in it (vector NN can rank an off-topic-but-lexically-close chunk
# above a relevant one), then let the extraction LLM filter. 8 balances that recall
# against the extraction prompt's context cost; it matches the chat path's document
# retrieval top-k region. Bump if a day's material is spread across many chunks.
DEFAULT_TOP_K = 8

_SYSTEM = (
    "You are a precise research assistant. You are given a learner's focus for today "
    "and a numbered list of candidate passages retrieved from THEIR uploaded material "
    "by vector search. Vector search returns nearest neighbours, not guaranteed-"
    "relevant results. Select ONLY the passages genuinely on-topic for today's focus; "
    "discard the rest. Return ONLY a JSON object — no prose, no markdown fences."
)


def _query_text(journey_entry: dict, keywords) -> str:
    parts = [journey_entry.get("focus"), journey_entry.get("display_title")]
    if keywords:
        parts.append(" ".join(keywords) if isinstance(keywords, (list, tuple)) else str(keywords))
    return " ".join(p for p in parts if p).strip() or "overview"


def _count_project_chunks(project_id: str) -> int:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM v2_material_chunks_vec WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    return int(row["n"]) if row else 0


def _retrieve(project_id: str, query_text: str, top_k: int) -> list[dict]:
    """Top-k nearest chunks for project_id, enriched with chunk_index/page_no/source.

    Two small queries rather than a join against the vec0 virtual table: the vec
    scan (scalar cosine, same shape as document_memory_service) returns the ordered
    chunk_ids, then a plain lookup enriches them. Cheap at top_k=8 and avoids relying
    on join behaviour through the virtual table."""
    qvec = json.dumps(embed_query(query_text))
    with get_connection() as conn:
        hits = conn.execute(
            """SELECT chunk_id, material_id, chunk_text,
                      vec_distance_cosine(embedding, ?) AS distance
               FROM   v2_material_chunks_vec
               WHERE  project_id = ?
               ORDER  BY distance ASC
               LIMIT  ?""",
            (qvec, project_id, top_k),
        ).fetchall()
        if not hits:
            return []
        ids = [h["chunk_id"] for h in hits]
        placeholders = ",".join("?" * len(ids))
        meta_rows = conn.execute(
            f"""SELECT k.chunk_id, k.chunk_index, k.page_no,
                       m.filename, m.type AS material_type, m.url
                FROM   v2_material_chunks k
                JOIN   v2_materials m ON m.material_id = k.material_id
                WHERE  k.chunk_id IN ({placeholders})""",
            ids,
        ).fetchall()
    meta = {r["chunk_id"]: dict(r) for r in meta_rows}
    out: list[dict] = []
    for h in hits:  # preserve distance order
        m = meta.get(h["chunk_id"], {})
        out.append({
            "chunk_id":      h["chunk_id"],
            "material_id":   h["material_id"],
            "chunk_index":   m.get("chunk_index"),
            "page_no":       m.get("page_no"),   # None today — never fabricated
            "source_label":  m.get("filename") or m.get("url") or h["material_id"],
            "material_type": m.get("material_type"),
            "text":          h["chunk_text"],
            "distance":      h["distance"],
        })
    return out


def _extract(candidates: list[dict], focus: str, meta: dict | None) -> list[dict]:
    """The ONE LLM call: keep only candidates on-topic for `focus`. Maps the model's
    selected indices back onto the DB-sourced citation metadata."""
    listing = "\n\n".join(
        f"[{i}] {c['text']}" for i, c in enumerate(candidates)
    )
    prompt = (
        f"TODAY'S FOCUS:\n{focus or '(general overview)'}\n\n"
        f"CANDIDATE PASSAGES ({len(candidates)}):\n{listing}\n\n"
        "Return the passages actually relevant to today's focus as JSON:\n"
        '{"passages": [{"index": <candidate number>, '
        '"quote": "<the most relevant verbatim span copied from that passage>", '
        '"why_relevant": "<one short phrase>"}]}\n'
        "Include an entry ONLY for passages genuinely on-topic. If NONE are relevant, "
        'return {"passages": []}.'
    )
    call_meta = {"call_type": "feed_v2_corpus_researcher", "surface": "feed_v2",
                 "agent_name": "corpus_researcher"}
    call_meta.update(meta or {})

    obj = call_agent("corpus_researcher", [{"role": "user", "content": prompt}],
                     system=_SYSTEM, meta=call_meta)

    selected: list[dict] = []
    for p in obj.get("passages") or []:
        idx = p.get("index")
        if not isinstance(idx, int) or not (0 <= idx < len(candidates)):
            continue  # model referenced a passage that wasn't offered — drop it
        c = candidates[idx]
        quote = (p.get("quote") or "").strip()
        selected.append({
            "src":           "corpus",
            "material_id":   c["material_id"],
            "chunk_index":   c["chunk_index"],
            "page_no":       c["page_no"],
            "source_label":  c["source_label"],
            "material_type": c["material_type"],
            "text":          quote or c["text"],   # model's pertinent span, else full chunk
            "why_relevant":  (p.get("why_relevant") or "").strip(),
            "distance":      c["distance"],
        })
    return selected


def run_corpus_research(*, project_id: str, journey_entry: dict, coverage_mode: str,
                        keywords=None, top_k: int = DEFAULT_TOP_K,
                        meta: dict | None = None) -> dict:
    """Retrieve + extract the material passages relevant to the day's focus.

    Returns {"corpus_findings": [...]} — a list of dicts, the SAME state key/shape
    the Phase-7 stub wrote, each tagged with coverage_mode. Empty (clean no-op) when
    the project has no chunks or nothing is relevant. Propagates AllLegsFailed if the
    extraction call's every provider leg fails (no silent fake data)."""
    if _count_project_chunks(project_id) == 0:
        return {"corpus_findings": []}   # no materials → nothing to find, no embed/LLM

    query_text = _query_text(journey_entry or {}, keywords)
    candidates = _retrieve(project_id, query_text, top_k)
    if not candidates:
        return {"corpus_findings": []}

    findings = _extract(candidates, (journey_entry or {}).get("focus") or "", meta)
    for f in findings:
        f["coverage_mode"] = coverage_mode   # Phase 8 tag for later weighting
    return {"corpus_findings": findings}


def _demo() -> None:
    """ponytail self-check: query building + index mapping, no network/DB."""
    assert _query_text({"focus": "gradient descent", "display_title": "Day 3"},
                       ["ml", "optimization"]) == "gradient descent Day 3 ml optimization"
    assert _query_text({}, None) == "overview"

    # _extract maps model indices onto DB metadata and drops out-of-range indices.
    cands = [{"material_id": "m1", "chunk_index": 4, "page_no": None,
              "source_label": "syllabus.pdf", "material_type": "document",
              "text": "backprop full chunk", "distance": 0.1},
             {"material_id": "m2", "chunk_index": 0, "page_no": None,
              "source_label": "cat.png", "material_type": "image",
              "text": "a fluffy cat", "distance": 0.9}]
    import backend.services.feed_v2.agents.corpus_researcher as self_mod
    orig = self_mod.call_agent
    self_mod.call_agent = lambda *a, **k: {"passages": [
        {"index": 0, "quote": "backprop", "why_relevant": "on topic"},
        {"index": 9, "quote": "x", "why_relevant": "out of range"}]}
    try:
        out = _extract(cands, "backprop", None)
    finally:
        self_mod.call_agent = orig
    assert len(out) == 1 and out[0]["material_id"] == "m1"
    assert out[0]["text"] == "backprop" and out[0]["chunk_index"] == 4
    assert out[0]["page_no"] is None   # never fabricated
    print("corpus_researcher._demo OK")


if __name__ == "__main__":
    _demo()
