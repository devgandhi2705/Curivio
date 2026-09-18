"""
Feed v2 Phase 12 — full graph run with REAL visual_director + visual_sourcing.

Same "real node, mocked LLM/network boundary" pattern test_feed_v2_section_writer.py's
test_full_graph_real_writer uses, extended two nodes further: real lesson_planner,
web_researcher, corpus_researcher, source_ranker, section_writer, visual_director,
visual_sourcing all run for real; only their LLM calls (and web search/fetch) are
mocked for determinism. A real Phase-4 figure is seeded so tier 1 can genuinely fire.

Proves: real visuals attach to real beats, and fan-in + downstream nodes
(claim_validator, assembler) are unaffected by the two new nodes.
"""
import json
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
from backend.services.feed_v2.agents import visual_director as VD
from backend.services.feed_v2.agents import visual_sourcing as VS

_DIM = 3072
_VEC = [1.0] + [0.0] * (_DIM - 1)


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "visualgraph.db")
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


def _echo_writer_with_visual_hint():
    def f(agent, messages, system="", schema=None, meta=None):
        return {"sections": [{"n": 1, "title": "Partitioning", "beats": [
            {"heading": "How partitioning works",
             "body": "Quicksort partitions the array around a pivot element.",
             "visual": "a process diagram of the partition steps", "citations": []}]}]}
    return f


def test_full_graph_real_visuals_attached_to_real_beats(db, monkeypatch, capsys):
    G.USE_REAL_LESSON_PLANNER = True
    G.USE_REAL_SECTION_WRITER = True
    G.USE_REAL_WEB_RESEARCHER = True
    G.USE_REAL_CORPUS_RESEARCHER = True
    G.USE_REAL_SOURCE_RANKER = True
    G.USE_REAL_VISUAL_DIRECTOR = True
    G.USE_REAL_VISUAL_SOURCING = True

    proj = P.create_project("u1", "Algorithms", "exam", "intermediate")
    pid = proj["project_id"]
    with v2db.get_connection() as c:
        c.execute("UPDATE v2_projects SET coverage_mode='open', profile_status='ready' WHERE project_id=?", (pid,))
        c.execute("INSERT INTO v2_materials(material_id,user_id,project_id,type,filename,extraction_status) "
                  "VALUES('m1','u1',?,'document','n.pdf','done')", (pid,))
        c.execute("INSERT INTO v2_material_chunks(chunk_id,user_id,material_id,project_id,chunk_index,chunk_text) "
                  "VALUES('c1','u1','m1',?,0,'Quicksort partitions the array')", (pid,))
        c.execute("INSERT INTO v2_material_chunks_vec(embedding,chunk_id,material_id,project_id,user_id,chunk_text,created_at) "
                  "VALUES(?,?,?,?,?,?,datetime('now'))",
                  (json.dumps(_VEC), "c1", "m1", pid, "u1", "Quicksort partitions the array"))
        # Phase 4 real figure — tier 1's data source, matched via the SAME embed_query mock
        c.execute("INSERT INTO v2_material_figures"
                  "(figure_id,user_id,material_id,project_id,page_no,caption,image_key,embedding_ref,created_at) "
                  "VALUES('fig1','u1','m1',?,0,'Figure 1: Quicksort partition steps',"
                  "'v2/figures/m1/fig1.png',?,datetime('now'))", (pid, json.dumps(_VEC)))

    monkeypatch.setattr(LP, "call_agent",
                        lambda *a, **k: {"objectives": ["understand quicksort"], "prerequisite_gap": False})
    monkeypatch.setattr(W, "_search", lambda q: [{"title": "Guide", "url": "https://w.com/1", "snippet": "quicksort"}])
    monkeypatch.setattr(W, "_fetch",
                        lambda urls: {u: {"text": "Quicksort partitions around a pivot.", "images": []} for u in urls})
    monkeypatch.setattr(W, "call_agent", lambda agent, messages, **k: (
        {"passages": [{"index": 0, "claim": "quicksort partitions around a pivot", "why_relevant": "core"}]}
        if "WEB RESULTS" in messages[0]["content"] else {"queries": ["quicksort"]}))
    monkeypatch.setattr(CR, "embed_query", lambda t: _VEC)
    monkeypatch.setattr(CR, "call_agent", lambda *a, **k: {
        "passages": [{"index": 0, "quote": "Quicksort partitions the array", "why_relevant": "core"}]})
    monkeypatch.setattr(G.ranker_agent, "call_agent", lambda agent, messages, **k: {"scores": [{"index": 0, "score": 0.8}]})
    monkeypatch.setattr(SW, "call_agent", _echo_writer_with_visual_hint())
    monkeypatch.setattr(VD, "call_agent", lambda agent, messages, system="", schema=None, meta=None: {
        "specs": [{"index": 0, "needs_visual": True, "visual_type": "process", "topic": "quicksort partition steps"}]})
    monkeypatch.setattr(VS, "embed_query", lambda t: _VEC)

    trace_id, final = G.run_graph("u1", pid, 1)
    with capsys.disabled():
        print(f"\nvisual_specs: {json.dumps(final.get('visual_specs'))}")
        print("visual_assets:", json.dumps([{k: v for k, v in a.items() if k != "svg"}
                                            for a in final.get("visual_assets", [])]))

    for key in ("lesson_plan", "web_findings", "corpus_findings", "ranked_sources",
               "section_drafts", "visual_specs", "visual_assets", "verdicts", "assembled"):
        assert final.get(key), f"missing {key}"

    assert final["visual_specs"][0]["visual_type"] == "process"
    asset = final["visual_assets"][0]
    assert asset["validated"] is True
    assert asset["tier"] == 1                       # real figure, real cosine match — not generated
    assert asset["figure_id"] == "fig1"
    assert asset["caption"] == "Figure 1: Quicksort partition steps"

    # fan-in / downstream unaffected: each ran exactly once, no duplicate/skip
    assert G._EXEC_LOG.count("visual_director") == 1
    assert G._EXEC_LOG.count("visual_sourcing") == 1
    assert G._EXEC_LOG.count("claim_validator") == 1
    assert G._EXEC_LOG.count("assembler") == 1


def test_full_graph_visual_nodes_stay_stubbed_offline(db, monkeypatch, capsys):
    """Regression guard: with the rig at its offline default (every OTHER Phase-7
    mechanics test in this codebase), the two new nodes still run (appear in
    _EXEC_LOG) but contribute empty state — no key/DB/browser needed, and no
    behavior change for tests that don't opt into real visuals."""
    G.USE_REAL_WEB_RESEARCHER = False
    G.USE_REAL_CORPUS_RESEARCHER = False
    G.USE_REAL_LESSON_PLANNER = False
    G.USE_REAL_SECTION_WRITER = False
    # USE_REAL_VISUAL_DIRECTOR / USE_REAL_VISUAL_SOURCING already False via _reset_rig()

    proj = P.create_project("u1", "X", "y", "intermediate")
    pid = proj["project_id"]
    with v2db.get_connection() as c:
        c.execute("UPDATE v2_projects SET coverage_mode='open', profile_status='ready' WHERE project_id=?", (pid,))
    trace_id, final = G.run_graph("u1", pid, 1)
    with capsys.disabled():
        print(f"\noffline visual_specs={final.get('visual_specs')} visual_assets={final.get('visual_assets')}")
    assert final.get("visual_specs") == []
    assert final.get("visual_assets") == []
    assert "visual_director" in G._EXEC_LOG and "visual_sourcing" in G._EXEC_LOG
