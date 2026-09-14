"""
Tests for streaming AI responses.

Covers:
  - chat_stream           (chat_service)
  - POST /chat/stream     (FastAPI endpoint)

All tests mock external calls (Groq API, DB) per project testing rules.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_ndjson(text: str) -> list[dict]:
    return [json.loads(line) for line in text.strip().splitlines() if line.strip()]


EMPTY_CONTEXT = {
    "user_profile":        {},
    "research":            {},
    "session":             {},
    "conversation_memory": {
        "message_count": 0, "session_turns": 0,
        "topics_discussed": [], "last_user_messages": [],
    },
    "exploration_breadth": {
        "total_explored": 0, "all_topics": [],
        "recently_explored": [], "deep_dived_topics": [],
    },
    "preference_snapshot": {},
    "learner_profile":     {},
    "continuity":          {},
}

EMPTY_RECOMMENDATIONS = {
    "based_on_topic": None, "source": "empty",
    "next_topics": [], "prerequisites": [], "advanced_topics": [],
}


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def patched_chat_stream(monkeypatch):
    """
    Patch all external dependencies of chat_stream so tests run without
    a DB or live Groq API.
    """
    import backend.services.memory_injection_service as mis
    import backend.services.chat_prompt_service      as cps
    import backend.services.follow_up_service        as fus
    import backend.services.chat_service             as cs

    monkeypatch.setattr(mis, "inject_memory",       lambda *a, **kw: dict(EMPTY_CONTEXT))
    monkeypatch.setattr(cps, "build_messages",      lambda *a, **kw: [{"role": "user", "content": "hi"}])
    monkeypatch.setattr(fus, "get_recommendations", lambda *a, **kw: dict(EMPTY_RECOMMENDATIONS))
    monkeypatch.setattr(cs,  "_load_history_messages", lambda *a, **kw: [])
    monkeypatch.setattr(cs,  "_save_message",          lambda *a, **kw: 42)
    monkeypatch.setattr(cs,  "_detect_topic_hint",     lambda *a, **kw: None)

    import backend.llm.chat_agent  as chat_agent
    import backend.llm.chat_router as chat_router

    monkeypatch.setattr(
        chat_agent, "ask_chat_stream",
        lambda *a, **kw: iter([
            {"type": "text", "text": "Hello", "seq": 0, "block_id": 0},
            {"type": "text", "text": ", ",    "seq": 1, "block_id": 0},
            {"type": "text", "text": "world", "seq": 2, "block_id": 0},
            {"type": "text", "text": "!",     "seq": 3, "block_id": 0},
        ]),
    )
    monkeypatch.setattr(chat_router, "classify_message", lambda *a, **kw: None)


@pytest.fixture
def api_client():
    from fastapi.testclient import TestClient
    from backend.main import app
    return TestClient(app)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. chat_stream generator
# ═══════════════════════════════════════════════════════════════════════════════

class TestChatStreamGenerator:
    def _collect(self, session_id, message, **kw):
        from backend.services.chat_service import chat_stream
        lines = list(chat_stream(session_id, message, **kw))
        return [json.loads(l) for l in lines if l.strip()]

    def test_yields_chunks_then_done(self, patched_chat_stream):
        events = self._collect("sess1", "What is Python?")
        types = [e["t"] for e in events]
        assert "chunk" in types
        assert types[-1] == "done"

    def test_chunk_events_contain_text(self, patched_chat_stream):
        events = self._collect("sess1", "Hello")
        chunks = [e for e in events if e["t"] == "chunk"]
        assert chunks
        for c in chunks:
            assert isinstance(c["v"], str)
            assert len(c["v"]) > 0

    def test_concatenated_chunks_equal_full_response(self, patched_chat_stream):
        events = self._collect("sess1", "Hello")
        text = "".join(e["v"] for e in events if e["t"] == "chunk")
        assert text == "Hello, world!"

    def test_done_event_has_required_fields(self, patched_chat_stream):
        events = self._collect("sess1", "Hello")
        done = next(e for e in events if e["t"] == "done")
        assert "message_id"   in done
        assert "topic_hint"   in done
        assert "context_used" in done
        assert "created_at"   in done
        assert "recommendations" in done

    def test_done_event_message_id_from_save(self, patched_chat_stream):
        events = self._collect("sess1", "Hello")
        done = next(e for e in events if e["t"] == "done")
        assert done["message_id"] == 42  # fixture returns 42

    def test_error_on_empty_session_id(self, patched_chat_stream):
        events = self._collect("", "Hello")
        assert events[0]["t"] == "error"
        assert len(events) == 1

    def test_error_on_empty_message(self, patched_chat_stream):
        events = self._collect("sess1", "")
        assert events[0]["t"] == "error"
        assert len(events) == 1

    def test_error_on_whitespace_session_id(self, patched_chat_stream):
        events = self._collect("   ", "Hello")
        assert events[0]["t"] == "error"

    def test_error_on_context_prep_failure(self, monkeypatch, patched_chat_stream):
        import backend.services.memory_injection_service as mis
        monkeypatch.setattr(mis, "inject_memory", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("DB down")))
        events = self._collect("sess1", "Hello")
        assert events[0]["t"] == "error"
        assert len(events) == 1

    def test_error_on_ai_failure_after_no_chunks(self, monkeypatch, patched_chat_stream):
        import backend.llm.chat_agent as chat_agent
        def boom(*a, **kw):
            raise RuntimeError("model unavailable")
        monkeypatch.setattr(chat_agent, "ask_chat_stream", boom)
        events = self._collect("sess1", "Hello")
        assert events[-1]["t"] == "error"

    def test_partial_chunks_then_error(self, monkeypatch, patched_chat_stream):
        import backend.llm.chat_agent as chat_agent
        def partial_stream(*a, **kw):
            yield {"type": "text", "text": "Partial", "seq": 0, "block_id": 0}
            raise RuntimeError("Disconnected mid-stream")
        monkeypatch.setattr(chat_agent, "ask_chat_stream", partial_stream)
        events = self._collect("sess1", "Hello")
        types = [e["t"] for e in events]
        assert "chunk" in types
        assert types[-1] == "error"
        assert "done" not in types

    def test_topic_hint_auto_detected(self, monkeypatch, patched_chat_stream):
        import backend.services.chat_service as cs
        monkeypatch.setattr(cs, "_detect_topic_hint", lambda msg: "Python")
        events = self._collect("sess1", "Tell me about Python")
        done = next(e for e in events if e["t"] == "done")
        assert done["topic_hint"] == "Python"

    def test_topic_hint_supplied_skips_detection(self, monkeypatch, patched_chat_stream):
        import backend.services.chat_service as cs
        detected = []
        monkeypatch.setattr(cs, "_detect_topic_hint", lambda msg: detected.append(msg) or "ignored")
        events = self._collect("sess1", "Hello", topic_hint="Rust")
        assert detected == []  # detection not called
        done = next(e for e in events if e["t"] == "done")
        assert done["topic_hint"] == "Rust"

    def test_save_message_called_twice(self, monkeypatch, patched_chat_stream):
        import backend.services.chat_service as cs
        calls = []
        monkeypatch.setattr(cs, "_save_message", lambda *a, **kw: calls.append(a[1]) or 99)
        list(cs.chat_stream("sess1", "Hello"))
        assert "user" in calls
        assert "assistant" in calls

    def test_recommendations_in_done_event(self, monkeypatch, patched_chat_stream):
        import backend.services.follow_up_service as fus
        monkeypatch.setattr(fus, "get_recommendations", lambda *a, **kw: {
            "based_on_topic": "Python",
            "source": "stored",
            "next_topics": [{"topic": "Django", "reason": "popular framework"}],
            "prerequisites": [],
            "advanced_topics": [],
        })
        events = self._collect("sess1", "Python")
        done = next(e for e in events if e["t"] == "done")
        assert done["recommendations"]["source"] == "stored"
        assert done["recommendations"]["next_topics"][0]["topic"] == "Django"

    def test_recommendations_failure_is_non_fatal(self, monkeypatch, patched_chat_stream):
        import backend.services.follow_up_service as fus
        monkeypatch.setattr(fus, "get_recommendations",
                            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("rec error")))
        events = self._collect("sess1", "Hello")
        done = next((e for e in events if e["t"] == "done"), None)
        assert done is not None
        assert done["recommendations"]["source"] == "empty"

    def test_continuity_recorded_when_topic_present(self, monkeypatch, patched_chat_stream):
        import backend.services.chat_service as cs
        import backend.services.continuity_service as cont
        monkeypatch.setattr(cs, "_detect_topic_hint", lambda msg: "Python")
        recorded = []
        monkeypatch.setattr(cont, "record_concepts",         lambda *a, **kw: recorded.append("concepts"))
        monkeypatch.setattr(cont, "record_recommendations",  lambda *a, **kw: recorded.append("recs"))
        list(cs.chat_stream("sess1", "Tell me about Python"))
        assert "concepts" in recorded
        assert "recs" in recorded

    def test_continuity_failure_is_non_fatal(self, monkeypatch, patched_chat_stream):
        import backend.services.chat_service as cs
        import backend.services.continuity_service as cont
        monkeypatch.setattr(cs, "_detect_topic_hint", lambda msg: "Python")
        monkeypatch.setattr(cont, "record_concepts", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError()))
        events = self._collect("sess1", "Python")
        assert any(e["t"] == "done" for e in events)

    def test_context_used_in_done_event(self, patched_chat_stream):
        events = self._collect("sess1", "Hello")
        done = next(e for e in events if e["t"] == "done")
        cu = done["context_used"]
        assert "has_deep_research"     in cu
        assert "has_learning_path"     in cu
        assert "history_turns"         in cu
        assert "interests_count"       in cu
        assert "total_topics_explored" in cu

    def test_persistence_failure_yields_done_with_zero_id(self, monkeypatch, patched_chat_stream):
        import backend.services.chat_service as cs
        monkeypatch.setattr(cs, "_save_message", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("DB full")))
        events = self._collect("sess1", "Hello")
        done = next((e for e in events if e["t"] == "done"), None)
        assert done is not None
        assert done["message_id"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 2. POST /chat/stream endpoint
# ═══════════════════════════════════════════════════════════════════════════════

class TestStreamEndpoint:
    def _mock_stream(self, monkeypatch, events=None):
        """Patch the generator imported by main.py."""
        if events is None:
            events = [
                json.dumps({"t": "chunk", "v": "Hello"}) + "\n",
                json.dumps({"t": "chunk", "v": " world"}) + "\n",
                json.dumps({
                    "t": "done", "message_id": 1, "topic_hint": "Python",
                    "action": None,
                    "recommendations": EMPTY_RECOMMENDATIONS,
                    "context_used": {
                        "has_deep_research": False, "has_learning_path": False,
                        "has_topic_expansion": False, "has_github_repos": False,
                        "interests_count": 0, "history_turns": 0,
                        "topics_in_session": 0, "total_topics_explored": 0,
                    },
                    "created_at": "2026-01-01 00:00:00",
                }) + "\n",
            ]
        monkeypatch.setattr("backend.main.chat_stream_generator", lambda *a, **kw: iter(events))

    def test_returns_200(self, api_client, monkeypatch):
        self._mock_stream(monkeypatch)
        resp = api_client.post("/chat/stream", json={"session_id": "s1", "message": "Hi"})
        assert resp.status_code == 200

    def test_content_type_is_ndjson(self, api_client, monkeypatch):
        self._mock_stream(monkeypatch)
        resp = api_client.post("/chat/stream", json={"session_id": "s1", "message": "Hi"})
        assert "ndjson" in resp.headers["content-type"]

    def test_response_is_valid_ndjson(self, api_client, monkeypatch):
        self._mock_stream(monkeypatch)
        resp = api_client.post("/chat/stream", json={"session_id": "s1", "message": "Hi"})
        events = _parse_ndjson(resp.text)
        assert len(events) == 3

    def test_chunk_events_in_order(self, api_client, monkeypatch):
        self._mock_stream(monkeypatch)
        resp = api_client.post("/chat/stream", json={"session_id": "s1", "message": "Hi"})
        events = _parse_ndjson(resp.text)
        chunks = [e for e in events if e["t"] == "chunk"]
        assert [c["v"] for c in chunks] == ["Hello", " world"]

    def test_last_event_is_done(self, api_client, monkeypatch):
        self._mock_stream(monkeypatch)
        resp = api_client.post("/chat/stream", json={"session_id": "s1", "message": "Hi"})
        events = _parse_ndjson(resp.text)
        assert events[-1]["t"] == "done"

    def test_done_event_has_message_id(self, api_client, monkeypatch):
        self._mock_stream(monkeypatch)
        resp = api_client.post("/chat/stream", json={"session_id": "s1", "message": "Hi"})
        done = _parse_ndjson(resp.text)[-1]
        assert done["message_id"] == 1

    def test_error_event_propagated(self, api_client, monkeypatch):
        error_events = [json.dumps({"t": "error", "message": "Test error"}) + "\n"]
        self._mock_stream(monkeypatch, events=error_events)
        resp = api_client.post("/chat/stream", json={"session_id": "s1", "message": "Hi"})
        events = _parse_ndjson(resp.text)
        assert events[0]["t"] == "error"

    def test_missing_session_id_returns_422(self, api_client):
        resp = api_client.post("/chat/stream", json={"message": "Hi"})
        assert resp.status_code == 422

    def test_missing_message_returns_422(self, api_client):
        resp = api_client.post("/chat/stream", json={"session_id": "s1"})
        assert resp.status_code == 422

    def test_no_cache_header_set(self, api_client, monkeypatch):
        self._mock_stream(monkeypatch)
        resp = api_client.post("/chat/stream", json={"session_id": "s1", "message": "Hi"})
        assert resp.headers.get("cache-control") == "no-cache"
