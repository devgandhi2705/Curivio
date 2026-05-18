"""
Rule-based resource categorizer for the AI learning agent.

Classifies a resource string (URL or descriptive text) into one of six categories:
  tutorial            — courses, books, how-to guides
  research_paper      — arXiv, conference proceedings, journals
  github_repository   — GitHub repos and project pages
  documentation       — official docs, API references, READMEs
  blog_post           — Medium, dev blogs, Substack articles
  video               — YouTube, Vimeo, recorded lectures

Classification priority (highest wins)
---------------------------------------
1. Prefix match (confidence 0.9–1.0)
   Resources from the learning path prompt use explicit prefixes:
   "Book:", "Course:", "Paper:", "Docs:", "Repo:", "Video:"

2. URL domain match (confidence 0.85–0.95)
   Exact or pattern-based match against known domains.

3. Path heuristics for unrecognised URLs (confidence 0.70–0.75)
   Checks for /docs/, /blog/, /papers/ etc. in the URL path.

4. Keyword match in plain text (confidence 0.60–0.70)
   Regex scan of the full resource string for category-specific terms.

5. Default (confidence 0.30)
   Falls through to "blog_post" — the most generic web-content category.

Public API
----------
categorize_resource(resource)   — classify a single resource string
categorize_resources(resources) — batch classify a list of resource strings
"""

import re
from typing import Literal
from urllib.parse import urlparse

Category = Literal[
    "tutorial",
    "research_paper",
    "github_repository",
    "documentation",
    "blog_post",
    "video",
]

# ── 1. Prefix rules ────────────────────────────────────────────────────────────
# The learning path prompt uses these explicit type labels.

_PREFIX_RULES: list[tuple[str, str, float]] = [
    ("repo:",            "github_repository", 1.0),
    ("paper:",           "research_paper",    1.0),
    ("docs:",            "documentation",     1.0),
    ("documentation:",   "documentation",     1.0),
    ("course:",          "tutorial",          1.0),
    ("tutorial:",        "tutorial",          1.0),
    ("video:",           "video",             1.0),
    ("book:",            "tutorial",          0.9),   # books → tutorial (closest category)
    ("blog:",            "blog_post",         1.0),
]

# ── 2. URL domain rules ────────────────────────────────────────────────────────

_DOMAIN_RULES: list[tuple[re.Pattern, str, float]] = [
    # GitHub
    (re.compile(r"\bgithub\.com\b"),                    "github_repository", 0.95),
    # Research
    (re.compile(r"\barxiv\.org\b"),                     "research_paper",    0.95),
    (re.compile(r"\bpapers\.nips\.cc\b"),               "research_paper",    0.95),
    (re.compile(r"\bopenreview\.net\b"),                "research_paper",    0.95),
    (re.compile(r"\baclanthology\.org\b"),              "research_paper",    0.95),
    (re.compile(r"\bsemanticscholar\.org\b"),           "research_paper",    0.90),
    (re.compile(r"\bproceedings\.(ml|neurips)\.cc\b"),  "research_paper",    0.90),
    (re.compile(r"\bdl\.acm\.org\b"),                   "research_paper",    0.90),
    # Video
    (re.compile(r"\b(youtube\.com|youtu\.be)\b"),       "video",             0.95),
    (re.compile(r"\bvimeo\.com\b"),                     "video",             0.90),
    (re.compile(r"\bloom\.com\b"),                      "video",             0.85),
    # Documentation
    (re.compile(r"\breadthedocs\.(io|org)\b"),          "documentation",     0.95),
    (re.compile(r"\bdocs\.[a-z0-9-]+\.(com|io|org)\b"), "documentation",    0.90),
    (re.compile(r"\bdeveloper\.[a-z0-9-]+\.(com|io)\b"), "documentation",   0.85),
    (re.compile(r"\bgithub\.io\b"),                     "documentation",     0.80),
    # Tutorial platforms
    (re.compile(r"\bcoursera\.org\b"),                  "tutorial",          0.95),
    (re.compile(r"\budemy\.com\b"),                     "tutorial",          0.95),
    (re.compile(r"\bedx\.org\b"),                       "tutorial",          0.95),
    (re.compile(r"\bfast\.ai\b"),                       "tutorial",          0.95),
    (re.compile(r"\bdeeplearning\.ai\b"),               "tutorial",          0.90),
    (re.compile(r"\bkhanacademy\.org\b"),               "tutorial",          0.90),
    (re.compile(r"\bdatacamp\.com\b"),                  "tutorial",          0.90),
    (re.compile(r"\bpluralsite?\.com\b"),               "tutorial",          0.85),
    # Blog / article
    (re.compile(r"\bmedium\.com\b"),                    "blog_post",         0.90),
    (re.compile(r"\btowardsdatascience\.com\b"),        "blog_post",         0.90),
    (re.compile(r"\bsubstack\.com\b"),                  "blog_post",         0.90),
    (re.compile(r"\bhashnode\.(com|dev)\b"),            "blog_post",         0.85),
    (re.compile(r"\bdev\.to\b"),                        "blog_post",         0.85),
    (re.compile(r"\bdistill\.pub\b"),                   "blog_post",         0.85),
    (re.compile(r"\bhuggingface\.co/blog\b"),           "blog_post",         0.85),
]

# ── 3. Path heuristics (applied to unrecognised URLs) ─────────────────────────

_PATH_RULES: list[tuple[re.Pattern, str, float]] = [
    (re.compile(r"/docs?(/|$)"),         "documentation",  0.75),
    (re.compile(r"/api(/|$)"),           "documentation",  0.70),
    (re.compile(r"/blog(/|$)"),          "blog_post",      0.70),
    (re.compile(r"/posts?(/|$)"),        "blog_post",      0.65),
    (re.compile(r"/papers?(/|$)"),       "research_paper", 0.70),
    (re.compile(r"/proceedings(/|$)"),   "research_paper", 0.70),
    (re.compile(r"/tutorial(/|$)"),      "tutorial",       0.70),
    (re.compile(r"/videos?(/|$)"),       "video",          0.70),
    (re.compile(r"/watch(/|$)"),         "video",          0.70),
]

# ── 4. Keyword rules (applied to full text when URL parsing fails) ─────────────

_KEYWORD_RULES: list[tuple[re.Pattern, str, float]] = [
    (re.compile(r"\barxiv\b|\bproceedings\b|\bjournal\b|\bpreprint\b", re.I),
     "research_paper", 0.70),
    (re.compile(r"\bpaper\b(?!back)", re.I),       "research_paper", 0.65),
    (re.compile(r"\btutorial\b|\bguide\b|\bcourse\b|\blearn\b|\bgetting.started\b", re.I),
     "tutorial", 0.70),
    (re.compile(r"\bhow.to\b|\bwalkthrough\b|\bworkshop\b", re.I), "tutorial", 0.65),
    (re.compile(r"\bdocumentation\b|\bapi.reference\b|\bmanual\b|\breadme\b", re.I),
     "documentation", 0.70),
    (re.compile(r"\bvideo\b|\blecture\b|\btalk\b|\bwebinar\b|\bwatch\b", re.I),
     "video", 0.65),
    (re.compile(r"\bblog\b|\barticle\b|\bpost\b|\bwrite.?up\b", re.I),
     "blog_post", 0.60),
    (re.compile(r"\bgithub\b|\brepository\b|\brepo\b|\bopen.?source\b|\bsource.?code\b", re.I),
     "github_repository", 0.65),
]

_DEFAULT_CATEGORY = "blog_post"
_DEFAULT_CONFIDENCE = 0.30


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def categorize_resource(resource: str) -> dict:
    """
    Classify a single resource string and return a categorized result dict.

    Returns
    -------
    {
      "resource":   str,
      "category":   str,   # one of the six Category values
      "confidence": float, # 0.30 (default fallback) to 1.0 (prefix match)
    }
    """
    resource = (resource or "").strip()
    category, confidence = _classify(resource)
    return {
        "resource":   resource,
        "category":   category,
        "confidence": round(confidence, 2),
    }


def categorize_resources(resources: list[str]) -> list[dict]:
    """Batch-classify a list of resource strings."""
    return [categorize_resource(r) for r in resources]


# ═══════════════════════════════════════════════════════════════════════════════
# Internal classification pipeline
# ═══════════════════════════════════════════════════════════════════════════════

def _classify(resource: str) -> tuple[str, float]:
    if not resource:
        return (_DEFAULT_CATEGORY, _DEFAULT_CONFIDENCE)

    # 1. Prefix match
    lower = resource.lower()
    for prefix, category, confidence in _PREFIX_RULES:
        if lower.startswith(prefix):
            return (category, confidence)

    # 2 & 3. URL-based matching
    parsed = _try_parse_url(resource)
    if parsed:
        netloc = parsed.netloc.lower()
        path   = parsed.path.lower()

        # 2a. Domain rules
        target = netloc + path
        for pattern, category, confidence in _DOMAIN_RULES:
            if pattern.search(target):
                return (category, confidence)

        # 2b. Path heuristics (domain not recognised)
        for pattern, category, confidence in _PATH_RULES:
            if pattern.search(path):
                return (category, confidence)

    # 3. Keyword scan on the full resource string
    for pattern, category, confidence in _KEYWORD_RULES:
        if pattern.search(resource):
            return (category, confidence)

    return (_DEFAULT_CATEGORY, _DEFAULT_CONFIDENCE)


def _try_parse_url(text: str) -> "urlparse result | None":
    """Return a parsed URL if the text looks like a URL, otherwise None."""
    stripped = text.strip()
    if not (stripped.startswith("http://") or stripped.startswith("https://")):
        return None
    try:
        parsed = urlparse(stripped)
        return parsed if parsed.netloc else None
    except Exception:
        return None
