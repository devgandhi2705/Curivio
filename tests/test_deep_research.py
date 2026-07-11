"""
Tests for the autonomous deep-dive research workflow.

Test levels
-----------
1. QueryExpansion        — _expand_queries logic and structure
2. ImportanceDetection   — is_important_topic thresholds and edge cases
3. FetchArticles         — _fetch_research_articles URL dedup, partial failures
4. RankArticles          — _rank_research_articles integration with source_ranker
5. GenerateAnalysis      — _generate_analysis JSON parsing, field defaults, metadata
6. StoreAndRetrieve      — _store_research + get_stored_research TTL and upsert
7. WorkflowStages        — DeepResearchWorkflow stage isolation and state flow
8. RunDeepResearch       — cache-hit path, cache-miss path
9. DeepResearchEndpoints — HTTP endpoint shape and behaviour
10. AutoTrigger          — feedback endpoint triggers background deep research
11. Helpers              — _topic_key, _format_articles, _parse_json_response
12. Integration          — live end-to-end cache round-trip (gated -m integration)

Patching note
-------------
All external service calls use deferred imports inside functions (to avoid circular
imports at module load time).  Correct patch targets are therefore the source modules:

  ask_grok        → backend.services.grok_service.ask_grok
  search_articles → backend.services.tavily_service.search_articles
  rank_articles   → backend.services.source_ranker.rank_articles

NOT backend.services.deep_research_service.<name> (those names don't exist there).

Run:
    pytest tests/test_deep_research.py -v
    pytest tests/test_deep_research.py -v -m integration   # live tests
"""

import json
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.database.schema import ALL_TABLES
from backend.services.deep_research_service import (
    DEEP_RESEARCH_TTL_HOURS,
    IMPORTANCE_LIKE_THRESHOLD,
    IMPORTANCE_RECOMMEND_THRESHOLD,
    IMPORTANCE_SCORE_THRESHOLD,
    DeepResearchWorkflow,
    _expand_queries,
    _fetch_research_articles,
    _format_articles,
    _generate_analysis,
    _parse_json_response,
    _rank_research_articles,
    _store_research,
    _topic_key,
    get_stored_research,
    is_important_topic,
    list_research_topics,
    run_deep_research,
)


# ── Shared in-memory DB fixture ────────────────────────────────────────────────

@pytest.fixture
def mem_db(monkeypatch):
    """
    Single persistent in-memory SQLite connection shared within one test.
    All tables (including deep_research) are created fresh.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    for stmt in ALL_TABLES:
        conn.execute(stmt)
    conn.commit()

    @contextmanager
    def _get_conn():
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    monkeypatch.setattr("backend.services.deep_research_service.get_connection", _get_conn)
    monkeypatch.setattr("backend.utils.db.get_connection", _get_conn)

    yield conn
    conn.close()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fake_article(title="Article", url="https://example.com/post", content="content text"):
    return {"title": title, "url": url, "content": content}


def _good_analysis():
    return {
        "related_concepts":       ["Concept A", "Concept B", "Concept C", "Concept D"],
        "implementation_ideas":   ["Build X", "Build Y", "Build Z"],
        "practical_applications": ["Use case 1", "Use case 2", "Use case 3"],
        "advanced_follow_ups":    ["Follow-up 1", "Follow-up 2", "Follow-up 3", "Follow-up 4"],
        "research_summary":       "This topic matters because of reasons.",
    }


def _fake_pref(times_liked=0, preference_score=0.0, times_recommended=0):
    return {
        "topic": "test",
        "times_liked": times_liked,
        "preference_score": preference_score,
        "times_recommended": times_recommended,
        "times_disliked": 0,
        "difficulty_preference": None,
        "last_updated": "2026-05-15 10:00:00",
    }


def _insert_research(conn, topic="Model Context Protocol", generated_at="2026-05-15 10:00:00"):
    key = _topic_key(topic)
    research = {**_good_analysis(), "topic": topic, "sources": [], "generated_at": generated_at}
    conn.execute(
        """INSERT INTO deep_research (topic, topic_key, research_json, generated_at)
           VALUES (?, ?, ?, ?)""",
        (topic, key, json.dumps(research), generated_at),
    )
    conn.commit()
    return research


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Query Expansion
# ═══════════════════════════════════════════════════════════════════════════════

class TestQueryExpansion:
    def test_returns_list_of_strings(self):
        queries = _expand_queries("Model Context Protocol")
        assert isinstance(queries, list)
        assert all(isinstance(q, str) for q in queries)

    def test_base_topic_is_first_query(self):
        queries = _expand_queries("RAG Pipelines")
        assert queries[0] == "RAG Pipelines"

    def test_returns_at_least_two_queries(self):
        queries = _expand_queries("Attention Mechanisms")
        assert len(queries) >= 2

    def test_returns_search_count_plus_one(self):
        from backend.services.deep_research_service import DEEP_RESEARCH_SEARCH_COUNT
        queries = _expand_queries("LoRA")
        assert len(queries) == DEEP_RESEARCH_SEARCH_COUNT + 1

    def test_additional_queries_expand_topic(self):
        topic = "Vector Databases"
        queries = _expand_queries(topic)
        for q in queries[1:]:
            assert topic.lower() in q.lower()

    def test_strips_whitespace(self):
        queries = _expand_queries("  transformers  ")
        assert queries[0] == "transformers"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Importance Detection
# ═══════════════════════════════════════════════════════════════════════════════

class TestImportanceDetection:
    def test_unknown_topic_returns_false(self, mem_db):
        assert is_important_topic("completely unknown topic xyz") is False

    def test_liked_once_is_important(self, mem_db):
        with patch("backend.services.deep_research_service.get_preference",
                   return_value=_fake_pref(times_liked=IMPORTANCE_LIKE_THRESHOLD)):
            assert is_important_topic("topic") is True

    def test_not_liked_enough_is_not_important(self, mem_db):
        with patch("backend.services.deep_research_service.get_preference",
                   return_value=_fake_pref(times_liked=IMPORTANCE_LIKE_THRESHOLD - 1,
                                           preference_score=0.0, times_recommended=0)):
            assert is_important_topic("topic") is False

    def test_high_preference_score_is_important(self, mem_db):
        with patch("backend.services.deep_research_service.get_preference",
                   return_value=_fake_pref(preference_score=IMPORTANCE_SCORE_THRESHOLD)):
            assert is_important_topic("topic") is True

    def test_frequently_recommended_is_important(self, mem_db):
        with patch("backend.services.deep_research_service.get_preference",
                   return_value=_fake_pref(
                       times_recommended=IMPORTANCE_RECOMMEND_THRESHOLD
                   )):
            assert is_important_topic("topic") is True

    def test_none_preference_returns_false(self, mem_db):
        with patch("backend.services.deep_research_service.get_preference", return_value=None):
            assert is_important_topic("unseen topic") is False

    def test_all_thresholds_met_is_important(self, mem_db):
        with patch("backend.services.deep_research_service.get_preference",
                   return_value=_fake_pref(
                       times_liked=2, preference_score=0.8, times_recommended=5
                   )):
            assert is_important_topic("hot topic") is True


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Fetch Articles
# ═══════════════════════════════════════════════════════════════════════════════

class TestFetchArticles:
    def test_calls_search_for_each_query(self):
        queries = ["query 1", "query 2"]
        with patch("backend.services.tavily_service.search_articles",
                   return_value=[_fake_article()]) as mock_search:
            _fetch_research_articles(queries)
        assert mock_search.call_count == len(queries)

    def test_deduplicates_by_url(self):
        # q1 returns articles at a.com/1 and a.com/2
        # q2 returns a.com/1 (duplicate) and a.com/3 (new)
        # Expected result: 3 unique articles
        articles_q1 = [
            _fake_article(url="https://a.com/1"),
            _fake_article(url="https://a.com/2"),
        ]
        articles_q2 = [
            _fake_article(url="https://a.com/1"),  # duplicate
            _fake_article(url="https://a.com/3"),  # new
        ]
        with patch("backend.services.tavily_service.search_articles",
                   side_effect=[articles_q1, articles_q2]):
            result = _fetch_research_articles(["q1", "q2"])

        urls = [a["url"] for a in result]
        assert len(urls) == len(set(urls)), "Duplicate URLs must be removed"
        assert len(result) == 3

    def test_empty_queries_returns_empty(self):
        result = _fetch_research_articles([])
        assert result == []

    def test_partial_failure_returns_successful_results(self):
        good = [_fake_article(url="https://good.com/1")]
        with patch("backend.services.tavily_service.search_articles",
                   side_effect=[RuntimeError("Tavily error"), good]):
            result = _fetch_research_articles(["bad query", "good query"])
        assert len(result) == 1
        assert result[0]["url"] == "https://good.com/1"

    def test_all_failures_returns_empty(self):
        with patch("backend.services.tavily_service.search_articles",
                   side_effect=RuntimeError("always fails")):
            result = _fetch_research_articles(["q1", "q2"])
        assert result == []


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Rank Articles
# ═══════════════════════════════════════════════════════════════════════════════

class TestRankArticles:
    def test_calls_rank_articles_with_correct_args(self):
        # Chat-4.2: min_domains=4 now passed (was a no-op default of 0 before —
        # matches project_service.py's real feed-mode "core content" value).
        articles = [_fake_article()]
        with patch("backend.services.source_ranker.rank_articles",
                   return_value=articles) as mock_rank:
            _rank_research_articles(articles, "my topic", top_n=6)
        mock_rank.assert_called_once_with(
            articles, query="my topic", top_n=6, min_score=0.1,
            domain="default", mode="deep_research", min_domains=4,
        )

    def test_empty_input_returns_empty(self):
        with patch("backend.services.source_ranker.rank_articles", return_value=[]):
            result = _rank_research_articles([], "topic")
        assert result == []

    def test_returns_ranked_list(self):
        articles = [_fake_article(url=f"https://ex.com/{i}") for i in range(5)]
        with patch("backend.services.source_ranker.rank_articles",
                   return_value=articles[:3]):
            result = _rank_research_articles(articles, "topic", top_n=3)
        assert len(result) == 3


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Generate Analysis
# ═══════════════════════════════════════════════════════════════════════════════

class TestGenerateAnalysis:
    # Patch at the source module — deferred import reads from there.
    _GROK_PATCH = "backend.services.grok_service.ask_grok"

    def test_returns_all_required_fields(self):
        with patch(self._GROK_PATCH, return_value=json.dumps(_good_analysis())):
            result = _generate_analysis("MCP", [_fake_article()])
        for field in ("related_concepts", "implementation_ideas",
                      "practical_applications", "advanced_follow_ups", "research_summary"):
            assert field in result

    def test_injects_topic_metadata(self):
        with patch(self._GROK_PATCH, return_value=json.dumps(_good_analysis())):
            result = _generate_analysis("MCP", [_fake_article()])
        assert result["topic"] == "MCP"

    def test_injects_sources_from_articles(self):
        articles = [_fake_article(url="https://a.com/1"), _fake_article(url="https://b.com/2")]
        with patch(self._GROK_PATCH, return_value=json.dumps(_good_analysis())):
            result = _generate_analysis("MCP", articles)
        assert result["sources"] == ["https://a.com/1", "https://b.com/2"]

    def test_injects_generated_at(self):
        with patch(self._GROK_PATCH, return_value=json.dumps(_good_analysis())):
            result = _generate_analysis("MCP", [])
        assert "generated_at" in result
        datetime.fromisoformat(result["generated_at"])  # must be a valid ISO timestamp

    def test_defaults_missing_fields(self):
        partial = {"research_summary": "Only summary"}
        with patch(self._GROK_PATCH, return_value=json.dumps(partial)):
            result = _generate_analysis("MCP", [])
        assert result["related_concepts"]       == []
        assert result["implementation_ideas"]   == []
        assert result["practical_applications"] == []
        assert result["advanced_follow_ups"]    == []

    def test_raises_on_unparseable_json(self):
        with patch(self._GROK_PATCH, return_value="not json at all %%%"):
            with pytest.raises(ValueError, match="could not be parsed as JSON"):
                _generate_analysis("MCP", [])

    def test_extracts_json_from_markdown_fence(self):
        wrapped = f"```json\n{json.dumps(_good_analysis())}\n```"
        with patch(self._GROK_PATCH, return_value=wrapped):
            result = _generate_analysis("MCP", [])
        assert result["research_summary"] == _good_analysis()["research_summary"]

    def test_empty_articles_uses_no_articles_placeholder(self):
        captured = {}
        def capture(prompt: str) -> str:
            captured["prompt"] = prompt
            return json.dumps(_good_analysis())
        with patch(self._GROK_PATCH, side_effect=capture):
            _generate_analysis("MCP", [])
        assert "no articles retrieved" in captured["prompt"].lower()


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Store and Retrieve
# ═══════════════════════════════════════════════════════════════════════════════

class TestStoreAndRetrieve:
    def test_store_creates_row_in_db(self, mem_db):
        result = {**_good_analysis(), "topic": "MCP", "sources": [],
                  "generated_at": "2026-05-15T10:00:00+00:00"}
        _store_research("MCP", result)
        count = mem_db.execute("SELECT COUNT(*) FROM deep_research").fetchone()[0]
        assert count == 1

    def test_retrieve_returns_stored_result(self, mem_db):
        research = _insert_research(mem_db)
        retrieved = get_stored_research("Model Context Protocol")
        assert retrieved is not None
        assert retrieved["research_summary"] == research["research_summary"]

    def test_retrieve_is_case_insensitive(self, mem_db):
        _insert_research(mem_db, topic="Model Context Protocol")
        assert get_stored_research("MODEL CONTEXT PROTOCOL") is not None
        assert get_stored_research("model context protocol")  is not None

    def test_retrieve_returns_none_on_miss(self, mem_db):
        assert get_stored_research("topic that does not exist") is None

    def test_expired_entry_returns_none(self, mem_db):
        _insert_research(mem_db, generated_at="2000-01-01 00:00:00")
        assert get_stored_research("Model Context Protocol") is None

    def test_upsert_updates_existing_entry(self, mem_db):
        _store_research("MCP", {**_good_analysis(), "research_summary": "old",
                                "topic": "MCP", "sources": [],
                                "generated_at": "2026-01-01T00:00:00"})
        _store_research("MCP", {**_good_analysis(), "research_summary": "new",
                                "topic": "MCP", "sources": [],
                                "generated_at": "2026-05-15T10:00:00"})
        row_count = mem_db.execute("SELECT COUNT(*) FROM deep_research").fetchone()[0]
        assert row_count == 1  # upsert, not double insert
        retrieved = get_stored_research("MCP")
        assert retrieved["research_summary"] == "new"

    def test_store_returns_integer_id(self, mem_db):
        result = {**_good_analysis(), "topic": "T", "sources": [],
                  "generated_at": "2026-05-15T10:00:00"}
        row_id = _store_research("T", result)
        assert isinstance(row_id, int)
        assert row_id > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Workflow Stages — isolation and state flow
# ═══════════════════════════════════════════════════════════════════════════════

class TestWorkflowStages:
    def test_initial_state_has_expected_keys(self):
        wf = DeepResearchWorkflow("MCP")
        for key in ("topic", "queries", "articles", "result", "research_id"):
            assert key in wf.state

    def test_expand_queries_populates_state(self):
        wf = DeepResearchWorkflow("MCP")
        wf.expand_queries()
        assert len(wf.state["queries"]) >= 2
        assert wf.state["queries"][0] == "MCP"

    def test_fetch_articles_populates_state(self):
        wf = DeepResearchWorkflow("MCP")
        wf.state["queries"] = ["query 1"]
        with patch("backend.services.tavily_service.search_articles",
                   return_value=[_fake_article()]):
            wf.fetch_articles()
        assert len(wf.state["articles"]) == 1

    def test_rank_articles_updates_state(self):
        wf = DeepResearchWorkflow("MCP")
        wf.state["articles"] = [_fake_article()]
        with patch("backend.services.source_ranker.rank_articles",
                   return_value=[_fake_article()]):
            wf.rank_articles()
        assert isinstance(wf.state["articles"], list)

    def test_generate_populates_result(self):
        wf = DeepResearchWorkflow("MCP")
        wf.state["articles"] = [_fake_article()]
        with patch("backend.services.grok_service.ask_grok",
                   return_value=json.dumps(_good_analysis())):
            wf.generate()
        assert "related_concepts" in wf.state["result"]
        assert wf.state["result"]["topic"] == "MCP"

    def test_persist_populates_research_id(self, mem_db):
        wf = DeepResearchWorkflow("MCP")
        wf.state["result"] = {**_good_analysis(), "topic": "MCP",
                               "sources": [], "generated_at": "2026-05-15T10:00:00"}
        wf.persist()
        assert isinstance(wf.state["research_id"], int)

    def test_stages_return_self_for_chaining(self):
        wf = DeepResearchWorkflow("MCP")
        result = wf.expand_queries()
        assert result is wf

    def test_run_executes_all_stages(self, mem_db):
        with patch("backend.services.tavily_service.search_articles",
                   return_value=[_fake_article()]), \
             patch("backend.services.source_ranker.rank_articles",
                   return_value=[_fake_article()]), \
             patch("backend.services.grok_service.ask_grok",
                   return_value=json.dumps(_good_analysis())):
            result = DeepResearchWorkflow("MCP").run()

        for field in ("related_concepts", "implementation_ideas",
                      "practical_applications", "advanced_follow_ups", "research_summary"):
            assert field in result
        assert result["topic"] == "MCP"


# ═══════════════════════════════════════════════════════════════════════════════
# 8. run_deep_research — cache hit/miss
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunDeepResearch:
    def test_returns_cached_result_without_running_workflow(self, mem_db):
        stored = _insert_research(mem_db, topic="Cached Topic")
        with patch.object(DeepResearchWorkflow, "run",
                          side_effect=AssertionError("should not run")):
            result = run_deep_research("Cached Topic")
        assert result["research_summary"] == stored["research_summary"]

    def test_runs_workflow_on_cache_miss(self, mem_db):
        with patch("backend.services.tavily_service.search_articles",
                   return_value=[_fake_article()]), \
             patch("backend.services.source_ranker.rank_articles",
                   return_value=[_fake_article()]), \
             patch("backend.services.grok_service.ask_grok",
                   return_value=json.dumps(_good_analysis())):
            result = run_deep_research("Fresh Topic")
        assert "related_concepts" in result

    def test_result_persisted_after_workflow(self, mem_db):
        with patch("backend.services.tavily_service.search_articles",
                   return_value=[]), \
             patch("backend.services.source_ranker.rank_articles",
                   return_value=[]), \
             patch("backend.services.grok_service.ask_grok",
                   return_value=json.dumps(_good_analysis())):
            run_deep_research("Persist Test")
        assert get_stored_research("Persist Test") is not None

    def test_list_research_topics_returns_entries(self, mem_db):
        _insert_research(mem_db, topic="Topic A")
        _insert_research(mem_db, topic="Topic B")
        topics = list_research_topics()
        names = [t["topic"] for t in topics]
        assert "Topic A" in names
        assert "Topic B" in names

    def test_list_research_topics_ordered_newest_first(self, mem_db):
        _insert_research(mem_db, topic="Old", generated_at="2026-05-10 10:00:00")
        _insert_research(mem_db, topic="New", generated_at="2026-05-15 10:00:00")
        topics = list_research_topics()
        assert topics[0]["topic"] == "New"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Deep Research HTTP Endpoints
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeepResearchEndpoints:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        return TestClient(app)

    def _stored(self):
        return {**_good_analysis(), "topic": "MCP", "sources": [],
                "generated_at": "2026-05-15T10:00:00+00:00"}

    def test_post_returns_200_on_cache_hit(self, client):
        with patch("backend.main.get_stored_research", return_value=self._stored()):
            resp = client.post("/deep-research", json={"topic": "MCP"})
        assert resp.status_code == 200

    def test_post_triggers_workflow_on_miss(self, client):
        with patch("backend.main.get_stored_research", return_value=None), \
             patch("backend.main.run_deep_research", return_value=self._stored()):
            resp = client.post("/deep-research", json={"topic": "MCP"})
        assert resp.status_code == 200

    def test_post_response_has_expected_fields(self, client):
        with patch("backend.main.get_stored_research", return_value=self._stored()):
            resp = client.post("/deep-research", json={"topic": "MCP"})
        body = resp.json()
        for field in ("topic", "related_concepts", "implementation_ideas",
                      "practical_applications", "advanced_follow_ups",
                      "research_summary", "sources", "generated_at"):
            assert field in body, f"Missing field: {field}"

    def test_post_blank_topic_returns_422(self, client):
        resp = client.post("/deep-research", json={"topic": "   "})
        assert resp.status_code == 422

    def test_get_topic_returns_200_on_hit(self, client):
        with patch("backend.main.get_stored_research", return_value=self._stored()):
            resp = client.get("/deep-research/MCP")
        assert resp.status_code == 200

    def test_get_topic_returns_404_on_miss(self, client):
        with patch("backend.main.get_stored_research", return_value=None):
            resp = client.get("/deep-research/unknown-topic")
        assert resp.status_code == 404

    def test_get_list_returns_200(self, client):
        with patch("backend.main.list_research_topics", return_value=[]):
            resp = client.get("/deep-research")
        assert resp.status_code == 200

    def test_get_list_returns_list(self, client):
        summaries = [{"id": 1, "topic": "MCP", "generated_at": "2026-05-15 10:00:00"}]
        with patch("backend.main.list_research_topics", return_value=summaries):
            resp = client.get("/deep-research")
        body = resp.json()
        assert isinstance(body, list)
        assert body[0]["topic"] == "MCP"

    def test_post_returns_cached_without_calling_workflow(self, client):
        stored = self._stored()
        with patch("backend.main.get_stored_research", return_value=stored), \
             patch("backend.main.run_deep_research") as mock_run:
            client.post("/deep-research", json={"topic": "MCP"})
        mock_run.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Auto-trigger via feedback endpoint
# ═══════════════════════════════════════════════════════════════════════════════

class TestAutoTrigger:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        return TestClient(app)

    def _mock_process_feedback(self, topic, feedback):
        return {
            "topic": topic, "feedback": feedback, "message": "saved",
            "preference_score": 1.0, "difficulty_preference": None,
            "times_liked": 1, "times_disliked": 0, "times_recommended": 1,
            "last_updated": "2026-05-15 10:00:00",
        }

    def _decision(self, should_explore: bool):
        from backend.services.exploration_trigger_service import ExplorationDecision
        return ExplorationDecision(
            topic="MCP",
            should_explore=should_explore,
            total_score=0.8 if should_explore else 0.2,
            signals=[],
            recommended_actions=["deep_research"] if should_explore else [],
            cooldown_active=False,
            reason="test fixture",
        )

    def test_feedback_skips_trigger_when_should_explore_false(self, client):
        with patch("backend.main.process_feedback", side_effect=self._mock_process_feedback), \
             patch("backend.main.evaluate_exploration",
                   return_value=self._decision(False)), \
             patch("backend.main.run_deep_research") as mock_run:
            resp = client.post("/feedback", json={"topic": "MCP", "feedback": "liked"})
        assert resp.status_code == 200
        mock_run.assert_not_called()

    def test_feedback_returns_200_regardless_of_research_trigger(self, client):
        # Patch run_deep_research (called inside _auto_research) to raise —
        # the real _auto_research wrapper must catch it so the 200 still lands.
        with patch("backend.main.process_feedback", side_effect=self._mock_process_feedback), \
             patch("backend.main.evaluate_exploration",
                   return_value=self._decision(True)), \
             patch("backend.main.run_deep_research", side_effect=RuntimeError("boom")):
            resp = client.post("/feedback", json={"topic": "MCP", "feedback": "liked"})
        assert resp.status_code == 200

    def test_feedback_queues_research_when_should_explore_true(self, client):
        queued = []
        def fake_auto_research(topic):
            queued.append(topic)
        with patch("backend.main.process_feedback", side_effect=self._mock_process_feedback), \
             patch("backend.main.evaluate_exploration",
                   return_value=self._decision(True)), \
             patch("backend.main._auto_research", side_effect=fake_auto_research):
            resp = client.post("/feedback", json={"topic": "MCP", "feedback": "liked"})
        assert resp.status_code == 200
        assert queued == ["MCP"]

    def test_feedback_does_not_queue_when_should_explore_false(self, client):
        queued = []
        def fake_auto_research(topic):
            queued.append(topic)
        with patch("backend.main.process_feedback", side_effect=self._mock_process_feedback), \
             patch("backend.main.evaluate_exploration",
                   return_value=self._decision(False)), \
             patch("backend.main._auto_research", side_effect=fake_auto_research):
            resp = client.post("/feedback", json={"topic": "MCP", "feedback": "liked"})
        assert resp.status_code == 200
        assert queued == []


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Helper unit tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestHelpers:
    def test_topic_key_lowercases(self):
        assert _topic_key("Model Context Protocol") == "model context protocol"

    def test_topic_key_strips_whitespace(self):
        assert _topic_key("  MCP  ") == "mcp"

    def test_format_articles_with_articles(self):
        articles = [_fake_article(title="T1", url="https://a.com", content="c1")]
        output = _format_articles(articles)
        assert "T1" in output
        assert "https://a.com" in output

    def test_format_articles_empty(self):
        output = _format_articles([])
        assert "no articles" in output.lower()

    def test_format_articles_numbers_each_entry(self):
        articles = [_fake_article(url=f"https://ex.com/{i}") for i in range(3)]
        output = _format_articles(articles)
        assert "1." in output
        assert "2." in output
        assert "3." in output

    def test_parse_json_strips_fences(self):
        raw = '```json\n{"key": "value"}\n```'
        result = _parse_json_response(raw)
        assert result == {"key": "value"}

    def test_parse_json_plain(self):
        result = _parse_json_response('{"key": 42}')
        assert result == {"key": 42}

    def test_parse_json_extracts_embedded(self):
        raw = 'Here is the result: {"key": 42} That is all.'
        result = _parse_json_response(raw)
        assert result == {"key": 42}

    def test_parse_json_raises_on_garbage(self):
        with pytest.raises(ValueError):
            _parse_json_response("not JSON !!!")


# ═══════════════════════════════════════════════════════════════════════════════
# 12. Integration — full cache round-trip (no live Groq or Tavily calls)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.integration
class TestDeepResearchIntegration:
    def test_full_workflow_round_trip(self, mem_db):
        """
        Run the complete workflow with mocked external APIs, persist the result,
        and verify it is retrievable without re-running the workflow.
        """
        articles = [
            _fake_article(title="MCP Overview",    url="https://mcp.io/docs",
                          content="MCP is a protocol for tool calling. " * 20),
            _fake_article(title="MCP Integration",  url="https://anthropic.com/mcp",
                          content="MCP enables agent orchestration. " * 20),
        ]
        analysis = {
            "related_concepts":       ["Tool calling", "Context windows",
                                       "Agent orchestration", "Function calling"],
            "implementation_ideas":   ["Build MCP server", "Connect LLM to tool",
                                       "Create orchestration layer"],
            "practical_applications": ["AI coding assistants", "Multi-step pipelines",
                                       "Data retrieval agents"],
            "advanced_follow_ups":    ["ReAct agents", "LangChain MCP",
                                       "Anthropic tool use", "Agent memory"],
            "research_summary":       "MCP standardises how AI models interact with tools.",
        }

        with patch("backend.services.tavily_service.search_articles",
                   return_value=articles), \
             patch("backend.services.source_ranker.rank_articles",
                   return_value=articles), \
             patch("backend.services.grok_service.ask_grok",
                   return_value=json.dumps(analysis)):
            result = run_deep_research("Model Context Protocol")

        # Correct structure
        assert result["topic"] == "Model Context Protocol"
        assert len(result["related_concepts"]) >= 4
        assert len(result["implementation_ideas"]) >= 3
        assert len(result["sources"]) == 2

        # Stored and retrievable
        cached = get_stored_research("model context protocol")
        assert cached is not None
        assert cached["research_summary"] == analysis["research_summary"]

        # Second call uses cache — workflow must not re-run
        with patch.object(DeepResearchWorkflow, "run",
                          side_effect=AssertionError("must not re-run")):
            second = run_deep_research("Model Context Protocol")
        assert second["research_summary"] == analysis["research_summary"]
