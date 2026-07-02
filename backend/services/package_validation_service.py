"""
Phase 9.3.4F — Package Validation Service

Cross-batch validation & grounding integrity for multi-call generation.
All audit functions are read-only — they never modify the package.

Public surface:
    DuplicateAudit       — card-level duplicate detection result
    NarrativeAudit       — frame diversity + difficulty consistency
    GroundingAudit       — primary URL validity and uniqueness
    CuriosityAudit       — curiosity cards' relevance to learning journey
    SynthesisAudit       — package_headline/thread/action_item reference check
    PackageHealthReport  — aggregated 0-10 health score
    validate_package()   — run all audits, return PackageHealthReport
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ── Audit thresholds ──────────────────────────────────────────────────────────

_DUPLICATE_THRESHOLD = 0.55   # title+summary Jaccard overlap to flag as duplicate
_DOMINANCE_THRESHOLD = 0.60   # max fraction of cards sharing one narrative frame
_MIN_CONTENT_WORD_LEN = 4     # minimum chars for a word to count as content-bearing


# ── Audit result dataclasses ──────────────────────────────────────────────────

@dataclass
class DuplicateAudit:
    duplicate_count: int
    duplicate_pairs: list[tuple[str, str, float]]   # (title_a, title_b, overlap)
    score:           float                           # 0-2


@dataclass
class NarrativeAudit:
    frame_counts:       dict[str, int]
    dominant_frame:     str | None
    frame_diversity_ok: bool
    difficulty_ok:      bool
    score:              float   # 0-2


@dataclass
class GroundingAudit:
    fabricated_count:        int
    duplicate_primary_count: int
    fabricated_urls:         list[str]
    score:                   float   # 0-2


@dataclass
class CuriosityAudit:
    curiosity_count:  int
    relevant_count:   int
    irrelevant_topics: list[str]
    score:            float   # 0-2


@dataclass
class SynthesisAudit:
    headline_ok: bool
    thread_ok:   bool
    action_ok:   bool
    score:       float   # 0-2


@dataclass
class PackageHealthReport:
    grounding_score: float
    narrative_score: float
    dedup_score:     float
    curiosity_score: float
    synthesis_score: float
    overall_score:   float
    status:          str     # "HEALTHY", "WARNING", "FAIL"
    duplicate_audit: DuplicateAudit
    narrative_audit: NarrativeAudit
    grounding_audit: GroundingAudit
    curiosity_audit: CuriosityAudit
    synthesis_audit: SynthesisAudit


# ── Helpers ───────────────────────────────────────────────────────────────────

def _content_words(text: str) -> set[str]:
    """Return set of lowercase, punctuation-stripped words >= _MIN_CONTENT_WORD_LEN chars."""
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    return {w for w in cleaned.split() if len(w) >= _MIN_CONTENT_WORD_LEN}


def _any_word_in(candidate_text: str, reference_words: set[str]) -> bool:
    """True if any content word from candidate_text appears in reference_words."""
    return bool(_content_words(candidate_text) & reference_words)


# ── Audit functions ───────────────────────────────────────────────────────────

def audit_duplicate_concepts(cards: list[dict]) -> DuplicateAudit:
    """
    Find card pairs with substantially overlapping titles and summaries.
    Reuses similarity_service.token_overlap (Jaccard on acronym-expanded tokens).
    """
    from .similarity_service import token_overlap

    titles    = [(c.get("title") or "") for c in cards]
    summaries = [(c.get("summary") or "") for c in cards]
    pairs: list[tuple[str, str, float]] = []

    for i in range(len(cards)):
        for j in range(i + 1, len(cards)):
            t_overlap = token_overlap(titles[i], titles[j])
            s_overlap = token_overlap(summaries[i], summaries[j])
            combined  = 0.5 * t_overlap + 0.5 * s_overlap
            if combined >= _DUPLICATE_THRESHOLD:
                pairs.append((titles[i], titles[j], round(combined, 3)))

    dup_count = len(pairs)
    score     = 2.0 if dup_count == 0 else (1.0 if dup_count <= 2 else 0.0)
    return DuplicateAudit(duplicate_count=dup_count, duplicate_pairs=pairs, score=score)


def audit_narrative_consistency(cards: list[dict], difficulty: str) -> NarrativeAudit:
    """
    Check frame diversity (no single frame dominating) and difficulty consistency.
    """
    frame_counts: dict[str, int] = {}
    for c in cards:
        f = (c.get("narrative_frame") or "").strip()
        if f:
            frame_counts[f] = frame_counts.get(f, 0) + 1

    total         = max(1, len(cards))
    dominant      = max(frame_counts, key=frame_counts.get) if frame_counts else None
    dominant_pct  = (frame_counts.get(dominant, 0) / total) if dominant else 0.0
    diversity_ok  = dominant_pct < _DOMINANCE_THRESHOLD

    # Difficulty: all cards should carry the package-level difficulty
    card_difficulties = [c.get("difficulty", "").strip() for c in cards if c.get("difficulty")]
    difficulty_ok     = all(d == difficulty for d in card_difficulties) if card_difficulties else True

    score = (
        2.0 if (diversity_ok and difficulty_ok)
        else 1.0 if (diversity_ok or difficulty_ok)
        else 0.0
    )
    return NarrativeAudit(
        frame_counts       = frame_counts,
        dominant_frame     = dominant,
        frame_diversity_ok = diversity_ok,
        difficulty_ok      = difficulty_ok,
        score              = score,
    )


def audit_grounding(raw_package: dict, allowed_urls: frozenset) -> GroundingAudit:
    """
    Check primary source URLs against the retrieval set.
    Pure audit — does NOT mutate the package.
    Checks: URL in allowed set (A-D), primary URL uniqueness (E).
    """
    all_cards       = raw_package.get("insights", []) + raw_package.get("curiosity_insights", [])
    fabricated_urls: list[str] = []
    seen_primary:    list[str] = []
    dup_primary                = 0

    for card in all_cards:
        url = ((card.get("primary_source") or {}).get("url") or "").strip()
        if not url:
            continue
        if url not in allowed_urls:
            fabricated_urls.append(url)
        if url in seen_primary:
            dup_primary += 1
        else:
            seen_primary.append(url)

    f_count = len(fabricated_urls)
    score   = (
        2.0 if (f_count == 0 and dup_primary == 0)
        else 1.0 if (f_count <= 1 and dup_primary <= 1)
        else 0.0
    )
    return GroundingAudit(
        fabricated_count        = f_count,
        duplicate_primary_count = dup_primary,
        fabricated_urls         = fabricated_urls,
        score                   = score,
    )


def audit_curiosity_relevance(
    curiosity_cards: list[dict],
    learning_topics: list[str],
    keywords:        list[str],
    project_name:    str,
) -> CuriosityAudit:
    """
    Check curiosity cards connect to the learner's journey.
    A card is relevant if any of its title/summary/category content words
    overlap with the learning topics, keywords, or project name.
    """
    if not curiosity_cards:
        return CuriosityAudit(curiosity_count=0, relevant_count=0, irrelevant_topics=[], score=2.0)

    reference_text  = " ".join(learning_topics + keywords + [project_name])
    reference_words = _content_words(reference_text)

    relevant_count   = 0
    irrelevant_topics: list[str] = []

    for card in curiosity_cards:
        card_text = f"{card.get('title', '')} {card.get('summary', '')} {card.get('category', '')}"
        if _any_word_in(card_text, reference_words):
            relevant_count += 1
        else:
            irrelevant_topics.append(card.get("title") or "?")

    total          = len(curiosity_cards)
    relevance_rate = relevant_count / total
    score          = 2.0 if relevance_rate >= 0.8 else (1.0 if relevance_rate >= 0.5 else 0.0)
    return CuriosityAudit(
        curiosity_count   = total,
        relevant_count    = relevant_count,
        irrelevant_topics = irrelevant_topics,
        score             = score,
    )


def audit_synthesis_quality(
    headline:        str,
    learning_thread: str,
    action_item:     str,
    cards:           list[dict],
) -> SynthesisAudit:
    """
    Check that synthesis fields reference actual generated card content.
    A field passes if it contains at least one content word from any card title or category.
    """
    card_words: set[str] = set()
    for c in cards:
        card_words |= _content_words(c.get("title", ""))
        card_words |= _content_words(c.get("category", ""))
        card_words |= _content_words(c.get("summary", ""))

    headline_ok = bool(headline)  and _any_word_in(headline,        card_words)
    thread_ok   = bool(learning_thread) and _any_word_in(learning_thread, card_words)
    action_ok   = bool(action_item) and _any_word_in(action_item,   card_words)

    score = round(sum([headline_ok, thread_ok, action_ok]) * (2.0 / 3), 2)
    return SynthesisAudit(
        headline_ok = headline_ok,
        thread_ok   = thread_ok,
        action_ok   = action_ok,
        score       = score,
    )


# ── Main entry point ──────────────────────────────────────────────────────────

def validate_package(
    raw_package:    dict,
    allowed_urls:   frozenset,
    keywords:       list[str],
    learning_topics: list[str],
    difficulty:     str,
    project_name:   str,
) -> PackageHealthReport:
    """
    Run all five audits and return a PackageHealthReport.
    Never modifies raw_package. Safe to call on any merged package dict.
    """
    all_cards       = raw_package.get("insights", []) + raw_package.get("curiosity_insights", [])
    curiosity_cards = raw_package.get("curiosity_insights", [])

    dup_audit  = audit_duplicate_concepts(all_cards)
    narr_audit = audit_narrative_consistency(all_cards, difficulty)
    gnd_audit  = audit_grounding(raw_package, allowed_urls)
    cur_audit  = audit_curiosity_relevance(curiosity_cards, learning_topics, keywords, project_name)
    syn_audit  = audit_synthesis_quality(
        raw_package.get("package_headline", ""),
        raw_package.get("learning_thread",  ""),
        raw_package.get("action_item",      ""),
        all_cards,
    )

    total  = gnd_audit.score + narr_audit.score + dup_audit.score + cur_audit.score + syn_audit.score
    status = "HEALTHY" if total >= 8.0 else ("WARNING" if total >= 6.0 else "FAIL")

    return PackageHealthReport(
        grounding_score = gnd_audit.score,
        narrative_score = narr_audit.score,
        dedup_score     = dup_audit.score,
        curiosity_score = cur_audit.score,
        synthesis_score = syn_audit.score,
        overall_score   = round(total, 2),
        status          = status,
        duplicate_audit = dup_audit,
        narrative_audit = narr_audit,
        grounding_audit = gnd_audit,
        curiosity_audit = cur_audit,
        synthesis_audit = syn_audit,
    )
