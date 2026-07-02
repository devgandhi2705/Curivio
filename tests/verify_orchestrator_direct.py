"""
Direct orchestrator verification -- Phase A Fix 3 + end-to-end.

Run from repo root:
  python -X utf8 tests/verify_orchestrator_direct.py

Calls run_generation_orchestrator() directly (no HTTP endpoint).
Patches _build_cross_batch_section to capture GenerationContext state
right before each batch's prompt is built, proving batch-2 has real
populated cross-batch fields from batch-1 output.

Evidence reported:
  - Per-batch prompt_tokens and cumulative_prompt_tok
  - gen_ctx field values when batch 2 is entered (spy intercept)
  - Final card counts vs resolve_package_counts()
  - Whether any rate-limit error occurred
"""

from __future__ import annotations

import logging
import sys
import os
import time
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

log_records: list[logging.LogRecord] = []

class _Capture(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        log_records.append(record)

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
root_logger.addHandler(_handler)
root_logger.addHandler(_Capture())


# -- Realistic 8-article fixture -----------------------------------------------
# 6 core + 2 curiosity; realistic fields for ArticleCompressor.

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
        "source_type": "news",
        "domain": "reuters.com",
        "score": 0.92,
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
        "source_type": "industry_report",
        "domain": "pharmabiz.com",
        "score": 0.88,
    },
    {
        "url": "https://nih.gov/pmc/pharma-generics-regulation-india",
        "title": "Regulatory Convergence and Generic Drug Approval Timelines in India",
        "content": (
            "CDSCO approval timelines for generic drugs in India average 18 months, "
            "versus 12 months for FDA-approved generics. A 2023 analysis of 400 ANDAs "
            "found that chemistry and manufacturing controls (CMC) deficiencies account "
            "for 62 percent of complete response letters. Regulatory convergence with "
            "ICH Q11 guidelines is underway."
        ),
        "source_type": "research_paper",
        "domain": "nih.gov",
        "score": 0.85,
    },
    {
        "url": "https://pib.gov.in/pharma-pli-scheme-update-2024",
        "title": "PLI Scheme for Bulk Drugs: 35 Projects Commissioned, Rs 3800 Cr Investment",
        "content": (
            "The Production Linked Incentive (PLI) scheme for bulk drugs has seen 35 "
            "projects commissioned as of Q1 2024, with total investment commitments of "
            "Rs 3,800 crore. The scheme targets 41 APIs across four categories including "
            "fermentation-based products and complex molecules. Incentive outgo is "
            "projected at Rs 695 crore over five years."
        ),
        "source_type": "government",
        "domain": "pib.gov.in",
        "score": 0.90,
    },
    {
        "url": "https://businessstandard.com/sun-pharma-q3-2024-margins",
        "title": "Sun Pharma Q3 Results: US Speciality Business Drives 18% Margin Expansion",
        "content": (
            "Sun Pharmaceutical Industries reported an 18 percent expansion in EBITDA "
            "margins for Q3 FY24, driven by higher revenue from its US speciality "
            "portfolio including Ilumya and Cequa. The company's specialty revenue now "
            "accounts for 38 percent of US sales."
        ),
        "source_type": "market_analysis",
        "domain": "businessstandard.com",
        "score": 0.83,
    },
    {
        "url": "https://medpace.com/india-clinical-trials-growth-2024",
        "title": "India Emerges as Top 3 Clinical Trial Destination After Regulatory Reforms",
        "content": (
            "India has risen to a top-three global clinical trial destination following "
            "2023 regulatory reforms that aligned Indian approval timelines with "
            "simultaneous global trial starts. Patient recruitment costs in India are "
            "40-60 percent lower than the US. Over 1,200 new trials were registered "
            "on ClinicalTrials.gov with Indian sites in 2023."
        ),
        "source_type": "educational",
        "domain": "medpace.com",
        "score": 0.80,
    },
]

CURIOSITY_ARTICLES = [
    {
        "url": "https://chemistryworld.com/aspirin-history-willow-bark",
        "title": "Aspirin's Origin: How a Willow Bark Extract Became the World's First Blockbuster Drug",
        "content": (
            "Aspirin's discovery traces back to Felix Hoffmann at Bayer in 1897, who "
            "acetylated salicylic acid to reduce its gastric side-effects. The compound "
            "had been used for millennia as willow bark extract. The patent war between "
            "Bayer and competitor firms after WWI shaped the modern pharmaceutical "
            "patent system."
        ),
        "source_type": "educational",
        "domain": "chemistryworld.com",
        "score": 0.78,
    },
    {
        "url": "https://scientificamerican.com/antibiotic-resistance-soil-bacteria-2024",
        "title": "Soil Bacteria Have Been Running an Arms Race Against Antibiotics for 40,000 Years",
        "content": (
            "Ancient permafrost cores reveal antibiotic resistance genes in bacteria "
            "predating human antibiotic use by 40,000 years, suggesting resistance is "
            "an intrinsic feature of microbial ecosystems rather than solely an "
            "artifact of clinical use. This reframes how antibiotic stewardship "
            "strategies should be designed."
        ),
        "source_type": "research_paper",
        "domain": "scientificamerican.com",
        "score": 0.76,
    },
]


def main() -> None:
    print("\n" + "="*70)
    print("DIRECT ORCHESTRATOR VERIFICATION -- Phase A Fix 3")
    print("="*70 + "\n")

    # Spy on _build_cross_batch_section to capture gen_ctx state at each batch entry.
    captured_gen_ctx_at_batch: dict[int, dict] = {}
    import backend.services.generation_orchestrator as _orch_mod
    _original_build_cross_batch = _orch_mod._build_cross_batch_section

    def _spy_build_cross_batch(gen_ctx, batch_num: int) -> str:
        captured_gen_ctx_at_batch[batch_num] = {
            "already_generated_titles":    list(gen_ctx.already_generated_titles),
            "already_covered_topics":      list(gen_ctx.already_covered_topics),
            "already_used_frames":         list(gen_ctx.already_used_frames),
            "already_used_primary_urls":   list(gen_ctx.already_used_primary_urls),
            "learning_thread_seed":        gen_ctx.learning_thread_seed,
        }
        return _original_build_cross_batch(gen_ctx, batch_num)

    from backend.services.article_plan_service import resolve_package_counts
    core_count, curiosity_count = resolve_package_counts(8)
    print(f"resolve_package_counts(8) -> core={core_count}, curiosity={curiosity_count}")
    print(f"Articles supplied: {len(CORE_ARTICLES)} core, {len(CURIOSITY_ARTICLES)} curiosity\n")

    error_raised: Exception | None = None
    raw: dict | None = None
    t_start = time.monotonic()

    with patch.object(_orch_mod, "_build_cross_batch_section", _spy_build_cross_batch):
        try:
            from backend.services.generation_orchestrator import run_generation_orchestrator
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
                project_id               = "test-direct-verify",
                intent_profile           = {
                    "persona":       "Analyst",
                    "goal":          "Understand Indian pharma supply chain dynamics",
                    "search_lens":   "Analytical",
                    "primary_focus": "API manufacturing and CDMO sector",
                    "industry_context": "Healthcare / Pharmaceuticals",
                    "intent_summary": "Track structural shifts in Indian pharma competitiveness.",
                },
            )
        except Exception as exc:
            error_raised = exc

    elapsed = time.monotonic() - t_start

    print("\n" + "="*70)
    print("RESULTS")
    print("="*70)

    # -- Error check -----------------------------------------------------------
    if error_raised:
        is_rate_limit = any(
            x in str(error_raised)
            for x in ("429", "413", "rate_limit", "Rate limit", "tokens per minute")
        )
        print(f"\nFAIL -- exception raised:")
        # Truncate to first 400 chars to avoid console flood
        msg = str(error_raised)[:400]
        print(f"  {msg}")
        if is_rate_limit:
            print("  [rate-limit / TPM error]")
        else:
            print("  [non-rate-limit failure]")
    else:
        print("\nPASS -- generation completed without exception.")

    # -- Per-batch token log lines (always show) --------------------------------
    print("\n-- Per-batch token evidence (from log) --")
    orch_records = [
        r for r in log_records
        if "[GENERATION ORCHESTRATOR]" in r.getMessage()
    ]
    for r in orch_records:
        print(f"  {r.getMessage()}")

    # -- Cross-batch context (always show captured spy data) --------------------
    print("\n-- GenerationContext state at _build_cross_batch_section() --")
    if not captured_gen_ctx_at_batch:
        print("  (spy never called -- only 1 batch ran or spy failed)")
    for batch_num in sorted(captured_gen_ctx_at_batch.keys()):
        state = captured_gen_ctx_at_batch[batch_num]
        print(f"\n  Batch {batch_num} entry:")
        for field_name, val in state.items():
            if isinstance(val, list):
                disp = val if val else "[]  <- EMPTY"
            else:
                disp = repr(val) if val else repr(val) + "  <- EMPTY"
            print(f"    {field_name}: {disp}")

    # Key cross-batch assertion: batch 2 must have non-empty fields from batch 1
    batch2_ctx = captured_gen_ctx_at_batch.get(2)
    if batch2_ctx is not None:
        titles_ok = bool(batch2_ctx["already_generated_titles"])
        urls_ok   = bool(batch2_ctx["already_used_primary_urls"])
        topics_ok = bool(batch2_ctx["already_covered_topics"])
        all_ok    = titles_ok and urls_ok and topics_ok
        print(f"\n  Cross-batch populated (batch 2 entry):")
        print(f"    already_generated_titles  non-empty: {'PASS' if titles_ok else 'FAIL'}")
        print(f"    already_used_primary_urls non-empty: {'PASS' if urls_ok   else 'FAIL'}")
        print(f"    already_covered_topics    non-empty: {'PASS' if topics_ok else 'FAIL'}")
        verdict = "PASS -- batch-2 has real batch-1 output in gen_ctx" if all_ok else "FAIL -- gen_ctx fields empty at batch-2 entry"
        print(f"\n  Cross-batch verdict: {verdict}")

    # -- Final card count (if generation succeeded) ----------------------------
    if raw:
        n_core  = len(raw.get("insights", []))
        n_curio = len(raw.get("curiosity_insights", []))
        print(f"\n-- Final package --")
        print(f"  core cards:      {n_core}  (target ~{core_count})")
        print(f"  curiosity cards: {n_curio}  (target ~{curiosity_count})")
        print(f"  package_headline: {raw.get('package_headline', '?')[:80]}")

    print(f"\n  Total wall time: {elapsed:.1f}s")
    print("\n" + "="*70 + "\n")


if __name__ == "__main__":
    main()
