"""
Feed v2 lesson_planner (Phase 11) — the decision layer.

Offline/deterministic: the one decision call is mocked so the gating logic (section-3
prerequisite gate + worked-example mode) is asserted without a key. One live test does a
real decision call. Fallback test exercises the real routing.

Proves:
  - section 3 gates ON when prerequisites exist AND the model calls them a real gap;
  - section 3 gates OFF when there are no prerequisites (empty overrides a stray gap vote);
  - worked-example mode maps from project difficulty (beginner/intermediate/advanced);
  - section_4b is always 'pending' (claim_validator, Phase 13, decides it later);
  - the fallback provider leg serves.
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
from backend.services.feed_v2.agents import lesson_planner as LP

_HAS_KEY = bool(os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY"))


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "lp.db")
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


def _fake_decide(gap, objectives=("obj-1", "obj-2")):
    def f(agent, messages, system="", schema=None, meta=None):
        return {"objectives": list(objectives), "prerequisite_gap": gap}
    return f


# ── prerequisite gate: ON with a real gap ─────────────────────────────────────
def test_prereq_gate_on_with_gap(db, monkeypatch, capsys):
    monkeypatch.setattr(LP, "call_agent", _fake_decide(True))
    proj = P.create_project("u1", "Neural nets", "exam", "intermediate")
    je = {"focus": "backprop", "prerequisite_concepts": ["chain rule", "gradients"]}
    plan = LP.run_lesson_planner(project_id=proj["project_id"], journey_entry=je,
                                 coverage_mode="open")["lesson_plan"]
    with capsys.disabled():
        print(f"\ngap+prereqs -> render_prerequisites={plan['render_prerequisites']} 4b={plan['section_4b']}")
    assert plan["render_prerequisites"] is True       # prereqs present + model gap -> section 3 ON
    assert plan["section_4b"] == "pending"            # 4b never on/off here
    assert plan["objectives"] and plan["worked_example_mode"] == "example-first"


# ── prerequisite gate: OFF when there are no prerequisites ─────────────────────
def test_prereq_gate_off_no_prereqs(db, monkeypatch, capsys):
    monkeypatch.setattr(LP, "call_agent", _fake_decide(True))   # model votes gap even so
    proj = P.create_project("u1", "Neural nets", "exam", "intermediate")
    je = {"focus": "intro", "prerequisite_concepts": []}        # day-1: nothing carried
    plan = LP.run_lesson_planner(project_id=proj["project_id"], journey_entry=je,
                                 coverage_mode="open")["lesson_plan"]
    with capsys.disabled():
        print(f"\nno prereqs -> render_prerequisites={plan['render_prerequisites']}")
    assert plan["render_prerequisites"] is False      # empty prereqs override the gap vote -> OFF


# ── worked-example mode maps from difficulty ──────────────────────────────────
def test_worked_example_mode_by_difficulty(db, monkeypatch, capsys):
    monkeypatch.setattr(LP, "call_agent", _fake_decide(False))
    got = {}
    for diff in ("beginner", "intermediate", "advanced"):
        proj = P.create_project("u1", f"P-{diff}", "g", diff)
        plan = LP.run_lesson_planner(project_id=proj["project_id"],
                                     journey_entry={"focus": "x"}, coverage_mode="open")["lesson_plan"]
        got[diff] = plan["worked_example_mode"]
    with capsys.disabled():
        print(f"\ndifficulty -> mode: {got}")
    assert got == {"beginner": "example-first", "intermediate": "example-first",
                   "advanced": "problem-first"}


# ── fallback leg serves ───────────────────────────────────────────────────────
def test_lesson_planner_fallback_leg(db, monkeypatch, capsys):
    from backend.services.feed_v2.llm import provider
    fb_id = provider.MODEL_REGISTRY["nemotron-nano-30b"][1]   # lesson_planner fallback (openrouter)
    served: list[str] = []
    monkeypatch.setattr(provider, "_keys_for_provider", lambda p: ["fake-key"])

    def fake_google(*a, **k):
        raise RuntimeError("simulated primary (gemini) outage")

    def fake_openrouter(api_model_id, messages, system, schema, key, images=None):
        served.append(api_model_id)
        return {"text": json.dumps({"objectives": ["o1"], "prerequisite_gap": False}),
                "in_tokens": 1, "out_tokens": 1, "latency_ms": 1, "model_used": api_model_id}

    monkeypatch.setitem(provider._SDK_FOR_PROVIDER, "google", fake_google)
    monkeypatch.setitem(provider._SDK_FOR_PROVIDER, "openrouter", fake_openrouter)
    monkeypatch.setattr(provider.call_logger, "write_call_row", lambda **k: None)

    proj = P.create_project("u1", "NN", "g", "intermediate")
    plan = LP.run_lesson_planner(project_id=proj["project_id"],
                                 journey_entry={"focus": "x", "prerequisite_concepts": ["a"]},
                                 coverage_mode="open")["lesson_plan"]
    with capsys.disabled():
        print(f"\nfallback served: {served}")
    assert served and all(s == fb_id for s in served)
    assert plan["objectives"] == ["o1"]


# ── live: real decision call ──────────────────────────────────────────────────
@pytest.mark.integration
@pytest.mark.skipif(not _HAS_KEY, reason="no Gemini API key")
def test_real_lesson_plan(db, capsys):
    proj = P.create_project("u1", "Neural networks", "exam prep", "intermediate")
    je = {"focus": "how backpropagation trains neural networks",
          "prerequisite_concepts": ["the chain rule", "partial derivatives"]}
    plan = LP.run_lesson_planner(project_id=proj["project_id"], journey_entry=je,
                                 coverage_mode="open")["lesson_plan"]
    with capsys.disabled():
        print(f"\nLIVE plan: objectives={plan['objectives']} render_prereq={plan['render_prerequisites']} "
              f"mode={plan['worked_example_mode']} 4b={plan['section_4b']}")
    assert plan["objectives"], "real call produced no objectives"
    assert plan["worked_example_mode"] == "example-first"   # intermediate
    assert plan["section_4b"] == "pending"
    assert isinstance(plan["render_prerequisites"], bool)
