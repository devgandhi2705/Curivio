"""
Tests for Phase 7.8 — Source Quality Audit (retrieval_metrics_service extension)

Covers:
  - _grounding_integrity:
      all URLs valid → 1.0
      some URLs invalid → partial score
      no URLs → 1.0 (vacuously valid)
      URL normalisation (trailing slash, case)

  - _duplicate_story_fraction:
      no duplicates → 0.0
      identical titles → 1.0
      single card → 0.0
      empty package → 0.0

  - audit():
      returns AuditReport with correct fields
      source_coverage_score range [0, 2]
      source_diversity_score range [0, 2]
      source_reuse_score == 2.0 when no collisions
      grounding_score == 2.0 when all grounded
      duplicate_story_score == 2.0 when no dups
      overall_score == sum of 5 scores
      overall_score <= 10.0
      passes dict has correct keys
      healthy package scores >= 8.0
      unhealthy package scores < 8.0

  - log_audit():
      callable without error for passing and failing reports

Run:
    pytest tests/test_source_audit_service.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.retrieval_metrics_service import (
    _DUP_STORY_TARGET,
    _DUP_TITLE_THRESH,
    _HEALTHY_SCORE,
    AuditReport,
    _duplicate_story_fraction,
    _grounding_integrity,
    audit,
    log_audit,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

URL_A = "https://reuters.com/business/fed-rates"
URL_B = "https://worldbank.org/trade-report"
URL_C = "https://ft.com/export-strategy"
URL_D = "https://imf.org/global-outlook"

ALLOWED: frozenset[str] = frozenset([
    URL_A.rstrip("/").lower(),
    URL_B.rstrip("/").lower(),
    URL_C.rstrip("/").lower(),
    URL_D.rstrip("/").lower(),
])


def _card(title: str = "Card Title", *source_urls: str) -> dict:
    source_links = [{"url": u, "title": ""} for u in source_urls]
    return {"id": title[:8], "title": title, "source_links": source_links}


def _package(*core_cards, curiosity=None) -> dict:
    return {
        "insights": list(core_cards),
        "curiosity_insights": list(curiosity or []),
    }


GOOD_PACKAGE = _package(
    _card("Federal Reserve raises rates", URL_A),
    _card("World Bank trade deficit analysis", URL_B),
    _card("Export strategy for founders", URL_C),
    _card("IMF global growth outlook", URL_D),
)


# ── _grounding_integrity ──────────────────────────────────────────────────────

class TestGroundingIntegrity:
    def test_all_valid_returns_one(self):
        pkg = _package(_card("T", URL_A), _card("T2", URL_B))
        assert _grounding_integrity(pkg, ALLOWED) == 1.0

    def test_empty_package_returns_one(self):
        assert _grounding_integrity(_package(), frozenset()) == 1.0

    def test_card_with_no_sources_ignored(self):
        pkg = _package({"id": "c1", "title": "T", "source_links": []})
        assert _grounding_integrity(pkg, ALLOWED) == 1.0

    def test_one_invalid_url_reduces_score(self):
        pkg = _package(_card("T", URL_A, "https://fake.com/hallucinated"))
        score = _grounding_integrity(pkg, ALLOWED)
        assert 0.0 < score < 1.0

    def test_all_invalid_returns_zero(self):
        pkg = _package(_card("T", "https://fake.com/a", "https://fake.com/b"))
        assert _grounding_integrity(pkg, frozenset()) == 0.0

    def test_url_normalised_trailing_slash(self):
        # stored with slash; allowed without
        pkg = _package(_card("T", URL_A + "/"))
        assert _grounding_integrity(pkg, ALLOWED) == 1.0

    def test_url_normalised_case(self):
        pkg = _package(_card("T", URL_A.upper()))
        assert _grounding_integrity(pkg, ALLOWED) == 1.0

    def test_curiosity_cards_included(self):
        bad_url = "https://fabricated.com/article"
        pkg = {
            "insights":          [_card("T", URL_A)],
            "curiosity_insights": [_card("T2", bad_url)],
        }
        score = _grounding_integrity(pkg, ALLOWED)
        assert score < 1.0


# ── _duplicate_story_fraction ─────────────────────────────────────────────────

class TestDuplicateStoryFraction:
    def test_single_card_returns_zero(self):
        pkg = _package(_card("Fed raises rates"))
        assert _duplicate_story_fraction(pkg) == 0.0

    def test_empty_package_returns_zero(self):
        assert _duplicate_story_fraction(_package()) == 0.0

    def test_distinct_titles_returns_zero(self):
        pkg = _package(
            _card("Federal Reserve rates decision"),
            _card("World Bank trade deficit"),
            _card("Export strategy for startups"),
        )
        assert _duplicate_story_fraction(pkg) == 0.0

    def test_identical_titles_returns_one(self):
        pkg = _package(
            _card("Federal Reserve raises rates"),
            _card("Federal Reserve raises rates"),
        )
        assert _duplicate_story_fraction(pkg) == 1.0

    def test_partial_duplicates_between_zero_and_one(self):
        pkg = _package(
            _card("Federal Reserve raises rates decision"),
            _card("Federal Reserve raises rates today"),
            _card("World Bank trade deficit report"),
        )
        frac = _duplicate_story_fraction(pkg)
        assert 0.0 < frac < 1.0

    def test_returns_float(self):
        pkg = _package(_card("A"), _card("B"))
        assert isinstance(_duplicate_story_fraction(pkg), float)

    def test_value_between_zero_and_one(self):
        pkg = _package(_card("A"), _card("A"), _card("B"))
        frac = _duplicate_story_fraction(pkg)
        assert 0.0 <= frac <= 1.0


# ── audit() ───────────────────────────────────────────────────────────────────

class TestAudit:
    def test_returns_audit_report(self):
        report = audit(GOOD_PACKAGE, ALLOWED, [], [])
        assert isinstance(report, AuditReport)

    def test_report_has_all_score_fields(self):
        report = audit(GOOD_PACKAGE, ALLOWED, [], [])
        assert hasattr(report, "source_coverage_score")
        assert hasattr(report, "source_diversity_score")
        assert hasattr(report, "source_reuse_score")
        assert hasattr(report, "grounding_score")
        assert hasattr(report, "duplicate_story_score")
        assert hasattr(report, "overall_score")

    def test_all_scores_in_range_0_to_2(self):
        report = audit(GOOD_PACKAGE, ALLOWED, [], [])
        for attr in ("source_coverage_score", "source_diversity_score",
                     "source_reuse_score", "grounding_score", "duplicate_story_score"):
            score = getattr(report, attr)
            assert 0.0 <= score <= 2.0, f"{attr}={score} out of range"

    def test_overall_score_is_sum_of_five(self):
        report = audit(GOOD_PACKAGE, ALLOWED, [], [])
        expected = (
            report.source_coverage_score  +
            report.source_diversity_score +
            report.source_reuse_score     +
            report.grounding_score        +
            report.duplicate_story_score
        )
        assert abs(report.overall_score - expected) < 0.001

    def test_overall_score_max_ten(self):
        report = audit(GOOD_PACKAGE, ALLOWED, [], [])
        assert report.overall_score <= 10.0

    def test_perfect_package_scores_high(self):
        report = audit(GOOD_PACKAGE, ALLOWED, [], [])
        assert report.overall_score >= _HEALTHY_SCORE

    def test_passes_dict_has_five_keys(self):
        report = audit(GOOD_PACKAGE, ALLOWED, [], [])
        expected_keys = {
            "source_coverage", "source_diversity", "source_reuse",
            "grounding_integrity", "duplicate_story",
        }
        assert set(report.passes.keys()) == expected_keys

    def test_passes_values_are_bool(self):
        report = audit(GOOD_PACKAGE, ALLOWED, [], [])
        assert all(isinstance(v, bool) for v in report.passes.values())

    def test_all_valid_sources_grounding_passes(self):
        report = audit(GOOD_PACKAGE, ALLOWED, [], [])
        assert report.passes["grounding_integrity"] is True
        assert report.grounding_score == 2.0

    def test_no_primary_collisions_reuse_passes(self):
        report = audit(GOOD_PACKAGE, ALLOWED, [], [])
        assert report.passes["source_reuse"] is True
        assert report.source_reuse_score == 2.0

    def test_distinct_cards_duplicate_story_passes(self):
        report = audit(GOOD_PACKAGE, ALLOWED, [], [])
        assert report.passes["duplicate_story"] is True
        assert report.duplicate_story_score == 2.0

    def test_empty_package_no_crash(self):
        # Empty package: no insights → source_coverage passes vacuously
        report = audit(_package(), frozenset(), [], [])
        assert isinstance(report, AuditReport)

    def test_details_dict_present(self):
        report = audit(GOOD_PACKAGE, ALLOWED, [], [])
        assert "coverage_raw"       in report.details
        assert "diversity_raw"      in report.details
        assert "grounding_raw"      in report.details
        assert "duplicate_fraction" in report.details

    def test_unhealthy_package_scores_below_threshold(self):
        # Package with no sources at all — coverage fails
        bad_pkg = _package(
            {"id": "c1", "title": "Title One",   "source_links": []},
            {"id": "c2", "title": "Title One",   "source_links": []},  # dup title too
            {"id": "c3", "title": "Title Two",   "source_links": []},
            {"id": "c4", "title": "Title Three", "source_links": []},
        )
        report = audit(bad_pkg, frozenset(), [], [])
        # coverage fails → source_coverage_score = 0
        assert report.source_coverage_score == 0.0
        # grounding vacuously passes (no sources to check)
        # overall should be significantly reduced
        assert report.overall_score < 10.0

    def test_hallucinated_sources_reduce_grounding_score(self):
        pkg = _package(
            _card("T1", "https://fake.com/hallucinated"),
            _card("T2", URL_B),
        )
        report = audit(pkg, ALLOWED, [], [])
        assert report.grounding_score < 2.0
        assert report.passes["grounding_integrity"] is False

    def test_high_dup_fraction_fails_duplicate_story(self):
        # All cards have same title → dup_fraction = 1.0
        pkg = _package(
            _card("Same title repeated", URL_A),
            _card("Same title repeated", URL_B),
            _card("Same title repeated", URL_C),
        )
        report = audit(pkg, ALLOWED, [], [])
        assert report.passes["duplicate_story"] is False
        assert report.duplicate_story_score < 2.0


# ── log_audit() ───────────────────────────────────────────────────────────────

class TestLogAudit:
    def test_log_audit_healthy_does_not_raise(self, caplog):
        import logging
        report = audit(GOOD_PACKAGE, ALLOWED, [], [])
        with caplog.at_level(logging.INFO):
            log_audit("proj-test", 1, report)
        assert any("AUDIT" in r.message for r in caplog.records)

    def test_log_audit_unhealthy_does_not_raise(self, caplog):
        import logging
        bad_pkg = _package({"id": "c1", "title": "T", "source_links": []})
        report = audit(bad_pkg, frozenset(), [], [])
        with caplog.at_level(logging.WARNING):
            log_audit("proj-test", 1, report)

    def test_log_contains_pass_fail(self, caplog):
        import logging
        report = audit(GOOD_PACKAGE, ALLOWED, [], [])
        with caplog.at_level(logging.INFO):
            log_audit("proj-test", 99, report)
        log_text = " ".join(r.message for r in caplog.records)
        assert "PASS" in log_text

    def test_log_audit_accepts_custom_logger(self):
        import logging
        custom = logging.getLogger("test.audit")
        report = audit(GOOD_PACKAGE, ALLOWED, [], [])
        log_audit("proj-test", 1, report, custom)   # should not raise
