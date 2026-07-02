"""
Source Intelligence Service — Phase 9.3.1

Deterministic enrichment of article dicts with structured intelligence signals.
No LLM calls. Regex and pattern matching only.

Insertion point: before source_ranker.rank_articles() — enrichment runs first so
signal_density / source_strength are available to the ranker's scoring terms.
Called via enrich_articles() which mutates articles in-place.

Fields added per article (all optional — empty string / empty list / 0.0 on failure):
  main_claim         str        — one sentence: what is this source asserting?
  key_evidence       list[str]  — sentences from content containing quantified facts
  important_numbers  list[str]  — number/percentage/scale strings extracted
  important_entities list[str]  — named entity strings (orgs, people, products)
  important_dates    list[str]  — date references (year, month+year, quarter)
  implications       list[str]  — forward-looking sentences
  risks              list[str]  — risk/concern/threat sentences
  contradictions     list[str]  — contrastive sentences (however, despite, ...)
  signal_density     float      — 0–1 richness score; higher = more grounded
  source_strength    float      — 0–1 quality tier derived from source_type

signal_density formula documented in _compute_signal_density().
Backward compatible: callers ignoring new fields continue to work unchanged.

Public API
----------
enrich_articles(articles: list[dict]) -> None
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


# ── Number patterns ────────────────────────────────────────────────────────────
# Captures meaningful quantitative strings: percentages, currencies, ML units, etc.

_NUMBER_RE = re.compile(
    r"(?:[\$€£¥])?"
    r"\d[\d,\.]*"
    r"(?:\s*(?:%|percent|pct"
    r"|billion|million|trillion|thousand|bn|mn"
    r"|bps|bp|pp|ppt"
    r"|tokens?|parameters?|params?"
    r"|[mgkt]b\b|ms\b"
    r"|years?|months?|weeks?|days?|hours?"
    r"))?",
    re.IGNORECASE,
)

# ── Date patterns ──────────────────────────────────────────────────────────────

_MONTH_YEAR_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)(?:\s+\d{1,2})?(?:,?\s*\d{4})?\b",
    re.IGNORECASE,
)

_QUARTER_RE = re.compile(r"\bQ[1-4]\s*(?:20[12]\d)?\b", re.IGNORECASE)

_YEAR_RE = re.compile(r"\b(20[12]\d|19[89]\d)\b")

# ── Entity patterns ────────────────────────────────────────────────────────────
# Two or more consecutive capitalized words (simple NER proxy).

_ENTITY_RE = re.compile(r"\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){1,4})\b")

_ENTITY_STOPWORDS: frozenset[str] = frozenset({
    "The", "This", "That", "These", "Those", "A", "An",
    "In", "On", "At", "By", "For", "Of", "With", "And", "Or",
    "New", "First", "Last", "Next", "Top", "Best", "Big",
    "Most", "More", "Some", "Many", "Such", "Both", "Each",
    "When", "Where", "While", "How", "Why", "What", "Who",
    "After", "Before", "During", "Since", "Until", "From",
})

# ── Claim verb patterns ────────────────────────────────────────────────────────

_CLAIM_VERB_RE = re.compile(
    r"\b(is|are|was|were|has|have|had|will|shows?|reveals?|finds?|found|"
    r"reports?|announces?|launches?|rises?|falls?|grows?|drops?|hits?|"
    r"reaches?|surpasses?|reduces?|increases?|decreases?|introduces?|"
    r"expands?|cuts?|raises?|builds?|creates?|releases?|exceeds?|"
    r"could|would|may|might|should)\b",
    re.IGNORECASE,
)

# ── Sentence-type detectors ────────────────────────────────────────────────────

_FORWARD_WORDS_RE = re.compile(
    r"\b(will|could|would|may|might|is expected|are expected|"
    r"likely|forecast|projected|aims?|means|signals?|suggests?|"
    r"indicates?|implies?|poised|set to|on track)\b",
    re.IGNORECASE,
)

_RISK_WORDS_RE = re.compile(
    r"\b(risk|risks|concern|concerns|threat|threats|danger|dangers|"
    r"failure|failures|challenge|challenges|vulnerability|vulnerabilities|"
    r"warning|warnings|downside|downsides|problem|problems|issue|issues|"
    r"shortage|disruption|uncertainty|uncertainties)\b",
    re.IGNORECASE,
)

_CONTRAST_WORDS_RE = re.compile(
    r"\b(however|despite|although|though|yet|whereas|"
    r"nevertheless|nonetheless|in contrast|contrary to|unlike|"
    r"instead|rather than|even though)\b",
    re.IGNORECASE,
)

# ── Source strength mapping ────────────────────────────────────────────────────
# Mirrors the taxonomy in source_metadata_service._TYPE_RULES.

_SOURCE_STRENGTH: dict[str, float] = {
    "government":      0.92,
    "research_paper":  0.88,
    "regulatory":      0.85,
    "industry_report": 0.75,
    "market_analysis": 0.70,
    "educational":     0.65,
    "news":            0.58,
    "company_blog":    0.48,
}
_DEFAULT_SOURCE_STRENGTH: float = 0.40


# ── Public API ─────────────────────────────────────────────────────────────────

def enrich_articles(articles: list[dict]) -> None:
    """
    Enrich every article dict in-place with Source Intelligence fields.
    Mutates articles; never raises.  Empty / bad content yields empty fields.
    Logs one sample object (first article) for observability.
    """
    first_logged = False
    for article in articles:
        try:
            _enrich_one(article)
        except Exception as exc:
            logger.debug(
                "[source_intelligence] enrich failed for %r: %s",
                article.get("url", "?"), exc,
            )
            _apply_empty_fields(article)
        if not first_logged:
            _log_sample(article)
            first_logged = True


# ── Private: single-article enrichment ────────────────────────────────────────

def _enrich_one(article: dict) -> None:
    title   = (article.get("title")   or "").strip()
    content = (article.get("content") or "").strip()
    text    = (title + " " + content[:1_000]).strip()

    numbers       = _extract_numbers(text)
    entities      = _extract_entities(text)
    dates         = _extract_dates(text)
    sentences     = _split_sentences(content[:1_000])
    evidence      = _extract_evidence(sentences, numbers)
    implications  = _extract_implications(sentences)
    risks         = _extract_risks(sentences)
    contradictions = _extract_contradictions(sentences)
    main_claim    = _derive_main_claim(title, sentences)
    src_strength  = _compute_source_strength(article.get("source_type") or "")
    sig_density   = _compute_signal_density(
        numbers, entities, evidence, main_claim, src_strength,
    )

    article["main_claim"]         = main_claim
    article["key_evidence"]       = evidence
    article["important_numbers"]  = numbers
    article["important_entities"] = entities
    article["important_dates"]    = dates
    article["implications"]       = implications
    article["risks"]              = risks
    article["contradictions"]     = contradictions
    article["signal_density"]     = sig_density
    article["source_strength"]    = src_strength


def _apply_empty_fields(article: dict) -> None:
    """Set all intelligence fields to empty defaults. Called on extraction failure."""
    article.setdefault("main_claim",         "")
    article.setdefault("key_evidence",       [])
    article.setdefault("important_numbers",  [])
    article.setdefault("important_entities", [])
    article.setdefault("important_dates",    [])
    article.setdefault("implications",       [])
    article.setdefault("risks",              [])
    article.setdefault("contradictions",     [])
    article.setdefault("signal_density",     0.0)
    article.setdefault("source_strength",
                       _compute_source_strength(article.get("source_type") or ""))


# ── Extraction helpers ─────────────────────────────────────────────────────────

def _extract_numbers(text: str) -> list[str]:
    """
    Extract quantitative strings from text.

    Skips bare 1–2 digit numbers (too noisy).
    Deduplicates; caps at 10 results.
    """
    seen:    set[str]  = set()
    results: list[str] = []
    for m in _NUMBER_RE.finditer(text):
        val = m.group().strip()
        if not val or val in seen:
            continue
        if re.fullmatch(r"\d{1,2}", val):
            continue
        seen.add(val)
        results.append(val)
        if len(results) >= 10:
            break
    return results


def _extract_entities(text: str) -> list[str]:
    """
    Extract named entities: 2–5 consecutive capitalized words.
    Filters sequences whose every word is a generic stopword.
    Deduplicates; caps at 10 results.
    """
    seen:    set[str]  = set()
    results: list[str] = []
    for m in _ENTITY_RE.finditer(text):
        ent   = m.group().strip()
        words = ent.split()
        if all(w in _ENTITY_STOPWORDS for w in words):
            continue
        key = ent.lower()
        if key in seen:
            continue
        seen.add(key)
        results.append(ent)
        if len(results) >= 10:
            break
    return results


def _extract_dates(text: str) -> list[str]:
    """
    Extract date references: month+year, quarter, and 4-digit years.
    Priority: month+year > quarter > year (more specific first).
    Deduplicates; caps at 8 results.
    """
    seen:    set[str]  = set()
    results: list[str] = []

    for pattern in (_MONTH_YEAR_RE, _QUARTER_RE, _YEAR_RE):
        for m in pattern.finditer(text):
            val = m.group().strip()
            key = val.lower()
            if key not in seen:
                seen.add(key)
                results.append(val)
                if len(results) >= 8:
                    return results

    return results


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences at . ! ? followed by whitespace + capital."""
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    return [p.strip() for p in parts if len(p.strip()) >= 20]


def _extract_evidence(sentences: list[str], numbers: list[str]) -> list[str]:
    """
    Sentences from content that contain at least one extracted number.
    Traceable to source text; never synthesised.
    Caps at 3; skips sentences longer than 300 chars.
    """
    if not numbers:
        return []
    number_set = {n.lower() for n in numbers}
    evidence: list[str] = []
    for s in sentences:
        if len(s) > 300:
            continue
        if any(n in s.lower() for n in number_set):
            evidence.append(s)
            if len(evidence) >= 3:
                break
    return evidence


def _extract_implications(sentences: list[str]) -> list[str]:
    """Sentences with forward-looking or implication language. Caps at 3."""
    return [
        s for s in sentences
        if _FORWARD_WORDS_RE.search(s) and len(s) <= 300
    ][:3]


def _extract_risks(sentences: list[str]) -> list[str]:
    """Sentences containing risk/concern/threat language. Caps at 3."""
    return [
        s for s in sentences
        if _RISK_WORDS_RE.search(s) and len(s) <= 300
    ][:3]


def _extract_contradictions(sentences: list[str]) -> list[str]:
    """Sentences with contrastive language (however, despite, ...). Caps at 2."""
    return [
        s for s in sentences
        if _CONTRAST_WORDS_RE.search(s) and len(s) <= 300
    ][:2]


def _derive_main_claim(title: str, sentences: list[str]) -> str:
    """
    One sentence: the most important assertion in this source.

    Priority:
    1. Title — if it contains a verb (assertive titles are already the claim).
    2. First content sentence — if assertive and <= 250 chars.
    3. Title truncated — fallback when neither is assertive.
    """
    if title and _CLAIM_VERB_RE.search(title):
        return title
    if sentences:
        first = sentences[0]
        if _CLAIM_VERB_RE.search(first) and len(first) <= 250:
            return first
    return title[:200] if title else ""


def _compute_source_strength(source_type: str) -> float:
    """
    0–1 quality tier derived from source_type (set by source_metadata_service).

    Higher = more authoritative source category.
    Returns _DEFAULT_SOURCE_STRENGTH for unknown / unclassified types.
    """
    return _SOURCE_STRENGTH.get(source_type, _DEFAULT_SOURCE_STRENGTH)


def _compute_signal_density(
    numbers:      list[str],
    entities:     list[str],
    evidence:     list[str],
    main_claim:   str,
    src_strength: float,
) -> float:
    """
    0–1 richness score: higher = article has more grounding signal.

    Component weights (sum = 1.0):
      numbers      0.30  — quantitative data is the strongest grounding signal
      entities     0.20  — named actors/products anchor the claim in reality
      evidence     0.25  — sentences with cited numbers are highest-quality grounding
      claim        0.15  — having a clear assertive claim adds interpretability
      source       0.10  — source authority contributes structural trust

    Normalisation:
      numbers  saturates at 5   (min(count / 5, 1.0))
      entities saturates at 5
      evidence saturates at 3   (min(count / 3, 1.0))
      claim    binary 1.0 / 0.0
      source   already 0–1
    """
    num_score   = min(len(numbers)  / 5.0, 1.0)
    ent_score   = min(len(entities) / 5.0, 1.0)
    evi_score   = min(len(evidence) / 3.0, 1.0)
    claim_score = 1.0 if main_claim else 0.0

    density = (
        0.30 * num_score   +
        0.20 * ent_score   +
        0.25 * evi_score   +
        0.15 * claim_score +
        0.10 * src_strength
    )
    return round(density, 3)


# ── Observability ──────────────────────────────────────────────────────────────

def _log_sample(article: dict) -> None:
    """Log one sample intelligence object per enrich_articles() call (Task 8)."""
    logger.info(
        "[source_intelligence] sample url=%s main_claim=%r"
        " evidence_count=%d entity_count=%d"
        " signal_density=%.3f source_strength=%.3f",
        (article.get("url") or "")[:80],
        (article.get("main_claim") or "")[:60],
        len(article.get("key_evidence")       or []),
        len(article.get("important_entities") or []),
        article.get("signal_density",  0.0),
        article.get("source_strength", 0.0),
    )
