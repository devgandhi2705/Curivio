"""
Feed v2 graph skeleton (Phase 7) — infrastructure tests.

Mostly offline (the stubs return canned data; source_ranker's real call is disabled
via USE_REAL_SOURCE_RANKER=False for these). The single integration test at the
bottom flips it on to prove the graph -> provider -> call_logger chain writes a real
llm_call_log row with all four Phase-3 columns.

Proves: full run populates state; all 3 loop caps fire exactly; resume-after-crash
via the checkpointer; concurrency rejected by the unique index (not app-level);
reaper flips expired leases only; SSE streams + labels loops + reattaches by trace_id.
"""
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest
import sqlite_vec

from backend.database.schema import ALL_TABLES, MIGRATIONS
from backend.services.feed_v2 import db as v2db
from backend.services.feed_v2.schema import run_v2_migrations
from backend.services.feed_v2 import projects as P
from backend.services.feed_v2 import graph as G

_HAS_KEY = bool(os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY"))


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
    path = str(tmp_path / "graph.db")
    _build_db(path)
    monkeypatch.setattr(v2db, "DB_PATH", path)
    return path


@pytest.fixture(autouse=True)
def _rig():
    G._reset_rig()
    G.USE_REAL_SOURCE_RANKER = False   # offline default; the integration test flips it
    yield
    G._reset_rig()


def _ready_project(coverage_mode="open"):
    proj = P.create_project("u1", "Subject", "learn it", "intermediate")
    profile = {"learning_subject": "Subject", "persona": "S", "coverage_mode": coverage_mode}
    with v2db.get_connection() as c:
        c.execute("UPDATE v2_projects SET profile_json=?, coverage_mode=?, profile_status='ready' WHERE project_id=?",
                  (json.dumps(profile), coverage_mode, proj["project_id"]))
    return proj["project_id"]


def _base(trace_id="t"):
    return {"trace_id": trace_id, "user_id": "u1", "project_id": "p", "day_number": 1,
            "profile": {}, "coverage_mode": "open", "journey_entry": {"focus": "x"},
            "web_findings": [], "corpus_findings": [], "web_research_iters": 0,
            "section_writer_runs": 0, "rewrite_iters": 0, "research_reentry_iters": 0}


# ── graph mechanics (no DB, no checkpointer needed) ───────────────────────────
def test_full_run_populates_state(capsys):
    final = G.compile_graph().invoke(_base())
    with capsys.disabled():
        print("\nassembled:", json.dumps(final["assembled"]))
    for key in ("lesson_plan", "web_findings", "corpus_findings", "ranked_sources",
                "section_drafts", "verdicts", "assembled"):
        assert final.get(key), f"missing {key}"
    assert G._EXEC_LOG.count("assembler") == 1
    assert final["assembled"]["sections"] and final["assembled"]["sources"]


def test_web_loop_caps_at_three():
    G.STUB_EVIDENCE_THIN = True
    G.compile_graph().invoke(_base())
    assert G._EXEC_LOG.count("web_researcher") == G.MAX_WEB_ITERS == 3


def test_rewrite_loop_caps_at_two():
    G.STUB_WRITING_WEAK = True
    G.compile_graph().invoke(_base())
    # 1 initial write + MAX_REWRITES rewrites
    assert G._EXEC_LOG.count("section_writer") == 1 + G.MAX_REWRITES == 3


def test_evidence_reentry_caps_at_one():
    G.STUB_EVIDENCE_WEAK = True
    G.compile_graph().invoke(_base())
    assert G._EXEC_LOG.count("research_reentry") == G.MAX_RESEARCH_REENTRY == 1
    assert G._EXEC_LOG.count("web_researcher") == 2   # initial + 1 re-entry


# ── checkpointer: resume-after-crash ──────────────────────────────────────────
def test_resume_after_crash(db, capsys):
    cfg = {"configurable": {"thread_id": "run1"}}
    G._CRASH_ONCE = {"source_ranker"}
    with pytest.raises(RuntimeError):
        G.compile_graph(G._saver()).invoke(_base("run1"), cfg)
    before = list(G._EXEC_LOG)
    final = G.compile_graph(G._saver()).invoke(None, cfg)   # None -> resume from checkpoint
    with capsys.disabled():
        print(f"\nexec before crash: {before}\nexec after resume: {G._EXEC_LOG}")
    assert G._EXEC_LOG.count("lesson_planner") == 1          # NOT restarted from node 1
    assert final.get("assembled")                            # completed on resume


# ── concurrency: unique index, not app-level check ────────────────────────────
def test_concurrent_run_rejected_by_unique_index(db, capsys):
    G.acquire_lease("trace-A", "u1", "projX", 5)
    with pytest.raises(G.ConcurrentRunError):
        G.acquire_lease("trace-B", "u1", "projX", 5)   # same (project, day) -> index rejects
    with v2db.get_connection() as c:
        n = c.execute("SELECT COUNT(*) FROM mas_runs WHERE project_id='projX' AND day_number=5 AND status='running'").fetchone()[0]
    with capsys.disabled():
        print(f"\nconcurrent: running rows for (projX,5) = {n}")
    assert n == 1   # only the first holds the slot
    # a DIFFERENT (project, day) is allowed concurrently
    G.acquire_lease("trace-C", "u1", "projX", 6)


# ── reaper ────────────────────────────────────────────────────────────────────
def test_reaper_flips_expired_leaves_fresh(db, capsys):
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    future = (datetime.now(timezone.utc) + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
    with v2db.get_connection() as c:
        c.execute("INSERT INTO mas_runs (trace_id,surface,user_id,project_id,day_number,status,lease_expires_at,started_at) VALUES ('exp','feed_v2','u1','pa',1,'running',?,?)", (past, past))
        c.execute("INSERT INTO mas_runs (trace_id,surface,user_id,project_id,day_number,status,lease_expires_at,started_at) VALUES ('live','feed_v2','u1','pb',1,'running',?,?)", (future, future))
    reaped = G.reap_expired_runs()
    assert G.reap_expired_runs() == 0   # idempotent: second sweep finds nothing
    with v2db.get_connection() as c:
        rows = {r["trace_id"]: r["status"] for r in c.execute("SELECT trace_id,status FROM mas_runs").fetchall()}
    with capsys.disabled():
        print(f"\nreaper: reaped={reaped} statuses={rows}")
    assert reaped == 1
    assert rows["exp"] == "failed"    # expired lease reaped
    assert rows["live"] == "running"  # fresh lease left alone


# ── runner: lease + finalize + totals ─────────────────────────────────────────
def test_run_graph_finalizes_mas_run(db):
    pid = _ready_project()
    trace_id, final = G.run_graph("u1", pid, 1)
    assert final.get("assembled")
    with v2db.get_connection() as c:
        row = dict(c.execute("SELECT status, ended_at, total_calls FROM mas_runs WHERE trace_id=?", (trace_id,)).fetchone())
    assert row["status"] == "done" and row["ended_at"]
    assert row["total_calls"] == 0   # offline: no real LLM call this run


# ── SSE ───────────────────────────────────────────────────────────────────────
def test_sse_streams_node_events_and_labels_loops(db, capsys):
    G.STUB_EVIDENCE_THIN = True
    events = [json.loads(e) for e in G.stream_events("s1", _base("s1"))]
    kinds = [(e["t"], e.get("agent")) for e in events]
    with capsys.disabled():
        print("\nSSE events:", kinds)
    assert events[0]["t"] == "start" and events[-1]["t"] == "done"
    # web_researcher looped: at least one distinctly-labeled loop event
    loops = [e for e in events if e["t"] == "loop" and e["agent"] == "web_researcher"]
    assert loops and loops[0]["label"]


def test_sse_reconnect_resumes_not_restarts(db, capsys):
    cfg = {"configurable": {"thread_id": "recon"}}
    G._CRASH_ONCE = {"source_ranker"}
    with pytest.raises(RuntimeError):
        G.compile_graph(G._saver()).invoke(_base("recon"), cfg)   # partial checkpoint
    # reconnect with the same trace_id -> resume from the checkpoint
    events = [json.loads(e) for e in G.stream_events("recon", None)]
    agents = [e.get("agent") for e in events if e["t"] in ("node", "loop")]
    with capsys.disabled():
        print(f"\nreconnect agents: {agents}")
    assert events[0]["resumed"] is True
    assert "lesson_planner" not in agents      # already ran — NOT replayed
    assert "assembler" in agents               # finishes from where it was
    assert G._EXEC_LOG.count("lesson_planner") == 1


def test_slow_node_still_streams(db, capsys):
    G.STUB_SLEEP_SECONDS = 1.0
    t0 = time.monotonic()
    events = [json.loads(e) for e in G.stream_events("slow", _base("slow"))]
    elapsed = time.monotonic() - t0
    with capsys.disabled():
        print(f"\nslow-node stream: {len(events)} events, {elapsed:.2f}s")
    assert elapsed >= 1.0                       # the slow lesson_planner ran
    assert any(e.get("agent") == "lesson_planner" for e in events)
    assert events[-1]["t"] == "done"


# ── the ONE real provider call: log-row proof (integration) ───────────────────
@pytest.mark.integration
@pytest.mark.skipif(not _HAS_KEY, reason="no Gemini API key")
def test_real_source_ranker_writes_log_row_with_all_four_columns(db, capsys):
    G.USE_REAL_SOURCE_RANKER = True
    trace_id, final = G.run_graph("u1", _ready_project(), 1)
    with v2db.get_connection() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT agent_name, trace_id, step_index, surface, success FROM llm_call_log WHERE trace_id=? AND agent_name='source_ranker'",
            (trace_id,)).fetchall()]
        run = dict(c.execute("SELECT total_calls FROM mas_runs WHERE trace_id=?", (trace_id,)).fetchone())
    with capsys.disabled():
        print(f"\nsource_ranker log rows: {rows}\nmas_run total_calls: {run['total_calls']}")
    assert rows, "no source_ranker row in llm_call_log"
    r = rows[0]
    assert r["agent_name"] == "source_ranker"
    assert r["trace_id"] == trace_id
    assert r["step_index"] == 3
    assert r["surface"] == "feed_v2"
    assert run["total_calls"] >= 1   # finalize summed the real call
