"""
Feed v2 visual_validator (Phase 12, Task 4).

Sourced path: real image bytes checked for real dimensions/aspect ratio (tiny =
icon/tracking pixel, extreme aspect = banner strip). Generated path: rendered
HEADLESS (Playwright/Chromium) and checked programmatically for out-of-bounds
elements and overlapping boxes — the forced-broken-SVG case the phase plan asks for.
"""
import io

import pytest
from PIL import Image

from backend.services.feed_v2.agents import svg_templates as T
from backend.services.feed_v2.agents import visual_validator as V


def _png_bytes(w: int, h: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (120, 40, 40)).save(buf, format="PNG")
    return buf.getvalue()


# ── sourced image path ─────────────────────────────────────────────────────────
def test_tiny_image_rejected_as_tracking_pixel(capsys):
    ok, reason = V.validate_sourced_image(_png_bytes(20, 20))
    with capsys.disabled():
        print(f"\n20x20: ok={ok} ({reason})")
    assert not ok and "small" in reason


def test_extreme_aspect_ratio_rejected_as_banner(capsys):
    ok, reason = V.validate_sourced_image(_png_bytes(900, 100))   # both dims clear the min-size floor
    with capsys.disabled():
        print(f"\n900x100: ok={ok} ({reason})")
    assert not ok and "aspect" in reason


def test_real_figure_dimensions_pass(capsys):
    ok, reason = V.validate_sourced_image(_png_bytes(500, 380))
    with capsys.disabled():
        print(f"\n500x380: ok={ok} ({reason})")
    assert ok


def test_unreadable_bytes_rejected():
    ok, reason = V.validate_sourced_image(b"not an image")
    assert not ok and "unreadable" in reason


def test_web_image_fetch_failure_is_non_fatal(monkeypatch):
    def boom(url, timeout=None):
        raise ConnectionError("dns failure")
    monkeypatch.setattr(V.requests, "get", boom)
    assert V.fetch_web_image_bytes("https://bad.example/x.png") is None


# ── generated SVG path (headless render) ────────────────────────────────────────
def _has_chromium() -> bool:
    try:
        V._browser()
        return True
    except Exception:
        return False


pytestmark_browser = pytest.mark.skipif(not _has_chromium(), reason="no headless Chromium available")


@pytestmark_browser
def test_real_template_renders_clean(capsys):
    svg = T.render("comparison", {"title": "T", "left_label": "A", "right_label": "B",
                                  "left_points": ["x", "y"], "right_points": ["z"]})
    ok, reason = V.validate_generated_svg(svg)
    with capsys.disabled():
        print(f"\ncomparison template: ok={ok} ({reason})")
    assert ok


@pytestmark_browser
def test_all_six_templates_render_clean(capsys):
    samples = {
        "timeline": {"title": "H", "events": [{"label": f"E{i}", "date": "2020"} for i in range(6)]},
        "comparison": {"title": "C", "left_label": "A", "right_label": "B",
                       "left_points": ["p1", "p2"], "right_points": ["q1"]},
        "process": {"title": "P", "steps": ["s1", "s2", "s3", "s4"]},
        "hierarchy": {"title": "Hi", "root": "Root", "children": ["c1", "c2", "c3"]},
        "before_after": {"title": "BA", "before_label": "Before", "after_label": "After",
                         "before_points": ["b1"], "after_points": ["a1", "a2"]},
        "labelled_parts": {"title": "LP", "parts": [{"label": "L1", "description": "d1"},
                                                    {"label": "L2", "description": "d2"}]},
    }
    results = {}
    for vtype, content in samples.items():
        svg = T.render(vtype, content)
        ok, reason = V.validate_generated_svg(svg)
        results[vtype] = (ok, reason)
    with capsys.disabled():
        for vtype, (ok, reason) in results.items():
            print(f"\n{vtype}: ok={ok} ({reason})")
    assert all(ok for ok, _ in results.values())


@pytestmark_browser
def test_forced_broken_svg_is_caught(capsys):
    """A deliberately broken SVG (text pushed off-canvas + two overlapping rects) —
    the exact case the phase plan asks the validator to catch."""
    broken = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 400 200' width='400' height='200'>"
             "<rect class='bg' x='0' y='0' width='400' height='200' fill='#fff'/>"
             "<rect x='10' y='10' width='100' height='60' fill='#eee' stroke='#333'/>"
             "<rect x='50' y='30' width='100' height='60' fill='#eee' stroke='#333'/>"
             "<text x='5000' y='20' font-size='14'>way off canvas</text>"
             "</svg>")
    ok, reason = V.validate_generated_svg(broken)
    with capsys.disabled():
        print(f"\nforced-broken SVG: ok={ok} ({reason})")
    assert not ok
    assert "out of bounds" in reason
    assert "overlapping" in reason


@pytestmark_browser
def test_background_rect_itself_is_not_a_false_positive(capsys):
    """The template's own full-canvas background rect must never trip the overlap
    check just by existing under every other box."""
    svg = T.render("process", {"title": "T", "steps": ["one", "two"]})
    ok, reason = V.validate_generated_svg(svg)
    with capsys.disabled():
        print(f"\nbackground-only sanity: ok={ok} ({reason})")
    assert ok
