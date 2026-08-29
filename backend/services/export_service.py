"""
Package export to Markdown — pure templating, zero LLM calls.

Public API
----------
insight_to_markdown(project_id, insight_id)              -> str
card_to_markdown(project_id, insight_id, article_key)    -> str
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone


def _fmt_date(ts: str) -> str:
    """ISO timestamp → 'Month D, YYYY'."""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return f"{dt.strftime('%B')} {dt.day}, {dt.year}"
    except Exception:
        return ts[:10] if ts else ""


_TYPE_EMOJI = {"news": "📰", "educational": "📚", "curiosity": "💡"}
_STEP_MARKER = re.compile(r"^\d+\.\s*")


def _block_to_md(btype: str, content: str) -> list[str]:
    text = (content or "").strip()
    if not text:
        return []
    if btype == "step_list":
        steps = [_STEP_MARKER.sub("", s).strip() for s in text.split("\n") if s.strip()]
        return [f"{i}. {s}" for i, s in enumerate(steps, 1)] + [""]
    if btype == "warning":
        return [f"> ⚠️ {text}", ""]
    if btype == "evidence":
        return [f"> {text}", ""]
    if btype == "key_takeaway":
        return [f"**{text}**", ""]
    label = btype.replace("_", " ").title() if btype else "Note"
    return [f"**{label}**", "", text, ""]


def _get_next_day_title(project_id: str, next_day: int, conn) -> str | None:
    batch_row = conn.execute(
        """SELECT plan_content, shape FROM journey_plans
           WHERE project_id = ? AND day_start <= ? AND day_end >= ?
           ORDER BY created_at DESC LIMIT 1""",
        (project_id, next_day, next_day),
    ).fetchone()
    if not batch_row or batch_row["shape"] != "fixed_sequence":
        return None
    batch = json.loads(batch_row["plan_content"])
    for entry in (batch.get("days") or []):
        if entry.get("day_number") == next_day:
            return entry.get("display_title") or None
    return None


def _card_to_md(card: dict) -> list[str]:
    lines: list[str] = []
    emoji = _TYPE_EMOJI.get(card.get("content_type", ""), "📄")
    lines += ["---", "", f"## {emoji} {card.get('title', '')} ", ""]

    if card.get("category"):
        lines += [f"*{card['category']}*", ""]

    if card.get("summary"):
        lines += [card["summary"], ""]

    blocks = card.get("blocks") or []
    if blocks:
        for b in blocks:
            lines += _block_to_md(b.get("type", ""), b.get("content", ""))
    else:
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


def card_to_markdown(project_id: str, insight_id: int, article_key: str) -> str:
    """
    One card of a day package, addressed by article_key, with the day's headline
    kept as framing. "" when the package or the card can't be resolved.

    Same renderer as insight_to_markdown (_card_to_md) -- this is the single-card
    scope of it, for callers that need the card the user actually acted on rather
    than the whole day.
    """
    if not article_key:
        return ""

    from ..utils.db import get_connection
    from .feed_read_service import article_key_from_title

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

    pkg = json.loads(row["insight_json"]) if isinstance(row["insight_json"], str) else {}
    all_cards = list(pkg.get("insights") or []) + list(pkg.get("curiosity_insights") or [])
    card = next(
        (c for c in all_cards if article_key_from_title(c.get("title") or "") == article_key),
        None,
    )
    if card is None:
        return ""

    meta_parts = [f"Day {row['day_number']}", _fmt_date(row["generated_at"] or "")]
    if row["project_name"]:
        meta_parts.append(row["project_name"])

    headline = pkg.get("package_headline") or f"Day {row['day_number']}"
    lines: list[str] = [f"# {headline}", ""]
    lines += [f"**{'  ·  '.join(p for p in meta_parts if p)}**", ""]
    lines += _card_to_md(card)

    return "\n".join(lines)


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

        next_title = _get_next_day_title(project_id, row["day_number"] + 1, conn)

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

    if next_title:
        lines += ["", f"*Next up: {next_title}*"]

    return "\n".join(lines)
