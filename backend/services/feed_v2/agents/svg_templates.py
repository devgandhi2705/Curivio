"""
Feed v2 SVG templates (Phase 12, Task 3) — six FIXED diagram templates. The
model fills CONTENT (visual_sourcing calls it, schema per template below);
this module owns ALL layout/coordinates — never free-form SVG generation.

Every template is capped at a fixed max item count and wraps/truncates text
deterministically BEFORE emitting coordinates, so a normal template call
can't overflow by construction. visual_validator (Task 4) still renders and
checks headlessly — this module makes that check usually pass, not
unnecessary; a pathological caption (one giant unbreakable word) can still
overflow a box, which is exactly the case the validator exists to catch.

Isolation: stdlib only. Never backend.services.* / backend.llm.*.
"""
from __future__ import annotations

import html

_W = 800          # fixed canvas width
_PAD = 40
_FONT = "font-family='Segoe UI, Arial, sans-serif'"
_INK = "#1a1a1a"
_BOX_FILL = "#eef2f7"
_BOX_STROKE = "#3b5bdb"
_ACCENT = "#3b5bdb"
_MUTED = "#5b6472"

# Per-template item caps — the layout-level guardrail against overflow.
MAX_TIMELINE_EVENTS = 6
MAX_COLUMN_POINTS = 5
MAX_PROCESS_STEPS = 6
MAX_HIERARCHY_CHILDREN = 6
MAX_LABELLED_PARTS = 6

TEMPLATE_SCHEMAS: dict[str, dict] = {
    "timeline": {"type": "object", "required": ["title", "events"],
                "properties": {"title": {"type": "string"},
                    "events": {"type": "array", "items": {"type": "object",
                        "properties": {"label": {"type": "string"}, "date": {"type": "string"}}}}}},
    "comparison": {"type": "object",
                  "required": ["title", "left_label", "right_label", "left_points", "right_points"],
                  "properties": {"title": {"type": "string"},
                      "left_label": {"type": "string"}, "right_label": {"type": "string"},
                      "left_points": {"type": "array", "items": {"type": "string"}},
                      "right_points": {"type": "array", "items": {"type": "string"}}}},
    "process": {"type": "object", "required": ["title", "steps"],
               "properties": {"title": {"type": "string"},
                   "steps": {"type": "array", "items": {"type": "string"}}}},
    "hierarchy": {"type": "object", "required": ["title", "root", "children"],
                 "properties": {"title": {"type": "string"}, "root": {"type": "string"},
                     "children": {"type": "array", "items": {"type": "string"}}}},
    "before_after": {"type": "object",
                     "required": ["title", "before_label", "after_label", "before_points", "after_points"],
                     "properties": {"title": {"type": "string"},
                         "before_label": {"type": "string"}, "after_label": {"type": "string"},
                         "before_points": {"type": "array", "items": {"type": "string"}},
                         "after_points": {"type": "array", "items": {"type": "string"}}}},
    "labelled_parts": {"type": "object", "required": ["title", "parts"],
                       "properties": {"title": {"type": "string"},
                           "parts": {"type": "array", "items": {"type": "object",
                               "properties": {"label": {"type": "string"}, "description": {"type": "string"}}}}}},
}


# ── shared primitives ───────────────────────────────────────────────────────
def _esc(s: object) -> str:
    return html.escape(str(s or ""), quote=True)


def _wrap(text: str, max_chars: int, max_lines: int) -> list[str]:
    """Greedy word-wrap to max_chars/line, hard-capped at max_lines (last line
    gets an ellipsis if content remains) — deterministic, no text-metrics lib."""
    words = (text or "").split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if len(trial) <= max_chars:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
            if len(cur) > max_chars:      # one unbreakable oversized word
                cur = cur[:max_chars - 1] + "…"
        if len(lines) == max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) == max_lines and (len(" ".join(words)) > sum(len(l) for l in lines)):
        lines[-1] = lines[-1].rstrip("…")[:max_chars - 1] + "…"
    return lines or [""]


def _text_lines(x: int, y: int, lines: list[str], *, size: int = 14, weight: str = "normal",
                fill: str = _INK, anchor: str = "start", line_height: int = 18) -> str:
    parts = []
    for i, ln in enumerate(lines):
        parts.append(f"<text x='{x}' y='{y + i * line_height}' font-size='{size}' "
                     f"font-weight='{weight}' fill='{fill}' text-anchor='{anchor}' {_FONT}>{_esc(ln)}</text>")
    return "".join(parts)


def _svg(height: int, title: str, body: str) -> str:
    return (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {_W} {height}' "
            f"width='{_W}' height='{height}'>"
            f"<rect class='bg' x='0' y='0' width='{_W}' height='{height}' fill='#ffffff'/>"
            f"<text x='{_PAD}' y='{_PAD}' font-size='20' font-weight='700' fill='{_INK}' {_FONT}>"
            f"{_esc(title)}</text>"
            f"{body}</svg>")


# ── 1. timeline ──────────────────────────────────────────────────────────────
def render_timeline(content: dict) -> str:
    events = (content.get("events") or [])[:MAX_TIMELINE_EVENTS]
    n = max(len(events), 1)
    height = 260
    y_line = 150
    x0, x1 = _PAD + 20, _W - _PAD - 20
    step = (x1 - x0) / max(n - 1, 1)
    body = [f"<line x1='{x0}' y1='{y_line}' x2='{x1}' y2='{y_line}' stroke='{_ACCENT}' stroke-width='3'/>"]
    for i, ev in enumerate(events):
        cx = x0 + step * i if n > 1 else (x0 + x1) / 2
        body.append(f"<circle cx='{cx}' cy='{y_line}' r='8' fill='{_ACCENT}'/>")
        label_lines = _wrap(ev.get("label") or "", 20, 2)
        date = ev.get("date") or ""
        above = i % 2 == 0
        label_y = y_line - 44 if above else y_line + 34
        date_y = label_y - 18 if above else label_y + len(label_lines) * 16 + 4
        body.append(_text_lines(cx, label_y, label_lines, size=13, weight="600",
                                anchor="middle", line_height=16))
        if date:
            body.append(_text_lines(cx, date_y, [date], size=11, fill=_MUTED, anchor="middle"))
    return _svg(height, content.get("title") or "Timeline", "".join(body))


# ── 2 & 5. two-column layout, shared by comparison + before_after ─────────────
def _render_two_column(title: str, left_label: str, right_label: str,
                       left_points: list[str], right_points: list[str]) -> str:
    left_points = (left_points or [])[:MAX_COLUMN_POINTS]
    right_points = (right_points or [])[:MAX_COLUMN_POINTS]
    rows = max(len(left_points), len(right_points), 1)
    row_h = 46
    top = 90
    height = top + rows * row_h + 30
    col_w = (_W - 3 * _PAD) / 2
    lx, rx = _PAD, _PAD * 2 + col_w
    body = [
        f"<rect x='{lx}' y='{top - 40}' width='{col_w}' height='{rows * row_h + 20}' "
        f"fill='{_BOX_FILL}' stroke='{_BOX_STROKE}' rx='8'/>",
        f"<rect x='{rx}' y='{top - 40}' width='{col_w}' height='{rows * row_h + 20}' "
        f"fill='{_BOX_FILL}' stroke='{_BOX_STROKE}' rx='8'/>",
        _text_lines(lx + 16, top - 16, [left_label or ""], size=15, weight="700"),
        _text_lines(rx + 16, top - 16, [right_label or ""], size=15, weight="700"),
    ]
    for i, pt in enumerate(left_points):
        lines = _wrap(pt, 42, 2)
        body.append(_text_lines(lx + 16, top + 12 + i * row_h, [f"• {lines[0]}"] + lines[1:], size=12))
    for i, pt in enumerate(right_points):
        lines = _wrap(pt, 42, 2)
        body.append(_text_lines(rx + 16, top + 12 + i * row_h, [f"• {lines[0]}"] + lines[1:], size=12))
    return _svg(height, title, "".join(body))


def render_comparison(content: dict) -> str:
    return _render_two_column(content.get("title") or "Comparison",
                              content.get("left_label") or "A", content.get("right_label") or "B",
                              content.get("left_points") or [], content.get("right_points") or [])


def render_before_after(content: dict) -> str:
    return _render_two_column(content.get("title") or "Before / After",
                              content.get("before_label") or "Before", content.get("after_label") or "After",
                              content.get("before_points") or [], content.get("after_points") or [])


# ── 3. process ───────────────────────────────────────────────────────────────
def render_process(content: dict) -> str:
    steps = (content.get("steps") or [])[:MAX_PROCESS_STEPS]
    n = max(len(steps), 1)
    box_w = (_W - _PAD * 2 - (n - 1) * 20) / n
    box_h = 90
    y = 90
    height = y + box_h + 30
    body = []
    for i, step in enumerate(steps):
        x = _PAD + i * (box_w + 20)
        body.append(f"<rect x='{x}' y='{y}' width='{box_w}' height='{box_h}' "
                    f"fill='{_BOX_FILL}' stroke='{_BOX_STROKE}' rx='8'/>")
        body.append(_text_lines(x + box_w / 2, y + 24, [str(i + 1)], size=16, weight="700",
                                fill=_ACCENT, anchor="middle"))
        lines = _wrap(step, int(box_w / 6.5), 3)
        body.append(_text_lines(x + box_w / 2, y + 46, lines, size=11, anchor="middle", line_height=14))
        if i < n - 1:
            ax = x + box_w + 4
            body.append(f"<polygon points='{ax},{y + box_h/2 - 6} {ax + 12},{y + box_h/2} "
                        f"{ax},{y + box_h/2 + 6}' fill='{_ACCENT}'/>")
    return _svg(height, content.get("title") or "Process", "".join(body))


# ── 4. hierarchy (root + one level of children) ────────────────────────────────
def render_hierarchy(content: dict) -> str:
    children = (content.get("children") or [])[:MAX_HIERARCHY_CHILDREN]
    n = max(len(children), 1)
    root_y = 80
    child_y = 190
    box_w = min(160, (_W - _PAD * 2) / n - 16)
    box_h = 60
    height = child_y + box_h + 30
    root_x = _W / 2
    root_w = 200
    body = [f"<rect x='{root_x - root_w/2}' y='{root_y}' width='{root_w}' height='{box_h}' "
           f"fill='{_ACCENT}' rx='8'/>",
           _text_lines(root_x, root_y + 34, _wrap(content.get("root") or "", 26, 1), size=14,
                       weight="700", fill="#ffffff", anchor="middle")]
    span = _W - _PAD * 2
    step = span / n
    for i, child in enumerate(children):
        cx = _PAD + step * i + step / 2
        body.append(f"<line x1='{root_x}' y1='{root_y + box_h}' x2='{cx}' y2='{child_y}' "
                    f"stroke='{_MUTED}' stroke-width='1.5'/>")
        body.append(f"<rect x='{cx - box_w/2}' y='{child_y}' width='{box_w}' height='{box_h}' "
                    f"fill='{_BOX_FILL}' stroke='{_BOX_STROKE}' rx='8'/>")
        lines = _wrap(child, int(box_w / 6.5), 3)
        body.append(_text_lines(cx, child_y + 24, lines, size=11, anchor="middle", line_height=14))
    return _svg(height, content.get("title") or "Hierarchy", "".join(body))


# ── 6. labelled parts (numbered legend, no base image to annotate) ────────────
def render_labelled_parts(content: dict) -> str:
    parts = (content.get("parts") or [])[:MAX_LABELLED_PARTS]
    n = max(len(parts), 1)
    row_h = 56
    top = 80
    height = top + n * row_h + 20
    body = []
    for i, p in enumerate(parts):
        cy = top + i * row_h + 18
        body.append(f"<circle cx='{_PAD + 14}' cy='{cy}' r='14' fill='{_ACCENT}'/>")
        body.append(_text_lines(_PAD + 14, cy + 5, [str(i + 1)], size=13, weight="700",
                                fill="#ffffff", anchor="middle"))
        label_lines = _wrap(p.get("label") or "", 60, 1)
        desc_lines = _wrap(p.get("description") or "", 70, 1)
        body.append(_text_lines(_PAD + 40, cy - 4, label_lines, size=13, weight="600"))
        if desc_lines[0]:
            body.append(_text_lines(_PAD + 40, cy + 16, desc_lines, size=11, fill=_MUTED))
    return _svg(height, content.get("title") or "Parts", "".join(body))


RENDERERS = {
    "timeline": render_timeline,
    "comparison": render_comparison,
    "process": render_process,
    "hierarchy": render_hierarchy,
    "before_after": render_before_after,
    "labelled_parts": render_labelled_parts,
}


def render(visual_type: str, content: dict) -> str:
    fn = RENDERERS.get(visual_type)
    if fn is None:
        raise ValueError(f"unknown visual_type {visual_type!r}")
    return fn(content)


def _demo() -> None:
    """ponytail self-check: every template renders well-formed SVG, capped item
    counts truncate instead of overflowing the fixed canvas."""
    import xml.etree.ElementTree as ET  # ponytail: stdlib parser, fine here — always OUR OWN
                                        # generated strings (self-check), never external/untrusted XML

    samples = {
        "timeline": {"title": "History", "events": [{"label": f"Event {i}", "date": f"19{i}0"}
                                                     for i in range(9)]},   # 9 > cap of 6
        "comparison": {"title": "Old vs New", "left_label": "Old", "right_label": "New",
                       "left_points": ["slow", "manual"], "right_points": ["fast", "automatic", "cheap"]},
        "process": {"title": "Pipeline", "steps": [f"Step {i} with a fairly long description of work" for i in range(8)]},
        "hierarchy": {"title": "Org", "root": "CEO", "children": [f"VP {i}" for i in range(7)]},
        "before_after": {"title": "Refactor", "before_label": "Before", "after_label": "After",
                         "before_points": ["tangled"], "after_points": ["clean", "tested"]},
        "labelled_parts": {"title": "Anatomy", "parts": [{"label": f"Part {i}", "description": "does a thing"}
                                                         for i in range(7)]},
    }
    for vtype, content in samples.items():
        svg = render(vtype, content)
        root = ET.fromstring(svg)              # raises if not well-formed XML
        assert root.tag.endswith("svg")
        assert 'viewBox' in svg
        print(f"{vtype}: {len(svg)} bytes, well-formed, viewBox present")
    print("svg_templates._demo OK")


if __name__ == "__main__":
    _demo()
