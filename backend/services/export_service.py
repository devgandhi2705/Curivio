"""
Package export to Markdown — pure templating, zero LLM calls.

Public API
----------
insight_to_markdown(project_id, insight_id) -> str
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone


def _fmt_date(ts: str) -> str:
    """ISO timestamp → 'Month D, YYYY'."""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return f"{dt.strftime('%B')} {dt.day}, {dt.year}"
    except Exception:
        return ts[:10] if ts else ""


_TYPE_EMOJI = {"news": "📰", "educational": "📚", "curiosity": "💡"}


def _card_to_md(card: dict) -> list[str]:
    lines: list[str] = []
    emoji = _TYPE_EMOJI.get(card.get("content_type", ""), "📄")
    lines += ["---", "", f"## {emoji} {card.get('title', '')} ", ""]

    if card.get("category"):
        lines += [f"*{card['category']}*", ""]

    if card.get("summary"):
        lines += [card["summary"], ""]

    edu = card.get("educational_explanation", "")
    if edu:
        label = "Deep Dive" if card.get("content_type") == "educational" else "Why This Works"
        lines += [f"### {label}", "", edu, ""]

    why = card.get("why_it_matters", "")
    if why:
        lines += ["### Why It Matters", "", why, ""]

    sources = card.get("source_links") or []
    if sources:
        lines += ["### Sources", ""]
        for link in sources:
            if isinstance(link, dict):
                url   = link.get("url", "")
                title = link.get("title") or "Source"
            else:
                url, title = str(link), "Source"
            if url:
                lines.append(f"- [{title}]({url})")
        lines.append("")

    return lines


def insight_to_markdown(project_id: str, insight_id: int) -> str:
    from ..utils.db import get_connection

    with get_connection() as conn:
        row = conn.execute(
            """SELECT pi.insight_json, pi.day_number, pi.generated_at, lp.name AS project_name
               FROM   project_insights pi
               LEFT JOIN learning_projects lp ON lp.project_id = pi.project_id
               WHERE  pi.id = ? AND pi.project_id = ?""",
            (insight_id, project_id),
        ).fetchone()

    if not row:
        return ""

    pkg          = json.loads(row["insight_json"]) if isinstance(row["insight_json"], str) else {}
    project_name = row["project_name"] or ""
    day_number   = row["day_number"]
    date_str     = _fmt_date(row["generated_at"] or "")

    lines: list[str] = []

    headline = pkg.get("package_headline") or f"Day {day_number}"
    lines += [f"# {headline}", ""]

    meta_parts = [f"Day {day_number}", date_str]
    if project_name:
        meta_parts.append(project_name)
    lines += [f"**{'  ·  '.join(p for p in meta_parts if p)}**", ""]

    thread = pkg.get("learning_thread", "")
    if thread:
        lines += [f"> {thread}", ""]

    all_cards = list(pkg.get("insights") or []) + list(pkg.get("curiosity_insights") or [])
    for card in all_cards:
        lines += _card_to_md(card)

    action = pkg.get("action_item", "")
    if action:
        lines += ["---", "", "## ✅ Today's Action", "", action, ""]

    today = date.today().isoformat()
    lines += ["---", "", f"*Exported from Research Agent · {today}*"]

    return "\n".join(lines)
