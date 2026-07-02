"""
Publisher Intelligence Service

Deterministic publisher identity enrichment from URL/domain.
No LLM calls. No network requests. Pure pattern matching.

Enriches article dicts with:
  publisher_name    : str | None  — canonical name ("Reuters", "IMF", …)
  publisher_family  : str | None  — parent brand/org ("reuters", "google_research", …)
  publisher_tier    : int | None  — 1 (primary authority) / 2 (high quality) / 3 (mainstream)

Unknown publishers get None on all three fields.

Public API
----------
enrich_publisher(article)  → None  (mutates in-place, idempotent)
identify(url)              → dict
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ── Publisher registry ────────────────────────────────────────────────────────
# Tuples of (domain_suffix, publisher_name, publisher_family, publisher_tier).
# Evaluated in order; first match wins.  domain_suffix is matched against the
# netloc stripped of "www." — either an exact match or a suffix (e.g. ".mit.edu"
# matches "news.mit.edu").
#
# Tier 1 — primary authoritative sources: intergovernmental, central banks, regulators
# Tier 2 — high-quality secondary: research institutions, top-tier press, consultancies
# Tier 3 — mainstream quality press, leading trade publications

_REGISTRY: list[tuple[str, str, str, int]] = [
    # ── Tier 1: Intergovernmental & regulatory ────────────────────────────────
    ("imf.org",              "IMF",               "imf",            1),
    ("worldbank.org",        "World Bank",         "world_bank",     1),
    ("ifc.org",              "IFC",                "world_bank",     1),
    ("who.int",              "WHO",                "un_system",      1),
    ("un.org",               "United Nations",     "un_system",      1),
    ("undp.org",             "UNDP",               "un_system",      1),
    ("unicef.org",           "UNICEF",             "un_system",      1),
    ("wto.org",              "WTO",                "wto",            1),
    ("oecd.org",             "OECD",               "oecd",           1),
    ("bis.org",              "BIS",                "bis",            1),
    ("federalreserve.gov",   "Federal Reserve",    "federal_reserve",1),
    ("ecb.europa.eu",        "ECB",                "ecb",            1),
    ("weforum.org",          "World Economic Forum","wef",           1),
    ("nber.org",             "NBER",               "nber",           1),
    ("cbo.gov",              "CBO",                "us_government",  1),
    ("whitehouse.gov",       "White House",        "us_government",  1),
    ("treasury.gov",         "US Treasury",        "us_government",  1),
    ("commerce.gov",         "US Commerce Dept",   "us_government",  1),
    ("nasa.gov",             "NASA",               "us_government",  1),
    ("nih.gov",              "NIH",                "us_health",      1),
    ("cdc.gov",              "CDC",                "us_health",      1),
    ("fda.gov",              "FDA",                "us_health",      1),
    ("ipcc.ch",              "IPCC",               "ipcc",           1),
    ("europa.eu",            "European Union",     "eu",             1),

    # ── Tier 1: Research AI labs ──────────────────────────────────────────────
    ("deepmind.google",      "DeepMind",           "google_research",1),
    ("research.google",      "Google Research",    "google_research",1),
    ("blog.research.google", "Google Research Blog","google_research",1),
    ("openai.com",           "OpenAI",             "openai",         1),
    ("anthropic.com",        "Anthropic",          "anthropic",      1),

    # ── Tier 2: Research institutions ─────────────────────────────────────────
    ("arxiv.org",            "arXiv",              "arxiv",          2),
    ("ssrn.com",             "SSRN",               "ssrn",           2),
    ("nature.com",           "Nature",             "nature_portfolio",2),
    ("science.org",          "Science",            "aaas",           2),
    ("sciencedirect.com",    "ScienceDirect",      "elsevier",       2),
    ("springer.com",         "Springer",           "springer_nature",2),
    ("mit.edu",              "MIT",                "mit",            2),
    ("stanford.edu",         "Stanford",           "stanford",       2),
    ("harvard.edu",          "Harvard",            "harvard",        2),
    ("ox.ac.uk",             "Oxford",             "oxford",         2),
    ("cam.ac.uk",            "Cambridge",          "cambridge",      2),
    ("brookings.edu",        "Brookings",          "brookings",      2),

    # ── Tier 2: High-quality press & analysis ─────────────────────────────────
    ("reuters.com",          "Reuters",            "reuters",        2),
    ("ft.com",               "Financial Times",    "financial_times",2),
    ("bloomberg.com",        "Bloomberg",          "bloomberg",      2),
    ("economist.com",        "The Economist",      "economist",      2),
    ("hbr.org",              "Harvard Business Review","hbr",        2),
    ("technologyreview.com", "MIT Technology Review","mit_tech_review",2),

    # ── Tier 2: Consulting & advisory ─────────────────────────────────────────
    ("mckinsey.com",         "McKinsey",           "mckinsey",       2),
    ("gartner.com",          "Gartner",            "gartner",        2),
    ("deloitte.com",         "Deloitte",           "deloitte",       2),
    ("deloitte.co.uk",       "Deloitte UK",        "deloitte",       2),
    ("pwc.com",              "PwC",                "pwc",            2),
    ("pwc.co.uk",            "PwC UK",             "pwc",            2),
    ("ey.com",               "EY",                 "ey",             2),
    ("kpmg.com",             "KPMG",               "kpmg",           2),
    ("bcg.com",              "BCG",                "bcg",            2),
    ("bain.com",             "Bain & Company",     "bain",           2),

    # ── Tier 3: Mainstream quality press ──────────────────────────────────────
    ("bbc.com",              "BBC",                "bbc",            3),
    ("bbc.co.uk",            "BBC",                "bbc",            3),
    ("wsj.com",              "Wall Street Journal","wsj",            3),
    ("nytimes.com",          "New York Times",     "nytimes",        3),
    ("washingtonpost.com",   "Washington Post",    "washingtonpost", 3),
    ("apnews.com",           "AP News",            "ap",             3),
    ("theguardian.com",      "The Guardian",       "guardian",       3),
    ("axios.com",            "Axios",              "axios",          3),
    ("politico.com",         "Politico",           "politico",       3),

    # ── Tier 3: Leading tech press ────────────────────────────────────────────
    ("techcrunch.com",       "TechCrunch",         "aol_verizon",    3),
    ("arstechnica.com",      "Ars Technica",       "conde_nast",     3),
    ("wired.com",            "Wired",              "conde_nast",     3),
    ("theverge.com",         "The Verge",          "vox_media",      3),
    ("venturebeat.com",      "VentureBeat",        "venturebeat",    3),
    ("zdnet.com",            "ZDNet",              "zdnet",          3),
]


def identify(url: str) -> dict:
    """
    Return publisher identity for a URL.
    All values are None when the domain is not in the registry.
    """
    if not url:
        return {"publisher_name": None, "publisher_family": None, "publisher_tier": None}

    try:
        netloc = urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return {"publisher_name": None, "publisher_family": None, "publisher_tier": None}

    for suffix, name, family, tier in _REGISTRY:
        if netloc == suffix or netloc.endswith("." + suffix):
            return {"publisher_name": name, "publisher_family": family, "publisher_tier": tier}

    return {"publisher_name": None, "publisher_family": None, "publisher_tier": None}


def enrich_publisher(article: dict) -> None:
    """
    Set publisher_name, publisher_family, publisher_tier on article in-place.
    Idempotent — skips if all three are already set.
    Never raises.
    """
    if (
        "publisher_name"   in article
        and "publisher_family" in article
        and "publisher_tier"  in article
    ):
        return

    try:
        info = identify(article.get("url") or "")
        article.setdefault("publisher_name",   info["publisher_name"])
        article.setdefault("publisher_family", info["publisher_family"])
        article.setdefault("publisher_tier",   info["publisher_tier"])
    except Exception:
        logger.debug("[publisher_intelligence] enrich_publisher failed silently")
        article.setdefault("publisher_name",   None)
        article.setdefault("publisher_family", None)
        article.setdefault("publisher_tier",   None)
