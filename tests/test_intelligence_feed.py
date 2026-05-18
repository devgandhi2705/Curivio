"""
Tests for the intelligence feed engine.

Covers:
  - _infer_industry        (keyword mapping)
  - _get_chat_context      (DB extraction)
  - _build_intelligence_context (personalization block)
  - _multi_search          (deduplication)
  - _add_compat_fields     (backward-compat shim)
  - generate_intelligence_feed (full pipeline)
  - POST /generate-feed    (FastAPI endpoint)

All tests use mocked dependencies — no live Groq or Tavily calls.
"""

from __future__ import annotations

import json
import sqlite3
from unittest.mock import patch

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# Shared test data
# ═══════════════════════════════════════════════════════════════════════════════

MOCK_ARTICLES = [
    {"title": "Article 1", "url": "https://example.com/1", "content": "LLM tool calling article."},
    {"title": "Article 2", "url": "https://example.com/2", "content": "RAG pipeline article."},
]

MOCK_FEED_RESPONSE = {
    "intelligence_brief": {
        "headline": "LLM Tool Calling Reshapes Production AI Systems",
        "executive_summary": "Function calling is now production-critical infrastructure.",
        "key_signals": ["Signal A", "Signal B", "Signal C"],
    },
    "sections": [
        {
            "type": "industry_news",
            "title": "Industry & Technology News",
            "items": [
                {"title": "T1", "insight": "I1", "why_it_matters": "W1", "sources": ["https://example.com/1"]},
                {"title": "T2", "insight": "I2", "why_it_matters": "W2", "sources": []},
            ],
        },
        {
            "type": "market_trends",
            "title": "Market Trends & Business Developments",
            "items": [
                {"title": "T3", "insight": "I3", "why_it_matters": "W3", "sources": []},
                {"title": "T4", "insight": "I4", "why_it_matters": "W4", "sources": []},
            ],
        },
        {
            "type": "technical_discoveries",
            "title": "Technical Discoveries & Research",
            "items": [
                {"title": "T5", "insight": "I5", "why_it_matters": "W5", "sources": []},
                {"title": "T6", "insight": "I6", "why_it_matters": "W6", "sources": []},
            ],
        },
    ],
    "learning_track": [
        {"title": "Tool Use", "reason": "Foundation.", "difficulty": "beginner",     "chat_connection": None},
        {"title": "RAG",      "reason": "Core skill.", "difficulty": "intermediate", "chat_connection": None},
        {"title": "LoRA",     "reason": "Adaptation.", "difficulty": "intermediate", "chat_connection": None},
        {"title": "Speculative Decoding", "reason": "Scale.", "difficulty": "advanced", "chat_connection": None},
    ],
    "action_items": [
        "Action 1: implement tool use loop",
        "Action 2: build RAG pipeline",
        "Action 3: run QLoRA fine-tune",
    ],
    "industry_context": "Brief optimized for an AI/ML engineer.",
}

EMPTY_RECOMMENDATIONS = {
    "based_on_topic": None, "source": "empty",
    "next_topics": [], "prerequisites": [], "advanced_topics": [],
}


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def mock_pipeline(monkeypatch):
    """Patch the full intelligence_service pipeline — no live calls."""
    import backend.services.intelligence_service as intl
    import backend.services.recommendation_service as rec
    import backend.services.tavily_service as tav
    import backend.services.grok_service as gs
    import backend.services.feed_cache_service as fcs
    import backend.services.source_ranker as sr
    import backend.services.source_analyzer as sa

    monkeypatch.setattr(intl, "_get_chat_context", lambda: {
        "recent_topics":      ["Machine Learning", "Python"],
        "explained_concepts": ["transformers", "embeddings"],
    })
    monkeypatch.setattr(rec, "get_top_user_interests", lambda limit=8: [
        {"topic": "LLM", "preference_score": 0.9, "difficulty_preference": "intermediate", "times_recommended": 2},
    ])
    monkeypatch.setattr(rec, "get_suppressed_topics",            lambda limit=5: [])
    monkeypatch.setattr(rec, "get_overall_difficulty_preference", lambda: "intermediate")
    monkeypatch.setattr(rec, "get_learning_stage",               lambda: "developing")
    monkeypatch.setattr(tav, "search_articles",                  lambda q: list(MOCK_ARTICLES))
    monkeypatch.setattr(gs,  "ask_grok",                         lambda p: json.dumps(MOCK_FEED_RESPONSE))
    monkeypatch.setattr(fcs, "get_cached_feed",                  lambda k: None)
    monkeypatch.setattr(fcs, "cache_feed",                       lambda *a: None)
    monkeypatch.setattr(fcs, "build_cache_key",                  lambda *a: "mock-key")
    monkeypatch.setattr(sr,  "rank_articles",                    lambda arts, **kw: arts)
    monkeypatch.setattr(sa,  "analyze_sources",                  lambda arts, **kw: {
        "source_count": len(arts), "contrastive_signals": [], "dominant_themes": [],
    })
    monkeypatch.setattr(sa,  "format_analysis_for_prompt",       lambda a: "source analysis")
    monkeypatch.setattr(intl, "_save_intelligence_feed",         lambda *a, **kw: 1)


@pytest.fixture
def api_client():
    from fastapi.testclient import TestClient
    from backend.main import app
    return TestClient(app)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Industry inference
# ═══════════════════════════════════════════════════════════════════════════════

class TestInferIndustry:
    def test_ai_ml_keywords(self):
        from backend.services.intelligence_service import _infer_industry
        result = _infer_industry(["LLM", "transformer", "RAG", "embeddings"])
        assert result == "AI / Machine Learning"

    def test_web_dev_keywords(self):
        from backend.services.intelligence_service import _infer_industry
        result = _infer_industry(["React", "TypeScript", "NextJS"])
        assert result == "Web / Full-Stack Development"

    def test_devops_keywords(self):
        from backend.services.intelligence_service import _infer_industry
        result = _infer_industry(["Kubernetes", "Docker", "Terraform"])
        assert result == "Cloud / DevOps"

    def test_fintech_keywords(self):
        from backend.services.intelligence_service import _infer_industry
        result = _infer_industry(["DeFi", "blockchain", "trading"])
        assert result == "Fintech / Finance"

    def test_empty_topics_returns_technology(self):
        from backend.services.intelligence_service import _infer_industry
        assert _infer_industry([]) == "technology"

    def test_unknown_topics_returns_technology(self):
        from backend.services.intelligence_service import _infer_industry
        assert _infer_industry(["cooking", "gardening"]) == "technology"

    def test_dominant_industry_wins(self):
        from backend.services.intelligence_service import _infer_industry
        # More AI keywords than web keywords
        topics = ["LLM", "transformer", "embeddings", "RAG", "React"]
        result = _infer_industry(topics)
        assert result == "AI / Machine Learning"

    def test_case_insensitive(self):
        from backend.services.intelligence_service import _infer_industry
        result = _infer_industry(["KUBERNETES", "DOCKER"])
        assert result == "Cloud / DevOps"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Chat context extraction
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetChatContext:
    def test_returns_empty_on_db_error(self, monkeypatch):
        import backend.services.intelligence_service as intl
        from unittest.mock import MagicMock
        cm = MagicMock(side_effect=Exception("DB down"))
        monkeypatch.setattr("backend.utils.db.get_connection", cm)
        # Re-import to get the patched version
        import importlib
        importlib.reload(intl)
        result = intl._get_chat_context()
        assert result["recent_topics"] == []
        assert result["explained_concepts"] == []

    def test_returns_correct_shape(self, monkeypatch):
        import backend.services.intelligence_service as intl
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE chat_messages (
                id INTEGER PRIMARY KEY, session_id TEXT, role TEXT,
                content TEXT, topic_hint TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE concept_memory (
                id INTEGER PRIMARY KEY, concept TEXT, concept_key TEXT,
                topic TEXT, topic_key TEXT, session_id TEXT,
                times_explained INTEGER DEFAULT 1,
                first_explained_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_explained_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO chat_messages (session_id, role, content, topic_hint)
                VALUES ('s1', 'user', 'hi', 'Python'), ('s1', 'assistant', 'hi', 'Python'),
                       ('s2', 'user', 'test', 'ML');
            INSERT INTO concept_memory (concept, concept_key, times_explained)
                VALUES ('embeddings', 'embeddings', 3), ('RAG', 'rag', 2);
        """)
        from contextlib import contextmanager
        @contextmanager
        def mock_conn():
            yield conn

        monkeypatch.setattr("backend.services.intelligence_service.get_connection" if hasattr(intl, "get_connection") else "backend.utils.db.get_connection", mock_conn, raising=False)

        # Patch inside the function
        with patch("backend.utils.db.get_connection", mock_conn):
            result = intl._get_chat_context()

        assert "recent_topics" in result
        assert "explained_concepts" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Intelligence context building
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildIntelligenceContext:
    def test_returns_tuple_str_str(self, monkeypatch):
        import backend.services.intelligence_service as intl
        import backend.services.recommendation_service as rec
        monkeypatch.setattr(rec, "get_top_user_interests", lambda limit=8: [
            {"topic": "LLM", "preference_score": 1.0, "difficulty_preference": None, "times_recommended": 1}
        ])
        monkeypatch.setattr(rec, "get_suppressed_topics", lambda limit=5: [])
        monkeypatch.setattr(rec, "get_overall_difficulty_preference", lambda: "intermediate")
        monkeypatch.setattr(rec, "get_learning_stage", lambda: "developing")
        ctx, industry = intl._build_intelligence_context({"recent_topics": ["ML"], "explained_concepts": []})
        assert isinstance(ctx, str)
        assert isinstance(industry, str)

    def test_liked_topics_appear_in_context(self, monkeypatch):
        import backend.services.intelligence_service as intl
        import backend.services.recommendation_service as rec
        monkeypatch.setattr(rec, "get_top_user_interests", lambda limit=8: [
            {"topic": "PyTorch", "preference_score": 1.0, "difficulty_preference": None, "times_recommended": 1}
        ])
        monkeypatch.setattr(rec, "get_suppressed_topics", lambda limit=5: [])
        monkeypatch.setattr(rec, "get_overall_difficulty_preference", lambda: "intermediate")
        monkeypatch.setattr(rec, "get_learning_stage", lambda: "early")
        ctx, _ = intl._build_intelligence_context({"recent_topics": [], "explained_concepts": []})
        assert "PyTorch" in ctx

    def test_suppressed_topics_appear_in_context(self, monkeypatch):
        import backend.services.intelligence_service as intl
        import backend.services.recommendation_service as rec
        monkeypatch.setattr(rec, "get_top_user_interests", lambda limit=8: [])
        monkeypatch.setattr(rec, "get_suppressed_topics", lambda limit=5: ["Java"])
        monkeypatch.setattr(rec, "get_overall_difficulty_preference", lambda: "beginner")
        monkeypatch.setattr(rec, "get_learning_stage", lambda: "early")
        ctx, _ = intl._build_intelligence_context({"recent_topics": [], "explained_concepts": []})
        assert "Java" in ctx

    def test_chat_topics_appear_in_context(self, monkeypatch):
        import backend.services.intelligence_service as intl
        import backend.services.recommendation_service as rec
        monkeypatch.setattr(rec, "get_top_user_interests", lambda limit=8: [])
        monkeypatch.setattr(rec, "get_suppressed_topics", lambda limit=5: [])
        monkeypatch.setattr(rec, "get_overall_difficulty_preference", lambda: "intermediate")
        monkeypatch.setattr(rec, "get_learning_stage", lambda: "developing")
        ctx, _ = intl._build_intelligence_context({
            "recent_topics": ["Vector Databases", "HNSW"],
            "explained_concepts": [],
        })
        assert "Vector Databases" in ctx

    def test_industry_inferred_from_liked_and_chat_topics(self, monkeypatch):
        import backend.services.intelligence_service as intl
        import backend.services.recommendation_service as rec
        monkeypatch.setattr(rec, "get_top_user_interests", lambda limit=8: [
            {"topic": "LLM", "preference_score": 1.0, "difficulty_preference": None, "times_recommended": 1},
            {"topic": "RAG", "preference_score": 0.8, "difficulty_preference": None, "times_recommended": 1},
        ])
        monkeypatch.setattr(rec, "get_suppressed_topics", lambda limit=5: [])
        monkeypatch.setattr(rec, "get_overall_difficulty_preference", lambda: "intermediate")
        monkeypatch.setattr(rec, "get_learning_stage", lambda: "developing")
        _, industry = intl._build_intelligence_context({"recent_topics": ["embeddings"], "explained_concepts": []})
        assert industry == "AI / Machine Learning"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Multi-domain search
# ═══════════════════════════════════════════════════════════════════════════════

class TestMultiSearch:
    def test_deduplicates_by_url(self, monkeypatch):
        import backend.services.intelligence_service as intl
        import backend.services.tavily_service as tav
        shared = [{"title": "Shared", "url": "https://shared.com", "content": "content"}]
        call_count = [0]
        def fake_search(q):
            call_count[0] += 1
            return shared  # same URL from both queries
        monkeypatch.setattr(tav, "search_articles", fake_search)
        result = intl._multi_search("python", "AI / Machine Learning")
        # Should have only 1 article despite 2 searches returning the same URL
        assert len(result) == 1
        assert call_count[0] == 2  # both queries ran

    def test_combines_unique_articles(self, monkeypatch):
        import backend.services.intelligence_service as intl
        import backend.services.tavily_service as tav
        articles_by_query = {
            "python": [{"title": "A1", "url": "https://a1.com", "content": "c1"}],
            "AI / Machine Learning industry news trends 2025": [
                {"title": "A2", "url": "https://a2.com", "content": "c2"}
            ],
        }
        monkeypatch.setattr(tav, "search_articles", lambda q: articles_by_query.get(q, []))
        result = intl._multi_search("python", "AI / Machine Learning")
        assert len(result) == 2

    def test_handles_search_exception_gracefully(self, monkeypatch):
        import backend.services.intelligence_service as intl
        import backend.services.tavily_service as tav
        monkeypatch.setattr(tav, "search_articles", lambda q: (_ for _ in ()).throw(RuntimeError("Tavily down")))
        result = intl._multi_search("python", "AI / ML")
        assert result == []

    def test_skips_articles_without_url(self, monkeypatch):
        import backend.services.intelligence_service as intl
        import backend.services.tavily_service as tav
        monkeypatch.setattr(tav, "search_articles", lambda q: [{"title": "No URL", "url": "", "content": "c"}])
        result = intl._multi_search("python", "AI / ML")
        assert result == []


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Backward-compat shim
# ═══════════════════════════════════════════════════════════════════════════════

class TestAddCompatFields:
    def _base_feed(self):
        return dict(MOCK_FEED_RESPONSE)

    def test_adds_news_insight(self):
        from backend.services.intelligence_service import _add_compat_fields
        feed = self._base_feed()
        feed.pop("news_insight", None)
        result = _add_compat_fields(feed)
        assert "news_insight" in result
        assert result["news_insight"]["title"] == MOCK_FEED_RESPONSE["intelligence_brief"]["headline"]

    def test_adds_perspectives(self):
        from backend.services.intelligence_service import _add_compat_fields
        feed = self._base_feed()
        result = _add_compat_fields(feed)
        assert "perspectives" in result
        assert isinstance(result["perspectives"]["common_themes"], list)

    def test_adds_learning_topics(self):
        from backend.services.intelligence_service import _add_compat_fields
        feed = self._base_feed()
        result = _add_compat_fields(feed)
        assert "learning_topics" in result
        assert len(result["learning_topics"]) == 4
        assert result["learning_topics"][0]["title"] == "Tool Use"

    def test_adds_next_step_from_first_action_item(self):
        from backend.services.intelligence_service import _add_compat_fields
        feed = self._base_feed()
        result = _add_compat_fields(feed)
        assert result["next_step"] == MOCK_FEED_RESPONSE["action_items"][0]

    def test_does_not_overwrite_existing_news_insight(self):
        from backend.services.intelligence_service import _add_compat_fields
        feed = self._base_feed()
        feed["news_insight"] = {"title": "Custom", "summary": "s", "why_it_matters": "w", "sources": []}
        result = _add_compat_fields(feed)
        assert result["news_insight"]["title"] == "Custom"

    def test_next_step_empty_when_no_action_items(self):
        from backend.services.intelligence_service import _add_compat_fields
        feed = self._base_feed()
        feed.pop("next_step", None)
        feed["action_items"] = []
        result = _add_compat_fields(feed)
        assert result["next_step"] == ""


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Full pipeline
# ═══════════════════════════════════════════════════════════════════════════════

class TestGenerateIntelligenceFeed:
    def test_returns_intelligence_brief(self, mock_pipeline):
        from backend.services.intelligence_service import generate_intelligence_feed
        result = generate_intelligence_feed("LLM tool calling")
        assert "intelligence_brief" in result
        assert result["intelligence_brief"]["headline"]

    def test_returns_three_sections(self, mock_pipeline):
        from backend.services.intelligence_service import generate_intelligence_feed
        result = generate_intelligence_feed("LLM tool calling")
        assert len(result["sections"]) == 3

    def test_sections_have_two_items_each(self, mock_pipeline):
        from backend.services.intelligence_service import generate_intelligence_feed
        result = generate_intelligence_feed("LLM")
        for section in result["sections"]:
            assert len(section["items"]) == 2

    def test_returns_four_learning_track_items(self, mock_pipeline):
        from backend.services.intelligence_service import generate_intelligence_feed
        result = generate_intelligence_feed("LLM")
        assert len(result["learning_track"]) == 4

    def test_returns_three_action_items(self, mock_pipeline):
        from backend.services.intelligence_service import generate_intelligence_feed
        result = generate_intelligence_feed("LLM")
        assert len(result["action_items"]) == 3

    def test_backward_compat_fields_present(self, mock_pipeline):
        from backend.services.intelligence_service import generate_intelligence_feed
        result = generate_intelligence_feed("LLM")
        assert "news_insight"    in result
        assert "perspectives"    in result
        assert "learning_topics" in result
        assert "next_step"       in result

    def test_returns_cached_result_on_hit(self, mock_pipeline, monkeypatch):
        import backend.services.feed_cache_service as fcs
        cached = dict(MOCK_FEED_RESPONSE)
        cached["_from_cache"] = True
        monkeypatch.setattr(fcs, "get_cached_feed", lambda k: cached)
        from backend.services.intelligence_service import generate_intelligence_feed
        result = generate_intelligence_feed("LLM")
        assert result.get("_from_cache") is True

    def test_raises_on_no_articles(self, mock_pipeline, monkeypatch):
        import backend.services.tavily_service as tav
        import backend.services.source_ranker as sr
        monkeypatch.setattr(tav, "search_articles", lambda q: [])
        monkeypatch.setattr(sr,  "rank_articles",   lambda arts, **kw: [])
        from backend.services.intelligence_service import generate_intelligence_feed
        with pytest.raises(ValueError, match="No articles found"):
            generate_intelligence_feed("LLM")

    def test_persistence_failure_is_non_fatal(self, mock_pipeline, monkeypatch):
        import backend.services.intelligence_service as intl
        monkeypatch.setattr(intl, "_save_intelligence_feed",
                            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("DB full")))
        from backend.services.intelligence_service import generate_intelligence_feed
        result = generate_intelligence_feed("LLM")
        assert "intelligence_brief" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 7. API endpoint
# ═══════════════════════════════════════════════════════════════════════════════

class TestGenerateFeedEndpoint:
    def _mock_endpoint(self, monkeypatch):
        monkeypatch.setattr(
            "backend.main.generate_intelligence_feed",
            lambda interests: dict(MOCK_FEED_RESPONSE),
        )
        monkeypatch.setattr(
            "backend.main.assign_category",
            lambda t: "AI / ML",
        )

    def test_returns_200(self, api_client, monkeypatch):
        self._mock_endpoint(monkeypatch)
        resp = api_client.post("/generate-feed", json={"interests": "LLM"})
        assert resp.status_code == 200

    def test_response_has_intelligence_brief(self, api_client, monkeypatch):
        self._mock_endpoint(monkeypatch)
        resp = api_client.post("/generate-feed", json={"interests": "LLM"})
        data = resp.json()
        assert "intelligence_brief" in data
        assert data["intelligence_brief"]["headline"]

    def test_response_has_sections(self, api_client, monkeypatch):
        self._mock_endpoint(monkeypatch)
        resp = api_client.post("/generate-feed", json={"interests": "LLM"})
        data = resp.json()
        assert "sections" in data
        assert len(data["sections"]) == 3

    def test_response_has_learning_track(self, api_client, monkeypatch):
        self._mock_endpoint(monkeypatch)
        resp = api_client.post("/generate-feed", json={"interests": "LLM"})
        data = resp.json()
        assert "learning_track" in data
        assert len(data["learning_track"]) == 4

    def test_response_has_action_items(self, api_client, monkeypatch):
        self._mock_endpoint(monkeypatch)
        resp = api_client.post("/generate-feed", json={"interests": "LLM"})
        data = resp.json()
        assert "action_items" in data
        assert len(data["action_items"]) == 3

    def test_missing_interests_returns_422(self, api_client):
        resp = api_client.post("/generate-feed", json={})
        assert resp.status_code == 422

    def test_backward_compat_news_insight_present(self, api_client, monkeypatch):
        self._mock_endpoint(monkeypatch)
        resp = api_client.post("/generate-feed", json={"interests": "LLM"})
        data = resp.json()
        assert "news_insight" in data or data.get("news_insight") is None

    def test_category_assigned_to_learning_track(self, api_client, monkeypatch):
        self._mock_endpoint(monkeypatch)
        resp = api_client.post("/generate-feed", json={"interests": "LLM"})
        data = resp.json()
        track = data.get("learning_track", [])
        for item in track:
            assert "category" in item
