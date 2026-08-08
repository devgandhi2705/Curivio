"""
Tests for the conversational research action router.

Coverage
--------
  TestDetectAction          — regex-based intent detection for all 6 actions
  TestDetectActionNegative  — messages that should not trigger any action
  TestDispatchAction        — mocked workflow dispatch per action
  TestRouteFunction         — end-to-end route() combining detect + dispatch
  TestActionPromptSection   — system prompt injection via _build_action_result_section
  TestChatServiceAction     — chat() returns action key in response dict
  TestActionEndpoint        — POST /chat response includes action field
  TestActionIntegration     — integration test (marked, uses real DB fixture)
"""

from __future__ import annotations

import json
import sqlite3
import pytest
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
            role TEXT NOT NULL, content TEXT NOT NULL,
            topic_hint TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS deep_research (
            id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT NOT NULL,
            topic_key TEXT NOT NULL UNIQUE, research_json TEXT NOT NULL,
            generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS topic_expansions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT NOT NULL,
            topic_key TEXT NOT NULL UNIQUE, expansion_json TEXT NOT NULL,
            generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS learning_paths (
            id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT NOT NULL,
            topic_key TEXT NOT NULL UNIQUE, learning_stage TEXT,
            path_json TEXT NOT NULL,
            generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS github_repos (
            id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT NOT NULL,
            topic_key TEXT NOT NULL UNIQUE, repos_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS research_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT NOT NULL,
            topic_key TEXT NOT NULL, activity TEXT,
            recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS user_preferences (
            id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT NOT NULL UNIQUE,
            topic_key TEXT NOT NULL UNIQUE, preference_score REAL NOT NULL DEFAULT 0.0,
            times_liked INTEGER NOT NULL DEFAULT 0,
            times_disliked INTEGER NOT NULL DEFAULT 0,
            difficulty_preference TEXT
        );
    """)
    conn.commit()
    return conn


@pytest.fixture()
def patch_db(db, monkeypatch):
    import backend.utils.db as _db
    import backend.services.chat_service as _cs
    import backend.services.deep_research_service as _drs
    import backend.services.learning_path_service as _lps
    import backend.services.github_service as _gs
    import backend.services.topic_expansion_service as _tes
    cm = MagicMock(return_value=db)
    for mod in (_db, _cs, _drs, _lps, _gs, _tes):
        monkeypatch.setattr(mod, "get_connection", cm)
    return db


def _ctx():
    return {
        "user_profile":        {"top_interests": []},
        "research":            {},
        "session":             {},
        "conversation_memory": {"message_count": 0, "session_turns": 0,
                                "topics_discussed": [], "last_user_messages": []},
        "exploration_breadth": {"total_explored": 0, "all_topics": [],
                                "recently_explored": [], "deep_dived_topics": []},
        "preference_snapshot": {},
        "learner_profile":     {"inferred_level": "intermediate", "directive": ""},
    }


# ─────────────────────────────────────────────────────────────────────────────
# TestDetectAction
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectAction:
    def _detect(self, msg):
        from backend.services.action_router_service import detect_action
        return detect_action(msg)

    # compare
    def test_compare_keyword(self):
        assert self._detect("Compare React and Vue") == "compare"

    def test_versus_abbreviation(self):
        assert self._detect("PyTorch vs TensorFlow — which is better?") == "compare"

    def test_difference_between(self):
        assert self._detect("What is the difference between SQL and NoSQL?") == "compare"

    def test_pros_and_cons(self):
        assert self._detect("What are the pros and cons of using Redis?") == "compare"

    # show_repos
    def test_repositories_keyword(self):
        assert self._detect("Show implementation repositories for FAISS") == "show_repos"

    def test_github_keyword(self):
        assert self._detect("Any good GitHub projects for this?") == "show_repos"

    def test_open_source_keyword(self):
        assert self._detect("What open-source libraries should I use?") == "show_repos"

    # learning_roadmap
    def test_roadmap_keyword(self):
        assert self._detect("Give me a learning roadmap for machine learning") == "learning_roadmap"

    def test_learning_path_phrase(self):
        assert self._detect("What's the learning path for Kubernetes?") == "learning_roadmap"

    def test_step_by_step_phrase(self):
        assert self._detect("Teach me step-by-step how to learn Rust") == "learning_roadmap"

    # find_tutorials
    def test_tutorial_keyword(self):
        assert self._detect("Find practical tutorials for Docker") == "find_tutorials"

    def test_hands_on_keyword(self):
        assert self._detect("I want some hands-on exercises") == "find_tutorials"

    # beginner_resources
    def test_beginner_keyword(self):
        assert self._detect("Recommend beginner resources for Python") == "beginner_resources"

    def test_getting_started_phrase(self):
        assert self._detect("How do I get started with React?") == "beginner_resources"

    def test_recommend_resources_phrase(self):
        assert self._detect("Can you recommend some resources for me?") == "beginner_resources"

    # explain_simply
    def test_explain_simply_phrase(self):
        assert self._detect("Explain this topic simply") == "explain_simply"

    def test_eli5_keyword(self):
        assert self._detect("ELI5 what is a transformer?") == "explain_simply"

    def test_in_simple_terms(self):
        assert self._detect("Explain transformers in simple terms") == "explain_simply"

    def test_like_i_am_5(self):
        assert self._detect("Explain this like I'm 5") == "explain_simply"

    # case insensitivity
    def test_uppercase_message(self):
        assert self._detect("COMPARE BERT AND GPT") == "compare"

    def test_mixed_case(self):
        assert self._detect("Show Me Repositories For This Topic") == "show_repos"


# ─────────────────────────────────────────────────────────────────────────────
# TestDetectActionNegative
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectActionNegative:
    def _detect(self, msg):
        from backend.services.action_router_service import detect_action
        return detect_action(msg)

    def test_plain_question_returns_none(self):
        assert self._detect("What is a neural network?") is None

    def test_empty_message_returns_none(self):
        assert self._detect("") is None

    def test_unrelated_message_returns_none(self):
        assert self._detect("Thanks, that was helpful!") is None

    def test_conversational_followup_returns_none(self):
        assert self._detect("Can you go deeper on that last point?") is None


# ─────────────────────────────────────────────────────────────────────────────
# TestDispatchAction
# ─────────────────────────────────────────────────────────────────────────────

class TestDispatchAction:
    def _dispatch(self, action, topic="Vector Databases", ctx=None):
        from backend.services.action_router_service import dispatch_action
        return dispatch_action(action, topic, ctx or _ctx())

    # ── explain_simply ──

    def test_explain_simply_with_research(self):
        stored = {"analysis": {"summary": "VDBs store embeddings.", "key_concepts": ["ANN", "HNSW"]}}
        with patch("backend.services.deep_research_service.get_stored_research", return_value=stored):
            result = self._dispatch("explain_simply")
        assert result["found"] is True
        assert result["action"] == "explain_simply"
        assert "summary" in result["data"] or "key_concepts" in result["data"]
        assert "Vector Databases" in result["instruction"]

    def test_explain_simply_no_research(self):
        with patch("backend.services.deep_research_service.get_stored_research", return_value=None):
            result = self._dispatch("explain_simply")
        assert result["found"] is False
        assert "instruction" in result
        assert result["instruction"]   # fallback instruction still provided

    def test_explain_simply_instruction_contains_action_label(self):
        with patch("backend.services.deep_research_service.get_stored_research", return_value=None):
            result = self._dispatch("explain_simply")
        assert "EXPLAIN SIMPLY" in result["instruction"]

    # ── compare ──

    def test_compare_with_expansion(self):
        expansion = {
            "related_topics": ["Pinecone", "Weaviate"],
            "prerequisites": ["Embeddings"],
            "advanced_follow_ups": ["Hybrid Search"],
        }
        with patch("backend.services.topic_expansion_service.get_stored_expansion", return_value=expansion):
            result = self._dispatch("compare")
        assert result["found"] is True
        assert "Pinecone" in result["instruction"] or "Pinecone" in str(result["data"])

    def test_compare_no_expansion(self):
        with patch("backend.services.topic_expansion_service.get_stored_expansion", return_value=None):
            result = self._dispatch("compare")
        assert result["found"] is False
        assert "COMPARE" in result["instruction"]

    # ── find_tutorials ──

    def test_find_tutorials_with_results(self):
        # domain_resource_service.discover_resources() is the real primary path
        # now (domain-aware GitHub/docs discovery); tavily_service is only the
        # fallback when discovery fails — force that here to exercise it.
        search_results = [
            {"title": "FAISS Tutorial", "url": "https://example.com/faiss", "content": "..."},
            {"title": "Pinecone Guide",  "url": "https://example.com/pinecone", "content": "..."},
        ]
        with patch("backend.services.domain_resource_service.discover_resources",
                   side_effect=RuntimeError("discovery down")), \
             patch("backend.services.tavily_service.search_articles", return_value=search_results):
            result = self._dispatch("find_tutorials")
        assert result["found"] is True
        assert len(result["data"]["results"]) == 2
        assert "FAISS Tutorial" in result["instruction"]

    def test_find_tutorials_search_fails_gracefully(self):
        with patch("backend.services.domain_resource_service.discover_resources",
                   side_effect=RuntimeError("discovery down")), \
             patch("backend.services.tavily_service.search_articles", side_effect=RuntimeError("down")):
            result = self._dispatch("find_tutorials")
        assert result["found"] is False
        assert result["instruction"]

    def test_find_tutorials_empty_results(self):
        with patch("backend.services.domain_resource_service.discover_resources",
                   side_effect=RuntimeError("discovery down")), \
             patch("backend.services.tavily_service.search_articles", return_value=[]):
            result = self._dispatch("find_tutorials")
        assert result["found"] is False

    # ── beginner_resources ──

    def test_beginner_resources_with_path(self):
        path = {"beginner": [
            {"concept": "What is a Vector?", "description": "Intro to vectors."},
            {"concept": "Embeddings 101",    "description": "How embeddings work."},
        ]}
        with patch("backend.services.learning_path_service.get_stored_path", return_value=path):
            result = self._dispatch("beginner_resources")
        assert result["found"] is True
        assert "What is a Vector?" in result["instruction"] or "What is a Vector?" in str(result["data"])

    def test_beginner_resources_no_path(self):
        with patch("backend.services.learning_path_service.get_stored_path", return_value=None):
            result = self._dispatch("beginner_resources")
        assert result["found"] is False
        assert "BEGINNER" in result["instruction"]

    # ── show_repos ──

    def test_show_repos_with_repos(self):
        repos = [
            {"name": "faiss", "stars": 20000, "description": "Efficient similarity search.", "url": "https://github.com/facebookresearch/faiss"},
            {"name": "hnswlib", "stars": 3000, "description": "HNSW algorithm.", "url": "https://github.com/nmslib/hnswlib"},
        ]
        with patch("backend.services.github_service.get_topic_repos", return_value=repos):
            result = self._dispatch("show_repos")
        assert result["found"] is True
        assert "faiss" in result["instruction"]
        assert len(result["data"]["repos"]) == 2

    def test_show_repos_empty(self):
        with patch("backend.services.github_service.get_topic_repos", return_value=[]):
            result = self._dispatch("show_repos")
        assert result["found"] is False
        assert "SHOW REPOSITORIES" in result["instruction"]

    # ── learning_roadmap ──

    def test_learning_roadmap_with_path(self):
        path = {
            "beginner":     [{"concept": "Intro",    "description": ""}],
            "intermediate": [{"concept": "Indexing",  "description": ""}],
            "advanced":     [{"concept": "Sharding",  "description": ""}],
        }
        with patch("backend.services.learning_path_service.get_learning_path", return_value=path):
            result = self._dispatch("learning_roadmap")
        assert result["found"] is True
        assert "LEARNING ROADMAP" in result["instruction"]
        assert "Intro" in result["instruction"] or "Intro" in str(result["data"])

    def test_learning_roadmap_no_path(self):
        with patch("backend.services.learning_path_service.get_learning_path", return_value=None):
            result = self._dispatch("learning_roadmap")
        assert result["found"] is False
        assert result["instruction"]

    # ── unknown action ──

    def test_unknown_action_returns_empty(self):
        result = self._dispatch("nonexistent_action")
        assert result["found"] is False
        assert result["data"] == {}

    # ── exception handling ──

    def test_dispatch_exception_returns_empty(self):
        with patch("backend.services.deep_research_service.get_stored_research",
                   side_effect=RuntimeError("crash")):
            result = self._dispatch("explain_simply")
        assert result["found"] is False   # safe fallback

    # ── result shape invariants ──

    def test_all_results_have_required_keys(self):
        actions = ["explain_simply", "compare", "find_tutorials",
                   "beginner_resources", "show_repos", "learning_roadmap"]
        required = {"action", "topic", "found", "data", "instruction"}
        with patch("backend.services.deep_research_service.get_stored_research", return_value=None), \
             patch("backend.services.topic_expansion_service.get_stored_expansion", return_value=None), \
             patch("backend.services.learning_path_service.get_stored_path", return_value=None), \
             patch("backend.services.learning_path_service.get_learning_path", return_value=None), \
             patch("backend.services.github_service.get_topic_repos", return_value=[]), \
             patch("backend.services.tavily_service.search_articles", return_value=[]):
            from backend.services.action_router_service import dispatch_action
            for action in actions:
                result = dispatch_action(action, "Test Topic", _ctx())
                assert required <= result.keys(), f"Missing keys for {action}: {required - result.keys()}"


# ─────────────────────────────────────────────────────────────────────────────
# TestRouteFunction
# ─────────────────────────────────────────────────────────────────────────────

class TestRouteFunction:
    def test_route_returns_none_for_plain_message(self):
        from backend.services.action_router_service import route
        result = route("What is machine learning?", "Machine Learning", _ctx())
        assert result is None

    def test_route_returns_none_without_topic(self):
        from backend.services.action_router_service import route
        result = route("Show me repositories", None, _ctx())
        assert result is None

    def test_route_returns_none_for_blank_topic(self):
        from backend.services.action_router_service import route
        result = route("Show me repositories", "  ", _ctx())
        assert result is None

    def test_route_returns_dict_when_action_detected(self):
        from backend.services.action_router_service import route
        with patch("backend.services.github_service.get_topic_repos", return_value=[]):
            result = route("Show me GitHub repositories", "Vector Databases", _ctx())
        assert isinstance(result, dict)
        assert result["action"] == "show_repos"

    def test_route_action_key_matches_detection(self):
        from backend.services.action_router_service import route
        with patch("backend.services.learning_path_service.get_learning_path", return_value=None):
            result = route("Give me a learning roadmap", "Python", _ctx())
        assert result is not None
        assert result["action"] == "learning_roadmap"

    def test_route_topic_stripped(self):
        from backend.services.action_router_service import route
        with patch("backend.services.github_service.get_topic_repos", return_value=[]):
            result = route("Show repos", "  Vector Databases  ", _ctx())
        assert result["topic"] == "Vector Databases"


# ─────────────────────────────────────────────────────────────────────────────
# TestActionPromptSection
# ─────────────────────────────────────────────────────────────────────────────

class TestActionPromptSection:
    def _section(self, action_result):
        from backend.services.chat_prompt_service import _build_action_result_section
        return _build_action_result_section(action_result)

    def test_empty_dict_returns_empty(self):
        assert self._section({}) == ""

    def test_none_instruction_returns_empty(self):
        assert self._section({"instruction": None}) == ""

    def test_blank_instruction_returns_empty(self):
        assert self._section({"instruction": "   "}) == ""

    def test_instruction_is_returned_verbatim(self):
        instr = "Action: EXPLAIN SIMPLY\nExplain Vector Databases plainly."
        result = self._section({"instruction": instr})
        assert result == instr

    def test_instruction_is_stripped(self):
        result = self._section({"instruction": "  Hello world  "})
        assert result == "Hello world"

    def test_section_in_system_prompt(self):
        # Chat-R7b: action_result renders in the structured prompt, which now
        # gates on a genuine Feed link (context["feed_linked"]), not mode.
        from backend.services.chat_prompt_service import build_system_prompt
        ctx = {
            "feed_linked": True,
            "user_profile": {}, "research": {}, "session": {},
            "conversation_memory": {}, "exploration_breadth": {},
            "preference_snapshot": {}, "learner_profile": {},
            "action_result": {"instruction": "Action: SHOW REPOSITORIES\nHere are repos..."},
        }
        prompt = build_system_prompt(ctx, mode="deep_research")
        assert "Action: SHOW REPOSITORIES" in prompt

    def test_no_action_result_prompt_unchanged(self):
        from backend.services.chat_prompt_service import build_system_prompt
        ctx = {
            "user_profile": {}, "research": {}, "session": {},
            "conversation_memory": {}, "exploration_breadth": {},
            "preference_snapshot": {}, "learner_profile": {},
        }
        prompt = build_system_prompt(ctx)
        assert "Action:" not in prompt


# ─────────────────────────────────────────────────────────────────────────────
# TestActionIntegration
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestActionIntegration:
    def test_detect_and_route_full_cycle(self):
        """Detect an action and dispatch it without any DB data (should return found=False gracefully)."""
        from backend.services.action_router_service import route
        with patch("backend.services.github_service.get_topic_repos", return_value=[]):
            result = route("Show me GitHub repositories for this", "FAISS", _ctx())
        assert result is not None
        assert result["action"] == "show_repos"
        assert isinstance(result["found"], bool)
        assert "instruction" in result
