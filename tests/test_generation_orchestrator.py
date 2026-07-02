"""
Phase 9.3.4C — Multi-Call Generation Orchestrator Tests

Test categories:
  A — 1 batch (4 core articles)
  B — 2 batches (8 core articles)
  C — 3 batches (8 core + 2 curiosity)
  D — merge order preserved
  E — merge_batch_results structure (required fields)
  F — batch failure propagation
  G — feature flag defaults to False

Run:
    pytest tests/test_generation_orchestrator.py -v --noconftest
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.generation_orchestrator import (
    BatchGenerationResult,
    merge_batch_results,
    run_generation_orchestrator,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _art(i: int) -> dict:
    return {
        "title":           f"Article {i}",
        "url":             f"https://source{i}.com/article",
        "content":         f"Content {i}.",
        "_rank_score":     max(0.30, 0.90 - i * 0.05),
        "signal_density":  0.70,
        "source_strength": 0.75,
        "source_type":     "news",
    }


def _card(card_id: str, url: str = "https://source0.com/article") -> dict:
    return {
        "id":             card_id,
        "content_type":   "news",
        "title":          f"Title for {card_id}",
        "summary":        "Summary.",
        "blocks":         [{"type": "evidence", "content": "CORE-1 reports ..."}],
        "primary_source": {"title": "Article 0", "url": url},
        "supporting_sources": [],
        "difficulty":     "intermediate",
        "estimated_read_time": "3 min",
    }


def _curio_card(card_id: str, url: str = "https://curio0.com/article") -> dict:
    return {
        "id":             card_id,
        "content_type":   "curiosity",
        "title":          f"Curiosity {card_id}",
        "summary":        "Something weird.",
        "blocks":         [{"type": "evidence", "content": "CORE-1 reports ..."}],
        "primary_source": {"title": "Curio 0", "url": url},
        "supporting_sources": [],
        "difficulty":     "intermediate",
        "estimated_read_time": "3 min",
    }


def _result(batch_id: int, insights=None, curiosity=None) -> BatchGenerationResult:
    return BatchGenerationResult(
        batch_id           = batch_id,
        insights           = insights or [],
        curiosity_insights = curiosity or [],
        prompt_tokens      = 500,
        completion_tokens  = 0,
        generation_time_ms = 200.0,
        source_ids_used    = [],
    )


def _base_kwargs(**overrides) -> dict:
    kwargs = dict(
        project_name             = "AI Agents",
        keywords                 = ["LLM", "agents"],
        difficulty               = "intermediate",
        day_number               = 3,
        display_label            = "Day 3",
        daily_core_article_count = 4,
        core_articles            = [_art(i) for i in range(4)],
        curiosity_articles       = [_art(i + 100) for i in range(2)],
        article_budget_tokens    = 2000,
        project_id               = "proj-test-001",
    )
    kwargs.update(overrides)
    return kwargs


# ── Test A: 1 batch (≤4 core articles) ───────────────────────────────────────

def test_a_single_batch_returns_raw_dict():
    batch1 = _result(1, insights=[_card("card-1"), _card("card-2")])
    curio1 = _result(2, curiosity=[_curio_card("curiosity-1"), _curio_card("curiosity-2")])

    with patch("backend.services.generation_orchestrator.generate_batch") as mock_gen:
        mock_gen.side_effect = [batch1, curio1]
        raw = run_generation_orchestrator(**_base_kwargs())

    assert isinstance(raw, dict)
    assert "insights" in raw
    assert "curiosity_insights" in raw


def test_a_single_batch_card_count():
    batch1 = _result(1, insights=[_card("card-1"), _card("card-2")])
    curio1 = _result(2, curiosity=[_curio_card("curiosity-1")])

    with patch("backend.services.generation_orchestrator.generate_batch") as mock_gen:
        mock_gen.side_effect = [batch1, curio1]
        raw = run_generation_orchestrator(**_base_kwargs())

    assert len(raw["insights"])           == 2
    assert len(raw["curiosity_insights"]) == 1


def test_a_required_package_fields_present():
    batch1 = _result(1, insights=[_card("card-1")])
    curio1 = _result(2, curiosity=[_curio_card("curiosity-1")])

    with patch("backend.services.generation_orchestrator.generate_batch") as mock_gen:
        mock_gen.side_effect = [batch1, curio1]
        raw = run_generation_orchestrator(**_base_kwargs())

    for key in ("package_headline", "content_mix", "learning_thread", "action_item",
                "insights", "curiosity_insights"):
        assert key in raw, f"Missing key: {key}"


# ── Test B: 2 core batches (8 articles) ──────────────────────────────────────

def test_b_two_batches_8_articles_calls_generate_batch_correctly():
    batch1 = _result(1, insights=[_card(f"card-{i}") for i in range(1, 5)])
    batch2 = _result(2, insights=[_card(f"card-{i}") for i in range(5, 9)])
    curio1 = _result(3, curiosity=[_curio_card("curiosity-1")])

    with patch("backend.services.generation_orchestrator.generate_batch") as mock_gen:
        mock_gen.side_effect = [batch1, batch2, curio1]
        raw = run_generation_orchestrator(
            **_base_kwargs(
                daily_core_article_count=8,
                core_articles=[_art(i) for i in range(8)],
            )
        )

    assert mock_gen.call_count == 3
    assert len(raw["insights"]) == 8


def test_b_two_batches_cards_merged_in_order():
    c1 = _card("card-1", url="https://source1.com/article")
    c2 = _card("card-2", url="https://source2.com/article")
    c3 = _card("card-3", url="https://source3.com/article")
    c4 = _card("card-4", url="https://source4.com/article")

    batch1 = _result(1, insights=[c1, c2])
    batch2 = _result(2, insights=[c3, c4])
    curio1 = _result(3, curiosity=[_curio_card("curiosity-1")])

    with patch("backend.services.generation_orchestrator.generate_batch") as mock_gen:
        mock_gen.side_effect = [batch1, batch2, curio1]
        raw = run_generation_orchestrator(
            **_base_kwargs(
                daily_core_article_count=8,
                core_articles=[_art(i) for i in range(8)],
            )
        )

    ids = [c["id"] for c in raw["insights"]]
    assert ids == ["card-1", "card-2", "card-3", "card-4"]


# ── Test C: 3 batches (8 core + 2 curiosity) ─────────────────────────────────

def test_c_three_batches_core_and_curiosity():
    batch1 = _result(1, insights=[_card(f"card-{i}") for i in range(1, 5)])
    batch2 = _result(2, insights=[_card(f"card-{i}") for i in range(5, 9)])
    curio1 = _result(3, curiosity=[_curio_card("curiosity-1"), _curio_card("curiosity-2")])

    with patch("backend.services.generation_orchestrator.generate_batch") as mock_gen:
        mock_gen.side_effect = [batch1, batch2, curio1]
        raw = run_generation_orchestrator(
            **_base_kwargs(
                daily_core_article_count=8,
                core_articles=[_art(i) for i in range(8)],
                curiosity_articles=[_art(i + 100) for i in range(2)],
            )
        )

    assert len(raw["insights"])           == 8
    assert len(raw["curiosity_insights"]) == 2


def test_c_generate_batch_called_once_per_batch():
    batch1 = _result(1, insights=[_card("card-1")])
    batch2 = _result(2, insights=[_card("card-2")])
    curio1 = _result(3, curiosity=[_curio_card("curiosity-1")])

    with patch("backend.services.generation_orchestrator.generate_batch") as mock_gen:
        mock_gen.side_effect = [batch1, batch2, curio1]
        run_generation_orchestrator(
            **_base_kwargs(
                daily_core_article_count=8,
                core_articles=[_art(i) for i in range(8)],
            )
        )

    assert mock_gen.call_count == 3


# ── Test D: merge order ───────────────────────────────────────────────────────

def test_d_merge_preserves_batch_order():
    cards_b1 = [_card(f"b1-card-{i}") for i in range(3)]
    cards_b2 = [_card(f"b2-card-{i}") for i in range(3)]
    cards_curio = [_curio_card("c-1"), _curio_card("c-2")]

    results = [
        _result(1, insights=cards_b1),
        _result(2, insights=cards_b2),
        _result(3, curiosity=cards_curio),
    ]
    raw = merge_batch_results(results, day_number=5)

    ids = [c["id"] for c in raw["insights"]]
    assert ids == [c["id"] for c in cards_b1 + cards_b2]


def test_d_merge_curiosity_appears_after_core():
    results = [
        _result(1, insights=[_card("card-1")]),
        _result(2, curiosity=[_curio_card("curiosity-1")]),
    ]
    raw = merge_batch_results(results, day_number=1)
    assert raw["insights"][0]["id"]           == "card-1"
    assert raw["curiosity_insights"][0]["id"] == "curiosity-1"


def test_d_merge_empty_batches_handled():
    raw = merge_batch_results([], day_number=1)
    assert raw["insights"] == []
    assert raw["curiosity_insights"] == []


# ── Test E: merge structure ───────────────────────────────────────────────────

def test_e_merge_has_package_headline():
    raw = merge_batch_results([_result(1, insights=[_card("c-1")])], day_number=7)
    assert raw["package_headline"]
    assert "7" in raw["package_headline"]


def test_e_merge_content_mix_counts_correct():
    results = [
        _result(1, insights=[_card("c-1"), _card("c-2")]),
        _result(2, curiosity=[_curio_card("q-1")]),
    ]
    raw = merge_batch_results(results, day_number=1)
    assert "2" in raw["content_mix"]
    assert "1" in raw["content_mix"]


def test_e_merge_learning_thread_is_string():
    raw = merge_batch_results([_result(1)], day_number=1)
    assert isinstance(raw["learning_thread"], str)


def test_e_merge_action_item_is_string():
    raw = merge_batch_results([_result(1)], day_number=1)
    assert isinstance(raw["action_item"], str)


# ── Test F: batch failure propagation ────────────────────────────────────────

def test_f_batch_failure_raises_runtime_error():
    import pytest

    def fail_on_batch2(bp, ctx, **kw):
        if bp.batch_id == 2:
            raise ValueError("Simulated batch 2 failure")
        return _result(bp.batch_id, insights=[_card(f"card-{bp.batch_id}")])

    with pytest.raises(RuntimeError) as exc_info:
        with patch("backend.services.generation_orchestrator.generate_batch") as mock_gen:
            mock_gen.side_effect = fail_on_batch2
            run_generation_orchestrator(
                **_base_kwargs(
                    daily_core_article_count=8,
                    core_articles=[_art(i) for i in range(8)],
                )
            )

    msg = str(exc_info.value)
    assert "batch=2 failed" in msg


def test_f_failure_message_names_succeeded_batches():
    import pytest

    call_count = [0]

    def fail_on_second(bp, ctx, **kw):
        call_count[0] += 1
        if call_count[0] == 2:
            raise ValueError("Second call failure")
        return _result(bp.batch_id, insights=[_card(f"card-{bp.batch_id}")])

    with pytest.raises(RuntimeError) as exc_info:
        with patch("backend.services.generation_orchestrator.generate_batch") as mock_gen:
            mock_gen.side_effect = fail_on_second
            run_generation_orchestrator(
                **_base_kwargs(
                    daily_core_article_count=8,
                    core_articles=[_art(i) for i in range(8)],
                )
            )

    msg = str(exc_info.value)
    assert "Succeeded" in msg
    assert "Failures" in msg


def test_f_all_batches_fail_raises():
    import pytest

    with pytest.raises(RuntimeError):
        with patch("backend.services.generation_orchestrator.generate_batch") as mock_gen:
            mock_gen.side_effect = RuntimeError("All batches explode")
            run_generation_orchestrator(**_base_kwargs())


# ── Test G: feature flag ──────────────────────────────────────────────────────

def test_g_multi_call_flag_defaults_false():
    from backend.config import MULTI_CALL_GENERATION
    assert MULTI_CALL_GENERATION is False


def test_g_batch_generation_result_dataclass_fields():
    r = _result(1, insights=[_card("c-1")])
    assert r.batch_id == 1
    assert r.prompt_tokens == 500
    assert r.completion_tokens == 0
    assert isinstance(r.generation_time_ms, float)
    assert r.error is None


def test_g_batch_generation_result_error_field():
    r = BatchGenerationResult(
        batch_id=2, insights=[], curiosity_insights=[],
        prompt_tokens=0, completion_tokens=0,
        generation_time_ms=0.0, source_ids_used=[],
        error="timeout",
    )
    assert r.error == "timeout"
