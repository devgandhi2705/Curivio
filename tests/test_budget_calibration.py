"""
Phase 9.3.3B — Budget Calibration Tests

Tests A–G proving:
  A. No hardcoded overhead constant (_NON_ARTICLE_OVERHEAD = 4500) remains.
  B. Overhead is measured from real prompt sections, not a fixed number.
  C. Article budget decreases when instruction overhead increases.
  D. Compression levels activate under budget pressure.
  E. Day-1000 probe overhead leaves room for articles within provider limit.
  F. 10-article package formatted with calibrated budget stays under provider limit.
  G. Backward compat — make_daily_package_composer works without new params.

Run:
    pytest tests/test_budget_calibration.py -v --noconftest
"""

from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.prompts.project_insight_prompt import make_daily_package_composer
from backend.prompts.article_compressor import ArticleCompressor, LEVEL_NAMES

_GROQ_PROVIDER_BUDGET = 10_500   # Groq on_demand: 12K TPM × 87.5%
_BUDGET_SAFETY_BUFFER = 300
_MIN_ARTICLE_BUDGET   = 800
_ARTICLE_SECTIONS     = frozenset({"core_articles", "curiosity_articles"})


def _probe_overhead(
    project_name="Test", keywords=None, difficulty="intermediate",
    day_number=1, knowledge_state=None,
    intelligence_context=None, intent_profile=None,
) -> int:
    """Build empty-article probe composer and return non-article token count."""
    p = make_daily_package_composer(
        project_name=project_name,
        keywords=keywords or ["test"],
        difficulty=difficulty,
        day_number=day_number,
        display_label=f"Day {day_number}",
        core_articles=[],
        curiosity_articles=[],
        knowledge_state=knowledge_state,
        intelligence_context=intelligence_context,
        intent_profile=intent_profile,
        article_budget_tokens=0,
    )
    return sum(s.tokens for s in p._sections if s.name not in _ARTICLE_SECTIONS)


def _article_budget(overhead: int, effective: int = _GROQ_PROVIDER_BUDGET) -> int:
    return max(_MIN_ARTICLE_BUDGET, effective - overhead - _BUDGET_SAFETY_BUFFER)


# ── Test A: No hardcoded overhead constant ────────────────────────────────────

def test_A_no_hardcoded_overhead_constant():
    src = Path("backend/services/project_service.py").read_text(encoding="utf-8")
    assert "_NON_ARTICLE_OVERHEAD" not in src, (
        "_NON_ARTICLE_OVERHEAD constant must be removed from project_service.py"
    )
    assert "= 4500" not in src, (
        "Magic number 4500 must not appear as an assignment in project_service.py"
    )


# ── Test B: Overhead is measured, not fixed ───────────────────────────────────

def test_B_overhead_varies_with_knowledge_state():
    base_overhead = _probe_overhead()

    large_ks_overhead = _probe_overhead(knowledge_state={
        "covered_topics":   [f"topic number {i} in depth" for i in range(20)],
        "active_topics":    [f"currently active topic {i}" for i in range(8)],
        "knowledge_gaps":   [f"identified knowledge gap area {i}" for i in range(10)],
        "recent_topics":    [f"recent coverage of topic {i}" for i in range(8)],
        "covered_entities": [f"entity name mention {i}" for i in range(15)],
        "covered_keywords": [f"important keyword {i}" for i in range(20)],
    })

    assert large_ks_overhead > base_overhead, (
        f"Overhead with large knowledge_state ({large_ks_overhead}) must exceed "
        f"base overhead ({base_overhead}) — overhead must be measured, not fixed"
    )


def test_B_overhead_varies_with_intent_profile():
    base_overhead = _probe_overhead()

    intent_overhead = _probe_overhead(intent_profile={
        "persona":           "Senior policy analyst at the World Bank",
        "goal":              "understand multilateral trade framework implications",
        "industry_context":  "international economics and trade policy",
        "primary_focus":     "WTO compliance and tariff structures",
        "search_lens":       "policy_analytical",
        "intent_summary":    (
            "Analyst wants to understand how new trade frameworks affect "
            "developing economy debt obligations and FX exposure across sectors."
        ),
    })

    assert intent_overhead > base_overhead, (
        f"Overhead with intent_profile ({intent_overhead}) must exceed "
        f"base ({base_overhead}) — intent_profile section must be counted"
    )


# ── Test C: Article budget decreases when overhead grows ─────────────────────

def test_C_article_budget_shrinks_with_larger_overhead():
    base_overhead = _probe_overhead()
    large_overhead = _probe_overhead(knowledge_state={
        "covered_topics":   [f"topic {i} covered in prior sessions" for i in range(20)],
        "active_topics":    [f"active learning thread {i}" for i in range(8)],
        "knowledge_gaps":   [f"gap in understanding domain {i}" for i in range(10)],
        "recent_topics":    [f"recent topic {i}" for i in range(8)],
        "covered_entities": [f"named entity {i}" for i in range(15)],
        "covered_keywords": [f"domain keyword {i}" for i in range(20)],
    })

    budget_base  = _article_budget(base_overhead)
    budget_large = _article_budget(large_overhead)

    assert budget_large < budget_base, (
        f"Larger overhead ({large_overhead} vs {base_overhead}) must reduce "
        f"article budget ({budget_large} vs {budget_base})"
    )


# ── Test D: Compression activates under budget pressure ───────────────────────

def test_D_compression_activates_under_pressure():
    AC = ArticleCompressor()
    articles = [
        {
            "title":    f"Article {i}: detailed sector analysis with depth",
            "url":      f"https://publisher{i}.com/article",
            "content":  "Dense content with many facts, figures, and context. " * 40,
            "main_claim":     f"Finding {i}: significant result with {i * 8 + 5}% impact.",
            "key_evidence":   [f"Study of {i * 100 + 200} firms shows {i * 8 + 5}% effect."],
            "important_numbers": [f"{i * 8 + 5}%", f"{i * 100 + 200} firms"],
            "important_entities": [f"Organization {i}", f"Institute {i}"],
            "implications":   [f"This implies structural change in sector {i}."],
            "_rank_score":    max(0.25, 0.90 - i * 0.08),
            "signal_density": max(0.25, 0.85 - i * 0.07),
            "source_strength": 0.70,
        }
        for i in range(8)
    ]

    # Tight budget: 8 richly-formatted articles in 500 tokens
    _, meta_tight = AC.format_intel_batch(articles, "CORE", article_budget_tokens=500)
    levels_tight  = {m["level_selected"] for m in meta_tight}

    assert levels_tight != {"FULL"}, (
        f"Expected compression level diversity under tight budget (500 tok / 8 articles). "
        f"All articles stayed at FULL — compression never activated. Levels: {levels_tight}"
    )

    # Verify rank ordering holds: top article level >= richness of bottom
    level_order = {
        "FULL": 0, "DETAILED": 1, "SMART": 1,
        "INSIGHT": 2, "COMPACT": 2, "CLAIM": 3, "MINIMAL": 3,
    }
    top_rank    = level_order.get(meta_tight[0]["level_selected"], 0)
    bottom_rank = level_order.get(meta_tight[-1]["level_selected"], 0)
    assert top_rank <= bottom_rank, (
        f"Top article ({meta_tight[0]['level_selected']}) must be at least as rich "
        f"as bottom article ({meta_tight[-1]['level_selected']})"
    )


def test_D_generous_budget_allows_full_level():
    AC = ArticleCompressor()
    articles = [
        {
            "title": f"Article {i}",
            "url":   f"https://src{i}.com",
            "content": "Content. " * 50,
            "main_claim": f"Key claim {i}.",
            "_rank_score": 0.80,
            "signal_density": 0.75,
        }
        for i in range(5)
    ]
    _, meta = AC.format_intel_batch(articles, "CORE", article_budget_tokens=5000)
    assert all(m["level_selected"] == "FULL" for m in meta), (
        f"Generous budget should yield all FULL: {[m['level_selected'] for m in meta]}"
    )


# ── Test E: Day-1000 overhead leaves room for articles ───────────────────────

def test_E_day1000_overhead_leaves_article_budget():
    overhead = _probe_overhead(
        project_name="Globalization Economics",
        keywords=["trade", "tariff", "GDP", "WTO", "exports", "imports"],
        difficulty="advanced",
        day_number=1000,
        knowledge_state={
            "covered_topics":   [f"topic {i}" for i in range(20)],
            "active_topics":    [f"active thread {i}" for i in range(8)],
            "knowledge_gaps":   [f"gap area {i}" for i in range(10)],
            "recent_topics":    [f"recent {i}" for i in range(8)],
            "covered_entities": [f"entity {i}" for i in range(15)],
            "covered_keywords": [f"keyword {i}" for i in range(20)],
        },
        intent_profile={
            "persona":          "Trade economist",
            "goal":             "master multilateral trade systems",
            "industry_context": "international trade",
            "primary_focus":    "WTO dispute resolution",
            "search_lens":      "analytical",
            "intent_summary":   "Deep understanding of trade law and policy.",
        },
    )

    article_budget = _article_budget(overhead, _GROQ_PROVIDER_BUDGET)

    assert article_budget >= _MIN_ARTICLE_BUDGET, (
        f"Day-1000 overhead ({overhead} tok) consumed too much budget — "
        f"article_budget ({article_budget}) dropped below minimum ({_MIN_ARTICLE_BUDGET})"
    )
    assert overhead < _GROQ_PROVIDER_BUDGET - _MIN_ARTICLE_BUDGET - _BUDGET_SAFETY_BUFFER, (
        f"Day-1000 overhead ({overhead}) exceeds available headroom "
        f"({_GROQ_PROVIDER_BUDGET - _MIN_ARTICLE_BUDGET - _BUDGET_SAFETY_BUFFER})"
    )


# ── Test F: 10-article package under provider budget ─────────────────────────

def test_F_10_article_calibrated_package_under_provider_budget():
    overhead = _probe_overhead(
        project_name="AI Agents",
        keywords=["LLM", "agent", "reasoning", "tools"],
        difficulty="intermediate",
        day_number=42,
    )
    article_budget = _article_budget(overhead, _GROQ_PROVIDER_BUDGET)

    AC = ArticleCompressor()
    arts = [
        {
            "title":    f"Article {i}: comprehensive analysis of topic area",
            "url":      f"https://publisher{i}.com/analysis-2025",
            "content":  "Dense technical content with statistics and research data. " * 25,
            "main_claim":     f"Core finding {i}: {i * 7 + 10}% improvement in metric X.",
            "key_evidence":   [
                f"Study {i} measured {i * 7 + 10}% gain across {i * 50 + 100} cases.",
                f"Replicated by {i + 2} independent labs with consistent results.",
            ],
            "important_numbers":  [f"{i * 7 + 10}%", f"{i * 50 + 100} cases"],
            "important_entities": [f"Lab {i}", f"Institute {i}", "MIT"],
            "implications":       [f"Result {i} changes deployment calculus for enterprises."],
            "_rank_score":        max(0.30, 0.90 - i * 0.06),
            "signal_density":     max(0.30, 0.85 - i * 0.05),
            "source_strength":    0.75,
        }
        for i in range(10)
    ]

    core_tok  = int(article_budget * 0.70)
    curio_tok = article_budget - core_tok
    core_txt,  core_meta  = AC.format_intel_batch(arts[:8], "CORE",      core_tok)
    curio_txt, curio_meta = AC.format_intel_batch(arts[8:], "CURIOSITY", curio_tok)

    article_tokens = (len(core_txt) + len(curio_txt)) // 4
    total          = overhead + article_tokens + _BUDGET_SAFETY_BUFFER

    assert total <= _GROQ_PROVIDER_BUDGET, (
        f"Total prompt ({total} tok) exceeds Groq provider budget ({_GROQ_PROVIDER_BUDGET}): "
        f"overhead={overhead} articles={article_tokens} safety={_BUDGET_SAFETY_BUFFER}"
    )


# ── Test G: Backward compatibility ───────────────────────────────────────────

def test_G_composer_works_without_new_params():
    """Old callers omitting core_article_text/curiosity_article_text still work."""
    composer = make_daily_package_composer(
        project_name="Test Project",
        keywords=["test", "learning"],
        difficulty="intermediate",
        day_number=1,
        display_label="Day 1",
        core_articles=[],
        curiosity_articles=[],
        # core_article_text and curiosity_article_text intentionally absent
    )
    assert composer is not None
    section_names = {s.name for s in composer._sections}
    assert "core_articles"      in section_names
    assert "curiosity_articles" in section_names
    assert "output_schema"      in section_names
    assert "source_grounding"   in section_names


def test_G_composer_accepts_pre_formatted_text():
    """New path: caller passes pre-formatted text and composer uses it directly."""
    pre_core  = "[CORE 1]\nSource-ID: CORE-1\nTitle: Pre-formatted\nURL: https://test.com\n"
    pre_curio = "[CURIOSITY 1]\nSource-ID: CURIOSITY-1\nTitle: Curious\nURL: https://q.com\n"

    composer = make_daily_package_composer(
        project_name="Test",
        keywords=["test"],
        difficulty="beginner",
        day_number=1,
        display_label="Day 1",
        core_articles=[],
        curiosity_articles=[],
        core_article_text=pre_core,
        curiosity_article_text=pre_curio,
    )

    core_section = next(s for s in composer._sections if s.name == "core_articles")
    assert pre_core.strip() in core_section.content, (
        "Pre-formatted core text must appear in core_articles section"
    )
    curio_section = next(s for s in composer._sections if s.name == "curiosity_articles")
    assert pre_curio.strip() in curio_section.content, (
        "Pre-formatted curiosity text must appear in curiosity_articles section"
    )


def test_G_probe_composer_has_no_article_content():
    """Probe composer (empty articles) must have placeholder, not real article content."""
    composer = make_daily_package_composer(
        project_name="Test",
        keywords=["test"],
        difficulty="intermediate",
        day_number=5,
        display_label="Day 5",
        core_articles=[],
        curiosity_articles=[],
        article_budget_tokens=0,
    )
    core_section = next(s for s in composer._sections if s.name == "core_articles")
    # Empty articles produce the "NO ARTICLES RETRIEVED" placeholder
    assert "NO ARTICLES" in core_section.content or len(core_section.content) < 200, (
        f"Probe with empty articles should have minimal core_articles content, "
        f"got {len(core_section.content)} chars"
    )
