"""Side-by-side prompt check: does the trimmed prompt answer at least as well?

Takes real logged turns, rebuilds each one's prompt with the NEW builder, and
answers both the old and the new prompt with the same free model. Output is one
markdown file to read.

What is compared: persona, principles, directives, the Feed note, the search
note and the format rules — everything this refactor touched. The dynamic
memory blocks are copied from the old prompt into the new one verbatim, so the
two differ only by the parts that changed.

Cost: $0 (Groq free tier). No writes: it reads llm_call_log and never calls
chat_service.

    python scripts/ab_prompt_check.py --limit 12 --out docs/superpowers/plans/ab-prompt-check.md
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
load_dotenv(dotenv_path=REPO / ".env")

_ROLE_RE = re.compile(r"(?m)^(system|human|ai|tool): ")
_SOURCE_RE = re.compile(r"^\s+\[(\d+)\]\s*⚑?\s*(.*?)\n\s+(.*?)\n\s+Source: (\S+)", re.M)
_MEMORY_HEADS = ("This conversation:", "Related past discussion", "What you know about this user:")


def _messages_from_log(text: str) -> list[dict]:
    parts = _ROLE_RE.split(text)
    roles = {"human": "user", "ai": "assistant"}
    return [{"role": roles.get(role, role), "content": body.strip("\n")}
            for role, body in zip(parts[1::2], parts[2::2])]


def _card_from_note(note: str) -> dict:
    """Rebuild the feed_context dict from the old [FEED INSIGHT ...] note."""
    def _field(label):
        match = re.search(rf"^{label}: (.*)$", note, re.M)
        return match.group(1).strip() if match else ""

    blocks = [{"type": block_type, "content": content}
              for block_type, content in re.findall(r"^  \[(\w+)\] (.*)$", note, re.M)]
    urls, links, contents = [], [], {}
    for line in note.splitlines():
        source = re.match(r"^  • (?:(.*?): )?(https?://\S+)$", line)
        if source:
            title, url = source.group(1) or "", source.group(2)
            urls.append(url)
            links.append({"title": title, "url": url})
    for url, body in re.findall(r"^  • .*?(https?://\S+)\n    Extracted text: (.*?)(?=\n  •|\n\n|\Z)",
                                note, re.M | re.S):
        contents[url] = body
    return {
        "action": "explain_simply" if "Simple Explanation" in note.splitlines()[0] else "ask_about",
        "insight_title": _field("Card"), "insight_summary": _field("Summary"),
        "why_it_matters": _field("Why it matters"),
        "educational_explanation": _field("Educational explanation"),
        "blocks": blocks, "source_urls": urls, "source_links": links,
        "source_contents": contents, "project_name": "", "domain": "default",
    }


def _case_from_messages(messages: list[dict]) -> dict:
    systems = [m["content"] for m in messages if m["role"] == "system"]
    tools = [m["content"] for m in messages if m["role"] == "tool"]
    feed_note = next((s for s in systems if s.startswith("[FEED INSIGHT")), "")
    search_note = next((s for s in systems + tools if "WEB SEARCH" in s[:60]), "")
    memory = "\n\n".join(block for s in systems for block in s.split("\n\n")
                         if block.startswith(_MEMORY_HEADS))
    name = re.search(r"^The user's name is (.*)\.$", systems[0] if systems else "", re.M)
    articles = [{"title": title, "content": content, "url": url}
                for _, title, content, url in _SOURCE_RE.findall(search_note)]
    return {
        "message": next((m["content"] for m in reversed(messages) if m["role"] == "user"), ""),
        "history": [m for m in messages if m["role"] in ("user", "assistant")][:-1],
        "user_name": name.group(1) if name else "",
        "feed_context": _card_from_note(feed_note) if feed_note else None,
        "articles": articles,
        "memory": memory,
        "simple_tone": "MECHANISM-PRESERVING SIMPLIFICATION" in (systems[0] if systems else "")
                       or "ACTIVE RESPONSE MODE" in (systems[0] if systems else ""),
        "old_messages": messages,
    }


def _new_messages(case: dict) -> list[dict]:
    from backend.services.chat_modes_service import build_feed_context_note, format_reasoning_search_note
    from backend.services.chat_prompt_service import build_messages

    context = {"user_name": case["user_name"], "vector_memory": case["memory"]}
    messages = build_messages(case["history"], case["message"], context,
                              simple_tone=case["simple_tone"])
    notes = []
    if case["feed_context"]:
        notes.append(build_feed_context_note(case["feed_context"]))
    if case["articles"]:
        half = len(case["articles"]) // 2 or len(case["articles"])
        notes.append(format_reasoning_search_note({
            "primary_query": "", "contradiction_query": "",
            "supporting": case["articles"][:half], "complicating": case["articles"][half:],
            "has_complicating": len(case["articles"]) > half,
        }))
    for note in notes:
        messages.insert(len(messages) - 1, {"role": "system", "content": note})
    return messages


def _answer(messages: list[dict]) -> str:
    from groq import RateLimitError
    from langchain_groq import ChatGroq
    key = (os.getenv("GROQ_API_KEYS") or os.getenv("GROQ_API_KEY")).split(",")[0].strip()
    model = ChatGroq(model="openai/gpt-oss-120b", api_key=key, temperature=0.7,
                     max_retries=0, max_tokens=1200)
    payload = [m for m in messages if m["role"] != "tool"]
    # ponytail: free tier is 8000 TPM: a 12-turn x 2-call run can trip it mid-run.
    # Fixed 15s backoff (not the error's own retry-after) x 3 tries — good enough
    # for a manual report script; a real service would parse retry-after.
    for attempt in range(3):
        try:
            return str(model.invoke(payload).content)
        except RateLimitError:
            if attempt == 2:
                raise
            time.sleep(15)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--db", default=str(REPO / "data" / "curivio.db"))
    parser.add_argument("--out", default=str(REPO / "docs/superpowers/plans/ab-prompt-check.md"))
    args = parser.parse_args()

    rows = sqlite3.connect(args.db).execute(
        "SELECT input FROM llm_call_log WHERE call_type='chat_turn' AND is_test=0 "
        "AND user_id IS NOT NULL AND success=1 AND length(input) > 800 "
        "ORDER BY id DESC LIMIT ?", (args.limit * 3,)).fetchall()

    report = ["# Prompt side-by-side check", "",
              "Old = the prompt exactly as it was sent in that real turn. New = the same turn "
              "rebuilt by the new builder, with the dynamic memory blocks copied across so only "
              "the changed parts differ. Same model for both: groq/openai/gpt-oss-120b.", ""]
    seen: set[str] = set()
    kept = 0
    for (text,) in rows:
        if kept >= args.limit:
            break
        case = _case_from_messages(_messages_from_log(text))
        if not case["message"] or case["message"] in seen:
            continue
        seen.add(case["message"])
        kept += 1

        old_messages, new_messages = case["old_messages"], _new_messages(case)
        old_chars = sum(len(m["content"]) for m in old_messages if m["role"] == "system")
        new_chars = sum(len(m["content"]) for m in new_messages if m["role"] == "system")
        label = ("Feed " + case["feed_context"]["action"] if case["feed_context"]
                 else "web search" if case["articles"] else "simple tone" if case["simple_tone"] else "plain")
        report += [f"## {kept}. {label} — {case['message'][:80]!r}", "",
                   f"System prompt: **{old_chars} -> {new_chars} chars** "
                   f"({(new_chars - old_chars) / max(old_chars, 1):+.0%})", "",
                   "### Old answer", "", _answer(old_messages), "",
                   "### New answer", "", _answer(new_messages), "", "---", ""]
        print(f"[{kept}/{args.limit}] {label}: {old_chars} -> {new_chars}")

    Path(args.out).write_text("\n".join(report), encoding="utf-8")
    print("wrote", args.out)


if __name__ == "__main__":
    main()
