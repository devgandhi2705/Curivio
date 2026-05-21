"""
GitHub repository discovery for the AI learning agent.

For a given technical topic, searches the GitHub API, ranks results by quality
signals (stars, recency, topic relevance), and caches the results so repeated
calls are free.

Ranking signals
---------------
- Stars (log-scaled, primary signal)
- Recent activity within 6 months (+1.0 bonus)
- Topic-word overlap between repo topics and search topic (+0.5 per match)
- Filtered out: archived repos, repos with no description, repos below MIN_STARS

Public API
----------
get_topic_repos(topic)       — cache-first; fetches from GitHub on a miss
list_repo_topics(limit)      — list stored topics newest-first

Correct patch targets for tests
--------------------------------
  requests.get          → requests.get
  get_connection        → backend.services.github_service.get_connection

Environment variables
----------------------
  GITHUB_TOKEN              — optional; raises rate limit from 60 to 5000 req/h
  GITHUB_REPOS_TTL_HOURS    — cache TTL, default 24
  GITHUB_MAX_REPOS          — repos returned per topic, default 5
  GITHUB_MIN_STARS          — repos below this are discarded, default 50
"""

import json
import logging
import math
import os
from datetime import datetime, timedelta, timezone

import requests

from ..utils.db import get_connection

logger = logging.getLogger(__name__)

_GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
_TIMEOUT_SECONDS   = 10

from ..config import (
    GITHUB_REPOS_TTL_HOURS as GITHUB_TTL_HOURS,
    GITHUB_MAX_REPOS,
    GITHUB_MIN_STARS,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def get_topic_repos(topic: str) -> list[dict]:
    """Return repos for topic, fetching from GitHub on a cache miss."""
    cached = _get_stored_repos(topic)
    if cached is not None:
        logger.info("[github] cache hit for %r", topic)
        return cached
    logger.info("[github] fetching repos for %r", topic)
    repos = _fetch_and_rank(topic)
    _store_repos(topic, repos)
    return repos


def list_repo_topics(limit: int = 20) -> list[dict]:
    """Return stored repo-discovery entries newest-first (id, topic, fetched_at)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, topic, fetched_at FROM github_repos "
            "ORDER BY fetched_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════════════
# Internal implementation
# ═══════════════════════════════════════════════════════════════════════════════

def _fetch_and_rank(topic: str) -> list[dict]:
    query = _build_query(topic)
    raw   = _fetch_from_github(query)
    items = raw.get("items", [])
    return _rank_repos(items, topic)[:GITHUB_MAX_REPOS]


def _build_query(topic: str) -> str:
    """Build a GitHub search query from a topic string."""
    return f"{topic.strip()} in:name,description,topics stars:>{GITHUB_MIN_STARS}"


def _fetch_from_github(query: str) -> dict:
    """Call the GitHub search API and return the raw JSON response dict."""
    headers = {"Accept": "application/vnd.github.v3+json"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"

    resp = requests.get(
        _GITHUB_SEARCH_URL,
        params={"q": query, "sort": "stars", "order": "desc", "per_page": 10},
        headers=headers,
        timeout=_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    return resp.json()


def _rank_repos(items: list[dict], topic: str) -> list[dict]:
    """
    Filter and rank GitHub search results by quality signals.

    Discards archived repos, repos without a description, and repos below
    GITHUB_MIN_STARS. Scores the rest by stars (log-scaled), recent activity,
    and overlap between repo topics and the search topic words.
    """
    topic_words  = set(topic.lower().split())
    scored: list[tuple[float, dict]] = []

    for item in items:
        if item.get("archived"):
            continue
        if not item.get("description", "").strip():
            continue
        stars = item.get("stargazers_count", 0)
        if stars < GITHUB_MIN_STARS:
            continue

        score = math.log1p(stars)

        # Recency bonus: updated within the last 6 months
        updated_at = item.get("updated_at", "")
        if updated_at:
            try:
                updated  = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                age_days = (datetime.now(timezone.utc) - updated).days
                if age_days < 180:
                    score += 1.0
            except ValueError:
                pass

        # Topic-word overlap bonus
        repo_topics = [t.lower() for t in item.get("topics", [])]
        overlap = sum(
            1 for word in topic_words
            if any(word in rt for rt in repo_topics)
        )
        score += overlap * 0.5

        scored.append((score, {
            "name":        item.get("full_name", item.get("name", "")),
            "description": item.get("description", ""),
            "stars":       stars,
            "url":         item.get("html_url", ""),
            "language":    item.get("language"),
            "topics":      item.get("topics", []),
        }))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [repo for _, repo in scored]


def _store_repos(topic: str, repos: list[dict]) -> None:
    """Upsert repo list for a topic into the cache table."""
    key = _topic_key(topic)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO github_repos (topic, topic_key, repos_json, fetched_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(topic_key) DO UPDATE SET
                topic      = excluded.topic,
                repos_json = excluded.repos_json,
                fetched_at = CURRENT_TIMESTAMP
            """,
            (topic.strip(), key, json.dumps(repos)),
        )


def _get_stored_repos(topic: str) -> list[dict] | None:
    """Return cached repos if they exist and have not expired."""
    key    = _topic_key(topic)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=GITHUB_TTL_HOURS)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT repos_json, fetched_at FROM github_repos WHERE topic_key = ?",
            (key,),
        ).fetchone()
    if row is None:
        return None
    if _parse_ts(row["fetched_at"]) < cutoff:
        return None
    return json.loads(row["repos_json"])


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers (exposed for unit tests)
# ═══════════════════════════════════════════════════════════════════════════════

def _topic_key(topic: str) -> str:
    return topic.strip().lower()


def _parse_ts(value: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Unrecognised timestamp format: {value!r}")
