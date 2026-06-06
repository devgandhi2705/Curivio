import json
import re

from .grok_service import ask_grok
from .recommendation_service import (
    get_top_user_interests,
    get_suppressed_topics,
    get_overall_difficulty_preference,
    get_learning_stage,
    get_frequently_seen_topics,
)
from .feed_cache_service import build_cache_key, get_cached_feed, cache_feed
from .source_ranker import rank_articles
from .source_analyzer import analyze_sources, format_analysis_for_prompt
from .digest_storage_service import list_digests
from .topic_cluster import assign_category, format_category_context
from ..prompts.learning_prompt import build_learning_prompt


def _get_recent_news_titles(limit: int = 5) -> list[str]:
    """
    Return the news_title from the last ``limit`` stored digests.

    Used to inject a freshness signal into the prompt so the LLM avoids
    regenerating news insights that are semantically similar to recent ones.
    Returns an empty list on any DB error to avoid blocking feed generation.
    """
    try:
        return [d["news_title"] for d in list_digests(limit=limit) if d.get("news_title")]
    except Exception:
        return []


def _format_articles(articles: list[dict]) -> str:
    lines = []
    for i, a in enumerate(articles, start=1):
        lines.append(f"{i}. {a['title']}\n   URL: {a['url']}\n   {a['content']}")
    return "\n\n".join(lines)


# Maps each learning stage to a plain-English instruction for the prompt.
_STAGE_GUIDANCE = {
    "early": (
        "User is early in their learning journey. "
        "Use 2 beginner + 1 intermediate + 1 advanced topic. "
        "Prioritize foundational concepts and practical entry points."
    ),
    "developing": (
        "User is progressing and ready to go deeper. "
        "Use 1 beginner + 2 intermediate + 1 advanced topic. "
        "Connect new concepts to areas they already know."
    ),
    "proficient": (
        "User is experienced. Challenge them. "
        "Use 1 beginner anchor + 1 intermediate bridge + 2 advanced topics. "
        "The beginner topic should reinforce a fundamental that underpins the advanced material."
    ),
}


def _build_memory_context() -> str:
    """
    Assemble a structured learning-state block to inject into the prompt.

    Sections included (each omitted if empty/not yet applicable):
      - Learning stage and difficulty distribution guidance
      - Preferred difficulty level
      - Topics the user has engaged with positively (reference and build on these)
      - Topics to avoid (user disliked)
      - Frequently seen topics (already familiar — enforce freshness)
    """
    liked         = get_top_user_interests(limit=5)
    suppressed    = get_suppressed_topics(limit=5)
    difficulty    = get_overall_difficulty_preference()
    stage         = get_learning_stage()
    frequent      = get_frequently_seen_topics(threshold=3)

    recent_news = _get_recent_news_titles()

    if not liked and not suppressed:
        base = (
            "No prior history — this is a fresh session.\n"
            "Treat the user as an intermediate engineer and adapt to their interests below."
        )
        if recent_news:
            base += (
                f"\nRecent news already covered (do NOT repeat these angles or near-identical "
                f"framings): {'; '.join(recent_news)}"
            )
        return base

    lines = [
        f"Learning stage: {stage}",
        f"Preferred difficulty: {difficulty}",
        f"Stage guidance: {_STAGE_GUIDANCE[stage]}",
    ]

    if liked:
        liked_names = ", ".join(r["topic"] for r in liked)
        lines.append(f"Topics engaged with positively: {liked_names}")
        category_ctx = format_category_context([assign_category(r["topic"]) for r in liked])
        if category_ctx:
            lines.append(category_ctx)

    if suppressed:
        lines.append(f"Topics to avoid (user disliked): {', '.join(suppressed)}")

    if frequent:
        lines.append(
            f"Frequently seen topics (already familiar — do NOT repeat as primary "
            f"recommendations; you may reference them as prerequisites): {', '.join(frequent)}"
        )

    if recent_news:
        lines.append(
            f"Recent news already covered (do NOT repeat these angles or near-identical "
            f"framings): {'; '.join(recent_news)}"
        )

    return "\n".join(lines)


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


def _build_memory_fingerprint() -> str:
    """
    Deterministic snapshot of the preference signals that affect the LLM prompt.

    We sort every list so the fingerprint is stable regardless of DB row order.
    Only fields that actually change the generated output are included — adding
    cosmetic fields here would cause unnecessary cache misses.
    """
    return json.dumps(
        {
            "liked":      sorted(r["topic"] for r in get_top_user_interests(limit=5)),
            "suppressed": sorted(get_suppressed_topics(limit=5)),
            "difficulty": get_overall_difficulty_preference(),
            "stage":      get_learning_stage(),
        },
        sort_keys=True,
    )


def generate_learning_feed(interests: str) -> dict:
    """
    Return a personalised learning feed for the given interests.

    Cache behaviour
    ---------------
    1. Build a cache key from normalised interests + current memory fingerprint.
    2. If a fresh (<FEED_CACHE_TTL_HOURS old) entry exists → return it directly,
       avoiding both a Tavily search and a Groq call.
    3. On a miss → run the full pipeline, store the result, then return it.
    """
    fingerprint = _build_memory_fingerprint()
    cache_key   = build_cache_key(interests, fingerprint)

    cached = get_cached_feed(cache_key)
    if cached is not None:
        return cached

    # Cache miss — run the full pipeline
    from .retrieval_router import route
    raw_articles    = route(interests, mode="feed")
    articles        = rank_articles(raw_articles, query=interests, top_n=5, mode="feed")
    analysis        = analyze_sources(articles, query=interests)
    source_analysis = format_analysis_for_prompt(analysis)
    formatted       = _format_articles(articles)
    memory_context  = _build_memory_context()

    prompt = build_learning_prompt(
        interests=interests,
        articles=formatted,
        memory_context=memory_context,
        source_analysis=source_analysis,
        source_count=analysis["source_count"],
    )

    raw  = ask_grok(prompt)
    feed = _parse_json_response(raw)

    cache_feed(cache_key, interests, feed)
    return feed
