"""
Feed v2 source_ranker (Phase 10) — multi-call, origin-aware ranking.

Deterministic/offline: the per-batch scoring is mocked (via _score_batch or the SDKs) so
batching, the mechanical merge, the material_bound floor, and the degraded floor are
asserted without a key. Two live-ish paths use the real routing (fallback test) and the
full graph. One integration test does real 0-1 scoring.

Proves:
  - batching is budget-driven and no source is dropped for landing in a later batch;
  - the merged list is sorted by the SHARED 0-1 score, not origin-then-score or input order;
  - material_bound corpus findings are retained and floored (never buried);
  - the < 6 floor writes a degraded_reason into state (mas_runs write deferred);
  - the fallback provider leg serves;
  - the full graph runs with real web + real corpus + real source_ranker + 2 stubs.
"""
import json
import os
import sqlite3

import pytest
import sqlite_vec

from backend.database.schema import ALL_TABLES, MIGRATIONS
from backend.services.feed_v2 import db as v2db
from backend.services.feed_v2.schema import run_v2_migrations
from backend.services.feed_v2 import projects as P
from backend.services.feed_v2 import graph as G
from backend.services.feed_v2.agents import source_ranker as SR
from backend.services.feed_v2.agents import web_researcher as W
from backend.services.feed_v2.agents import corpus_researcher as CR

_HAS_KEY = bool(os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY"))
_DIM = 3072


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "rank.db")
    conn = sqlite3.connect(path)
    conn.enable_load_extension(True); sqlite_vec.load(conn); conn.enable_load_extension(False)
    for s in ALL_TABLES:
        conn.execute(s)
    for m in MIGRATIONS:
        try:
            conn.execute(m) if not isinstance(m, (list, tuple)) else [conn.execute(x) for x in m]
        except sqlite3.OperationalError as e:
            if not any(k in str(e).lower() for k in ("already exists", "duplicate column", "no such column")):
                raise
    run_v2_migrations(conn)
    conn.execute("INSERT OR IGNORE INTO users(user_id,email,name,hashed_pw) VALUES('u1','u1@t.com','u','x')")
    conn.commit(); conn.close()
    monkeypatch.setattr(v2db, "DB_PATH", path)
    return path


@pytest.fixture(autouse=True)
def _rig():
    G._reset_rig()
    yield
    G._reset_rig()
    SR._RANK_CALL_TOKENS = None   # reset any forced budget


def _c(text, score, i=0):
    return {"src": "corpus", "material_id": f"m{i}", "chunk_index": i, "text": text, "_score": score}


def _w(text, score, i=0):
    return {"src": "web", "url": f"https://w{i}.com", "title": f"t{i}", "text": text, "_score": score}


def _score_by_field(batch, focus, origin, meta):
    """Mock _score_batch: score each source from its test-only `_score` field."""
    return {i: float(b.get("_score", 0.5)) for i, b in enumerate(batch)}


# ── 1. budget batching: 2+ batches, every source scored, none dropped ─────────
def test_batching_scores_every_source(monkeypatch, capsys):
    SR._RANK_CALL_TOKENS = 1                       # tiny budget → each source its own batch
    seen_batches = []

    def counting(batch, focus, origin, meta):
        seen_batches.append((origin, [b["text"] for b in batch]))
        return _score_by_field(batch, focus, origin, meta)
    monkeypatch.setattr(SR, "_score_batch", counting)

    corpus = [_c(f"corpus source {i} content", 0.5, i) for i in range(5)]
    out = SR.run_source_ranker(coverage_mode="open", web_findings=[], corpus_findings=corpus,
                               journey_entry={"focus": "x"})
    with capsys.disabled():
        print(f"\ncorpus batches: {len([b for b in seen_batches if b[0]=='corpus'])}; "
              f"scored: {len(out['ranked_sources'])}")
    assert len([b for b in seen_batches if b[0] == "corpus"]) == 5     # 5 batches (forced tiny budget)
    assert len(out["ranked_sources"]) == 5                             # every source survived
    assert all("rank_score" in s for s in out["ranked_sources"])       # none left unscored


# ── 2. merge sorted by the shared score, not origin or input order ────────────
def test_merge_sorted_by_shared_score(monkeypatch, capsys):
    monkeypatch.setattr(SR, "_score_batch", _score_by_field)
    corpus = [_c("c-low", 0.3, 0), _c("c-high", 0.9, 1)]
    web = [_w("w-mid", 0.6, 0), _w("w-low", 0.1, 1)]
    out = SR.run_source_ranker(coverage_mode="open", web_findings=web, corpus_findings=corpus,
                               journey_entry={"focus": "x"})
    order = [(s["rank_origin"], s["rank_score"]) for s in out["ranked_sources"]]
    with capsys.disabled():
        print("\nmerged order:", order)
    assert [sc for _, sc in order] == [0.9, 0.6, 0.3, 0.1]             # strictly by score
    assert order[0][0] == "corpus" and order[1][0] == "web"            # interleaved, NOT origin-grouped


# ── 3. material_bound: corpus PROTECTED (flag), score honest, never buried ────
def test_material_bound_corpus_protected_not_floored(monkeypatch, capsys):
    """Phase 10c: material_bound corpus keeps its REAL low score (no 0.5 floor) and carries
    protected=True instead — the bypass a later cut must honor. open/anchored: no flag."""
    monkeypatch.setattr(SR, "_score_batch", _score_by_field)
    corpus = [_c("material passage", 0.0, 0)]      # model scores the learner's material 0.0 (adversarial)
    web = [_w("web result", 0.8, 0)]

    mb = SR.run_source_ranker(coverage_mode="material_bound", web_findings=web,
                              corpus_findings=corpus, journey_entry={"focus": "x"})
    op = SR.run_source_ranker(coverage_mode="open", web_findings=web,
                              corpus_findings=list(corpus), journey_entry={"focus": "x"})
    an = SR.run_source_ranker(coverage_mode="material_anchored", web_findings=web,
                              corpus_findings=list(corpus), journey_entry={"focus": "x"})
    mb_corpus = next(s for s in mb["ranked_sources"] if s["rank_origin"] == "corpus")
    op_corpus = next(s for s in op["ranked_sources"] if s["rank_origin"] == "corpus")
    an_corpus = next(s for s in an["ranked_sources"] if s["rank_origin"] == "corpus")
    with capsys.disabled():
        print(f"\nmaterial_bound corpus: score={mb_corpus['rank_score']} protected={mb_corpus.get('protected')} | "
              f"open: score={op_corpus['rank_score']} protected={op_corpus.get('protected')}")
    # material_bound: retained, HONEST low score (no floor), protected flag set
    assert mb_corpus in mb["ranked_sources"]                          # survives to output
    assert mb_corpus["rank_score"] == 0.0                             # real score intact, NOT floored 0.5
    assert mb_corpus["protected"] is True                             # protection is the flag now
    # near-zero protected item sorts to the BOTTOM by real score (below the 0.8 web), not the middle
    assert mb["ranked_sources"][-1] is mb_corpus
    assert mb["ranked_sources"][0]["rank_origin"] == "web"
    # open + anchored: no protected flag, no bypass, honest score unchanged
    assert "protected" not in op_corpus and op_corpus["rank_score"] == 0.0
    assert "protected" not in an_corpus and an_corpus["rank_score"] == 0.0


# ── 4. floor check both directions ────────────────────────────────────────────
def test_floor_sets_degraded_below_six(monkeypatch, capsys):
    monkeypatch.setattr(SR, "_score_batch", _score_by_field)
    few = SR.run_source_ranker(coverage_mode="open", web_findings=[_w("a", 0.5, 0)],
                               corpus_findings=[_c("b", 0.5, 0)], journey_entry={"focus": "x"})
    many_web = [_w(f"src {i}", 0.5, i) for i in range(6)]
    plenty = SR.run_source_ranker(coverage_mode="open", web_findings=many_web,
                                  corpus_findings=[], journey_entry={"focus": "x"})
    with capsys.disabled():
        print(f"\nfew(2)->degraded={'degraded_reason' in few} | plenty(6)->degraded={'degraded_reason' in plenty}")
    assert "degraded_reason" in few and "only 2" in few["degraded_reason"]    # 2 < 6 → degraded
    assert "degraded_reason" not in plenty                                    # 6 >= 6 → clean


# ── 5. fallback provider leg serves ───────────────────────────────────────────
def test_fallback_leg_serves(db, monkeypatch, capsys):
    from backend.services.feed_v2.llm import provider
    fallback_id = provider.MODEL_REGISTRY["gemini-3.1-flash-lite"][1]   # source_ranker fallback (google)
    served: list[str] = []
    monkeypatch.setattr(provider, "_keys_for_provider", lambda p: ["fake-key"])

    def fake_openrouter(api_model_id, *a, **k):
        raise RuntimeError("simulated primary (nemotron) outage")

    def fake_google(api_model_id, messages, system, schema, key, images=None):
        served.append(api_model_id)
        return {"text": json.dumps({"scores": [{"index": 0, "score": 0.7}]}),
                "in_tokens": 1, "out_tokens": 1, "latency_ms": 1, "model_used": api_model_id}

    monkeypatch.setitem(provider._SDK_FOR_PROVIDER, "openrouter", fake_openrouter)
    monkeypatch.setitem(provider._SDK_FOR_PROVIDER, "google", fake_google)
    monkeypatch.setattr(provider.call_logger, "write_call_row", lambda **k: None)

    out = SR.run_source_ranker(coverage_mode="open",
                               web_findings=[_w("web c", 0, 0)], corpus_findings=[_c("corpus c", 0, 0)],
                               journey_entry={"focus": "x"})
    with capsys.disabled():
        print(f"\nfallback served: {served}")
    assert served and all(s == fallback_id for s in served)             # both origin calls hit the fallback
    assert all("rank_score" in s for s in out["ranked_sources"])
    assert out["ranked_sources"][0]["rank_score"] == 0.7                # fallback's score parsed through


# ── 6. full graph: real web + real corpus + real source_ranker + 2 stubs ──────
def test_full_graph_real_ranker(db, monkeypatch, capsys):
    G.USE_REAL_WEB_RESEARCHER = True
    G.USE_REAL_CORPUS_RESEARCHER = True
    G.USE_REAL_SOURCE_RANKER = True
    proj = P.create_project("u1", "NN", "exam", "intermediate")
    pid = proj["project_id"]
    with v2db.get_connection() as c:
        c.execute("UPDATE v2_projects SET coverage_mode='open', profile_status='ready' WHERE project_id=?", (pid,))
        c.execute("INSERT INTO v2_materials(material_id,user_id,project_id,type,filename,extraction_status) VALUES('m1','u1',?,'document','n.pdf','done')", (pid,))
        c.execute("INSERT INTO v2_material_chunks(chunk_id,user_id,material_id,project_id,chunk_index,chunk_text) VALUES('c1','u1','m1',?,0,'Backprop chain rule')", (pid,))
        c.execute("INSERT INTO v2_material_chunks_vec(embedding,chunk_id,material_id,project_id,user_id,chunk_text,created_at) VALUES(?,?,?,?,?,?,datetime('now'))",
                  (json.dumps([1.0] + [0.0] * (_DIM - 1)), "c1", "m1", pid, "u1", "Backprop chain rule"))
    # web
    monkeypatch.setattr(W, "_search", lambda q: [{"title": "Guide", "url": "https://w.com/1", "snippet": "backprop"}])
    monkeypatch.setattr(W, "_fetch", lambda urls: {u: "Backpropagation uses the chain rule." for u in urls})
    monkeypatch.setattr(W, "call_agent", lambda agent, messages, **k: (
        {"passages": [{"index": 0, "claim": "backprop uses the chain rule", "why_relevant": "core"}]}
        if "WEB RESULTS" in messages[0]["content"] else {"queries": ["backprop"]}))
    # corpus
    monkeypatch.setattr(CR, "embed_query", lambda t: [1.0] + [0.0] * (_DIM - 1))
    monkeypatch.setattr(CR, "call_agent", lambda *a, **k: {"passages": [{"index": 0, "quote": "Backprop chain rule", "why_relevant": "core"}]})
    # ranker: real _score_batch parsing, scores mocked at the LLM boundary
    monkeypatch.setattr(SR, "call_agent", lambda agent, messages, **k: {"scores": [{"index": 0, "score": 0.8}]})

    trace_id, final = G.run_graph("u1", pid, 1)
    with capsys.disabled():
        print("\nranked_sources:", json.dumps(final["ranked_sources"]))
    for key in ("lesson_plan", "web_findings", "corpus_findings", "ranked_sources",
                "section_drafts", "verdicts", "assembled"):
        assert final.get(key), f"missing {key}"
    origins = {s.get("rank_origin") for s in final["ranked_sources"]}
    assert origins == {"web", "corpus"}                                # both passes ran
    assert all("rank_score" in s for s in final["ranked_sources"])
    scores = [s["rank_score"] for s in final["ranked_sources"]]
    assert scores == sorted(scores, reverse=True)                      # merged, sorted
    assert G._EXEC_LOG.count("assembler") == 1 and G._EXEC_LOG.count("source_ranker") == 1   # barrier intact


# ── 8. Phase 10b: bigger web content → more/smaller batches (budget reacts) ───
def test_full_content_makes_more_batches(monkeypatch, capsys):
    """budget.py's pack-until-ceiling batching sizes off the origin's SCORED text, so once
    the web pass carries full page content (Phase 9c) instead of the short claim, the same
    sources split into more, smaller batches — confirmed, not assumed."""
    monkeypatch.setattr(SR, "_score_batch", _score_by_field)
    SR._RANK_CALL_TOKENS = 60                        # small fixed budget so size differences bite

    web_claim = [_w("chain rule", 0.5, i) for i in range(4)]                    # ~3 tokens each
    web_full = [{**w, "content": "backpropagation gradient descent " * 40} for w in web_claim]  # ~340 tok each

    _, nb_claim = SR._rank_origin(web_claim, "backprop", "web", None)
    _, nb_full = SR._rank_origin(web_full, "backprop", "web", None)
    with capsys.disabled():
        print(f"\nbatches: claim-only={nb_claim}  full-content={nb_full}")
    assert nb_claim == 1                             # 4 short claims fit one 60-token batch
    assert nb_full == 4                              # each full page overflows → its own batch
    assert nb_full > nb_claim                        # batching reacted to the larger size


# ── 9. Phase 10b THE POINT: full content catches relevance the claim missed ───
def test_full_content_catches_what_claim_missed(monkeypatch, capsys):
    """A web source whose CLAIM alone reads off-topic but whose full CONTENT is clearly
    relevant: the claim-only pass would score it 0, the full-content pass scores it 1.
    This is the test that proves re-pointing the web pass at `content` was worth making."""
    def keyword_scorer(agent, messages, system="", schema=None, meta=None):
        # scores 1.0 iff the focus keyword reached the prompt — it can ONLY arrive via the
        # source's content (the claim/title/url below deliberately omit it).
        txt = messages[0]["content"].lower()
        return {"scores": [{"index": 0, "score": 1.0 if "backpropagation" in txt else 0.0}]}
    monkeypatch.setattr(SR, "call_agent", keyword_scorer)

    with_content = [{"src": "web", "url": "https://w0.com", "title": "misc",
                     "text": "a general note about training methods",          # claim: no keyword
                     "content": "Deep dive: backpropagation propagates the loss gradient "
                                "backward through every layer to update the weights."}]     # content: has it
    claim_only = [{k: v for k, v in with_content[0].items() if k != "content"}]  # baseline: pre-10b behaviour

    full = SR.run_source_ranker(coverage_mode="open", web_findings=with_content,
                                corpus_findings=[], journey_entry={"focus": "backprop"})
    base = SR.run_source_ranker(coverage_mode="open", web_findings=claim_only,
                                corpus_findings=[], journey_entry={"focus": "backprop"})
    with capsys.disabled():
        print(f"\nfull-content score={full['ranked_sources'][0]['rank_score']}  "
              f"claim-only score={base['ranked_sources'][0]['rank_score']}")
    assert full["ranked_sources"][0]["rank_score"] == 1.0    # full content → caught as relevant
    assert base["ranked_sources"][0]["rank_score"] == 0.0    # claim alone → would have been missed


# ── 7. live: real 0-1 scoring on both origins (comparability sanity) ──────────
@pytest.mark.integration
@pytest.mark.skipif(not _HAS_KEY, reason="no Gemini API key")
def test_real_scoring_is_zero_to_one(db, capsys):
    corpus = [_c("Backpropagation computes gradients via the chain rule.", 0, 0)]
    web = [_w("Backprop trains neural networks by reducing prediction error.", 0, 0),
           _w("A recipe for chocolate chip cookies with butter and sugar.", 0, 1)]
    out = SR.run_source_ranker(coverage_mode="open", web_findings=web, corpus_findings=corpus,
                               journey_entry={"focus": "how backpropagation trains neural networks"})
    scores = {s["rank_origin"] + ":" + (s.get("url") or s.get("material_id")): s["rank_score"]
              for s in out["ranked_sources"]}
    with capsys.disabled():
        print("\nLIVE scores:", scores)
    assert all(0.0 <= s["rank_score"] <= 1.0 for s in out["ranked_sources"])   # same 0-1 scale both passes
    # the cookie recipe should score below the on-topic sources (sanity, not a hard contract)
    cookie = next(s for s in out["ranked_sources"] if "w1.com" in (s.get("url") or ""))
    on_topic = [s["rank_score"] for s in out["ranked_sources"] if s is not cookie]
    assert cookie["rank_score"] <= max(on_topic)
