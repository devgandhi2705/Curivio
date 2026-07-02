"""
Tests for source_grounding_service.py — Phase 7.5

Covers:
  - _repair_url: finds closest valid source by title similarity
  - ground_package:
      valid sources pass through unchanged
      invalid primary_source URL → repaired when title matches
      invalid primary_source URL → discarded when no title match (violation logged)
      empty URL in source → dropped silently (no violation)
      supporting_sources cleaned independently
      legacy source_links format handled
      primary uniqueness enforced across cards
      card with zero valid sources → dropped from package
      all core cards dropped → RuntimeError raised
      curiosity cards with no sources → dropped (no RuntimeError)
      violations list contains correct Violation records
      repaired violation has action="repaired" and repaired_to set
      discarded violation has action="discarded"

Run:
    pytest tests/test_source_grounding_service.py -v
"""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.source_grounding_service import (
    REPAIR_THRESHOLD,
    Violation,
    _norm,
    _repair_url,
    ground_package,
)


# ── Test fixtures ─────────────────────────────────────────────────────────────

REAL_URL_A = "https://reuters.com/business/fed-raises-rates-2025"
REAL_URL_B = "https://worldbank.org/en/trade-report-2025"
REAL_URL_C = "https://ft.com/content/export-strategy"

ALLOWED_URLS: frozenset[str] = frozenset([
    _norm(REAL_URL_A),
    _norm(REAL_URL_B),
    _norm(REAL_URL_C),
])

ALLOWED_TITLES: dict[str, str] = {
    _norm(REAL_URL_A): "Federal Reserve Raises Interest Rates",
    _norm(REAL_URL_B): "World Bank Trade Report 2025",
    _norm(REAL_URL_C): "Export Strategy for Founders",
}


def _package(*cards, curiosity=None) -> dict:
    """Build a minimal raw package dict."""
    return {
        "insights": list(cards),
        "curiosity_insights": list(curiosity or []),
    }


def _card(card_id: str, primary_url: str, primary_title: str = "",
          supporting: list | None = None) -> dict:
    return {
        "id":             card_id,
        "title":          f"Card {card_id}",
        "primary_source": {"url": primary_url, "title": primary_title},
        "supporting_sources": supporting or [],
    }


def _curiosity_card(card_id: str, primary_url: str) -> dict:
    return {
        "id":             card_id,
        "title":          f"Curiosity {card_id}",
        "primary_source": {"url": primary_url, "title": ""},
        "supporting_sources": [],
    }


# ── _norm ─────────────────────────────────────────────────────────────────────

class TestNorm:
    def test_strips_trailing_slash(self):
        assert _norm("https://reuters.com/") == "https://reuters.com"

    def test_lowercases(self):
        assert _norm("HTTPS://Reuters.COM") == "https://reuters.com"

    def test_empty_returns_empty(self):
        assert _norm("") == ""


# ── _repair_url ───────────────────────────────────────────────────────────────

class TestRepairUrl:
    def test_finds_exact_title_match(self):
        result = _repair_url(
            "Federal Reserve Raises Interest Rates",
            ALLOWED_TITLES,
        )
        assert result is not None
        matched_url, matched_title = result
        assert matched_url == _norm(REAL_URL_A)

    def test_finds_near_title_match(self):
        # "Fed Raises Rates" → close enough to "Federal Reserve Raises Interest Rates"
        result = _repair_url("Fed Raises Interest Rates", ALLOWED_TITLES)
        assert result is not None

    def test_no_match_returns_none(self):
        result = _repair_url("Completely Unrelated Quantum Physics Zebra", ALLOWED_TITLES)
        assert result is None

    def test_returns_tuple_on_match(self):
        result = _repair_url("Federal Reserve Raises Interest Rates", ALLOWED_TITLES)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_empty_title_returns_none(self):
        result = _repair_url("", ALLOWED_TITLES)
        assert result is None

    def test_empty_allowed_titles_returns_none(self):
        result = _repair_url("Federal Reserve Raises Rates", {})
        assert result is None


# ── ground_package — happy path ───────────────────────────────────────────────

class TestGroundPackageHappyPath:
    def test_valid_primary_passes_through(self):
        pkg = _package(_card("c1", REAL_URL_A, "Federal Reserve Raises Interest Rates"))
        result, violations = ground_package(pkg, ALLOWED_URLS, ALLOWED_TITLES, "proj1", 1)
        assert len(result["insights"]) == 1
        assert result["insights"][0]["source_links"][0]["url"] == REAL_URL_A

    def test_valid_sources_produce_no_violations(self):
        pkg = _package(_card("c1", REAL_URL_A))
        _, violations = ground_package(pkg, ALLOWED_URLS, ALLOWED_TITLES, "proj1", 1)
        assert violations == []

    def test_primary_source_field_removed_from_output(self):
        pkg = _package(_card("c1", REAL_URL_A))
        result, _ = ground_package(pkg, ALLOWED_URLS, ALLOWED_TITLES, "proj1", 1)
        assert "primary_source" not in result["insights"][0]

    def test_supporting_sources_field_removed_from_output(self):
        pkg = _package(_card("c1", REAL_URL_A, supporting=[{"url": REAL_URL_B, "title": "WB"}]))
        result, _ = ground_package(pkg, ALLOWED_URLS, ALLOWED_TITLES, "proj1", 1)
        assert "supporting_sources" not in result["insights"][0]

    def test_valid_supporting_included_in_source_links(self):
        pkg = _package(_card("c1", REAL_URL_A, supporting=[{"url": REAL_URL_B, "title": "WB"}]))
        result, _ = ground_package(pkg, ALLOWED_URLS, ALLOWED_TITLES, "proj1", 1)
        urls = [s["url"] for s in result["insights"][0]["source_links"]]
        assert REAL_URL_B in urls

    def test_multiple_valid_cards_all_kept(self):
        pkg = _package(
            _card("c1", REAL_URL_A),
            _card("c2", REAL_URL_B),
        )
        result, _ = ground_package(pkg, ALLOWED_URLS, ALLOWED_TITLES, "proj1", 1)
        assert len(result["insights"]) == 2


# ── Repair behavior ───────────────────────────────────────────────────────────

class TestGroundPackageRepair:
    def test_repaired_url_produces_violation_with_action_repaired(self):
        # LLM uses a slightly different URL but real title
        pkg = _package(_card("c1", "https://fake-reuters.com/rates",
                              "Federal Reserve Raises Interest Rates"))
        _, violations = ground_package(pkg, ALLOWED_URLS, ALLOWED_TITLES, "proj1", 1)
        repaired = [v for v in violations if v.action == "repaired"]
        assert len(repaired) == 1

    def test_repaired_source_contains_real_url(self):
        pkg = _package(_card("c1", "https://fake-reuters.com/rates",
                              "Federal Reserve Raises Interest Rates"))
        result, _ = ground_package(pkg, ALLOWED_URLS, ALLOWED_TITLES, "proj1", 1)
        assert result["insights"][0]["source_links"]
        assert result["insights"][0]["source_links"][0]["url"] == _norm(REAL_URL_A)

    def test_repaired_violation_has_repaired_to_set(self):
        pkg = _package(_card("c1", "https://fake-reuters.com/rates",
                              "Federal Reserve Raises Interest Rates"))
        _, violations = ground_package(pkg, ALLOWED_URLS, ALLOWED_TITLES, "proj1", 1)
        assert violations[0].repaired_to == _norm(REAL_URL_A)

    def test_repaired_violation_records_original_url(self):
        invalid_url = "https://fake-reuters.com/rates"
        pkg = _package(_card("c1", invalid_url, "Federal Reserve Raises Interest Rates"))
        _, violations = ground_package(pkg, ALLOWED_URLS, ALLOWED_TITLES, "proj1", 1)
        assert violations[0].invalid_url == invalid_url

    def test_unmatched_url_produces_discarded_violation(self):
        pkg = _package(_card("c1", "https://totally-fake.com/unrelated",
                              "Quantum Computing Zebra Research"))
        # Card will have c1 discarded; since no valid source, card dropped.
        # Need another valid card so we don't hit RuntimeError
        pkg["insights"].append(_card("c2", REAL_URL_A))
        _, violations = ground_package(pkg, ALLOWED_URLS, ALLOWED_TITLES, "proj1", 1)
        discarded = [v for v in violations if v.action == "discarded"]
        assert len(discarded) >= 1

    def test_discarded_violation_has_no_repaired_to(self):
        pkg = _package(
            _card("c1", "https://fake.com/zebra", "Quantum Zebra Research"),
            _card("c2", REAL_URL_A),
        )
        _, violations = ground_package(pkg, ALLOWED_URLS, ALLOWED_TITLES, "proj1", 1)
        discarded = [v for v in violations if v.action == "discarded"]
        assert all(v.repaired_to is None for v in discarded)


# ── Discard and drop behavior ─────────────────────────────────────────────────

class TestGroundPackageDiscard:
    def test_card_with_empty_url_source_dropped(self):
        pkg = _package(_card("c1", ""), _card("c2", REAL_URL_A))
        result, violations = ground_package(pkg, ALLOWED_URLS, ALLOWED_TITLES, "proj1", 1)
        # Card c1 has empty URL → no source_links → dropped
        ids = [c["id"] for c in result["insights"]]
        assert "c1" not in ids
        assert "c2" in ids

    def test_empty_url_produces_no_violation(self):
        pkg = _package(_card("c1", ""), _card("c2", REAL_URL_A))
        _, violations = ground_package(pkg, ALLOWED_URLS, ALLOWED_TITLES, "proj1", 1)
        # Empty URL is silently skipped; only unmatched non-empty URLs are violations
        assert all(v.invalid_url != "" for v in violations)

    def test_invalid_supporting_url_discarded_silently(self):
        pkg = _package(_card("c1", REAL_URL_A,
                              supporting=[{"url": "https://fake.com/s", "title": "Quantum"}]))
        result, _ = ground_package(pkg, ALLOWED_URLS, ALLOWED_TITLES, "proj1", 1)
        # Card is kept (primary valid); fake supporting is dropped
        assert result["insights"][0]["source_links"]
        sl_urls = [s["url"] for s in result["insights"][0]["source_links"]]
        assert "https://fake.com/s" not in sl_urls

    def test_all_core_cards_dropped_raises_runtime_error(self):
        pkg = _package(_card("c1", "https://fake.com/article", "Quantum Zebra"))
        with pytest.raises(RuntimeError, match="did not faithfully cite"):
            ground_package(pkg, ALLOWED_URLS, ALLOWED_TITLES, "proj1", 1)

    def test_curiosity_all_dropped_does_not_raise(self):
        pkg = {
            "insights": [{"id": "c1", "primary_source": {"url": REAL_URL_A}, "supporting_sources": []}],
            "curiosity_insights": [_curiosity_card("q1", "https://fake.com/curiosity")],
        }
        result, _ = ground_package(pkg, ALLOWED_URLS, ALLOWED_TITLES, "proj1", 1)
        assert result["curiosity_insights"] == []
        assert len(result["insights"]) == 1


# ── Legacy source_links format ────────────────────────────────────────────────

class TestLegacySourceLinks:
    def test_legacy_format_primary_accepted(self):
        card = {
            "id": "c1",
            "title": "Legacy Card",
            "source_links": [{"url": REAL_URL_A, "title": "Reuters"}],
        }
        pkg = {"insights": [card], "curiosity_insights": []}
        result, _ = ground_package(pkg, ALLOWED_URLS, ALLOWED_TITLES, "proj1", 1)
        assert result["insights"][0]["source_links"][0]["url"] == REAL_URL_A

    def test_legacy_format_invalid_url_discarded(self):
        card = {
            "id": "c1",
            "title": "Legacy Card",
            "source_links": [{"url": "https://fake.com/legacy", "title": "Quantum Zebra"}],
        }
        pkg = {"insights": [card, {
            "id": "c2", "title": "Valid",
            "source_links": [{"url": REAL_URL_A, "title": "Reuters"}],
        }], "curiosity_insights": []}
        result, violations = ground_package(pkg, ALLOWED_URLS, ALLOWED_TITLES, "proj1", 1)
        ids = [c["id"] for c in result["insights"]]
        assert "c1" not in ids
        assert len(violations) >= 1


# ── Primary uniqueness ────────────────────────────────────────────────────────

class TestPrimaryUniqueness:
    def test_same_primary_url_demoted_when_duplicate(self):
        # c2 has REAL_URL_A as primary (already used by c1) and REAL_URL_B as supporting.
        # After enforcement: c2's primary is promoted from supporting → REAL_URL_B.
        pkg = _package(
            _card("c1", REAL_URL_A),
            _card("c2", REAL_URL_A, supporting=[{"url": REAL_URL_B, "title": "WB"}]),
        )
        result, _ = ground_package(pkg, ALLOWED_URLS, ALLOWED_TITLES, "proj1", 1)
        c2 = next(c for c in result["insights"] if c["id"] == "c2")
        # c2's first source_link should be the promoted supporting (REAL_URL_B)
        assert c2["source_links"][0]["url"] == REAL_URL_B

    def test_violation_objects_have_correct_card_id(self):
        pkg = _package(
            _card("c1", "https://fake.com/a", "Quantum Zebra"),
            _card("c2", REAL_URL_A),
        )
        _, violations = ground_package(pkg, ALLOWED_URLS, ALLOWED_TITLES, "proj1", 1)
        card_ids = {v.card_id for v in violations}
        assert "c1" in card_ids


# ── Violation data model ──────────────────────────────────────────────────────

class TestViolationModel:
    def test_violation_is_dataclass(self):
        v = Violation(card_id="c1", invalid_url="https://fake.com", action="discarded")
        assert v.card_id == "c1"
        assert v.invalid_url == "https://fake.com"
        assert v.action == "discarded"
        assert v.repaired_to is None

    def test_ground_package_returns_list_of_violations(self):
        pkg = _package(
            _card("c1", "https://fake.com/one", "Quantum"),
            _card("c2", REAL_URL_A),
        )
        _, violations = ground_package(pkg, ALLOWED_URLS, ALLOWED_TITLES, "proj1", 1)
        assert isinstance(violations, list)
        assert all(isinstance(v, Violation) for v in violations)
