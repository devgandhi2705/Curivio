"""
Feed v2 visual sourcing (Phase 12, Tasks 2/3) — turns each visual_director spec
into a real asset, three tiers in order:

  Tier 1: the user's OWN uploaded figures (v2_material_figures), matched by
          caption-embedding cosine similarity — same embed_query model every
          other retrieval in this codebase uses (corpus_researcher's chunk
          search, figures.py's own caption embed).
  Tier 2: images from the beat's OWN cited ranked web sources (Phase 9c
          `images` on each web finding). The beat's citations are the join key
          — deterministic, never re-guessed by similarity. Logos/icons and SVG
          are skipped unfetched; up to TIER2_MAX_FETCHES candidates are tried.
  Tier 3: generate from a fixed template (svg_templates) — the model fills
          CONTENT into the template's schema; svg_templates owns all layout.

Every tier-1/tier-2 candidate is validated (visual_validator) before use.
Tier 3 gets one regeneration attempt on a validation failure, then falls back
to a fresh tier-2 attempt, then gives up (no visual for that beat) — a lesson
with one good diagram beats one with a broken one.

CITATION JOIN: a beat's citations reference s1..sN ids that section_writer
assigns LOCALLY (per rank order of ranked_sources) and never persists to
state. Since ranked_sources doesn't change between section_writer and this
node, re-running the SAME id-assignment (section_writer._assign_ids, reused
here, not reimplemented) reproduces the identical mapping deterministically.

Isolation: feed_v2's own modules + stdlib only. Never backend.services.* /
backend.llm.*.
"""
from __future__ import annotations

import json
import logging
import re
from itertools import islice
from urllib.parse import urlsplit

from . import svg_templates, visual_validator
from .section_writer import _assign_ids
from ..db import get_connection
from ..ingestion.embeddings import embed_query
from ..llm.provider import AllLegsFailed, call_agent  # noqa: F401  (re-exported for callers)

logger = logging.getLogger(__name__)

# Cosine similarity floor for a tier-1 caption match to count as "real" — below this,
# nearest-neighbour is nearest, not relevant (matches corpus_researcher's stance that
# a vector NN is only ever a candidate, not a guarantee). Calibrated on real
# gemini-embedding-001 scores (2026-09-18): unrelated text ~0.49, same-domain WRONG
# figure 0.55-0.62, true match 0.64-0.85. 0.5 was the noise floor and took every
# near-miss. A missed true match still gets a tier-2/3 visual; a wrong figure doesn't.
TIER1_MIN_SIMILARITY = 0.65

# Tier 2: at most this many candidate images fetched per beat. Real pages carry ~20-66
# image links; most early ones are site chrome, so a few tries find the first real figure
# (Wikipedia: 3rd fetch) without fetching the whole page's worth.
TIER2_MAX_FETCHES = 5

# Skipped WITHOUT fetching. SVG: Pillow can't open it, so it can only fail validation.
# The check is on the URL path's own extension, so Wikimedia's rasterised thumbnails
# ('.../500px-Photosynthesis_en.svg.png') are kept. Logo/icon: a path segment or
# filename token (delimited by / _ - . =) naming site chrome, so 'silicon' doesn't match.
_SVG_EXTS = (".svg", ".svgz")
_CHROME_IMAGE_RE = re.compile(
    r"(?:^|[/_\-.=])(?:logos?|icons?|favicon|avatars?|badges?|sprites?|wordmark|tagline|emoji|spinner)"
    r"(?=[/_\-.=0-9]|$)")

_FILL_SYSTEM = (
    "You write the CONTENT for a diagram template — the layout is fixed by code, you "
    "only supply real, specific, concrete content matching the requested shape. No "
    "placeholder text. Return ONLY a JSON object — no prose, no markdown fences."
)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


# ── Tier 1: the user's own document figures ────────────────────────────────────
def source_tier1(spec: dict, project_id: str) -> dict | None:
    """Best caption-embedding match among the project's own figures, above the
    similarity floor. None if the project has no figures, or nothing matches."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT figure_id, caption, image_key, embedding_ref FROM v2_material_figures "
            "WHERE project_id = ? AND image_key IS NOT NULL AND embedding_ref IS NOT NULL",
            (project_id,)).fetchall()
    if not rows:
        return None
    qvec = embed_query(spec["topic"])
    best, best_score = None, -1.0
    for r in rows:
        try:
            vec = json.loads(r["embedding_ref"])
        except (TypeError, ValueError):
            continue
        score = _cosine(qvec, vec)
        if score > best_score:
            best, best_score = r, score
    if best is None or best_score < TIER1_MIN_SIMILARITY:
        return None
    return {"tier": 1, "kind": "figure", "figure_id": best["figure_id"], "image_key": best["image_key"],
           "caption": best["caption"], "score": round(best_score, 4)}


# ── Tier 2: images from the beat's own cited web sources ───────────────────────
def _skip_image_url(url: str) -> bool:
    """True for an SVG or a logo/icon/avatar/badge-style URL — never worth a fetch."""
    path = urlsplit(url).path.lower()
    return (path.endswith(_SVG_EXTS) or url.lower().startswith("data:image/svg")
            or bool(_CHROME_IMAGE_RE.search(path)))


def _tier2_candidates(spec: dict, ranked_sources: list[dict]):
    """Every non-skipped image of the beat's cited web sources, in citation then page
    order. citations are the beat's own s1..sN — reproduced deterministically, never
    re-guessed."""
    ided = _assign_ids(ranked_sources or [])
    by_id = {s["source_id"]: s for s in ided}
    for cid in spec.get("citations") or []:
        s = by_id.get(cid)
        if s and s.get("src") == "web":
            for img_url in (s.get("images") or []):
                if img_url and not _skip_image_url(img_url):
                    yield {"tier": 2, "kind": "web_image", "url": img_url, "source_id": cid,
                           "source_url": s.get("url")}


def source_tier2(spec: dict, ranked_sources: list[dict]) -> dict | None:
    """The first candidate image (logos/icons/SVG already skipped), unvalidated."""
    return next(_tier2_candidates(spec, ranked_sources), None)


# ── Tier 3: template-constrained generation ─────────────────────────────────────
def _fill_content(spec: dict, meta: dict | None) -> dict:
    vtype = spec["visual_type"]
    schema = svg_templates.TEMPLATE_SCHEMAS[vtype]
    prompt = (f"Create the content for a {vtype.replace('_', ' ')} diagram about:\n{spec['topic']}\n\n"
              f"Return ONLY JSON matching this shape: {json.dumps(schema)}")
    call_meta = {"call_type": "feed_v2_visual_fill", "surface": "feed_v2",
                 "agent_name": "visual_director", "step_index": 5}
    call_meta.update(meta or {})
    return call_agent("visual_director", [{"role": "user", "content": prompt}],
                      system=_FILL_SYSTEM, schema=schema, meta=call_meta)


def generate_tier3(spec: dict, meta: dict | None = None) -> str:
    """One fill-content call + template render. Raises AllLegsFailed if the LLM leg
    fails (caller decides whether to retry)."""
    content = _fill_content(spec, meta)
    return svg_templates.render(spec["visual_type"], content)


# ── validated sourcing (tier 1/2) + orchestrated generation (tier 3) ──────────
def _try_tier1(spec: dict, project_id: str) -> dict | None:
    cand = source_tier1(spec, project_id)
    # ponytail: no R2 bytes re-fetch here — Phase 4 already established real
    # provenance (an explicit "Figure N" caption or an embedded image in the
    # user's OWN document); re-validating via a network GET would duplicate that
    # work for near-zero real risk. Add a bytes/dimension check only if tier-1
    # mismatches show up for real.
    return cand


def _try_tier2(spec: dict, ranked_sources: list[dict]) -> dict | None:
    """First candidate that fetches AND validates; a failed one moves on to the next,
    up to TIER2_MAX_FETCHES. None -> the caller falls through to tier 3."""
    for cand in islice(_tier2_candidates(spec, ranked_sources), TIER2_MAX_FETCHES):
        data = visual_validator.fetch_web_image_bytes(cand["url"])
        if data is None:
            continue
        ok, reason = visual_validator.validate_sourced_image(data)
        if not ok:
            logger.info("[feed_v2.visual] tier2 candidate rejected (%s): %s", cand["url"], reason)
            continue
        return {**cand, "validation_reason": reason}
    return None


def _try_tier3(spec: dict, meta: dict | None) -> dict | None:
    for attempt in (1, 2):   # one regeneration attempt on a validation failure
        try:
            svg = generate_tier3(spec, meta)
        except AllLegsFailed:
            logger.warning("[feed_v2.visual] tier3 generation call failed for %r", spec.get("topic"))
            return None
        ok, reason = visual_validator.validate_generated_svg(svg)
        if ok:
            return {"tier": 3, "kind": "generated_svg", "svg": svg, "validation_reason": reason}
        logger.info("[feed_v2.visual] tier3 attempt %d failed validation: %s", attempt, reason)
    return None


def run_visual_sourcing(*, visual_specs: list[dict], project_id: str, ranked_sources: list[dict],
                        meta: dict | None = None) -> dict:
    """Three-tier sourcing + validation for every spec. Returns
    {"visual_assets": [...]} — one entry per spec, each carrying its own
    section_n/beat_index plus tier/kind/validated (+ the asset payload), or
    tier=None/validated=False when nothing usable was found."""
    assets = []
    render_down: str | None = None   # set once the headless browser can't start; tier 3 skipped after
    for spec in visual_specs or []:
        asset = _try_tier1(spec, project_id) or _try_tier2(spec, ranked_sources)
        if asset is None and render_down is None:
            try:
                asset = _try_tier3(spec, meta)
            except visual_validator.RenderUnavailable as exc:
                # Environment failure, not a verdict: this beat goes visual-less and the
                # run carries on. A broken SVG never lands here (it's a (False, reason)).
                render_down = str(exc)
                logger.warning("[feed_v2.visual] headless render unavailable, tier 3 off for this run: %s", exc)
        if asset is None:
            asset = _try_tier2(spec, ranked_sources)   # last resort after generation fails twice
        if asset is not None:
            assets.append({**spec, **asset, "validated": True})
        else:
            reason = f"render unavailable: {render_down}" if render_down else "no visual available"
            assets.append({**spec, "tier": None, "validated": False, "reason": reason})
    logger.info("[feed_v2.visual] sourced %d/%d beat(s) (tiers: %s)",
               sum(1 for a in assets if a["validated"]), len(assets),
               [a.get("tier") for a in assets])
    out: dict = {"visual_assets": assets}
    if render_down:
        missed = sum(1 for a in assets if not a["validated"])
        out["degraded_reason"] = f"visuals: render unavailable, {missed} beat(s) without a visual ({render_down})"
    return out
