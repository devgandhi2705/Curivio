"""
Retrieval Quality Metrics Service

Computes and stores per-package retrieval quality metrics.
Called after package generation — internal use only, no UI surface.

Metrics computed:
  retrieved_count           — raw articles fetched (pre-validation)
  validated_count           — articles that passed the validator
  rejected_count            — retrieved - validated
  avg_relevance             — mean _retrieval_score across validated articles
  unique_domains            — distinct domains in package source_links
  unique_publishers         — same as unique_domains (domain proxy)
  source_reuse_rate         — fraction of distinct URLs appearing in 2+ cards
  primary_source_collisions — URLs used as primary (source_links[0]) in 2+ cards
  domain_concentration      — Herfindahl index of domain distribution (0=diverse, 1=monopoly)
  articles_without_sources  — cards with empty source_links

Source quality audit (Phase 7.8):
  source_coverage_score   — [0, 2] articles_with_sources / total_articles, target 100%
  source_diversity_score  — [0, 2] unique_domains / total_articles,         target ≥0.75
  source_reuse_score      — [0, 2] based on primary_source_collisions,      target 0
  grounding_score         — [0, 2] URLs verified against retrieval set,      target 100%
  duplicate_story_score   — [0, 2] card-title pair similarity below 20%,    target <20%
  overall_score           — [0, 10] sum of above; package healthy if ≥ 8

Success targets:
  articles_without_sources  == 0
  primary_source_collisions == 0
  source_reuse_rate         <  0.20
  unique_domains            >= article_count (where feasible)

Public API
----------
compute(package, retrieved_count, core_articles, curiosity_articles) -> dict
store(project_id, insight_id, metrics)                               -> None
log_metrics(project_id, insight_id, metrics, logger)                 -> None
audit(package, allowed_urls, core_articles, curiosity_articles)      -> AuditReport
log_audit(project_id, insight_id, report, logger)                    -> None
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from urllib.parse import urlparse

_logger = logging.getLogger(__name__)

# ── Audit thresholds ──────────────────────────────────────────────────────────

_COVERAGE_TARGET:   float = 1.00   # 100% of cards must have sources
_DIVERSITY_TARGET:  float = 0.75   # unique_domains / total_cards
_DUP_STORY_TARGET:  float = 0.20   # fraction of near-duplicate card pairs
_HEALTHY_SCORE:     float = 8.0    # overall score threshold for "healthy" package
_DUP_TITLE_THRESH:  float = 0.50   # token_overlap above this = duplicate story


@dataclass
class AuditReport:
    source_coverage_score:  float   # [0, 2]
    source_diversity_score: float   # [0, 2]
    source_reuse_score:     float   # [0, 2]
    grounding_score:        float   # [0, 2]
    duplicate_story_score:  float   # [0, 2]
    overall_score:          float   # [0, 10]
    passes:                 dict    # metric_name → bool
    details:                dict    # raw metric values


# ── Domain extraction ─────────────────────────────────────────────────────────

def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


# ── Compute ───────────────────────────────────────────────────────────────────

def compute(
    package:          dict,
    retrieved_count:  int,
    core_articles:    list[dict],
    curiosity_articles: list[dict],
) -> dict:
    """
    Compute all retrieval quality metrics for a generated package.
    core_articles / curiosity_articles are the ranked lists passed to the LLM —
    they carry _retrieval_score from the validator.
    """
    all_validated  = core_articles + curiosity_articles
    validated_count = len(all_validated)
    rejected_count  = max(0, retrieved_count - validated_count)

    # Average relevance score across validated articles
    scores = [float(a.get("_retrieval_score") or 0.0) for a in all_validated if a.get("_retrieval_score")]
    avg_relevance = round(sum(scores) / len(scores), 4) if scores else 0.0

    # Analyse source_links in the FINAL package
    all_cards = (package.get("insights") or []) + (package.get("curiosity_insights") or [])

    url_card_count: dict[str, int]    = {}   # distinct URL → how many cards reference it
    primary_urls:   list[str]         = []   # first URL per card
    domain_counts:  dict[str, int]    = {}   # domain → reference count (not card count)
    cards_without_sources = 0

    for card in all_cards:
        links = card.get("source_links") or []
        if not links:
            cards_without_sources += 1
            continue

        card_urls: set[str] = set()
        for link in links:
            url = (link.get("url") or "").rstrip("/").lower()
            if not url:
                continue
            card_urls.add(url)
            dom = _domain(url)
            if dom:
                domain_counts[dom] = domain_counts.get(dom, 0) + 1

        for url in card_urls:
            url_card_count[url] = url_card_count.get(url, 0) + 1

        # source_links[0] is primary (guaranteed by _process_card in project_service)
        first_url = (links[0].get("url") or "").rstrip("/").lower()
        if first_url:
            primary_urls.append(first_url)

    # Primary source collisions — same URL as primary in 2+ cards
    primary_counts = Counter(primary_urls)
    primary_source_collisions = sum(1 for c in primary_counts.values() if c > 1)

    # Source reuse rate — fraction of distinct URLs shared across 2+ cards
    total_distinct = len(url_card_count)
    reused = sum(1 for c in url_card_count.values() if c > 1)
    source_reuse_rate = round(reused / total_distinct, 4) if total_distinct > 0 else 0.0

    # Domain diversity
    unique_domains    = len(domain_counts)
    unique_publishers = unique_domains   # domain is publisher proxy

    # Domain concentration — Herfindahl index over reference counts
    total_refs = sum(domain_counts.values())
    if total_refs > 0:
        domain_concentration = round(
            sum((c / total_refs) ** 2 for c in domain_counts.values()), 4
        )
    else:
        domain_concentration = 0.0

    return {
        "retrieved_count":            retrieved_count,
        "validated_count":            validated_count,
        "rejected_count":             rejected_count,
        "avg_relevance":              avg_relevance,
        "unique_domains":             unique_domains,
        "unique_publishers":          unique_publishers,
        "source_reuse_rate":          source_reuse_rate,
        "primary_source_collisions":  primary_source_collisions,
        "domain_concentration":       domain_concentration,
        "articles_without_sources":   cards_without_sources,
    }


# ── Store ─────────────────────────────────────────────────────────────────────

def store(project_id: str, insight_id: int, metrics: dict) -> None:
    """INSERT OR REPLACE metrics row for this package."""
    from ..utils.db import get_connection
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with get_connection() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO retrieval_metrics
               (project_id, insight_id, computed_at,
                retrieved_count, validated_count, rejected_count, avg_relevance,
                unique_domains, unique_publishers, source_reuse_rate,
                primary_source_collisions, domain_concentration, articles_without_sources)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                project_id, insight_id, now,
                metrics["retrieved_count"],
                metrics["validated_count"],
                metrics["rejected_count"],
                metrics["avg_relevance"],
                metrics["unique_domains"],
                metrics["unique_publishers"],
                metrics["source_reuse_rate"],
                metrics["primary_source_collisions"],
                metrics["domain_concentration"],
                metrics["articles_without_sources"],
            ),
        )

    _logger.debug(
        "[METRICS] stored for project_id=%s insight_id=%d", project_id, insight_id
    )


# ── Log ───────────────────────────────────────────────────────────────────────

def log_metrics(
    project_id: str,
    insight_id: int,
    metrics: dict,
    logger: logging.Logger | None = None,
) -> None:
    """Emit one structured INFO log line covering all quality signals."""
    _log = logger or _logger

    # Flag anything that violates success targets
    flags: list[str] = []
    if metrics["articles_without_sources"] > 0:
        flags.append(f"SOURCES_MISSING={metrics['articles_without_sources']}")
    if metrics["primary_source_collisions"] > 0:
        flags.append(f"PRIMARY_COLLISIONS={metrics['primary_source_collisions']}")
    if metrics["source_reuse_rate"] >= 0.20:
        flags.append(f"HIGH_REUSE={metrics['source_reuse_rate']:.0%}")

    flag_str = " [" + " ".join(flags) + "]" if flags else ""

    _log.info(
        "[METRICS] project_id=%s insight_id=%d"
        " retrieved=%d validated=%d rejected=%d avg_relevance=%.3f"
        " unique_domains=%d unique_publishers=%d"
        " source_reuse_rate=%.1f%% primary_collisions=%d"
        " domain_concentration=%.3f articles_without_sources=%d%s",
        project_id, insight_id,
        metrics["retrieved_count"],
        metrics["validated_count"],
        metrics["rejected_count"],
        metrics["avg_relevance"],
        metrics["unique_domains"],
        metrics["unique_publishers"],
        metrics["source_reuse_rate"] * 100,
        metrics["primary_source_collisions"],
        metrics["domain_concentration"],
        metrics["articles_without_sources"],
        flag_str,
    )


# ── Phase 7.8: Source Quality Audit ──────────────────────────────────────────

def _grounding_integrity(
    package:      dict,
    allowed_urls: frozenset[str],
) -> float:
    """Fraction of source URLs in the package that exist in the retrieval set."""
    all_cards  = (package.get("insights") or []) + (package.get("curiosity_insights") or [])
    total = grounded = 0
    for card in all_cards:
        for link in (card.get("source_links") or []):
            url = (link.get("url") or "").rstrip("/").lower()
            if url:
                total   += 1
                grounded += 1 if url in allowed_urls else 0
    return grounded / total if total > 0 else 1.0


def _duplicate_story_fraction(package: dict) -> float:
    """
    Fraction of core insight card pairs whose titles score above _DUP_TITLE_THRESH.
    Single-card or empty packages return 0.0 (no duplicates possible).
    """
    from .similarity_service import token_overlap

    titles = [
        (c.get("title") or "")
        for c in (package.get("insights") or [])
        if c.get("title")
    ]
    n = len(titles)
    if n < 2:
        return 0.0
    total_pairs = n * (n - 1) // 2
    dup_pairs   = sum(
        1
        for i in range(n)
        for j in range(i + 1, n)
        if token_overlap(titles[i], titles[j]) > _DUP_TITLE_THRESH
    )
    return round(dup_pairs / total_pairs, 4) if total_pairs > 0 else 0.0


def audit(
    package:            dict,
    allowed_urls:       frozenset[str],
    core_articles:      list[dict],
    curiosity_articles: list[dict],
) -> AuditReport:
    """
    Compute Phase 7.8 source quality audit for a generated package.

    Calls compute() internally to reuse raw metric calculations.
    Returns AuditReport with per-metric scores (0-2 each) and overall score (0-10).
    Package is "healthy" when overall_score >= _HEALTHY_SCORE (8.0).
    """
    raw = compute(
        package,
        retrieved_count=0,          # not needed for audit scoring
        core_articles=core_articles,
        curiosity_articles=curiosity_articles,
    )

    all_cards   = (package.get("insights") or []) + (package.get("curiosity_insights") or [])
    total_cards = len(all_cards)

    # ── 1. Source Coverage ────────────────────────────────────────────────────
    cards_with_sources = total_cards - raw["articles_without_sources"]
    coverage_raw  = cards_with_sources / total_cards if total_cards > 0 else 1.0
    cov_score     = round(min(2.0, coverage_raw * 2.0), 4)
    cov_pass      = coverage_raw >= _COVERAGE_TARGET

    # ── 2. Source Diversity ───────────────────────────────────────────────────
    diversity_raw = raw["unique_domains"] / total_cards if total_cards > 0 else 1.0
    div_score     = round(min(2.0, (diversity_raw / _DIVERSITY_TARGET) * 2.0), 4)
    div_pass      = diversity_raw >= _DIVERSITY_TARGET

    # ── 3. Source Reuse ───────────────────────────────────────────────────────
    collisions    = raw["primary_source_collisions"]
    reuse_score   = round(max(0.0, 2.0 - collisions * 0.5), 4) if collisions > 0 else 2.0
    reuse_pass    = collisions == 0

    # ── 4. Grounding Integrity ────────────────────────────────────────────────
    grounding_raw  = _grounding_integrity(package, allowed_urls)
    grnd_score     = round(min(2.0, grounding_raw * 2.0), 4)
    grnd_pass      = grounding_raw >= 1.0

    # ── 5. Duplicate Story ────────────────────────────────────────────────────
    dup_raw    = _duplicate_story_fraction(package)
    if dup_raw < _DUP_STORY_TARGET:
        dup_score = 2.0
    else:
        dup_score = round(max(0.0, 2.0 - (dup_raw - _DUP_STORY_TARGET) * 10), 4)
    dup_pass   = dup_raw < _DUP_STORY_TARGET

    overall = round(cov_score + div_score + reuse_score + grnd_score + dup_score, 4)

    return AuditReport(
        source_coverage_score  = cov_score,
        source_diversity_score = div_score,
        source_reuse_score     = reuse_score,
        grounding_score        = grnd_score,
        duplicate_story_score  = dup_score,
        overall_score          = overall,
        passes = {
            "source_coverage":    cov_pass,
            "source_diversity":   div_pass,
            "source_reuse":       reuse_pass,
            "grounding_integrity": grnd_pass,
            "duplicate_story":    dup_pass,
        },
        details = {
            "coverage_raw":       round(coverage_raw,   4),
            "diversity_raw":      round(diversity_raw,  4),
            "collisions":         collisions,
            "grounding_raw":      round(grounding_raw,  4),
            "duplicate_fraction": dup_raw,
            "total_cards":        total_cards,
        },
    )


def log_audit(
    project_id: str,
    insight_id: int,
    report:     AuditReport,
    logger:     logging.Logger | None = None,
) -> None:
    """Log PASS/FAIL per metric and overall score at INFO level."""
    _log  = logger or _logger
    lvl   = logging.INFO if report.overall_score >= _HEALTHY_SCORE else logging.WARNING
    health = "HEALTHY" if report.overall_score >= _HEALTHY_SCORE else "UNHEALTHY"

    def _pf(ok: bool) -> str:
        return "PASS" if ok else "FAIL"

    _log.log(
        lvl,
        "[AUDIT] project=%s insight=%d overall=%.1f/10 [%s]"
        " | source_coverage=%s(%.2f)"
        " | source_diversity=%s(%.2f)"
        " | source_reuse=%s"
        " | grounding=%s(%.2f)"
        " | duplicate_story=%s(%.1f%%)",
        project_id, insight_id, report.overall_score, health,
        _pf(report.passes["source_coverage"]),    report.details["coverage_raw"],
        _pf(report.passes["source_diversity"]),   report.details["diversity_raw"],
        _pf(report.passes["source_reuse"]),
        _pf(report.passes["grounding_integrity"]), report.details["grounding_raw"],
        _pf(report.passes["duplicate_story"]),    report.details["duplicate_fraction"] * 100,
    )
