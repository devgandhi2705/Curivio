"""
Feed v2 Phase 8b — page-level provenance for PDF chunking.

Real PDFs (built with reportlab) go through the REAL extraction + page-aware chunking
path; only the embedding call is mocked (page_no mapping is embedding-independent, so
these stay deterministic and keyless in the default suite). Proves:

  - a multi-page PDF's chunks each carry the ACTUAL source page number (verified by
    content -> page, not just "field is non-null");
  - the page number flows end-to-end into corpus_researcher with ZERO changes to that
    module (it already joins page_no from the DB row);
  - DOCX has pages=None and its chunks stay page_no=NULL (no false precision) — the
    image/link paths use the identical flat chunker, so they stay NULL too.
"""
import io
import json
import sqlite3

import pytest
import sqlite_vec

from docx import Document as DocxDocument
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from backend.database.schema import ALL_TABLES, MIGRATIONS
from backend.services.feed_v2 import db as v2db
from backend.services.feed_v2.schema import run_v2_migrations
from backend.services.feed_v2.ingestion import documents, chunking
from backend.services.feed_v2.agents import corpus_researcher as CR

_DIM = 3072  # v2_material_chunks_vec float[3072]


# ── real document builders ────────────────────────────────────────────────────
def _make_pdf(pages: list[list[str]]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    for lines in pages:
        y = 720
        for ln in lines:
            c.drawString(72, y, ln); y -= 16
        c.showPage()
    c.save()
    return buf.getvalue()


# Three pages, each one topic, each < 800 chars → exactly one chunk per page.
_PDF_PAGES = [
    ["PAGE ONE PHOTOSYNTHESIS.",
     "Photosynthesis is how green plants convert light energy into chemical energy",
     "stored as glucose. Chlorophyll in the chloroplasts absorbs sunlight, mainly in",
     "the blue and red bands, powering carbon dioxide and water into sugar and oxygen."],
    ["PAGE TWO FRENCH REVOLUTION.",
     "The French Revolution began in 1789 amid deep social and economic unrest. The",
     "storming of the Bastille on July 14 became its defining symbol. The monarchy",
     "was abolished and the Declaration of the Rights of Man was proclaimed widely."],
    ["PAGE THREE QUICKSORT.",
     "Quicksort is a divide and conquer sorting algorithm that selects a pivot and",
     "partitions the array around it. Average case time is O(n log n); the worst case",
     "is O(n squared) with poor pivots. It sorts in place with low memory overhead."],
]
_TOPIC_TO_PAGE = {"PHOTOSYNTHESIS": 1, "FRENCH REVOLUTION": 2, "QUICKSORT": 3}


def _make_docx(paras: list[str]) -> bytes:
    doc = DocxDocument()
    for p in paras:
        doc.add_paragraph(p)
    buf = io.BytesIO(); doc.save(buf)
    return buf.getvalue()


def _vec(bucket: int) -> list[float]:
    v = [0.0] * _DIM
    v[bucket % _DIM] = 1.0
    return v


def _fake_embed_texts_by_topic(texts):
    """Deterministic stand-in for ingestion.embeddings.embed_texts: one batch, a
    per-topic direction so a topic query retrieves that topic's chunk. page_no is set
    by the REAL chunker regardless of these vectors."""
    embs = []
    for t in texts:
        up = t.upper()
        bucket = next((p for topic, p in _TOPIC_TO_PAGE.items() if topic in up), 0)
        embs.append(_vec(bucket))
    yield 0, list(texts), embs


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "pdfpages.db")
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
    conn.execute("INSERT INTO v2_materials(material_id,user_id,project_id,type,filename,extraction_status) VALUES('mpdf','u1','proj','document','nn.pdf','done')")
    conn.execute("INSERT INTO v2_materials(material_id,user_id,project_id,type,filename,extraction_status) VALUES('mdoc','u1','proj','document','notes.docx','done')")
    conn.commit(); conn.close()
    monkeypatch.setattr(v2db, "DB_PATH", path)
    return path


# ── 1. extraction returns per-page structure ──────────────────────────────────
def test_extract_pdf_returns_pages_docx_does_not(capsys):
    pr = documents.extract(_make_pdf(_PDF_PAGES), "nn.pdf", ".pdf")
    assert pr.error is None and pr.page_count == 3
    assert pr.pages and [p["page_no"] for p in pr.pages] == [1, 2, 3]   # 1-based
    assert "PHOTOSYNTHESIS" in pr.pages[0]["text"] and "QUICKSORT" in pr.pages[2]["text"]

    dr = documents.extract(_make_docx(["A heading", "Some body text about turtles."]), "notes.docx", ".docx")
    with capsys.disabled():
        print(f"\nPDF pages: {[p['page_no'] for p in pr.pages]} | DOCX pages: {dr.pages}")
    assert dr.error is None
    assert dr.pages is None            # docx has no page concept → stays flat → NULL page_no


# ── 2. real chunking carries the ACTUAL page number per chunk ──────────────────
def test_pdf_chunks_carry_actual_page_numbers(db, monkeypatch, capsys):
    monkeypatch.setattr(chunking, "embed_texts", _fake_embed_texts_by_topic)
    pr = documents.extract(_make_pdf(_PDF_PAGES), "nn.pdf", ".pdf")
    stats = chunking.chunk_and_embed_pages("mpdf", "u1", "proj", pr.pages)

    with v2db.get_connection() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT chunk_index, page_no, chunk_text FROM v2_material_chunks WHERE material_id='mpdf' ORDER BY chunk_index").fetchall()]
    with capsys.disabled():
        print(f"\nchunk_and_embed_pages: {stats}")
        for r in rows:
            print(f"   page_no={r['page_no']}  text={r['chunk_text'][:38]!r}")
    assert stats["chunk_count"] == 3           # one chunk per page (each page < 800 chars)
    # verify page_no against the ACTUAL content, not just non-null
    checked = 0
    for r in rows:
        up = r["chunk_text"].upper()
        for topic, expected_page in _TOPIC_TO_PAGE.items():
            if topic in up:
                assert r["page_no"] == expected_page, f"{topic} should be page {expected_page}, got {r['page_no']}"
                checked += 1
    assert checked == 3                        # all three distinct pages verified


# ── 3. corpus_researcher picks up the real page_no with ZERO code changes ──────
def test_ingested_page_no_flows_into_corpus_researcher(db, monkeypatch, capsys):
    monkeypatch.setattr(chunking, "embed_texts", _fake_embed_texts_by_topic)
    pr = documents.extract(_make_pdf(_PDF_PAGES), "nn.pdf", ".pdf")
    chunking.chunk_and_embed_pages("mpdf", "u1", "proj", pr.pages)   # REAL ingestion → real page_no

    # retrieval + extraction mocked to deterministically target the quicksort (page 3) chunk
    monkeypatch.setattr(CR, "embed_query", lambda t: _vec(3))
    monkeypatch.setattr(CR, "call_agent", lambda agent, messages, system="", **k: {
        "passages": [{"index": 0, "quote": "", "why_relevant": "sorting"}]})   # top candidate = page 3

    out = CR.run_corpus_research(project_id="proj",
                                 journey_entry={"focus": "quicksort partitioning"},
                                 coverage_mode="material_bound")
    f = out["corpus_findings"][0]
    with capsys.disabled():
        print(f"\ncorpus finding: page_no={f['page_no']} material={f['material_id']} text={f['text'][:40]!r}")
    assert f["material_id"] == "mpdf"
    assert f["page_no"] == 3                    # REAL ingestion page, not seeded, not a figure row
    assert "QUICKSORT" in f["text"].upper()


# ── 4. docx / flat path stays page_no=NULL (image & link use this same path) ───
def test_docx_and_flat_path_stay_null(db, monkeypatch, capsys):
    monkeypatch.setattr(chunking, "embed_texts", lambda texts: iter([(0, list(texts), [_vec(0) for _ in texts])]))
    dr = documents.extract(_make_docx(["Turtles are reptiles.", "They live a long time."]), "notes.docx", ".docx")
    assert dr.pages is None
    chunking.chunk_and_embed("mdoc", "u1", "proj", dr.text)   # flat path (docx/image/link)

    with v2db.get_connection() as c:
        pages = [r["page_no"] for r in c.execute("SELECT page_no FROM v2_material_chunks WHERE material_id='mdoc'").fetchall()]
    with capsys.disabled():
        print(f"\ndocx chunk page_nos: {pages}")
    assert pages and all(p is None for p in pages)   # no false precision on a source with no pages
