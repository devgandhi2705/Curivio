"""
Tests for backend.llm.chat_router — Chat-R4 LLM-based turn router.

Real LLM calls (classify_message hits the live pooled classifier model) —
marked @pytest.mark.integration per this project's convention (pytest.ini
excludes `integration` by default; run with `-m integration`). Structural
shape is asserted (task_type bucket, field types, needs_tool<->shaped_query
gating), never exact wording, since live model output varies run to run.
"""
from __future__ import annotations

import pytest

from backend.llm.chat_router import RoutingDecision, classify_message, map_to_task_type


# ─────────────────────────────────────────────────────────────────────────────
# map_to_task_type — pure function, deterministic, no LLM call
# ─────────────────────────────────────────────────────────────────────────────

class TestMapToTaskType:
    def test_code_execution_wins_first(self):
        d = RoutingDecision(needs_tool=True, tool_name="web_search", complexity="complex",
                             requires_code_execution=True, shaped_query="x")
        assert map_to_task_type(d) == "coding"

    def test_needs_tool_when_no_code_execution(self):
        d = RoutingDecision(needs_tool=True, tool_name="web_search", complexity="simple",
                             requires_code_execution=False, shaped_query="x")
        assert map_to_task_type(d) == "tool_use"

    def test_complex_when_no_tool_no_code(self):
        d = RoutingDecision(needs_tool=False, tool_name="none", complexity="complex",
                             requires_code_execution=False, shaped_query="")
        assert map_to_task_type(d) == "complex_reasoning"

    def test_simple_qa_fallback(self):
        d = RoutingDecision(needs_tool=False, tool_name="none", complexity="simple",
                             requires_code_execution=False, shaped_query="")
        assert map_to_task_type(d) == "simple_qa"


# ─────────────────────────────────────────────────────────────────────────────
# classify_message -> map_to_task_type — real live classifier, one clear
# example per bucket. Live-verified once (see phase report): all 4 landed
# in their expected bucket with needs_tool<->shaped_query correctly gated.
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestClassifyMessageRouting:
    def _classify(self, message: str) -> RoutingDecision:
        decision = classify_message(message)
        assert decision is not None, "classifier unavailable (all pooled legs failed) — cannot assert routing"
        return decision

    def test_coding_message_routes_to_coding(self):
        d = self._classify(
            "Write a Python function that reverses a linked list, then run it on [1,2,3,4] to check for bugs"
        )
        assert d.requires_code_execution is True
        assert map_to_task_type(d) == "coding"

    def test_live_data_message_routes_to_tool_use(self):
        d = self._classify("What's the current live price of Bitcoin right now, today?")
        assert d.needs_tool is True
        assert d.tool_name == "web_search"
        assert d.shaped_query != "", "needs_tool=True must produce a non-empty shaped_query"
        assert map_to_task_type(d) == "tool_use"

    def test_multi_factor_question_routes_to_complex_reasoning(self):
        d = self._classify(
            "Explain the tradeoffs between microservices and a monolith for an early-stage "
            "fintech startup, including how each choice affects long-term technical debt and "
            "team velocity."
        )
        assert d.needs_tool is False
        assert d.requires_code_execution is False
        assert d.complexity == "complex"
        assert map_to_task_type(d) == "complex_reasoning"

    def test_trivia_question_routes_to_simple_qa(self):
        d = self._classify("What is the capital of France?")
        assert d.needs_tool is False
        assert d.requires_code_execution is False
        assert d.complexity == "simple"
        assert map_to_task_type(d) == "simple_qa"

    def test_needs_tool_false_means_empty_shaped_query(self):
        d = self._classify("What is the capital of France?")
        assert d.needs_tool is False
        assert d.shaped_query == "", "shaped_query must be empty when needs_tool is False (field contract)"
