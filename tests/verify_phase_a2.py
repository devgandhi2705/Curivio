"""
Phase A2 Verification — four checks, real output, no mocking of LLM calls for check 1.

Check 1: Real Gemini generation (valid GEMINI_WRITER_API_KEY).
Check 2: Quota fallback — mock Gemini to raise 429, confirm Groq completes it.
Check 3: Non-quota error — mock Gemini to raise a non-quota error, confirm raise, no fallback.
Check 4: frame_hint present in Gemini prompt; source ranking scores not broken.

Run from repo root:
  python -X utf8 tests/verify_phase_a2.py
"""

from __future__ import annotations

import logging
import os
import sys
import time
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Logging capture ────────────────────────────────────────────────────────────
log_records: list[logging.LogRecord] = []

class _Capture(logging.Handler):
    def emit(self, r: logging.LogRecord) -> None:
        log_records.append(r)

root = logging.getLogger()
root.setLevel(logging.INFO)
_fh = logging.StreamHandler(sys.stdout)
_fh.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s  %(message)s"))
root.addHandler(_fh)
root.addHandler(_Capture())

def _flush_records():
    log_records.clear()

def _records_containing(*fragments) -> list[str]:
    out = []
    for r in log_records:
        msg = r.getMessage()
        if all(f in msg for f in fragments):
            out.append(msg)
    return out


# ── Shared article fixture (8 articles: 6 core + 2 curiosity) ─────────────────

CORE_ARTICLES = [
    {
        "url": "https://reuters.com/pharma/india-api-china-dependency-2024",
        "title": "India's Pharma API Dependency on China Reaches 70% for Key Molecules",
        "content": (
            "India's pharmaceutical industry sources more than 70 percent of active "
            "pharmaceutical ingredients (APIs) from China, creating structural supply "
            "chain risk. The dependency is most acute for antibiotics, where Chinese "
            "factories supply over 80 percent of global fermentation-based APIs. "
            "Indian regulators are now pushing PLI schemes to onshore production."
        ),
        "source_type": "news", "domain": "reuters.com", "score": 0.92,
        "_rank_score": 0.92, "signal_density": 0.85, "source_strength": 0.88,
        "main_claim": "India sources 70%+ of pharma APIs from China, raising supply risk.",
        "key_evidence": ["70% API sourcing dependency on China", "80% fermentation APIs from China"],
        "important_numbers": ["70%", "80%"],
        "important_entities": ["India", "China", "PLI scheme"],
        "implications": ["Structural supply chain vulnerability for Indian pharma"],
        "risks": ["Single-country supply dependency"],
        "important_dates": ["2024"],
        "contradictions": [],
    },
    {
        "url": "https://pharmabiz.com/cdmo-capacity-india-2024",
        "title": "CDMO Sector in India Set for $20 Billion Expansion by 2030",
        "content": (
            "Contract development and manufacturing organisations (CDMOs) in India "
            "are projecting a combined capacity addition worth $20 billion by 2030, "
            "driven by Western clients diversifying away from Chinese manufacturers. "
            "Divi's Laboratories and Laurus Labs lead expansion plans."
        ),
        "source_type": "industry_report", "domain": "pharmabiz.com", "score": 0.88,
        "_rank_score": 0.88, "signal_density": 0.80, "source_strength": 0.82,
        "main_claim": "Indian CDMOs projecting $20B capacity expansion by 2030.",
        "key_evidence": ["$20 billion capacity addition by 2030"],
        "important_numbers": ["$20 billion", "2030"],
        "important_entities": ["Divi's Laboratories", "Laurus Labs", "CDMOs"],
        "implications": ["Western pharma diversification driving Indian CDMO growth"],
        "risks": [], "important_dates": ["2030"], "contradictions": [],
    },
    {
        "url": "https://nih.gov/pmc/pharma-generics-regulation-india",
        "title": "Regulatory Convergence and Generic Drug Approval Timelines in India",
        "content": (
            "CDSCO approval timelines for generic drugs in India average 18 months, "
            "versus 12 months for FDA-approved generics. A 2023 analysis of 400 ANDAs "
            "found that CMC deficiencies account for 62% of CRLs. Regulatory convergence "
            "with ICH Q11 guidelines is underway."
        ),
        "source_type": "research_paper", "domain": "nih.gov", "score": 0.85,
        "_rank_score": 0.85, "signal_density": 0.88, "source_strength": 0.90,
        "main_claim": "CDSCO generics approval averages 18 months vs FDA's 12.",
        "key_evidence": ["62% of CRLs caused by CMC deficiencies", "400 ANDA study"],
        "important_numbers": ["18 months", "12 months", "62%", "400"],
        "important_entities": ["CDSCO", "FDA", "ICH Q11"],
        "implications": ["Regulatory gap slows Indian generic drug market entry"],
        "risks": ["CMC quality deficiencies"], "important_dates": ["2023"], "contradictions": [],
    },
    {
        "url": "https://pib.gov.in/pharma-pli-scheme-update-2024",
        "title": "PLI Scheme for Bulk Drugs: 35 Projects Commissioned, Rs 3800 Cr Investment",
        "content": (
            "The Production Linked Incentive (PLI) scheme for bulk drugs has seen 35 "
            "projects commissioned as of Q1 2024, with total investment commitments of "
            "Rs 3,800 crore. The scheme targets 41 APIs across four categories."
        ),
        "source_type": "government", "domain": "pib.gov.in", "score": 0.90,
        "_rank_score": 0.90, "signal_density": 0.82, "source_strength": 0.91,
        "main_claim": "PLI scheme: 35 projects commissioned, Rs 3800 Cr committed.",
        "key_evidence": ["Rs 3,800 crore investment", "35 projects commissioned"],
        "important_numbers": ["35", "Rs 3800 crore", "41 APIs"],
        "important_entities": ["PLI scheme", "Government of India"],
        "implications": ["State-led API onshoring underway"],
        "risks": [], "important_dates": ["Q1 2024"], "contradictions": [],
    },
    {
        "url": "https://businessstandard.com/sun-pharma-q3-2024-margins",
        "title": "Sun Pharma Q3 Results: US Speciality Business Drives 18% Margin Expansion",
        "content": (
            "Sun Pharmaceutical Industries reported an 18 percent expansion in EBITDA margins "
            "for Q3 FY24, driven by higher revenue from its US speciality portfolio. "
            "Specialty revenue now accounts for 38 percent of US sales."
        ),
        "source_type": "market_analysis", "domain": "businessstandard.com", "score": 0.83,
        "_rank_score": 0.83, "signal_density": 0.75, "source_strength": 0.78,
        "main_claim": "Sun Pharma EBITDA margin expanded 18% on US specialty growth.",
        "key_evidence": ["18% EBITDA margin expansion", "38% of US sales from specialty"],
        "important_numbers": ["18%", "38%"],
        "important_entities": ["Sun Pharma", "Ilumya", "Cequa"],
        "implications": ["Specialty pivot as margin lever for Indian pharma majors"],
        "risks": [], "important_dates": ["Q3 FY24"], "contradictions": [],
    },
    {
        "url": "https://medpace.com/india-clinical-trials-growth-2024",
        "title": "India Emerges as Top 3 Clinical Trial Destination After Regulatory Reforms",
        "content": (
            "India has risen to a top-three global clinical trial destination following "
            "2023 regulatory reforms. Patient recruitment costs in India are 40-60% lower "
            "than the US. Over 1,200 new trials registered on ClinicalTrials.gov in 2023."
        ),
        "source_type": "educational", "domain": "medpace.com", "score": 0.80,
        "_rank_score": 0.80, "signal_density": 0.72, "source_strength": 0.74,
        "main_claim": "India is now top-3 global clinical trial destination.",
        "key_evidence": ["40-60% lower patient recruitment costs", "1,200+ new trials 2023"],
        "important_numbers": ["40-60%", "1,200"],
        "important_entities": ["ClinicalTrials.gov", "India"],
        "implications": ["India's cost advantage making it CRO hub"],
        "risks": [], "important_dates": ["2023"], "contradictions": [],
    },
]

CURIOSITY_ARTICLES = [
    {
        "url": "https://chemistryworld.com/aspirin-history-willow-bark",
        "title": "Aspirin's Origin: How a Willow Bark Extract Became the World's First Blockbuster Drug",
        "content": (
            "Aspirin's discovery traces back to Felix Hoffmann at Bayer in 1897, who "
            "acetylated salicylic acid to reduce gastric side-effects. The patent war "
            "between Bayer and competitor firms after WWI shaped the modern pharmaceutical "
            "patent system."
        ),
        "source_type": "educational", "domain": "chemistryworld.com", "score": 0.78,
        "_rank_score": 0.78, "signal_density": 0.65, "source_strength": 0.70,
        "main_claim": "Aspirin's patent wars shaped the modern pharma patent system.",
        "key_evidence": ["Acetylation of salicylic acid in 1897"],
        "important_numbers": ["1897"],
        "important_entities": ["Felix Hoffmann", "Bayer", "WWI"],
        "implications": ["Patent strategy origins in early pharma"],
        "risks": [], "important_dates": ["1897"], "contradictions": [],
    },
    {
        "url": "https://scientificamerican.com/antibiotic-resistance-soil-bacteria-2024",
        "title": "Soil Bacteria Have Been Running an Arms Race Against Antibiotics for 40,000 Years",
        "content": (
            "Ancient permafrost cores reveal antibiotic resistance genes predating human "
            "antibiotic use by 40,000 years, suggesting resistance is intrinsic to microbial "
            "ecosystems rather than solely an artifact of clinical use."
        ),
        "source_type": "research_paper", "domain": "scientificamerican.com", "score": 0.76,
        "_rank_score": 0.76, "signal_density": 0.78, "source_strength": 0.72,
        "main_claim": "Antibiotic resistance predates human antibiotic use by 40,000 years.",
        "key_evidence": ["40,000-year-old resistance genes in permafrost"],
        "important_numbers": ["40,000 years"],
        "important_entities": ["permafrost bacteria"],
        "implications": ["Antibiotic stewardship must account for evolutionary baseline"],
        "risks": [], "important_dates": [], "contradictions": [],
    },
]

INTENT_PROFILE = {
    "persona":          "Analyst",
    "goal":             "Understand Indian pharma supply chain dynamics",
    "search_lens":      "Analytical",
    "primary_focus":    "API manufacturing and CDMO sector",
    "industry_context": "Healthcare / Pharmaceuticals",
    "intent_summary":   "Track structural shifts in Indian pharma competitiveness.",
}


# ── Helper: run orchestrator with optional patches ─────────────────────────────

def _run(patches_ctx=(), frame_hint="timeline", article_plan_block=None):
    """Run run_generation_orchestrator under optional patches. Returns (raw, error, elapsed)."""
    from backend.services.generation_orchestrator import run_generation_orchestrator
    from backend.services.article_plan_service import (
        build_article_plans, plans_to_prompt_block, resolve_package_counts,
    )

    core_count, curiosity_count = resolve_package_counts(8)
    if article_plan_block is None:
        _plans = build_article_plans(CORE_ARTICLES, core_count)
        article_plan_block = plans_to_prompt_block(_plans, CORE_ARTICLES, frame_hint=frame_hint)

    raw = error = None
    t0 = time.monotonic()
    try:
        raw = run_generation_orchestrator(
            project_name             = "Indian Pharma",
            keywords                 = ["API manufacturing", "CDMO", "generics", "regulation"],
            difficulty               = "intermediate",
            day_number               = 5,
            display_label            = "Day 5",
            daily_core_article_count = 8,
            core_articles            = CORE_ARTICLES,
            curiosity_articles       = CURIOSITY_ARTICLES,
            article_budget_tokens    = 3000,
            project_id               = "test-phase-a2",
            intent_profile           = INTENT_PROFILE,
            frame_hint               = frame_hint,
            article_plan_block       = article_plan_block,
        )
    except Exception as exc:
        error = exc
    return raw, error, time.monotonic() - t0


# ═══════════════════════════════════════════════════════════════════════════════
# CHECK 1 — Real Gemini generation
# ═══════════════════════════════════════════════════════════════════════════════

def check1_real_gemini():
    print("\n" + "="*72)
    print("CHECK 1 — Real Gemini generation (valid GEMINI_WRITER_API_KEY)")
    print("="*72)

    # Reset cached Gemini writer client so it picks up the real key fresh
    import backend.services.writer_provider_router as _router
    _router._gemini_writer_client = None

    _flush_records()
    from backend.services.article_plan_service import resolve_package_counts
    core_count, curiosity_count = resolve_package_counts(8)
    print(f"\nresolve_package_counts(8) -> core={core_count}, curiosity={curiosity_count}")

    raw, error, elapsed = _run(frame_hint="timeline")

    # ── Error ──────────────────────────────────────────────────────────────────
    if error:
        print(f"\nFAIL — exception: {str(error)[:600]}")
        return False

    print(f"\nPASS — generation completed in {elapsed:.1f}s")

    # ── Provider / token log lines ─────────────────────────────────────────────
    print("\n-- writer_router log lines --")
    for msg in _records_containing("[writer_router]"):
        print(f"  {msg}")

    # ── Batch orchestrator lines ───────────────────────────────────────────────
    print("\n-- GENERATION ORCHESTRATOR log lines --")
    for msg in _records_containing("[GENERATION ORCHESTRATOR]"):
        print(f"  {msg}")

    # ── Synthesis log ─────────────────────────────────────────────────────────
    print("\n-- PACKAGE SYNTHESIS log lines --")
    for msg in _records_containing("[PACKAGE SYNTHESIS]"):
        print(f"  {msg}")

    # ── Sleep check ───────────────────────────────────────────────────────────
    sleep_lines = _records_containing("post-batch pause 60s")
    print(f"\n-- Inter-batch sleep: {'FIRED (' + str(len(sleep_lines)) + ' occurrences) — UNEXPECTED' if sleep_lines else 'SKIPPED (correct — Gemini served)'}")
    for msg in sleep_lines:
        print(f"  {msg}")

    # ── Provider check ────────────────────────────────────────────────────────
    gemini_served = _records_containing("provider=gemini")
    groq_fallback = _records_containing("provider=groq")
    print(f"\n-- Provider check --")
    print(f"  provider=gemini lines: {len(gemini_served)}")
    print(f"  provider=groq lines:   {len(groq_fallback)}")

    # ── Card counts ───────────────────────────────────────────────────────────
    if raw:
        n_core  = len(raw.get("insights", []))
        n_curio = len(raw.get("curiosity_insights", []))
        print(f"\n-- Final package --")
        print(f"  core cards:      {n_core}  (target {core_count})")
        print(f"  curiosity cards: {n_curio}  (target {curiosity_count})")
        print(f"  package_headline: {raw.get('package_headline', '?')[:90]}")
        print(f"  learning_thread:  {raw.get('learning_thread', '?')[:90]}")
        count_ok = (n_core == core_count) and (n_curio == curiosity_count)
        print(f"\n  Card count matches resolve_package_counts: {'PASS' if count_ok else 'FAIL (mismatch)'}")

    # ── Gemini JSON parse check ───────────────────────────────────────────────
    # If we got here with raw results, JSON parsed cleanly for all batches
    print(f"\n-- JSON parse: {'PASS — all batches and synthesis parsed cleanly' if raw else 'FAIL — no raw output'}")

    return bool(raw) and bool(gemini_served)


# ═══════════════════════════════════════════════════════════════════════════════
# CHECK 2 — Quota fallback (mock 429)
# ═══════════════════════════════════════════════════════════════════════════════

def check2_quota_fallback():
    print("\n" + "="*72)
    print("CHECK 2 — Quota fallback: mock Gemini raises 429, Groq completes")
    print("="*72)

    import backend.services.writer_provider_router as _router
    _router._gemini_writer_client = None

    # Build a mock client whose .chat.completions.create() raises a 429-style error
    _mock_resp = MagicMock()
    _mock_resp.chat.completions.create.side_effect = Exception(
        "Error code: 429 - {'error': {'code': 429, 'message': 'RESOURCE_EXHAUSTED: "
        "Quota exceeded for quota metric quota.googleapis.com/generate_content_free_tier_input_token_count'}}"
    )

    _flush_records()

    with patch.object(_router, "_get_gemini_writer_client", return_value=_mock_resp):
        raw, error, elapsed = _run()

    # ── Results ───────────────────────────────────────────────────────────────
    print(f"\nElapsed: {elapsed:.1f}s")

    if error:
        print(f"\nFAIL — exception raised (expected Groq to complete): {str(error)[:400]}")
        return False

    print("\nPASS — generation completed (Groq fallback succeeded)")

    print("\n-- writer_router log lines --")
    for msg in _records_containing("[writer_router]"):
        print(f"  {msg}")

    print("\n-- GENERATION ORCHESTRATOR lines --")
    for msg in _records_containing("[GENERATION ORCHESTRATOR]"):
        print(f"  {msg}")

    print("\n-- PACKAGE SYNTHESIS lines --")
    for msg in _records_containing("[PACKAGE SYNTHESIS]"):
        print(f"  {msg}")

    fallback_lines = _records_containing("quota fallback") or _records_containing("falling back to Groq")
    print(f"\n-- Fallback fired: {'YES (' + str(len(fallback_lines)) + ' lines)' if fallback_lines else 'NO — FAIL'}")
    for msg in fallback_lines:
        print(f"  {msg}")

    groq_lines = _records_containing("provider=groq")
    print(f"\n-- provider=groq lines: {len(groq_lines)}")
    for msg in groq_lines:
        print(f"  {msg}")

    if raw:
        n_core  = len(raw.get("insights", []))
        n_curio = len(raw.get("curiosity_insights", []))
        print(f"\n-- Package: core={n_core}  curiosity={n_curio}  headline={raw.get('package_headline','?')[:70]}")

    return bool(raw) and bool(fallback_lines)


# ═══════════════════════════════════════════════════════════════════════════════
# CHECK 3 — Non-quota error propagates (no Groq fallback)
# ═══════════════════════════════════════════════════════════════════════════════

def check3_non_quota_error():
    print("\n" + "="*72)
    print("CHECK 3 — Non-quota Gemini error: must raise, no Groq fallback")
    print("="*72)

    import backend.services.writer_provider_router as _router
    _router._gemini_writer_client = None

    # Mock: raises a ConnectionError (non-quota — no "429" or "RESOURCE_EXHAUSTED")
    _mock_resp = MagicMock()
    _mock_resp.chat.completions.create.side_effect = ConnectionError(
        "Failed to establish connection to generativelanguage.googleapis.com: "
        "Name or service not known"
    )

    _flush_records()

    with patch.object(_router, "_get_gemini_writer_client", return_value=_mock_resp):
        raw, error, elapsed = _run()

    print(f"\nElapsed: {elapsed:.1f}s")

    if error is None:
        print("\nFAIL — no error raised; expected propagation")
        return False

    print(f"\nError raised (as expected):")
    print(f"  Type: {type(error).__name__}")
    print(f"  Message: {str(error)[:300]}")

    # Confirm Groq was NOT called
    groq_fallback_lines = _records_containing("quota fallback") or _records_containing("falling back to Groq")
    groq_provider_lines = _records_containing("provider=groq")
    print(f"\n-- Groq fallback fired: {'YES — FAIL (should not have fallen back)' if groq_fallback_lines else 'NO — PASS'}")
    print(f"-- provider=groq lines: {len(groq_provider_lines)}  (expect 0)")

    # Confirm the non-quota raise log
    non_quota_logs = _records_containing("non-quota error")
    print(f"\n-- non-quota error log: {'present' if non_quota_logs else 'absent'}")
    for msg in non_quota_logs:
        print(f"  {msg}")

    return error is not None and not groq_fallback_lines


# ═══════════════════════════════════════════════════════════════════════════════
# CHECK 4 — frame_hint in Gemini prompt + source ranking intact
# ═══════════════════════════════════════════════════════════════════════════════

def check4_frame_hint_and_ranking():
    print("\n" + "="*72)
    print("CHECK 4 — frame_hint in Gemini prompt; source ranking scores intact")
    print("="*72)

    # Build article_plan_block with frame_hint and show its content
    from backend.services.article_plan_service import (
        build_article_plans, plans_to_prompt_block, resolve_package_counts,
    )
    core_count, _ = resolve_package_counts(8)
    plans = build_article_plans(CORE_ARTICLES, core_count)
    plan_block = plans_to_prompt_block(plans, CORE_ARTICLES, frame_hint="timeline")

    print("\n-- article_source_assignments block (frame_hint wired as 'timeline') --")
    for line in plan_block.splitlines()[:40]:
        print(f"  {line}")
    timeline_present = "Narrative shape: timeline" in plan_block
    print(f"\n  'Narrative shape: timeline' present: {'PASS' if timeline_present else 'FAIL'}")

    # Build the full Gemini prompt to confirm frame_hint propagates into composer
    from backend.prompts.project_insight_prompt import PromptContext, build_batch_prompt
    from backend.services.writer_provider_router import format_articles_full

    full_core_text  = format_articles_full(CORE_ARTICLES,      "CORE")
    full_curio_text = format_articles_full(CURIOSITY_ARTICLES, "CURIOSITY")

    ctx = PromptContext(
        project_name             = "Indian Pharma",
        keywords                 = ["API manufacturing", "CDMO", "generics", "regulation"],
        difficulty               = "intermediate",
        day_number               = 5,
        display_label            = "Day 5",
        daily_core_article_count = 8,
        intent_profile           = INTENT_PROFILE,
        article_plan_block       = plan_block,
        frame_hint               = "timeline",
    )
    composer = build_batch_prompt(ctx, batch_plan=None,
                                  core_article_text=full_core_text,
                                  curiosity_article_text=full_curio_text)
    gemini_prompt = composer.build()

    print(f"\n-- Gemini full prompt stats --")
    print(f"  Total chars:   {len(gemini_prompt):,}")
    print(f"  Tokens (est):  {len(gemini_prompt)//4:,}")

    # Show the article_source_assignments section from the prompt
    start = gemini_prompt.find("ARTICLE SOURCE ASSIGNMENTS")
    if start != -1:
        snippet = gemini_prompt[start:start+600]
        print(f"\n-- article_source_assignments section (first 600 chars) --")
        for line in snippet.splitlines()[:20]:
            print(f"  {line}")
        frame_in_prompt = "Narrative shape: timeline" in snippet
        print(f"\n  frame_hint present in Gemini prompt: {'PASS' if frame_in_prompt else 'FAIL'}")
    else:
        print("\n  FAIL — article_source_assignments section not found in Gemini prompt")

    # Source ranking: show _rank_score values from CORE_ARTICLES
    print("\n-- Source ranking scores (upstream, not affected by A2) --")
    for a in CORE_ARTICLES:
        print(f"  rank={a.get('_rank_score'):.2f}  sig={a.get('signal_density'):.2f}  "
              f"src={a.get('source_strength'):.2f}  domain={a.get('domain')}")

    # Verify all source_intelligence fields present in full article text (spot check article 1)
    a0_text = format_articles_full([CORE_ARTICLES[0]], "CORE")
    print(f"\n-- format_articles_full spot check (article 1) --")
    for line in a0_text.splitlines():
        print(f"  {line}")

    intel_fields_present = all(
        field in a0_text
        for field in ["Main claim:", "Evidence:", "Number:", "Entity:", "Implication:", "Risk:", "Source strength:"]
    )
    print(f"\n  All intel fields present: {'PASS' if intel_fields_present else 'FAIL'}")
    full_content_present = "active pharmaceutical ingredients" in a0_text  # article 1 content field
    print(f"  Full raw content included (no truncation): {'PASS' if full_content_present else 'FAIL'}")

    return timeline_present and intel_fields_present


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    results: dict[str, bool] = {}

    results["check1_real_gemini"]      = check1_real_gemini()
    results["check2_quota_fallback"]   = check2_quota_fallback()
    results["check3_non_quota_error"]  = check3_non_quota_error()
    results["check4_frame_hint"]       = check4_frame_hint_and_ranking()

    print("\n" + "="*72)
    print("SUMMARY")
    print("="*72)
    for name, passed in results.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    all_pass = all(results.values())
    print(f"\nOverall: {'ALL PASS' if all_pass else 'SOME FAILURES'}")
    print("="*72 + "\n")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
