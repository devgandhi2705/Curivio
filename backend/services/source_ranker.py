"""
Domain-aware source relevance ranker.  Phase 9.3.2 — Intelligence-Aware Ranking.

Two scoring paths depending on whether learning context is supplied:

LEARNING PATH (learning_context provided, typically mode="feed")
  Intent-aware intelligence ranking — the best learning article wins.

  Base formula (sums to 1.0):
    total = intent_match×0.60 + topic_match×0.30 + freshness×0.10

  topic_match sub-weights (sum to 1.0):
    continuity×0.40 + novelty×0.27 + authority×0.15 + practical×0.09 + perspective×0.09

  Signal-quality bonus (additive, max ~0.14 — Phase 9.3.2B recalibration):
    sig_bonus = signal_density×0.10 + source_strength×0.04
    A sig_density gap of 0.20 contributes 0.020 — beats intent gaps up to 0.036.
    total = min(1.0, base + sig_bonus)

  intent_match uses: project keywords + intent_profile fields + project_description
                     + article's retrieval_query (Phase 9.3.2 T3)
  signal_density / source_strength from Phase 9.3.1 Source Intelligence Layer (T4, T5)

  Penalties applied AFTER scoring:
    quality_multiplier  — domain source-type quality filter
    repetition_penalty  — concept/entity overlap with covered knowledge (0.40 floor)
    recency_penalty     — source reused too recently (0.60–1.0 multiplier)

  Post-score diversity enforcement:
    diversity_adjustment  — domain, source-type, perspective, publisher-family signals
    domain cap            — MAX_PER_DOMAIN / MAX_PER_TRUSTED_DOMAIN
    min_domains swap      — ensures minimum unique-domain count
    perspective cap       — max ceil(top_n/3) per editorial angle

STANDARD PATH (no learning_context)
  Five dimensions — keyword_relevance, technical_depth, content_quality,
  educational_value, recency.  Used by chat, feed, and other services.

Public API
----------
score_article(article, query, domain, mode, learning_context)   → dict
rank_articles(articles, query, top_n, min_score, domain, mode,
              learning_context)                                  → list[dict]
"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

from .publisher_intelligence_service import enrich_publisher as _enrich_publisher
from .source_diversity_scorer import diversity_adjustment as _diversity_adjustment
from .source_metadata_service import enrich as _enrich_metadata
from .source_quality_filter import filter_articles, quality_multiplier
from .similarity_service import deduplicate_articles
from ..config.retrieval_config import get_domain_config, get_authority_domains

import logging as _logging
_logger = _logging.getLogger(__name__)

# Articles below this combined score are silently dropped before ranking.
MIN_SCORE_FLOOR: float = 0.15

# Recency penalty: sources used too recently score lower to prevent same-source fatigue.
_RECENCY_HIGH_DAYS:   int   = 3     # used within this many days → high penalty
_RECENCY_WINDOW_DAYS: int   = 7     # used within this many days → medium penalty
_RECENCY_HIGH_MULT:   float = 0.60  # multiplier when used within _RECENCY_HIGH_DAYS
_RECENCY_MED_MULT:    float = 0.80  # multiplier when used within _RECENCY_WINDOW_DAYS

# Authority override: high-authority + high-relevance sources skip the recency penalty.
# Prevents penalising IMF/WB/WTO when they genuinely publish the best source.
_AUTHORITY_OVERRIDE_THRESHOLD:  float = 0.75
_RELEVANCE_OVERRIDE_THRESHOLD:  float = 0.65

# Maximum articles from the same netloc in the final ranked list.
# Plan-trusted domains (rotating_theme only, from today_plan.trusted_sources) may contribute up to MAX_PER_TRUSTED_DOMAIN.
# fixed_sequence plans always use MAX_PER_DOMAIN (no static override list).
MAX_PER_DOMAIN:         int = 2
MAX_PER_TRUSTED_DOMAIN: int = 3


# ── Mode weight scaling ───────────────────────────────────────────────────────
# Multiplicative factors applied to the domain's base RankingWeights before
# renormalizing to sum=1.0.  Values > 1.0 push that dimension higher; < 1.0
# reduces its relative influence.

_MODE_SCALE: dict[str, dict[str, float]] = {
    "chat": {
        "keyword_relevance": 1.30,   # fast: relevance is king
        "recency":           1.40,   # fresh results preferred
        "technical_depth":   0.65,   # shallow is fine for chat
        "educational_value": 0.55,   # not needed in quick lookups
        "content_quality":   1.00,
    },
    "feed": {
        "keyword_relevance": 0.85,
        "educational_value": 1.40,   # learning-focused content
        "content_quality":   1.30,   # quality over freshness
        "technical_depth":   0.85,
        "recency":           0.75,
    },
}


# ── Scoring constants ─────────────────────────────────────────────────────────

_STOP_WORDS = frozenset(
    "the a an and or but in on at to for of with is are was were be been"
    " being have has had do does did will would could should may might can"
    " this that these those it its from by as".split()
)

_TECH_TERMS = frozenset(
    "algorithm implementation architecture framework inference training benchmark "
    "optimization deployment pipeline model dataset parameter gradient embedding "
    "token transformer attention layer neural api library performance latency "
    "throughput accuracy precision recall evaluation fine-tuning finetune vector "
    "index retrieval generation prompt context retrieval-augmented rag llm lm "
    "gpu cuda batch epoch loss weight activation softmax relu ".split()
)

_QUANT_RE = re.compile(
    r"\d+(\.\d+)?\s*"
    r"(%|x|ms|gb|kb|mb|b\b|m\b|tokens|parameters|billion|million|layers|heads|steps|epochs)",
    re.IGNORECASE,
)

_SPAM_RE = re.compile(
    r"(you won'?t believe|click here|subscribe now|buy now|limited (time )?offer|"
    r"number \d+ will shock|doctors hate|this one weird trick|"
    r"make money|earn \$|free download|sign up today|"
    r"\d+ reasons why .* is dead|top \d+ ways to get rich)",
    re.IGNORECASE,
)

_EDU_SIGNALS = frozenset(
    "tutorial guide explained how-to introduction beginner step-by-step "
    "practical hands-on walkthrough example overview fundamentals basics "
    "deep-dive deep dive implementation guide primer cookbook recipe "
    "from scratch learn course lesson".split()
)

_SPAM_DOMAINS: dict[str, float] = {
    "buzzfeed.com":    0.05,
    "dailymail.co.uk": 0.05,
    "tmz.com":         0.00,
}

_DATE_IN_URL_RE = re.compile(r"/(20\d{2})/(\d{2})/")

# ── Supplemental signal vocabularies ──────────────────────────────────────────

_REAL_WORLD_SIGNALS = frozenset(
    "company startup deployed production shipped used billion million "
    "enterprise customer case real-world industry deployed integration "
    "adopted partnership deal acquisition revenue growth market".split()
)

_ENGAGEMENT_SIGNALS = frozenset(
    "breakthrough surprising unexpected counterintuitive revealed secret "
    "insider hidden discovered exposed controversial debate viral trending "
    "widely cited influential landmark seminal award winning prize notable".split()
)

_NOVELTY_SIGNALS = frozenset(
    "first new novel unprecedented announced introduced launches reveals "
    "2025 2026 just-released latest recently exclusive never-before "
    "record breakthrough invention pioneering revolutionizes redefines".split()
)

_PRACTICAL_SIGNALS = frozenset(
    "implementation tutorial how-to steps guide code example build create "
    "deploy configure setup walkthrough recipe hands-on practice applied "
    "production ready framework library tool open-source github".split()
)

# ── Learning-path weights ─────────────────────────────────────────────────────
# Seven dimensions (sum = 1.0). Targets per Phase 5.5:
#   Intent Match ~40%, Relevance ~30% (continuity+authority), Novelty 15%,
#   Perspective 5% — source diversity is enforced structurally via min_domains.

_LEARNING_WEIGHTS = {
    "intent_match": 0.60,   # primary signal: persona + goal alignment
    "topic_match":  0.30,   # composite: continuity, novelty, authority, practical, perspective
    "freshness":    0.10,   # article recency
}

# Sub-weights within the topic_match bucket (must sum to 1.0).
# Derived by normalising the old topic-dimension weights.
_TOPIC_SUBWEIGHTS = {
    "learning_continuity": 0.40,
    "novelty":             0.27,
    "authority":           0.15,
    "practical_value":     0.09,
    "perspective":         0.09,
}

# Additive bonus for articles whose domain appears in the journey plan's
# trusted_sources list.  Defined alongside sig_bonus weights (signal_density×0.10,
# source_strength×0.04) — all three contribute to the same additive step.
TRUSTED_SOURCE_BONUS: float = 0.05

# ── Perspective angle signals ─────────────────────────────────────────────────
# Used to classify articles by editorial angle and enforce perspective diversity.

_PERSPECTIVE_ANGLES: dict[str, frozenset] = {
    "policy_regulatory": frozenset([
        "regulation", "policy", "laws", "compliance", "government", "regulatory",
        "ministry", "authority", "rule", "sanction", "legislation", "reform",
        "committee", "parliament", "court", "legal", "treaty", "enforcement",
    ]),
    "economic_financial": frozenset([
        "economy", "market", "price", "cost", "revenue", "profit", "gdp", "trade",
        "export", "import", "tariff", "financial", "investment", "fund", "inflation",
        "interest", "debt", "currency", "fiscal", "monetary", "recession", "valuation",
    ]),
    "business_commercial": frozenset([
        "company", "startup", "enterprise", "business", "corporate", "merger",
        "acquisition", "strategy", "commercial", "brand", "chief", "launch",
        "product", "customer", "client", "sales", "partnership", "quarter",
    ]),
    "technology": frozenset([
        "technology", "software", "algorithm", "digital", "platform", "data",
        "artificial", "machine", "automation", "infrastructure", "engineering",
        "technical", "system", "model", "cloud", "semiconductor", "hardware", "chip",
    ]),
    "social_human": frozenset([
        "people", "worker", "community", "social", "impact", "health", "education",
        "consumer", "patient", "society", "labor", "welfare", "rights", "public",
        "cultural", "human", "population", "employment", "workforce",
    ]),
    "scientific_research": frozenset([
        "research", "study", "published", "scientists", "laboratory", "experiment",
        "findings", "evidence", "clinical", "discovery", "analysis", "journal",
        "university", "academia", "trial", "peer", "institute",
    ]),
}

_LEARN_STOP = frozenset(
    "the a an and or but in on at to for of with is are was were be been"
    " being have has had do does did will would could should may might can"
    " this that these those it its from by as new about".split()
)


def _recency_penalty_mult(
    article:        dict,
    breakdown:      dict,
    recent_sources: dict[str, int],
) -> float:
    """
    Multiplier in [_RECENCY_HIGH_MULT, 1.0] penalising sources reused too soon.

    recent_sources: {normalised_url: days_since_last_use}

    Authority override: sources above both authority and relevance thresholds are
    not penalised — they may legitimately be the best source regardless of recency.
    """
    if not recent_sources:
        return 1.0

    if (breakdown.get("authority")     or 0.0) >= _AUTHORITY_OVERRIDE_THRESHOLD \
       and (breakdown.get("intent_match") or 0.0) >= _RELEVANCE_OVERRIDE_THRESHOLD:
        return 1.0

    url_norm = (article.get("url") or "").rstrip("/").lower()
    days = recent_sources.get(url_norm)
    if days is None:
        return 1.0

    if days <= _RECENCY_HIGH_DAYS:
        return _RECENCY_HIGH_MULT
    if days <= _RECENCY_WINDOW_DAYS:
        return _RECENCY_MED_MULT
    return 1.0


def _perspective_label(article: dict) -> str:
    """Return the dominant editorial angle for this article, or '' if unclear."""
    text = (
        (article.get("title") or "") + " " + (article.get("content") or "")[:400]
    ).lower()
    words = frozenset(re.findall(r"[a-z]{4,}", text))
    best_label, best_hits = "", 0
    for label, signals in _PERSPECTIVE_ANGLES.items():
        hits = len(words & signals)
        if hits > best_hits:
            best_hits, best_label = hits, label
    return best_label


def _perspective_diversity_score(article: dict) -> float:
    """
    [0, 1] — how distinctively angled this article is.
    High score = one angle clearly dominates (e.g. regulatory, not a generic overview).
    Low score = spread across many angles or no clear signal.
    """
    text = (
        (article.get("title") or "") + " " + (article.get("content") or "")[:400]
    ).lower()
    words = frozenset(re.findall(r"[a-z]{4,}", text))
    hits_per = [len(words & sig) for sig in _PERSPECTIVE_ANGLES.values()]
    total = sum(hits_per)
    if total == 0:
        return 0.30   # no signal → neutral
    peak = max(hits_per)
    dominance = peak / total                    # 1.0 = only one angle matches
    strength  = min(1.0, peak / 4)             # 4 hits in one angle = full strength
    return round(dominance * 0.6 + strength * 0.4, 3)


def _learn_tokens(text: str) -> frozenset:
    words = re.findall(r"[a-z]{3,}", text.lower())
    return frozenset(w for w in words if w not in _LEARN_STOP)


# ── Public API ────────────────────────────────────────────────────────────────

def score_article(
    article:          dict,
    query:            str,
    domain:           str        = "default",
    mode:             str        = "feed",
    learning_context: dict | None = None,
) -> dict:
    """
    Return a scoring breakdown for one article.

    When learning_context is provided, uses the 7-dimension learning-path scorer
    (intent, continuity, novelty, authority, freshness, practical_value, perspective).
    Otherwise falls back to the standard 5-dimension scorer.

    learning_context keys (all optional):
        intent_profile, knowledge_state, keywords
    """
    if learning_context is not None:
        return _learning_score_article(article, query, domain, learning_context)

    authority_domains = get_authority_domains(domain)
    weights = _get_effective_weights(domain, mode)

    kw   = _keyword_score(article, query)
    tech = _technical_depth_score(article)
    qual = _content_quality_score(article, authority_domains)
    edu  = _educational_value_score(article)
    rec  = _recency_score(article)

    base = (
        kw   * weights.keyword_relevance +
        tech * weights.technical_depth   +
        qual * weights.content_quality   +
        edu  * weights.educational_value +
        rec  * weights.recency
    )

    bonus = _supplemental_bonus(article, mode)
    total = min(1.0, base + bonus)

    return {
        "keyword_relevance":  round(kw,    3),
        "technical_depth":    round(tech,  3),
        "content_quality":    round(qual,  3),
        "educational_value":  round(edu,   3),
        "recency":            round(rec,   3),
        "supplemental_bonus": round(bonus, 3),
        "total":              round(total, 3),
    }


def rank_articles(
    articles:         list[dict],
    query:            str,
    top_n:            int        = 5,
    min_score:        float      = MIN_SCORE_FLOOR,
    domain:           str        = "default",
    mode:             str        = "feed",
    learning_context: dict | None = None,
    min_domains:      int        = 0,
) -> list[dict]:
    """
    Score, filter, deduplicate by domain, and return the top_n articles.

    Steps
    -----
    1. Hard-filter low-quality articles (stubs, spam, content farms).
    2. Deduplicate near-identical titles across domains.
    3. Score every surviving article (learning path or standard path).
    4. Apply domain-aware source-type quality multiplier.
    5. Apply repetition penalty (learning path only).
    6. Drop articles below min_score.
    7. Sort by total score descending.
    8. Apply diversity cap: MAX_PER_DOMAIN per netloc.
    9. Diversity enforcement: if unique domains < min_domains, swap same-domain
       duplicates for scored articles from under-represented domains.
    10. Return up to top_n articles.
    """
    articles = filter_articles(articles, domain=domain)
    articles = deduplicate_articles(articles)

    knowledge_state = (learning_context or {}).get("knowledge_state")
    scored: list[tuple[float, dict, dict]] = []

    for article in articles:
        _enrich_publisher(article)   # T2: publisher identity (idempotent, no-op if already set)
        breakdown = score_article(article, query, domain=domain, mode=mode,
                                  learning_context=learning_context)
        mult = quality_multiplier(article, domain=domain)
        if learning_context is not None:
            # T1 (9.3.2B): cap quality multiplier in learning path so intent dominates.
            # Spam/content-farm penalty (floor 0.50) is preserved; authority boost is
            # capped at 1.10 so official_docs (1.20) cannot reorder over engineering_blog
            # (1.10) when the intent signal favours the lower-authority article.
            mult = max(0.50, min(1.10, mult))
        adjusted  = breakdown["total"] * mult
        if learning_context is not None:
            adjusted *= _repetition_penalty(article, knowledge_state)
        adjusted = round(adjusted, 3)
        if adjusted < min_score:
            continue
        scored.append((adjusted, article, breakdown))

    scored.sort(key=lambda x: x[0], reverse=True)

    result: list[dict] = []
    domain_counts: dict[str, int] = {}
    _recent_sources: dict[str, int] = (learning_context or {}).get("recent_sources") or {}
    _plan_trusted: list[str] = (learning_context or {}).get("trusted_sources") or []

    for _score, article, breakdown in scored:
        netloc = _extract_domain(article.get("url", ""))
        count  = domain_counts.get(netloc, 0)
        # rotating_theme plans supply trusted_sources; those domains get an extra slot.
        # fixed_sequence plans leave trusted_sources empty → everyone gets MAX_PER_DOMAIN.
        limit  = MAX_PER_TRUSTED_DOMAIN if (_plan_trusted and _is_plan_trusted_source(netloc, _plan_trusted)) else MAX_PER_DOMAIN
        if count >= limit:
            continue
        # Perspective must be set before diversity check (diversity reads _perspective)
        article["_perspective"] = _perspective_label(article)
        _div_adj   = _diversity_adjustment(article, result)
        _rec_mult  = _recency_penalty_mult(article, breakdown, _recent_sources)
        _eff_score = round(min(1.0, max(0.0, (_score + _div_adj) * _rec_mult)), 3)
        if _eff_score < min_score:
            continue    # penalty pushed below floor — prefer less-recently-used candidate
        domain_counts[netloc] = count + 1
        article["_rank_score"]  = _eff_score
        article["_rank_reason"] = _top_dimension(breakdown)
        _enrich_metadata(article, breakdown, final_score=_eff_score)
        result.append(article)
        if len(result) >= top_n:
            break

    # ── Domain diversity enforcement (best-effort, relevance preserved) ───────
    # If unique domains in result < min_domains, swap same-domain duplicates
    # for the highest-scored articles from under-represented domains.
    # Only swaps articles from domains that appear 2+ times (never removes
    # the sole representative of a domain).
    if min_domains > 0:
        _unique_doms = {_extract_domain(a.get("url", "")) for a in result}
        if len(_unique_doms) < min_domains:
            _selected_urls = {a.get("url", "") for a in result}
            for _sc, art, bd in scored:
                if len(_unique_doms) >= min_domains:
                    break
                _url = art.get("url", "")
                if _url in _selected_urls:
                    continue
                _dom = _extract_domain(_url)
                if _dom in _unique_doms:
                    continue
                # Find lowest-scored article from a domain that has 2+ entries
                _freq: dict[str, int] = {}
                for r in result:
                    d = _extract_domain(r.get("url", ""))
                    _freq[d] = _freq.get(d, 0) + 1
                _to_remove = None
                for r in reversed(result):
                    if _freq.get(_extract_domain(r.get("url", "")), 0) > 1:
                        _to_remove = r
                        break
                if _to_remove is None:
                    break   # no duplicate domains to swap; can't improve further
                result.remove(_to_remove)
                _selected_urls.discard(_to_remove.get("url", ""))
                art["_rank_score"]  = _sc
                art["_rank_reason"] = _top_dimension(bd)
                art["_perspective"] = _perspective_label(art)
                _enrich_metadata(art, bd, final_score=_sc)
                result.append(art)
                _unique_doms.add(_dom)
                _selected_urls.add(_url)

    # ── Perspective diversity enforcement (best-effort) ───────────────────────
    # If any single editorial angle appears >= ceil(top_n/3) times, swap the
    # lowest-scored over-represented article for the highest-scored candidate
    # that brings a different angle. Only swaps; never drops below top_n.
    _max_same_angle = max(2, top_n // 3)
    _persp_counts: dict[str, int] = {}
    for a in result:
        p = a.get("_perspective") or ""
        _persp_counts[p] = _persp_counts.get(p, 0) + 1

    _overrep = {p for p, c in _persp_counts.items() if p and c >= _max_same_angle}
    if _overrep:
        _sel_urls = {a.get("url", "") for a in result}
        for _sc, art, bd in scored:
            if not _overrep:
                break
            _url = art.get("url", "")
            if _url in _sel_urls:
                continue
            _plab = _perspective_label(art)
            if _plab in _overrep or not _plab:
                continue
            # Find lowest-scored article with an over-represented angle
            _to_remove = None
            for r in reversed(result):
                if (r.get("_perspective") or "") in _overrep:
                    _to_remove = r
                    break
            if _to_remove is None:
                break
            result.remove(_to_remove)
            _over_p = _to_remove.get("_perspective") or ""
            _persp_counts[_over_p] = _persp_counts.get(_over_p, 1) - 1
            if _persp_counts[_over_p] < _max_same_angle:
                _overrep.discard(_over_p)
            art["_rank_score"]  = _sc
            art["_rank_reason"] = _top_dimension(bd)
            art["_perspective"] = _plab
            _enrich_metadata(art, bd, final_score=_sc)
            result.append(art)
            _sel_urls.add(_url)
            _persp_counts[_plab] = _persp_counts.get(_plab, 0) + 1

    _log_ranking_audit(result, query, domain, mode)
    return result


# ── T9: Ranking observability ─────────────────────────────────────────────────

def _log_ranking_audit(
    result: list[dict],
    query:  str,
    domain: str,
    mode:   str,
) -> None:
    """Emit one structured INFO log per rank_articles() call — top-5 snapshot."""
    if not result:
        return
    top = []
    for a in result[:5]:
        top.append({
            "title":           (a.get("title") or "")[:60],
            "domain":          _extract_domain(a.get("url", "")),
            "rank_score":      a.get("_rank_score"),
            "rank_reason":     a.get("_rank_reason"),
            "signal_density":  a.get("signal_density"),
            "source_strength": a.get("source_strength"),
            "publisher":       a.get("publisher_name"),
            "perspective":     a.get("_perspective"),
        })
    _logger.info(
        "[ranking_audit] query=%r domain=%s mode=%s n=%d top=%s",
        (query or "")[:60], domain, mode, len(result), top,
    )


# ── Learning-path scorer ──────────────────────────────────────────────────────

def _learning_score_article(
    article:          dict,
    query:            str,
    domain:           str,
    learning_context: dict,
) -> dict:
    """
    Intent-aware learning scorer (Phase 9.3.2).

    Base: intent_match×0.60 + topic_match×0.30 + freshness×0.10
    Signal bonus: signal_density×0.05 + source_strength×0.03  (max ~0.08)
    Total = min(1.0, base + sig_bonus)
    """
    intent_profile      = learning_context.get("intent_profile")
    knowledge_state     = learning_context.get("knowledge_state")
    keywords            = learning_context.get("keywords") or []
    project_description = (learning_context.get("project_description") or "").strip()
    authority_domains   = get_authority_domains(domain)

    intent      = _intent_match_score(article, intent_profile, keywords, project_description)
    continuity  = _learning_continuity_score(article, knowledge_state)
    novelty     = _novelty_score(article, knowledge_state)
    authority   = _content_quality_score(article, authority_domains)
    freshness   = _recency_score(article)
    practical   = _educational_value_score(article)
    perspective = _perspective_diversity_score(article)

    sw = _TOPIC_SUBWEIGHTS
    topic_match = (
        continuity  * sw["learning_continuity"] +
        novelty     * sw["novelty"]             +
        authority   * sw["authority"]           +
        practical   * sw["practical_value"]     +
        perspective * sw["perspective"]
    )

    w = _LEARNING_WEIGHTS
    base = (
        intent      * w["intent_match"] +
        topic_match * w["topic_match"]  +
        freshness   * w["freshness"]
    )

    # T4 (9.3.2B): signal_density raised to 10% — meaningful quality amplifier.
    # A sig_density gap of 0.20 contributes 0.020, beating intent gaps up to 0.033.
    # Cannot override intent gaps above ~0.23 (max sig bonus 0.14 / intent weight 0.60).
    # T5: source_strength at 4% — secondary tie-breaker.
    signal_density  = float(article.get("signal_density")  or 0.0)
    source_strength = float(article.get("source_strength") or 0.0)
    sig_bonus = signal_density * 0.10 + source_strength * 0.04

    # Phase 2b-ii: additive bonus for plan-trusted sources (TRUSTED_SOURCE_BONUS = 0.05).
    _plan_trusted = learning_context.get("trusted_sources") or []
    _netloc = _extract_domain(article.get("url", ""))
    trusted_bonus = TRUSTED_SOURCE_BONUS if (_plan_trusted and _is_plan_trusted_source(_netloc, _plan_trusted)) else 0.0

    total = min(1.0, round(base + sig_bonus + trusted_bonus, 3))

    return {
        "intent_match":        round(intent,          3),
        "topic_match":         round(topic_match,     3),
        "learning_continuity": round(continuity,      3),
        "novelty":             round(novelty,          3),
        "authority":           round(authority,        3),
        "freshness":           round(freshness,        3),
        "practical_value":     round(practical,        3),
        "perspective":         round(perspective,      3),
        "signal_density":      round(signal_density,   3),
        "source_strength":     round(source_strength,  3),
        "trusted_bonus":       round(trusted_bonus,    3),
        "total":               total,
    }


def _intent_match_score(
    article:             dict,
    intent_profile:      dict | None,
    keywords:            list[str],
    project_description: str = "",
) -> float:
    """
    Token overlap between article and learner intent.

    Reference signal (T3 — Phase 9.3.2):
      keywords + intent_profile fields + project_description + article retrieval_query
    Soft Jaccard: intersection / ref_size (how much of the intent is covered).
    """
    ref_parts: list[str] = list(keywords)
    if intent_profile:
        for field in ("industry_context", "goal", "primary_focus", "persona", "intent_summary", "search_lens"):
            val = (intent_profile.get(field) or "").strip()
            if val:
                ref_parts.append(val)

    # T3: enrich reference with project description and the retrieval query
    # that sourced this article — both encode intent more precisely than keywords alone
    if project_description:
        ref_parts.append(project_description)
    retrieval_query = (article.get("retrieval_query") or "").strip()
    if retrieval_query:
        ref_parts.append(retrieval_query)

    ref = _learn_tokens(" ".join(ref_parts))
    if not ref:
        return 0.5

    article_text = (article.get("title") or "") + " " + (article.get("content") or "")[:600]
    art = _learn_tokens(article_text)

    return min(1.0, len(art & ref) / len(ref))


def _learning_continuity_score(
    article:         dict,
    knowledge_state: dict | None,
) -> float:
    """
    How well the article fits current learning progression.
    High when article aligns with active topics, recent topics, or knowledge gaps.
    """
    ref_parts: list[str] = []
    if knowledge_state:
        ref_parts.extend(knowledge_state.get("active_topics",  []))
        ref_parts.extend(knowledge_state.get("recent_topics",  []))
        ref_parts.extend(knowledge_state.get("knowledge_gaps", []))

    ref = _learn_tokens(" ".join(ref_parts))
    if not ref:
        return 0.5

    art = _learn_tokens(
        (article.get("title") or "") + " " + (article.get("content") or "")[:600]
    )
    base = min(1.0, len(art & ref) / len(ref))

    # Gap bonus: articles that address known gaps score higher
    gap_tokens = _learn_tokens(" ".join((knowledge_state or {}).get("knowledge_gaps", [])))
    gap_bonus  = 0.20 if gap_tokens and (art & gap_tokens) else 0.0

    return min(1.0, base + gap_bonus)


def _novelty_score(article: dict, knowledge_state: dict | None) -> float:
    """
    Higher when the article covers ground not yet taught.
    Inverted covered-concept overlap: 1 - fraction of title already in covered set.
    Gap boost added when the article addresses a known knowledge gap.
    """
    if not knowledge_state:
        return 0.70   # no state = new project; everything is novel

    covered_parts = (
        knowledge_state.get("covered_topics",   []) +
        knowledge_state.get("covered_keywords", [])
    )
    covered = _learn_tokens(" ".join(covered_parts))
    title   = _learn_tokens(article.get("title") or "")

    if not title:
        return 0.50

    # Fraction of title tokens already in covered set
    overlap_frac = len(title & covered) / len(title)
    base = 1.0 - overlap_frac

    # Boost if article addresses a known gap
    gap_tokens = _learn_tokens(" ".join(knowledge_state.get("knowledge_gaps", [])))
    gap_boost  = 0.20 if gap_tokens and (title & gap_tokens) else 0.0

    return min(1.0, base + gap_boost)


def _repetition_penalty(article: dict, knowledge_state: dict | None) -> float:
    """
    Penalty multiplier in (0, 1] applied to the final score.
    Articles heavily repeating already-covered concepts or entities are deprioritised.

    concept_repeat — title overlap with covered_topics + covered_keywords → up to -40%
    entity_repeat  — title overlap with covered_entities                  → up to -20%
    Minimum multiplier: 0.40 (never zero — article may still have value).
    """
    if not knowledge_state:
        return 1.0

    title = _learn_tokens(article.get("title") or "")
    if not title:
        return 1.0

    covered = _learn_tokens(" ".join(
        knowledge_state.get("covered_topics",   []) +
        knowledge_state.get("covered_keywords", [])
    ))
    entities = _learn_tokens(" ".join(knowledge_state.get("covered_entities", [])))

    concept_frac = len(title & covered)  / len(title) if covered else 0.0
    entity_frac  = len(title & entities) / len(title) if entities else 0.0

    penalty = 1.0 - (concept_frac * 0.40) - (entity_frac * 0.20)
    return max(0.40, round(penalty, 3))


# ── Effective weight computation ──────────────────────────────────────────────

def _get_effective_weights(domain: str, mode: str):
    """
    Combine domain base weights with mode scaling, renormalized to sum=1.0.

    Returns a RankingWeights-compatible object (namedtuple-like).
    """
    from ..config.retrieval_config import RankingWeights

    base = get_domain_config(domain).ranking_weights
    scale = _MODE_SCALE.get(mode, {})

    if not scale:
        return base

    raw = {
        "keyword_relevance": base.keyword_relevance * scale.get("keyword_relevance", 1.0),
        "technical_depth":   base.technical_depth   * scale.get("technical_depth",   1.0),
        "content_quality":   base.content_quality   * scale.get("content_quality",   1.0),
        "educational_value": base.educational_value * scale.get("educational_value", 1.0),
        "recency":           base.recency           * scale.get("recency",           1.0),
    }

    total = sum(raw.values())
    normalized = {k: round(v / total, 6) for k, v in raw.items()}

    # Correct any floating-point drift so the sum is exactly 1.0
    diff = round(1.0 - sum(normalized.values()), 6)
    if diff:
        normalized["keyword_relevance"] = round(normalized["keyword_relevance"] + diff, 6)

    return RankingWeights(**normalized)


# ── Dimension scorers ─────────────────────────────────────────────────────────

def _keyword_score(article: dict, query: str) -> float:
    """
    Coverage of query keywords in title (primary) and content (secondary).

    Formula: (2×title_coverage + content_coverage) / 2
    Full title match alone yields 1.0.
    """
    query_words = {
        w for w in re.sub(r"[^\w\s]", " ", query.lower()).split()
        if w not in _STOP_WORDS and len(w) > 2
    }
    if not query_words:
        return 0.5

    title   = article.get("title",   "").lower()
    content = article.get("content", "").lower()

    title_hits   = sum(1 for w in query_words if w in title)
    content_hits = sum(1 for w in query_words if w in content)

    title_coverage   = title_hits   / len(query_words)
    content_coverage = content_hits / len(query_words)
    return min(1.0, (title_coverage * 2 + content_coverage) / 2)


def _technical_depth_score(article: dict) -> float:
    """
    Three sub-signals, linearly combined:
      - Technical term density   (50%)
      - Quantitative data hits   (30%)
      - Content length tier      (20%)
    """
    text = (article.get("title", "") + " " + article.get("content", "")).lower()

    term_hits  = sum(1 for t in _TECH_TERMS if t in text)
    term_score = min(1.0, term_hits / 8)

    quant_hits  = len(_QUANT_RE.findall(text))
    quant_score = min(1.0, quant_hits / 4)

    content_len  = len(article.get("content", ""))
    length_score = min(1.0, content_len / 1_000)

    return term_score * 0.50 + quant_score * 0.30 + length_score * 0.20


def _content_quality_score(article: dict, authority_domains: dict[str, float]) -> float:
    """
    Two sub-signals:
      - Content length tier      (60%)
      - Domain reputation        (40%)

    Returns 0.0 immediately if the title matches a spam pattern.
    """
    title = article.get("title", "")
    if _SPAM_RE.search(title):
        return 0.0

    n = len(article.get("content", ""))
    if n < 50:
        length_score = 0.10
    elif n < 200:
        length_score = 0.35
    elif n < 400:
        length_score = 0.60
    elif n < 800:
        length_score = 0.80
    else:
        length_score = 1.00

    domain_score = _domain_reputation(article.get("url", ""), authority_domains)
    return length_score * 0.60 + domain_score * 0.40


def _educational_value_score(article: dict) -> float:
    """Educational signals in title + content plus URL path bonus."""
    text = (article.get("title", "") + " " + article.get("content", "")).lower()
    url  = article.get("url", "").lower()

    hits = sum(1 for s in _EDU_SIGNALS if s in text)
    signal_score = min(1.0, hits / 3)

    domain_bonus = 0.20 if any(
        seg in url
        for seg in ("docs.", "/learn", "tutorial", "course", "arxiv", "paper", "research")
    ) else 0.0

    return min(1.0, signal_score + domain_bonus)


def _recency_score(article: dict) -> float:
    """
    Score based on article age.  Returns 0.5 (neutral) when the date is unknown.

    Date resolution order:
    1. published_date field from Tavily (ISO string).
    2. Date pattern in the URL path (e.g. /2024/11/).
    """
    raw_date = article.get("published_date") or article.get("publishedDate")

    pub_dt: datetime | None = None

    if raw_date and isinstance(raw_date, str):
        pub_dt = _try_parse_iso(raw_date)

    if pub_dt is None:
        m = _DATE_IN_URL_RE.search(article.get("url", ""))
        if m:
            try:
                pub_dt = datetime(int(m.group(1)), int(m.group(2)), 1, tzinfo=timezone.utc)
            except ValueError:
                pass

    if pub_dt is None:
        return 0.5

    if pub_dt.tzinfo is None:
        pub_dt = pub_dt.replace(tzinfo=timezone.utc)

    age_days = (datetime.now(timezone.utc) - pub_dt).days
    if age_days <= 7:
        return 1.0
    if age_days <= 30:
        return 0.85
    if age_days <= 90:
        return 0.65
    if age_days <= 365:
        return 0.40
    return 0.20


# ── Supplemental scoring ──────────────────────────────────────────────────────

def _supplemental_bonus(article: dict, mode: str) -> float:
    """
    Four supplemental signals beyond the base 5 dimensions.

    Each signal returns [0, 1]; the mode-weighted combination is scaled to
    a max bonus of 0.12 added directly to the weighted total.

    Signals
    -------
    real_world   — deployed by real companies, case studies, production use
    engagement   — surprising, counterintuitive, widely cited, breakthrough
    novelty      — recent announcement, first-of-kind, 2025/2026 content
    practical    — implementation guide, code, tutorial, hands-on steps
    """
    title   = article.get("title",   "").lower()
    content = (article.get("content") or "")[:600].lower()
    url     = article.get("url", "").lower()
    text    = title + " " + content

    real_world = min(1.0, sum(1 for s in _REAL_WORLD_SIGNALS  if s in text) / 4)
    engagement = min(1.0, sum(1 for s in _ENGAGEMENT_SIGNALS  if s in text) / 3)
    novelty    = min(1.0, sum(1 for s in _NOVELTY_SIGNALS     if s in text) / 3)
    practical  = min(1.0, sum(1 for s in _PRACTICAL_SIGNALS   if s in text) / 4)

    # URL bonus for high-engagement sources
    if any(seg in url for seg in ("arxiv.org", "nature.com", "science.org", "hbr.org", "mit.edu")):
        engagement = min(1.0, engagement + 0.25)
    if any(seg in url for seg in ("github.com", "docs.", "/tutorial", "/guide", "cookbook")):
        practical = min(1.0, practical + 0.30)

    if mode == "feed":
        combined = practical * 0.35 + real_world * 0.30 + novelty * 0.20 + engagement * 0.15
    else:  # chat
        combined = practical * 0.40 + engagement * 0.30 + real_world * 0.20 + novelty * 0.10

    return round(min(0.12, combined * 0.12), 4)


# ── Private helpers ───────────────────────────────────────────────────────────

def _domain_reputation(url: str, authority_domains: dict[str, float]) -> float:
    netloc = _extract_domain(url)
    for known, score in authority_domains.items():
        if known in netloc:
            return score
    for known, score in _SPAM_DOMAINS.items():
        if known in netloc:
            return score
    return 0.50


def _is_plan_trusted_source(netloc: str, trusted_sources: list[str]) -> bool:
    """True if netloc exactly matches or is a subdomain of any entry in trusted_sources."""
    return any(netloc == src or netloc.endswith("." + src) for src in trusted_sources)


def _extract_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return url.lower()


def _top_dimension(breakdown: dict) -> str:
    dims = {k: v for k, v in breakdown.items() if k != "total" and isinstance(v, (int, float))}
    return max(dims, key=dims.get) if dims else ""


def _try_parse_iso(value: str) -> datetime | None:
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None
