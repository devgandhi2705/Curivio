"""
Information Diversity Scorer  (Phase 9.3.2B)

Computes a score adjustment based on how much NEW INFORMATION a candidate
article contributes relative to what is already selected.

Design principle
----------------
Diversity of knowledge, not diversity of publishers.
Same publisher is fine when articles cover different concepts.
Different publishers are penalised when they cover the same concepts.

Signals
-------
Signal               Condition                           Adjustment
------               ---------                           ----------
Concept novelty      Max pairwise Jaccard < 0.15         +0.08  (highly novel)
Concept novelty      Max pairwise Jaccard 0.15–0.30      +0.04  (mostly novel)
Concept novelty      Max pairwise Jaccard 0.30–0.45      +0.00  (neutral)
Concept novelty      Max pairwise Jaccard 0.45–0.60      -0.05  (significant overlap)
Concept novelty      Max pairwise Jaccard > 0.60         -0.10  (near-duplicate concepts)
Perspective angle    New editorial angle                 +0.03
Perspective angle    3rd+ same editorial angle           -0.04

Output: clamped to [-0.15, +0.10]

Examples
--------
GeeksForGeeks — Dynamic Programming   ┐  concept tokens disjoint
GeeksForGeeks — Segment Trees         ├→ all get concept novelty bonuses
GeeksForGeeks — Fenwick Trees         ┘  publisher identity irrelevant

3 articles on "dynamic programming intro" from 3 publishers
→ 2nd and 3rd get concept novelty penalty (high title/entity overlap)

Public API
----------
diversity_adjustment(article, selected_articles) -> float
"""

from __future__ import annotations

import re


# ── Concept extraction ────────────────────────────────────────────────────────

_CONCEPT_STOP = frozenset(
    "the and for are was were been have has had its that this with from about"
    " will can into more than when then they their there which would could"
    " should also just very most some over under after before between through"
    " during while since until against among each other within without across"
    " how why what who where new get use make take give find know think see"
    " come want look need feel try ask tell seem help show call keep put run"
    " may might must shall let did does did been".split()
)


def _concept_tokens(article: dict) -> frozenset:
    """
    Extract concept tokens from title + named entities (source_intelligence layer).
    Title tokens are high signal; important_entities add named-concept precision.
    """
    tokens: set[str] = set()

    title_words = re.findall(r"[a-z]{3,}", (article.get("title") or "").lower())
    tokens.update(w for w in title_words if w not in _CONCEPT_STOP)

    for ent in (article.get("important_entities") or []):
        tokens.update(
            w.lower() for w in re.findall(r"[a-z]{3,}", ent.lower())
            if w.lower() not in _CONCEPT_STOP
        )

    return frozenset(tokens)


def _max_concept_overlap(candidate: frozenset, selected: list[dict]) -> float:
    """
    Max pairwise Jaccard similarity between the candidate's concept tokens
    and each already-selected article's concept tokens.

    Returns 0.0 when nothing is selected or candidate has no tokens.
    """
    if not candidate or not selected:
        return 0.0

    max_sim = 0.0
    for s in selected:
        s_tokens = _concept_tokens(s)
        if not s_tokens:
            continue
        union = len(candidate | s_tokens)
        if union == 0:
            continue
        sim = len(candidate & s_tokens) / union
        if sim > max_sim:
            max_sim = sim
            if max_sim >= 0.80:   # early exit — can't get worse
                break

    return max_sim


# ── Public API ────────────────────────────────────────────────────────────────

def diversity_adjustment(
    article:  dict,
    selected: list[dict],
) -> float:
    """
    Score delta in [-0.15, +0.10] reflecting information diversity contribution.

    Requires article["_perspective"] to be set before this call.
    article["important_entities"] is used when available (set by
    source_intelligence_service.enrich_articles() before ranking).
    """
    if not selected:
        return 0.0

    adj = 0.0

    # ── Concept novelty (primary signal) ─────────────────────────────────────
    # Measures information overlap with already-selected articles.
    # Same publisher is irrelevant; same concept set is what matters.
    cand_tokens  = _concept_tokens(article)
    max_overlap  = _max_concept_overlap(cand_tokens, selected)

    if max_overlap < 0.15:
        adj += 0.08    # highly novel — brings mostly new concepts
    elif max_overlap < 0.30:
        adj += 0.04    # mostly novel
    elif max_overlap < 0.45:
        adj += 0.00    # neutral zone — some overlap, some new
    elif max_overlap < 0.60:
        adj -= 0.05    # significant concept overlap with an existing article
    else:
        adj -= 0.10    # near-duplicate concept coverage

    # ── Perspective / editorial angle (secondary signal) ──────────────────────
    perspective = article.get("_perspective") or ""
    if perspective:
        same_persp = sum(1 for s in selected if (s.get("_perspective") or "") == perspective)
        if same_persp == 0:
            adj += 0.03    # new editorial angle → mild bonus
        elif same_persp >= 2:
            adj -= 0.04    # 3rd+ same angle → mild penalty

    return max(-0.15, min(0.10, round(adj, 3)))
