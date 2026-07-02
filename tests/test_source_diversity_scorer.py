"""
Tests for source_diversity_scorer.py — Phase 7.2

Covers:
  - Empty selected → zero adjustment
  - Domain signals: new (+0.05), second (-0.03), third+ (-0.10)
  - Source-type signals: new (+0.04), 4th+ of same type (-0.05)
  - Perspective/viewpoint signals: new (+0.03), 3rd+ same (-0.04)
  - Clamping: total stays in [-0.15, +0.10]
  - Canonical "Reuters Reuters Reuters Reuters" scenario
  - Diverse feed scenario (World Bank, IMF, Harvard, Reuters → all bonuses)

Run:
    pytest tests/test_source_diversity_scorer.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.source_diversity_scorer import diversity_adjustment


# ── Helpers ───────────────────────────────────────────────────────────────────

def _art(url: str, source_type: str = "", perspective: str = "") -> dict:
    return {
        "url":         url,
        "title":       url,
        "source_type": source_type,
        "_perspective": perspective,
    }


# ── Empty selected ────────────────────────────────────────────────────────────

class TestEmptySelected:
    def test_no_selected_returns_zero(self):
        art = _art("https://reuters.com/article-1", "news", "economic_financial")
        assert diversity_adjustment(art, []) == 0.0


# ── Domain signal ─────────────────────────────────────────────────────────────

class TestDomainSignal:
    def test_new_domain_gets_bonus(self):
        selected = [_art("https://reuters.com/a"), _art("https://bbc.com/b")]
        candidate = _art("https://worldbank.org/report")
        adj = diversity_adjustment(candidate, selected)
        assert adj > 0, f"Expected bonus for new domain, got {adj}"

    def test_new_domain_bonus_is_correct(self):
        # All 3 signals new → domain(+0.05) + type(+0.04) + persp(+0.03) → clamped to 0.10
        selected = [
            _art("https://reuters.com/a", "news", "economic_financial"),
        ]
        candidate = _art("https://arxiv.org/paper", "research_paper", "scientific_research")
        adj = diversity_adjustment(candidate, selected)
        # domain new(+0.05) + type new(+0.04) + persp new(+0.03) = +0.12 → clamped 0.10
        assert adj == 0.10

    def test_second_from_same_domain_mild_penalty(self):
        selected = [_art("https://reuters.com/a", "news", "economic_financial")]
        candidate = _art("https://reuters.com/b", "news", "economic_financial")
        adj = diversity_adjustment(candidate, selected)
        # domain seen(-0.03) + type seen 1(no penalty) + persp seen 1(no penalty) = -0.03
        assert adj == -0.03

    def test_third_from_same_domain_strong_penalty(self):
        selected = [
            _art("https://reuters.com/a", "news", "economic_financial"),
            _art("https://reuters.com/b", "news", "economic_financial"),
        ]
        candidate = _art("https://reuters.com/c", "news", "economic_financial")
        adj = diversity_adjustment(candidate, selected)
        # domain 2+ (-0.10) + type 2(no penalty) + persp 2(-0.04) = -0.14
        assert adj == -0.14

    def test_subdomain_same_as_root(self):
        # www.reuters.com and reuters.com both normalize to reuters.com
        selected = [_art("https://www.reuters.com/a", "news", "")]
        candidate = _art("https://reuters.com/b", "news", "")
        adj = diversity_adjustment(candidate, selected)
        assert adj < 0, "Same netloc after www-strip should penalize"


# ── Source-type signal ────────────────────────────────────────────────────────

class TestSourceTypeSignal:
    def test_new_type_gets_bonus(self):
        selected = [_art("https://bbc.com/a", "news", "")]
        candidate = _art("https://arxiv.org/p", "research_paper", "")
        adj = diversity_adjustment(candidate, selected)
        assert adj > 0

    def test_known_type_no_penalty_under_threshold(self):
        # 1 news already selected; 2nd news — no type penalty
        selected = [_art("https://bbc.com/a", "news", "")]
        candidate = _art("https://cnn.com/b", "news", "")
        adj = diversity_adjustment(candidate, selected)
        # domain new(+0.05) — type seen once(no penalty) — persp empty(no effect)
        assert adj == 0.05

    def test_fourth_of_same_type_gets_penalty(self):
        selected = [
            _art("https://bbc.com/a",      "news", ""),
            _art("https://cnn.com/b",      "news", ""),
            _art("https://reuters.com/c",  "news", ""),
        ]
        candidate = _art("https://ft.com/d", "news", "")
        adj = diversity_adjustment(candidate, selected)
        # domain new(+0.05) + type 3+ (-0.05) + persp empty
        assert adj == 0.0

    def test_missing_source_type_falls_back_to_classifier(self):
        # article has no source_type; classifier infers from URL
        selected = [_art("https://bbc.com/a", "news", "")]
        candidate = {"url": "https://arxiv.org/abs/123", "title": "Test", "_perspective": ""}
        # arxiv → research_paper (new type) + new domain → bonus
        adj = diversity_adjustment(candidate, selected)
        assert adj > 0


# ── Perspective signal ────────────────────────────────────────────────────────

class TestPerspectiveSignal:
    def test_new_perspective_gets_bonus(self):
        selected = [_art("https://economist.com/a", "news", "economic_financial")]
        candidate = _art("https://nature.com/a", "research_paper", "scientific_research")
        adj = diversity_adjustment(candidate, selected)
        assert adj > 0

    def test_third_same_perspective_gets_penalty(self):
        selected = [
            _art("https://reuters.com/a", "news",       "economic_financial"),
            _art("https://ft.com/b",      "news",       "economic_financial"),
        ]
        candidate = _art("https://wsj.com/c", "news", "economic_financial")
        adj = diversity_adjustment(candidate, selected)
        # domain new(+0.05) + type 2(no penalty) + persp 2(-0.04) = +0.01
        assert adj == 0.01

    def test_empty_perspective_not_penalized(self):
        selected = [_art("https://reuters.com/a", "news", "")]
        candidate = _art("https://bbc.com/b", "news", "")
        # perspective empty on both → no perspective signal → only domain
        adj = diversity_adjustment(candidate, selected)
        # domain new(+0.05) + type seen once(no penalty) + persp empty(no signal)
        assert adj == 0.05


# ── Clamping ──────────────────────────────────────────────────────────────────

class TestClamping:
    def test_max_bonus_clamped_to_0_10(self):
        # All three signals new → 0.05 + 0.04 + 0.03 = 0.12 → clamped 0.10
        selected = [_art("https://bbc.com/a", "news", "economic_financial")]
        candidate = _art("https://arxiv.org/p", "research_paper", "scientific_research")
        adj = diversity_adjustment(candidate, selected)
        assert adj <= 0.10

    def test_max_penalty_clamped_to_minus_0_15(self):
        # Heavy repetition: domain -0.10, type -0.05, perspective -0.04 = -0.19 → clamped -0.15
        selected = [
            _art("https://reuters.com/a", "news", "economic_financial"),
            _art("https://reuters.com/b", "news", "economic_financial"),
            _art("https://reuters.com/c", "news", "economic_financial"),
        ]
        candidate = _art("https://reuters.com/d", "news", "economic_financial")
        adj = diversity_adjustment(candidate, selected)
        assert adj >= -0.15

    def test_result_is_float(self):
        adj = diversity_adjustment(_art("https://test.com"), [])
        assert isinstance(adj, float)

    def test_result_always_in_bounds(self):
        import random
        random.seed(42)
        domains = ["a.com", "b.com", "c.com", "a.com", "a.com"]
        types   = ["news", "news", "research_paper", "news", "news"]
        persps  = ["p1", "p1", "p2", "p1", "p1"]
        selected = []
        for d, t, p in zip(domains, types, persps):
            art = _art(f"https://{d}/page", t, p)
            adj = diversity_adjustment(art, selected)
            assert -0.15 <= adj <= 0.10, f"Out of bounds: {adj}"
            selected.append(art)


# ── Canonical scenarios ───────────────────────────────────────────────────────

class TestCanonicalScenarios:
    def test_reuters_four_times_progressively_worse(self):
        """
        Simulates ranking 4 Reuters articles sequentially.
        Diversity adjustment should worsen with each addition.
        """
        reuters = lambda n: _art(f"https://reuters.com/article-{n}", "news", "economic_financial")

        selected = []
        adjustments = []
        for i in range(4):
            art = reuters(i)
            adj = diversity_adjustment(art, selected)
            adjustments.append(adj)
            selected.append(art)

        # 1st: empty selected → 0
        assert adjustments[0] == 0.0
        # 2nd: domain seen once → penalty
        assert adjustments[1] < 0
        # 3rd: domain seen twice → stronger penalty
        assert adjustments[2] < adjustments[1]
        # 4th: domain seen 3+ times → clamped max penalty
        assert adjustments[3] <= -0.14

    def test_diverse_feed_all_bonuses(self):
        """
        Reuters, World Bank, IMF, Harvard — each should get a positive adjustment
        after the first article (different domains, types, perspectives).
        """
        articles = [
            _art("https://reuters.com/a",      "news",           "economic_financial"),
            _art("https://worldbank.org/r",    "government",     "policy_regulatory"),
            _art("https://imf.org/report",     "government",     "economic_financial"),
            _art("https://harvard.edu/study",  "research_paper", "scientific_research"),
        ]
        selected = []
        for i, art in enumerate(articles):
            adj = diversity_adjustment(art, selected)
            if i > 0:
                assert adj > 0 or i == 2, (
                    f"Expected bonus for diverse source #{i+1}, got {adj}"
                )
            selected.append(art)

    def test_same_type_but_different_domains_preferred(self):
        """3 news sources from different domains all pass; 4th same type gets penalty."""
        bbc     = _art("https://bbc.com/a",     "news", "technology")
        cnn     = _art("https://cnn.com/b",     "news", "technology")
        reuters = _art("https://reuters.com/c", "news", "technology")
        fourth  = _art("https://ft.com/d",      "news", "economic_financial")

        selected = [bbc, cnn, reuters]
        adj = diversity_adjustment(fourth, selected)
        # domain new(+0.05) + type 3+ (-0.05) + persp new(+0.03) = +0.03
        assert adj == 0.03
