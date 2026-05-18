"""
Tests for the /digests API endpoints.

All tests use mocked digest storage — no SQLite file, no AI calls.

Run:
    pytest tests/test_digest_endpoints.py -v
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.main import app

client = TestClient(app)

# ── Shared mock data ──────────────────────────────────────────────────────────

def _make_digest(id=1, title="Test Insight", source="scheduler", ts="2025-05-14 08:00:00"):
    return {
        "id": id,
        "generated_at": ts,
        "news_title": title,
        "news_summary": "A clear summary.",
        "why_it_matters": "Because it does.",
        "learning_topics": [
            {"title": "Topic A", "reason": "Reason A", "difficulty": "beginner"},
            {"title": "Topic B", "reason": "Reason B", "difficulty": "intermediate"},
            {"title": "Topic C", "reason": "Reason C", "difficulty": "intermediate"},
            {"title": "Topic D", "reason": "Reason D", "difficulty": "advanced"},
        ],
        "next_step": "Keep going.",
        "source_links": ["https://example.com/a", "https://example.com/b"],
        "source": source,
    }

DIGEST_1 = _make_digest(id=1, title="First Insight",  ts="2025-05-14 08:00:00")
DIGEST_2 = _make_digest(id=2, title="Second Insight", ts="2025-05-15 08:00:00", source="user")


# ── GET /digests/latest ───────────────────────────────────────────────────────

class TestDigestsLatest:
    BASE = "backend.main.get_latest_digest"

    def test_returns_200_with_digest(self):
        with patch(self.BASE, return_value=DIGEST_1):
            r = client.get("/digests/latest")
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == 1
        assert data["news_title"] == "First Insight"

    def test_returns_null_when_empty(self):
        with patch(self.BASE, return_value=None):
            r = client.get("/digests/latest")
        assert r.status_code == 200
        assert r.json() is None

    def test_response_has_all_fields(self):
        with patch(self.BASE, return_value=DIGEST_1):
            r = client.get("/digests/latest")
        data = r.json()
        for key in ("id", "generated_at", "news_title", "news_summary",
                    "why_it_matters", "learning_topics", "next_step",
                    "source_links", "source"):
            assert key in data, f"missing field: {key}"

    def test_learning_topics_is_list_of_four(self):
        with patch(self.BASE, return_value=DIGEST_1):
            r = client.get("/digests/latest")
        topics = r.json()["learning_topics"]
        assert isinstance(topics, list) and len(topics) == 4

    def test_source_links_is_list(self):
        with patch(self.BASE, return_value=DIGEST_1):
            r = client.get("/digests/latest")
        assert isinstance(r.json()["source_links"], list)

    def test_source_field_preserved(self):
        with patch(self.BASE, return_value=DIGEST_2):
            r = client.get("/digests/latest")
        assert r.json()["source"] == "user"


# ── GET /digests (list) ───────────────────────────────────────────────────────

class TestDigestsList:
    LIST_BASE  = "backend.main.list_digests"
    DATE_BASE  = "backend.main.get_digests_by_date"

    def test_returns_list(self):
        with patch(self.LIST_BASE, return_value=[DIGEST_1, DIGEST_2]):
            r = client.get("/digests")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        assert len(r.json()) == 2

    def test_empty_list_when_no_digests(self):
        with patch(self.LIST_BASE, return_value=[]):
            r = client.get("/digests")
        assert r.json() == []

    def test_date_param_routes_to_get_digests_by_date(self):
        with patch(self.DATE_BASE, return_value=[DIGEST_1]) as mock_date, \
             patch(self.LIST_BASE, return_value=[]) as mock_list:
            r = client.get("/digests?date=2025-05-14")
        assert r.status_code == 200
        mock_date.assert_called_once_with("2025-05-14")
        mock_list.assert_not_called()

    def test_no_date_param_routes_to_list_digests(self):
        with patch(self.LIST_BASE, return_value=[DIGEST_1]) as mock_list, \
             patch(self.DATE_BASE, return_value=[]) as mock_date:
            r = client.get("/digests")
        mock_list.assert_called_once()
        mock_date.assert_not_called()

    def test_limit_param_forwarded(self):
        with patch(self.LIST_BASE, return_value=[]) as mock_list:
            client.get("/digests?limit=5")
        mock_list.assert_called_once_with(limit=5)

    def test_each_item_has_required_fields(self):
        with patch(self.LIST_BASE, return_value=[DIGEST_1, DIGEST_2]):
            r = client.get("/digests")
        for item in r.json():
            assert "id" in item
            assert "news_title" in item
            assert "generated_at" in item


# ── GET /digests/{id} ─────────────────────────────────────────────────────────

class TestDigestById:
    BASE = "backend.main.get_digest_by_id"

    def test_returns_digest_by_id(self):
        with patch(self.BASE, return_value=DIGEST_1):
            r = client.get("/digests/1")
        assert r.status_code == 200
        assert r.json()["id"] == 1

    def test_returns_404_when_not_found(self):
        with patch(self.BASE, return_value=None):
            r = client.get("/digests/9999")
        assert r.status_code == 404
        assert "not found" in r.json()["detail"].lower()

    def test_correct_id_passed_to_service(self):
        with patch(self.BASE, return_value=DIGEST_2) as mock_fn:
            client.get("/digests/2")
        mock_fn.assert_called_once_with(2)

    def test_full_fields_returned(self):
        with patch(self.BASE, return_value=DIGEST_2):
            r = client.get("/digests/2")
        data = r.json()
        assert data["news_title"] == "Second Insight"
        assert data["source"] == "user"
        assert len(data["learning_topics"]) == 4
