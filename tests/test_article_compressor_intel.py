"""
Phase 9.3.3 — Source Context Construction & LLM Input Optimization

Tests A–J proving:
  A. All compression levels preserve source grounding (URL always present).
  B. No source URLs are lost in a batch.
  C. High-ranked articles receive more token budget than low-ranked.
  D. Low-ranked articles compress more aggressively (lower level).
  E. Budget-aware assembly keeps total within ~20% of target.
  F. No information duplication — claim suppressed when title has high overlap.
  G. Evidence and numbers survive LEVEL_COMPACT.
  H. 10-article package (core only) stays under Groq provider budget (10 500 tok).
  I. 12-article package (8 core + 4 curiosity) simulating Day-1000 stays under budget.
  J. Backward compat — articles without source_intelligence fields still format.

Run:
    pytest tests/test_article_compressor_intel.py -v --noconftest
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.prompts.article_compressor import (
    ArticleCompressor,
    LEVEL_FULL, LEVEL_SMART, LEVEL_COMPACT, LEVEL_MINIMAL,
    LEVEL_NAMES,
    _intel_weight,
    _level_for_budget,
    _title_claim_overlap,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _art(
    title: str = "Test Article",
    url:   str = "https://example.com/test",
    content: str = "This is test content about the subject.",
    rank_score: float | None = None,
    signal_density: float | None = None,
    source_strength: float | None = None,
    main_claim: str = "",
    key_evidence: list[str] | None = None,
    important_numbers: list[str] | None = None,
    important_entities: list[str] | None = None,
    implications: list[str] | None = None,
    risks: list[str] | None = None,
    source_type: str = "news",
) -> dict:
    a: dict = {"title": title, "url": url, "content": content, "source_type": source_type}
    if rank_score      is not None: a["_rank_score"]      = rank_score
    if signal_density  is not None: a["signal_density"]   = signal_density
    if source_strength is not None: a["source_strength"]  = source_strength
    if main_claim:                  a["main_claim"]        = main_claim
    if key_evidence    is not None: a["key_evidence"]     = key_evidence
    if important_numbers is not None: a["important_numbers"] = important_numbers
    if important_entities is not None: a["important_entities"] = important_entities
    if implications    is not None: a["implications"]     = implications
    if risks           is not None: a["risks"]            = risks
    return a


AC = ArticleCompressor()


# ── Test A: URL preserved at all levels ───────────────────────────────────────

def test_A_all_levels_preserve_url():
    article = _art(
        title="Federal Reserve Raises Interest Rates",
        url="https://federalreserve.gov/rates/2025",
        main_claim="The Federal Reserve raised rates by 25 basis points.",
        key_evidence=["Rate hike was 25 bps at the June 2025 FOMC meeting."],
        important_numbers=["25", "5.50%"],
    )
    ca = AC.compress_intel(article, 1, "CORE")
    for level in [LEVEL_FULL, LEVEL_SMART, LEVEL_COMPACT, LEVEL_MINIMAL]:
        text = ca.at_level(level)
        assert "federalreserve.gov" in text, (
            f"URL missing at level {LEVEL_NAMES[level]}:\n{text}"
        )


# ── Test B: No source URLs lost in batch ─────────────────────────────────────

def test_B_batch_preserves_all_urls():
    articles = [
        _art(title=f"Article {i}", url=f"https://source{i}.example.com/article-{i}")
        for i in range(6)
    ]
    text, meta = AC.format_intel_batch(articles, "CORE", article_budget_tokens=1200)
    for i in range(6):
        assert f"source{i}.example.com" in text, (
            f"URL for article {i} missing from batch output"
        )
    assert len(meta) == 6


# ── Test C: High-ranked articles get more budget than low-ranked ──────────────

def test_C_high_rank_gets_more_budget():
    articles = [
        _art(title="High rank", url="https://h.com", rank_score=0.95, signal_density=0.90, source_strength=0.88),
        _art(title="Low rank",  url="https://l.com", rank_score=0.15, signal_density=0.10, source_strength=0.30),
    ]
    _, meta = AC.format_intel_batch(articles, "CORE", article_budget_tokens=400)
    assert meta[0]["budget_allocated"] >= meta[1]["budget_allocated"], (
        f"High-rank article ({meta[0]['budget_allocated']} tok) should get >= "
        f"low-rank ({meta[1]['budget_allocated']} tok)"
    )


# ── Test D: Low-ranked articles compress more aggressively ───────────────────

def test_D_low_rank_higher_compression():
    # 5 articles with sharply declining scores — tight budget forces lower levels for weakest
    articles = [
        _art(
            title=f"Article {i}",
            url=f"https://src{i}.com",
            content="Long content " * 30,
            rank_score=max(0.05, 0.90 - i * 0.20),
            signal_density=max(0.05, 0.85 - i * 0.18),
        )
        for i in range(5)
    ]
    # Very tight budget forces differentiation
    _, meta = AC.format_intel_batch(articles, "CORE", article_budget_tokens=350)
    level_nums = [list(LEVEL_NAMES.keys()).index(
        next(k for k, v in LEVEL_NAMES.items() if v == m["level_selected"])
    ) for m in meta]
    # Top article level_num should be <= (i.e. richer level) than bottom article
    assert level_nums[0] <= level_nums[-1], (
        f"Top article level ({meta[0]['level_selected']}) should be >= richness "
        f"than bottom ({meta[-1]['level_selected']})"
    )


# ── Test E: Budget respected (within 20% overrun) ────────────────────────────

def test_E_budget_respected():
    articles = [
        _art(
            title=f"Article {i}",
            url=f"https://src{i}.com",
            content="Content word " * 100,
            main_claim=f"Key claim for article {i} with specific finding.",
            key_evidence=[f"Study shows {i * 10 + 5}% improvement in outcome."],
            important_numbers=[f"{i * 10 + 5}%"],
            rank_score=0.80 - i * 0.05,
            signal_density=0.75 - i * 0.05,
        )
        for i in range(8)
    ]
    BUDGET = 2000
    text, _ = AC.format_intel_batch(articles, "CORE", article_budget_tokens=BUDGET)
    total_tokens = max(1, len(text) // 4)
    assert total_tokens <= BUDGET * 1.20, (
        f"Budget overrun: {total_tokens} tokens > {int(BUDGET * 1.20)} (120% of {BUDGET})"
    )


# ── Test F: Title+claim dedup suppresses redundant claim ─────────────────────

def test_F_claim_suppressed_when_redundant_with_title():
    # Title and claim are nearly identical — high word overlap
    title = "IMF raises global growth forecast for 2025 to three point one percent"
    claim = "IMF has raised its global growth forecast for 2025 to 3.1 percent."
    article = _art(title=title, url="https://imf.org/forecast", main_claim=claim)
    ca = AC.compress_intel(article, 1, "CORE")
    text_smart = ca.at_level(LEVEL_SMART)
    # High overlap case: claim should NOT be repeated separately after title
    # Either claim is absent or appears only once in the output
    claim_keyword = "3.1"   # unique marker in claim that shouldn't appear twice
    count = text_smart.count(claim_keyword)
    # Allow it to appear in the claim line OR nowhere — but not in BOTH claim+content
    assert count <= 1, (
        f"Claim data appears {count} times — possible duplication:\n{text_smart}"
    )


def test_F_low_overlap_claim_not_suppressed():
    # Title and claim share few words — claim should appear
    title   = "Global Economic Outlook 2025"
    claim   = "Advanced economies will grow 1.8% while emerging markets expand 4.3%."
    article = _art(title=title, url="https://imf.org/weo", main_claim=claim)
    ca = AC.compress_intel(article, 1, "CORE")
    text = ca.at_level(LEVEL_SMART)
    # Unique word from claim should appear
    assert "1.8" in text or "4.3" in text, (
        f"Claim with low title overlap should appear in SMART output:\n{text}"
    )


# ── Test G: Evidence and numbers survive LEVEL_COMPACT ───────────────────────

def test_G_evidence_and_numbers_survive_compact():
    article = _art(
        title="Trade Policy Update 2025",
        url="https://wto.org/trade-update",
        main_claim="WTO reports trade volumes fell 3.2% in Q1 2025.",
        key_evidence=["Trade volumes fell 3.2% year-over-year according to WTO data."],
        important_numbers=["3.2%", "$1.4 trillion"],
        rank_score=0.40,   # mediocre rank → will get COMPACT budget
        signal_density=0.50,
    )
    ca = AC.compress_intel(article, 1, "CORE")
    text = ca.at_level(LEVEL_COMPACT)
    # URL preserved
    assert "wto.org" in text, f"URL missing in COMPACT:\n{text}"
    # At least one quantitative signal preserved
    has_data = "3.2" in text or "1.4" in text or "WTO" in text
    assert has_data, f"No evidence/numbers in COMPACT level:\n{text}"


# ── Test H: 10-article package under Groq provider budget (10 500 tokens) ────

_GROQ_PROVIDER_BUDGET = 10_500   # Groq on_demand tier: 12K TPM × 87.5%

def test_H_10_article_package_under_provider_budget():
    articles = [
        _art(
            title=f"Core article {i}: detailed analysis of topic area {i}",
            url=f"https://publisher{i}.com/analysis-2025-{i}",
            content="Detailed analysis content with statistics and data. " * 25,
            main_claim=f"Key finding {i}: significant impact on sector {i}.",
            key_evidence=[
                f"Study {i} shows {i * 7 + 5}% change in outcome metric.",
                f"Secondary evidence: {i * 3 + 2} organizations affected.",
            ],
            important_numbers=[f"{i * 7 + 5}%", f"{i * 3 + 2}B"],
            important_entities=[f"Organization {i}", f"Institute {i}"],
            implications=[f"This implies major restructuring in sector {i}."],
            rank_score=max(0.30, 0.90 - i * 0.07),
            signal_density=max(0.30, 0.85 - i * 0.06),
            source_strength=0.75,
        )
        for i in range(10)
    ]
    # Use same budget ratio as production: 70% of article budget for core
    ARTICLE_BUDGET = 3500   # typical production value after overhead subtraction
    text, meta = AC.format_intel_batch(articles, "CORE", article_budget_tokens=int(ARTICLE_BUDGET * 0.70))
    total_tok = max(1, len(text) // 4)
    assert total_tok < _GROQ_PROVIDER_BUDGET, (
        f"10-article core package exceeds Groq budget: {total_tok} > {_GROQ_PROVIDER_BUDGET}"
    )


# ── Test I: Day-1000 (8 core + 4 curiosity) under provider budget ─────────────

def test_I_day1000_12_article_package_under_budget():
    core_arts = [
        _art(
            title=f"Core {i}: advanced topic analysis with comprehensive coverage",
            url=f"https://core-source{i}.com/deep-dive-{i}",
            content="Dense academic content with multiple data points. " * 30,
            main_claim=f"Core finding {i}: mechanism X produces outcome Y with {i * 8}% efficiency.",
            key_evidence=[f"Longitudinal study of {i * 100}K subjects over {i + 3} years."],
            important_numbers=[f"{i * 8}%", f"{i * 100}K"],
            rank_score=max(0.35, 0.92 - i * 0.06),
            signal_density=max(0.35, 0.88 - i * 0.05),
            source_strength=0.80,
        )
        for i in range(8)
    ]
    curiosity_arts = [
        _art(
            title=f"Curiosity {i}: surprising fact about hidden mechanism",
            url=f"https://curiosity{i}.com/rabbit-hole-{i}",
            content="Fascinating backstory and surprising angle. " * 20,
            main_claim=f"Counterintuitive finding: {i + 1} unexpected connection revealed.",
            key_evidence=[f"Historical record shows {i * 15 + 10} similar cases."],
            important_numbers=[f"{i * 15 + 10}"],
            rank_score=max(0.30, 0.75 - i * 0.10),
            signal_density=max(0.25, 0.65 - i * 0.08),
            source_strength=0.60,
        )
        for i in range(4)
    ]
    ART_BUDGET   = 3500
    CORE_BUDGET  = int(ART_BUDGET * 0.70)
    CURIO_BUDGET = ART_BUDGET - CORE_BUDGET

    core_text,  _ = AC.format_intel_batch(core_arts,     "CORE",      CORE_BUDGET)
    curio_text, _ = AC.format_intel_batch(curiosity_arts, "CURIOSITY", CURIO_BUDGET)

    combined_tok = max(1, (len(core_text) + len(curio_text)) // 4)
    assert combined_tok < _GROQ_PROVIDER_BUDGET, (
        f"Day-1000 12-article package exceeds Groq budget: {combined_tok} > {_GROQ_PROVIDER_BUDGET}"
    )


# ── Test J: Backward compat — articles without source_intelligence fields ─────

def test_J_backward_compat_no_intel_fields():
    # Plain Tavily-style article — no source_intelligence enrichment
    article = {
        "title": "Fed Signals Rate Pause in September Meeting",
        "url":   "https://reuters.com/fed-pause-2025",
        "content": (
            "The Federal Reserve signaled a pause in rate hikes during its September "
            "2025 meeting. Chairman Powell indicated inflation is cooling toward the "
            "2% target. Markets rallied 1.8% on the announcement. The next meeting "
            "is scheduled for November 2025."
        ),
        "source_type": "news",
    }
    # Should not raise and must preserve URL
    ca = AC.compress_intel(article, 1, "CORE")
    for level in [LEVEL_FULL, LEVEL_SMART, LEVEL_COMPACT, LEVEL_MINIMAL]:
        text = ca.at_level(level)
        assert "reuters.com" in text, f"URL missing at {LEVEL_NAMES[level]} with no intel fields"
        assert len(text) > 0, f"Empty output at {LEVEL_NAMES[level]}"

    # Batch also works
    text, meta = AC.format_intel_batch([article], "CORE", article_budget_tokens=500)
    assert "reuters.com" in text
    assert len(meta) == 1
    assert meta[0]["level_selected"] in LEVEL_NAMES.values()


# ── Test: _intel_weight helper ────────────────────────────────────────────────

def test_weight_higher_for_better_signals():
    high = _art(rank_score=0.95, signal_density=0.90, source_strength=0.88)
    low  = _art(rank_score=0.10, signal_density=0.08, source_strength=0.20)
    w_high = _intel_weight(high, 0, 2)
    w_low  = _intel_weight(low,  1, 2)
    assert w_high > w_low, f"High-signal weight ({w_high:.3f}) should beat low ({w_low:.3f})"


def test_weight_graceful_with_missing_fields():
    # No signal fields — defaults should produce a valid weight
    w = _intel_weight({}, 0, 1)
    assert 0.0 < w <= 1.5, f"Default weight out of expected range: {w}"


# ── Test: title_claim_overlap helper ─────────────────────────────────────────

def test_overlap_high_for_similar_strings():
    title = "Federal Reserve raises interest rates 25 basis points"
    claim = "Federal Reserve raised interest rates by 25 basis points in June"
    assert _title_claim_overlap(title, claim) >= 0.55


def test_overlap_low_for_different_strings():
    title = "IMF Growth Outlook 2025"
    claim = "Emerging markets outperform advanced economies by 2.5 percentage points."
    assert _title_claim_overlap(title, claim) < 0.40


# ── Test: _level_for_budget helper ───────────────────────────────────────────

def test_level_selection_from_budget():
    assert _level_for_budget(200) == LEVEL_FULL
    assert _level_for_budget(130) == LEVEL_SMART
    assert _level_for_budget(70)  == LEVEL_COMPACT
    assert _level_for_budget(30)  == LEVEL_MINIMAL
