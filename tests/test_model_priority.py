"""
Chat-R3: model priority registry — data + lookup only, no routing logic.
Confirms get_model_priority_list() returns the exact ordered list per task
type and that callers can't mutate the shared registry through it.
"""
from __future__ import annotations

from backend.config import (
    GEMINI_FALLBACK_MODEL, GEMINI_LITE_MODEL, GEMINI_MODEL,
    GROQ_FALLBACK_MODEL, GROQ_FAST_MODEL,
)
from backend.llm.model_priority import TASK_MODEL_PRIORITY, get_model_priority_list

_EXPECTED = {
    "routing": [("groq", GROQ_FAST_MODEL), ("gemini", GEMINI_LITE_MODEL)],
    "simple_qa": [
        ("gemini", GEMINI_MODEL), ("groq", GROQ_FAST_MODEL), ("gemini", GEMINI_FALLBACK_MODEL),
    ],
    "complex_reasoning": [
        ("gemini", GEMINI_MODEL), ("gemini", GEMINI_FALLBACK_MODEL), ("groq", GROQ_FALLBACK_MODEL),
    ],
    "coding": [
        ("gemini", GEMINI_FALLBACK_MODEL), ("gemini", GEMINI_MODEL), ("groq", GROQ_FALLBACK_MODEL),
    ],
    "tool_use": [
        ("gemini", GEMINI_MODEL), ("gemini", GEMINI_FALLBACK_MODEL), ("groq", GROQ_FALLBACK_MODEL),
    ],
    "vision": [("gemini", GEMINI_MODEL), ("gemini", GEMINI_FALLBACK_MODEL)],
}


def test_every_task_type_has_a_registry_entry():
    assert set(TASK_MODEL_PRIORITY) == set(_EXPECTED)


def test_get_model_priority_list_returns_correct_order_per_task_type():
    for task_type, expected in _EXPECTED.items():
        got = get_model_priority_list(task_type)
        assert got == expected, f"{task_type}: expected {expected}, got {got}"


def test_returned_list_is_a_copy_not_the_live_registry():
    got = get_model_priority_list("routing")
    got.append(("groq", "should-not-persist"))
    assert TASK_MODEL_PRIORITY["routing"] == _EXPECTED["routing"]


def test_unknown_task_type_raises():
    try:
        get_model_priority_list("not_a_real_task_type")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "not_a_real_task_type" in str(exc)


if __name__ == "__main__":
    test_every_task_type_has_a_registry_entry()
    test_get_model_priority_list_returns_correct_order_per_task_type()
    test_returned_list_is_a_copy_not_the_live_registry()
    test_unknown_task_type_raises()
    print("all model_priority registry checks passed")
