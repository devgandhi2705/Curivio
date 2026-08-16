"""
Feed v2 section_writer (Phase 11) — four-group writer.

Offline/deterministic: the writing call is mocked (echoes back the source ids it was given,
in a real beats shape) so routing, citations, beats structure, and per-group crash-resume
are asserted without a key. Fallback + full-graph tests use the real routing/graph.

Proves:
  - a protected (material_bound) source is actually CITED in the group that covers its topic
    (Phase 10c's protected flag would be pointless otherwise);
  - each group's PROMPT carries only its routed sources, not the full ranked list;
  - output is a genuine array of beats per section, not flat text with a wrapper;
  - a crash after group B does NOT regenerate A/B on resume, only C/D run;
  - the fallback provider leg serves;
  - the full graph runs real lesson_planner + section_writer + web/corpus/ranker.
"""
import json
import os
import re
import sqlite3

import pytest
import sqlite_vec

from backend.database.schema import ALL_TABLES, MIGRATIONS
from backend.services.feed_v2 import db as v2db
from backend.services.feed_v2.schema import run_v2_migrations
from backend.services.feed_v2 import projects as P
from backend.services.feed_v2 import graph as G
from backend.services.feed_v2.agents import section_writer as SW
from backend.services.feed_v2.agents import lesson_planner as LP
from backend.services.feed_v2.agents import web_researcher as W
from backend.services.feed_v2.agents import corpus_researcher as CR

_HAS_KEY = bool(os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY"))
_DIM = 3072

_PLAN = {"focus": "backprop", "objectives": ["understand backprop"], "difficulty": "intermediate",
         "worked_example_mode": "example-first", "render_prerequisites": False, "section_4b": "pending"}


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "sw.db")
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
    SW._WRITE_CALL_TOKENS = None


def _sources_in_prompt(prompt: str) -> set:
    """The source ids actually placed in a group's SOURCES listing (not the instructions)."""
    body = prompt.split("SOURCES you may cite", 1)[-1].split("Each section's content", 1)[0]
    return set(re.findall(r"\[(s\d+)\]", body))


def _echo_writer(sink=None):
    """Mock call_agent: echo the listing's ids as a real beats section; add checks for group C."""
    def f(agent, messages, system="", schema=None, meta=None):
        content = messages[0]["content"]
        if sink is not None:
            sink[meta.get("call_type", "?")] = content
        cites = sorted(_sources_in_prompt(content))
        body = "core claim " + " ".join(f"[{c}]" for c in cites)
        out = {"sections": [{"n": 1, "title": "T", "beats": [
            {"heading": "H", "body": body, "visual": None, "citations": cites}]}]}
        if meta.get("call_type") == "feed_v2_write_c":
            out["checks"] = [{"question": "what is backprop?", "expected": "chain rule over layers"}]
        return out
    return f


# ── 1. protected source is cited where its topic is covered ───────────────────
def test_protected_source_cited(db, monkeypatch, capsys):
    monkeypatch.setattr(SW, "call_agent", _echo_writer())
    ranked = [
        {"src": "web", "url": "https://w0.com", "title": "t0", "content": "web core content",
         "rank_score": 0.9, "rank_origin": "web"},
        {"src": "corpus", "material_id": "m1", "chunk_index": 0, "text": "the learner's own material",
         "rank_score": 0.0, "rank_origin": "corpus", "protected": True},   # bottom-scored, protected
    ]
    out = SW.run_section_writer(project_id="p", user_id="u1", day_number=1,
                                coverage_mode="material_bound", lesson_plan=_PLAN,
                                ranked_sources=ranked, section_writer_runs=0)
    prot_id = "s2"     # protected corpus is 2nd in rank order → id s2
    covering = [d for d in out["section_drafts"] if d["group"] in ("A", "B")]
    cited = {c for d in covering for b in d["beats"] for c in b["citations"]}
    with capsys.disabled():
        print(f"\nprotected id={prot_id} cited in A/B groups: {prot_id in cited} (all cited: {sorted(cited)})")
    assert prot_id in cited     # protected source IS represented+cited where its topic is covered


# ── 2. each group's prompt carries only its routed sources ────────────────────
def test_each_group_gets_only_its_sources(db, monkeypatch, capsys):
    prompts: dict = {}
    monkeypatch.setattr(SW, "call_agent", _echo_writer(prompts))
    ranked = [{"src": "web", "url": f"https://w{i}.com", "title": f"t{i}", "content": f"content {i}",
               "rank_score": 1.0 - i * 0.05, "rank_origin": "web"} for i in range(10)]
    SW.run_section_writer(project_id="p2", user_id="u1", day_number=1, coverage_mode="open",
                          lesson_plan=_PLAN, ranked_sources=ranked, section_writer_runs=0)
    b_ids = _sources_in_prompt(prompts["feed_v2_write_b"])
    d_ids = _sources_in_prompt(prompts["feed_v2_write_d"])
    all_ids = {f"s{i}" for i in range(1, 11)}
    with capsys.disabled():
        print(f"\ncore(B)={sorted(b_ids)}  deeper(D)={sorted(d_ids)}")
    assert b_ids != all_ids and d_ids != all_ids     # NO group got the full ranked list
    assert b_ids and d_ids
    assert b_ids.isdisjoint(d_ids)                    # core and deeper are distinct subsets


# ── 3. output is genuine beats, not flat text ─────────────────────────────────
def test_output_is_beats_not_flat(db, monkeypatch, capsys):
    monkeypatch.setattr(SW, "call_agent", _echo_writer())
    ranked = [{"src": "web", "url": "https://w.com", "title": "t", "content": "c",
               "rank_score": 0.9, "rank_origin": "web"}]
    out = SW.run_section_writer(project_id="p3", user_id="u1", day_number=1, coverage_mode="open",
                                lesson_plan=_PLAN, ranked_sources=ranked, section_writer_runs=0)
    sec = out["section_drafts"][0]
    with capsys.disabled():
        print(f"\nsection keys={sorted(sec)} beat0 keys={sorted(sec['beats'][0])}")
    assert isinstance(sec["beats"], list) and sec["beats"]
    assert {"heading", "body", "visual", "citations"} <= set(sec["beats"][0])
    assert isinstance(sec["beats"][0]["citations"], list)
    assert "text" not in sec                          # NOT flat text with a beats wrapper


# ── 4. crash after group B: resume runs only C, D ─────────────────────────────
def test_crash_after_group_b_resumes_only_c_d(db, monkeypatch, capsys):
    monkeypatch.setattr(SW, "call_agent", _echo_writer())
    calls: list[str] = []
    real_write = SW._write_group

    def rigged(group, plan, sources, meta):
        calls.append(group)
        if group == "C" and rigged.armed:
            rigged.armed = False
            raise RuntimeError("simulated crash after group B")
        return real_write(group, plan, sources, meta)
    rigged.armed = True
    monkeypatch.setattr(SW, "_write_group", rigged)

    ranked = [{"src": "web", "url": "https://w.com", "title": "t", "content": "c",
               "rank_score": 0.9, "rank_origin": "web"}]
    kw = dict(project_id="pcrash", user_id="u1", day_number=1, coverage_mode="open",
              lesson_plan=_PLAN, ranked_sources=ranked, section_writer_runs=0)

    with pytest.raises(RuntimeError):
        SW.run_section_writer(**kw)              # writes A,B then crashes entering C
    assert calls == ["A", "B", "C"]             # A,B completed, C attempted

    calls.clear()
    out = SW.run_section_writer(**kw)            # resume: same attempt (runs still 0)
    with capsys.disabled():
        print(f"\nresume wrote groups: {calls}")
    assert calls == ["C", "D"]                  # ONLY C,D re-run — A,B loaded from DB, not regenerated
    assert {d["group"] for d in out["section_drafts"]} == {"A", "B", "C", "D"}   # full lesson present


# ── 5. fallback leg serves ────────────────────────────────────────────────────
def test_section_writer_fallback_leg(db, monkeypatch, capsys):
    from backend.services.feed_v2.llm import provider
    fb_id = provider.MODEL_REGISTRY["nemotron-super-120b"][1]   # section_writer fallback (openrouter)
    served: list[str] = []
    monkeypatch.setattr(provider, "_keys_for_provider", lambda p: ["fake-key"])

    def fake_google(*a, **k):
        raise RuntimeError("simulated primary (gemini) outage")

    def fake_openrouter(api_model_id, messages, system, schema, key, images=None):
        served.append(api_model_id)
        return {"text": json.dumps({"sections": [{"n": 1, "title": "T", "beats": [
                    {"heading": "h", "body": "b", "citations": []}]}]}),
                "in_tokens": 1, "out_tokens": 1, "latency_ms": 1, "model_used": api_model_id}

    monkeypatch.setitem(provider._SDK_FOR_PROVIDER, "google", fake_google)
    monkeypatch.setitem(provider._SDK_FOR_PROVIDER, "openrouter", fake_openrouter)
    monkeypatch.setattr(provider.call_logger, "write_call_row", lambda **k: None)

    ranked = [{"src": "web", "url": "https://w.com", "title": "t", "content": "c",
               "rank_score": 0.5, "rank_origin": "web"}]
    out = SW.run_section_writer(project_id="pfb", user_id="u1", day_number=1, coverage_mode="open",
                                lesson_plan=_PLAN, ranked_sources=ranked, section_writer_runs=0)
    with capsys.disabled():
        print(f"\nfallback served {len(served)} group calls: all fallback={all(s == fb_id for s in served)}")
    assert served and all(s == fb_id for s in served)   # all 4 group calls hit the fallback
    assert out["section_drafts"]


# ── 6. full graph: real lesson_planner + section_writer + web/corpus/ranker ───
def test_full_graph_real_writer(db, monkeypatch, capsys):
    G.USE_REAL_LESSON_PLANNER = True
    G.USE_REAL_SECTION_WRITER = True
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
    # lesson_planner + web + corpus + ranker + section_writer LLM boundaries mocked
    monkeypatch.setattr(LP, "call_agent", lambda *a, **k: {"objectives": ["understand backprop"], "prerequisite_gap": False})
    monkeypatch.setattr(W, "_search", lambda q: [{"title": "Guide", "url": "https://w.com/1", "snippet": "backprop"}])
    monkeypatch.setattr(W, "_fetch", lambda urls: {u: "Backpropagation uses the chain rule across layers." for u in urls})
    monkeypatch.setattr(W, "call_agent", lambda agent, messages, **k: (
        {"passages": [{"index": 0, "claim": "backprop uses the chain rule", "why_relevant": "core"}]}
        if "WEB RESULTS" in messages[0]["content"] else {"queries": ["backprop"]}))
    monkeypatch.setattr(CR, "embed_query", lambda t: [1.0] + [0.0] * (_DIM - 1))
    monkeypatch.setattr(CR, "call_agent", lambda *a, **k: {"passages": [{"index": 0, "quote": "Backprop chain rule", "why_relevant": "core"}]})
    monkeypatch.setattr(G.ranker_agent, "call_agent", lambda agent, messages, **k: {"scores": [{"index": 0, "score": 0.8}]})
    monkeypatch.setattr(SW, "call_agent", _echo_writer())

    trace_id, final = G.run_graph("u1", pid, 1)
    drafts = final["section_drafts"]
    groups = {d["group"] for d in drafts}
    sample = next(d for d in drafts if d["beats"])
    with capsys.disabled():
        print(f"\nfull-graph groups={sorted(groups)} sections={len(drafts)}")
        print("sample section:", json.dumps(sample)[:400])
    for key in ("lesson_plan", "web_findings", "corpus_findings", "ranked_sources",
                "section_drafts", "verdicts", "assembled"):
        assert final.get(key), f"missing {key}"
    assert groups == {"A", "B", "C", "D"}                       # all four groups written
    assert all("beats" in d for d in drafts)                    # beats shape end to end
    assert any(b["citations"] for d in drafts for b in d["beats"])   # real citations present
    assert final["lesson_plan"]["objectives"]                   # real lesson_plan wired in
    assert G._EXEC_LOG.count("assembler") == 1                  # barrier intact, ran once
    # group C persisted retrieval checks
    with v2db.get_connection() as c:
        n_checks = c.execute("SELECT COUNT(*) n FROM v2_retrieval_checks WHERE project_id=?", (pid,)).fetchone()["n"]
    assert n_checks >= 1                                        # Group C wrote to v2_retrieval_checks


# ── 7. live: real writing call — real beats + inline citations ────────────────
@pytest.mark.integration
@pytest.mark.skipif(not _HAS_KEY, reason="no Gemini API key")
def test_real_section_writer_beats_and_citations(db, capsys):
    ranked = [
        {"src": "web", "url": "https://en.wikipedia.org/wiki/Backpropagation", "title": "Backpropagation",
         "content": ("Backpropagation computes the gradient of the loss with respect to each weight by "
                     "the chain rule, propagating error backward from the output layer. It is the core "
                     "algorithm for training neural networks via gradient descent."),
         "rank_score": 0.95, "rank_origin": "web"},
        {"src": "corpus", "material_id": "m1", "chunk_index": 0,
         "text": "Gradient descent updates each weight by subtracting the learning rate times its gradient.",
         "rank_score": 0.6, "rank_origin": "corpus", "protected": True},
    ]
    out = SW.run_section_writer(project_id="plive", user_id="u1", day_number=1,
                                coverage_mode="material_bound", lesson_plan=_PLAN,
                                ranked_sources=ranked, section_writer_runs=0)
    drafts = out["section_drafts"]
    groups = {d["group"] for d in drafts}
    cited = [(d["group"], d["n"], b["citations"], b["body"][:110])
             for d in drafts for b in d["beats"] if b["citations"]]
    with capsys.disabled():
        print(f"\nLIVE groups={sorted(groups)} sections={len(drafts)}")
        for g, n, cites, body in cited[:5]:
            print(f"  [{g}] sec{n} cites={cites} :: {body}")
    assert groups == {"A", "B", "C", "D"}                       # all four groups written for real
    assert all(isinstance(d["beats"], list) and d["beats"] for d in drafts)   # real beats everywhere
    assert cited, "no beat carried an inline citation"
    ab_cites = {c for d in drafts if d["group"] in ("A", "B") for b in d["beats"] for c in b["citations"]}
    assert ab_cites, "framing/core cited nothing"              # sources actually consumed + cited
