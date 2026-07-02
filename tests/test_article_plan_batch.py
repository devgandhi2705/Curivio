"""
Phase 9.3.4A — Batch-Aware Article Planning Tests

Tests cover:
  - resolve_package_counts: all count rules
  - ArticlePlan: backward compat + new fields (Task 1)
  - Curiosity plan first-class treatment (Task 4)
  - build_batch_plans structure: 4, 8, 10-article cases (Task 5)
  - batch_id / batch_position assignment (Tasks 1+5)
  - Supporting source batch-scoping (Task 6)
  - Global primary uniqueness (Task 7)
  - validate_batch_plans checks A-E (Task 8)

Run:
    pytest tests/test_article_plan_batch.py -v --noconftest
"""

from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.article_plan_service import (
    ArticlePlan,
    BatchPlan,
    MAX_SOURCES,
    BACKUP_SOURCES,
    build_article_plans,
    build_batch_plans,
    resolve_package_counts,
    validate_batch_plans,
    validate_plans,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _art(i: int, url: str | None = None) -> dict:
    return {
        "title":           f"Article {i}: Test Headline About Topic Number {i}",
        "url":             url or f"https://source{i}.com/article",
        "content":         f"Content for article {i}. Detailed analysis follows.",
        "_rank_score":     max(0.30, 0.92 - i * 0.06),
        "signal_density":  0.70,
        "source_strength": 0.75,
        "source_type":     "news",
    }


def _core_plans(n: int) -> list[ArticlePlan]:
    return build_article_plans([_art(i) for i in range(n)], n)


def _curiosity_plans(n: int, offset: int = 100) -> list[ArticlePlan]:
    return build_article_plans(
        [_art(i + offset) for i in range(n)], n, article_type="curiosity"
    )


# ── Task 3: resolve_package_counts ────────────────────────────────────────────

def test_counts_4():
    assert resolve_package_counts(4) == (4, 2)

def test_counts_5():
    assert resolve_package_counts(5) == (5, 2)

def test_counts_6():
    assert resolve_package_counts(6) == (4, 2)

def test_counts_7():
    assert resolve_package_counts(7) == (5, 2)

def test_counts_10():
    assert resolve_package_counts(10) == (8, 2)


# ── Task 1: ArticlePlan backward compat ───────────────────────────────────────

def test_new_fields_default_none_before_batch():
    plans = _core_plans(4)
    assert all(p.batch_id is None for p in plans)
    assert all(p.batch_position is None for p in plans)

def test_default_article_type_is_core():
    plans = _core_plans(4)
    assert all(p.article_type == "core" for p in plans)

def test_existing_validate_plans_still_passes():
    plans = _core_plans(4)
    ok, errs = validate_plans(plans)
    assert ok, errs

def test_primary_source_property():
    plans = _core_plans(3)
    for plan in plans:
        assert plan.primary_source is not None
        assert plan.primary_source.get("url")

def test_source_urls_property():
    plans = _core_plans(4)
    for plan in plans:
        urls = plan.source_urls
        assert len(urls) >= 1
        assert all(u.startswith("https://") for u in urls)


# ── Task 4: Curiosity planning — first-class treatment ───────────────────────

def test_curiosity_plans_article_type():
    plans = _curiosity_plans(2)
    assert all(p.article_type == "curiosity" for p in plans)

def test_curiosity_plans_slot_id_prefix():
    plans = _curiosity_plans(2)
    assert all(p.slot_id.startswith("curiosity-slot-") for p in plans)

def test_curiosity_plans_have_primary_source():
    plans = _curiosity_plans(2)
    assert all(p.primary_source is not None for p in plans)

def test_curiosity_plans_pass_validate_plans():
    plans = _curiosity_plans(4)
    ok, errs = validate_plans(plans)
    assert ok, errs

def test_core_and_curiosity_slot_ids_distinct():
    core  = _core_plans(4)
    curio = _curiosity_plans(2)
    core_ids  = {p.slot_id for p in core}
    curio_ids = {p.slot_id for p in curio}
    assert core_ids.isdisjoint(curio_ids)


# ── Task 5: build_batch_plans structure ───────────────────────────────────────

def test_4_articles_one_batch():
    batches = build_batch_plans(_core_plans(4))
    assert len(batches) == 1
    assert len(batches[0].plans) == 4
    assert batches[0].batch_id == 1

def test_8_articles_two_batches():
    batches = build_batch_plans(_core_plans(8), max_articles_per_batch=4)
    assert len(batches) == 2
    assert len(batches[0].plans) == 4
    assert len(batches[1].plans) == 4

def test_10_articles_three_batches():
    all_plans = _core_plans(8) + _curiosity_plans(2)
    batches = build_batch_plans(all_plans, max_articles_per_batch=4)
    assert len(batches) == 3
    core_batches  = [b for b in batches if b.plans and b.plans[0].article_type == "core"]
    curio_batches = [b for b in batches if b.plans and b.plans[0].article_type == "curiosity"]
    assert len(core_batches) == 2
    assert len(curio_batches) == 1
    assert len(curio_batches[0].plans) == 2

def test_curiosity_batch_always_last():
    all_plans = _core_plans(4) + _curiosity_plans(2)
    batches = build_batch_plans(all_plans, max_articles_per_batch=4)
    last = batches[-1]
    assert all(p.article_type == "curiosity" for p in last.plans)

def test_empty_input_returns_empty():
    assert build_batch_plans([]) == []

def test_batch_ids_sequential_from_1():
    all_plans = _core_plans(8) + _curiosity_plans(2)
    batches = build_batch_plans(all_plans, max_articles_per_batch=4)
    assert [bp.batch_id for bp in batches] == [1, 2, 3]

def test_batch_article_ids_match_plan_slot_ids():
    batches = build_batch_plans(_core_plans(4))
    bp = batches[0]
    assert bp.article_ids == [p.slot_id for p in bp.plans]

def test_primary_source_urls_populated():
    batches = build_batch_plans(_core_plans(4))
    bp = batches[0]
    assert len(bp.primary_source_urls) == 4
    assert all(u.startswith("https://") for u in bp.primary_source_urls)

def test_non_multiple_batch_last_chunk():
    """6 core articles → batch of 4 + batch of 2 (not padded)."""
    batches = build_batch_plans(_core_plans(6), max_articles_per_batch=4)
    assert len(batches) == 2
    assert len(batches[0].plans) == 4
    assert len(batches[1].plans) == 2


# ── Tasks 1+5: batch_id and batch_position stamped on plans ──────────────────

def test_batch_id_stamped_on_all_plans():
    all_plans = _core_plans(8)
    batches = build_batch_plans(all_plans, max_articles_per_batch=4)
    for bp in batches:
        assert all(p.batch_id == bp.batch_id for p in bp.plans)

def test_batch_position_is_sequential():
    batches = build_batch_plans(_core_plans(4))
    positions = [p.batch_position for p in batches[0].plans]
    assert positions == list(range(4))

def test_originals_not_mutated():
    """build_batch_plans must not mutate the input plan objects."""
    plans = _core_plans(4)
    orig_batch_ids = [p.batch_id for p in plans]
    orig_assigned  = [list(p.assigned_sources) for p in plans]
    build_batch_plans(plans)
    assert [p.batch_id for p in plans] == orig_batch_ids
    assert [list(p.assigned_sources) for p in plans] == orig_assigned


# ── Task 6: Supporting sources batch-scoped ───────────────────────────────────

def test_supporting_within_batch_8_articles():
    batches = build_batch_plans(_core_plans(8), max_articles_per_batch=4)
    for bp in batches:
        primary_set = set(bp.primary_source_urls)
        for plan in bp.plans:
            for src in plan.assigned_sources[1:]:
                url = src.get("url", "")
                assert url in primary_set, (
                    f"batch={bp.batch_id} {plan.slot_id}: supporting {url!r} "
                    f"not in batch primaries {primary_set}"
                )

def test_supporting_within_batch_12_articles():
    batches = build_batch_plans(_core_plans(12), max_articles_per_batch=4)
    assert len(batches) == 3
    for bp in batches:
        primary_set = set(bp.primary_source_urls)
        for plan in bp.plans:
            for src in plan.assigned_sources[1:]:
                assert src.get("url") in primary_set

def test_backup_sources_not_constrained_to_batch():
    """Backup sources may reference URLs outside the batch — no scoping requirement."""
    batches = build_batch_plans(_core_plans(8), max_articles_per_batch=4)
    # Batch-1 backup sources often come from batch-2 articles — this is correct.
    # Just verify they exist and have URLs (not checking which batch they're from).
    for bp in batches:
        for plan in bp.plans:
            for src in plan.backup_sources:
                assert src.get("url"), f"Backup source missing URL in {plan.slot_id}"


# ── Task 7: Global primary URL uniqueness ─────────────────────────────────────

def test_primary_urls_unique_across_all_batches():
    all_plans = _core_plans(8) + _curiosity_plans(4, offset=100)
    batches = build_batch_plans(all_plans, max_articles_per_batch=4)
    all_primaries = [url for bp in batches for url in bp.primary_source_urls]
    assert len(all_primaries) == len(set(all_primaries)), (
        f"Duplicate primary URLs found: "
        f"{[u for u in all_primaries if all_primaries.count(u) > 1]}"
    )

def test_primary_urls_unique_8_core_only():
    batches = build_batch_plans(_core_plans(8), max_articles_per_batch=4)
    all_primaries = [url for bp in batches for url in bp.primary_source_urls]
    assert len(all_primaries) == len(set(all_primaries))


# ── Task 8: validate_batch_plans — Check A: duplicate primary ────────────────

def test_validate_clean_build_passes():
    all_plans = _core_plans(8) + _curiosity_plans(2)
    batches = build_batch_plans(all_plans, max_articles_per_batch=4)
    ok, errors = validate_batch_plans(batches)
    assert ok, errors

def test_validate_single_batch_passes():
    # 5 articles so each plan has 1 backup (article-4 isn't consumed by any assigned set)
    batches = build_batch_plans(_core_plans(5))
    ok, errors = validate_batch_plans(batches)
    assert ok, errors

def test_validate_empty_input():
    ok, errors = validate_batch_plans([])
    assert not ok
    assert any("No batch" in e for e in errors)

def test_validate_check_A_duplicate_primary():
    batches = build_batch_plans(_core_plans(8), max_articles_per_batch=4)
    dup_url = batches[0].primary_source_urls[0]
    # Inject dup into batch-2
    batches[1].primary_source_urls[0] = dup_url
    batches[1].plans[0].assigned_sources[0] = {
        "url": dup_url, "title": "Dup", "why_used": "injected",
    }
    ok, errors = validate_batch_plans(batches)
    assert not ok
    assert any("Duplicate primary" in e for e in errors)

# ── Task 8: Check B — no assigned sources ────────────────────────────────────

def test_validate_check_B_no_assigned_sources():
    batches = build_batch_plans(_core_plans(4))
    batches[0].plans[0].assigned_sources = []
    ok, errors = validate_batch_plans(batches)
    assert not ok
    assert any("no assigned sources" in e for e in errors)

# ── Task 8: Check C — missing backup on large batch ──────────────────────────

def test_validate_check_C_missing_backup_large_batch():
    """Batch with MAX_SOURCES plans must have backup sources on all plans."""
    batches = build_batch_plans(_core_plans(8), max_articles_per_batch=4)
    for plan in batches[0].plans:
        plan.backup_sources = []
    batches[0].backup_source_urls = []
    ok, errors = validate_batch_plans(batches)
    assert not ok
    assert any("backup" in e for e in errors)

def test_validate_check_C_small_batch_exempt():
    """Curiosity batch with 2 plans is exempt from backup check — too small to supply them."""
    curio = _curiosity_plans(2)
    batches = build_batch_plans(curio, max_articles_per_batch=4)
    # Force-clear backup sources to confirm the check is skipped for small batches
    for plan in batches[0].plans:
        plan.backup_sources = []
    batches[0].backup_source_urls = []
    ok, errors = validate_batch_plans(batches)
    # Should still pass (small batch exempt from check C)
    assert ok, errors

# ── Task 8: Check D — cross-batch supporting source ──────────────────────────

def test_validate_check_D_cross_batch_supporting():
    batches = build_batch_plans(_core_plans(8), max_articles_per_batch=4)
    cross_url = batches[1].primary_source_urls[0]
    batches[0].plans[0].assigned_sources.append({
        "url": cross_url, "title": "Cross-batch", "why_used": "injected",
    })
    batches[0].supporting_source_urls.append(cross_url)
    ok, errors = validate_batch_plans(batches)
    assert not ok
    assert any("not in batch" in e for e in errors)

# ── Task 8: Check E — empty batch ────────────────────────────────────────────

def test_validate_check_E_empty_batch():
    empty = BatchPlan(
        batch_id=1, article_ids=[], plans=[],
        primary_source_urls=[], supporting_source_urls=[], backup_source_urls=[],
    )
    ok, errors = validate_batch_plans([empty])
    assert not ok
    assert any("empty" in e for e in errors)

# ── Task 8: Curiosity plan parity ────────────────────────────────────────────

def test_validate_curiosity_parity_with_enough_articles():
    """6 curiosity articles → backup sources available → all checks pass."""
    curio_plans = _curiosity_plans(6, offset=200)
    batches = build_batch_plans(curio_plans, max_articles_per_batch=6)
    ok, errors = validate_batch_plans(batches)
    assert ok, errors

def test_validate_multiple_errors_reported():
    """validate_batch_plans collects all errors, not just the first."""
    batches = build_batch_plans(_core_plans(8), max_articles_per_batch=4)
    # Strip sources from two plans in different batches
    batches[0].plans[0].assigned_sources = []
    batches[1].plans[0].assigned_sources = []
    ok, errors = validate_batch_plans(batches)
    assert not ok
    assert len(errors) >= 2
