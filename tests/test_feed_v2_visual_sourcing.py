"""
Feed v2 visual_sourcing (Phase 12, Tasks 2/3) — three-tier sourcing:

  1. Real material_bound project with a real figure-containing document -> tier 1
     fires and picks the CORRECT real figure (by content, not just "first row").
  2. Real project with no document figures but real ranked web images -> tier 2
     fires correctly (via the beat's own citations).
  3. Real case with neither available -> tier 3 generates a valid, non-overflowing
     SVG from a real template.
  4. Real forced-broken-SVG case -> the validator catches it, regenerates once,
     then correctly falls back to tier 2.

Embeddings are a deterministic per-topic fake (same convention
tests/test_feed_v2_pdf_pages.py uses for chunk embeddings) — real extraction, real
DB, real cosine-similarity selection code, no network/API key needed. Tier-2/3
network+render boundaries (image fetch, headless validation) are real code; only
the LLM content-fill call is mocked where a test needs deterministic content.
"""
import io
import json
import sqlite3

import pytest
import sqlite_vec
from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from backend.database.schema import ALL_TABLES, MIGRATIONS
from backend.services.feed_v2 import db as v2db
from backend.services.feed_v2.schema import run_v2_migrations
from backend.services.feed_v2.ingestion import figures
from backend.services.feed_v2.agents import visual_sourcing as VS
from backend.services.feed_v2.agents import svg_templates as T
from backend.services.feed_v2.agents import visual_validator as V

_DIM = 3072
_TOPIC_BUCKET = {"PHOTOSYNTHESIS": 1, "QUICKSORT": 2, "FRENCH REVOLUTION": 3}


def _vec(bucket: int) -> list[float]:
    v = [0.0] * _DIM
    v[bucket % _DIM] = 1.0
    return v


def _fake_embed_by_topic(text: str) -> list[float]:
    up = text.upper()
    bucket = next((b for topic, b in _TOPIC_BUCKET.items() if topic in up), 0)
    return _vec(bucket)


def _pdf_with_figure(caption: str, color=(200, 30, 30)) -> bytes:
    img_buf = io.BytesIO()
    Image.new("RGB", (80, 60), color=color).save(img_buf, format="PNG")
    img_buf.seek(0)
    pdf_buf = io.BytesIO()
    c = canvas.Canvas(pdf_buf, pagesize=letter)
    c.drawString(72, 700, caption)
    c.drawImage(ImageReader(img_buf), 72, 550, width=80, height=60)
    c.showPage()
    c.save()
    return pdf_buf.getvalue()


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "visual.db")
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
    conn.execute("INSERT INTO v2_materials(material_id,user_id,project_id,type,filename,extraction_status) "
                "VALUES('mA','u1','proj','document','a.pdf','done')")
    conn.execute("INSERT INTO v2_materials(material_id,user_id,project_id,type,filename,extraction_status) "
                "VALUES('mB','u1','proj','document','b.pdf','done')")
    conn.commit(); conn.close()
    monkeypatch.setattr(v2db, "DB_PATH", path)
    return path


# ── 1. Tier 1: real figures, real cosine selection picks the RIGHT one ─────────
def test_tier1_picks_the_correct_real_figure(db, monkeypatch, capsys):
    monkeypatch.setattr(figures, "embed_query", _fake_embed_by_topic)
    monkeypatch.setattr(VS, "embed_query", _fake_embed_by_topic)

    figures.extract_figures("mA", "u1", "proj",
                            _pdf_with_figure("Figure 1: Photosynthesis light reactions"),
                            "a.pdf", ".pdf")
    figures.extract_figures("mB", "u1", "proj",
                            _pdf_with_figure("Figure 1: Quicksort partition step", color=(30, 30, 200)),
                            "b.pdf", ".pdf")

    spec = {"section_n": 1, "beat_index": 0, "visual_type": "process",
           "topic": "how quicksort partitions the array", "citations": []}
    asset = VS.source_tier1(spec, "proj")
    with capsys.disabled():
        print(f"\ntier1 match: {asset}")
    assert asset is not None and asset["tier"] == 1
    assert "Quicksort" in asset["caption"]     # picked the RIGHT figure, not just the first row


def test_tier1_returns_none_below_similarity_floor(db, monkeypatch):
    monkeypatch.setattr(figures, "embed_query", _fake_embed_by_topic)
    monkeypatch.setattr(VS, "embed_query", _fake_embed_by_topic)
    figures.extract_figures("mA", "u1", "proj",
                            _pdf_with_figure("Figure 1: Photosynthesis light reactions"), "a.pdf", ".pdf")

    spec = {"topic": "unrelated topic about roman aqueduct engineering", "citations": []}
    assert VS.source_tier1(spec, "proj") is None    # bucket 0 vs bucket 1 -> cosine 0.0, below floor


def test_tier1_same_domain_near_miss_falls_through(db, monkeypatch):
    """gemini-embedding-001 scores unrelated text ~0.49 and a same-domain WRONG figure
    0.55-0.62 (measured). A 0.6 cosine is a near-miss, not a match — must fall through."""
    monkeypatch.setattr(figures, "embed_query", _fake_embed_by_topic)
    figures.extract_figures("mA", "u1", "proj",
                            _pdf_with_figure("Figure 1: Photosynthesis light reactions"), "a.pdf", ".pdf")
    near = [0.0] * _DIM
    near[1], near[0] = 0.6, 0.8                          # cosine 0.6 against the bucket-1 caption
    monkeypatch.setattr(VS, "embed_query", lambda text: near)
    assert VS.source_tier1({"topic": "the Calvin cycle", "citations": []}, "proj") is None


def test_tier1_none_when_project_has_no_figures(db, monkeypatch):
    monkeypatch.setattr(VS, "embed_query", _fake_embed_by_topic)
    spec = {"topic": "anything", "citations": []}
    assert VS.source_tier1(spec, "proj") is None


# ── 2. Tier 2: real ranked web images, matched via the beat's own citations ────
def _png_bytes(w=400, h=300) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (10, 200, 10)).save(buf, format="PNG")
    return buf.getvalue()


def test_tier2_fires_via_beat_citations(monkeypatch, capsys):
    ranked_sources = [
        {"src": "web", "url": "https://a.com/1", "title": "A", "content": "x",
         "images": ["https://a.com/diagram.png"]},
        {"src": "corpus", "material_id": "m1", "text": "own material", "protected": True},
    ]
    monkeypatch.setattr(V, "fetch_web_image_bytes", lambda url: _png_bytes())

    spec = {"section_n": 1, "beat_index": 0, "visual_type": "comparison",
           "topic": "t", "citations": ["s1"]}   # s1 = first source by rank order
    asset = VS._try_tier2(spec, ranked_sources)
    with capsys.disabled():
        print(f"\ntier2 asset: {asset}")
    assert asset is not None and asset["tier"] == 2
    assert asset["url"] == "https://a.com/diagram.png"


def test_tier2_none_when_cited_source_has_no_images(monkeypatch):
    ranked_sources = [{"src": "web", "url": "https://a.com/1", "title": "A", "content": "x", "images": []}]
    spec = {"citations": ["s1"]}
    assert VS.source_tier2(spec, ranked_sources) is None


def test_tier2_rejects_candidate_that_fails_validation(monkeypatch, capsys):
    """A cited source's image is a real fetch but a tiny 10x10 tracking pixel — tier 2
    must reject it (real validate_sourced_image, real dimension check), not just accept
    whatever URL exists."""
    ranked_sources = [{"src": "web", "url": "https://a.com/1", "title": "A", "content": "x",
                       "images": ["https://a.com/pixel.png"]}]
    monkeypatch.setattr(V, "fetch_web_image_bytes", lambda url: _png_bytes(10, 10))
    spec = {"citations": ["s1"]}
    asset = VS._try_tier2(spec, ranked_sources)
    with capsys.disabled():
        print(f"\ntiny tracking pixel -> {asset}")
    assert asset is None


# ── 3. Tier 3: real generation from a real template, no other tier available ──
def test_tier3_generates_valid_non_overflowing_svg(monkeypatch, capsys):
    def fake_call(agent, messages, system="", schema=None, meta=None):
        return {"title": "Sorting steps", "steps": ["Pick pivot", "Partition", "Recurse"]}
    monkeypatch.setattr(VS, "call_agent", fake_call)

    spec = {"section_n": 1, "beat_index": 0, "visual_type": "process",
           "topic": "quicksort steps", "citations": []}
    asset = VS._try_tier3(spec, meta=None)
    with capsys.disabled():
        print(f"\ntier3 asset kind={asset and asset['kind']} validation={asset and asset['validation_reason']}")
    assert asset is not None and asset["tier"] == 3 and asset["kind"] == "generated_svg"
    assert "<svg" in asset["svg"]
    ok, reason = V.validate_generated_svg(asset["svg"])   # re-validate independently
    assert ok, reason


# ── 4. forced-broken-SVG: caught, regenerated once, then falls back to tier 2 ──
def test_broken_generation_regenerates_then_falls_back_to_tier2(monkeypatch, capsys):
    """tier 1/2 have nothing at first (so tier 3 gets tried); generation is FORCED
    broken both attempts; only THEN does a tier-2 candidate become available (the
    documented last-resort fallback) — proves the orchestration's exact call order:
    tier1 -> tier2 (empty) -> generate -> validate fail -> regenerate -> validate
    fail -> tier2 retry (now real) -> used."""
    broken_svg = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 400 200' width='400' height='200'>"
                 "<rect class='bg' x='0' y='0' width='400' height='200' fill='#fff'/>"
                 "<text x='9000' y='20' font-size='14'>off canvas</text></svg>")
    render_calls = []

    def always_broken_render(vtype, content):
        render_calls.append(vtype)
        return broken_svg
    monkeypatch.setattr(T, "render", always_broken_render)
    monkeypatch.setattr(VS, "call_agent", lambda *a, **k: {"title": "x", "steps": ["a"]})
    monkeypatch.setattr(VS, "_try_tier1", lambda spec, project_id: None)

    real_tier2_asset = {"tier": 2, "kind": "web_image", "url": "https://a.com/diagram.png",
                        "source_id": "s1", "source_url": "https://a.com/1", "validation_reason": "ok"}
    tier2_calls = []

    def fake_tier2(spec, ranked_sources):
        tier2_calls.append(1)
        return None if len(tier2_calls) == 1 else real_tier2_asset   # empty first, real on the fallback retry
    monkeypatch.setattr(VS, "_try_tier2", fake_tier2)

    spec = {"section_n": 1, "beat_index": 0, "visual_type": "process", "topic": "t", "citations": ["s1"]}
    out = VS.run_visual_sourcing(visual_specs=[spec], project_id="no-such-project", ranked_sources=[])
    asset = out["visual_assets"][0]
    with capsys.disabled():
        print(f"\nregen attempts: {len(render_calls)} | tier2 attempts: {len(tier2_calls)} | "
              f"final asset: tier={asset.get('tier')} validated={asset['validated']} kind={asset.get('kind')}")
    assert len(render_calls) == 2                 # generated, failed, regenerated once
    assert len(tier2_calls) == 2                  # tried empty first, retried as the fallback
    assert asset["validated"] is True
    assert asset["tier"] == 2                     # fell back to the real tier-2 image
    assert asset["url"] == "https://a.com/diagram.png"


def test_no_visual_available_when_every_tier_fails(monkeypatch, capsys):
    broken_svg = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' width='10' height='10'></svg>"
    monkeypatch.setattr(T, "render", lambda vtype, content: broken_svg)
    monkeypatch.setattr(VS, "call_agent", lambda *a, **k: {})
    # a broken-but-technically-empty SVG (no elements) would actually validate OK (no
    # out-of-bounds/overlap possible with zero elements) — force a real failure instead
    # by making validate_generated_svg itself report broken, so this test genuinely
    # exercises "no tier produced anything usable", not template quirks.
    monkeypatch.setattr(V, "validate_generated_svg", lambda svg: (False, "forced failure"))

    out = VS.run_visual_sourcing(visual_specs=[{"section_n": 1, "beat_index": 0, "visual_type": "process",
                                               "topic": "t", "citations": []}],
                                 project_id="no-such-project", ranked_sources=[])
    asset = out["visual_assets"][0]
    with capsys.disabled():
        print(f"\nno visual case -> {asset}")
    assert asset["validated"] is False
    assert asset["tier"] is None


# ── Phase 12b: headless render unavailable -> that beat is visual-less, run goes on ──
def test_render_unavailable_degrades_to_no_visual(monkeypatch, capsys):
    """REAL Chromium launch failure (browser path pointed at nothing). The beat gets no
    visual, tier 3 is not retried for later beats (no wasted fill calls), and the reason
    comes back as degraded_reason for the run record — never an exception."""
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/nonexistent-phase12b")
    fills = []
    monkeypatch.setattr(VS, "call_agent", lambda *a, **k: fills.append(1) or {"title": "x", "steps": ["a", "b"]})
    monkeypatch.setattr(VS, "_try_tier1", lambda spec, project_id: None)
    specs = [{"section_n": 1, "beat_index": i, "visual_type": "process", "topic": "t", "citations": []}
             for i in range(2)]
    out = VS.run_visual_sourcing(visual_specs=specs, project_id="p", ranked_sources=[])
    with capsys.disabled():
        print(f"\nassets={[{k: a[k] for k in ('tier', 'validated', 'reason')} for a in out['visual_assets']]}"
              f"\ndegraded_reason={out.get('degraded_reason')!r} fill_calls={len(fills)}")
    assert [a["validated"] for a in out["visual_assets"]] == [False, False]
    assert all("render unavailable" in a["reason"] for a in out["visual_assets"])
    assert len(fills) == 1                     # tier 3 skipped once the browser is known down
    assert "render unavailable" in out["degraded_reason"]


def test_real_validation_failure_is_not_reported_as_degraded(monkeypatch):
    """The degrade path must not absorb a genuine broken-SVG verdict: no degraded_reason,
    the plain 'no visual available' outcome of the tier chain."""
    monkeypatch.setattr(VS, "call_agent", lambda *a, **k: {"title": "x", "steps": ["a"]})
    monkeypatch.setattr(V, "validate_generated_svg", lambda svg: (False, "1 element(s) out of bounds"))
    out = VS.run_visual_sourcing(visual_specs=[{"section_n": 1, "beat_index": 0, "visual_type": "process",
                                               "topic": "t", "citations": []}],
                                 project_id="no-such-project", ranked_sources=[])
    assert "degraded_reason" not in out
    assert out["visual_assets"][0]["reason"] == "no visual available"


# ── Phase 12b: tier 2 skips logos/icons and SVG, tries the next candidate ─────
@pytest.mark.parametrize("url,skip", [
    # real image_links from the Phase 12 cost check (Wikipedia / GeeksforGeeks / MDN)
    ("https://en.wikipedia.org/static/images/icons/enwiki-25.svg", True),
    ("https://en.wikipedia.org/static/images/mobile/copyright/wikipedia-wordmark-en-25.svg", True),
    ("https://media.geeksforgeeks.org/gfg-gg-logo.svg", True),
    ("https://media.geeksforgeeks.org/auth-dashboard-uploads/Property=Light---Default.svg", True),
    ("https://mdn.github.io/shared-assets/images/diagrams/http/overview/http-layers.svg", True),
    ("https://example.com/assets/avatar_42.png", True),
    ("https://example.com/img/badge-new.png", True),
    ("https://example.com/favicon.ico", True),
    # real content images must survive the filter
    ("https://thumb.wikimedia.org/wikipedia/commons/thumb/5/55/Photosynthesis_en.svg/"
     "500px-Photosynthesis_en.svg.png?utm_source=en.wikipedia.org", False),
    ("https://media.geeksforgeeks.org/wp-content/uploads/20240925173636/quick-sort--images.webp", False),
    ("https://example.com/silicon-wafer.jpg", False),          # 'icon' inside a word is not a logo
])
def test_tier2_skip_filter_on_real_urls(url, skip):
    assert VS._skip_image_url(url) is skip


def test_tier2_skips_logo_and_svg_then_uses_next_real_image(monkeypatch):
    fetched = []
    monkeypatch.setattr(V, "fetch_web_image_bytes", lambda url: fetched.append(url) or _png_bytes())
    ranked = [{"src": "web", "url": "https://a.com/1", "title": "A", "content": "x",
               "images": ["https://a.com/logo.svg", "https://a.com/static/icons/x.png",
                          "https://a.com/diagram.svg", "https://a.com/figure-1.png"]}]
    asset = VS._try_tier2({"citations": ["s1"]}, ranked)
    assert fetched == ["https://a.com/figure-1.png"]       # logo/icon/SVG never fetched
    assert asset["url"] == "https://a.com/figure-1.png"


def test_tier2_moves_to_next_candidate_after_validation_reject(monkeypatch):
    sizes = {"https://a.com/shackle-20px.png": (20, 20), "https://a.com/content.png": (500, 380)}
    monkeypatch.setattr(V, "fetch_web_image_bytes", lambda url: _png_bytes(*sizes[url]))
    ranked = [{"src": "web", "url": "https://a.com/1", "title": "A", "content": "x",
               "images": list(sizes)}]
    asset = VS._try_tier2({"citations": ["s1"]}, ranked)
    assert asset["url"] == "https://a.com/content.png"


def test_tier2_fetch_attempts_are_capped(monkeypatch):
    fetched = []
    monkeypatch.setattr(V, "fetch_web_image_bytes", lambda url: fetched.append(url) or _png_bytes(10, 10))
    ranked = [{"src": "web", "url": "https://a.com/1", "title": "A", "content": "x",
               "images": [f"https://a.com/p{i}.png" for i in range(20)]}]
    assert VS._try_tier2({"citations": ["s1"]}, ranked) is None
    assert len(fetched) == VS.TIER2_MAX_FETCHES


def test_all_svg_source_falls_through_to_tier3(monkeypatch):
    """MDN's real image list is all SVG: tier 2 must skip every one WITHOUT fetching and
    the beat must land on tier 3 (a generated diagram), not 'no visual'."""
    fetched = []
    monkeypatch.setattr(V, "fetch_web_image_bytes", lambda url: fetched.append(url))
    monkeypatch.setattr(VS, "_try_tier1", lambda spec, project_id: None)
    monkeypatch.setattr(VS, "call_agent", lambda *a, **k: {"title": "HTTP", "steps": ["request", "response"]})
    monkeypatch.setattr(V, "validate_generated_svg", lambda svg: (True, "ok"))
    mdn = [f"https://mdn.github.io/shared-assets/images/diagrams/http/overview/{n}.svg"
           for n in ("fetching-a-page", "http-layers", "client-server-chain", "http-request", "http-response")]
    ranked = [{"src": "web", "url": "https://developer.mozilla.org/x", "title": "MDN", "content": "x", "images": mdn}]
    out = VS.run_visual_sourcing(visual_specs=[{"section_n": 1, "beat_index": 0, "visual_type": "process",
                                               "topic": "http", "citations": ["s1"]}],
                                 project_id="p", ranked_sources=ranked)
    assert fetched == []
    assert out["visual_assets"][0]["tier"] == 3


def test_web_image_fetch_sends_a_user_agent(monkeypatch):
    """Wikimedia 403s requests' default UA ('Please set a user-agent')."""
    seen = {}

    class _R:
        content = b"x"
        def raise_for_status(self): pass
    monkeypatch.setattr(V.requests, "get", lambda url, timeout=None, headers=None: seen.update(headers or {}) or _R())
    V.fetch_web_image_bytes("https://thumb.wikimedia.org/x.png")
    assert seen.get("User-Agent", "").startswith("Curivio/")
