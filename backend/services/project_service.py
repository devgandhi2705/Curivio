"""
Learning Projects service — CRUD and per-project daily intelligence generation.

Each call to generate_project_insight() produces a *daily package*:
  - 3 news cards  (current-events grounded)
  - 2 educational cards (evergreen concepts)

A daily guard prevents double-generation for the same project on the same UTC day.

Public API
----------
create_project(...)             -> dict
list_projects()                 -> list[dict]
get_project(project_id)         -> dict | None
update_project(project_id, ...) -> dict | None
delete_project(project_id)      -> bool

generate_project_insight(project_id)       -> dict   (daily package)
generate_all_projects()                    -> dict   (summary of batch run)
list_project_insights(project_id, limit)   -> list[dict]
get_project_insight(insight_id)            -> dict | None
already_generated_today(project_id)        -> bool
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_DATETIME_FMT = "%Y-%m-%dT%H:%M:%SZ"
_DATE_FMT     = "%Y-%m-%d"


def _now() -> str:
    return datetime.now(timezone.utc).strftime(_DATETIME_FMT)


def _today() -> str:
    return datetime.now(timezone.utc).strftime(_DATE_FMT)


# ─────────────────────────────────────────────────────────────────────────────
# Project CRUD
# ─────────────────────────────────────────────────────────────────────────────

def create_project(
    name: str,
    description: str = "",
    keywords: list[str] | None = None,
    difficulty: str = "intermediate",
    focus_areas: list[str] | None = None,
    color: str = "blue",
    preferred_sources: list[str] | None = None,
    ignored_sources: list[str] | None = None,
    daily_core_article_count: int = 4,
    user_id: str | None = None,
) -> dict:
    from ..utils.db import get_connection
    project_id = str(uuid.uuid4())
    now = _now()
    count = max(2, min(10, int(daily_core_article_count)))
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO learning_projects
               (project_id, name, description, keywords, difficulty, focus_areas, color, preferred_sources, ignored_sources, daily_core_article_count, created_at, updated_at, user_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (project_id, name, description,
             json.dumps(keywords or []), difficulty,
             json.dumps(focus_areas or []), color,
             json.dumps(_normalize_sources(preferred_sources or [])),
             json.dumps(_normalize_sources(ignored_sources or [])),
             count, now, now, user_id),
        )
    return get_project(project_id)


def list_projects(user_id: str | None = None) -> list[dict]:
    from ..utils.db import get_connection
    with get_connection() as conn:
        if user_id:
            rows = conn.execute(
                """SELECT p.*,
                          COALESCE(MAX(i.day_number), 0) AS insight_count,
                          MAX(i.generated_at) AS last_insight_at
                   FROM learning_projects p
                   LEFT JOIN project_insights i ON i.project_id = p.project_id
                   WHERE p.user_id = ?
                   GROUP BY p.project_id
                   ORDER BY p.updated_at DESC""",
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT p.*,
                          COALESCE(MAX(i.day_number), 0) AS insight_count,
                          MAX(i.generated_at) AS last_insight_at
                   FROM learning_projects p
                   LEFT JOIN project_insights i ON i.project_id = p.project_id
                   GROUP BY p.project_id
                   ORDER BY p.updated_at DESC"""
            ).fetchall()
    return [_project_row(r) for r in rows]


def get_project(project_id: str) -> dict | None:
    from ..utils.db import get_connection
    with get_connection() as conn:
        row = conn.execute(
            """SELECT p.*,
                      COALESCE(MAX(i.day_number), 0) AS insight_count,
                      MAX(i.generated_at) AS last_insight_at
               FROM learning_projects p
               LEFT JOIN project_insights i ON i.project_id = p.project_id
               WHERE p.project_id = ?
               GROUP BY p.project_id""",
            (project_id,),
        ).fetchone()
    return _project_row(row) if row else None


def update_project(project_id: str, **fields) -> dict | None:
    allowed = {"name", "description", "keywords", "difficulty", "focus_areas", "color", "preferred_sources", "ignored_sources", "daily_core_article_count"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_project(project_id)
    updates["updated_at"] = _now()
    for lf in ("keywords", "focus_areas"):
        if lf in updates and isinstance(updates[lf], list):
            updates[lf] = json.dumps(updates[lf])
    if "preferred_sources" in updates and isinstance(updates["preferred_sources"], list):
        updates["preferred_sources"] = json.dumps(_normalize_sources(updates["preferred_sources"]))
    if "ignored_sources" in updates and isinstance(updates["ignored_sources"], list):
        updates["ignored_sources"] = json.dumps(_normalize_sources(updates["ignored_sources"]))
    if "daily_core_article_count" in updates:
        updates["daily_core_article_count"] = max(2, min(10, int(updates["daily_core_article_count"])))
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    from ..utils.db import get_connection
    with get_connection() as conn:
        conn.execute(
            f"UPDATE learning_projects SET {set_clause} WHERE project_id = ?",
            [*updates.values(), project_id],
        )
    return get_project(project_id)


def delete_project(project_id: str) -> bool:
    from ..utils.db import get_connection
    with get_connection() as conn:
        r = conn.execute("DELETE FROM learning_projects WHERE project_id = ?", (project_id,))
    return r.rowcount > 0


def _project_row(row) -> dict:
    d = dict(row)
    for lf in ("keywords", "focus_areas", "preferred_sources", "ignored_sources"):
        raw = d.get(lf)
        if isinstance(raw, str):
            try:
                d[lf] = json.loads(raw)
            except Exception:
                d[lf] = []
        elif raw is None:
            d[lf] = []
    if d.get("daily_core_article_count") is None:
        d["daily_core_article_count"] = 4
    return d


def _normalize_sources(sources: list[str]) -> list[str]:
    """
    Normalize a list of source URLs/domains to bare domain strings suitable
    for Tavily include_domains (e.g. "https://arxiv.org" → "arxiv.org").

    Deduplicates and filters out empty/invalid entries.
    """
    from urllib.parse import urlparse
    seen: set[str] = set()
    result: list[str] = []
    for s in sources:
        s = s.strip().lower()
        if not s:
            continue
        if "://" not in s:
            s = "https://" + s
        try:
            netloc = urlparse(s).netloc
        except Exception:
            continue
        domain = netloc.removeprefix("www.").rstrip(".").split(":")[0]
        if domain and "." in domain and domain not in seen:
            seen.add(domain)
            result.append(domain)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Source relevance check
# ─────────────────────────────────────────────────────────────────────────────

_CONSUMER_BLOCKLIST: frozenset[str] = frozenset({
    "facebook.com", "instagram.com", "twitter.com", "x.com", "tiktok.com",
    "snapchat.com", "ok.com", "vk.com", "tumblr.com", "pinterest.com",
    "youtube.com", "netflix.com", "twitch.tv", "spotify.com",
    "amazon.com", "ebay.com", "etsy.com", "aliexpress.com",
    "whatsapp.com", "telegram.org", "discord.com", "slack.com",
    "google.com", "bing.com", "yahoo.com", "duckduckgo.com",
})


def check_source_relevance(domain: str, project_name: str, keywords: list[str]) -> dict:
    """
    Check whether a domain is relevant to a learning project.

    Fast path: blocklist of consumer/social sites → always irrelevant.
    Slow path: minimal Grok call to judge relevance.
    Returns {"relevant": bool, "reason": str}.
    """
    domain_lower = domain.lower().strip()
    if domain_lower in _CONSUMER_BLOCKLIST:
        return {
            "relevant": False,
            "reason": f"{domain} is a consumer/social platform — not useful as a research source",
        }

    kw_str = ", ".join(keywords[:5]) if keywords else project_name
    prompt = (
        f'Is "{domain}" a useful research or reference source for learning about '
        f'"{project_name}" ({kw_str})? Reply with YES or NO only.'
    )
    try:
        from .grok_service import ask_grok
        answer = ask_grok(prompt).strip().upper()
        relevant = answer.startswith("Y")
        return {
            "relevant": relevant,
            "reason": (
                f"Relevant to {project_name}" if relevant
                else f"{domain} does not appear to cover {project_name} topics"
            ),
        }
    except Exception as exc:
        logger.warning("[project_service] relevance check failed for %r: %s", domain, exc)
        return {"relevant": True, "reason": "Validation unavailable — defaulting to relevant"}


# ─────────────────────────────────────────────────────────────────────────────
# Display label helpers (mirrors frontend computeDisplayLabels / computeNextLabel)
# ─────────────────────────────────────────────────────────────────────────────

def _compute_display_labels(project_id: str) -> dict[int, str]:
    """
    Returns {day_number: display_label} for all existing packages of a project.
    Same logic as the frontend computeDisplayLabels:
      - First package of each calendar date → "Day X"
      - Subsequent packages on same date   → "Day X.1", "Day X.2", …
    """
    from ..utils.db import get_connection
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT day_number, DATE(generated_at) AS date_str, insight_json
               FROM project_insights
               WHERE project_id = ?
               ORDER BY day_number ASC""",
            (project_id,),
        ).fetchall()

    labels: dict[int, str] = {}
    calendar_day = 0
    last_date: str | None = None
    sub_count = 0

    for row in rows:
        try:
            pkg = json.loads(row["insight_json"]) if row["insight_json"] else {}
            insights = pkg.get("insights", []) or []
        except Exception:
            insights = []

        if not insights:          # failed package
            labels[row["day_number"]] = "Day 0"
            continue

        d = row["date_str"]
        if d != last_date:
            calendar_day += 1
            sub_count = 0
            last_date = d
            labels[row["day_number"]] = f"Day {calendar_day}"
        else:
            sub_count += 1
            labels[row["day_number"]] = f"Day {calendar_day}.{sub_count}"

    return labels


def _compute_next_display_label(project_id: str) -> tuple[str, str | None]:
    """
    Returns (next_display_label, prev_display_label) for the package about to
    be generated.  prev_display_label is None when no packages exist yet.
    """
    from ..utils.db import get_connection
    today = _today()

    with get_connection() as conn:
        rows = conn.execute(
            """SELECT day_number, DATE(generated_at) AS date_str
               FROM project_insights
               WHERE project_id = ?
               ORDER BY day_number ASC""",
            (project_id,),
        ).fetchall()

    if not rows:
        return "Day 1", None

    # Rebuild calendar day counter (skip failed packages for numbering)
    existing_labels = _compute_display_labels(project_id)
    last_row = rows[-1]
    prev_label = existing_labels.get(last_row["day_number"])

    # Determine the highest non-Day-0 calendar day number
    good_labels = [v for v in existing_labels.values() if v != "Day 0"]
    if not good_labels:
        return "Day 1", prev_label

    # Extract the base calendar number from the latest good label
    import re as _re
    base_num = max(
        int(m.group(1))
        for label in good_labels
        if (m := _re.match(r"Day (\d+)", label))
    )

    today_count = sum(1 for r in rows if r["date_str"] == today)
    last_date = last_row["date_str"]

    if last_date == today:
        next_label = f"Day {base_num}.{today_count}"
    else:
        next_label = f"Day {base_num + 1}"

    return next_label, prev_label


# ─────────────────────────────────────────────────────────────────────────────
# Article retrieval — separate pipelines for core learning vs curiosity
# ─────────────────────────────────────────────────────────────────────────────

def _search_articles(query: str, preferred_sources: list[str] | None = None) -> list[dict]:
    """Single retrieval call — broad search, no domain restriction. Never raises."""
    try:
        from .retrieval_router import route
        return route(query, mode="feed")
    except Exception as e:
        logger.warning("[project_service] retrieval failed for %r: %s", query, e)
        return []


def _search_articles_targeted(query: str, domains: list[str]) -> list[dict]:
    """
    Targeted retrieval restricted to specific domains (user preferred sources).
    Used for the preferred-source slots in the article blend.
    Never raises.
    """
    try:
        from .retrieval_router import route
        return route(query, mode="feed", preferred_domains=domains)
    except Exception as e:
        logger.warning("[project_service] targeted retrieval failed for %r: %s", query, e)
        return []


def _dedup_articles(articles: list[dict]) -> list[dict]:
    """Remove duplicate URLs, preserve order."""
    seen: set[str] = set()
    out: list[dict] = []
    for a in articles:
        url = a.get("url", "")
        if url and url not in seen:
            seen.add(url)
            out.append(a)
        elif not url:
            out.append(a)
    return out


def _fetch_core_articles(
    project_name: str,
    keywords: list[str],
    suggested_next_topics: list[str],
    preferred_sources: list[str] | None = None,
) -> list[dict]:
    """
    Progression-aware retrieval for core learning cards.

    Retrieval strategy:
      Query 1: Targets the next suggested topic (curriculum advancement).
      Query 2: Broader project developments (keeps content current).
      Query 3 (if preferred_sources): Targeted search restricted to user's
               preferred domains — fills the dedicated preferred-source slots.

    Results are blended so preferred-source articles get priority slots,
    then filled from global search. Deduplication is applied at the end.
    """
    kw = " ".join(keywords[:3]) if keywords else project_name

    if suggested_next_topics:
        next_topic = suggested_next_topics[0]
        q1 = f"{project_name} {next_topic} 2025 2026"
        q2 = f"{next_topic} {kw} concepts framework analysis depth"
    else:
        q1 = f"{project_name} {kw} latest developments 2025 2026"
        q2 = f"{project_name} {kw} concepts framework deep dive"

    # Global search (always run)
    global_articles = _dedup_articles(_search_articles(q1) + _search_articles(q2))

    # Preferred-source search (only when user has anchors configured)
    preferred_articles: list[dict] = []
    if preferred_sources:
        pref_query = q1  # use the progression-focused query for preferred sources too
        preferred_articles = _search_articles_targeted(pref_query, preferred_sources)
        logger.info(
            "[project_service] preferred source retrieval: %d articles from %s",
            len(preferred_articles), preferred_sources[:3],
        )

    # Blend: up to 2 preferred-source slots first, then fill from global
    seen_urls: set[str] = set()
    blended: list[dict] = []

    for a in preferred_articles[:2]:
        url = a.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            blended.append(a)

    for a in global_articles:
        url = a.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            blended.append(a)

    return blended


_CURIOSITY_QUERIES = [
    "{project_name} {kw} biggest failure mistake controversy scandal",
    "{project_name} {kw} history origin invention accident discovery",
    "{project_name} {kw} surprising counterintuitive secret insider",
    "{project_name} {kw} behind the scenes hidden mechanism how it actually works",
    "{project_name} {kw} founder story pivot near failure comeback",
]


def _fetch_curiosity_articles(
    project_name: str,
    keywords: list[str],
) -> list[dict]:
    """
    Retrieval for curiosity/expansion cards targeting "WAIT… WHAT?" content.

    Runs two queries with different curiosity angles — history/controversy
    and counterintuitive/secret — to give the LLM surprising material to work with.
    """
    kw = " ".join(keywords[:2]) if keywords else project_name
    import random
    # Pick two non-overlapping curiosity angles for variety
    angles = random.sample(_CURIOSITY_QUERIES, k=min(2, len(_CURIOSITY_QUERIES)))
    results: list[dict] = []
    for angle_template in angles:
        q = angle_template.format(project_name=project_name, kw=kw)
        results.extend(_search_articles(q, None))
    return _dedup_articles(results)


# ─────────────────────────────────────────────────────────────────────────────
# Daily package generation
# ─────────────────────────────────────────────────────────────────────────────

def generate_project_insight(project_id: str) -> dict:
    """
    Generate a progressive daily learning package for a project.

    Package structure:
      - insights[]           → core learning cards (count driven by daily_core_article_count)
      - curiosity_insights[] → exactly 2 curiosity/exploration cards

    Multiple generations per calendar day are allowed and encouraged.
    Same-day packages are labelled Day X.1, X.2 … by the frontend.

    Raises ValueError if the project is not found.
    Returns the saved package dict.
    """
    project = get_project(project_id)
    if not project:
        raise ValueError(f"Project {project_id!r} not found")

    # Use MAX(day_number) so duplicate rows never inflate the counter
    from ..utils.db import get_connection as _gc
    with _gc() as _conn:
        _row = _conn.execute(
            "SELECT COALESCE(MAX(day_number), 0) AS max_day FROM project_insights WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    day_number               = (_row["max_day"] if _row else 0) + 1
    display_label, prev_display_label = _compute_next_display_label(project_id)
    keywords                 = project.get("keywords") or []
    focus_areas              = project.get("focus_areas") or []
    difficulty               = project.get("difficulty", "intermediate")
    preferred_sources        = project.get("preferred_sources") or []
    daily_core_article_count = project.get("daily_core_article_count") or 4

    # ── Load learning progression ─────────────────────────────────────────────
    try:
        from .progression_service import get_progression
        progression           = get_progression(project_id)
        explored_concepts     = progression.get("explored_concepts", [])
        suggested_next_topics = progression.get("suggested_next_topics", [])
    except Exception:
        explored_concepts     = []
        suggested_next_topics = []

    # ── Build rich previous-package summaries (last 3, oldest-first) ──────────
    previous_pkgs = list_project_insights(project_id, limit=3)
    existing_labels = _compute_display_labels(project_id)
    previous_packages: list[dict] = []
    for p in reversed(previous_pkgs):
        cards      = p.get("insights", [])
        categories = list({c.get("category", "") for c in cards if c.get("category")})
        day_num    = p.get("day_number")
        day_label  = existing_labels.get(day_num, f"Day {day_num}")
        previous_packages.append({
            "day":        day_label,
            "headline":   p.get("package_headline", ""),
            "categories": categories[:5],
        })

    # ── Retrieve articles — two separate pipelines ────────────────────────────
    core_articles = _fetch_core_articles(
        project["name"], keywords, suggested_next_topics,
        preferred_sources=preferred_sources,
    )
    curiosity_articles = _fetch_curiosity_articles(project["name"], keywords)

    logger.info(
        "[project_service] %s day=%d core=%d curiosity=%d next_topics=%s",
        project_id, day_number,
        len(core_articles), len(curiosity_articles),
        suggested_next_topics[:2],
    )

    # ── Build and send prompt ─────────────────────────────────────────────────
    from ..prompts.project_insight_prompt import make_daily_package_prompt
    prompt = make_daily_package_prompt(
        project_name=project["name"],
        keywords=keywords,
        difficulty=difficulty,
        focus_areas=focus_areas,
        day_number=day_number,
        display_label=display_label,
        prev_display_label=prev_display_label,
        previous_packages=previous_packages,
        core_articles=core_articles,
        curiosity_articles=curiosity_articles,
        explored_concepts=explored_concepts,
        suggested_next_topics=suggested_next_topics,
        daily_core_article_count=daily_core_article_count,
    )

    try:
        from .grok_service import ask_grok
        text = ask_grok(prompt, json_mode=True)
        raw  = _extract_json(text)
    except Exception as e:
        logger.error("[project_service] generation failed for %s: %s", project_id, e)
        raise RuntimeError(str(e)) from e

    # Validate that the model returned actual content before saving anything
    if not raw.get("insights"):
        logger.error("[project_service] generation returned no insight cards for %s", project_id)
        raise RuntimeError("Generation produced no insight cards — please try again.")

    # Guarantee curiosity_insights key exists (older LLM outputs may omit it)
    if "curiosity_insights" not in raw:
        raw["curiosity_insights"] = []

    package = {
        "id":           None,
        "project_id":   project_id,
        "day_number":   day_number,
        "generated_at": _now(),
        **raw,
    }

    pkg_id       = _save_package(project_id, day_number, package)
    package["id"] = pkg_id

    # Auto-update learning progression (non-fatal)
    try:
        from .progression_service import update_progression_from_package
        update_progression_from_package(project_id, package)
    except Exception:
        logger.warning("[project_service] progression update failed for %s (non-fatal)", project_id)

    return package


def generate_all_projects() -> dict:
    """
    Run daily generation for every project.  Called by the scheduler.

    Returns a summary dict:
      {"total": int, "generated": int, "skipped": int, "failed": int, "errors": [str]}
    """
    projects = list_projects()
    total = len(projects)
    generated = failed = 0
    errors: list[str] = []

    for proj in projects:
        pid = proj["project_id"]
        try:
            generate_project_insight(pid)
            generated += 1
            logger.info("[project_service] generated package for %s (%s)", pid, proj["name"])
        except Exception as e:
            failed += 1
            msg = f"{proj['name']} ({pid}): {e}"
            errors.append(msg)
            logger.error("[project_service] failed for %s: %s", pid, e)

    return {
        "total":     total,
        "generated": generated,
        "skipped":   0,
        "failed":    failed,
        "errors":    errors,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Storage helpers
# ─────────────────────────────────────────────────────────────────────────────

def list_project_insights(project_id: str, limit: int = 20) -> list[dict]:
    from ..utils.db import get_connection
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT id, project_id, day_number, insight_json, generated_at
               FROM project_insights
               WHERE project_id = ?
               ORDER BY day_number DESC
               LIMIT ?""",
            (project_id, limit),
        ).fetchall()
    return [_pkg_row(r) for r in rows]


def get_project_insight(insight_id: int) -> dict | None:
    from ..utils.db import get_connection
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, project_id, day_number, insight_json, generated_at FROM project_insights WHERE id = ?",
            (insight_id,),
        ).fetchone()
    return _pkg_row(row) if row else None


def _save_package(project_id: str, day_number: int, package: dict) -> int:
    from ..utils.db import get_connection
    now = package["generated_at"]
    with get_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO project_insights (project_id, day_number, insight_json, generated_at)
               VALUES (?, ?, ?, ?)""",
            (project_id, day_number, json.dumps(package), now),
        )
        conn.execute(
            "UPDATE learning_projects SET updated_at = ? WHERE project_id = ?",
            (now, project_id),
        )
    return cursor.lastrowid


def _pkg_row(row) -> dict:
    d = dict(row)
    raw = d.pop("insight_json", "{}")
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = {}
    return {
        **parsed,
        "id":           d["id"],
        "project_id":   d["project_id"],
        "generated_at": d["generated_at"],
    }


def _extract_json(text: str) -> dict:
    """Extract a JSON object from LLM output using multiple fallback strategies."""
    # Strategy 1: JSON inside a code fence
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    # Strategy 2: outermost { ... }
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start : end + 1])
    # Strategy 3: raw parse (will raise if not JSON)
    return json.loads(text.strip())


def delete_project_insight(project_id: str, insight_id: int) -> bool:
    from ..utils.db import get_connection
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM project_insights WHERE id = ? AND project_id = ?",
            (insight_id, project_id),
        )
    return cur.rowcount > 0


def _fallback_package(project_name: str, day_number: int) -> dict:
    return {
        "package_headline": f"Day {day_number} — {project_name} (generation error — retry)",
        "content_mix": "0 news · 0 educational + 0 curiosity picks",
        "learning_thread": "Generation failed. Retry to get structured content.",
        "action_item": f"Manually search for recent '{project_name}' developments.",
        "insights": [],
        "curiosity_insights": [],
    }
