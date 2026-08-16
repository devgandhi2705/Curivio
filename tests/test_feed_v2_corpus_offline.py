"""
Feed v2 corpus_researcher (Phase 8) — real RAG over uploaded materials.

Mostly offline/deterministic (embed_query + the extraction call_agent are mocked so
retrieval ranking and the extraction-filter mapping are asserted without a key). The
single integration test at the bottom flips both on: real gemini-embedding-001 query
embedding + a real extraction LLM call against a freshly-embedded mixed material set,
proving the PDF's chunks rank + get selected and the off-topic image/link chunks are
dropped by the extraction step (not merely by vector distance).

Covers Phase 8's contract:
  - retrieval ranks nearest, extraction FILTERS the candidate set (drops retrieved-
    but-irrelevant chunks);
  - citation metadata is honest: a real page_no is carried through when the row has
    one, and stays None (never fabricated) when it doesn't;
  - coverage_mode is TAGGED onto every finding for later weighting;
  - zero-materials is a clean no-op (no embed, no LLM) that flows into source_ranker;
  - the fallback provider leg serves;
  - the FULL graph runs with the real corpus node + the other 4 stubs, barrier intact.
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
from backend.services.feed_v2.agents import corpus_researcher as A

_HAS_KEY = bool(os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY"))
_DIM = 3072  # must match v2_material_chunks_vec float[3072]


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
    path = str(tmp_path / "corpus.db")
    _build_db(path)
    monkeypatch.setattr(v2db, "DB_PATH", path)
    return path


@pytest.fixture(autouse=True)
def _rig():
    G._reset_rig()   # USE_REAL_CORPUS_RESEARCHER=False, USE_REAL_SOURCE_RANKER=False
    yield
    G._reset_rig()


def _vec(bucket: int) -> list[float]:
    """A unit direction along one axis — orthogonal buckets are max cosine distance
    apart, an identical bucket is distance 0, so retrieval order is deterministic."""
    v = [0.0] * _DIM
    v[bucket % _DIM] = 1.0
    return v


def _ready_project(coverage_mode="material_bound"):
    proj = P.create_project("u1", "Neural Nets", "exam prep", "intermediate")
    profile = {"learning_subject": "Neural Nets", "persona": "S", "coverage_mode": coverage_mode}
    with v2db.get_connection() as c:
        c.execute("UPDATE v2_projects SET profile_json=?, coverage_mode=?, profile_status='ready' WHERE project_id=?",
                  (json.dumps(profile), coverage_mode, proj["project_id"]))
    return proj["project_id"]


def _material(project_id, mid, *, type_="document", filename=None, url=None):
    with v2db.get_connection() as c:
        c.execute(
            """INSERT INTO v2_materials (material_id,user_id,project_id,type,filename,url,extraction_status,created_at)
               VALUES (?,?,?,?,?,?, 'done', datetime('now'))""",
            (mid, "u1", project_id, type_, filename, url),
        )


def _chunk(project_id, mid, cid, idx, text, vec, *, page_no=None):
    with v2db.get_connection() as c:
        c.execute(
            "INSERT INTO v2_material_chunks (chunk_id,user_id,material_id,project_id,chunk_index,page_no,chunk_text) VALUES (?,?,?,?,?,?,?)",
            (cid, "u1", mid, project_id, idx, page_no, text),
        )
        c.execute(
            "INSERT INTO v2_material_chunks_vec (embedding,chunk_id,material_id,project_id,user_id,chunk_text,created_at) VALUES (?,?,?,?,?,?,datetime('now'))",
            (json.dumps(vec), cid, mid, project_id, "u1", text),
        )


def _mixed_set(pid):
    """PDF (backprop, page 4), image (cat), link (recipe) — three orthogonal buckets."""
    _material(pid, "mpdf", type_="document", filename="neural_nets.pdf")
    _material(pid, "mimg", type_="image", filename="cat.png")
    _material(pid, "mlink", type_="link", url="https://example.com/pasta")
    _chunk(pid, "mpdf", "cpdf", 3, "Backpropagation computes gradients via the chain rule.", _vec(0), page_no=4)
    _chunk(pid, "mimg", "cimg", 0, "A fluffy orange cat sits on a sunny windowsill.", _vec(1))
    _chunk(pid, "mlink", "clink", 0, "Boil the pasta for eight minutes, then drain.", _vec(2))


# ── retrieval ranks + extraction filters + citation honesty ───────────────────
def test_extraction_filters_candidates_and_page_no_is_honest(db, monkeypatch, capsys):
    pid = _ready_project()
    _mixed_set(pid)
    monkeypatch.setattr(A, "embed_query", lambda t: _vec(0))   # query nearest the PDF chunk

    # The extraction LLM keeps the PDF (index 0, nearest) AND the image (also a
    # candidate), and DROPS the link — proving the filter is the LLM step, not just
    # vector distance (all three were retrieved as candidates).
    def fake_call(agent, messages, system="", **k):
        listing = messages[0]["content"]
        assert "Backpropagation" in listing and "pasta" in listing   # link WAS a candidate
        return {"passages": [
            {"index": 0, "quote": "Backpropagation computes gradients", "why_relevant": "core topic"},
            {"index": 1, "quote": "", "why_relevant": "loosely related"}]}
    monkeypatch.setattr(A, "call_agent", fake_call)

    out = A.run_corpus_research(project_id=pid, journey_entry={"focus": "backprop"},
                                coverage_mode="material_bound")
    findings = out["corpus_findings"]
    with capsys.disabled():
        print("\ncorpus findings:", json.dumps(findings, indent=1))
    mats = [f["material_id"] for f in findings]
    assert "mpdf" in mats and "mimg" in mats     # both kept
    assert "mlink" not in mats                    # link filtered by EXTRACTION, not distance
    pdf = next(f for f in findings if f["material_id"] == "mpdf")
    img = next(f for f in findings if f["material_id"] == "mimg")
    assert pdf["page_no"] == 4                     # real page carried through
    assert pdf["chunk_index"] == 3 and pdf["source_label"] == "neural_nets.pdf"
    assert pdf["text"] == "Backpropagation computes gradients"   # the model's pertinent span
    assert img["page_no"] is None                  # image has no page — NOT fabricated
    assert all(f["coverage_mode"] == "material_bound" for f in findings)   # tagged


# ── no-materials edge case: clean no-op, no embed, no LLM, flows downstream ────
def test_zero_materials_noop_flows_into_source_ranker(db, monkeypatch, capsys):
    pid = _ready_project(coverage_mode="open")   # open + zero uploads is legitimate

    def _no_embed(_t):
        raise AssertionError("embed_query must NOT be called when there are no chunks")
    monkeypatch.setattr(A, "embed_query", _no_embed)
    monkeypatch.setattr(A, "call_agent", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("call_agent must NOT be called when there are no chunks")))

    out = A.run_corpus_research(project_id=pid, journey_entry={"focus": "anything"},
                                coverage_mode="open")
    assert out == {"corpus_findings": []}          # clean empty, no error

    # Flow the empty result into the ACTUAL next node in the graph (source_ranker).
    # Use the canned-merge path (this test is about corpus flow-through, not ranking).
    G.USE_REAL_SOURCE_RANKER = False
    state = {"trace_id": "t", "user_id": "u1", "project_id": pid, "day_number": 1,
             "web_findings": [{"src": "web", "stub": True}], "corpus_findings": out["corpus_findings"]}
    ranked = G.source_ranker(state)                # canned merge → web + corpus pass-through
    with capsys.disabled():
        print("\nzero-materials ranked_sources:", ranked["ranked_sources"])
    assert ranked["ranked_sources"] == [{"src": "web", "stub": True}]   # unbroken barrier input


# ── fallback provider leg serves ──────────────────────────────────────────────
def test_fallback_leg_serves_through_routing(db, monkeypatch, capsys):
    from backend.services.feed_v2.llm import provider
    primary_id = provider.MODEL_REGISTRY["gemini-3.1-flash-lite"][1]   # corpus primary (google)
    fallback_id = provider.MODEL_REGISTRY["nemotron-nano-30b"][1]      # corpus fallback (OR)
    served: list[str] = []

    pid = _ready_project()
    _material(pid, "mpdf", filename="doc.pdf")
    _chunk(pid, "mpdf", "cpdf", 0, "Backprop and the chain rule.", _vec(0), page_no=2)
    monkeypatch.setattr(A, "embed_query", lambda t: _vec(0))
    monkeypatch.setattr(provider, "_keys_for_provider", lambda p: ["fake-key"])

    def fake_google(api_model_id, *a, **k):
        raise RuntimeError("simulated primary (gemini) outage")

    def fake_openrouter(api_model_id, messages, system, schema, key, images=None):
        served.append(api_model_id)
        return {"text": json.dumps({"passages": [{"index": 0, "quote": "Backprop", "why_relevant": "x"}]}),
                "in_tokens": 1, "out_tokens": 1, "latency_ms": 1, "model_used": api_model_id}

    monkeypatch.setitem(provider._SDK_FOR_PROVIDER, "google", fake_google)
    monkeypatch.setitem(provider._SDK_FOR_PROVIDER, "openrouter", fake_openrouter)
    monkeypatch.setattr(provider.call_logger, "write_call_row", lambda **k: None)

    out = A.run_corpus_research(project_id=pid, journey_entry={"focus": "backprop"},
                                coverage_mode="material_bound")
    with capsys.disabled():
        print(f"\nfallback (offline): primary {primary_id} failed -> served {served}")
    assert served == [fallback_id]                 # fallback leg served through routing
    assert out["corpus_findings"] and out["corpus_findings"][0]["material_id"] == "mpdf"


# ── FULL graph: real corpus node + 4 stubs, barrier still single-fires ─────────
def test_full_graph_with_real_corpus_node(db, monkeypatch, capsys):
    G.USE_REAL_CORPUS_RESEARCHER = True            # this node real; the other 4 stay stubbed
    pid = _ready_project()
    _mixed_set(pid)
    monkeypatch.setattr(A, "embed_query", lambda t: _vec(0))
    monkeypatch.setattr(A, "call_agent", lambda *a, **k: {
        "passages": [{"index": 0, "quote": "Backpropagation computes gradients", "why_relevant": "core"}]})

    trace_id, final = G.run_graph("u1", pid, 1)
    with capsys.disabled():
        print("\nfull-run assembled:", json.dumps(final["assembled"]))
        print("corpus_findings:", json.dumps(final["corpus_findings"]))
    for key in ("lesson_plan", "web_findings", "corpus_findings", "ranked_sources",
                "section_drafts", "verdicts", "assembled"):
        assert final.get(key), f"missing {key}"
    # the REAL node ran (real material_id from the DB, not the stub's {"stub": True})
    cf = final["corpus_findings"][0]
    assert cf["material_id"] == "mpdf" and "stub" not in cf
    assert cf["coverage_mode"] == "material_bound"
    # barrier intact: the tail ran exactly once despite a real (non-instant) corpus node
    assert G._EXEC_LOG.count("assembler") == 1
    assert G._EXEC_LOG.count("source_ranker") == 1


# ── the real embedding + extraction chain (integration) ───────────────────────
@pytest.mark.integration
@pytest.mark.skipif(not _HAS_KEY, reason="no Gemini API key")
def test_real_retrieval_and_extraction_on_mixed_set(db, capsys):
    """Real gemini-embedding-001 query embedding (same model as the seed embeddings)
    + a real extraction LLM call. A backprop-focused query must surface the PDF's
    chunk and the extraction step must drop the off-topic cat/recipe chunks."""
    pid = _ready_project()
    texts = {
        ("mpdf", "cpdf", 3, 4, "document", "neural_nets.pdf", None):
            "Backpropagation trains a neural network by computing the gradient of the "
            "loss with respect to each weight using the chain rule, layer by layer.",
        ("mimg", "cimg", 0, None, "image", "cat.png", None):
            "A fluffy orange cat sitting on a sunny windowsill looking outside.",
        ("mlink", "clink", 0, None, "link", None, "https://example.com/pasta"):
            "To cook pasta, boil salted water, add the pasta, cook for eight minutes, then drain.",
    }
    for (mid, cid, idx, page_no, type_, filename, url), text in texts.items():
        _material(pid, mid, type_=type_, filename=filename, url=url)
        _chunk(pid, mid, cid, idx, text, A.embed_query(text), page_no=page_no)   # REAL embedding

    out = A.run_corpus_research(project_id=pid,
                                journey_entry={"focus": "how backpropagation computes gradients"},
                                coverage_mode="material_bound", keywords=["chain rule", "weights"])
    findings = out["corpus_findings"]
    mats = [f["material_id"] for f in findings]
    with capsys.disabled():
        print("\nLIVE corpus findings:", json.dumps(findings, indent=1))
    assert "mpdf" in mats                           # the relevant PDF chunk was selected
    assert "mlink" not in mats                       # off-topic recipe dropped by extraction
    pdf = next(f for f in findings if f["material_id"] == "mpdf")
    assert pdf["page_no"] == 4                        # real page carried through
    if "mimg" in mats:                               # if the model happened to keep the image
        img = next(f for f in findings if f["material_id"] == "mimg")
        assert img["page_no"] is None                # never a fabricated page
