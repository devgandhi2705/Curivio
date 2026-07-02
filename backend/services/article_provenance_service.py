"""
Article Provenance Service

Persists retrieval evidence for every article that enters the feed pipeline.
Called before generation begins; updated after the package is saved.

Supports audit queries: "Why was this article generated?"
  → source used, query used, ranking score, selection reason

Public API
----------
persist(project_id, feed_date, articles, source_type, queries) -> None
mark_selected(project_id, insight_id, urls)                    -> None
get_for_audit(project_id, feed_date)                           -> list[dict]
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def persist(
    project_id:  str,
    feed_date:   str,
    articles:    list[dict],
    source_type: str,
    queries:     list[str],
) -> None:
    """
    Write one provenance row per article.
    source_type = "core" | "serendipity"
    queries     = search queries for this retrieval batch (stored as audit trail)
    _retrieval_score and _rank_score/_rank_reason are read from article metadata
    set by filter_articles() and rank_articles() respectively.
    """
    if not articles:
        return

    query_used = "; ".join(q for q in queries if q)[:500]
    now        = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []

    for article in articles:
        url    = article.get("url") or ""
        domain = _extract_domain(url)
        rows.append((
            str(uuid.uuid4()),
            project_id,
            feed_date,
            (article.get("title") or "")[:500],
            url[:1000],
            domain,
            domain,                                        # publisher = domain for now
            source_type,
            query_used,
            float(article.get("_retrieval_score") or 0.0),
            float(article.get("_rank_score")      or 0.0),
            (article.get("_rank_reason") or "")[:100],
            0,
            now,
        ))

    from ..utils.db import get_connection
    with get_connection() as conn:
        conn.executemany(
            """INSERT OR IGNORE INTO article_provenance
               (id, project_id, feed_date, title, url, domain, publisher,
                source_type, query_used, retrieval_score, ranking_score,
                ranking_reason, selected, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

    logger.debug(
        "[provenance] persisted %d %s articles for project %s date %s",
        len(rows), source_type, project_id, feed_date,
    )


def mark_selected(project_id: str, insight_id: int, urls: list[str]) -> None:
    """
    Set selected=1 and insight_id on provenance rows whose URL appears in
    the final generated package.
    """
    if not urls:
        return

    from ..utils.db import get_connection
    with get_connection() as conn:
        conn.executemany(
            """UPDATE article_provenance
               SET selected = 1, insight_id = ?
               WHERE project_id = ? AND url = ?""",
            [(insight_id, project_id, url) for url in urls],
        )

    logger.debug(
        "[provenance] marked %d URLs selected for insight %d project %s",
        len(urls), insight_id, project_id,
    )


def get_recent_source_usage(
    project_id:  str,
    window_days: int = 7,
) -> dict[str, int]:
    """
    Return {normalised_url: days_since_last_use} for every source that was
    actually selected (selected=1) in the last `window_days` calendar days.

    Used by the ranker to apply a recency penalty — sources repeated too soon
    score lower so the feed naturally diversifies across days.
    """
    from datetime import date, timedelta
    from ..utils.db import get_connection

    cutoff = (date.today() - timedelta(days=window_days)).isoformat()
    today  = date.today()

    with get_connection() as conn:
        rows = conn.execute(
            """SELECT url, MAX(feed_date) AS last_date
               FROM article_provenance
               WHERE project_id = ? AND selected = 1 AND feed_date >= ?
               GROUP BY url""",
            (project_id, cutoff),
        ).fetchall()

    result: dict[str, int] = {}
    for row in rows:
        url_norm = (row["url"] or "").rstrip("/").lower()
        if not url_norm:
            continue
        try:
            delta = (today - date.fromisoformat(row["last_date"])).days
        except (ValueError, TypeError):
            continue
        result[url_norm] = delta

    return result


def get_for_audit(project_id: str, feed_date: str | None = None) -> list[dict]:
    """
    Return provenance records for a project, optionally scoped to a date.
    Records answer: source, query used, ranking score, selection reason.
    """
    from ..utils.db import get_connection
    with get_connection() as conn:
        if feed_date:
            rows = conn.execute(
                """SELECT * FROM article_provenance
                   WHERE project_id = ? AND feed_date = ?
                   ORDER BY selected DESC, ranking_score DESC""",
                (project_id, feed_date),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM article_provenance
                   WHERE project_id = ?
                   ORDER BY feed_date DESC, selected DESC, ranking_score DESC
                   LIMIT 200""",
                (project_id,),
            ).fetchall()
    return [dict(r) for r in rows]


def _extract_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""
