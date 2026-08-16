"""
Feed v2 journey planner — offline unit tests (no network, in default suite).

Covers the deterministic contracts:
  - material_bound day_count = the document's actual section count, UNCLAMPED (the
    Phase-6 step-3 design decision), vs the [7,20] clamp kept for anchored/open.
  - material_bound day ORDER binds to structure_json order (source_section per day).
  - shape LOCK: an unchanged description reuses the locked shape (continuation
    prompt, no re-decide); a changed description re-decides.
  - APPEND-ONLY: re-planning inserts a new batch row; get_day_entry reads the newest.
  - NO SILENT FALLBACK: a forced failure writes no plan row and marks
    journey_status='failed'.
  - the new journey_planner role's fallback leg serves through the routing table
    (primary nemotron forced to fail -> gemini fallback), deterministically.

Live-LLM cases (real plans in each mode, real rotating_theme) live in
test_feed_v2_journey.py (integration, skip-no-key).
"""
import json
import sqlite3

import pytest
import sqlite_vec

from backend.database.schema import ALL_TABLES, MIGRATIONS
from backend.services.feed_v2 import db as v2db
from backend.services.feed_v2.schema import run_v2_migrations
from backend.services.feed_v2 import projects as P
from backend.services.feed_v2 import journeys as J
from backend.services.feed_v2.agents import journey_planner as A
from backend.services.feed_v2.llm.provider import AllLegsFailed


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
    path = str(tmp_path / "journey.db")
    _build_db(path)
    monkeypatch.setattr(v2db, "DB_PATH", path)
    return path


def _ready_project(coverage_mode, *, description="learn the subject", material_scope="scope"):
    """Create a project already carrying a ready profile + coverage_mode (skips the
    live profile agent)."""
    proj = P.create_project("u1", "Test Subject", description, "intermediate")
    profile = {"learning_subject": "Test Subject", "persona": "Student", "goal": "learn",
               "primary_focus": "core", "search_lens": "Educational", "material_scope": material_scope,
               "coverage_mode": coverage_mode, "coverage_reasoning": "x"}
    with v2db.get_connection() as c:
        c.execute("UPDATE v2_projects SET profile_json=?, coverage_mode=?, material_scope=?, profile_status='ready' WHERE project_id=?",
                  (json.dumps(profile), coverage_mode, material_scope, proj["project_id"]))
    return proj["project_id"]


def _add_material(project_id, mid, titles):
    structure = json.dumps([{"title": t, "level": 1} for t in titles])
    with v2db.get_connection() as c:
        c.execute("""INSERT INTO v2_materials
                        (material_id,user_id,project_id,type,filename,extraction_status,
                         structure_json,has_structure,section_count,created_at)
                     VALUES (?,?,?, 'document', ?, 'done', ?, 1, ?, datetime('now'))""",
                  (mid, "u1", project_id, mid + ".md", structure, len(titles)))


def _fixed_days(n):
    return {"shape": "fixed_sequence", "day_count": n, "reasoning": "r",
            "days": [{"day_number": i + 1, "focus": f"focus {i+1}", "display_title": f"Day {i+1}",
                      "frame_hint": "timeline", "prerequisite_concepts": [], "rationale": "x"}
                     for i in range(n)]}


def test_material_bound_daycount_unclamped_and_ordered(db, monkeypatch, capsys):
    """3 sections -> day_count 3 (below MIN 7, UNCLAMPED); 25 -> 25 (above MAX 20).
    And day order binds to structure_json order."""
    # 3 chapters (below the [7,20] floor)
    pid3 = _ready_project("material_bound")
    _add_material(pid3, "m3", ["Alpha", "Beta", "Gamma"])
    monkeypatch.setattr(A, "call_agent", lambda *a, **k: _fixed_days(3))
    b3 = J.plan_next_batch("u1", pid3)

    # 25 chapters (above the [7,20] ceiling)
    pid25 = _ready_project("material_bound")
    big = [f"Ch{i}" for i in range(25)]
    _add_material(pid25, "m25", big)
    monkeypatch.setattr(A, "call_agent", lambda *a, **k: _fixed_days(30))  # model over-emits; agent truncates
    b25 = J.plan_next_batch("u1", pid25)

    with capsys.disabled():
        print(f"\nmaterial_bound day_count: 3-section doc -> {b3['day_count']}  |  25-section doc -> {b25['day_count']}")
    assert b3["day_count"] == 3 and b3["day_end"] == 3      # UNCLAMPED below MIN
    assert b25["day_count"] == 25 and b25["day_end"] == 25  # UNCLAMPED above MAX
    # order binds to structure_json order
    assert [d["source_section"] for d in b3["days"]] == ["Alpha", "Beta", "Gamma"]
    assert len(b25["days"]) == 25 and b25["days"][0]["source_section"] == "Ch0"


def test_anchored_and_open_stay_clamped(db, monkeypatch):
    """Non-bound modes keep the [7,20] clamp — the planner is choosing a length."""
    for mode in ("material_anchored", "open"):
        pid = _ready_project(mode)
        monkeypatch.setattr(A, "call_agent", lambda *a, **k: _fixed_days(3))   # asks for 3
        low = J.plan_next_batch("u1", pid)
        assert low["day_count"] == 7, (mode, low["day_count"])                 # clamped UP to MIN

        pid2 = _ready_project(mode)
        monkeypatch.setattr(A, "call_agent", lambda *a, **k: _fixed_days(30))  # asks for 30
        high = J.plan_next_batch("u1", pid2)
        assert high["day_count"] == 20, (mode, high["day_count"])              # clamped DOWN to MAX


def test_no_silent_fallback_on_failure(db, monkeypatch, capsys):
    pid = _ready_project("open")

    def _boom(*a, **k):
        raise AllLegsFailed("journey_planner: all legs failed (simulated)")
    monkeypatch.setattr(A, "call_agent", _boom)

    with pytest.raises(AllLegsFailed):
        J.plan_next_batch("u1", pid)

    with v2db.get_connection() as c:
        n = c.execute("SELECT COUNT(*) FROM v2_journey_plans WHERE project_id=?", (pid,)).fetchone()[0]
        proj = dict(c.execute("SELECT journey_shape, journey_status FROM v2_projects WHERE project_id=?", (pid,)).fetchone())
    with capsys.disabled():
        print(f"\nFAILED plan: rows={n}  project={proj}")
    assert n == 0                              # NO fake plan row written
    assert proj["journey_status"] == "failed"  # visible failure state
    assert proj["journey_shape"] is None       # shape not falsely locked


def test_shape_lock_reuses_then_redecides_on_description_change(db, monkeypatch, capsys):
    pid = _ready_project("open", description="teach me the fundamentals")
    prompts = []

    def _capture(agent, messages, system="", **k):
        prompts.append(messages[0]["content"])
        return _fixed_days(8)
    monkeypatch.setattr(A, "call_agent", _capture)

    J.plan_next_batch("u1", pid)                       # batch 1: full decision
    J.plan_next_batch("u1", pid)                       # batch 2: same description -> locked
    # change the description -> lock clears
    with v2db.get_connection() as c:
        c.execute("UPDATE v2_projects SET description='keep me current on the topic' WHERE project_id=?", (pid,))
    J.plan_next_batch("u1", pid)                       # batch 3: re-decide

    decided = ["DECIDE THE JOURNEY SHAPE" in p for p in prompts]
    locked = ["THE SHAPE IS ALREADY DECIDED" in p for p in prompts]
    with capsys.disabled():
        print(f"\nprompts decided={decided} locked={locked}")
    assert decided[0] and not locked[0]     # 1st: full decision
    assert locked[1] and not decided[1]     # 2nd: locked continuation (no re-decide)
    assert decided[2] and not locked[2]     # 3rd: description changed -> re-decide


def test_append_only_and_get_day_entry(db, monkeypatch):
    pid = _ready_project("open")
    monkeypatch.setattr(A, "call_agent", lambda *a, **k: _fixed_days(8))
    J.plan_next_batch("u1", pid)             # days 1-8
    J.plan_next_batch("u1", pid)             # days 9-16 (append)

    with v2db.get_connection() as c:
        n = c.execute("SELECT COUNT(*) FROM v2_journey_plans WHERE project_id=?", (pid,)).fetchone()[0]
    assert n == 2                            # two batch rows, nothing updated/deleted

    e = J.get_day_entry("u1", pid, 10)       # falls in the 2nd batch
    assert e and e["day_number"] == 10
    assert J.get_day_entry("u1", pid, 999) is None


def test_material_bound_under_emission_is_a_real_failure(db, monkeypatch, capsys):
    """Phase 6b: in material_bound, entries < sections must FAIL (document fidelity),
    not silently repeat the last day. No plan row, journey_status='failed'."""
    pid = _ready_project("material_bound")
    _add_material(pid, "m", ["Alpha", "Beta", "Gamma"])          # 3 sections
    monkeypatch.setattr(A, "call_agent", lambda *a, **k: _fixed_days(1))  # model emits only 1 day

    with pytest.raises(ValueError, match="dropped chapters"):
        J.plan_next_batch("u1", pid)

    with v2db.get_connection() as c:
        n = c.execute("SELECT COUNT(*) FROM v2_journey_plans WHERE project_id=?", (pid,)).fetchone()[0]
        proj = dict(c.execute("SELECT journey_status FROM v2_projects WHERE project_id=?", (pid,)).fetchone())
    with capsys.disabled():
        print(f"\nmaterial_bound under-emission: rows={n} journey_status={proj['journey_status']!r}")
    assert n == 0                                # no plan row written
    assert proj["journey_status"] == "failed"    # visible failure


def test_anchored_open_under_emission_still_repeats(db, monkeypatch):
    """material_anchored/open are UNAFFECTED by the Phase-6b guard: under-emission is
    still tolerated (day_count is the clamped choice; get_day_entry repeats the last
    entry for tail days) exactly as before."""
    for mode in ("material_anchored", "open"):
        pid = _ready_project(mode)
        under = {"shape": "fixed_sequence", "day_count": 10, "reasoning": "r",
                 "days": [{"day_number": i + 1, "focus": f"f{i}", "display_title": f"D{i}",
                           "frame_hint": "timeline", "prerequisite_concepts": [], "rationale": "x"}
                          for i in range(3)]}                     # only 3 entries for a day_count of 10
        monkeypatch.setattr(A, "call_agent", lambda *a, _u=under, **k: {**_u, "days": [dict(d) for d in _u["days"]]})
        b = J.plan_next_batch("u1", pid)                          # no raise
        assert b["day_count"] == 10, (mode, b["day_count"])       # clamped choice preserved
        e = J.get_day_entry("u1", pid, 8)                         # tail day past the 3 entries
        assert e is not None and e["day_number"] == 3, (mode, e)  # repeat-last last entry, as before


def test_journey_fallback_leg_serves_through_routing(db, monkeypatch, capsys):
    """Deterministic (no network/keys): force the primary journey_planner leg
    (nemotron) to fail; prove call_agent routes to the gemini fallback and its
    payload flows back into the saved plan."""
    from backend.services.feed_v2.llm import provider
    primary_id = provider.MODEL_REGISTRY["nemotron-nano-30b"][1]
    fallback_id = provider.MODEL_REGISTRY["gemini-3-flash-preview"][1]
    served = []
    monkeypatch.setattr(provider, "_keys_for_provider", lambda p: ["fake-key"])

    def fake_openrouter(api_model_id, *a, **k):
        raise RuntimeError("simulated primary (nemotron) outage")

    def fake_google(api_model_id, messages, system, schema, key, images=None):
        served.append(api_model_id)
        return {"text": json.dumps(_fixed_days(8)), "in_tokens": 1, "out_tokens": 1,
                "latency_ms": 1, "model_used": api_model_id}

    monkeypatch.setitem(provider._SDK_FOR_PROVIDER, "openrouter", fake_openrouter)
    monkeypatch.setitem(provider._SDK_FOR_PROVIDER, "google", fake_google)
    monkeypatch.setattr(provider.call_logger, "write_call_row", lambda **k: None)

    pid = _ready_project("open")
    batch = J.plan_next_batch("u1", pid)
    with capsys.disabled():
        print(f"\njourney fallback routing (offline): primary {primary_id} failed -> served {served}")
    assert served == [fallback_id]
    assert batch["shape"] == "fixed_sequence" and batch["day_count"] == 8
