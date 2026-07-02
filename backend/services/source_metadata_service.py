"""
Source Metadata Service

Populates the formal source metadata model on article dicts in-place.
Called by rank_articles() immediately after scoring — metadata persists
through the rest of the pipeline without any further computation.

Formal model (guaranteed keys after enrich()):
    url, title, domain, published_date,
    authority_score, freshness_score, intent_score, novelty_score,
    final_score, retrieval_query, source_type

Score mapping
-------------
Learning-path breakdown  → formal model field
  authority              → authority_score
  freshness              → freshness_score
  intent_match           → intent_score
  novelty                → novelty_score
  (adjusted rank score)  → final_score

Standard-path breakdown fallbacks:
  content_quality        → authority_score
  recency                → freshness_score
  keyword_relevance      → intent_score
  (no novelty field)     → 0.0

Source types
------------
news | research_paper | government | industry_report |
company_blog | regulatory | educational | market_analysis

Public API
----------
enrich(article, breakdown, final_score) -> None   (mutates article in-place)
"""

from __future__ import annotations

from urllib.parse import urlparse


# ── Source-type classification rules ─────────────────────────────────────────
# Evaluated in order; first match wins.  Patterns checked against lowercased URL.

_TYPE_RULES: list[tuple[list[str], str]] = [
    (
        ["arxiv.org", "pubmed", "ncbi.nlm", "researchgate", "jstor.org",
         "doi.org", "ieee.org", "biorxiv", "medrxiv", "openreview",
         "semanticscholar", "acm.org", "springer.com", "nature.com",
         "science.org", "pnas.org", "aclanthology", "paperswithcode"],
        "research_paper",
    ),
    (
        # Regulatory before government — more specific URLs must win
        ["ema.europa.eu", "fca.org.uk", "finra.org", "federalregister.gov",
         "cfr.gov", "regulatory", "/regulations/", "/compliance/"],
        "regulatory",
    ),
    (
        [".gov", ".gov.", "government", "parliament", "senate.gov",
         "congress.gov", "treasury.gov", "fda.gov", "sec.gov", "cdc.gov",
         "who.int", "un.org", "europa.eu", "irs.gov", "rbi.org.in",
         "sebi.gov.in", "oecd.org", "worldbank.org", "imf.org"],
        "government",
    ),
    (
        ["mckinsey.com", "deloitte.com", "pwc.com", "bcg.com", "bain.com",
         "gartner.com", "forrester.com", "idc.com", "statista.com",
         "frost.com", "ibisworld.com", "mordorintelligence", "grandviewresearch",
         "marketsandmarkets"],
        "industry_report",
    ),
    (
        ["bloomberg.com", "reuters.com", "cnbc.com", "ft.com", "wsj.com",
         "economist.com", "bbc.com", "bbc.co.uk", "theguardian.com",
         "nytimes.com", "washingtonpost.com", "techcrunch.com", "venturebeat.com",
         "wired.com", "businessinsider.com", "fortune.com", "apnews.com",
         "cnn.com", "theverge.com", "arstechnica.com"],
        "news",
    ),
    (
        [".edu/", "coursera.org", "khanacademy.org", "edx.org", "mit.edu",
         "stanford.edu", "udemy.com", "pluralsight.com", "/tutorial",
         "/learn/", "academy.", "geeksforgeeks", "w3schools"],
        "educational",
    ),
    (
        ["medium.com", "substack.com", "dev.to", "hashnode.com", "/blog/",
         "engineering.fb.com", "engineering.linkedin.com", "openai.com/blog",
         "anthropic.com/blog", "huggingface.co/blog", "blog.google",
         "developer.apple.com", "aws.amazon.com/blogs"],
        "company_blog",
    ),
]

# Fallback: if no URL rule matches, scan title for these keyword signals
_TITLE_TYPE_MAP: list[tuple[list[str], str]] = [
    (["study", "paper", "research", "journal", "findings", "published"], "research_paper"),
    (["government", "ministry", "parliament", "policy report"], "government"),
    (["regulation", "regulatory", "compliance", "legislation"], "regulatory"),
    (["market report", "industry report", "market analysis", "forecast", "outlook"], "industry_report"),
    (["news", "breaking", "today", "report:"], "news"),
    (["tutorial", "guide", "introduction", "course", "lesson", "explained"], "educational"),
    (["blog", "post:"], "company_blog"),
]


def _extract_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def _classify_source_type(url: str, title: str) -> str:
    """Classify a source into one of 8 canonical types via URL pattern matching."""
    lower_url   = url.lower()
    lower_title = title.lower()

    for patterns, source_type in _TYPE_RULES:
        if any(p in lower_url for p in patterns):
            return source_type

    for signals, source_type in _TITLE_TYPE_MAP:
        if any(s in lower_title for s in signals):
            return source_type

    return "news"   # sensible default for uncategorised web content


def enrich(
    article:     dict,
    breakdown:   dict,
    final_score: float | None = None,
) -> None:
    """
    Populate the formal source metadata model on the article dict in-place.

    Idempotent: calling enrich() again with a new breakdown simply overwrites
    the score fields with the latest values.  source_type is only set once
    (first call wins) since it depends on URL/title, not scores.

    Args:
        article:     Article dict to mutate.
        breakdown:   Score breakdown from score_article() or _learning_score_article().
        final_score: Adjusted rank score (after quality multiplier + penalties).
                     Defaults to breakdown["total"] when not supplied.
    """
    # Guarantee domain is populated
    if not article.get("domain"):
        article["domain"] = _extract_domain(article.get("url", ""))

    # Score fields — support both learning-path and standard-path breakdowns
    article["authority_score"] = round(
        float(breakdown.get("authority") or breakdown.get("content_quality") or 0.0), 3
    )
    article["freshness_score"] = round(
        float(breakdown.get("freshness") or breakdown.get("recency") or 0.0), 3
    )
    article["intent_score"] = round(
        float(breakdown.get("intent_match") or breakdown.get("keyword_relevance") or 0.0), 3
    )
    article["novelty_score"] = round(
        float(breakdown.get("novelty") or 0.0), 3
    )
    article["final_score"] = round(
        float(final_score if final_score is not None else breakdown.get("total") or 0.0), 3
    )

    # Source type — classified once; URL/title don't change after retrieval
    if "source_type" not in article:
        article["source_type"] = _classify_source_type(
            article.get("url", ""), article.get("title", "")
        )

    # Retrieval query — must be tagged at fetch time; default to "" if missing
    article.setdefault("retrieval_query", "")
    article.setdefault("published_date", "")
