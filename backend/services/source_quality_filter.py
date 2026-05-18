"""
Source quality classification and filtering for AI research agent.

Classifies each article into a source type and either hard-removes it
(is_low_quality) or adjusts its rank score via a domain-aware type-specific
multiplier (quality_multiplier).

Source type taxonomy
--------------------
research_paper   — arxiv, proceedings, preprints, academic databases
official_docs    — product documentation, API references, regulatory bodies
engineering_blog — company research blogs, respected practitioner blogs
educational      — tutorials, courses, structured learning resources
news             — news outlets (neutral; no boost/penalty in default domain)
content_farm     — high-volume low-effort listicle / SEO sites
unknown          — unrecognised domain with no strong type signals

Domain-aware multipliers
------------------------
Each domain in retrieval_config defines its own source_type_multipliers table
reflecting its trust hierarchy (e.g. Finance values official_docs highest;
Pharma values research_paper highest).  The generic _FALLBACK_MULTIPLIERS table
is used when a domain has no override.

Public API
----------
classify_source_type(article)               → str         one of SOURCE_TYPES
quality_multiplier(article, domain)         → float       [0.0, 1.40]
is_low_quality(article)                     → bool        hard-fail: exclude before ranking
filter_articles(articles, domain)           → list[dict]  convenience: drop all low-quality
"""

import re
from collections import Counter
from urllib.parse import urlparse


# ── Source type taxonomy ──────────────────────────────────────────────────────

SOURCE_TYPES = frozenset({
    "research_paper",
    "official_docs",
    "engineering_blog",
    "educational",
    "news",
    "content_farm",
    "unknown",
})

# Fallback multipliers used when a domain has no source_type_multipliers override.
# > 1.0  → boost   (high-trust sources)
# < 1.0  → penalty (low-trust sources)
_FALLBACK_MULTIPLIERS: dict[str, float] = {
    "research_paper":   1.25,
    "official_docs":    1.20,
    "educational":      1.15,
    "engineering_blog": 1.10,
    "news":             1.00,
    "unknown":          1.00,
    "content_farm":     0.40,
}


# ── Domain sets ───────────────────────────────────────────────────────────────
# Listed as bare host strings (no scheme, no trailing slash, no www.).
# Matching is substring-based so "arxiv.org" also matches "export.arxiv.org".

_RESEARCH_DOMAINS = frozenset({
    "arxiv.org", "semanticscholar.org", "paperswithcode.com",
    "aclanthology.org", "proceedings.neurips.cc", "openreview.net",
    "jmlr.org", "dl.acm.org", "ieeexplore.ieee.org", "ncbi.nlm.nih.gov",
    "pubmed.ncbi.nlm.nih.gov", "biorxiv.org", "medrxiv.org",
    "scholar.google.com", "researchgate.net", "nature.com",
    "science.org", "thelancet.com", "nejm.org", "bmj.com",
    "plos.org", "frontiersin.org",
})

_OFFICIAL_DOC_DOMAINS = frozenset({
    # Tech docs
    "docs.python.org", "pytorch.org", "tensorflow.org",
    "docs.anthropic.com", "platform.openai.com", "developer.mozilla.org",
    "kubernetes.io", "docs.aws.amazon.com", "cloud.google.com",
    "learn.microsoft.com", "developer.apple.com", "developers.google.com",
    "docs.github.com", "docs.docker.com", "huggingface.co",
    # Regulatory bodies
    "sec.gov", "federalreserve.gov", "fda.gov", "ema.europa.eu",
    "clinicaltrials.gov", "who.int", "wto.org", "trade.gov",
    "nist.gov", "iso.org", "ich.org", "nih.gov",
    "imf.org", "worldbank.org", "bis.org", "unctad.org",
    "dgft.gov.in", "customs.gov", "comtrade.un.org",
})

_ENGINEERING_BLOG_DOMAINS = frozenset({
    "openai.com", "anthropic.com", "deepmind.google", "research.google",
    "ai.meta.com", "blog.langchain.dev", "simonwillison.net",
    "eugeneyan.com", "lilianweng.github.io", "distill.pub",
    "newsletter.pragmaticengineer.com", "martinfowler.com",
    "netflixtechblog.com", "engineering.atspotify.com",
    "engineering.fb.com", "wandb.ai", "staffeng.com",
    "blog.cloudflare.com", "mckinsey.com", "bcg.com", "hbr.org",
    "strategy-business.com", "a16z.com", "ycombinator.com",
})

_EDUCATIONAL_DOMAINS = frozenset({
    "fast.ai", "course.fast.ai", "learnprompting.org",
    "d2l.ai", "cs231n.github.io", "karpathy.github.io",
    "towardsdatascience.com", "investopedia.com",
})

_CONTENT_FARM_DOMAINS = frozenset({
    "buzzfeed.com", "dailymail.co.uk", "tmz.com",
    "listverse.com", "clickhole.com", "makeuseof.com",
    "boredpanda.com",
})


# ── URL-path classification signals ──────────────────────────────────────────

_RESEARCH_URL_SIGNALS  = frozenset({"arxiv", "paper", "papers", "proceedings",
                                    "abstract", "preprint", "pubmed", "journal"})
_DOCS_URL_SIGNALS      = frozenset({"docs", "documentation", "reference",
                                    "api-reference", "developer", "sdk", "releases",
                                    "guidelines", "guidance", "regulations"})
_EDU_URL_SIGNALS       = frozenset({"learn", "tutorial", "course", "lesson",
                                    "workshop", "colab", "notebook", "guide"})


# ── Content-keyword classifiers ───────────────────────────────────────────────

_RESEARCH_CONTENT_RE = re.compile(
    r"\b(abstract|arxiv|proceedings|citation|doi\b|we propose|we present|"
    r"our approach|experimental results|state[- ]of[- ]the[- ]art|sota|"
    r"benchmark results|figure \d|table \d|clinical trial|phase [123iii]+|"
    r"p[- ]value|confidence interval|hazard ratio)\b",
    re.IGNORECASE,
)

_DOCS_CONTENT_RE = re.compile(
    r"\b(parameters?|returns?:|raises?:|example:|syntax:|note:|warning:|"
    r"see also|api reference|class |method |function |version \d|"
    r"regulation|regulatory|compliance|guideline|filing|disclosure)\b",
    re.IGNORECASE,
)


# ── Low-quality detection patterns ───────────────────────────────────────────

_CONTENT_FARM_TITLE_RE = re.compile(
    r"(top \d+ (best|ways|tools|tips|tricks|reasons)|"
    r"ultimate guide to|everything you need to know about|"
    r"\d+ (things|ways|steps|tips|hacks|secrets|mistakes) (to|you|that)|"
    r"best \w+ (for \d{4}|tools|apps|software|platforms)|"
    r"how to (make money|earn \$|get rich|go viral))",
    re.IGNORECASE,
)

_BOILERPLATE_RE = re.compile(
    r"(in this article[,\s]+(we will|you will|we'll|you'll)|"
    r"are you looking for|welcome to this (guide|article|post|tutorial)|"
    r"in this (comprehensive|complete|ultimate|definitive) guide|"
    r"this article will (teach|show|explain|cover|explore))",
    re.IGNORECASE,
)

_MIN_CONTENT_LENGTH: int = 80

_STUFFING_MIN_WORD_LEN:   int = 5
_STUFFING_REPEAT_THRESH:  int = 6
_STUFFING_CONTENT_WINDOW: int = 800


# ── Public API ────────────────────────────────────────────────────────────────

def classify_source_type(article: dict) -> str:
    """
    Classify an article into one of SOURCE_TYPES.

    Resolution order (first match wins):
      1. Domain lookup  — most reliable
      2. URL path segments
      3. Content / title keyword regexes
      4. Content-farm title pattern
      5. Default → ``"unknown"``
    """
    url     = article.get("url", "").lower()
    title   = article.get("title", "").lower()
    content = article.get("content", "")
    domain  = _extract_domain(url)

    # 1. Domain-based (ordered: most specific types first)
    for known in _RESEARCH_DOMAINS:
        if known in domain:
            return "research_paper"
    for known in _OFFICIAL_DOC_DOMAINS:
        if known in domain:
            return "official_docs"
    for known in _ENGINEERING_BLOG_DOMAINS:
        if known in domain:
            return "engineering_blog"
    for known in _EDUCATIONAL_DOMAINS:
        if known in domain:
            return "educational"
    for known in _CONTENT_FARM_DOMAINS:
        if known in domain:
            return "content_farm"

    # 2. URL path segments
    path_parts = frozenset(re.split(r"[/\-_.]", url))
    if path_parts & _RESEARCH_URL_SIGNALS:
        return "research_paper"
    if path_parts & _DOCS_URL_SIGNALS:
        return "official_docs"
    if path_parts & _EDU_URL_SIGNALS:
        return "educational"

    # 3. Content / title keywords
    combined = title + " " + content
    if _RESEARCH_CONTENT_RE.search(combined):
        return "research_paper"
    if _DOCS_CONTENT_RE.search(combined):
        return "official_docs"

    # 4. Content-farm title patterns (last before unknown)
    if _CONTENT_FARM_TITLE_RE.search(title):
        return "content_farm"

    return "unknown"


def quality_multiplier(article: dict, domain: str = "default") -> float:
    """
    Return a score multiplier based on source type and domain trust hierarchy.

    Looks up the domain's source_type_multipliers from retrieval_config.
    Falls back to _FALLBACK_MULTIPLIERS when the domain has no override.

    domain — canonical config key (e.g. "finance", "pharma").
    """
    from ..config.retrieval_config import get_source_type_multipliers
    source_type = classify_source_type(article)
    domain_mults = get_source_type_multipliers(domain)
    table = domain_mults if domain_mults else _FALLBACK_MULTIPLIERS
    return table.get(source_type, _FALLBACK_MULTIPLIERS.get(source_type, 1.00))


def is_low_quality(article: dict) -> bool:
    """
    Return True when the article should be hard-filtered before ranking.

    Any single trigger is sufficient:
      - Content shorter than the minimum threshold (stub / empty).
      - Title matches a content-farm / SEO-bait pattern.
      - Content opens with boilerplate / AI-generated summary phrases.
      - Severe keyword stuffing in short content.
      - Article belongs to a known content-farm domain.
    """
    content = article.get("content", "")
    title   = article.get("title", "")

    if len(content.strip()) < _MIN_CONTENT_LENGTH:
        return True

    if _CONTENT_FARM_TITLE_RE.search(title):
        return True

    if _BOILERPLATE_RE.search(content[:300]):
        return True

    if _is_keyword_stuffed(content):
        return True

    if classify_source_type(article) == "content_farm":
        return True

    return False


def filter_articles(articles: list[dict], domain: str = "default") -> list[dict]:
    """
    Return only articles that pass the is_low_quality hard filter.

    domain is accepted for future domain-specific filtering rules
    (e.g. Pharma requiring minimum content length) but currently only
    used to validate the parameter is propagated correctly.
    """
    return [a for a in articles if not is_low_quality(a)]


# ── Private helpers ───────────────────────────────────────────────────────────

def _extract_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return url.lower()


def _is_keyword_stuffed(content: str) -> bool:
    if len(content) >= _STUFFING_CONTENT_WINDOW:
        return False

    words = re.findall(
        r"\b[a-z]{%d,}\b" % _STUFFING_MIN_WORD_LEN,
        content.lower(),
    )
    if not words:
        return False

    top_count = Counter(words).most_common(1)[0][1]
    return top_count >= _STUFFING_REPEAT_THRESH
