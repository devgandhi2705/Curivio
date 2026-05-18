"""
Tests for topic_cluster.py.

Test levels
-----------
1. assign_category   — each category, keyword matching, edge cases, priority tiebreak
2. cluster_topics    — grouping by category, pre-assigned category respected
3. get_category_distribution — counting correctness
4. suggest_unexplored_categories — returns unseen, respects top_n, excludes UNCATEGORIZED
5. format_category_context — string formatting, empty input
6. Curator wiring    — category context injected into memory context when liked topics exist
7. Endpoint wiring   — /generate-feed response topics contain a category field

Run:
    pytest tests/test_topic_cluster.py -v
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.topic_cluster import (
    CATEGORIES,
    UNCATEGORIZED,
    assign_category,
    cluster_topics,
    format_category_context,
    get_category_distribution,
    suggest_unexplored_categories,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _topic(title, difficulty="intermediate", category=None):
    t = {"title": title, "reason": f"Learn {title}", "difficulty": difficulty}
    if category is not None:
        t["category"] = category
    return t


# ── TestAssignCategory ────────────────────────────────────────────────────────

class TestAssignCategory:

    # --- Each category covered by ≥1 representative title ---

    def test_llm_infrastructure_inference(self):
        assert assign_category("LLM Inference Optimization and Serving") == "LLM Infrastructure"

    def test_llm_infrastructure_quantization(self):
        assert assign_category("INT8 Quantization for Transformer Models") == "LLM Infrastructure"

    def test_llm_infrastructure_speculative_decoding(self):
        assert assign_category("Speculative Decoding to Reduce Latency") == "LLM Infrastructure"

    def test_llm_training_lora(self):
        assert assign_category("LoRA: Low-Rank Adaptation for Fine-Tuning") == "LLM Training"

    def test_llm_training_rlhf(self):
        assert assign_category("RLHF and Instruction Alignment for LLMs") == "LLM Training"

    def test_llm_training_peft(self):
        assert assign_category("Parameter Efficient Fine-Tuning with PEFT") == "LLM Training"

    def test_ai_agents(self):
        assert assign_category("Building Autonomous AI Agents with Tool Use") == "AI Agents"

    def test_ai_agents_planning(self):
        assert assign_category("Multi-Agent Orchestration and Planning") == "AI Agents"

    def test_rag_retrieval(self):
        assert assign_category("RAG Pipelines for Document Retrieval") == "RAG & Retrieval"

    def test_rag_retrieval_reranking(self):
        assert assign_category("Hybrid Search and Reranking Strategies") == "RAG & Retrieval"

    def test_vector_databases(self):
        assert assign_category("Vector Database Architecture with Faiss and Pinecone") == "Vector Databases"

    def test_vector_databases_ann(self):
        assert assign_category("Approximate Nearest Neighbour Search Algorithms") == "Vector Databases"

    def test_reinforcement_learning(self):
        assert assign_category("Proximal Policy Optimization and Reward Modeling") == "Reinforcement Learning"

    def test_reinforcement_learning_dqn(self):
        assert assign_category("Deep Q-Learning Networks for Discrete Environments") == "Reinforcement Learning"

    def test_multimodal_ai(self):
        assert assign_category("Multimodal Vision-Language Models and CLIP") == "Multimodal AI"

    def test_computer_vision_diffusion(self):
        assert assign_category("Stable Diffusion Architecture and Image Generation") == "Computer Vision"

    def test_computer_vision_segmentation(self):
        assert assign_category("Instance Segmentation with Transformer Backbones") == "Computer Vision"

    def test_nlp_foundations_attention(self):
        assert assign_category("Self-Attention Mechanisms in Transformer Architecture") == "NLP Foundations"

    def test_nlp_foundations_tokenizer(self):
        assert assign_category("Tokenization Strategies and Vocabulary Design") == "NLP Foundations"

    def test_ml_engineering_mlops(self):
        assert assign_category("MLOps Best Practices with Experiment Tracking") == "ML Engineering"

    def test_ml_engineering_monitoring(self):
        assert assign_category("Model Monitoring and Reproducibility in Production") == "ML Engineering"

    def test_ai_safety_interpretability(self):
        assert assign_category("Interpretability and Fairness in Large Models") == "AI Safety"

    def test_ai_safety_hallucination(self):
        assert assign_category("Reducing Hallucination via Constitutional AI") == "AI Safety"

    def test_finance_ai(self):
        assert assign_category("Quantitative Trading Strategies with Machine Learning") == "Finance AI"

    def test_finance_ai_portfolio(self):
        assert assign_category("Portfolio Risk Modelling Using Neural Networks") == "Finance AI"

    def test_uncategorized_fallback(self):
        assert assign_category("General Concepts in Data Structures") == UNCATEGORIZED

    def test_empty_title_returns_uncategorized(self):
        assert assign_category("") == UNCATEGORIZED

    # --- Result is always in CATEGORIES ---

    def test_result_always_in_categories(self):
        titles = [
            "Flash Attention Memory Optimization",
            "RAG with Dense Retrieval",
            "Actor Critic in Robotics",
            "Completely Unrelated Topic",
            "",
        ]
        for t in titles:
            assert assign_category(t) in CATEGORIES

    # --- Hyphenated terms handled ---

    def test_hyphenated_finetuning(self):
        # "fine-tuning" should merge to "finetuning" and match LLM Training
        assert assign_category("Fine-Tuning Language Models with LoRA") == "LLM Training"

    def test_hyphenated_multiagent(self):
        assert assign_category("Multi-Agent Workflow Orchestration") == "AI Agents"

    # --- Priority tiebreak ---

    def test_finance_beats_general_on_tie(self):
        # "financial" is in Finance AI; should not fall through to something generic
        result = assign_category("Financial Risk Modelling")
        assert result == "Finance AI"

    def test_vector_databases_beats_rag_on_vector_only(self):
        # "vector" alone → Vector Databases (higher priority) beats RAG
        result = assign_category("Vector Similarity Search")
        assert result == "Vector Databases"


# ── TestClusterTopics ─────────────────────────────────────────────────────────

class TestClusterTopics:
    def test_empty_list_returns_empty_dict(self):
        assert cluster_topics([]) == {}

    def test_single_topic_creates_one_cluster(self):
        topics = [_topic("LoRA Fine-Tuning for LLMs")]
        result = cluster_topics(topics)
        assert "LLM Training" in result
        assert len(result["LLM Training"]) == 1

    def test_topics_grouped_by_category(self):
        topics = [
            _topic("LoRA Fine-Tuning for LLMs"),
            _topic("RAG Pipeline with Reranking"),
            _topic("Vector Database with Faiss"),
        ]
        result = cluster_topics(topics)
        assert "LLM Training" in result
        assert "RAG & Retrieval" in result
        assert "Vector Databases" in result

    def test_multiple_topics_same_category(self):
        topics = [
            _topic("LoRA Fine-Tuning"),
            _topic("RLHF and Instruction Tuning"),
            _topic("PEFT Methods Overview"),
        ]
        result = cluster_topics(topics)
        assert len(result["LLM Training"]) == 3

    def test_pre_assigned_category_respected(self):
        topic = _topic("Unrelated Title", category="Finance AI")
        result = cluster_topics([topic])
        assert "Finance AI" in result

    def test_only_non_empty_categories_returned(self):
        topics = [_topic("LoRA Fine-Tuning")]
        result = cluster_topics(topics)
        # Only categories with ≥1 topic should appear
        assert all(len(v) > 0 for v in result.values())

    def test_uncategorized_topics_grouped_together(self):
        topics = [
            _topic("Something Unrelated First"),
            _topic("Something Unrelated Second"),
        ]
        result = cluster_topics(topics)
        assert UNCATEGORIZED in result
        assert len(result[UNCATEGORIZED]) == 2


# ── TestGetCategoryDistribution ───────────────────────────────────────────────

class TestGetCategoryDistribution:
    def test_empty_list_returns_empty_dict(self):
        assert get_category_distribution([]) == {}

    def test_single_category(self):
        assert get_category_distribution(["LLM Training"]) == {"LLM Training": 1}

    def test_multiple_occurrences_counted(self):
        dist = get_category_distribution(
            ["LLM Training", "LLM Training", "RAG & Retrieval"]
        )
        assert dist["LLM Training"] == 2
        assert dist["RAG & Retrieval"] == 1

    def test_all_distinct_categories(self):
        cats = ["LLM Training", "AI Agents", "Finance AI"]
        dist = get_category_distribution(cats)
        assert all(dist[c] == 1 for c in cats)


# ── TestSuggestUnexploredCategories ───────────────────────────────────────────

class TestSuggestUnexploredCategories:
    def test_empty_seen_returns_top_priority_categories(self):
        result = suggest_unexplored_categories([], top_n=3)
        assert len(result) == 3
        # Should start with highest-priority non-uncategorized categories
        assert result[0] == "Finance AI"

    def test_seen_categories_excluded(self):
        seen = ["Finance AI", "Reinforcement Learning"]
        result = suggest_unexplored_categories(seen, top_n=3)
        assert "Finance AI" not in result
        assert "Reinforcement Learning" not in result

    def test_uncategorized_never_suggested(self):
        result = suggest_unexplored_categories([], top_n=20)
        assert UNCATEGORIZED not in result

    def test_top_n_respected(self):
        result = suggest_unexplored_categories([], top_n=2)
        assert len(result) == 2

    def test_all_covered_returns_empty(self):
        all_real = [c for c in CATEGORIES if c != UNCATEGORIZED]
        result = suggest_unexplored_categories(all_real)
        assert result == []

    def test_respects_priority_order(self):
        seen = ["Finance AI"]
        result = suggest_unexplored_categories(seen, top_n=2)
        # After Finance AI, next highest priority is Reinforcement Learning
        assert result[0] == "Reinforcement Learning"


# ── TestFormatCategoryContext ─────────────────────────────────────────────────

class TestFormatCategoryContext:
    def test_empty_input_returns_empty_string(self):
        assert format_category_context([]) == ""

    def test_returns_string(self):
        result = format_category_context(["LLM Training"])
        assert isinstance(result, str)

    def test_includes_coverage_section(self):
        result = format_category_context(["LLM Training", "RAG & Retrieval"])
        assert "Category coverage" in result

    def test_includes_unexplored_section(self):
        result = format_category_context(["LLM Training"])
        assert "Consider exploring" in result

    def test_count_appears_in_coverage(self):
        result = format_category_context(["LLM Training", "LLM Training", "AI Agents"])
        assert "LLM Training (2)" in result
        assert "AI Agents (1)" in result

    def test_all_categories_seen_no_unexplored_section(self):
        all_cats = [c for c in CATEGORIES if c != UNCATEGORIZED]
        result = format_category_context(all_cats)
        # Unexplored section should be absent since all categories are covered
        assert "Consider exploring" not in result


# ── TestCuratorWiring ─────────────────────────────────────────────────────────

class TestCuratorWiring:
    """Verify category context is injected into _build_memory_context."""

    def test_category_context_injected_when_liked_topics_exist(self):
        from backend.services.curator_service import _build_memory_context

        liked = [
            {"topic": "LoRA Fine-Tuning",          "preference_score": 1.0, "difficulty_preference": None, "times_recommended": 2},
            {"topic": "RAG Pipeline Optimization", "preference_score": 0.8, "difficulty_preference": None, "times_recommended": 1},
        ]

        with patch("backend.services.curator_service.get_top_user_interests", return_value=liked), \
             patch("backend.services.curator_service.get_suppressed_topics", return_value=[]), \
             patch("backend.services.curator_service.get_overall_difficulty_preference", return_value="intermediate"), \
             patch("backend.services.curator_service.get_learning_stage", return_value="developing"), \
             patch("backend.services.curator_service.get_frequently_seen_topics", return_value=[]), \
             patch("backend.services.curator_service.list_digests", return_value=[]):
            context = _build_memory_context()

        assert "Category coverage" in context

    def test_no_category_context_when_no_liked_topics(self):
        from backend.services.curator_service import _build_memory_context

        with patch("backend.services.curator_service.get_top_user_interests", return_value=[]), \
             patch("backend.services.curator_service.get_suppressed_topics", return_value=[]), \
             patch("backend.services.curator_service.list_digests", return_value=[]):
            context = _build_memory_context()

        # Fresh-session early return — no category context expected
        assert "Category coverage" not in context

    def test_unexplored_categories_appear_in_context(self):
        from backend.services.curator_service import _build_memory_context

        liked = [
            {"topic": "LoRA Fine-Tuning", "preference_score": 1.0, "difficulty_preference": None, "times_recommended": 1},
        ]

        with patch("backend.services.curator_service.get_top_user_interests", return_value=liked), \
             patch("backend.services.curator_service.get_suppressed_topics", return_value=[]), \
             patch("backend.services.curator_service.get_overall_difficulty_preference", return_value="intermediate"), \
             patch("backend.services.curator_service.get_learning_stage", return_value="early"), \
             patch("backend.services.curator_service.get_frequently_seen_topics", return_value=[]), \
             patch("backend.services.curator_service.list_digests", return_value=[]):
            context = _build_memory_context()

        # With only LLM Training covered, many categories should appear as unexplored
        assert "Consider exploring" in context


# ── TestEndpointWiring ────────────────────────────────────────────────────────

class TestEndpointWiring:
    """Verify the /generate-feed endpoint attaches categories to topics."""

    def test_topics_have_category_field(self):
        from fastapi.testclient import TestClient
        from backend.main import app

        mock_feed = {
            "news_insight": {
                "title": "Test News",
                "summary": "Test summary of the news article.",
                "why_it_matters": "This matters for engineers.",
                "sources": [],
            },
            "perspectives": {
                "common_themes": ["theme1"],
                "synthesis": "Sources collectively show X.",
                "notable_tension": None,
            },
            "learning_topics": [
                {"title": "LoRA Fine-Tuning Techniques",          "reason": "Core PEFT skill", "difficulty": "intermediate"},
                {"title": "RAG Pipeline with Hybrid Retrieval",   "reason": "Practical retrieval", "difficulty": "intermediate"},
                {"title": "Speculative Decoding for Inference",   "reason": "Speed up LLMs", "difficulty": "advanced"},
                {"title": "Tokenization Fundamentals",            "reason": "Foundation", "difficulty": "beginner"},
            ],
            "next_step": "Implement a LoRA adapter on a small model.",
        }

        with patch("backend.main.generate_learning_feed", return_value=mock_feed):
            client = TestClient(app)
            resp = client.post("/generate-feed", json={"interests": "LLM fine-tuning"})

        assert resp.status_code == 200
        topics = resp.json()["learning_topics"]
        assert all("category" in t for t in topics), "Every topic must have a category field"

    def test_categories_are_valid_values(self):
        from fastapi.testclient import TestClient
        from backend.main import app

        mock_feed = {
            "news_insight": {
                "title": "AI Agents News",
                "summary": "Agent systems are becoming more capable.",
                "why_it_matters": "Agents automate complex workflows.",
                "sources": [],
            },
            "perspectives": {
                "common_themes": ["agents", "autonomy"],
                "synthesis": "Sources show agentic AI maturing.",
                "notable_tension": None,
            },
            "learning_topics": [
                {"title": "Autonomous Agent Planning",          "reason": "r1", "difficulty": "intermediate"},
                {"title": "Vector Database Indexing",           "reason": "r2", "difficulty": "beginner"},
                {"title": "Reinforcement Learning for Agents",  "reason": "r3", "difficulty": "advanced"},
                {"title": "RAG Pipeline for Knowledge Agents",  "reason": "r4", "difficulty": "intermediate"},
            ],
            "next_step": "Build a simple ReAct agent.",
        }

        with patch("backend.main.generate_learning_feed", return_value=mock_feed):
            client = TestClient(app)
            resp = client.post("/generate-feed", json={"interests": "AI agents"})

        assert resp.status_code == 200
        from backend.services.topic_cluster import CATEGORIES
        for topic in resp.json()["learning_topics"]:
            assert topic["category"] in CATEGORIES, f"Unknown category: {topic['category']}"

    def test_known_topic_titles_get_correct_category(self):
        from fastapi.testclient import TestClient
        from backend.main import app

        mock_feed = {
            "news_insight": {
                "title": "Finance AI News",
                "summary": "AI models now used in trading.",
                "why_it_matters": "Changes how markets operate.",
                "sources": [],
            },
            "perspectives": {
                "common_themes": ["finance"],
                "synthesis": "Finance AI is growing.",
                "notable_tension": None,
            },
            "learning_topics": [
                {"title": "Quantitative Trading with Neural Networks", "reason": "r1", "difficulty": "advanced"},
                {"title": "RLHF and PEFT Fine-Tuning Methods",           "reason": "r2", "difficulty": "intermediate"},
                {"title": "Approximate Nearest Neighbour Search",       "reason": "r3", "difficulty": "beginner"},
                {"title": "MLOps Experiment Tracking with Weights and Biases", "reason": "r4", "difficulty": "intermediate"},
            ],
            "next_step": "Try a quantitative backtest.",
        }

        with patch("backend.main.generate_learning_feed", return_value=mock_feed):
            client = TestClient(app)
            resp = client.post("/generate-feed", json={"interests": "finance AI"})

        assert resp.status_code == 200
        topic_map = {t["title"]: t["category"] for t in resp.json()["learning_topics"]}
        assert topic_map["Quantitative Trading with Neural Networks"] == "Finance AI"
        assert topic_map["RLHF and PEFT Fine-Tuning Methods"]          == "LLM Training"
        assert topic_map["Approximate Nearest Neighbour Search"]      == "Vector Databases"
        assert topic_map["MLOps Experiment Tracking with Weights and Biases"] == "ML Engineering"
