"""
Feed v2 journey planner — live integration tests (real planner LLM call).

Skipped without a Gemini key and excluded from the default suite (integration).
Proves the parts that need a real model:
  - material_bound: day order tracks the document's structure_json order and
    day_count = the actual section count (the Phase-6 step-3 decision), against a
    really-ingested syllabus.
  - material_anchored: the plan visibly EXTENDS beyond the two seed blog links
    rather than rigidly mirroring them.
  - open: a sensible plan from the planner's own knowledge, no material.
  - rotating_theme is actually reachable ("stay current on AI research").
  - the journey_planner role's cross-provider fallback leg (nemotron primary ->
    gemini fallback) serves live.

coverage_mode is set directly here (Phase 5 already proved profile inference); this
file tests the PLANNER's per-mode behavior, so the plan generation is the real call.
"""
import io
import json
import os
import sqlite3

import pytest
import sqlite_vec

from backend.database.schema import ALL_TABLES, MIGRATIONS
from backend.services.feed_v2 import db as v2db
from backend.services.feed_v2.schema import run_v2_migrations
from backend.services.feed_v2.ingestion import materials, links
from backend.services.feed_v2 import projects as P
from backend.services.feed_v2 import journeys as J
from backend.services.feed_v2.llm import provider

_HAS_KEY = bool(os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY"))
pytestmark = [pytest.mark.integration,
              pytest.mark.skipif(not _HAS_KEY, reason="no Gemini API key")]


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
    path = str(tmp_path / "journey_live.db")
    _build_db(path)
    monkeypatch.setattr(v2db, "DB_PATH", path)
    monkeypatch.setattr(links, "_MOCK", True)
    return path


def _ready_project(coverage_mode, *, description, material_scope="",
                   learning_subject="Test Subject", goal="learn it",
                   search_lens="Educational", primary_focus="core concepts"):
    # The planner reads the PROFILE (as legacy did), not the raw description — so the
    # profile must carry whatever framing matters (e.g. "stay current" for rotating).
    proj = P.create_project("u1", learning_subject, description, "intermediate")
    profile = {"learning_subject": learning_subject, "persona": "Student", "goal": goal,
               "primary_focus": primary_focus, "search_lens": search_lens,
               "material_scope": material_scope, "coverage_mode": coverage_mode,
               "coverage_reasoning": "x"}
    with v2db.get_connection() as c:
        c.execute("UPDATE v2_projects SET profile_json=?, coverage_mode=?, material_scope=?, profile_status='ready' WHERE project_id=?",
                  (json.dumps(profile), coverage_mode, material_scope, proj["project_id"]))
    return proj["project_id"]


def _md_syllabus():
    topics = ["Arrays", "Linked Lists", "Stacks", "Queues", "Hash Tables", "Trees",
              "Heaps", "Graphs", "Sorting", "Dynamic Programming"]
    lines = ["# Data Structures Syllabus", "Fixed weekly schedule to the final exam.", ""]
    for i, t in enumerate(topics, 1):
        lines += [f"## Week {i}: {t}", f"Reading and exercises on {t}.", ""]
    return "\n".join(lines).encode()


def _structure_titles(pid):
    with v2db.get_connection() as c:
        rows = c.execute("SELECT structure_json FROM v2_materials WHERE project_id=? ORDER BY created_at", (pid,)).fetchall()
    out = []
    for r in rows:
        for s in json.loads(r["structure_json"] or "[]"):
            if s.get("title"):
                out.append(s["title"])
    return out


def test_material_bound_follows_document_order(db, capsys):
    pid = _ready_project("material_bound", description="following the course syllabus for the exam")
    materials.ingest("u1", pid, file_bytes=_md_syllabus(), filename="syllabus.md")
    titles = _structure_titles(pid)

    batch = J.plan_next_batch("u1", pid)
    day_sections = [d.get("source_section") for d in batch["days"]]
    with capsys.disabled():
        print(f"\nmaterial_bound: {len(titles)} sections -> day_count={batch['day_count']}")
        print(f"  document order: {titles}")
        print(f"  day order:      {day_sections}")
    assert batch["shape"] == "fixed_sequence"
    assert batch["day_count"] == len(titles)          # UNCLAMPED = actual section count
    assert day_sections == titles                     # day order tracks structure_json order


def test_material_anchored_extends_beyond_material(db, capsys):
    pid = _ready_project("material_anchored",
                         description="just getting into async rust, want to learn the basics",
                         material_scope="basic async syntax from two intro blog posts")
    materials.ingest("u1", pid, url="https://blog.example.com/async-1")
    materials.ingest("u1", pid, url="https://blog.example.com/async-2")

    batch = J.plan_next_batch("u1", pid)
    foci = [d.get("focus") for d in batch.get("days", [])]
    with capsys.disabled():
        print(f"\nmaterial_anchored: 2 seed blogs -> shape={batch['shape']} day_count={batch['day_count']}")
        print(f"  day foci: {foci}")
    # Not rigidly bound to the 2 seed items: the plan spans far more days than the
    # material alone, in the planner's clamped [7,20] choosing range.
    assert 7 <= batch["day_count"] <= 20             # >> the 2 seed blogs -> expanded
    if batch["shape"] == "fixed_sequence":
        assert len(batch.get("days", [])) > 2        # more day entries than the 2 blog posts


def test_open_mode_sensible_plan(db, capsys):
    pid = _ready_project("open", description="learn linear algebra from scratch")
    batch = J.plan_next_batch("u1", pid)
    with capsys.disabled():
        print(f"\nopen: shape={batch['shape']} day_count={batch['day_count']}")
    assert 7 <= batch["day_count"] <= 20
    body = batch.get("days") or batch.get("themes")
    assert body                                        # a real plan, not an empty shell


def test_rotating_theme_is_reachable(db, capsys):
    # A genuinely open-ended, "stay current" project — the profile carries that
    # framing (as Phase 5 would produce), which is what the planner actually reads.
    pid = _ready_project("open", description="stay current on AI research",
                         learning_subject="AI research", goal="stay current on AI research",
                         search_lens="Investigative", primary_focus="frontier AI developments")
    batch = J.plan_next_batch("u1", pid)
    with capsys.disabled():
        print(f"\nrotating test: shape={batch['shape']}  themes={[t.get('name') for t in batch.get('themes', [])]}")
    # Legacy's audit found rotating_theme was never exercised. An explicitly
    # open-ended "stay current" framing reaches it (diagnosed 3/3 on both legs). If
    # this ever lands on fixed_sequence, that's a reportable finding, not a rig.
    assert batch["shape"] == "rotating_theme", f"expected rotating_theme, got {batch['shape']}"


def test_journey_fallback_leg_serves(db, monkeypatch, capsys):
    """Force the primary journey_planner leg (nemotron/OpenRouter) to fail; confirm
    the gemini fallback serves a real plan."""
    primary_id = provider.MODEL_REGISTRY["nemotron-nano-30b"][1]
    fallback_id = provider.MODEL_REGISTRY["gemini-3-flash-preview"][1]
    real_google = provider._call_google
    served = []

    def fake_openrouter(api_model_id, *a, **k):
        raise RuntimeError("simulated primary (nemotron) outage")

    def rec_google(api_model_id, messages, system, schema, key, images=None):
        served.append(api_model_id)
        return real_google(api_model_id, messages, system, schema, key, images)

    monkeypatch.setitem(provider._SDK_FOR_PROVIDER, "openrouter", fake_openrouter)
    monkeypatch.setitem(provider._SDK_FOR_PROVIDER, "google", rec_google)

    pid = _ready_project("open", description="learn graph theory")
    batch = J.plan_next_batch("u1", pid)
    with capsys.disabled():
        print(f"\njourney routing: primary {primary_id} failed -> served {served}")
    assert served and all(s == fallback_id for s in served), served
    assert primary_id not in served
    assert batch["day_count"] >= 1 and (batch.get("days") or batch.get("themes"))
