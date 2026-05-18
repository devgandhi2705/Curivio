"""
Quick-starter prefix intent tests.

Each quick-starter in ChatInput.jsx inserts a prefix ("Research ", "Compare ",
"Analyze ", "Learning roadmap for ") that the user completes before sending.
These tests verify that the completed prompts route to the correct backend
auto-mode — no Tavily, no Groq, no deep-research pipeline is called.

Quick-starters and their expected auto-mode:
  "Research <topic>"            → deep_research
  "Compare <A> vs <B>"          → web_search   (comparison)
  "Analyze <topic>"             → deep_research
  "Learning roadmap for <X>"    → normal        (no research intent)

TESTING RULES
─────────────
- All retrieval is mocked
- No live API calls
"""

import pytest
from backend.services.chat_intent_service import detect_intent


# ─────────────────────────────────────────────────────────────────────────────
# "Research " prefix
# ─────────────────────────────────────────────────────────────────────────────

class TestResearchPrefix:
    def test_research_ai_manufacturing(self):
        r = detect_intent("Research AI in manufacturing")
        assert r["intent"]           == "research"
        assert r["recommended_mode"] == "deep_research"

    def test_research_transformer_architecture(self):
        r = detect_intent("Research transformer architecture")
        assert r["intent"]           == "research"
        assert r["recommended_mode"] == "deep_research"

    def test_research_global_supply_chains(self):
        r = detect_intent("Research global supply chains in pharma")
        assert r["intent"]           == "research"
        assert r["recommended_mode"] == "deep_research"

    def test_research_query_type_is_research(self):
        r = detect_intent("Research reinforcement learning from human feedback")
        assert r["query_type"] == "research"

    def test_research_topic_cleaned_of_prefix(self):
        r = detect_intent("Research semiconductor fabs")
        # "research" should not appear in the cleaned topic
        assert "research" not in r["topic"].lower()
        # The core subject should be retained
        assert "semiconductor" in r["topic"].lower() or "fabs" in r["topic"].lower()


# ─────────────────────────────────────────────────────────────────────────────
# "Compare " prefix
# ─────────────────────────────────────────────────────────────────────────────

class TestComparePrefix:
    def test_compare_vs_triggers_web_search(self):
        r = detect_intent("Compare Indian vs Chinese pharma exports")
        assert r["intent"]           == "compare"
        assert r["recommended_mode"] == "web_search"

    def test_compare_extracts_two_subjects(self):
        r = detect_intent("Compare PyTorch vs TensorFlow")
        assert len(r["subjects"]) == 2

    def test_compare_nvidia_vs_amd(self):
        r = detect_intent("Compare NVIDIA vs AMD for AI workloads")
        assert r["intent"]           == "compare"
        assert r["recommended_mode"] == "web_search"

    def test_compare_query_type_is_comparison(self):
        r = detect_intent("Compare React vs Vue for large apps")
        assert r["query_type"] == "comparison"

    def test_compare_bare_prefix_still_detected(self):
        # User typed "Compare " and then completed to "Compare Python and Rust"
        r = detect_intent("Compare Python and Rust for systems programming")
        assert r["intent"] == "compare"


# ─────────────────────────────────────────────────────────────────────────────
# "Analyze " prefix
# ─────────────────────────────────────────────────────────────────────────────

class TestAnalyzePrefix:
    def test_analyze_supply_chain(self):
        r = detect_intent("Analyze semiconductor supply chains")
        assert r["intent"]           == "analyze"
        assert r["recommended_mode"] == "deep_research"

    def test_analyze_market_trends(self):
        r = detect_intent("Analyze EV market trends in Asia")
        assert r["intent"]           == "analyze"
        assert r["recommended_mode"] == "deep_research"

    def test_analyze_query_type_is_analysis(self):
        r = detect_intent("Analyze the fintech regulatory landscape")
        assert r["query_type"] == "analysis"

    def test_analyze_topic_cleaned(self):
        r = detect_intent("Analyze global trade flows")
        assert "analyze" not in r["topic"].lower()

    def test_analyze_pharma_export(self):
        r = detect_intent("Analyze Indian pharma export competitiveness")
        assert r["intent"] == "analyze"


# ─────────────────────────────────────────────────────────────────────────────
# "Learning roadmap for " prefix
# ─────────────────────────────────────────────────────────────────────────────

class TestRoadmapPrefix:
    def test_roadmap_stays_normal(self):
        r = detect_intent("Learning roadmap for machine learning")
        assert r["intent"]           == "normal"
        assert r["recommended_mode"] == "normal"

    def test_roadmap_python_normal(self):
        r = detect_intent("Learning roadmap for Python")
        assert r["intent"] == "normal"

    def test_roadmap_no_subjects_extracted(self):
        r = detect_intent("Learning roadmap for data science")
        assert r["subjects"] == []

    def test_roadmap_query_type_default(self):
        r = detect_intent("Learning roadmap for deep learning")
        assert r["query_type"] == "default"


# ─────────────────────────────────────────────────────────────────────────────
# Mode override: explicit non-normal mode is NOT overridden by auto-detection
# (backend spec)
# ─────────────────────────────────────────────────────────────────────────────

class TestAutoModeWithQuickStarters:
    """
    Verify that when chat_mode is explicitly set by the user (not "normal"),
    the intent detection cannot override it. Tested end-to-end via
    chat_service.chat_stream with all external services mocked.
    """

    def _stream_done(self, message, chat_mode):
        import json
        from unittest.mock import patch
        from backend.services.chat_service import chat_stream

        with patch("backend.services.chat_service._detect_topic_hint", return_value=None), \
             patch("backend.services.chat_service._load_history_messages", return_value=[]), \
             patch("backend.services.chat_service._save_message", return_value=1), \
             patch("backend.services.memory_injection_service.inject_memory", return_value={}), \
             patch("backend.services.domain_classifier_service.get_domain_context", return_value={}), \
             patch("backend.services.action_router_service.route", return_value=None), \
             patch("backend.services.chat_prompt_service.build_messages",
                   return_value=[{"role": "user", "content": message}]), \
             patch("backend.services.grok_service.ask_grok_chat_stream", return_value=["ok"]), \
             patch("backend.services.follow_up_service.get_recommendations",
                   return_value={"based_on_topic": None, "source": "empty",
                                 "next_topics": [], "prerequisites": [], "advanced_topics": []}), \
             patch("backend.services.chat_modes_service._fetch_web_context",
                   return_value={"mode": "web_search", "query_type": "default",
                                 "subjects": [], "web_search_results": []}), \
             patch("backend.services.chat_modes_service._fetch_deep_research_context",
                   return_value={"mode": "deep_research", "query_type": "default",
                                 "deep_research_result": None}):
            events = [
                json.loads(line.strip())
                for line in chat_stream("s1", message, chat_mode=chat_mode)
                if line.strip()
            ]
        return next(e for e in events if e["t"] == "done")

    # ── Explicit web_search mode ──────────────────────────────────────────────

    def test_explicit_web_search_research_prompt_not_upgraded(self):
        # "Research X" would normally auto-upgrade to deep_research,
        # but user explicitly selected web_search — must stay web_search
        done = self._stream_done("Research AI in manufacturing", "web_search")
        assert done["chat_mode"] == "web_search"
        assert done["auto_mode"] is False

    def test_explicit_web_search_stays_on_roadmap(self):
        # Roadmap prompt + explicit web_search → web_search (intent=normal, no upgrade)
        done = self._stream_done("Learning roadmap for machine learning", "web_search")
        assert done["chat_mode"] == "web_search"
        assert done["auto_mode"] is False

    # ── Explicit deep_research mode ───────────────────────────────────────────

    def test_explicit_deep_research_compare_not_downgraded(self):
        # "Compare X vs Y" would auto-detect web_search, but user set deep_research
        done = self._stream_done("Compare PyTorch vs TensorFlow", "deep_research")
        assert done["chat_mode"] == "deep_research"
        assert done["auto_mode"] is False

    # ── Auto mode (normal → intent detection fires) ───────────────────────────

    def test_auto_research_prefix_upgrades_to_deep_research(self):
        done = self._stream_done("Research semiconductor fabs", "normal")
        assert done["chat_mode"] == "deep_research"
        assert done["auto_mode"] is True

    def test_auto_compare_prefix_upgrades_to_web_search(self):
        done = self._stream_done("Compare NVIDIA vs AMD", "normal")
        assert done["chat_mode"] == "web_search"
        assert done["auto_mode"] is True

    def test_auto_analyze_prefix_upgrades_to_deep_research(self):
        done = self._stream_done("Analyze global pharma supply chains", "normal")
        assert done["chat_mode"] == "deep_research"
        assert done["auto_mode"] is True

    def test_auto_roadmap_stays_normal(self):
        done = self._stream_done("Learning roadmap for Python", "normal")
        assert done["chat_mode"] == "normal"
        assert done["auto_mode"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Quick-starter QUICK_STARTERS constant integrity
# (mirrors the JS constant — verifies the prefixes trigger correct intents)
# ─────────────────────────────────────────────────────────────────────────────

QUICK_STARTER_SPECS = [
    ("Research ",             "deep_research"),
    ("Compare ",              "web_search"),
    ("Analyze ",              "deep_research"),
    ("Learning roadmap for ", "normal"),
]

COMPLETIONS = {
    "Research ":             "AI in manufacturing",
    "Compare ":              "Python vs JavaScript",
    "Analyze ":              "semiconductor supply chains",
    "Learning roadmap for ": "data science",
}

class TestQuickStarterPrefixToModeMapping:
    @pytest.mark.parametrize("prefix,expected_mode", QUICK_STARTER_SPECS)
    def test_completed_prompt_reaches_expected_mode(self, prefix, expected_mode):
        full_message = prefix + COMPLETIONS[prefix]
        r = detect_intent(full_message)
        assert r["recommended_mode"] == expected_mode, (
            f"Prefix {prefix!r} completed to {full_message!r} "
            f"should recommend {expected_mode!r}, got {r['recommended_mode']!r}"
        )
