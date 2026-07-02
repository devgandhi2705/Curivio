"""
Tests for Phase 9.3.4D — Package Synthesizer.

Run: python -m pytest backend/tests/test_package_synthesizer.py -v
"""

import json
import pytest
from unittest.mock import patch


def _make_card(i: int, ctype: str = "news") -> dict:
    return {
        "id":              f"card-{i}",
        "content_type":    ctype,
        "narrative_frame": "INVESTIGATIVE",
        "title":           f"Test Card {i} Title",
        "summary":         f"Summary of card {i} with key insight.",
        "primary_source":  {"title": f"Source {i}", "url": f"https://example.com/{i}"},
        "blocks":          [{"type": "evidence", "content": f"Source {i} reports finding {i}."}],
    }


def _mock_grok(headline="Today Headline Across All Cards For Test",
               thread="Cards build from mechanism A to implication B. Question: what drives C?",
               action="INVESTIGATE — Find one example of Card 1's mechanism in practice."):
    return json.dumps({
        "package_headline": headline,
        "learning_thread":  thread,
        "action_item":      action,
    })


# ── A: 4 cards ────────────────────────────────────────────────────────────────

def test_synthesize_4_cards():
    from backend.services.package_synthesizer_service import synthesize_package
    cards = [_make_card(i) for i in range(1, 5)]
    with patch("backend.services.grok_service.ask_grok", return_value=_mock_grok()):
        result = synthesize_package(cards, "Test Project", "beginner", 1)

    assert result.package_headline
    assert result.learning_thread
    assert result.action_item
    assert len(cards) == 4


# ── B: 10 cards ───────────────────────────────────────────────────────────────

def test_synthesize_10_cards():
    from backend.services.package_synthesizer_service import synthesize_package
    cards = [_make_card(i) for i in range(1, 11)]
    with patch("backend.services.grok_service.ask_grok", return_value=_mock_grok()):
        result = synthesize_package(cards, "Test Project", "advanced", 5)

    assert result.package_headline
    assert result.learning_thread
    assert result.action_item
    assert len(cards) == 10  # G: no mutation


# ── C: curiosity cards present ────────────────────────────────────────────────

def test_synthesize_with_curiosity():
    from backend.services.package_synthesizer_service import synthesize_package
    cards = [_make_card(i, "news") for i in range(1, 4)] + \
            [_make_card(i, "curiosity") for i in range(4, 6)]
    with patch("backend.services.grok_service.ask_grok", return_value=_mock_grok()):
        result = synthesize_package(cards, "Test Project", "intermediate", 2)

    assert result.package_headline
    ctypes = {c["content_type"] for c in cards}
    assert "curiosity" in ctypes


# ── D: no curiosity ───────────────────────────────────────────────────────────

def test_synthesize_no_curiosity():
    from backend.services.package_synthesizer_service import synthesize_package
    cards = [_make_card(i, "news") for i in range(1, 5)]
    with patch("backend.services.grok_service.ask_grok", return_value=_mock_grok()):
        result = synthesize_package(cards, "Test Project", "beginner", 3)

    assert result.package_headline
    ctypes = {c["content_type"] for c in cards}
    assert "curiosity" not in ctypes


# ── E: synthesis failure handling ─────────────────────────────────────────────

def test_synthesize_missing_headline_uses_fallback(caplog):
    from backend.services.package_synthesizer_service import synthesize_package
    bad_response = json.dumps({"learning_thread": "Some thread.", "action_item": "Some action."})
    with patch("backend.services.grok_service.ask_grok", return_value=bad_response):
        with caplog.at_level("WARNING", logger="backend.services.package_synthesizer_service"):
            result = synthesize_package([_make_card(1)], "Project", "beginner", 1)
    assert result.package_headline == ""
    assert "package_headline missing" in caplog.text


def test_synthesize_missing_learning_thread_uses_fallback(caplog):
    from backend.services.package_synthesizer_service import synthesize_package
    bad_response = json.dumps({"package_headline": "A headline here today.", "action_item": "Action."})
    with patch("backend.services.grok_service.ask_grok", return_value=bad_response):
        with caplog.at_level("WARNING", logger="backend.services.package_synthesizer_service"):
            result = synthesize_package([_make_card(1)], "Project", "beginner", 1)
    assert result.learning_thread == ""
    assert "learning_thread missing" in caplog.text


def test_synthesize_missing_action_item_uses_fallback(caplog):
    from backend.services.package_synthesizer_service import synthesize_package
    bad_response = json.dumps({"package_headline": "A headline.", "learning_thread": "Thread."})
    with patch("backend.services.grok_service.ask_grok", return_value=bad_response):
        with caplog.at_level("WARNING", logger="backend.services.package_synthesizer_service"):
            result = synthesize_package([_make_card(1)], "Project", "beginner", 1)
    assert result.action_item == ""
    assert "action_item missing" in caplog.text


# ── F: metadata merge ─────────────────────────────────────────────────────────

def test_orchestrator_merge_injects_synthesis():
    """synthesize_package result correctly overwrites stubs in the raw package dict."""
    from backend.services.generation_orchestrator import merge_batch_results, BatchGenerationResult
    from backend.services.package_synthesizer_service import PackageSynthesisResult

    batch = BatchGenerationResult(
        batch_id=1,
        insights=[_make_card(1)],
        curiosity_insights=[_make_card(2, "curiosity")],
        prompt_tokens=100,
        completion_tokens=0,
        generation_time_ms=500.0,
        source_ids_used=[],
    )
    raw = merge_batch_results([batch], day_number=1)

    # Simulate what run_generation_orchestrator does after merge
    synthesis = PackageSynthesisResult(
        package_headline  = "Synthesized Headline For Day One",
        learning_thread   = "Cards built from X to Y. Q: what drives Z?",
        action_item       = "INVESTIGATE — verify X claim in source.",
        prompt_tokens     = 0,
        completion_tokens = 0,
    )
    raw["package_headline"] = synthesis.package_headline
    raw["learning_thread"]  = synthesis.learning_thread
    raw["action_item"]      = synthesis.action_item

    assert raw["package_headline"] == "Synthesized Headline For Day One"
    assert raw["learning_thread"]  == "Cards built from X to Y. Q: what drives Z?"
    assert raw["action_item"]      == "INVESTIGATE — verify X claim in source."
    assert len(raw["insights"]) == 1
    assert len(raw["curiosity_insights"]) == 1


# ── G: no card mutation ───────────────────────────────────────────────────────

def test_synthesize_does_not_mutate_cards():
    from backend.services.package_synthesizer_service import synthesize_package
    cards = [_make_card(i) for i in range(1, 4)]
    originals = [c.copy() for c in cards]

    with patch("backend.services.grok_service.ask_grok", return_value=_mock_grok()):
        synthesize_package(cards, "Project", "beginner", 1)

    for before, after in zip(originals, cards):
        assert before == after, f"Card mutated: {after}"
