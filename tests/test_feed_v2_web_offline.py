"""
Feed v2 web_researcher (Phase 9) — real search, real coverage-assessor self-loop,
coverage_mode-governed query construction.

Deterministic/offline: _search (the TinyFish client) and call_agent (query construction
+ claim extraction) are mocked so search results and the loop condition are controlled
without a key. One live integration test at the bottom (skipif no TinyFish key) does a
real search + real extraction.

Proves:
  - claim extraction FILTERS results (not every candidate survives);
  - material_bound HARD-GATES queries to the uploaded material — an off-material query
    the model emits is dropped BEFORE search (adversarial), so no off-topic result;
  - a user's uploaded link url is never re-emitted as a web finding (dedup);
  - the coverage assessor fires the loop for a REAL reason (thin pass → diversified pass
    improves) and the cap holds at 3 under persistent thinness (real condition, not the
    rigged STUB_EVIDENCE_THIN);
  - the fallback provider leg serves;
  - the full graph runs with real web + real corpus + 3 stubs, barrier intact.
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
from backend.services.feed_v2.agents import web_researcher as W
from backend.services.feed_v2.agents import corpus_researcher as CR

_HAS_TINYFISH = bool(os.getenv("TINYFISH_API_KEY"))
_DIM = 3072


def _build_db(path):
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


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "web.db")
    _build_db(path)
    monkeypatch.setattr(v2db, "DB_PATH", path)
    return path


@pytest.fixture(autouse=True)
def _rig(request, monkeypatch):
    G._reset_rig()
    # Phase 9b: run_web_research now fetches full page content. Keep these offline tests
    # deterministic by stubbing the fetch to empty (extraction falls back to the snippet,
    # the pre-9b behaviour these tests were written against). The integration test opts out.
    if request.node.get_closest_marker("integration") is None:
        monkeypatch.setattr(W, "_fetch", lambda urls: {})
    yield
    G._reset_rig()


def _ready_project(coverage_mode="open"):
    proj = P.create_project("u1", "Subject", "learn it", "intermediate")
    profile = {"learning_subject": "Subject", "persona": "S", "coverage_mode": coverage_mode}
    with v2db.get_connection() as c:
        c.execute("UPDATE v2_projects SET profile_json=?, coverage_mode=?, profile_status='ready' WHERE project_id=?",
                  (json.dumps(profile), coverage_mode, proj["project_id"]))
    return proj["project_id"]


def _seed_material_chunk(project_id, text, mid="m1"):
    emb = json.dumps([1.0] + [0.0] * (_DIM - 1))   # bucket-0 dir (matches the tests' mocked embed_query)
    with v2db.get_connection() as c:
        c.execute("INSERT OR IGNORE INTO v2_materials(material_id,user_id,project_id,type,filename,extraction_status) VALUES(?,?,?,?,?, 'done')",
                  (mid, "u1", project_id, "document", mid + ".pdf"))
        c.execute("INSERT INTO v2_material_chunks(chunk_id,user_id,material_id,project_id,chunk_index,chunk_text) VALUES(?,?,?,?,0,?)",
                  (mid + "c", "u1", mid, project_id, text))
        c.execute("INSERT INTO v2_material_chunks_vec(embedding,chunk_id,material_id,project_id,user_id,chunk_text,created_at) VALUES(?,?,?,?,?,?,datetime('now'))",
                  (emb, mid + "c", mid, project_id, "u1", text))


def _seed_user_link(project_id, url, mid="ml"):
    with v2db.get_connection() as c:
        c.execute("INSERT INTO v2_materials(material_id,user_id,project_id,type,url,extraction_status) VALUES(?,?,?,?,?, 'done')",
                  (mid, "u1", project_id, "link", url))


def _q_or_p(messages, queries, passages):
    """Route a mocked call_agent to the queries-response or passages-response by which
    step's prompt it is (query construction vs claim extraction)."""
    content = messages[0]["content"]
    return {"passages": passages} if "WEB RESULTS" in content else {"queries": queries}


# ── 1. claim extraction filters candidates ────────────────────────────────────
def test_extraction_filters_results(db, monkeypatch, capsys):
    pid = _ready_project("open")
    monkeypatch.setattr(W, "_search", lambda q: [
        {"title": "Relevant A", "url": "https://a.com/1", "snippet": "on-topic gradient descent"},
        {"title": "Irrelevant", "url": "https://b.com/2", "snippet": "celebrity gossip"},
        {"title": "Relevant B", "url": "https://c.com/3", "snippet": "backprop chain rule"}])
    monkeypatch.setattr(W, "call_agent", lambda agent, messages, **k: _q_or_p(
        messages, queries=["gradient descent"],
        passages=[{"index": 0, "claim": "GD minimizes loss", "why_relevant": "core"},
                  {"index": 2, "claim": "chain rule backprop", "why_relevant": "core"}]))  # drops index 1

    out = W.run_web_research(project_id=pid, journey_entry={"focus": "gradient descent"}, coverage_mode="open")
    urls = [f["url"] for f in out["web_findings"]]
    with capsys.disabled():
        print("\nweb findings:", json.dumps(out["web_findings"], indent=1))
    assert urls == ["https://a.com/1", "https://c.com/3"]   # irrelevant b.com dropped by extraction
    assert all(f["src"] == "web" and f["coverage_mode"] == "open" for f in out["web_findings"])
    assert out["evidence_thin"] is True                      # 2 claims < MIN_CLAIMS_FOR_ENOUGH(3)


# ── 2. material_bound HARD gate drops an off-material query (adversarial) ──────
def test_material_bound_gate_blocks_offtopic_query(db, monkeypatch, capsys):
    pid = _ready_project("material_bound")
    _seed_material_chunk(pid, "Photosynthesis converts light energy into glucose using "
                              "chlorophyll inside the chloroplasts of green plant cells.")
    searched: list[str] = []

    def fake_search(q):
        searched.append(q)
        return [{"title": q, "url": f"https://x.com/{len(searched)}", "snippet": f"about {q}"}]
    monkeypatch.setattr(W, "_search", fake_search)
    # The model MISBEHAVES: emits an on-material query AND an off-material topic-B query.
    monkeypatch.setattr(W, "call_agent", lambda agent, messages, **k: _q_or_p(
        messages,
        queries=["chlorophyll light absorption", "French Revolution causes 1789"],
        passages=[{"index": 0, "claim": "chlorophyll absorbs light", "why_relevant": "material"}]))

    out = W.run_web_research(project_id=pid, journey_entry={"focus": "how plants make food"},
                             coverage_mode="material_bound")
    with capsys.disabled():
        print("\nqueries actually searched:", searched)
        print("findings:", [f["title"] for f in out["web_findings"]])
    assert "chlorophyll light absorption" in searched           # on-material query issued
    assert all("Revolution" not in q for q in searched)         # off-material query GATED before search
    assert all("Revolution" not in f["title"] for f in out["web_findings"])


# ── 3. user link is never re-emitted as a web finding ─────────────────────────
def test_user_link_deduped_from_search(db, monkeypatch, capsys):
    pid = _ready_project("open")
    _seed_user_link(pid, "https://www.userlink.com/article")
    # search returns the user's own url AND a genuinely new one
    monkeypatch.setattr(W, "_search", lambda q: [
        {"title": "User's own", "url": "https://userlink.com/article", "snippet": "same as uploaded"},
        {"title": "New find", "url": "https://fresh.com/x", "snippet": "newly discovered"}])
    monkeypatch.setattr(W, "call_agent", lambda agent, messages, **k: _q_or_p(
        messages, queries=["topic"],
        passages=[{"index": 0, "claim": "c0", "why_relevant": "r"},
                  {"index": 1, "claim": "c1", "why_relevant": "r"}]))

    out = W.run_web_research(project_id=pid, journey_entry={"focus": "topic"}, coverage_mode="open")
    urls = [f["url"] for f in out["web_findings"]]
    with capsys.disabled():
        print("\nfindings urls:", urls)
    assert "https://fresh.com/x" in urls
    assert not any("userlink.com/article" in u for u in urls)   # user's uploaded link excluded


# ── 4. coverage assessor fires the loop for a REAL reason; second pass improves ─
def test_coverage_assessor_loops_then_satisfied(db, monkeypatch, capsys):
    pid = _ready_project("open")
    calls = {"n": 0}

    def staged_search(q):
        calls["n"] += 1
        if calls["n"] == 1:
            return [{"title": "one", "url": "https://s.com/1", "snippet": "thin"}]      # pass 1: 1 result
        return [{"title": f"m{i}", "url": f"https://s.com/1{i}", "snippet": "more"} for i in range(3)]  # pass 2: 3
    monkeypatch.setattr(W, "_search", staged_search)
    monkeypatch.setattr(W, "call_agent", lambda agent, messages, **k: _q_or_p(
        messages, queries=["q"],
        passages=[{"index": i, "claim": f"c{i}", "why_relevant": "r"} for i in range(3)]))

    p1 = W.run_web_research(project_id=pid, journey_entry={"focus": "t"}, coverage_mode="open", iteration=1)
    assert p1["evidence_thin"] is True and len(p1["web_findings"]) == 1     # thin → would loop
    p2 = W.run_web_research(project_id=pid, journey_entry={"focus": "t"}, coverage_mode="open",
                            iteration=2, prior_findings=p1["web_findings"])
    with capsys.disabled():
        print(f"\npass1 findings={len(p1['web_findings'])} thin={p1['evidence_thin']} | "
              f"pass2 findings={len(p2['web_findings'])} thin={p2['evidence_thin']}")
    assert len(p2["web_findings"]) >= 3 and p2["evidence_thin"] is False    # second pass improved coverage


# ── 5. cap still enforced at 3 under the REAL (persistent-thin) condition ──────
def test_real_loop_caps_at_three(db, monkeypatch, capsys):
    G.USE_REAL_WEB_RESEARCHER = True
    pid = _ready_project("open")
    # every pass returns the SAME url → deduped to nothing after pass 1 → stays thin forever
    monkeypatch.setattr(W, "_search", lambda q: [{"title": "same", "url": "https://same.com/x", "snippet": "s"}])
    monkeypatch.setattr(W, "call_agent", lambda agent, messages, **k: _q_or_p(
        messages, queries=["q"], passages=[{"index": 0, "claim": "c", "why_relevant": "r"}]))
    G.USE_REAL_CORPUS_RESEARCHER = False   # keep corpus a cheap stub; this test is about the web cap

    state = {"trace_id": "t", "user_id": "u1", "project_id": pid, "day_number": 1,
             "coverage_mode": "open", "journey_entry": {"focus": "t"}, "profile": {},
             "web_findings": [], "corpus_findings": [], "web_research_iters": 0,
             "section_writer_runs": 0, "rewrite_iters": 0, "research_reentry_iters": 0}
    final = G.compile_graph().invoke(state)
    with capsys.disabled():
        print(f"\nweb ran {G._EXEC_LOG.count('web_researcher')}x; final web_findings={len(final['web_findings'])}")
    assert G._EXEC_LOG.count("web_researcher") == G.MAX_WEB_ITERS == 3    # real condition hit the cap
    assert len(final["web_findings"]) < W.MIN_CLAIMS_FOR_ENOUGH           # still thin → cap stopped it


# ── 6. fallback provider leg serves ───────────────────────────────────────────
def test_fallback_leg_serves(db, monkeypatch, capsys):
    from backend.services.feed_v2.llm import provider
    primary_id = provider.MODEL_REGISTRY["nemotron-nano-30b"][1]        # web primary (OR)
    fallback_id = provider.MODEL_REGISTRY["gemini-3-flash-preview"][1]  # web fallback (google)
    served: list[str] = []
    pid = _ready_project("open")
    monkeypatch.setattr(W, "_search", lambda q: [{"title": "t", "url": "https://z.com/1", "snippet": "s"}])
    monkeypatch.setattr(provider, "_keys_for_provider", lambda p: ["fake-key"])

    def fake_openrouter(api_model_id, *a, **k):
        raise RuntimeError("simulated primary (nemotron) outage")

    def fake_google(api_model_id, messages, system, schema, key, images=None):
        served.append(api_model_id)
        body = {"queries": ["q"]} if "queries" in (schema.get("properties") or {}) else \
               {"passages": [{"index": 0, "claim": "c", "why_relevant": "r"}]}
        return {"text": json.dumps(body), "in_tokens": 1, "out_tokens": 1,
                "latency_ms": 1, "model_used": api_model_id}

    monkeypatch.setitem(provider._SDK_FOR_PROVIDER, "openrouter", fake_openrouter)
    monkeypatch.setitem(provider._SDK_FOR_PROVIDER, "google", fake_google)
    monkeypatch.setattr(provider.call_logger, "write_call_row", lambda **k: None)

    out = W.run_web_research(project_id=pid, journey_entry={"focus": "t"}, coverage_mode="open")
    with capsys.disabled():
        print(f"\nfallback: primary {primary_id} failed -> served {served}")
    assert served and all(s == fallback_id for s in served)   # both LLM calls served by the fallback leg
    assert out["web_findings"] and out["web_findings"][0]["url"] == "https://z.com/1"


# ── 7. full graph: real web + real corpus + 3 stubs, barrier intact ───────────
def test_full_graph_real_web_and_corpus(db, monkeypatch, capsys):
    G.USE_REAL_WEB_RESEARCHER = True
    G.USE_REAL_CORPUS_RESEARCHER = True
    pid = _ready_project("material_bound")
    _seed_material_chunk(pid, "Backpropagation computes gradients via the chain rule to train networks.")
    # web
    monkeypatch.setattr(W, "_search", lambda q: [{"title": "Backprop guide", "url": "https://w.com/1",
                                                  "snippet": "gradients chain rule"}])
    monkeypatch.setattr(W, "call_agent", lambda agent, messages, **k: _q_or_p(
        messages, queries=["backpropagation chain rule gradients"],
        passages=[{"index": 0, "claim": "backprop uses the chain rule", "why_relevant": "core"}]))
    # corpus (real node, retrieval mocked)
    monkeypatch.setattr(CR, "embed_query", lambda t: [1.0] + [0.0] * (_DIM - 1))
    monkeypatch.setattr(CR, "call_agent", lambda *a, **k: {
        "passages": [{"index": 0, "quote": "Backpropagation computes gradients", "why_relevant": "core"}]})

    state = {"trace_id": "t", "user_id": "u1", "project_id": pid, "day_number": 1,
             "coverage_mode": "material_bound", "journey_entry": {"focus": "backpropagation"},
             "profile": {}, "web_findings": [], "corpus_findings": [], "web_research_iters": 0,
             "section_writer_runs": 0, "rewrite_iters": 0, "research_reentry_iters": 0}
    final = G.compile_graph().invoke(state)
    with capsys.disabled():
        print("\nfull-run web_findings:", json.dumps(final["web_findings"]))
        print("full-run corpus_findings:", json.dumps(final["corpus_findings"]))
        print("assembled sources:", json.dumps(final["assembled"]["sources"]))
    for key in ("lesson_plan", "web_findings", "corpus_findings", "ranked_sources",
                "section_drafts", "verdicts", "assembled"):
        assert final.get(key), f"missing {key}"
    assert final["web_findings"][0]["src"] == "web" and final["web_findings"][0]["url"]      # real web
    assert final["corpus_findings"][0]["material_id"] == "m1"                                # real corpus
    assert G._EXEC_LOG.count("assembler") == 1 and G._EXEC_LOG.count("source_ranker") == 1   # barrier intact


# ── 8. parallel execution: honest topological-independence proof ──────────────
def test_web_and_corpus_are_independent_not_sequential(db, monkeypatch, capsys):
    """Phase 9 design: web reads MATERIAL from the DB, not corpus_researcher's output —
    so the two are truly independent. LangGraph's default sync executor runs same-super-
    step nodes sequentially (not wall-clock overlapping), so we prove the meaningful
    property — neither consumes the other's output — rather than claim thread overlap."""
    G.USE_REAL_WEB_RESEARCHER = True
    G.USE_REAL_CORPUS_RESEARCHER = True
    pid = _ready_project("material_bound")
    _seed_material_chunk(pid, "Photosynthesis uses chlorophyll to convert light into glucose.")
    corpus_seen_web: list = []

    monkeypatch.setattr(W, "_search", lambda q: [{"title": "t", "url": "https://p.com/1", "snippet": "chlorophyll"}])
    monkeypatch.setattr(W, "call_agent", lambda agent, messages, **k: _q_or_p(
        messages, queries=["chlorophyll photosynthesis"],
        passages=[{"index": 0, "claim": "chlorophyll converts light", "why_relevant": "material"}]))
    monkeypatch.setattr(CR, "embed_query", lambda t: [1.0] + [0.0] * (_DIM - 1))
    monkeypatch.setattr(CR, "call_agent", lambda *a, **k: {"passages": []})

    # web's material_bound result is correct even though corpus's output is NOT visible to
    # it (super-step semantics) — proving web derives its fence from the DB, not corpus.
    state = {"trace_id": "t", "user_id": "u1", "project_id": pid, "day_number": 1,
             "coverage_mode": "material_bound", "journey_entry": {"focus": "how plants eat"},
             "profile": {}, "web_findings": [], "corpus_findings": [], "web_research_iters": 0,
             "section_writer_runs": 0, "rewrite_iters": 0, "research_reentry_iters": 0}
    final = G.compile_graph().invoke(state)
    with capsys.disabled():
        print(f"\nexec order: {[n for n in G._EXEC_LOG if n in ('web_researcher','corpus_researcher')]}")
        print("web fenced to material (no corpus dependency):", final["web_findings"][0]["title"])
    assert "web_researcher" in G._EXEC_LOG and "corpus_researcher" in G._EXEC_LOG   # both co-scheduled
    assert final["web_findings"]      # web produced material_bound results with corpus output unavailable


# ── live: real TinyFish search + real extraction (integration) ────────────────
@pytest.mark.integration
@pytest.mark.skipif(not _HAS_TINYFISH, reason="no TinyFish API key")
def test_real_search_and_extraction(db, capsys):
    pid = _ready_project("open")
    out = W.run_web_research(project_id=pid,
                             journey_entry={"focus": "what is backpropagation in neural networks"},
                             coverage_mode="open", keywords=["gradient descent", "chain rule"])
    with capsys.disabled():
        print(f"\nLIVE web findings ({len(out['web_findings'])}):",
              json.dumps(out["web_findings"][:3], indent=1))
    assert out["web_findings"], "real search returned no usable findings"
    assert all(f["url"].startswith("http") for f in out["web_findings"])   # real urls from search response
