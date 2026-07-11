"""
Source Grounding Service

Enforces that every generated card cites ONLY URLs supplied by the retrieval
system.  Operates on the parsed LLM JSON package BEFORE it is saved.

Three-stage enforcement
-----------------------
Stage 1 — Validate: accept sources whose URL (normalised) is in allowed_urls.
Stage 2 — Repair:   for rejected URLs, attempt title-similarity matching against
                     allowed sources.  If Jaccard overlap ≥ REPAIR_THRESHOLD,
                     replace the fabricated URL with the real match.
Stage 3 — Discard:  sources that survive neither stage are dropped.  Cards with
                     zero surviving sources are removed from the package.

Hard failure
------------
If ALL core insight cards are stripped, ground_package() raises RuntimeError so
the caller can surface the error rather than saving an empty package.

Violation logging
-----------------
Every rejected or repaired source writes a structured entry to the dedicated
logger `curivio.grounding.violations` at WARNING level.  The caller also receives
a list[Violation] for further handling.

Public API
----------
ground_package(raw_package, allowed_urls, allowed_titles, project_id, day_number)
    → tuple[dict, list[Violation]]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .similarity_service import token_overlap

_violation_logger = logging.getLogger("curivio.grounding.violations")

# Minimum Jaccard title-similarity to accept a repair mapping.
# Low enough to catch rephrasings; high enough to avoid wrong-article substitution.
REPAIR_THRESHOLD: float = 0.35


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class Violation:
    card_id:     str
    invalid_url: str
    action:      str              # "repaired" | "discarded"
    repaired_to: str | None = None
    reason:      str = ""


# ── Private helpers ───────────────────────────────────────────────────────────

def _norm(url: str) -> str:
    """Normalise URL for set membership: lowercase + strip trailing slash."""
    return (url or "").rstrip("/").lower()


def _normalize_action_item(value):
    """
    Coerce a card-level action_item to a plain string.

    Not a documented per-card field (only the package-level action_item is
    schema'd) — the writer occasionally attaches one to individual cards
    anyway (echoing ACTION_DESIGN's type/description framing meant for the
    package-level field), sometimes as a {"type", "description"} dict.
    Returns the value unchanged if already a string.
    """
    if isinstance(value, str) or value is None:
        return value
    if isinstance(value, dict):
        t = (value.get("type") or "").strip()
        d = (value.get("description") or "").strip()
        if t and d:
            return f"{t}: {d}"
        return t or d or str(value)
    return str(value)


def _repair_url(
    invalid_title:  str,
    allowed_titles: dict[str, str],   # normalised_url → original title
    threshold:      float = REPAIR_THRESHOLD,
) -> tuple[str, str] | None:
    """
    Find the closest valid source by title similarity.

    Returns (normalised_url, original_title) when a match above `threshold`
    is found, else None.  Prefers the highest-scoring candidate.
    """
    best_url:   str | None = None
    best_title: str        = ""
    best_score: float      = threshold - 1e-9   # just below threshold

    for url, title in allowed_titles.items():
        score = token_overlap(invalid_title, title)
        if score > best_score:
            best_score = score
            best_url   = url
            best_title = title

    return (best_url, best_title) if best_url else None


# ── Core enforcement ──────────────────────────────────────────────────────────

def ground_package(
    raw_package:     dict,
    allowed_urls:    frozenset[str],
    allowed_titles:  dict[str, str],   # normalised_url → title
    project_id:      str,
    day_number:      int,
    citable_sources: dict[str, dict] | None = None,
) -> tuple[dict, list[Violation]]:
    """
    Validate and repair source citations in a generated package in-place.

    Mutates raw_package: replaces primary_source / supporting_sources with a
    flat `source_links` list containing only verified real URLs.

    Args:
        raw_package:     Parsed LLM JSON dict with "insights" and "curiosity_insights".
        allowed_urls:    Normalised URLs from the retrieval system (frozenset).
        allowed_titles:  Mapping of normalised URL → article title (for repair).
        project_id:      Used in violation log entries.
        day_number:      Used in violation log entries.
        citable_sources: Feed-4.2 — Source-ID -> {"url", "images"} for whatever
                         this generation actually offered the writer (empty/None
                         when full_content wasn't wired in, e.g. package mode or
                         a Groq-answered batch). Used to validate per-block
                         "image" content and optional "source_id" fields.

    Returns:
        (raw_package, violations)

    Raises:
        RuntimeError: when all core insight cards are stripped of valid sources.
    """
    citable_sources = citable_sources or {}
    _valid_source_ids = frozenset(citable_sources.keys())
    _valid_image_urls = frozenset(
        img for v in citable_sources.values() for img in (v.get("images") or [])
    )

    violations: list[Violation]   = []
    used_primary: set[str]        = set()

    # Build a reverse mapping: normalised_url → original URL string (for output)
    orig_url: dict[str, str] = {}
    for a_url, _ in allowed_titles.items():
        # allowed_titles keys are already normalised; find the original via allowed_urls
        orig_url[a_url] = a_url   # normalised is used for output when no original known

    def _validate_or_repair(src: dict | None, card_id: str) -> dict | None:
        """
        Accept src if URL is in allowed_urls.
        On rejection: try title-based repair.
        On repair failure: discard and record violation.
        Returns a clean {title, url} dict or None.
        """
        if not isinstance(src, dict):
            return None

        raw_url   = src.get("url") or ""
        raw_title = src.get("title") or ""

        if not raw_url:
            return None   # empty URL — no violation, LLM just omitted the field

        norm = _norm(raw_url)

        if norm in allowed_urls:
            return {"title": raw_title, "url": raw_url}

        # URL not in retrieval set — attempt repair
        match = _repair_url(raw_title, allowed_titles)
        if match:
            matched_norm, matched_title = match
            # Reconstruct best-effort original URL from allowed_titles key
            v = Violation(
                card_id=card_id,
                invalid_url=raw_url,
                action="repaired",
                repaired_to=matched_norm,
                reason=f"title matched '{matched_title[:60]}' (Jaccard >= {REPAIR_THRESHOLD})",
            )
            violations.append(v)
            _violation_logger.warning(
                "[grounding] project=%s day=%d card=%s | REPAIRED %r -> %r | %s",
                project_id, day_number, card_id, raw_url, matched_norm, v.reason,
            )
            return {"title": matched_title, "url": matched_norm}

        # No repair possible — discard
        v = Violation(
            card_id=card_id,
            invalid_url=raw_url,
            action="discarded",
            reason="not in retrieved set; no title match above threshold",
        )
        violations.append(v)
        _violation_logger.warning(
            "[grounding] project=%s day=%d card=%s | DISCARDED %r | %s",
            project_id, day_number, card_id, raw_url, v.reason,
        )
        return None

    def _process_card(card: dict) -> None:
        card_id = card.get("id") or "unknown"

        # Handle new format: primary_source + supporting_sources
        primary   = _validate_or_repair(card.get("primary_source"), card_id)
        secondary = [
            s for s in (
                _validate_or_repair(x, card_id)
                for x in (card.get("supporting_sources") or [])
            ) if s
        ]

        # Legacy format fallback: source_links list
        if not primary and not secondary:
            old = card.get("source_links") or []
            if old:
                primary   = _validate_or_repair(old[0], card_id) if old else None
                secondary = [
                    s for s in (
                        _validate_or_repair(x, card_id) for x in old[1:]
                    ) if s
                ]

        # Enforce cross-card primary uniqueness (same URL cannot be primary twice)
        if primary:
            p_norm = _norm(primary["url"])
            if p_norm in used_primary:
                # Demote to supporting; promote first unused supporting to primary
                secondary.insert(0, primary)
                primary = None
                for i, s in enumerate(secondary):
                    s_norm = _norm(s["url"])
                    if s_norm not in used_primary:
                        primary = s
                        secondary.pop(i)
                        used_primary.add(s_norm)
                        break
            else:
                used_primary.add(p_norm)

        card["source_links"] = ([primary] if primary else []) + secondary
        card.pop("primary_source",     None)
        card.pop("supporting_sources", None)

        _validate_blocks(card, card_id)

        if "action_item" in card and not isinstance(card["action_item"], str):
            _before = card["action_item"]
            card["action_item"] = _normalize_action_item(_before)
            _violation_logger.warning(
                "[grounding] project=%s day=%d card=%s | NORMALIZED action_item %r -> %r",
                project_id, day_number, card_id, _before, card["action_item"],
            )

    def _validate_blocks(card: dict, card_id: str) -> None:
        """
        Feed-4.2 — validate per-block "image" content and optional "source_id".

        image blocks: content must be a URL this card's source(s) actually
        offered (citable_sources); otherwise the block is dropped outright —
        an image block's entire payload IS the URL, there's nothing to "strip"
        and keep.
        source_id: must reference a real Source-ID from this generation;
        otherwise only the field is stripped — the block's content stands on
        its own regardless of whether the attribution survives.
        """
        blocks = card.get("blocks") or []
        if not blocks:
            return

        kept: list[dict] = []
        for block in blocks:
            if block.get("type") == "image":
                url = block.get("content") or ""
                if url not in _valid_image_urls:
                    _violation_logger.warning(
                        "[grounding] project=%s day=%d card=%s | DROPPED image block — "
                        "URL not offered to writer: %r",
                        project_id, day_number, card_id, url,
                    )
                    continue

            if "source_id" in block and block["source_id"] not in _valid_source_ids:
                _violation_logger.warning(
                    "[grounding] project=%s day=%d card=%s | STRIPPED invalid source_id %r",
                    project_id, day_number, card_id, block["source_id"],
                )
                block = {k: v for k, v in block.items() if k != "source_id"}

            kept.append(block)

        card["blocks"] = kept

    # ── Process all cards ─────────────────────────────────────────────────────
    for card in raw_package.get("insights", []):
        _process_card(card)
    for card in raw_package.get("curiosity_insights", []):
        _process_card(card)

    # ── Backup rescue: assign any unclaimed allowed URL to sourceless core cards ─
    # Runs BEFORE the drop filter so rescued cards survive.
    _sourceless_core = [c for c in raw_package.get("insights", []) if not c.get("source_links")]
    if _sourceless_core:
        _spare_urls = [
            (url, title) for url, title in allowed_titles.items()
            if _norm(url) not in used_primary
        ]
        for _card in _sourceless_core:
            if not _spare_urls:
                break
            _fallback_url, _fallback_title = _spare_urls.pop(0)
            _card["source_links"] = [{"title": _fallback_title, "url": _fallback_url}]
            used_primary.add(_norm(_fallback_url))
            _violation_logger.warning(
                "[grounding] project=%s day=%d card=%s | RESCUED with fallback url=%r",
                project_id, day_number, _card.get("id", "?"), _fallback_url,
            )

    # ── Drop sourceless cards ─────────────────────────────────────────────────
    _before = len(raw_package.get("insights", []))
    raw_package["insights"] = [
        c for c in raw_package.get("insights", []) if c.get("source_links")
    ]
    _after = len(raw_package["insights"])

    if _before > _after:
        _violation_logger.warning(
            "[grounding] project=%s day=%d: dropped %d/%d core cards — zero verified sources",
            project_id, day_number, _before - _after, _before,
        )

    raw_package["curiosity_insights"] = [
        c for c in raw_package.get("curiosity_insights", [])
        if c.get("source_links")
    ]

    # ── Hard fail if all core cards dropped ───────────────────────────────────
    if not raw_package.get("insights"):
        _violation_logger.error(
            "[grounding] project=%s day=%d: ALL core cards dropped — generation failed",
            project_id, day_number,
        )
        raise RuntimeError(
            "Generated cards lacked verified source links. "
            "The model did not faithfully cite retrieved articles — please try again."
        )

    return raw_package, violations
