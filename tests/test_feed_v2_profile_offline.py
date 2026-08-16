"""
Feed v2 profile agent — offline unit tests (no network, in default suite).

Covers the parts that must NOT depend on a live LLM:
  - the NO-SILENT-FALLBACK contract: a failed generation leaves profile_status=
    'failed' and writes NO fake "Learner" profile (the explicit reversal of legacy
    intent_profile_service's silent default), asserted as real assertions.
  - generate_profile persists the agent output correctly (profile_json + the three
    coverage columns + profile_status='ready').
  - the prompt actually RECEIVES the queryable has_structure/section_count signals
    (Phase 5 step 3 requirement), not just raw text.
  - create_project + set_coverage_mode override round-trip.

The live-LLM cases (real persona output, opposite coverage_mode, thin-title rescue,
provider fallback leg) live in test_feed_v2_profile.py (integration, skip-no-key).
"""
import json
import sqlite3

import pytest
import sqlite_vec

from backend.database.schema import ALL_TABLES, MIGRATIONS
from backend.services.feed_v2 import db as v2db
from backend.services.feed_v2.schema import run_v2_migrations
from backend.services.feed_v2 import projects as P
from backend.services.feed_v2.agents import profile as A
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
    path = str(tmp_path / "profile.db")
    _build_db(path)
    monkeypatch.setattr(v2db, "DB_PATH", path)
    return path


def _add_material(project_id, mid, *, type_="document", has_structure=1, section_count=3,
                  structure_json='[{"title":"A"},{"title":"B"},{"title":"C"}]',
                  chunk_text="some extracted content"):
    with v2db.get_connection() as c:
        c.execute(
            """INSERT INTO v2_materials
                   (material_id,user_id,project_id,type,filename,extraction_status,
                    structure_json,has_structure,section_count,created_at)
               VALUES (?,?,?,?,?, 'done', ?, ?, ?, datetime('now'))""",
            (mid, "u1", project_id, type_, mid + ".md", structure_json, has_structure, section_count),
        )
        if chunk_text:
            c.execute(
                "INSERT INTO v2_material_chunks (chunk_id,user_id,material_id,project_id,chunk_index,chunk_text) VALUES (?,?,?,?,0,?)",
                (mid + "c", "u1", mid, project_id, chunk_text),
            )


_CANNED = {
    "learning_subject": "Data Structures & Algorithms",
    "persona": "CS Student",
    "goal": "Master DSA for the final exam",
    "industry_context": "Academic",
    "primary_focus": "Trees, graphs, and complexity analysis",
    "search_lens": "Educational",
    "intent_summary": "A CS student preparing for a DSA final.",
    "material_scope": "Covers weeks 1-12 of the course syllabus.",
    "coverage_mode": "material_bound",
    "coverage_reasoning": "One large structured syllabus drives the whole journey.",
}


def test_create_project_row_defaults(db):
    proj = P.create_project("u1", "My Project", "a description", "beginner")
    assert proj["intent_confirmed"] == 0
    assert proj["profile_status"] is None        # not generated yet
    assert proj["profile"] is None
    assert proj["difficulty"] == "beginner"
    # scoping: another user cannot read it
    assert P.get_project("someone_else", proj["project_id"]) is None


def test_profile_failure_is_visible_and_retryable_no_silent_fallback(db, monkeypatch, capsys):
    """Force the agent to fail on EVERY leg. The project must NOT get a fake
    'Learner' profile — it must land in a visible, retryable 'failed' state."""
    proj = P.create_project("u1", "Quantum Computing", "grad student", "advanced")
    _add_material(proj["project_id"], "m1")  # got far enough to have material

    def _boom(*a, **k):
        raise AllLegsFailed("agent profile: all legs failed (simulated)")
    monkeypatch.setattr(A, "call_agent", _boom)  # the name run_profile calls

    with pytest.raises(AllLegsFailed):
        P.generate_profile("u1", proj["project_id"])

    with v2db.get_connection() as c:
        row = dict(c.execute(
            "SELECT profile_status, profile_json, coverage_mode FROM v2_projects WHERE project_id=?",
            (proj["project_id"],)).fetchone())
    with capsys.disabled():
        print("\nFAILED-PROFILE row:", row)
    assert row["profile_status"] == "failed"          # visible failure state
    assert row["profile_json"] is None                # NO profile written
    assert row["coverage_mode"] is None               # nothing invented
    # and specifically NOT the legacy silent default
    assert row["profile_json"] is None or "Learner" not in (row["profile_json"] or "")


def test_generate_profile_persists_agent_output(db, monkeypatch, capsys):
    proj = P.create_project("u1", "DSA", "CS student, final exam prep", "intermediate")
    _add_material(proj["project_id"], "m1", has_structure=1, section_count=12)
    monkeypatch.setattr(A, "call_agent", lambda *a, **k: dict(_CANNED))

    out = P.generate_profile("u1", proj["project_id"])
    with capsys.disabled():
        print("\nPERSISTED profile_status:", out["profile_status"],
              "| coverage_mode:", out["coverage_mode"],
              "| persona:", out["profile"]["persona"])
    assert out["profile_status"] == "ready"
    assert out["coverage_mode"] == "material_bound"
    assert out["material_scope"] == _CANNED["material_scope"]
    assert out["coverage_reasoning"] == _CANNED["coverage_reasoning"]
    assert out["profile"]["persona"] == "CS Student"


def test_prompt_receives_queryable_structure_signals(db, monkeypatch):
    """Step 3: the agent must be fed has_structure/section_count per material, not
    left to re-derive structure from raw text."""
    proj = P.create_project("u1", "DSA", "exam prep", "intermediate")
    _add_material(proj["project_id"], "m1", has_structure=1, section_count=9,
                  structure_json='[{"title":"Trees"},{"title":"Graphs"}]')
    captured = {}

    def _capture(agent, messages, system="", **k):
        captured["prompt"] = messages[0]["content"]
        return dict(_CANNED)
    monkeypatch.setattr(A, "call_agent", _capture)

    P.generate_profile("u1", proj["project_id"])
    prompt = captured["prompt"]
    assert "has_structure=1" in prompt
    assert "section_count=9" in prompt
    assert "Trees" in prompt and "Graphs" in prompt   # section titles reached the prompt


def test_profile_fallback_leg_serves_through_routing(db, monkeypatch, capsys):
    """Deterministic (no network/keys): force the primary 'profile' leg to fail and
    prove provider.call_agent ROUTES to the fallback leg (nemotron/OpenRouter) and
    that leg's payload flows back through parse+validate into the saved profile.
    Complements the live integration variant, which is subject to nemotron upstream
    availability."""
    from backend.services.feed_v2.llm import provider
    primary_id = provider.MODEL_REGISTRY["gemini-3-flash-preview"][1]
    fallback_id = provider.MODEL_REGISTRY["nemotron-nano-30b"][1]
    served: list[str] = []

    monkeypatch.setattr(provider, "_keys_for_provider", lambda p: ["fake-key"])  # no real keys

    def fake_google(api_model_id, *a, **k):
        raise RuntimeError("simulated primary (gemini) outage")

    def fake_openrouter(api_model_id, messages, system, schema, key, images=None):
        served.append(api_model_id)
        return {"text": json.dumps(_CANNED), "in_tokens": 1, "out_tokens": 1,
                "latency_ms": 1, "model_used": api_model_id}

    monkeypatch.setitem(provider._SDK_FOR_PROVIDER, "google", fake_google)
    monkeypatch.setitem(provider._SDK_FOR_PROVIDER, "openrouter", fake_openrouter)
    monkeypatch.setattr(provider.call_logger, "write_call_row", lambda **k: None)

    proj = P.create_project("u1", "DSA", "final exam prep", "intermediate")
    _add_material(proj["project_id"], "m1", has_structure=1, section_count=12)
    out = P.generate_profile("u1", proj["project_id"])

    with capsys.disabled():
        print(f"\nfallback routing (offline): primary {primary_id} failed -> served {served}")
    assert served == [fallback_id]                    # fallback leg served through the routing table
    assert out["profile_status"] == "ready"
    assert out["profile"]["coverage_mode"] == "material_bound"


def test_set_coverage_mode_override(db, monkeypatch):
    proj = P.create_project("u1", "DSA", "exam prep", "intermediate")
    _add_material(proj["project_id"], "m1")
    monkeypatch.setattr(A, "call_agent", lambda *a, **k: dict(_CANNED, coverage_mode="material_anchored"))
    P.generate_profile("u1", proj["project_id"])

    updated = P.set_coverage_mode("u1", proj["project_id"], "material_bound", confirmed=True)
    assert updated["coverage_mode"] == "material_bound"   # user override won
    assert updated["intent_confirmed"] == 1

    with pytest.raises(ValueError):
        P.set_coverage_mode("u1", proj["project_id"], "nonsense")
