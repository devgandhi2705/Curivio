"""
Chat-R7a smoke test — cross-user personalization context isolation.

Drives real production entry points end to end: real DB (data/curivio.db),
two real registered users, real activity written through the real write
paths (record_feedback/record_activity via feedback_service/session_memory_service),
real reads through memory_injection_service.inject_memory() — the exact
chain that leaked cross-user data before this fix.

Verifies:
  1. Two real users with distinct activity get back ONLY their own context
     for all four originally-leaking functions.
  2. A brand-new, never-used user_id (the exact case that surfaced the bug)
     returns a genuinely empty/neutral profile, not another user's data.
  3. The R7 open-ended baseline prompt no longer fabricates unrequested
     context (the M&A framing symptom) with a fresh user_id.
  4. Feed-side callers (recommendation_service, unscoped) still see the
     full global preference set — this fix must not have narrowed their
     view to nothing.

Run
---
  python scripts/smoke_test_personalization_isolation.py
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.auth_service import register_user
from backend.services.feedback_service import process_feedback
from backend.services.session_memory_service import record_activity
from backend.services.memory_injection_service import inject_memory
from backend.services import recommendation_service
from backend.utils.db import init_db


def _new_user(label: str) -> str:
    email = f"r7a-{label}-{uuid.uuid4().hex[:8]}@example.com"
    result = register_user(email, f"R7a {label}", "test-password-123")
    return result["user"]["user_id"]


def test_two_users_zero_cross_contamination() -> None:
    print("\n=== 1. Two real users, distinct activity, zero cross-contamination ===")
    alice = _new_user("alice")
    bob   = _new_user("bob")
    print(f"alice user_id={alice}")
    print(f"bob   user_id={bob}")

    process_feedback("Distributed Systems", "liked", alice)
    process_feedback("Distributed Systems", "liked", alice)
    record_activity("Distributed Systems", "deep_research", alice)
    record_activity("Kubernetes", "topic_expansion", alice)

    process_feedback("Watercolor Painting", "liked", bob)
    record_activity("Watercolor Painting", "deep_research", bob)
    record_activity("Oil Painting", "learning_path", bob)
    record_activity("Acrylics", "github_repos", bob)

    ctx_alice = inject_memory("sess-alice", user_id=alice)
    ctx_bob   = inject_memory("sess-bob", user_id=bob)

    print("alice preference_snapshot:", ctx_alice["preference_snapshot"])
    print("alice exploration_breadth:", ctx_alice["exploration_breadth"])
    print("alice user_profile:", ctx_alice["user_profile"])
    print("alice learner_profile.signals:", ctx_alice["learner_profile"]["signals"])
    print()
    print("bob preference_snapshot:", ctx_bob["preference_snapshot"])
    print("bob exploration_breadth:", ctx_bob["exploration_breadth"])
    print("bob user_profile:", ctx_bob["user_profile"])
    print("bob learner_profile.signals:", ctx_bob["learner_profile"]["signals"])

    assert "Distributed Systems" in ctx_alice["preference_snapshot"]["liked_topics"]
    assert "Watercolor Painting" not in ctx_alice["preference_snapshot"]["liked_topics"]
    assert "Distributed Systems" in ctx_alice["user_profile"]["top_interests"]
    assert "Watercolor Painting" not in ctx_alice["user_profile"]["top_interests"]
    assert ctx_alice["exploration_breadth"]["total_explored"] == 2
    assert "Kubernetes" in ctx_alice["exploration_breadth"]["all_topics"]
    assert "Watercolor Painting" not in ctx_alice["exploration_breadth"]["all_topics"]
    assert "Oil Painting" not in ctx_alice["exploration_breadth"]["all_topics"]

    assert "Watercolor Painting" in ctx_bob["preference_snapshot"]["liked_topics"]
    assert "Distributed Systems" not in ctx_bob["preference_snapshot"]["liked_topics"]
    assert ctx_bob["exploration_breadth"]["total_explored"] == 3
    assert "Kubernetes" not in ctx_bob["exploration_breadth"]["all_topics"]

    assert "Distributed Systems" in ctx_alice["learner_profile"]["topic_connections"]
    assert "Watercolor Painting" not in ctx_alice["learner_profile"]["topic_connections"]
    print("PASS: alice and bob each see only their own data across all four functions")


def test_fresh_user_id_returns_neutral() -> None:
    print("\n=== 2. Brand-new never-used user_id -> genuinely empty/neutral ===")
    fresh = _new_user("fresh")
    print(f"fresh user_id={fresh}")
    ctx = inject_memory("sess-fresh", user_id=fresh)
    print("preference_snapshot:", ctx["preference_snapshot"])
    print("exploration_breadth:", ctx["exploration_breadth"])
    print("user_profile:", ctx["user_profile"])
    assert ctx["preference_snapshot"]["liked_topics"] == []
    assert ctx["exploration_breadth"]["total_explored"] == 0
    assert ctx["user_profile"]["top_interests"] == []
    assert ctx["learner_profile"]["signals"]["exploration_breadth"] == 0
    print("PASS: fresh user gets an empty/neutral profile, not someone else's numbers")


def test_missing_user_id_returns_neutral() -> None:
    print("\n=== 2b. user_id=None (no other real caller exists) -> empty, never global fallback ===")
    ctx = inject_memory("sess-none", user_id=None)
    print("preference_snapshot:", ctx["preference_snapshot"])
    print("exploration_breadth:", ctx["exploration_breadth"])
    assert ctx["preference_snapshot"]["liked_topics"] == []
    assert ctx["exploration_breadth"]["total_explored"] == 0
    print("PASS: missing user_id never falls back to global data")


def test_baseline_prompt_no_fabricated_context() -> None:
    print("\n=== 3. R7 open-ended baseline re-run, fresh user -> no fabricated M&A framing ===")
    from backend.services import chat_service
    import json

    fresh = _new_user("baseline")
    msg = ("I keep bouncing between wanting to learn distributed systems and wanting "
           "to learn ML, and I am not sure how to think about which one to actually "
           "commit to right now.")
    events = []
    for line in chat_service.chat_stream("sess-baseline", msg, chat_mode="normal", user_id=fresh):
        events.append(json.loads(line))
    done = next((e for e in events if e["t"] == "done"), {})
    text = "".join(e["v"] for e in events if e["t"] == "chunk")
    print("context_used:", done.get("context_used"))
    print("--- answer (first 500 chars) ---")
    print(text[:500])
    assert done.get("context_used", {}).get("interests_count", 0) == 0
    assert done.get("context_used", {}).get("total_topics_explored", 0) == 0
    assert "M&A" not in text and "merger" not in text.lower() and "due diligence" not in text.lower()
    print("PASS: no fabricated business-context framing; context_used confirms zero leaked signal")


def test_feed_side_still_sees_global_data() -> None:
    print("\n=== 4. Feed-side callers (unscoped, out of this fix's scope) still see global data ===")
    # recommendation_service is called with no user_id from Feed's curator_service —
    # confirm that path is unaffected: it must still see every topic ever recorded,
    # including alice's and bob's from test 1, not just an empty/neutral result.
    interests = recommendation_service.get_top_user_interests(limit=100)
    topics = {i["topic"] for i in interests}
    print(f"Feed-side get_top_user_interests() sees {len(topics)} topics (unscoped, global)")
    assert "Distributed Systems" in topics, "Feed's unscoped read must still see all users' topics"
    assert "Watercolor Painting" in topics
    print("PASS: Feed's existing unscoped behavior is unchanged by this fix")


if __name__ == "__main__":
    init_db()
    test_two_users_zero_cross_contamination()
    test_fresh_user_id_returns_neutral()
    test_missing_user_id_returns_neutral()
    test_baseline_prompt_no_fabricated_context()
    test_feed_side_still_sees_global_data()
    print("\nAll Chat-R7a personalization isolation smoke tests passed.")
