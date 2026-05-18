"""
Tests for the deep research progress streaming feature.

Covers:
- stream_research_progress generator: status events, result event, stage order
- Cache-hit path (no stage progress, just one status then result)
- Stage failure is non-fatal
- chat_stream integration: status events forwarded for deep_research mode only

TESTING RULES
─────────────
- DeepResearchWorkflow stages are fully mocked — no Tavily, no Groq calls
- get_stored_research is mocked to control cache-hit vs cache-miss paths
- chat_stream integration uses all service mocks (same pattern as other chat tests)
"""

import json
import pytest
from unittest.mock import patch, MagicMock, call


MOCK_RESEARCH = {
    "topic":            "Semiconductors",
    "research_summary": "Global chip supply is concentrated in Taiwan.",
    "key_findings":     ["TSMC holds 60% of advanced node capacity."],
    "viewpoints":       [],
}


# ─────────────────────────────────────────────────────────────────────────────
# stream_research_progress — cache-miss path
# ─────────────────────────────────────────────────────────────────────────────

def _make_wf_mock(wf_result=None):
    """Return (mock_class, mock_instance) pair with STAGES pre-configured."""
    from backend.services.deep_research_service import DeepResearchWorkflow as Real
    mock_wf = MagicMock(spec=Real)
    mock_wf.state = {"result": wf_result or MOCK_RESEARCH}
    for stage in Real.STAGES:
        getattr(mock_wf, stage).return_value = mock_wf
    mock_cls = MagicMock(return_value=mock_wf)
    mock_cls.STAGES = Real.STAGES
    return mock_cls, mock_wf


def _run_progress(message, topic, query_type="default", cached=None, wf_result=None):
    """Run stream_research_progress with mocked workflow and return all events."""
    mock_cls, _ = _make_wf_mock(wf_result)
    with patch("backend.services.deep_research_service.get_stored_research", return_value=cached), \
         patch("backend.services.deep_research_service.DeepResearchWorkflow", mock_cls):
        from backend.services.chat_modes_service import stream_research_progress
        return list(stream_research_progress(message, topic, query_type=query_type))


class TestStreamResearchProgressCacheMiss:
    def test_yields_status_for_each_stage(self):
        events = _run_progress("Semiconductors", "Semiconductors")
        status_events = [v for t, v in events if t == "status"]
        from backend.services.deep_research_service import DeepResearchWorkflow
        # One status per stage
        assert len(status_events) == len(DeepResearchWorkflow.STAGES)

    def test_yields_exactly_one_result_event(self):
        events = _run_progress("Semiconductors", "Semiconductors")
        result_events = [(t, v) for t, v in events if t == "result"]
        assert len(result_events) == 1

    def test_result_event_is_last(self):
        events = _run_progress("Semiconductors", "Semiconductors")
        assert events[-1][0] == "result"

    def test_result_contains_mode(self):
        events = _run_progress("AI chip design", "AI chip design")
        _, result = events[-1]
        assert result["mode"] == "deep_research"

    def test_result_contains_research_data(self):
        events = _run_progress("Semiconductors", "Semiconductors", wf_result=MOCK_RESEARCH)
        _, result = events[-1]
        assert result["deep_research_result"] == MOCK_RESEARCH

    def test_result_carries_query_type(self):
        events = _run_progress("Analyze supply chains", "supply chains", query_type="analysis")
        _, result = events[-1]
        assert result["query_type"] == "analysis"

    def test_stages_run_in_order(self):
        from backend.services.deep_research_service import DeepResearchWorkflow
        from backend.services.chat_modes_service import stream_research_progress

        call_order = []
        mock_cls, mock_wf = _make_wf_mock()
        mock_wf.state = {"result": MOCK_RESEARCH}
        for stage in DeepResearchWorkflow.STAGES:
            getattr(mock_wf, stage).side_effect = lambda s=stage: call_order.append(s) or mock_wf

        with patch("backend.services.deep_research_service.get_stored_research", return_value=None), \
             patch("backend.services.deep_research_service.DeepResearchWorkflow", mock_cls):
            list(stream_research_progress("topic", "topic"))

        assert call_order == list(DeepResearchWorkflow.STAGES)

    def test_no_status_events_are_empty(self):
        events = _run_progress("Semiconductors", "Semiconductors")
        for t, v in events:
            if t == "status":
                assert v.strip() != ""

    def test_status_labels_are_human_readable(self):
        events = _run_progress("Semiconductors", "Semiconductors")
        status_texts = [v for t, v in events if t == "status"]
        for text in status_texts:
            # Should end with ellipsis (…) — indicates ongoing action
            assert text.endswith("…"), f"Status {text!r} should end with …"


# ─────────────────────────────────────────────────────────────────────────────
# stream_research_progress — cache-hit path
# ─────────────────────────────────────────────────────────────────────────────

class TestStreamResearchProgressCacheHit:
    def test_cache_hit_yields_single_status(self):
        events = _run_progress("Semiconductors", "Semiconductors", cached=MOCK_RESEARCH)
        status_events = [v for t, v in events if t == "status"]
        assert len(status_events) == 1

    def test_cache_hit_status_mentions_cache(self):
        events = _run_progress("Semiconductors", "Semiconductors", cached=MOCK_RESEARCH)
        status_text = next(v for t, v in events if t == "status")
        assert "cache" in status_text.lower() or "load" in status_text.lower()

    def test_cache_hit_returns_cached_research(self):
        events = _run_progress("Semiconductors", "Semiconductors", cached=MOCK_RESEARCH)
        _, result = events[-1]
        assert result["deep_research_result"] == MOCK_RESEARCH

    def test_cache_hit_skips_workflow_stages(self):
        from backend.services.chat_modes_service import stream_research_progress

        with patch("backend.services.deep_research_service.get_stored_research", return_value=MOCK_RESEARCH), \
             patch("backend.services.deep_research_service.DeepResearchWorkflow") as wf_cls:
            list(stream_research_progress("topic", "topic"))
        wf_cls.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Stage failure resilience
# ─────────────────────────────────────────────────────────────────────────────

class TestStreamResearchProgressResilience:
    def test_stage_failure_does_not_stop_generator(self):
        from backend.services.deep_research_service import DeepResearchWorkflow
        from backend.services.chat_modes_service import stream_research_progress

        mock_wf = MagicMock(spec=DeepResearchWorkflow)
        mock_wf.state = {"result": MOCK_RESEARCH}
        mock_wf.fetch_articles.side_effect = RuntimeError("Tavily timeout")
        # Other stages fine
        for stage in DeepResearchWorkflow.STAGES:
            if stage != "fetch_articles":
                getattr(mock_wf, stage).return_value = mock_wf

        with patch("backend.services.deep_research_service.get_stored_research", return_value=None), \
             patch("backend.services.deep_research_service.DeepResearchWorkflow", return_value=mock_wf):
            events = list(stream_research_progress("topic", "topic"))

        # Should still yield a result
        result_events = [e for e in events if e[0] == "result"]
        assert len(result_events) == 1

    def test_total_workflow_failure_yields_none_result(self):
        from backend.services.chat_modes_service import stream_research_progress

        with patch("backend.services.deep_research_service.get_stored_research", return_value=None), \
             patch("backend.services.deep_research_service.DeepResearchWorkflow", side_effect=RuntimeError("boom")):
            events = list(stream_research_progress("topic", "topic"))

        result_events = [(t, v) for t, v in events if t == "result"]
        assert len(result_events) == 1
        assert result_events[0][1]["deep_research_result"] is None


# ─────────────────────────────────────────────────────────────────────────────
# chat_stream integration — status events forwarded as NDJSON
# ─────────────────────────────────────────────────────────────────────────────

class TestDeepResearchProgressInChatStream:
    """
    Verify that chat_stream emits status events from stream_research_progress
    for deep_research mode, and does NOT emit them for normal/web_search mode.
    """

    MOCK_PROGRESS = [
        ("status", "Searching sources…"),
        ("status", "Comparing perspectives…"),
        ("status", "Generating findings…"),
        ("result", {"mode": "deep_research", "query_type": "default", "deep_research_result": MOCK_RESEARCH}),
    ]

    def _collect_events(self, message, chat_mode, progress=None):
        from backend.services.chat_service import chat_stream

        with patch("backend.services.chat_service._detect_topic_hint", return_value=None), \
             patch("backend.services.chat_service._load_history_messages", return_value=[{"role":"user","content":"prev"},{"role":"assistant","content":"ans"}]), \
             patch("backend.services.chat_service._save_message", return_value=1), \
             patch("backend.services.memory_injection_service.inject_memory", return_value={}), \
             patch("backend.services.domain_classifier_service.get_domain_context", return_value={}), \
             patch("backend.services.action_router_service.route", return_value=None), \
             patch("backend.services.chat_prompt_service.build_messages",
                   return_value=[{"role": "user", "content": message}]), \
             patch("backend.services.grok_service.ask_grok_chat_stream",
                   return_value=["answer text"]), \
             patch("backend.services.follow_up_service.get_recommendations",
                   return_value={"based_on_topic": None, "source": "empty",
                                 "next_topics": [], "prerequisites": [], "advanced_topics": []}), \
             patch("backend.services.chat_modes_service.stream_research_progress",
                   return_value=iter(progress or self.MOCK_PROGRESS)), \
             patch("backend.services.chat_modes_service._fetch_web_context",
                   return_value={"mode": "web_search", "query_type": "default",
                                 "subjects": [], "web_search_results": []}):
            return [
                json.loads(line.strip())
                for line in chat_stream("s1", message, chat_mode=chat_mode)
                if line.strip()
            ]

    def test_deep_research_emits_multiple_status_events(self):
        events = self._collect_events("Analyze AI chips", "deep_research")
        status_events = [e for e in events if e["t"] == "status"]
        assert len(status_events) == 3

    def test_deep_research_status_text_matches_progress(self):
        events = self._collect_events("Analyze AI chips", "deep_research")
        status_texts = [e["v"] for e in events if e["t"] == "status"]
        assert "Searching sources…" in status_texts
        assert "Generating findings…" in status_texts

    def test_web_search_does_not_use_stream_research_progress(self):
        from backend.services.chat_service import chat_stream
        with patch("backend.services.chat_service._detect_topic_hint", return_value=None), \
             patch("backend.services.chat_service._load_history_messages", return_value=[{"role":"user","content":"prev"},{"role":"assistant","content":"ans"}]), \
             patch("backend.services.chat_service._save_message", return_value=1), \
             patch("backend.services.memory_injection_service.inject_memory", return_value={}), \
             patch("backend.services.domain_classifier_service.get_domain_context", return_value={}), \
             patch("backend.services.action_router_service.route", return_value=None), \
             patch("backend.services.chat_prompt_service.build_messages",
                   return_value=[{"role": "user", "content": "search query"}]), \
             patch("backend.services.grok_service.ask_grok_chat_stream",
                   return_value=["ok"]), \
             patch("backend.services.follow_up_service.get_recommendations",
                   return_value={"based_on_topic": None, "source": "empty",
                                 "next_topics": [], "prerequisites": [], "advanced_topics": []}), \
             patch("backend.services.chat_modes_service.stream_research_progress") as mock_srp, \
             patch("backend.services.chat_modes_service._fetch_web_context",
                   return_value={"mode": "web_search", "query_type": "default",
                                 "subjects": [], "web_search_results": []}):
            list(chat_stream("s1", "search query", chat_mode="web_search"))
        mock_srp.assert_not_called()

    def test_normal_mode_emits_no_status_events(self):
        from backend.services.chat_service import chat_stream
        with patch("backend.services.chat_service._detect_topic_hint", return_value=None), \
             patch("backend.services.chat_service._load_history_messages", return_value=[{"role":"user","content":"prev"},{"role":"assistant","content":"ans"}]), \
             patch("backend.services.chat_service._save_message", return_value=1), \
             patch("backend.services.memory_injection_service.inject_memory", return_value={}), \
             patch("backend.services.domain_classifier_service.get_domain_context", return_value={}), \
             patch("backend.services.action_router_service.route", return_value=None), \
             patch("backend.services.chat_prompt_service.build_messages",
                   return_value=[{"role": "user", "content": "what is AI?"}]), \
             patch("backend.services.grok_service.ask_grok_chat_stream",
                   return_value=["ok"]), \
             patch("backend.services.follow_up_service.get_recommendations",
                   return_value={"based_on_topic": None, "source": "empty",
                                 "next_topics": [], "prerequisites": [], "advanced_topics": []}):
            events = [
                json.loads(line.strip())
                for line in chat_stream("s1", "what is AI?", chat_mode="normal")
                if line.strip()
            ]
        status_events = [e for e in events if e["t"] == "status"]
        assert len(status_events) == 0

    def test_status_events_arrive_before_chunk_events(self):
        events = self._collect_events("Analyze AI chips", "deep_research")
        event_types = [e["t"] for e in events]
        # All status events should come before any chunk
        last_status_idx = max((i for i, t in enumerate(event_types) if t == "status"), default=-1)
        first_chunk_idx = next((i for i, t in enumerate(event_types) if t == "chunk"), len(event_types))
        assert last_status_idx < first_chunk_idx

    def test_done_event_includes_chat_mode(self):
        events = self._collect_events("Analyze AI chips", "deep_research")
        done = next(e for e in events if e["t"] == "done")
        assert done["chat_mode"] == "deep_research"
