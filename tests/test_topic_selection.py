"""
Tests for POST /select-topics.

All tests mock process_feedback — no real DB writes, no AI calls.

Run:
    pytest tests/test_topic_selection.py -v
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, call

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.main import app

client = TestClient(app)
BASE = "backend.main.process_feedback"


def _feedback_row(topic, times_liked=1):
    return {
        "topic":                topic,
        "feedback":             "liked",
        "message":              "Marked as helpful",
        "preference_score":     round(times_liked / max(1, times_liked), 4),
        "difficulty_preference": "intermediate",
        "times_liked":          times_liked,
        "times_disliked":       0,
        "times_recommended":    times_liked,
        "last_updated":         "2025-05-14 08:00:00",
    }


# ── Validation ────────────────────────────────────────────────────────────────

class TestValidation:
    def test_empty_list_rejected(self):
        r = client.post("/select-topics", json={"topics": []})
        assert r.status_code == 422

    def test_three_topics_rejected(self):
        r = client.post("/select-topics", json={"topics": ["A", "B", "C"]})
        assert r.status_code == 422

    def test_duplicate_topics_rejected(self):
        r = client.post("/select-topics", json={"topics": ["RAG", "RAG"]})
        assert r.status_code == 422

    def test_missing_body_rejected(self):
        r = client.post("/select-topics")
        assert r.status_code == 422

    def test_one_topic_accepted(self):
        with patch(BASE, return_value=_feedback_row("RAG")):
            r = client.post("/select-topics", json={"topics": ["RAG"]})
        assert r.status_code == 200

    def test_two_topics_accepted(self):
        with patch(BASE, side_effect=[_feedback_row("RAG"), _feedback_row("LLMs")]):
            r = client.post("/select-topics", json={"topics": ["RAG", "LLMs"]})
        assert r.status_code == 200


# ── Response shape ────────────────────────────────────────────────────────────

class TestResponseShape:
    def test_selected_list_length_matches_input(self):
        with patch(BASE, side_effect=[_feedback_row("RAG"), _feedback_row("LLMs")]):
            r = client.post("/select-topics", json={"topics": ["RAG", "LLMs"]})
        assert len(r.json()["selected"]) == 2

    def test_message_field_present(self):
        with patch(BASE, return_value=_feedback_row("RAG")):
            r = client.post("/select-topics", json={"topics": ["RAG"]})
        assert "message" in r.json()

    def test_message_singular_for_one_topic(self):
        with patch(BASE, return_value=_feedback_row("RAG")):
            r = client.post("/select-topics", json={"topics": ["RAG"]})
        msg = r.json()["message"]
        assert "1 topic" in msg and "topics" not in msg

    def test_message_plural_for_two_topics(self):
        with patch(BASE, side_effect=[_feedback_row("RAG"), _feedback_row("LLMs")]):
            r = client.post("/select-topics", json={"topics": ["RAG", "LLMs"]})
        assert "2 topics" in r.json()["message"]

    def test_each_result_has_required_fields(self):
        with patch(BASE, return_value=_feedback_row("RAG")):
            r = client.post("/select-topics", json={"topics": ["RAG"]})
        item = r.json()["selected"][0]
        for key in ("topic", "preference_score", "times_liked", "times_recommended", "difficulty_preference"):
            assert key in item, f"missing field: {key}"

    def test_topic_name_preserved_in_result(self):
        with patch(BASE, return_value=_feedback_row("Prompt Engineering")):
            r = client.post("/select-topics", json={"topics": ["Prompt Engineering"]})
        assert r.json()["selected"][0]["topic"] == "Prompt Engineering"


# ── Feedback delegation ───────────────────────────────────────────────────────

class TestFeedbackDelegation:
    def test_calls_process_feedback_with_liked_for_each_topic(self):
        with patch(BASE, side_effect=[_feedback_row("RAG"), _feedback_row("LLMs")]) as mock_fn:
            client.post("/select-topics", json={"topics": ["RAG", "LLMs"]})
        mock_fn.assert_has_calls([
            call("RAG",  "liked"),
            call("LLMs", "liked"),
        ])

    def test_calls_process_feedback_exactly_once_per_topic(self):
        with patch(BASE, return_value=_feedback_row("RAG")) as mock_fn:
            client.post("/select-topics", json={"topics": ["RAG"]})
        assert mock_fn.call_count == 1

    def test_preference_score_reflected_in_response(self):
        row = _feedback_row("Deep Learning", times_liked=3)
        row["preference_score"] = 0.75
        with patch(BASE, return_value=row):
            r = client.post("/select-topics", json={"topics": ["Deep Learning"]})
        assert r.json()["selected"][0]["preference_score"] == 0.75

    def test_times_liked_incremented_in_response(self):
        with patch(BASE, return_value=_feedback_row("RAG", times_liked=4)):
            r = client.post("/select-topics", json={"topics": ["RAG"]})
        assert r.json()["selected"][0]["times_liked"] == 4


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_whitespace_topic_name_passes_through(self):
        with patch(BASE, return_value=_feedback_row("  RAG  ")):
            r = client.post("/select-topics", json={"topics": ["  RAG  "]})
        assert r.status_code == 200

    def test_long_topic_name_accepted(self):
        long_name = "A" * 200
        with patch(BASE, return_value=_feedback_row(long_name)):
            r = client.post("/select-topics", json={"topics": [long_name]})
        assert r.status_code == 200

    def test_difficulty_preference_null_allowed(self):
        row = _feedback_row("RAG")
        row["difficulty_preference"] = None
        with patch(BASE, return_value=row):
            r = client.post("/select-topics", json={"topics": ["RAG"]})
        assert r.json()["selected"][0]["difficulty_preference"] is None
