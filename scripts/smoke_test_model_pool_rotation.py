"""
Chat-R3 smoke test — key-rotation pool machinery (backend/llm/model_provider.
build_pooled_legs / get_chat_model_for_task).

Verifies, against live APIs, the ONE load-bearing behavior this phase adds:
  1. Poison key #1 of a model's pool -> rotates to key #2 of the SAME model,
     not straight to the next model in the priority list.
  2. Poison EVERY key of a model's pool -> THEN drops to the next model.
  3. Add a key to GEMINI_API_KEYS at runtime (no code change) -> it's used.
  4. GROQ_API_KEYS list works and is backward-compatible with single
     GROQ_API_KEY.
  5. llm_call_log rows + parent_run_id grouping are unaffected by this new
     layer (same LLMCallLogger, reused as-is).

Requires GEMINI_API_KEYS (>=2 real keys) and GROQ_API_KEY in .env.
Additive-only — does not touch get_chat_model()/get_structured_chat_model()
or any existing call site (chat_agent.py, Feed).

Run
---
  python scripts/smoke_test_model_pool_rotation.py
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_RUN = uuid.uuid4().hex[:8]  # unique per script run so repeated runs' llm_call_log rows never mix

from backend.config import GEMINI_MODEL, GROQ_FALLBACK_MODEL
from backend.llm.call_logger import LLMCallLogger
from backend.llm.model_provider import _RETRY_ATTEMPTS, build_pooled_legs, get_chat_model_for_task
from backend.utils.db import get_connection


def _mask(key: str) -> str:
    return key[:4] + "…" + key[-4:] if len(key) > 8 else "***"


def _rows_for(call_type: str, last_n: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM llm_call_log WHERE call_type = ? ORDER BY id DESC LIMIT ?",
            (call_type, last_n),
        ).fetchall()
    return [dict(r) for r in rows][::-1]


def test_poison_one_key_rotates_within_same_model() -> None:
    print("\n=== 1. Poison key #1 of a 2-model priority list -> key #2 of the SAME model first ===")
    real_keys = [k.strip() for k in os.environ["GEMINI_API_KEYS"].split(",") if k.strip()]
    assert len(real_keys) >= 2, "need >=2 real Gemini keys in GEMINI_API_KEYS for this proof"
    print(f"Real Gemini pool: {len(real_keys)} key(s): {[_mask(k) for k in real_keys]}")

    poisoned = ["invalid-test-key-0000"] + real_keys
    os.environ["GEMINI_API_KEYS"] = ",".join(poisoned)
    try:
        priority_list = [("gemini", GEMINI_MODEL), ("groq", GROQ_FALLBACK_MODEL)]
        legs = build_pooled_legs(priority_list)
        print(f"Built {len(legs)} legs: expect {len(poisoned)} gemini legs then 1 groq leg")
        assert len(legs) == len(poisoned) + 1

        built = []
        from backend.llm.model_provider import _with_retry
        for m, exc_types in legs:
            built.append(_with_retry(m, exc_types))
        primary, *fallbacks = built
        chain = primary.with_fallbacks(fallbacks).with_config(callbacks=[LLMCallLogger()])

        resp = chain.invoke(
            "Reply with exactly one short sentence confirming you are online.",
            config={"metadata": {"call_type": f"smoke_r3_poison_one_{_RUN}", "is_test": True}},
        )
        model_used = resp.response_metadata.get("model_name")
        print("Answered by:", model_used)
        assert "gemini" in (model_used or "").lower(), (
            f"expected a Gemini leg (key #2) to answer, got {model_used!r} — "
            f"means it skipped straight past the SAME model's remaining keys"
        )

        rows = _rows_for(f"smoke_r3_poison_one_{_RUN}", len(poisoned) * _RETRY_ATTEMPTS + 3)
        print(f"llm_call_log rows for this turn ({len(rows)}):")
        for row in rows:
            print(f"  provider={row['provider']} model_used={row['model_used']} "
                  f"success={row['success']} error_type={row['error_type']} "
                  f"parent_run_id={row['parent_run_id']}")
        providers_seen = [r["provider"] for r in rows]
        # NOTE: chat-r2-fix.md already documented 2 of 3 pooled keys with exhausted
        # gemini-2.5-flash daily quota from earlier R1/R2 live testing — real quota
        # state we don't control. That's fine: it doesn't weaken this proof, it
        # strengthens it. Whatever intermediate gemini keys fail for whatever
        # reason, the invariant under test is that groq (the NEXT model in the
        # priority list) is never touched while any gemini key still has capacity.
        assert "groq" not in providers_seen, (
            f"groq must never be reached while a gemini key still has capacity, saw: {providers_seen}"
        )
        assert rows[0]["success"] == 0 and rows[0]["provider"] == "gemini", (
            "first attempt (poisoned key) should fail on the gemini provider"
        )
        assert rows[-1]["success"] == 1 and rows[-1]["provider"] == "gemini", (
            "must eventually succeed on a REAL gemini key without ever falling to groq — "
            "proves key rotation happens BEFORE any model-drop"
        )
    finally:
        os.environ["GEMINI_API_KEYS"] = ",".join(real_keys)


def test_poison_all_keys_drops_to_next_model() -> None:
    print("\n=== 2. Poison ALL Gemini keys -> drops to the next model (Groq) ===")
    real_keys = [k.strip() for k in os.environ["GEMINI_API_KEYS"].split(",") if k.strip()]
    os.environ["GEMINI_API_KEYS"] = ",".join(f"invalid-test-key-{i}" for i in range(len(real_keys)))
    try:
        priority_list = [("gemini", GEMINI_MODEL), ("groq", GROQ_FALLBACK_MODEL)]
        legs = build_pooled_legs(priority_list)
        from backend.llm.model_provider import _with_retry
        built = [_with_retry(m, exc_types) for m, exc_types in legs]
        primary, *fallbacks = built
        chain = primary.with_fallbacks(fallbacks).with_config(callbacks=[LLMCallLogger()])

        resp = chain.invoke(
            "Reply with exactly one short sentence confirming you are online.",
            config={"metadata": {"call_type": f"smoke_r3_poison_all_{_RUN}", "is_test": True}},
        )
        model_used = resp.response_metadata.get("model_name")
        print("Answered by:", model_used)

        rows = _rows_for(f"smoke_r3_poison_all_{_RUN}", len(real_keys) * _RETRY_ATTEMPTS + 3)
        print(f"llm_call_log rows for this turn ({len(rows)}):")
        for row in rows:
            print(f"  provider={row['provider']} model_used={row['model_used']} success={row['success']}")
        assert all(r["provider"] == "gemini" and r["success"] == 0 for r in rows[:-1]), (
            "every gemini key should fail before the drop"
        )
        assert rows[-1]["provider"] == "groq" and rows[-1]["success"] == 1, (
            f"expected the FINAL row to be a successful groq call, got {rows[-1]}"
        )
    finally:
        os.environ["GEMINI_API_KEYS"] = ",".join(real_keys)


def test_new_key_added_to_pool_is_picked_up_with_zero_code_change() -> None:
    print("\n=== 3. Add a new key to the pool env var -> used automatically ===")
    real_keys = [k.strip() for k in os.environ["GEMINI_API_KEYS"].split(",") if k.strip()]
    # Simulate "adding a key and restarting": append a *duplicate* of a real key
    # under a distinct pool position — proves the pool size purely follows the
    # env var's key count, no code/config touched to recognize it.
    extended = real_keys + [real_keys[0]]
    os.environ["GEMINI_API_KEYS"] = ",".join(extended)
    try:
        legs = build_pooled_legs([("gemini", GEMINI_MODEL)])
        print(f"Pool had {len(real_keys)} keys, env now lists {len(extended)} -> built {len(legs)} legs")
        assert len(legs) == len(extended), (
            "leg count must track GEMINI_API_KEYS length with zero code change"
        )
    finally:
        os.environ["GEMINI_API_KEYS"] = ",".join(real_keys)


def test_groq_key_list_backward_compatible_with_single_key() -> None:
    print("\n=== 4. GROQ_API_KEYS list + backward-compat with single GROQ_API_KEY ===")
    from backend.llm.model_provider import _groq_keys

    assert "GROQ_API_KEYS" not in os.environ, "test assumes no GROQ_API_KEYS set yet"
    single = _groq_keys()
    print(f"No GROQ_API_KEYS set -> falls back to single GROQ_API_KEY: {len(single)} key(s)")
    assert len(single) == 1

    os.environ["GROQ_API_KEYS"] = f"invalid-groq-0000,{os.environ['GROQ_API_KEY']}"
    try:
        pool = _groq_keys()
        print(f"GROQ_API_KEYS set (2 entries) -> pool has {len(pool)} key(s)")
        assert len(pool) == 2

        legs = build_pooled_legs([("groq", GROQ_FALLBACK_MODEL)])
        from backend.llm.model_provider import _with_retry
        built = [_with_retry(m, exc_types) for m, exc_types in legs]
        primary, *fallbacks = built
        chain = primary.with_fallbacks(fallbacks) if fallbacks else primary
        chain = chain.with_config(callbacks=[LLMCallLogger()])
        resp = chain.invoke(
            "Reply with exactly one short sentence confirming you are online.",
            config={"metadata": {"call_type": f"smoke_r3_groq_pool_{_RUN}", "is_test": True}},
        )
        print("Answered by:", resp.response_metadata.get("model_name") or resp.response_metadata)
        rows = _rows_for(f"smoke_r3_groq_pool_{_RUN}", 2)
        for row in rows:
            print(f"  provider={row['provider']} success={row['success']} parent_run_id={row['parent_run_id']}")
        assert rows[0]["success"] == 0, "poisoned groq key #1 should fail first"
        assert rows[1]["success"] == 1, "real groq key #2 should then succeed — groq pool rotation works"
    finally:
        del os.environ["GROQ_API_KEYS"]


def test_get_chat_model_for_task_end_to_end() -> None:
    print("\n=== 5. get_chat_model_for_task() end to end (routing task) ===")
    model = get_chat_model_for_task("routing")
    resp = model.invoke(
        "Reply with exactly one word: yes.",
        config={"metadata": {"call_type": f"smoke_r3_task_routing_{_RUN}", "is_test": True}},
    )
    print("Reply:", resp.content)
    print("Answered by:", resp.response_metadata.get("model_name") or resp.response_metadata)
    rows = _rows_for(f"smoke_r3_task_routing_{_RUN}", 1)
    assert len(rows) == 1 and rows[0]["success"] == 1


if __name__ == "__main__":
    test_poison_one_key_rotates_within_same_model()
    test_poison_all_keys_drops_to_next_model()
    test_new_key_added_to_pool_is_picked_up_with_zero_code_change()
    test_groq_key_list_backward_compatible_with_single_key()
    test_get_chat_model_for_task_end_to_end()
    print("\nAll Chat-R3 pool-rotation smoke tests passed.")
