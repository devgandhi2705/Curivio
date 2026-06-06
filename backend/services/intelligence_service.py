"""
Personalized daily intelligence feed engine.

Upgrades the basic learning feed into a multi-section intelligence brief by:
  - Running multi-domain article searches (interests + inferred industry)
  - Pulling chat context (recent topics + explained concepts from DB)
  - Inferring the user's industry focus from liked topics and chat history
  - Generating a 3-section brief (industry news, market trends, tech discoveries)
    plus a personalized learning track connected to recent chat history

Public API
----------
generate_intelligence_feed(interests)  -> dict
get_recent_intelligence_feeds(limit)   -> list[dict]
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Industry inference
# ═══════════════════════════════════════════════════════════════════════════════

_INDUSTRY_MAP: dict[str, list[str]] = {
    "AI / Machine Learning": [
        "llm", "machine learning", "deep learning", "neural network",
        "transformer", "gpt", "embedding", "rag", "vector database",
        "diffusion", "reinforcement learning", "fine-tuning", "langchain",
        "agent", "prompt engineering",
    ],
    "Web / Full-Stack Development": [
        "react", "nextjs", "typescript", "javascript", "frontend",
        "backend", "api", "graphql", "rest", "node", "css", "html",
        "tailwind", "vue", "angular",
    ],
    "Cloud / DevOps": [
        "kubernetes", "docker", "aws", "gcp", "azure", "terraform",
        "ci/cd", "devops", "infrastructure", "serverless", "helm",
    ],
    "Data Engineering": [
        "spark", "airflow", "dbt", "data pipeline", "etl",
        "data warehouse", "lakehouse", "flink", "kafka",
    ],
    "Cybersecurity": [
        "security", "cryptography", "zero trust", "authentication",
        "vulnerability", "penetration testing", "soc", "malware",
    ],
    "Fintech / Finance": [
        "fintech", "defi", "blockchain", "crypto", "payment",
        "banking", "trading", "quant", "financial",
    ],
    "Product / Startup": [
        "startup", "saas", "product market fit", "growth",
        "b2b", "venture capital", "fundraising", "go-to-market",
    ],
}


def _infer_industry(topics: list[str]) -> str:
    """Map topic list to the most-represented industry domain."""
    if not topics:
        return "technology"
    text = " ".join(t.lower() for t in topics)
    scores: dict[str, int] = {}
    for industry, keywords in _INDUSTRY_MAP.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scores[industry] = score
    if not scores:
        return "technology"
    return max(scores, key=lambda k: scores[k])


# ═══════════════════════════════════════════════════════════════════════════════
# Chat context extraction
# ═══════════════════════════════════════════════════════════════════════════════

def _get_chat_context() -> dict:
    """Return recent chat topics and explained concepts from DB."""
    try:
        from ..utils.db import get_connection
        with get_connection() as conn:
            topic_rows = conn.execute(
                """
                SELECT   topic_hint
                FROM     chat_messages
                WHERE    topic_hint IS NOT NULL
                GROUP BY topic_hint
                ORDER BY MAX(created_at) DESC
                LIMIT    10
                """
            ).fetchall()
            concept_rows = conn.execute(
                """
                SELECT concept
                FROM   concept_memory
                ORDER  BY times_explained DESC, last_explained_at DESC
                LIMIT  12
                """
            ).fetchall()
        return {
            "recent_topics":      [r["topic_hint"] for r in topic_rows],
            "explained_concepts": [r["concept"]    for r in concept_rows],
        }
    except Exception:
        logger.exception("intelligence_service: failed to load chat context")
        return {"recent_topics": [], "explained_concepts": []}


# ═══════════════════════════════════════════════════════════════════════════════
# Personalization context
# ═══════════════════════════════════════════════════════════════════════════════

def _build_intelligence_context(chat_ctx: dict) -> tuple[str, str]:
    """
    Build the personalization block for the prompt and return the inferred industry.

    Returns (context_block: str, industry: str)
    """
    from .recommendation_service import (
        get_top_user_interests,
        get_suppressed_topics,
        get_overall_difficulty_preference,
        get_learning_stage,
    )

    liked       = get_top_user_interests(limit=8)
    suppressed  = get_suppressed_topics(limit=5)
    difficulty  = get_overall_difficulty_preference()
    stage       = get_learning_stage()
    chat_topics = chat_ctx.get("recent_topics",      [])
    concepts    = chat_ctx.get("explained_concepts", [])

    all_topics = [r["topic"] for r in liked] + chat_topics
    industry   = _infer_industry(all_topics)

    lines = [
        f"Industry focus (inferred): {industry}",
        f"Learning stage: {stage}",
        f"Preferred difficulty: {difficulty}",
    ]

    if liked:
        lines.append(f"Positively-rated topics: {', '.join(r['topic'] for r in liked)}")

    if chat_topics:
        lines.append(f"Recently discussed in chat: {', '.join(chat_topics[:6])}")

    if concepts:
        lines.append(
            f"Concepts already explained (build on these, do not re-explain basics): "
            f"{', '.join(concepts[:8])}"
        )

    if suppressed:
        lines.append(f"Avoid entirely: {', '.join(suppressed)}")

    return "\n".join(lines), industry


# ═══════════════════════════════════════════════════════════════════════════════
# Multi-domain search
# ═══════════════════════════════════════════════════════════════════════════════

def _multi_search(interests: str, industry: str) -> list[dict]:
    """
    Retrieve articles for a daily intelligence feed via the retrieval router.

    Routes through domain classification → trusted sources → extract+search
    instead of two generic Tavily search() calls.
    """
    from .retrieval_router import route
    try:
        return route(interests, mode="feed")
    except Exception:
        logger.exception("intelligence_service: retrieval failed for %r", interests)
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# JSON parsing
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_json_response(raw: str) -> dict:
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        raise ValueError(
            f"LLM response could not be parsed as JSON. "
            f"Raw output (first 300 chars): {cleaned[:300]}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Backward-compatibility shim
# ═══════════════════════════════════════════════════════════════════════════════

def _add_compat_fields(feed: dict) -> dict:
    """
    Add news_insight / perspectives / learning_topics / next_step so existing
    digest storage and any callers expecting the old shape still work.
    """
    brief    = feed.get("intelligence_brief", {})
    sections = feed.get("sections",           [])
    track    = feed.get("learning_track",     [])

    if "news_insight" not in feed:
        industry_section = next(
            (s for s in sections if s.get("type") == "industry_news"), {}
        )
        first_item = (industry_section.get("items") or [{}])[0]
        feed["news_insight"] = {
            "title":          brief.get("headline",          "Intelligence Brief"),
            "summary":        brief.get("executive_summary", ""),
            "why_it_matters": first_item.get("why_it_matters", ""),
            "sources":        first_item.get("sources",        []),
        }

    if "perspectives" not in feed:
        feed["perspectives"] = {
            "common_themes":  brief.get("key_signals", [])[:3],
            "synthesis":      brief.get("executive_summary", ""),
            "notable_tension": None,
        }

    if "learning_topics" not in feed:
        feed["learning_topics"] = [
            {
                "title":      t.get("title",      ""),
                "reason":     t.get("reason",     ""),
                "difficulty": t.get("difficulty", "intermediate"),
            }
            for t in track[:4]
        ]

    action_items = feed.get("action_items", [])
    if "next_step" not in feed:
        feed["next_step"] = action_items[0] if action_items else ""

    return feed


# ═══════════════════════════════════════════════════════════════════════════════
# Cache key
# ═══════════════════════════════════════════════════════════════════════════════

def _build_cache_key(interests: str, industry: str, chat_topics: list[str]) -> str:
    from .feed_cache_service import build_cache_key
    from .recommendation_service import (
        get_top_user_interests, get_suppressed_topics,
        get_overall_difficulty_preference, get_learning_stage,
    )
    fingerprint = json.dumps(
        {
            "liked":       sorted(r["topic"] for r in get_top_user_interests(limit=8)),
            "suppressed":  sorted(get_suppressed_topics(limit=5)),
            "difficulty":  get_overall_difficulty_preference(),
            "stage":       get_learning_stage(),
            "industry":    industry,
            "chat_topics": sorted(chat_topics[:5]),
        },
        sort_keys=True,
    )
    return build_cache_key(interests, fingerprint)


# ═══════════════════════════════════════════════════════════════════════════════
# Persistence
# ═══════════════════════════════════════════════════════════════════════════════

def _save_intelligence_feed(
    feed: dict,
    interests: str,
    industry: str,
    source: str = "user",
) -> int:
    from ..utils.db import get_connection
    from datetime import datetime, timezone
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO intelligence_feeds
                (interests, industry, feed_json, source, generated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                interests,
                industry,
                json.dumps(feed),
                source,
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
    return cur.lastrowid


def get_recent_intelligence_feeds(limit: int = 10) -> list[dict]:
    """Return the N most recent intelligence feeds, newest first."""
    try:
        from ..utils.db import get_connection
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, interests, industry, source, generated_at
                FROM   intelligence_feeds
                ORDER  BY generated_at DESC
                LIMIT  ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        logger.exception("intelligence_service: failed to list feeds")
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def generate_intelligence_feed(interests: str) -> dict:
    """
    Generate a personalized daily intelligence brief for *interests*.

    Pipeline
    --------
    1. Pull chat context (recent topics + explained concepts).
    2. Build enriched personalization block + infer industry.
    3. Check cache — return immediately on hit.
    4. Multi-domain search (interests + industry trends).
    5. Rank and truncate to top-8 articles.
    6. Synthesize via Groq with the intelligence prompt.
    7. Add backward-compat fields (news_insight, learning_topics, etc.).
    8. Cache and persist.

    Return shape
    ------------
    The dict includes both the new intelligence fields AND the legacy
    news_insight / perspectives / learning_topics / next_step fields so
    existing digest storage and API consumers keep working.
    """
    from .feed_cache_service  import get_cached_feed, cache_feed
    from .source_ranker        import rank_articles
    from .source_analyzer      import analyze_sources, format_analysis_for_prompt
    from .grok_service         import ask_grok
    from ..prompts.intelligence_prompt import build_intelligence_prompt

    chat_ctx = _get_chat_context()
    intelligence_ctx, industry = _build_intelligence_context(chat_ctx)

    cache_key = _build_cache_key(
        interests, industry, chat_ctx.get("recent_topics", [])
    )
    cached = get_cached_feed(cache_key)
    if cached is not None:
        return cached

    # Multi-domain search and ranking
    raw_articles = _multi_search(interests, industry)
    articles     = rank_articles(raw_articles, query=interests, top_n=8, mode="feed")

    if not articles:
        raise ValueError(f"No articles found for interests: {interests!r}")

    analysis        = analyze_sources(articles, query=interests)
    source_analysis = format_analysis_for_prompt(analysis)
    formatted_articles = "\n\n".join(
        f"{i}. {a['title']}\n   URL: {a['url']}\n   {a['content']}"
        for i, a in enumerate(articles, 1)
    )

    prompt = build_intelligence_prompt(
        intelligence_context = intelligence_ctx,
        industry             = industry,
        source_count         = analysis["source_count"],
        source_analysis      = source_analysis,
        articles             = formatted_articles,
        interests            = interests,
    )

    raw  = ask_grok(prompt)
    feed = _parse_json_response(raw)
    feed = _add_compat_fields(feed)

    cache_feed(cache_key, interests, feed)

    try:
        _save_intelligence_feed(feed, interests, industry)
    except Exception:
        logger.exception("intelligence_service: persistence failed (non-fatal)")

    return feed
