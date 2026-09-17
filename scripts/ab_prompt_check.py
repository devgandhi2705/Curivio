"""Side-by-side prompt check: does the trimmed prompt answer at least as well?

Takes real logged turns, rebuilds each one's prompt with the NEW builder, and
answers both the old and the new prompt — twice each, per spec 4.4: once on
Groq gpt-oss-120b, once on Gemini flash-lite. Output is one markdown file to
read.

What is compared: persona, principles, directives, the Feed note, the search
note and the format rules — everything this refactor touched. The dynamic
memory blocks are copied from the old prompt into the new one verbatim, so the
two differ only by the parts that changed.

Cost: $0 (Groq free tier, Gemini free tier). No writes: it reads llm_call_log
and never calls chat_service. Models are built through
backend.llm.model_provider.build_leg() (the same routing layer chat uses),
not a hand-rolled provider client (CLAUDE.md's "never hand-roll a new
provider client" rule) — both legs come from the "simple" route's real list
in chat_models.toml (step 1 = groq/openai/gpt-oss-120b, step 2 =
gemini/gemini-3.1-flash-lite).

Gemini's free tier is 20 requests/day per key per model, and a --limit 12 run
makes 24 Gemini calls (12 turns x old+new) — spread round-robin across every
configured Gemini key via key_index so no single key gets close to the
ceiling. If every key still runs out mid-run, the remaining Gemini answers
are recorded as "(quota exhausted)" and the run keeps going (Groq answers are
unaffected) — the report says so at the top when that happened.

    python scripts/ab_prompt_check.py --limit 12 --out docs/superpowers/plans/ab-prompt-check.md
"""
from __future__ import annotations

import argparse
import itertools
import re
import sqlite3
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
load_dotenv(dotenv_path=REPO / ".env")

from backend.llm.model_provider import LegSpec, _keys_for_provider, build_leg, extract_text  # noqa: E402
from backend.llm.rate_limits import classify_error  # noqa: E402

_GROQ_MODEL   = "openai/gpt-oss-120b"
_GEMINI_MODEL = "gemini-3.1-flash-lite"
_gemini_key_cycle = itertools.cycle(range(len(_keys_for_provider("gemini"))))
_gemini_exhausted = False

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


def _answer_with_leg(spec: LegSpec, messages: list[dict]) -> str:
    """Build the leg through the shared routing layer and answer once, with a
    small retry on a rate-limit-shaped OR transient (e.g. a provider's real,
    unrelated 503) error. Fixed 15s backoff (not the error's own retry-after)
    x 3 tries — good enough for a manual report script; a real service would
    parse retry-after (chat's does, via rate_limits)."""
    model = build_leg(spec, temperature=0.7)
    payload = [m for m in messages if m["role"] != "tool"]
    for attempt in range(3):
        try:
            # extract_text, not str(...content): Gemini 3+ legs return a list of
            # content parts (text + a base64 thought signature), not a plain
            # string — str() on that list dumps the whole repr, signature included.
            return extract_text(model.invoke(payload))
        except Exception as exc:
            if classify_error(exc) in ("rate_limit", "daily_quota", "transient") and attempt < 2:
                time.sleep(15)
                continue
            raise


def _groq_answer(messages: list[dict]) -> str:
    """A 12-turn x 2-prompt run makes 24 calls each way — a real (if rare)
    provider hiccup must not crash the whole report and lose every answer
    already produced, so a persistent failure degrades to a visible marker
    instead of propagating."""
    spec = LegSpec("simple", 1, "groq", _GROQ_MODEL, 0)
    try:
        return _answer_with_leg(spec, messages)
    except Exception as exc:
        print(f"  Groq call failed: {exc}")
        return f"(error: {exc})"


def _gemini_answer(messages: list[dict]) -> str:
    """Round-robins the configured Gemini keys across calls (free tier is 20
    requests/day per key per model) and degrades to a marker once every key
    has shown a rate-limit/quota error, so the rest of the run (Groq answers
    included) still completes instead of crashing partway through. Any other
    persistent failure (e.g. a real provider outage) degrades the same way
    rather than crashing the report."""
    global _gemini_exhausted
    if _gemini_exhausted:
        return "(quota exhausted)"
    key_index = next(_gemini_key_cycle)
    spec = LegSpec("simple", 2, "gemini", _GEMINI_MODEL, key_index)
    try:
        return _answer_with_leg(spec, messages)
    except Exception as exc:
        if classify_error(exc) in ("rate_limit", "daily_quota"):
            _gemini_exhausted = True
            print(f"  Gemini quota exhausted (key #{key_index}): {exc}")
            return "(quota exhausted)"
        print(f"  Gemini call failed (key #{key_index}): {exc}")
        return f"(error: {exc})"


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
              "the changed parts differ. Each turn answers on both models the \"simple\" route "
              f"actually uses: groq/{_GROQ_MODEL} (step 1) and gemini/{_GEMINI_MODEL} (step 2, "
              "key rotated per call).", ""]
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
                   f"### Old answer ({_GROQ_MODEL})", "", _groq_answer(old_messages), "",
                   f"### New answer ({_GROQ_MODEL})", "", _groq_answer(new_messages), "",
                   f"### Old answer ({_GEMINI_MODEL})", "", _gemini_answer(old_messages), "",
                   f"### New answer ({_GEMINI_MODEL})", "", _gemini_answer(new_messages), "",
                   "---", ""]
        print(f"[{kept}/{args.limit}] {label}: {old_chars} -> {new_chars}")
        # Saved after every turn, not just at the end: 24 real network calls
        # over several minutes is long enough for a real (rare) crash, and a
        # partial report beats losing every answer produced so far.
        Path(args.out).write_text("\n".join(report), encoding="utf-8")

    if _gemini_exhausted:
        report.insert(2, "**Note:** Gemini's free-tier quota ran out partway through this run — "
                         "answers marked \"(quota exhausted)\" below were not produced. Every Groq "
                         "answer is unaffected.\n")

    Path(args.out).write_text("\n".join(report), encoding="utf-8")
    print("wrote", args.out)


if __name__ == "__main__":
    main()
