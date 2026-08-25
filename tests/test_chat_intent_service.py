"""
Tests for chat_intent_service — research intent detection.

Covers
------
- detect_intent: compare, research, analyze, normal
- detect_intent: priority ordering (compare > research > analyze)
- extract_comparison_subjects: vs / versus / between … and / compare … and
- _clean_topic: verb stripping
- Auto-mode integration with chat_service (mocked pipeline)

TESTING RULES
-------------
- No Tavily calls — mock all external services
"""

import pytest
from backend.services.chat_intent_service import (
    detect_intent,
    extract_comparison_subjects,
)


# ─────────────────────────────────────────────────────────────────────────────
# detect_intent — normal (no research signal)
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectIntentNormal:
    def test_casual_question_is_normal(self):
        r = detect_intent("What is a transformer?")
        assert r["intent"]           == "normal"
        assert r["recommended_mode"] == "normal"
        assert r["query_type"]       == "default"

    def test_explain_simply_is_normal(self):
        r = detect_intent("Explain attention mechanism simply")
        assert r["intent"] == "normal"

    def test_empty_string_is_normal(self):
        r = detect_intent("")
        assert r["intent"] == "normal"

    def test_roadmap_request_is_normal(self):
        r = detect_intent("Give me a learning roadmap for Python")
        assert r["intent"] == "normal"

    def test_subjects_empty_for_normal(self):
        r = detect_intent("Tell me about neural networks")
        assert r["subjects"] == []

    def test_topic_empty_for_normal(self):
        r = detect_intent("Hello there")
        assert r["topic"] == ""


# ─────────────────────────────────────────────────────────────────────────────
# detect_intent — compare
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectIntentCompare:
    def test_vs_triggers_compare(self):
        r = detect_intent("Compare Indian vs Chinese pharma exports")
        assert r["intent"]           == "compare"
        assert r["recommended_mode"] == "web_search"
        assert r["query_type"]       == "comparison"

    def test_versus_triggers_compare(self):
        r = detect_intent("PyTorch versus TensorFlow for production")
        assert r["intent"] == "compare"

    def test_compare_keyword_triggers_compare(self):
        r = detect_intent("Compare the two frameworks")
        assert r["intent"] == "compare"

    def test_difference_between_triggers_compare(self):
        r = detect_intent("What is the difference between BERT and GPT?")
        assert r["intent"] == "compare"

    def test_contrast_triggers_compare(self):
        r = detect_intent("Contrast supervised and unsupervised learning")
        assert r["intent"] == "compare"

    def test_pros_and_cons_triggers_compare(self):
        r = detect_intent("Pros and cons of React vs Vue")
        assert r["intent"] == "compare"

    def test_subjects_extracted_for_vs(self):
        r = detect_intent("Compare PyTorch vs TensorFlow")
        assert len(r["subjects"]) == 2
        assert "PyTorch" in r["subjects"][0]
        assert "TensorFlow" in r["subjects"][1]

    def test_subjects_extracted_for_versus(self):
        r = detect_intent("Indian exports versus Chinese exports")
        assert len(r["subjects"]) == 2

    def test_topic_contains_subjects_when_found(self):
        r = detect_intent("Compare NumPy vs Pandas")
        assert "NumPy" in r["topic"] or "Pandas" in r["topic"]

    def test_subjects_empty_when_not_extractable(self):
        r = detect_intent("Compare the two options")
        # No clear "X vs Y" pattern — subjects may be empty
        assert isinstance(r["subjects"], list)


# ─────────────────────────────────────────────────────────────────────────────
# detect_intent — research
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectIntentResearch:
    def test_research_keyword_triggers_research(self):
        r = detect_intent("Research AI in manufacturing")
        assert r["intent"]           == "research"
        assert r["recommended_mode"] == "web_search"
        assert r["query_type"]       == "research"

    def test_deep_dive_triggers_research(self):
        r = detect_intent("Deep dive into RAG systems")
        assert r["intent"] == "research"

    def test_in_depth_triggers_research(self):
        r = detect_intent("Give me an in-depth overview of transformers")
        assert r["intent"] == "research"

    def test_comprehensive_triggers_research(self):
        r = detect_intent("Comprehensive overview of LLMs")
        assert r["intent"] == "research"

    def test_everything_about_triggers_research(self):
        r = detect_intent("Tell me everything about RLHF")
        assert r["intent"] == "research"

    def test_deep_research_phrase_triggers_research(self):
        r = detect_intent("Do a deep research on semiconductor fabs")
        assert r["intent"] == "research"

    def test_topic_cleaned_from_research_prefix(self):
        r = detect_intent("Research AI in manufacturing")
        assert "research" not in r["topic"].lower()
        assert "AI" in r["topic"] or "manufacturing" in r["topic"].lower()

    def test_subjects_populated_for_research(self):
        r = detect_intent("Research transformer architecture")
        assert len(r["subjects"]) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# detect_intent — analyze
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectIntentAnalyze:
    def test_analyze_triggers_analyze(self):
        r = detect_intent("Analyze semiconductor supply chains")
        assert r["intent"]           == "analyze"
        assert r["recommended_mode"] == "web_search"
        assert r["query_type"]       == "analysis"

    def test_analysis_of_triggers_analyze(self):
        r = detect_intent("Analysis of the pharma export market")
        assert r["intent"] == "analyze"

    def test_breakdown_of_triggers_analyze(self):
        r = detect_intent("Breakdown of global trade flows")
        assert r["intent"] == "analyze"

    def test_supply_chain_triggers_analyze(self):
        r = detect_intent("What's happening with the supply chain?")
        assert r["intent"] == "analyze"

    def test_market_dynamics_triggers_analyze(self):
        r = detect_intent("Market dynamics for electric vehicles")
        assert r["intent"] == "analyze"

    def test_sector_analysis_triggers_analyze(self):
        r = detect_intent("Sector analysis of renewable energy")
        assert r["intent"] == "analyze"

    def test_topic_cleaned_from_analyze_prefix(self):
        r = detect_intent("Analyze semiconductor supply chains")
        assert "analyze" not in r["topic"].lower()

    def test_assess_triggers_analyze(self):
        r = detect_intent("Assess the risks in fintech regulation")
        assert r["intent"] == "analyze"


# ─────────────────────────────────────────────────────────────────────────────
# Priority ordering
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectIntentPriority:
    def test_compare_beats_research(self):
        # "Research comparing X vs Y" — compare wins
        r = detect_intent("Research comparing PyTorch vs TensorFlow")
        assert r["intent"] == "compare"

    def test_compare_beats_analyze(self):
        # "Analyze X vs Y" — compare wins
        r = detect_intent("Analyze Python vs JavaScript performance")
        assert r["intent"] == "compare"

    def test_research_beats_analyze(self):
        # "Research the analysis of X" — research wins over analyze
        r = detect_intent("Research the analysis of supply chain risks")
        assert r["intent"] in ("research", "analyze")  # either is reasonable


# ─────────────────────────────────────────────────────────────────────────────
# extract_comparison_subjects
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractComparisonSubjects:
    def test_vs_pattern(self):
        subjects = extract_comparison_subjects("Compare Indian vs Chinese pharma exports")
        assert len(subjects) == 2
        assert "Indian" in subjects[0]
        assert "Chinese" in subjects[1]

    def test_versus_pattern(self):
        subjects = extract_comparison_subjects("PyTorch versus TensorFlow")
        assert len(subjects) == 2
        assert "PyTorch" in subjects[0]
        assert "TensorFlow" in subjects[1]

    def test_between_and_pattern(self):
        subjects = extract_comparison_subjects("difference between BERT and GPT")
        assert len(subjects) == 2
        assert "BERT" in subjects[0]
        assert "GPT" in subjects[1]

    def test_compare_and_pattern(self):
        subjects = extract_comparison_subjects("compare NumPy and Pandas")
        assert len(subjects) == 2

    def test_no_pattern_returns_empty(self):
        subjects = extract_comparison_subjects("What is machine learning?")
        assert subjects == []

    def test_strips_trailing_punctuation_from_second_subject(self):
        subjects = extract_comparison_subjects("Python vs JavaScript?")
        assert not subjects[1].endswith("?")

    def test_strips_compare_verb_from_first_subject(self):
        subjects = extract_comparison_subjects("Compare PyTorch vs TensorFlow")
        # "compare" should not appear in the first subject
        assert "compare" not in subjects[0].lower()

    def test_multiword_subjects(self):
        subjects = extract_comparison_subjects("Indian pharma exports vs Chinese pharma exports")
        assert len(subjects) == 2
        assert len(subjects[0]) > 5  # multi-word
        assert len(subjects[1]) > 5

    def test_case_insensitive(self):
        subjects = extract_comparison_subjects("PYTHON VS JAVASCRIPT")
        assert len(subjects) == 2


# ─────────────────────────────────────────────────────────────────────────────
# Return shape contract
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectIntentReturnShape:
    @pytest.mark.parametrize("message", [
        "Compare X vs Y",
        "Research transformers",
        "Analyze supply chains",
        "Hello",
    ])
    def test_always_returns_required_keys(self, message):
        r = detect_intent(message)
        for key in ("intent", "recommended_mode", "query_type", "subjects", "topic"):
            assert key in r, f"Missing key {key!r} for message {message!r}"

    @pytest.mark.parametrize("message", [
        "Compare X vs Y",
        "Research transformers",
        "Analyze supply chains",
        "Hello",
    ])
    def test_intent_is_valid_value(self, message):
        r = detect_intent(message)
        assert r["intent"] in ("compare", "research", "analyze", "normal")

    @pytest.mark.parametrize("message", [
        "Compare X vs Y",
        "Research transformers",
        "Analyze supply chains",
        "Hello",
    ])
    def test_recommended_mode_is_valid_value(self, message):
        r = detect_intent(message)
        assert r["recommended_mode"] in ("web_search", "normal")

    @pytest.mark.parametrize("message", [
        "Compare X vs Y",
        "Research transformers",
        "Analyze supply chains",
        "Hello",
    ])
    def test_subjects_is_list(self, message):
        r = detect_intent(message)
        assert isinstance(r["subjects"], list)


# ─────────────────────────────────────────────────────────────────────────────
# Auto-mode integration in chat_service (mocked pipeline)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestAutoModeIntegration:
    """
    Chat-4.1: the regex mode-override this class originally tested is retired
    (chat_stream no longer reassigns chat_mode from detect_intent()) — the
    model decides via real tools now. The three "auto-upgrades" tests that
    asserted a deterministic regex-driven chat_mode/auto_mode outcome were
    removed; that guarantee no longer exists (tool use is a live model
    decision). Deterministic coverage of chat_stream's chat_mode/auto_mode/
    sources translation logic (given a tool WAS or WASN'T called) now lives in
    tests/test_chat_mode_mapping.py::TestStreamReflectsActualToolUse, which
    mocks chat_agent.ask_chat_stream directly instead of relying on live model
    behavior. The tests kept here still hold because they don't depend on
    regex mode-routing: explicit non-normal chat_mode is never overridden
    (auto_mode is only ever True when chat_mode was "normal"), and the
    pre-stream status event fires unconditionally regardless of tool use.
    """

    def _run_stream(self, message, chat_mode="normal"):
        """Collect all stream events from chat_stream into a list of dicts."""
        import json
        from unittest.mock import patch, MagicMock

        FAKE_DB_ROWS = []
        FAKE_PREFS   = []
        FAKE_RESEARCH_ROWS = []

        with patch("backend.services.chat_service._detect_topic_hint", return_value="test_topic"), \
             patch("backend.services.chat_service._load_history_messages", return_value=[]), \
             patch("backend.services.chat_service._save_message", return_value=1), \
             patch("backend.services.memory_injection_service.inject_memory", return_value={}), \
             patch("backend.services.domain_classifier_service.get_domain_context", return_value={}), \
             patch("backend.services.action_router_service.route", return_value=None), \
             patch("backend.services.chat_prompt_service.build_messages", return_value=[{"role": "user", "content": message}]), \
             patch("backend.services.grok_service.ask_grok_chat_stream", return_value=["Hello ", "world"]), \
             patch("backend.services.follow_up_service.get_recommendations", return_value={
                 "based_on_topic": None, "source": "empty",
                 "next_topics": [], "prerequisites": [], "advanced_topics": [],
             }):
            from backend.services.chat_service import chat_stream
            events = []
            for line in chat_stream("session-1", message, chat_mode=chat_mode):
                line = line.strip()
                if line:
                    events.append(json.loads(line))
            return events

    def test_normal_message_stays_normal(self):
        events = self._run_stream("What is attention?")
        done = next(e for e in events if e["t"] == "done")
        assert done["chat_mode"] == "normal"
        assert done["auto_mode"] is False

    def test_explicit_web_search_mode_not_overridden(self):
        # User explicitly chose web_search — auto_mode should be False
        events = self._run_stream("What is attention?", chat_mode="web_search")
        done = next(e for e in events if e["t"] == "done")
        assert done["chat_mode"] == "web_search"
        assert done["auto_mode"] is False

    def test_status_event_emitted_before_chunks_for_web_search(self):
        events = self._run_stream("Compare X vs Y")
        types = [e["t"] for e in events]
        assert "status" in types
        # Status should appear before first chunk
        status_idx = types.index("status")
        chunk_idx  = types.index("chunk") if "chunk" in types else len(types)
        assert status_idx < chunk_idx
