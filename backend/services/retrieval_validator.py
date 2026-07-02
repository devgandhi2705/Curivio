"""
Retrieval Validator

Heuristic relevance filter applied to retrieved articles before feed generation.
Runs before ranking (or the LLM prompt in the project pipeline).

Scores three dimensions on [0, 1] each:
  intent_score      — alignment with learner's domain, goal, and current focus
  continuity_score  — alignment with current learning progression
  relevance_score   — general keyword overlap with project space

All scoring is token-overlap based — no extra LLM calls.
One LLM call processes 10-20 articles; heuristic costs ~0ms per article.

Public API
----------
validate(article, intent_profile, knowledge_state, keywords)
    -> {intent_score, continuity_score, relevance_score, rejection_reason}

filter_articles(articles, intent_profile, knowledge_state,
                keywords, mode="core")
    -> list[dict]   (only passing articles)
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ── Thresholds ─────────────────────────────────────────────────────────────────
# Generous defaults — validator catches obvious mismatches, not borderline content.
# The LLM prompt handles nuanced filtering; validator removes clear garbage.
_THRESHOLDS = {
    "core": {
        "intent_alignment":  0.02,   # any 1 token overlap with persona profile — blocks zero-overlap drift
        "intent_score":      0.06,
        "continuity_score":  0.04,
        "relevance_score":   0.04,
        "repetition_limit":  0.70,   # fraction of title tokens already in covered_keywords
    },
    "serendipity": {
        "intent_alignment":  0.00,   # serendipity is intentionally off-persona — alignment exempt
        "intent_score":      0.04,   # lower — adjacent/surprising territory is expected
        "continuity_score":  0.00,   # serendipity is intentionally off-progression
        "relevance_score":   0.03,
        "repetition_limit":  0.80,
    },
}

_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "how", "why", "what", "when", "where", "who", "is", "are",
    "was", "were", "has", "have", "had", "its", "as", "by", "from", "this",
    "that", "they", "their", "into", "not", "does", "did", "its", "about",
    "will", "can", "could", "would", "should", "may", "might", "new", "says",
})


# ── Public API ─────────────────────────────────────────────────────────────────

def validate(
    article:         dict,
    intent_profile:  dict | None,
    knowledge_state: dict | None,
    keywords:            list[str],
    project_name:        str = "",
    project_description: str = "",
) -> dict:
    """
    Score one article on three dimensions.
    Returns {intent_score, continuity_score, relevance_score, score, rejection_reason}.
    rejection_reason is empty string when article passes all thresholds.
    score = min(intent, continuity, relevance) — the binding constraint.
    """
    article_tokens = _tokenize(
        (article.get("title") or "") + " " + (article.get("content") or "")[:600]
    )
    title_tokens = _tokenize(article.get("title") or "")

    intent_tokens     = _build_intent_terms(
        intent_profile, keywords, project_name, project_description
    )
    continuity_tokens = _build_continuity_terms(knowledge_state)
    # Day-1 / legacy-project fallback: no learning history yet.
    # Score continuity against intent+description anchor so articles are judged
    # against project domain rather than getting a free pass.
    if not continuity_tokens:
        continuity_tokens = intent_tokens
    relevance_tokens  = _build_relevance_terms(keywords)
    covered_tokens    = _build_covered_terms(knowledge_state)
    alignment_tokens  = _build_intent_alignment_terms(intent_profile, keywords)

    intent_score      = _overlap(article_tokens, intent_tokens)
    continuity_score  = _overlap(article_tokens, continuity_tokens)
    relevance_score   = _overlap(article_tokens, relevance_tokens)
    repetition_frac   = _overlap(title_tokens,   covered_tokens) if title_tokens else 0.0
    # intent_alignment: 1.0 when no profile (no constraint), else persona-focused overlap
    intent_alignment  = _overlap(article_tokens, alignment_tokens) if alignment_tokens else 1.0
    combined_score    = round(min(intent_score, continuity_score, relevance_score), 3)

    return {
        "intent_alignment_score": round(intent_alignment,  3),
        "intent_score":           round(intent_score,      3),
        "continuity_score":       round(continuity_score,  3),
        "relevance_score":        round(relevance_score,   3),
        "_repetition_frac":       round(repetition_frac,   3),
        "score":                  combined_score,
        "rejection_reason":       "",   # populated by filter_articles
    }


def _run_filter_pass(
    articles:        list[dict],
    intent_profile:  dict | None,
    knowledge_state: dict | None,
    keywords:            list[str],
    project_id:          str,
    project_name:        str,
    project_description: str,
    query_label:         str,
    thresholds:          dict,
) -> list[dict]:
    passing: list[dict] = []
    for article in articles:
        result = validate(
            article, intent_profile, knowledge_state, keywords,
            project_name=project_name, project_description=project_description,
        )
        reason = _rejection_reason(result, thresholds)
        title  = (article.get("title") or "")[:60]
        if reason:
            logger.info(
                "[VALIDATOR] project_id=%s query=%r article=%r score=%.2f reason=%s",
                project_id, query_label, title, result["score"], reason,
            )
        else:
            logger.debug(
                "[VALIDATOR] project_id=%s query=%r article=%r score=%.2f reason=PASS",
                project_id, query_label, title, result["score"],
            )
            article["_retrieval_score"] = result["score"]
            passing.append(article)
    return passing


def filter_articles(
    articles:        list[dict],
    intent_profile:  dict | None,
    knowledge_state: dict | None,
    keywords:            list[str],
    mode:                str = "core",
    project_id:          str = "",
    project_name:        str = "",
    project_description: str = "",
    min_required:        int = 0,
) -> list[dict]:
    """
    Return only articles that pass all threshold checks.
    mode = "core" | "serendipity"  — serendipity uses softer thresholds.
    If min_required > 0 and fewer articles pass than needed, retries once with
    halved alignment/score thresholds and a raised repetition_limit.
    """
    t = _THRESHOLDS.get(mode, _THRESHOLDS["core"])

    kw_sample   = ", ".join(keywords[:4]) if keywords else ""
    query_label = f"{project_name} [{kw_sample}]" if project_name else kw_sample or "(no anchor)"

    passing = _run_filter_pass(
        articles, intent_profile, knowledge_state, keywords,
        project_id, project_name, project_description, query_label, t,
    )

    if min_required > 0 and len(passing) < min_required:
        t_relaxed = {
            "intent_alignment":  t["intent_alignment"]  / 2,
            "intent_score":      t["intent_score"]      / 2,
            "continuity_score":  t["continuity_score"]  / 2,
            "relevance_score":   t["relevance_score"]   / 2,
            "repetition_limit":  min(t["repetition_limit"] + 0.20, 0.95),
        }
        logger.warning(
            "[VALIDATOR] project_id=%s mode=%s: %d/%d passed (need %d) — "
            "retrying with relaxed thresholds",
            project_id, mode, len(passing), len(articles), min_required,
        )
        passing = _run_filter_pass(
            articles, intent_profile, knowledge_state, keywords,
            project_id, project_name, project_description, query_label, t_relaxed,
        )

    return passing


# ── Scoring helpers ────────────────────────────────────────────────────────────

def _rejection_reason(result: dict, t: dict) -> str:
    if result["intent_alignment_score"] < t["intent_alignment"]:
        return f"persona drift (alignment={result['intent_alignment_score']:.2f} < {t['intent_alignment']})"
    if result["intent_score"] < t["intent_score"]:
        return f"intent mismatch (score={result['intent_score']:.2f} < {t['intent_score']})"
    if result["continuity_score"] < t["continuity_score"]:
        return f"off progression (score={result['continuity_score']:.2f} < {t['continuity_score']})"
    if result["relevance_score"] < t["relevance_score"]:
        return f"off topic (score={result['relevance_score']:.2f} < {t['relevance_score']})"
    if result["_repetition_frac"] >= t["repetition_limit"]:
        return f"repetitive (frac={result['_repetition_frac']:.2f} >= {t['repetition_limit']})"
    return ""


def _overlap(article_tokens: frozenset, ref_tokens: frozenset) -> float:
    """Soft Jaccard: intersection / ref_size."""
    if not ref_tokens:
        return 0.0
    return len(article_tokens & ref_tokens) / len(ref_tokens)


# ── Term set builders ──────────────────────────────────────────────────────────

def _build_intent_terms(
    intent_profile:      dict | None,
    keywords:            list[str],
    project_name:        str = "",
    project_description: str = "",
) -> frozenset:
    # Raw title + description first — richest, most literal signal.
    texts: list[str] = []
    if project_name:
        texts.append(project_name)
    if project_description:
        texts.append(project_description)
    texts.extend(keywords)
    if intent_profile:
        for field in ("industry_context", "goal", "primary_focus", "persona", "intent_summary", "search_lens"):
            val = intent_profile.get(field) or ""
            if val:
                texts.append(val)
    return _tokenize(" ".join(texts))


def _build_intent_alignment_terms(
    intent_profile: dict | None,
    keywords:       list[str],  # accepted for API consistency; intentionally unused
) -> frozenset:
    """Persona-specific reference terms for intent_alignment_score.

    Uses ONLY primary_focus + goal + search_lens from the intent profile —
    not keywords or project_name. Keywords contain topic terms shared across
    personas (e.g. "globalization"), which would inflate the score and prevent
    detection of clear persona drift (CBSE notes for a Startup Founder).

    Articles that share even one token with the persona's core profile pass.
    Articles with zero overlap are flagged as persona drift.

    Returns empty frozenset when no profile is available — caller treats this as
    no constraint (score defaults to 1.0 = pass-through).
    """
    if not intent_profile:
        return frozenset()
    texts: list[str] = []
    for field in ("primary_focus", "goal", "search_lens"):
        val = intent_profile.get(field) or ""
        if val:
            texts.append(val)
    return _tokenize(" ".join(texts))


def _build_continuity_terms(knowledge_state: dict | None) -> frozenset:
    texts: list[str] = []
    if knowledge_state:
        texts.extend(knowledge_state.get("active_topics",  []))
        texts.extend(knowledge_state.get("recent_topics",  []))
        texts.extend(knowledge_state.get("knowledge_gaps", []))
    return _tokenize(" ".join(texts))


def _build_relevance_terms(keywords: list[str]) -> frozenset:
    return _tokenize(" ".join(keywords))


def _build_covered_terms(knowledge_state: dict | None) -> frozenset:
    if not knowledge_state:
        return frozenset()
    texts: list[str] = []
    texts.extend(knowledge_state.get("covered_topics",   []))
    texts.extend(knowledge_state.get("covered_keywords", []))
    return _tokenize(" ".join(texts))


# ── Tokenizer ──────────────────────────────────────────────────────────────────

def _tokenize(text: str) -> frozenset:
    words = re.findall(r"[a-z]{3,}", text.lower())
    return frozenset(w for w in words if w not in _STOPWORDS)
