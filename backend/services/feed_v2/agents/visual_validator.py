"""
Feed v2 visual validator (Phase 12, Task 4).

TWO paths:
  - Sourced (tier 1/2): real image bytes, checked for real dimensions/aspect ratio to
    reject an obvious logo/ad/tracking pixel. NOT a full vision judgment (image_ingestor
    elsewhere already owns vision+OCR; re-running that per candidate image would be a
    second LLM call per beat for a cheap mechanical check this handles directly).
  - Generated (tier 3): rendered HEADLESS (Playwright/Chromium — pinned in
    requiremnts.txt, browser + system libs installed by the Dockerfile since Phase 12b)
    and checked programmatically for out-of-bounds elements and overlapping boxes. If
    the browser can't start, RenderUnavailable is raised and the caller degrades.

No headless SVG rendering wrapper existed before this phase (confirmed absent
repo-wide); this module is that wrapper.

Isolation: feed_v2's own modules + stdlib/third-party only. Never
backend.services.* / backend.llm.*.
"""
from __future__ import annotations

import io
import logging
from contextlib import contextmanager

import requests

logger = logging.getLogger(__name__)

_MIN_DIM_PX = 80          # below this on either side: almost certainly an icon/tracking pixel
_MAX_ASPECT_RATIO = 6.0   # a real figure isn't a 1x1000 banner strip
_FETCH_TIMEOUT_S = 15
# Wikimedia 403s requests' default UA ("Please set a user-agent"). Contact = the public Space.
_FETCH_HEADERS = {"User-Agent": "Curivio/1.0 (+https://huggingface.co/spaces/Devg-01/Curivio)"}

_BOUNDS_TOLERANCE_PX = 1.0   # sub-pixel rounding slack in the out-of-bounds check


class RenderUnavailable(Exception):
    """The headless browser can't START (playwright not installed, browser binary or
    shared libs missing). An ENVIRONMENT failure, not a verdict on the SVG — raised only
    from import/launch, never from rendering or checking, so a broken SVG still comes
    back as (False, reason)."""


def _launch_error_line(exc: Exception) -> str:
    """Playwright's launch error is a multi-KB launch log; keep the line that names the
    cause (e.g. '... libglib-2.0.so.0: cannot open shared object file')."""
    lines = [ln.strip() for ln in str(exc).splitlines() if ln.strip()] or [type(exc).__name__]
    return next((ln for ln in lines if "[err]" in ln or "doesn't exist" in ln), lines[0])[:300]


@contextmanager
def _browser():
    """A fresh headless Chromium per use. NOT a process-wide singleton: sync Playwright
    objects are bound to the thread that created them, and FastAPI iterates the feed
    stream on threadpool workers — a cached browser raised 'cannot switch to a
    different thread' on the next run.
    ponytail: launch per validation; a per-thread cache only if launch cost shows up."""
    try:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
    except Exception as exc:  # noqa: BLE001 — any failure to start is environmental
        raise RenderUnavailable(f"playwright unavailable: {_launch_error_line(exc)}") from exc
    try:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            raise RenderUnavailable(f"chromium launch failed: {_launch_error_line(exc)}") from exc
        try:
            yield browser      # render/check errors propagate as-is — NOT RenderUnavailable
        finally:
            browser.close()
    finally:
        pw.stop()


# ── sourced image path (tier 1 / tier 2) ──────────────────────────────────────
def validate_sourced_image(image_bytes: bytes) -> tuple[bool, str]:
    """Real dimension/aspect-ratio check on real fetched bytes. Returns (ok, reason)."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size
    except Exception as exc:
        return False, f"unreadable image: {exc}"
    if w < _MIN_DIM_PX or h < _MIN_DIM_PX:
        return False, f"too small ({w}x{h}) - likely an icon/tracking pixel"
    ratio = max(w, h) / max(min(w, h), 1)
    if ratio > _MAX_ASPECT_RATIO:
        return False, f"extreme aspect ratio ({w}x{h}) - likely a banner strip, not a figure"
    return True, f"ok ({w}x{h})"


def fetch_web_image_bytes(url: str) -> bytes | None:
    """Best-effort real fetch of a tier-2 web image URL. Non-fatal: a fetch failure is
    logged and treated as an unvalidatable candidate (caller moves on), same pattern
    web_researcher._fetch uses for a failed page fetch."""
    try:
        resp = requests.get(url, timeout=_FETCH_TIMEOUT_S, headers=_FETCH_HEADERS)
        resp.raise_for_status()
        return resp.content
    except Exception as exc:
        logger.info("[feed_v2.visual] web image fetch failed for %s: %s", url, exc)
        return None


# ── generated SVG path (tier 3) — headless render + programmatic check ────────
_CHECK_JS = """
() => {
    const svg = document.querySelector('svg');
    const vb = svg.viewBox.baseVal;
    const bounds = {x: vb.x, y: vb.y, w: vb.width, h: vb.height};
    // the template's own full-canvas background rect (class='bg') is EXPECTED to
    // cover everything — excluded from both checks, not a real element to validate.
    const els = Array.from(svg.querySelectorAll('text, rect, circle, polygon'))
        .filter(el => !el.classList.contains('bg'));
    const boxes = els.map(el => {
        const b = el.getBBox();
        return {tag: el.tagName.toLowerCase(), x: b.x, y: b.y, w: b.width, h: b.height};
    });
    const out_of_bounds = boxes.filter(b =>
        b.x < bounds.x - %(tol)f || b.y < bounds.y - %(tol)f ||
        b.x + b.w > bounds.x + bounds.w + %(tol)f || b.y + b.h > bounds.y + bounds.h + %(tol)f);
    const rects = boxes.filter(b => b.tag === 'rect');
    const overlaps = [];
    for (let i = 0; i < rects.length; i++) {
        for (let j = i + 1; j < rects.length; j++) {
            const a = rects[i], c = rects[j];
            if (a.x < c.x + c.w && a.x + a.w > c.x && a.y < c.y + c.h && a.y + a.h > c.y) {
                overlaps.push([i, j]);
            }
        }
    }
    return {out_of_bounds: out_of_bounds.length, overlaps: overlaps.length, element_count: boxes.length};
}
""" % {"tol": _BOUNDS_TOLERANCE_PX}


def validate_generated_svg(svg_markup: str) -> tuple[bool, str]:
    """Render svg_markup headless, check for out-of-bounds elements and overlapping
    boxes. Returns (ok, reason)."""
    with _browser() as browser:
        page = browser.new_page()
        page.set_content(f"<!DOCTYPE html><html><body style='margin:0'>{svg_markup}</body></html>")
        result = page.evaluate(_CHECK_JS)
    problems = []
    if result["out_of_bounds"]:
        problems.append(f"{result['out_of_bounds']} element(s) out of bounds")
    if result["overlaps"]:
        problems.append(f"{result['overlaps']} overlapping box pair(s)")
    if problems:
        return False, "; ".join(problems)
    return True, f"ok ({result['element_count']} elements checked)"


def _demo() -> None:
    """ponytail self-check: a real template renders clean; a deliberately broken SVG
    (text pushed off-canvas, two overlapping rects) is caught. Needs a real headless
    Chromium — skips with a clear message if Playwright's browser isn't installed."""
    from . import svg_templates

    try:
        with _browser():
            pass
    except Exception as exc:
        print(f"visual_validator._demo SKIPPED (no headless browser available: {exc})")
        return

    good = svg_templates.render("process", {"title": "T", "steps": ["one", "two", "three"]})
    ok, reason = validate_generated_svg(good)
    print(f"real template: ok={ok} ({reason})")
    assert ok

    broken = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 400 200' width='400' height='200'>"
             "<rect x='10' y='10' width='100' height='60' fill='#eee' stroke='#333'/>"
             "<rect x='50' y='30' width='100' height='60' fill='#eee' stroke='#333'/>"   # overlaps the above
             "<text x='5000' y='20' font-size='14'>way off canvas</text>"                # out of bounds
             "</svg>")
    ok, reason = validate_generated_svg(broken)
    print(f"broken SVG: ok={ok} ({reason})")
    assert not ok and "out of bounds" in reason and "overlapping" in reason

    from PIL import Image

    small = io.BytesIO()
    Image.new("RGB", (20, 20), (255, 0, 0)).save(small, format="PNG")
    ok, reason = validate_sourced_image(small.getvalue())
    print(f"tiny image: ok={ok} ({reason})")
    assert not ok

    real = io.BytesIO()
    Image.new("RGB", (400, 300), (255, 0, 0)).save(real, format="PNG")
    ok, reason = validate_sourced_image(real.getvalue())
    print(f"normal image: ok={ok} ({reason})")
    assert ok
    print("visual_validator._demo OK")


if __name__ == "__main__":
    _demo()
