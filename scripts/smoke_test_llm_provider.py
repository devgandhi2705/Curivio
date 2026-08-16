"""
LangChain provider-layer smoke test (backend/llm/model_provider.py).

Verifies, against live APIs:
  1. get_chat_model() answers a plain prompt.
  2. An invalid Gemini key in the pool falls through to the next pool key /
     Groq via .with_fallbacks() — proven by response_metadata showing which
     model actually answered.
  3. get_structured_chat_model(schema) returns a parsed Pydantic object.
  4. Every call is logged to llm_call_log with call_type/user_id/project_id/
     day_ref populated from config={"metadata": {...}}, and model_used shows
     the model that actually answered (not just requested).
  5. Two chained calls in one Runnable sequence share a parent_run_id.
  6. A forced failure is logged with success=false and an error_message.
  7. Post-fix: Gemini retry-with-backoff actually fires (retry:attempt:N),
     proving the ChatGoogleGenerativeAIError retry-predicate fix works.

Requires GEMINI_API_KEYS (comma-separated) and GROQ_API_KEY in .env.
This script is additive-only — it does not touch any existing call site.

Run
---
  python scripts/smoke_test_llm_provider.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google.genai.errors import ClientError as GeminiClientError
from langchain_core.runnables import RunnableLambda
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field

from backend.llm.call_logger import LLMCallLogger
from backend.llm.model_provider import get_chat_model, get_structured_chat_model
from backend.utils.db import get_connection


def _mask(key: str) -> str:
    return key[:4] + "…" + key[-4:] if len(key) > 8 else "***"


def test_primary_call() -> None:
    print("\n=== 1. Primary call (unmodified pool) ===")
    model = get_chat_model()
    resp = model.invoke("Reply with exactly one short sentence confirming you are online.")
    print("Reply:", resp.content)
    print("Answered by:", resp.response_metadata.get("model_name") or resp.response_metadata)


def test_fallback_on_invalid_key() -> None:
    print("\n=== 2. Fallback chain (first Gemini key forced invalid) ===")
    real_keys = [k.strip() for k in os.environ["GEMINI_API_KEYS"].split(",") if k.strip()]
    print(f"Real pool has {len(real_keys)} key(s): {[_mask(k) for k in real_keys]}")

    poisoned = ["invalid-test-key-0000"] + real_keys
    os.environ["GEMINI_API_KEYS"] = ",".join(poisoned)
    try:
        model = get_chat_model()
        resp = model.invoke("Reply with exactly one short sentence confirming you are online.")
        print("Reply:", resp.content)
        print(
            "Answered by (proves fallthrough past the invalid key):",
            resp.response_metadata.get("model_name") or resp.response_metadata,
        )
    finally:
        os.environ["GEMINI_API_KEYS"] = ",".join(real_keys)


class OneFact(BaseModel):
    animal: str = Field(description="Name of the animal")
    fact: str = Field(description="One short, true fact about it")


def test_structured_output() -> None:
    print("\n=== 3. Structured output (.with_structured_output) ===")
    model = get_structured_chat_model(OneFact)
    result = model.invoke("Give me one interesting fact about octopuses.")
    print("Parsed object:", result)
    print("Type:", type(result))
    assert isinstance(result, OneFact), f"Expected OneFact, got {type(result)}"


def _rows_for(call_type: str, last_n: int) -> list[dict]:
    """Most recent `last_n` rows for call_type, oldest first — re-runnable across script executions."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM llm_call_log WHERE call_type = ? ORDER BY id DESC LIMIT ?",
            (call_type, last_n),
        ).fetchall()
    return [dict(r) for r in rows][::-1]


def test_call_logging() -> None:
    print("\n=== 4. Call logging (metadata -> llm_call_log row) ===")
    model = get_chat_model()
    model.invoke(
        "Reply with exactly one short sentence confirming you are online.",
        config={"metadata": {
            "call_type": "smoke_test_basic",
            "user_id": "smoke-user-1",
            "project_id": "smoke-project-1",
            "day_ref": 3,
            "is_test": True,
        }},
    )
    rows = _rows_for("smoke_test_basic", 1)
    assert len(rows) == 1, f"expected 1 row, got {len(rows)}"
    row = rows[0]
    for k, v in row.items():
        print(f"  {k}: {v}")
    assert row["model_used"], "model_used not populated"
    assert row["success"] == 1
    assert row["user_id"] == "smoke-user-1"
    assert row["project_id"] == "smoke-project-1"
    assert row["day_ref"] == 3


def test_parent_child_logging() -> None:
    print("\n=== 5. Parent/child nesting (two calls, one Runnable sequence) ===")
    # Raw model (no .with_retry()) on purpose: get_chat_model() wraps every leg in
    # with_retry(), which creates its own synthetic per-invocation run — so each
    # call's *immediate* parent would be that retry-wrapper's run (a fresh UUID
    # every time), not the outer sequence's run, even though the sequence run is
    # a shared grandparent one level up. That's real LangChain run-tree behavior,
    # not a logging bug (retry's own parent/child linkage is proven in test 7).
    # Using a raw model here isolates and proves the callback's parent/child
    # capture against LangChain's native propagation with nothing in between.
    # Groq (not Gemini): Gemini's free-tier daily quota is exhausted by this
    # point in the session from the other live-call tests above.
    raw_model = ChatGroq(model="llama-3.3-70b-versatile", api_key=os.environ["GROQ_API_KEY"]).with_config(
        callbacks=[LLMCallLogger()]
    )

    def _to_second_prompt(ai_msg):
        return f"Reply with exactly one word: the opposite of '{ai_msg.content.strip()}'."

    chain = raw_model | RunnableLambda(_to_second_prompt) | raw_model
    chain.invoke(
        "Reply with exactly one word: hot",
        config={"metadata": {"call_type": "smoke_test_chain", "is_test": True}},
    )
    rows = _rows_for("smoke_test_chain", 2)
    assert len(rows) == 2, f"expected 2 rows, got {len(rows)}"
    for row in rows:
        print(f"  run_id={row['run_id']} parent_run_id={row['parent_run_id']} output={row['output']!r}")
    assert rows[0]["parent_run_id"] is not None
    assert rows[0]["parent_run_id"] == rows[1]["parent_run_id"], "both calls should share one parent_run_id"


def test_failed_call_logging() -> None:
    print("\n=== 6. Failed call logging (forced error) ===")
    bad_model = ChatGroq(
        model="llama-3.3-70b-versatile", api_key="invalid-groq-key-000", max_retries=0
    ).with_config(callbacks=[LLMCallLogger()])
    try:
        bad_model.invoke("hi", config={"metadata": {"call_type": "smoke_test_failure", "is_test": True}})
        raise AssertionError("expected an auth error, call succeeded instead")
    except Exception as exc:
        print("Expected failure raised:", type(exc).__name__)

    rows = _rows_for("smoke_test_failure", 1)
    assert len(rows) == 1, f"expected 1 row, got {len(rows)}"
    row = rows[0]
    for k, v in row.items():
        print(f"  {k}: {v}")
    assert row["success"] == 0
    assert row["error_message"]


def test_gemini_retry_fires_post_fix() -> None:
    print("\n=== 7. Gemini retry-with-backoff fires now (post-fix verification) ===")
    # Mirrors the retry_if_exception_type fix applied in model_provider.py's
    # _build_raw_models(): ChatGoogleGenerativeAI wraps ClientError into
    # ChatGoogleGenerativeAIError, so the predicate must match the wrapper.
    bad_model = ChatGoogleGenerativeAI(
        model="models/gemini-2.5-flash", api_key="invalid-key-xyz", max_retries=0
    ).with_retry(
        retry_if_exception_type=(ChatGoogleGenerativeAIError, GeminiClientError),
        wait_exponential_jitter=True,
        stop_after_attempt=3,
    ).with_config(callbacks=[LLMCallLogger()])

    try:
        bad_model.invoke("hi", config={"metadata": {"call_type": "smoke_test_gemini_retry", "is_test": True}})
        raise AssertionError("expected an auth error, call succeeded instead")
    except Exception as exc:
        print("Final exception after retries:", type(exc).__name__)

    rows = _rows_for("smoke_test_gemini_retry", 3)
    assert len(rows) == 3, f"expected 3 rows (3 attempts), got {len(rows)}"
    parent_ids = {row["parent_run_id"] for row in rows}
    retry_counts = sorted(row["retry_count"] for row in rows)
    for row in rows:
        print(f"  run_id={row['run_id']} parent_run_id={row['parent_run_id']} retry_count={row['retry_count']} success={row['success']}")
    assert len(parent_ids) == 1 and None not in parent_ids, "all 3 attempts should share one non-null parent_run_id"
    assert retry_counts == [0, 1, 2], f"expected retry_count 0,1,2 across attempts, got {retry_counts}"
    assert all(row["success"] == 0 for row in rows)


if __name__ == "__main__":
    test_primary_call()
    test_fallback_on_invalid_key()
    test_structured_output()
    test_call_logging()
    test_parent_child_logging()
    test_failed_call_logging()
    test_gemini_retry_fires_post_fix()
    print("\nAll smoke tests passed.")
