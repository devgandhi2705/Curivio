"""
Live provider test (Phase 3b) — proves the v2 provider's Gemini leg drives
real structured output through GenerateContentConfig.response_schema using each
agent's raw-dict JSON schema (google-genai 2.10.0 accepts dict[Any, Any] and
treats it as an OpenAPI-3.0-subset Schema).

Skipped automatically when no Gemini key is configured, so CI never needs live
credentials. Marked `integration` so it's also excluded by the default
`-m "not integration"` addopts; run explicitly with `-m integration`.
"""
import os

import pytest

from backend.services.feed_v2.llm import provider

_HAS_GEMINI_KEY = bool(os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY")
                       or os.getenv("GEMINI_BACKUP_API_KEY"))


@pytest.mark.integration
@pytest.mark.skipif(not _HAS_GEMINI_KEY, reason="no Gemini API key configured")
def test_lesson_planner_live_structured_output(capsys):
    """lesson_planner's primary leg is gemini-3-flash-preview → this exercises
    the raw-dict response_schema path end to end against the real API."""
    result = provider.call_agent(
        "lesson_planner",
        messages=[{"role": "user",
                   "content": "Create a one-day introductory lesson on binary search. "
                              "Return exactly 3 concise learning objectives."}],
        system="You are a lesson planner. Respond with a JSON object whose "
               "'objectives' field is an array of short objective strings.",
        meta={"call_type": "feed_v2_phase3b_live", "surface": "feed_v2",
              "trace_id": "p3b-live-trace", "agent_name": "lesson_planner",
              "step_index": 0, "user_id": "u_test"},
    )
    assert isinstance(result, dict), result
    assert "objectives" in result, result            # the declared schema's required key
    assert isinstance(result["objectives"], list) and result["objectives"], result
    with capsys.disabled():
        print("\nLIVE lesson_planner structured result:", result)
