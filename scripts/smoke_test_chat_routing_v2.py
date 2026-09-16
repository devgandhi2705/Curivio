"""Live smoke for chat routing v2 — real providers, real DB, is_test=True.

Ten turn types, then the log check the spec asks for: every chat/classifier/
explain row carries a route, and nothing called OpenRouter.

    python scripts/smoke_test_chat_routing_v2.py
"""
from __future__ import annotations

import io
import json
import sqlite3
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Windows' console defaults to the cp1252 codepage, which can't encode plain
# characters real model output uses (em dash, narrow no-break space, curly
# quotes) — reconfigure() falls back to '?' instead of crashing mid-turn.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from backend.services import chat_service, unpack_service
from backend.utils.db import DB_PATH, init_db

CARD = {
    "action": "ask_about",
    "insight_title": "Why Small Reasoning Models Beat Big Ones on Cost",
    "insight_summary": "A 150M-parameter reasoning model set a new cost-accuracy frontier on "
                       "ARC-AGI-1, which cuts against the assumption that capability tracks size.",
    "why_it_matters": "Recurrent latent reasoning lets a small model re-use its own intermediate "
                      "state, so it buys depth with time instead of parameters.",
    "blocks": [{"type": "mechanism", "content": "Latent recurrence trades parameter count for "
                                                "sequential compute at inference."}],
    "source_urls": ["https://paperswithcode.com/sota"],
    "source_links": [{"title": "Trending Papers", "url": "https://paperswithcode.com/sota"}],
    "project_name": "Model Efficiency", "domain": "ai", "content_type": "news",
}


def run_turn(label, message, *, chat_mode="normal", feed_context=None, attachments=None):
    session_id = f"smoke-{uuid.uuid4().hex[:8]}"
    kinds, text, sources, error = {}, [], [], None
    for line in chat_service.chat_stream(
        session_id, message, chat_mode=chat_mode, feed_context=feed_context,
        attachments=attachments, is_test=True, client_timezone="Asia/Kolkata",
    ):
        event = json.loads(line)
        kinds[event["t"]] = kinds.get(event["t"], 0) + 1
        if event["t"] == "chunk":
            text.append(event["v"])
        elif event["t"] == "done":
            sources = event.get("sources") or []
        elif event["t"] == "error":
            error = event["message"]
    answer = "".join(text)
    print(f"\n=== {label} ===")
    print("events:", kinds, "| sources:", len(sources), "| chars:", len(answer))
    print("answer:", answer[:220].replace("\n", " "))
    if error:
        print("ERROR:", error)
    return {"label": label, "session_id": session_id, "kinds": kinds,
            "answer": answer, "sources": sources, "error": error}


def main() -> None:
    init_db()
    results = []

    results.append(run_turn("1 plain", "What is attention in transformers?"))
    results.append(run_turn("2 automatic search", "What were the biggest AI releases this week?"))
    results.append(run_turn("3 search toggle", "How does retrieval-augmented generation work?",
                            chat_mode="web_search"))
    results.append(run_turn("4 explain-simply toggle", "Explain vector databases", chat_mode="layman"))
    results.append(run_turn("5 feed ask about", "Why does the small model win on cost?",
                            feed_context=dict(CARD)))
    results.append(run_turn("6 feed explain simply", "Explain this simply.",
                            feed_context={**CARD, "action": "explain_simply"}))
    results.append(run_turn("7 code execution",
                            "Compute the 30th Fibonacci number by running python code."))

    from PIL import Image, ImageDraw
    from backend.llm.model_provider import upload_attachment
    image = Image.new("RGB", (200, 200), color=(255, 255, 255))
    ImageDraw.Draw(image).rectangle([40, 40, 160, 160], fill=(220, 20, 60))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    upload = upload_attachment(buffer.getvalue(), "image/png", "square.png")
    results.append(run_turn("8 image", "What colour is the shape in this image?",
                            attachments=[upload]))

    results.append(run_turn("9 crisis", "than I will do suicide"))

    print("\n=== 10 explain popover ===")
    explain = [json.loads(line) for line in unpack_service.explain_stream(
        "latent recurrence", "smoke-user",
        sentence="Latent recurrence trades parameter count for sequential compute.")]
    print("events:", [e["t"] for e in explain])
    print("meaning:", (explain[-1].get("meaning_in_context") or "")[:160])

    # ── Log checks ────────────────────────────────────────────────────────
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT call_type, provider, route, route_step, success, error_type FROM llm_call_log "
        "WHERE is_test = 1 AND created_at >= datetime('now', '-30 minutes')").fetchall()
    routed = [r for r in rows if r["call_type"] in ("chat_turn", "chat_router_classify", "explain")]
    missing_route = [dict(r) for r in routed if not r["route"]]
    openrouter = [dict(r) for r in rows if r["provider"] == "openrouter"]
    failures = [dict(r) for r in rows if not r["success"]]

    print("\n=== log ===")
    print(f"rows: {len(rows)} | routed: {len(routed)} | missing route: {len(missing_route)} "
          f"| openrouter: {len(openrouter)} | failed calls: {len(failures)}")
    for row in routed[:12]:
        print(f"  {row['call_type']:<22} {row['provider']:<10} step {row['route_step']} :: {row['route']}")
    for row in failures:
        print("  FAILED:", row["call_type"], row["error_type"], row["route"])

    problems = [r for r in results if r["error"] or not r["answer"].strip()]
    print("\n=== verdict ===")
    print("turns without an answer:", [p["label"] for p in problems] or "none")
    assert not missing_route, f"rows without a route: {missing_route}"
    assert not openrouter, f"OpenRouter was called: {openrouter}"
    assert not problems, "some turns produced no answer"
    print("PASS")


if __name__ == "__main__":
    main()
