"""
Phase 8 Rendering Diversity Verification
=========================================
Verifies that the Phase 8 block-based article system produces structural diversity.

Modes
-----
  LIVE   — calls Groq LLM with test fixtures (requires GROQ_API_KEY)
  SIM    — structural simulation based on prompt heuristics (no API needed)

Run
---
  python scripts/verify_phase8_diversity.py           # auto-detect
  python scripts/verify_phase8_diversity.py --sim     # force simulation
  python scripts/verify_phase8_diversity.py --live    # force live (errors if no key)

Success targets
---------------
  1. No single block combination > 40% of articles
  2. >= 6 distinct block types across all articles
  3. >= 5 distinct block combinations across all articles
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import Counter
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ── Test fixtures ─────────────────────────────────────────────────────────────

TOPICS = [
    {
        "name": "Global Trade Economics",
        "keywords": ["trade", "tariffs", "WTO", "supply chain"],
        "articles": [
            {"title": "WTO Issues New Trade Dispute Framework", "url": "https://wto.org/trade-framework", "source_type": "government", "content": "The WTO issued updated dispute resolution procedures affecting 164 member states. New rules target digital trade barriers."},
            {"title": "OECD Economic Outlook 2025", "url": "https://oecd.org/outlook-2025", "source_type": "research_paper", "content": "OECD projections show GDP growth slowing in G7 economies. Inflation expected to decline but remain above targets."},
            {"title": "Goldman Trade Desk: Tariff Impact Report", "url": "https://gs.com/tariff-report", "source_type": "market_analysis", "content": "Goldman estimates 15% tariff increase adds 0.8pp to US inflation. Supply chain relocation accelerates."},
            {"title": "Reuters: EU-US Trade Summit Collapses", "url": "https://reuters.com/eu-us-summit", "source_type": "news", "content": "Talks stalled over agricultural subsidies. Both sides signalled willingness to resume in Q3."},
        ],
    },
    {
        "name": "AI Research Frontiers",
        "keywords": ["LLMs", "transformers", "inference", "alignment"],
        "articles": [
            {"title": "Scaling Laws for Neural Language Models", "url": "https://arxiv.org/abs/2001.08361", "source_type": "research_paper", "content": "Empirical analysis shows model performance scales predictably with compute, data, and parameters. Optimal allocation formula derived."},
            {"title": "OpenAI Safety Team: RLHF Limitations", "url": "https://openai.com/research/rlhf-limits", "source_type": "company_blog", "content": "RLHF reduces harmful outputs but introduces reward hacking. Team proposes constitutional AI alternatives."},
            {"title": "MIT OCW: Transformer Architecture Deep Dive", "url": "https://ocw.mit.edu/transformers", "source_type": "educational", "content": "Attention mechanism explained from first principles. Includes complexity analysis and positional encoding variants."},
            {"title": "The Verge: AI Chip Shortage Hits Inference Market", "url": "https://theverge.com/ai-chips", "source_type": "news", "content": "NVIDIA H100 allocation tightens as inference demand surges. AMD and custom silicon alternatives emerging."},
        ],
    },
    {
        "name": "Pharmaceutical Regulation",
        "keywords": ["FDA", "EMA", "clinical trials", "drug approval"],
        "articles": [
            {"title": "FDA Guidance: Adaptive Trial Design 2025", "url": "https://fda.gov/adaptive-trials", "source_type": "government", "content": "Updated guidance permits interim analyses with pre-specified adaptation rules. Requires independent DSMB review."},
            {"title": "EMA Regulatory Update: Biosimilars Q2 2025", "url": "https://ema.europa.eu/biosimilars-q2", "source_type": "regulatory", "content": "Three new biosimilars approved under expedited pathway. Manufacturing comparability standards tightened."},
            {"title": "NEJM: Adaptive Designs Cut Trial Duration 30%", "url": "https://nejm.org/adaptive-trial-study", "source_type": "research_paper", "content": "Randomised analysis across 47 Phase II trials finds adaptive designs reduce median duration by 8.4 months."},
            {"title": "Pharma Industry Report Q2 2025", "url": "https://pharma-report.com/q2", "source_type": "industry_report", "content": "Oncology and rare disease pipelines lead M&A activity. GLP-1 market share battle intensifies among Big Pharma."},
        ],
    },
    {
        "name": "Climate Science",
        "keywords": ["carbon", "emissions", "climate models", "IPCC"],
        "articles": [
            {"title": "IPCC AR6: Tipping Points Synthesis", "url": "https://ipcc.ch/ar6-tipping", "source_type": "research_paper", "content": "Nine Earth system tipping points now considered active risk. 1.5C threshold may trigger cascade effects in Amazon and West Antarctic ice."},
            {"title": "EPA Methane Reporting Rule Finalized", "url": "https://epa.gov/methane-rule", "source_type": "government", "content": "Final rule requires oil and gas operators to report methane emissions quarterly. Satellite monitoring accepted as verification method."},
            {"title": "Nature Climate: Carbon Capture Cost Curve", "url": "https://nature.com/climate/carbon-capture", "source_type": "research_paper", "content": "Direct air capture costs fell 23% in 2024. Learning curve analysis projects sub-$100/tonne by 2031."},
            {"title": "Bloomberg NEF: Renewables Capacity Report", "url": "https://bnef.com/renewables-2025", "source_type": "market_analysis", "content": "Solar additions hit 600GW in 2024, doubling 2022 record. Wind offshore pipeline grows despite supply chain pressure."},
        ],
    },
    {
        "name": "Business Strategy",
        "keywords": ["competitive advantage", "market entry", "M&A", "strategy"],
        "articles": [
            {"title": "HBR: Platform Business Model Failures 2020-2025", "url": "https://hbr.org/platform-failures", "source_type": "educational", "content": "Analysis of 34 platform business failures identifies three structural patterns: premature scaling, demand-side neglect, and governance gaps."},
            {"title": "McKinsey: M&A Value Creation Study", "url": "https://mckinsey.com/ma-value", "source_type": "industry_report", "content": "70% of M&A deals destroy shareholder value in first 3 years. Integration speed and cultural alignment are top predictors of success."},
            {"title": "a16z: The Market Map Methodology", "url": "https://a16z.com/market-map", "source_type": "company_blog", "content": "Framework for mapping competitive dynamics using demand-side segmentation rather than product categories. Includes worked examples."},
            {"title": "FT: Private Equity Exits Hit 10-Year Low", "url": "https://ft.com/pe-exits", "source_type": "news", "content": "IPO window stays closed as valuations compress. Secondary buyouts and continuation funds filling the exit gap."},
        ],
    },
]

ALL_BLOCK_TYPES = [
    "headline", "key_takeaway", "evidence", "explanation", "mechanism",
    "example", "timeline", "comparison", "step_list", "warning",
    "counterpoint", "insight", "implication", "reflection",
]


# ── Structural simulation ─────────────────────────────────────────────────────

SOURCE_TYPE_PATTERNS: dict[str, list[str]] = {
    "government":      ["timeline", "evidence", "implication", "warning"],
    "regulatory":      ["timeline", "evidence", "implication", "warning"],
    "research_paper":  ["explanation", "evidence", "mechanism", "counterpoint"],
    "industry_report": ["comparison", "evidence", "insight", "implication"],
    "market_analysis": ["key_takeaway", "comparison", "evidence", "implication"],
    "news":            ["key_takeaway", "evidence", "counterpoint", "implication"],
    "educational":     ["explanation", "example", "evidence", "step_list"],
    "company_blog":    ["example", "evidence", "insight", "warning"],
}

FALLBACK_PATTERN = ["key_takeaway", "evidence", "explanation", "implication"]

_rng = random.Random(42)   # deterministic seed for reproducibility


def _simulate_blocks(source_type: str, topic_seed: int) -> list[str]:
    """Pick blocks following the prompt heuristics with ~20% random deviation."""
    base = list(SOURCE_TYPE_PATTERNS.get(source_type, FALLBACK_PATTERN))
    _rng.seed(topic_seed)

    # 20% chance: swap one block for a thematically adjacent alternative
    swaps = {
        "timeline":     ["comparison", "step_list"],
        "comparison":   ["timeline", "counterpoint"],
        "explanation":  ["insight", "key_takeaway"],
        "mechanism":    ["insight", "explanation"],
        "step_list":    ["example", "timeline"],
        "warning":      ["counterpoint", "reflection"],
        "counterpoint": ["warning", "insight"],
        "implication":  ["reflection", "insight"],
    }
    if _rng.random() < 0.20 and base:
        idx = _rng.randrange(len(base))
        candidates = swaps.get(base[idx], [])
        if candidates:
            base[idx] = _rng.choice(candidates)

    # 30% chance: add one extra block (evidence always stays)
    if _rng.random() < 0.30:
        extras = [t for t in ALL_BLOCK_TYPES if t not in base and t != "evidence"]
        if extras:
            base.append(_rng.choice(extras))

    return base


def simulate_articles(n: int = 20) -> list[dict]:
    """Generate n simulated article block specs from the test fixture topics."""
    results = []
    per_topic = n // len(TOPICS)
    extra = n - per_topic * len(TOPICS)

    for t_idx, topic in enumerate(TOPICS):
        count = per_topic + (1 if t_idx < extra else 0)
        for a_idx in range(count):
            article = topic["articles"][a_idx % len(topic["articles"])]
            seed = t_idx * 100 + a_idx
            blocks = _simulate_blocks(article["source_type"], seed)
            results.append({
                "topic":       topic["name"],
                "source_type": article["source_type"],
                "blocks":      blocks,
                "mode":        "sim",
            })
    return results


# ── Live LLM generation ───────────────────────────────────────────────────────

def _build_live_prompt(topic: dict) -> str:
    from backend.prompts.project_insight_prompt import make_daily_package_prompt
    return make_daily_package_prompt(
        project_name    = topic["name"],
        keywords        = topic["keywords"],
        difficulty      = "intermediate",
        day_number      = 1,
        display_label   = "Day 1",
        core_articles   = topic["articles"],
        curiosity_articles = [],
    )


def _parse_llm_blocks(raw: str, topic_name: str) -> list[dict]:
    """Extract block-type lists from LLM JSON response."""
    try:
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        data  = json.loads(raw[start:end])
    except Exception as e:
        print(f"  [WARN] JSON parse error for {topic_name!r}: {e}")
        return []

    results = []
    for card in (data.get("insights") or []) + (data.get("curiosity_insights") or []):
        blocks_raw = card.get("blocks") or []
        block_types = [b["type"] for b in blocks_raw if isinstance(b, dict) and b.get("type")]
        if block_types:
            results.append({
                "topic":       topic_name,
                "source_type": "live",
                "blocks":      block_types,
                "mode":        "live",
            })
    return results


def live_articles(target: int = 20) -> list[dict]:
    """Call LLM for each topic and collect block structures."""
    from backend.services.grok_service import ask_grok

    results: list[dict] = []
    per_topic = max(1, target // len(TOPICS))

    for topic in TOPICS:
        if len(results) >= target:
            break
        print(f"  Calling LLM for: {topic['name']} …", end=" ", flush=True)
        try:
            prompt = _build_live_prompt(topic)
            raw    = ask_grok(prompt, json_mode=True)
            cards  = _parse_llm_blocks(raw, topic["name"])
            results.extend(cards[:per_topic])
            print(f"got {len(cards)} cards")
        except Exception as e:
            print(f"FAILED ({e})")

    return results[:target]


# ── Audit ─────────────────────────────────────────────────────────────────────

class AuditResult(NamedTuple):
    total:                  int
    avg_block_count:        float
    unique_combinations:    int
    distinct_block_types:   int
    top_combo_pct:          float
    block_type_dist:        dict[str, int]
    combo_dist:             dict[tuple, int]
    passes:                 dict[str, bool]
    overall_pass:           bool


TARGET_MAX_COMBO_PCT = 0.40
TARGET_MIN_BLOCK_TYPES = 6
TARGET_MIN_COMBOS = 5


def audit(articles: list[dict]) -> AuditResult:
    if not articles:
        raise ValueError("No articles to audit")

    combos      = [tuple(sorted(a["blocks"])) for a in articles]
    combo_counts = Counter(combos)
    type_counts  = Counter(t for a in articles for t in a["blocks"])

    top_combo_pct = combo_counts.most_common(1)[0][1] / len(articles)

    passes = {
        "combo_dominance":  top_combo_pct <= TARGET_MAX_COMBO_PCT,
        "block_type_count": len(type_counts) >= TARGET_MIN_BLOCK_TYPES,
        "combo_count":      len(combo_counts) >= TARGET_MIN_COMBOS,
    }

    return AuditResult(
        total               = len(articles),
        avg_block_count     = sum(len(a["blocks"]) for a in articles) / len(articles),
        unique_combinations = len(combo_counts),
        distinct_block_types= len(type_counts),
        top_combo_pct       = top_combo_pct,
        block_type_dist     = dict(type_counts.most_common()),
        combo_dist          = dict(combo_counts.most_common(10)),
        passes              = passes,
        overall_pass        = all(passes.values()),
    )


# ── Report ────────────────────────────────────────────────────────────────────

def _bar(count: int, total: int, width: int = 20) -> str:
    filled = round(count / total * width)
    return "█" * filled + "░" * (width - filled)


def print_report(result: AuditResult, mode: str) -> None:
    W = 60
    line = "─" * W
    print()
    print("═" * W)
    print(f"  PHASE 8 DIVERSITY AUDIT  [{mode.upper()} MODE]")
    print("═" * W)
    print(f"  Articles audited : {result.total}")
    print(f"  Mode             : {mode}")
    print()
    print(f"  Avg blocks/article  : {result.avg_block_count:.1f}")
    print(f"  Distinct block types: {result.distinct_block_types}  (target ≥ {TARGET_MIN_BLOCK_TYPES})")
    print(f"  Unique combinations : {result.unique_combinations}  (target ≥ {TARGET_MIN_COMBOS})")
    print(f"  Top combo share     : {result.top_combo_pct:.0%}  (target ≤ {TARGET_MAX_COMBO_PCT:.0%})")
    print()
    print(line)
    print("  BLOCK TYPE DISTRIBUTION")
    print(line)
    total_blocks = sum(result.block_type_dist.values())
    for btype, count in result.block_type_dist.items():
        pct = count / total_blocks
        print(f"  {btype:<15} {_bar(count, total_blocks)} {count:>3}  {pct:>5.1%}")
    print()
    print(line)
    print("  STRUCTURE COMBINATIONS (top 10)")
    print(line)
    for combo, count in list(result.combo_dist.items())[:10]:
        pct = count / result.total
        marker = " ← dominant" if pct > TARGET_MAX_COMBO_PCT else ""
        print(f"  {pct:>5.1%}  {', '.join(combo)}{marker}")
    print()
    print("═" * W)
    print("  CHECKS")
    print("═" * W)
    for check, passed in result.passes.items():
        icon = "PASS" if passed else "FAIL"
        labels = {
            "combo_dominance":  f"No combo > {TARGET_MAX_COMBO_PCT:.0%}",
            "block_type_count": f">= {TARGET_MIN_BLOCK_TYPES} distinct block types",
            "combo_count":      f">= {TARGET_MIN_COMBOS} distinct combinations",
        }
        print(f"  [{icon}]  {labels[check]}")
    print()
    verdict = "PASS" if result.overall_pass else "FAIL"
    print(f"  OVERALL: {verdict}")
    print("═" * W)
    print()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 8 diversity audit")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--live", action="store_true", help="Force real LLM generation")
    group.add_argument("--sim",  action="store_true", help="Force structural simulation")
    parser.add_argument("--n", type=int, default=20, help="Number of articles (default 20)")
    args = parser.parse_args()

    use_live = False
    if args.live:
        use_live = True
    elif args.sim:
        use_live = False
    else:
        use_live = bool(os.getenv("GROQ_API_KEY"))

    mode = "live" if use_live else "sim"
    print(f"\nRunning Phase 8 diversity audit in {mode.upper()} mode …")
    print(f"Target: {args.n} articles across {len(TOPICS)} topics\n")

    if use_live:
        print("Generating articles via LLM …")
        articles = live_articles(args.n)
        if not articles:
            print("ERROR: No articles generated. Check GROQ_API_KEY and API connectivity.")
            return 1
    else:
        print("Running structural simulation (set GROQ_API_KEY for live mode) …")
        articles = simulate_articles(args.n)

    if len(articles) < args.n:
        print(f"[WARN] Only got {len(articles)} articles (requested {args.n})")

    result = audit(articles)
    print_report(result, mode)

    return 0 if result.overall_pass else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "buffer") and (not sys.stdout.encoding or sys.stdout.encoding.lower() not in ("utf-8", "utf-8-sig")):
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.exit(main())
