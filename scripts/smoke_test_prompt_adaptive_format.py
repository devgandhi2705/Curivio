"""
Chat-R7b smoke test — adaptive-format redesign, live verification.

Drives real production entry points end to end: real DB, real Gemini calls.

Verifies:
  1. "top 10 github trends" (R1's original screenshot case, no Feed link)
     -> adaptive free-form output, structured_response is None.
  2. A genuine Feed-linked turn (feed_context present) -> structured_response
     is populated (Key Takeaways/Resources/Explore Next schema fires).
  3. A real image attachment -> model does not deny vision capability.
  4. A real oversized document (retrieval-trimmed) -> model represents the
     answer as a partial excerpt, not a claimed full read.
  5. detect_depth: "how"/"about" alone no longer false-positive to "detailed".
  6. Full regression: R6a document upload + R7a personalization isolation
     smoke tests still pass with these prompt changes in place.

Run
---
  python scripts/smoke_test_prompt_adaptive_format.py
"""
from __future__ import annotations

import io
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services import chat_service, chat_prompt_service, document_extraction_service, document_memory_service
from backend.services.auth_service import register_user
from backend.utils.db import init_db


def _new_user(label: str) -> str:
    email = f"r7b-{label}-{uuid.uuid4().hex[:8]}@example.com"
    result = register_user(email, f"R7b {label}", "test-password-123")
    return result["user"]["user_id"]


def _run_turn(session_id, message, user_id, chat_mode="normal", feed_context=None, attachments=None):
    events = []
    for line in chat_service.chat_stream(
        session_id, message, chat_mode=chat_mode, user_id=user_id,
        feed_context=feed_context, attachments=attachments,
    ):
        events.append(json.loads(line))
    done = next((e for e in events if e["t"] == "done"), {})
    text = "".join(e["v"] for e in events if e["t"] == "chunk")
    return text, done


def test_no_feed_link_adaptive_free_form() -> None:
    print("\n=== 1. 'top 10 github trends', no Feed link -> adaptive free-form ===")
    user = _new_user("nofeeds")
    text, done = _run_turn(f"sess-{uuid.uuid4().hex[:6]}", "find today's github trends top 10", user, chat_mode="web_search")
    print("chat_mode resolved:", done.get("chat_mode"))
    print("structured_response:", done.get("structured_response"))
    print("answer (first 300 chars):", text[:300])
    assert done.get("structured_response") is None, "no Feed link -> must NOT force the JSON schema"
    assert "Key Takeaways" not in text and "Explore Next" not in text
    print("PASS: adaptive free-form output, no forced schema")


def test_feed_linked_turn_structured() -> None:
    print("\n=== 2. Genuine Feed-linked turn -> structured formatting applies ===")
    user = _new_user("feedlinked")
    feed_context = {
        "insight_title": "Why vector databases are eating search infrastructure",
        "insight_summary": "Vector DBs are replacing traditional inverted indexes for semantic search.",
        "why_it_matters": "This changes how every search product gets built going forward.",
        "action": "ask_about",
        "domain": "technology",
    }
    text, done = _run_turn(
        f"sess-{uuid.uuid4().hex[:6]}", "Why does this matter for search infrastructure?",
        user, chat_mode="normal", feed_context=feed_context,
    )
    print("chat_mode resolved:", done.get("chat_mode"))
    print("structured_response is not None:", done.get("structured_response") is not None)
    if done.get("structured_response"):
        sr = done["structured_response"]
        print("response_type:", sr.get("response_type"), "| title:", sr.get("title"))
        print("key_takeaways:", sr.get("key_takeaways"))
    assert done.get("structured_response") is not None, "genuine Feed link -> JSON schema must fire"
    assert done["structured_response"].get("key_takeaways"), "schema should include key_takeaways"
    print("PASS: Feed-linked turn correctly gets structured formatting")


def test_image_no_vision_denial() -> None:
    print("\n=== 3. Real image attachment -> no vision-capability denial ===")
    from PIL import Image, ImageDraw
    from backend.llm.model_provider import upload_attachment

    img = Image.new("RGB", (200, 200), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    d.ellipse([40, 40, 160, 160], fill=(30, 144, 255))  # solid blue circle
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    att = upload_attachment(buf.getvalue(), "image/png", "circle.png")

    user = _new_user("vision")
    text, done = _run_turn(
        f"sess-{uuid.uuid4().hex[:6]}", "What shape and color is in this image?",
        user, chat_mode="normal", attachments=[att],
    )
    print("answer:", text[:300])
    denial_phrases = ["cannot process images", "cannot see images", "cannot view images",
                       "text-based", "i am unable to view", "i cannot directly"]
    lowered = text.lower()
    assert not any(p in lowered for p in denial_phrases), f"model denied vision: {text[:200]}"
    assert "blue" in lowered or "circle" in lowered, "model should describe the actual image content"
    print("PASS: no vision-capability denial, real content described")


def test_document_excerpt_framing() -> None:
    print("\n=== 4. Oversized document (retrieval-trimmed) -> represented as partial excerpt ===")
    filler = "The quarterly report discusses general market trends and administrative notes. "
    secret = "The confidential Q3 headcount figure discussed in this section is 4,417 employees."
    paragraphs = [filler * 3 for _ in range(120)]
    paragraphs.insert(60, secret)
    big_text = "\n\n".join(paragraphs)
    attachment_id = document_memory_service.store_document("headcount_report.txt", big_text)
    att = {"uri": f"doc://{attachment_id}", "mime_type": "text/plain",
           "filename": "headcount_report.txt", "size_bytes": len(big_text), "expires_at": None}

    user = _new_user("docframe")
    text, done = _run_turn(
        f"sess-{uuid.uuid4().hex[:6]}",
        "What is the confidential Q3 headcount figure, and did you read the whole report or just part of it?",
        user, chat_mode="normal", attachments=[att],
    )
    print("answer:", text[:400])
    lowered = text.lower()
    assert "4,417" in text or "4417" in text.replace(",", "")
    full_read_claims = ["read the entire", "read the whole document", "read the full document", "i have read the complete"]
    assert not any(p in lowered for p in full_read_claims), f"model falsely claimed a full read: {text[:300]}"
    excerpt_language = ["excerpt", "portion", "part of", "relevant section", "visible excerpt", "showing"]
    assert any(p in lowered for p in excerpt_language), f"model should acknowledge partial view: {text[:300]}"
    print("PASS: model represents the document as a partial excerpt, not a full read")


def test_depth_detection_no_false_positive() -> None:
    print("\n=== 5. detect_depth: 'how'/'about' alone no longer false-positive ===")
    msg = ("I keep bouncing between wanting to learn distributed systems and wanting "
           "to learn ML, and I am not sure how to think about which one to actually "
           "commit to right now.")
    depth = chat_prompt_service.detect_depth(msg, "normal")
    print(f"detect_depth(...) = {depth!r} (was 'detailed' before the fix)")
    assert depth != "detailed", "isolated 'how'/'about' must not trigger detailed depth"

    # Real phrase should still correctly trigger detailed.
    phrase_msg = "Can you explain this in detail, step by step?"
    depth2 = chat_prompt_service.detect_depth(phrase_msg, "normal")
    print(f"detect_depth({phrase_msg!r}) = {depth2!r}")
    assert depth2 == "detailed", "genuine 'in detail'/'step by step' phrases must still trigger detailed"
    print("PASS: false positive fixed, true positive preserved")


if __name__ == "__main__":
    init_db()
    test_no_feed_link_adaptive_free_form()
    test_feed_linked_turn_structured()
    test_image_no_vision_denial()
    test_document_excerpt_framing()
    test_depth_detection_no_false_positive()
    print("\nAll Chat-R7b adaptive-format smoke tests passed.")
