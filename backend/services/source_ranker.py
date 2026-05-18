"""
Domain-aware source relevance ranker.

Each article is scored on five dimensions, each returning a float in [0, 1].
A weighted sum produces the total score.  Weights come from the domain's
RankingWeights config, then scaled by mode-specific multipliers to reflect
different retrieval objectives (chat = fast/relevant, feed = educational/quality,
deep_research = technical/current).

Dimensions
----------
keyword_relevance   How well the article matches the query terms.
technical_depth     Technical vocabulary, quantitative data, and substantive length.
content_quality     Length tiers, domain reputation, absence of spam patterns.
educational_value   Educational signals (tutorials, guides) or trend signals
                    (benchmarks, research, recent findings) depending on mode.
recency             Article age; neutral (0.5) when unknown.

Mode scaling
------------
chat            Boosts keyword_relevance and recency; reduces educational_value.
feed            Boosts educational_value and content_quality; reduces recency.
deep_research   Boosts technical_depth and recency; educational_value dimension
                blends in trend signals (latest findings, benchmarks, new papers).

Domain weights
--------------
Base weights come from DomainRetrievalConfig.ranking_weights, which encodes
domain-specific priorities (e.g. Finance: content_quality 0.25, recency 0.15;
AI: technical_depth 0.30).  Mode scaling is applied on top, then renormalized.

Public API
----------
score_article(article, query, domain, mode)              → dict  (breakdown + total)
rank_articles(articles, query, top_n, min_score, domain, mode) → list[dict]
"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

from .source_quality_filter import filter_articles, quality_multiplier
from .similarity_service import deduplicate_articles
from ..config.retrieval_config import get_domain_config, get_trusted_domains

# Articles below this combined score are silently dropped before ranking.
MIN_SCORE_FLOOR: float = 0.15

# Maximum articles from the same netloc in the final ranked list.
# Trusted domains may contribute up to MAX_PER_TRUSTED_DOMAIN.
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
    "deep_research": {
        "technical_depth":   1.45,   # analytical depth required
        "recency":           1.25,   # current literature preferred
        "keyword_relevance": 0.85,
        "educational_value": 0.70,   # see note: trend signals blended in
        "content_quality":   0.95,
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

# Trend signals for deep_research mode: new findings, recent papers, benchmarks
_TREND_SIGNALS = frozenset(
    "breakthrough emerging state-of-the-art sota introduces launches released "
    "latest novel new recent 2025 2026 benchmark outperforms surpasses "
    "advancement progress development discovery finding".split()
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


# ── Public API ────────────────────────────────────────────────────────────────

def score_article(
    article: dict,
    query:   str,
    domain:  str = "default",
    mode:    str = "feed",
) -> dict:
    """
    Return a scoring breakdown for one article.

    Keys: keyword_relevance, technical_depth, content_quality,
          educational_value, recency, total.  All values are rounded floats
          in [0, 1].

    domain — config key (e.g. "finance") for trusted-domain reputation lookup
             and base weight selection.
    mode   — "chat" | "feed" | "deep_research" for mode-specific weight scaling.
    """
    trusted = get_trusted_domains(domain)
    weights = _get_effective_weights(domain, mode)

    kw   = _keyword_score(article, query)
    tech = _technical_depth_score(article)
    qual = _content_quality_score(article, trusted)
    edu  = _educational_or_trend_score(article, mode)
    rec  = _recency_score(article)

    base = (
        kw   * weights.keyword_relevance +
        tech * weights.technical_depth   +
        qual * weights.content_quality   +
        edu  * weights.educational_value +
        rec  * weights.recency
    )

    # Supplemental bonus: up to +0.12 for real-world relevance, engagement,
    # novelty/surprise, and practical applicability (mode-weighted)
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
    articles:  list[dict],
    query:     str,
    top_n:     int   = 5,
    min_score: float = MIN_SCORE_FLOOR,
    domain:    str   = "default",
    mode:      str   = "feed",
) -> list[dict]:
    """
    Score, filter, deduplicate by domain, and return the top_n articles.

    Steps
    -----
    1. Hard-filter low-quality articles (stubs, spam, content farms).
    2. Deduplicate near-identical titles across domains.
    3. Score every surviving article (domain weights + mode scaling).
    4. Apply domain-aware source-type quality multiplier.
    5. Drop articles below min_score.
    6. Sort by total score descending.
    7. Apply diversity cap: MAX_PER_DOMAIN per netloc (trusted domains
       get MAX_PER_TRUSTED_DOMAIN slots to avoid penalising authoritative sources).
    8. Return up to top_n articles (without scoring metadata).
    """
    articles = filter_articles(articles, domain=domain)
    articles = deduplicate_articles(articles)

    trusted = get_trusted_domains(domain)
    scored: list[tuple[float, dict]] = []

    for article in articles:
        breakdown = score_article(article, query, domain=domain, mode=mode)
        mult      = quality_multiplier(article, domain=domain)
        adjusted  = round(breakdown["total"] * mult, 3)
        if adjusted < min_score:
            continue
        scored.append((adjusted, article))

    scored.sort(key=lambda x: x[0], reverse=True)

    result: list[dict] = []
    domain_counts: dict[str, int] = {}

    for _score, article in scored:
        netloc = _extract_domain(article.get("url", ""))
        count  = domain_counts.get(netloc, 0)
        # Trusted domains get an extra slot to avoid penalising authoritative sources
        limit  = MAX_PER_TRUSTED_DOMAIN if _is_trusted(netloc, trusted) else MAX_PER_DOMAIN
        if count >= limit:
            continue
        domain_counts[netloc] = count + 1
        result.append(article)
        if len(result) >= top_n:
            break

    return result


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


def _content_quality_score(article: dict, trusted_domains: dict[str, float]) -> float:
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

    domain_score = _domain_reputation(article.get("url", ""), trusted_domains)
    return length_score * 0.60 + domain_score * 0.40


def _educational_or_trend_score(article: dict, mode: str) -> float:
    """
    Returns the educational_value dimension score, adapted for mode.

    feed / chat   — educational signals: tutorials, guides, walkthroughs
    deep_research — blends educational (40%) with trend signals (60%):
                    benchmarks, new papers, SOTA, breakthrough findings.

    In both cases the URL path provides a domain-level boost.
    """
    if mode == "deep_research":
        return _trend_value_score(article) * 0.60 + _educational_value_score(article) * 0.40
    return _educational_value_score(article)


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


def _trend_value_score(article: dict) -> float:
    """
    Trend and research-frontier signals for deep_research mode.

    Checks title and first 500 chars of content for trend vocabulary,
    year mentions, and URL patterns indicating recent research artifacts.
    """
    title   = article.get("title", "").lower()
    content = article.get("content", "")[:500].lower()
    url     = article.get("url", "").lower()
    text    = title + " " + content

    trend_hits = sum(1 for s in _TREND_SIGNALS if s in text)
    signal_score = min(1.0, trend_hits / 4)

    # URL patterns indicating recent/research content
    url_bonus = 0.25 if any(
        seg in url for seg in (
            "arxiv.org/abs", "paperswithcode", "openreview",
            "proceedings.neurips", "aclanthology", "biorxiv",
        )
    ) else 0.0

    # Year mentions in title indicate timely content
    year_bonus = 0.15 if re.search(r"\b202[5-9]\b", title) else 0.0

    return min(1.0, signal_score + url_bonus + year_bonus)


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
    elif mode == "deep_research":
        combined = novelty * 0.40 + engagement * 0.35 + real_world * 0.15 + practical * 0.10
    else:  # chat
        combined = practical * 0.40 + engagement * 0.30 + real_world * 0.20 + novelty * 0.10

    return round(min(0.12, combined * 0.12), 4)


# ── Private helpers ───────────────────────────────────────────────────────────

def _domain_reputation(url: str, trusted_domains: dict[str, float]) -> float:
    netloc = _extract_domain(url)
    for known, score in trusted_domains.items():
        if known in netloc:
            return score
    for known, score in _SPAM_DOMAINS.items():
        if known in netloc:
            return score
    return 0.50


def _is_trusted(netloc: str, trusted_domains: dict[str, float]) -> bool:
    return any(known in netloc for known in trusted_domains)


def _extract_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return url.lower()


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
