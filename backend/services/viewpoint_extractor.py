"""
Multi-angle viewpoint extraction for the deep research pipeline.

Pure code analysis — no AI calls, no external dependencies.  Consumes the
ranked article list produced by deep_research_service and emits a structured
analytical scaffold that the LLM prompt uses to reason across sources rather
than summarising each article in isolation.

Output signals
--------------
  source_types        – how many articles come from each credibility tier
  convergence_points  – topics corroborated by 3+ distinct sources
  divergence_points   – topics where sources signal competing claims
  key_claims          – one-line assertion per article (title + first sentence)
  temporal_signals    – recency markers and trend indicators found in titles
  authority_gradient  – "strong" | "moderate" | "weak" credibility mix
  debate_surface      – verbatim short sentences that flag tensions/challenges
  competing_approaches – side-by-side alternatives extracted from titles

Public API
----------
extract_viewpoints(articles, topic) -> dict
format_viewpoints_for_prompt(vp)    -> str  (ready to inject into LLM prompt)
"""

from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlparse

# ── Source-type classification ────────────────────────────────────────────────

_ACADEMIC_DOMAINS = frozenset({
    "arxiv.org", "pubmed.ncbi.nlm.nih.gov", "scholar.google.com",
    "nature.com", "science.org", "biorxiv.org", "medrxiv.org",
    "semanticscholar.org", "acm.org", "ieee.org", "sciencedirect.com",
    "springer.com", "wiley.com", "tandfonline.com", "researchgate.net",
    "papers.nips.cc", "proceedings.mlr.press",
})

_NEWS_DOMAINS = frozenset({
    "techcrunch.com", "wired.com", "theverge.com", "ars technica.com",
    "bloomberg.com", "reuters.com", "ft.com", "wsj.com", "economist.com",
    "businessinsider.com", "forbes.com", "fortune.com", "cnbc.com",
    "nytimes.com", "washingtonpost.com", "guardian.com", "bbc.com",
    "venturebeat.com", "zdnet.com", "theregister.com",
})

_PRACTITIONER_DOMAINS = frozenset({
    "github.com", "stackoverflow.com", "medium.com", "dev.to",
    "hackernoon.com", "towardsdatascience.com", "huggingface.co",
    "paperswithcode.com", "pytorch.org", "tensorflow.org",
    "readthedocs.io", "docs.python.org", "developer.mozilla.org",
})

_OFFICIAL_DOMAINS_SUFFIXES = (".gov", ".edu", ".int", ".mil")
_OFFICIAL_DOMAINS_NAMES = frozenset({
    "who.int", "nih.gov", "fda.gov", "ema.europa.eu", "iso.org",
    "wto.org", "worldbank.org", "imf.org",
})

_YEAR_PATTERN = re.compile(r"\b(202[0-9])\b")
_TREND_WORDS  = frozenset({
    "new", "novel", "emerging", "breakthrough", "advances", "launches",
    "released", "latest", "growing", "rapidly", "increasingly",
    "introduces", "unveils", "announces", "next-generation",
})
_CONTRASTIVE_WORDS = frozenset({
    "however", "but", "alternatively", "challenge", "limitation",
    "debate", "controversy", "competing", "versus", "tradeoff",
    "trade-off", "concern", "criticism", "risk", "drawback",
    "downside", "caution", "caveat", "despite",
})
_STOP_WORDS = frozenset(
    "the a an and or but in on at to for of with is are was were be been"
    " being have has had do does did will would could should may might"
    " this that these those it its from by as how what why when who which".split()
)


# ── Public API ────────────────────────────────────────────────────────────────

def extract_viewpoints(articles: list[dict], topic: str) -> dict:
    """
    Perform multi-angle analysis of ranked articles and return a structured dict.

    Return shape
    ------------
    {
      "source_types":          dict[str, int],   # tier → count
      "convergence_points":    list[str],         # topics in 3+ sources
      "divergence_points":     list[str],         # topics w/ competing signals
      "key_claims":            list[str],         # one-line claim per article
      "temporal_signals":      list[str],         # recency/trend phrases
      "authority_gradient":    str,               # "strong"|"moderate"|"weak"
      "debate_surface":        list[str],         # sentences flagging tensions
      "competing_approaches":  list[str],         # side-by-side alternatives
      "source_count":          int,
    }
    """
    if not articles:
        return _empty()

    source_types    = _classify_sources(articles)
    convergence     = _find_convergence(articles, topic, min_sources=3)
    divergence      = _find_divergence(articles)
    key_claims      = _extract_key_claims(articles)
    temporal        = _extract_temporal_signals(articles)
    authority       = _assess_authority(source_types, len(articles))
    debate          = _surface_debate(articles)
    competing       = _extract_competing_approaches(articles)

    return {
        "source_types":         source_types,
        "convergence_points":   convergence[:6],
        "divergence_points":    divergence[:4],
        "key_claims":           key_claims[:8],
        "temporal_signals":     temporal[:4],
        "authority_gradient":   authority,
        "debate_surface":       debate[:4],
        "competing_approaches": competing[:4],
        "source_count":         len(articles),
    }


def format_viewpoints_for_prompt(vp: dict) -> str:
    """
    Render a viewpoints dict as a structured text block for LLM prompt injection.

    Returns a fallback string when the dict is empty.
    """
    if not vp or vp.get("source_count", 0) == 0:
        return "No viewpoint analysis available."

    lines = [
        f"Multi-source viewpoint analysis ({vp['source_count']} articles):",
        f"  Authority gradient: {vp['authority_gradient']}",
    ]

    types = vp.get("source_types", {})
    if types:
        type_str = ", ".join(f"{t}: {n}" for t, n in sorted(types.items()) if n > 0)
        lines.append(f"  Source mix: {type_str}")

    if vp.get("convergence_points"):
        lines.append(
            "  Convergence (3+ sources agree): "
            + ", ".join(vp["convergence_points"][:5])
        )

    if vp.get("divergence_points"):
        lines.append(
            "  Divergence (competing claims): "
            + ", ".join(vp["divergence_points"][:3])
        )

    if vp.get("temporal_signals"):
        lines.append(
            "  Temporal signals: "
            + ", ".join(vp["temporal_signals"][:3])
        )

    if vp.get("competing_approaches"):
        lines.append("  Competing approaches identified:")
        for approach in vp["competing_approaches"][:3]:
            lines.append(f"    - {approach}")

    if vp.get("debate_surface"):
        lines.append("  Tensions and debates flagged in sources:")
        for sentence in vp["debate_surface"][:3]:
            lines.append(f"    - {sentence}")

    if vp.get("key_claims"):
        lines.append("  Key claims per source:")
        for claim in vp["key_claims"][:6]:
            lines.append(f"    • {claim}")

    return "\n".join(lines)


# ── Source classification ─────────────────────────────────────────────────────

def _classify_sources(articles: list[dict]) -> dict[str, int]:
    types: dict[str, int] = {
        "academic": 0, "news": 0, "practitioner": 0,
        "official": 0, "general": 0,
    }
    for article in articles:
        tier = _source_tier(article.get("url", ""))
        types[tier] += 1
    return types


def _source_tier(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return "general"

    if netloc in _ACADEMIC_DOMAINS:
        return "academic"
    if netloc in _NEWS_DOMAINS:
        return "news"
    if netloc in _PRACTITIONER_DOMAINS:
        return "practitioner"
    if netloc in _OFFICIAL_DOMAINS_NAMES:
        return "official"
    if any(netloc.endswith(s) for s in _OFFICIAL_DOMAINS_SUFFIXES):
        return "official"
    return "general"


# ── Convergence detection ─────────────────────────────────────────────────────

def _find_convergence(
    articles: list[dict],
    topic: str,
    min_sources: int = 3,
) -> list[str]:
    """
    Return meaningful words that appear in the titles of ≥ min_sources articles.
    Topic words are excluded (they're trivially shared).
    """
    topic_words = set(_tokenize(topic))
    word_sets: dict[str, set[int]] = {}

    for idx, article in enumerate(articles):
        for word in _tokenize(article.get("title", "")):
            if word in topic_words or len(word) < 4:
                continue
            word_sets.setdefault(word, set()).add(idx)

    convergent = [w for w, idxs in word_sets.items() if len(idxs) >= min_sources]
    convergent.sort(key=lambda w: len(word_sets[w]), reverse=True)
    return convergent


# ── Divergence detection ──────────────────────────────────────────────────────

def _find_divergence(articles: list[dict]) -> list[str]:
    """
    Return topics where one source uses contrastive language while another
    does not — a proxy for competing viewpoints.
    """
    topic_signals: dict[str, dict] = {}  # word → {with_contrast: set, without: set}

    for idx, article in enumerate(articles):
        content = (article.get("title", "") + " " + article.get("content", "")[:300]).lower()
        has_contrast = any(cw in content for cw in _CONTRASTIVE_WORDS)
        title_words = set(_tokenize(article.get("title", "")))

        for word in title_words:
            if len(word) < 4:
                continue
            bucket = topic_signals.setdefault(word, {"with": set(), "without": set()})
            if has_contrast:
                bucket["with"].add(idx)
            else:
                bucket["without"].add(idx)

    divergent = [
        w for w, b in topic_signals.items()
        if b["with"] and b["without"]  # appears in both contrastive and non-contrastive articles
    ]
    divergent.sort(key=lambda w: len(topic_signals[w]["with"]), reverse=True)
    return divergent


# ── Key claim extraction ──────────────────────────────────────────────────────

def _extract_key_claims(articles: list[dict]) -> list[str]:
    """
    Return one-line claim per article: title + first content sentence (truncated).
    """
    claims = []
    for article in articles:
        title   = article.get("title", "").strip()
        content = article.get("content", "").strip()
        if not title:
            continue
        # Extract first sentence from content
        first_sentence = ""
        for sent in re.split(r"(?<=[.!?])\s+", content):
            sent = sent.strip()
            if len(sent) > 30:
                first_sentence = sent[:120].rstrip()
                if len(sent) > 120:
                    first_sentence += "…"
                break
        claim = f"{title}: {first_sentence}" if first_sentence else title
        claims.append(claim[:180])
    return claims


# ── Temporal signals ──────────────────────────────────────────────────────────

def _extract_temporal_signals(articles: list[dict]) -> list[str]:
    """
    Return phrases from titles that include year mentions or trend words.
    """
    seen: set[str] = set()
    signals: list[str] = []

    for article in articles:
        title = article.get("title", "")
        words = title.split()
        for i, word in enumerate(words):
            w_lower = word.lower().rstrip(".,")
            is_trend = w_lower in _TREND_WORDS
            is_year  = bool(_YEAR_PATTERN.match(w_lower))
            if is_trend or is_year:
                start  = max(0, i - 2)
                end    = min(len(words), i + 3)
                phrase = " ".join(words[start:end]).strip(".,;:")
                if phrase and phrase not in seen and len(phrase) > 5:
                    seen.add(phrase)
                    signals.append(phrase)

    return signals


# ── Authority gradient ────────────────────────────────────────────────────────

def _assess_authority(source_types: dict[str, int], total: int) -> str:
    if total == 0:
        return "weak"
    high_authority = source_types.get("academic", 0) + source_types.get("official", 0)
    ratio = high_authority / total
    if ratio >= 0.4:
        return "strong"
    if ratio >= 0.15:
        return "moderate"
    return "weak"


# ── Debate surface ────────────────────────────────────────────────────────────

def _surface_debate(articles: list[dict]) -> list[str]:
    """
    Extract short sentences from article content that explicitly flag tensions.
    """
    sentences: list[str] = []
    seen: set[str] = set()

    for article in articles:
        content = article.get("content", "")
        for sent in re.split(r"(?<=[.!?])\s+", content):
            sent = sent.strip()
            if len(sent) < 25:
                continue
            lower = sent.lower()
            if any(cw in lower for cw in _CONTRASTIVE_WORDS):
                excerpt = sent[:130].rstrip()
                if len(sent) > 130:
                    excerpt += "…"
                if excerpt not in seen:
                    seen.add(excerpt)
                    sentences.append(excerpt)

    return sentences


# ── Competing approaches ──────────────────────────────────────────────────────

def _extract_competing_approaches(articles: list[dict]) -> list[str]:
    """
    Look for "X vs Y" or "X or Y" patterns in titles — explicit comparisons.
    """
    patterns = [
        re.compile(r"(\w[\w\s]{2,25})\s+(?:vs\.?|versus|or|over)\s+([\w\s]{2,25}\w)", re.I),
    ]
    seen: set[str] = set()
    approaches: list[str] = []

    for article in articles:
        title = article.get("title", "")
        for pat in patterns:
            for match in pat.finditer(title):
                phrase = match.group(0).strip()
                if phrase.lower() not in seen and len(phrase) > 5:
                    seen.add(phrase.lower())
                    approaches.append(phrase[:120])

    return approaches


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    words = re.sub(r"[^\w\s]", " ", text.lower()).split()
    return [w for w in words if w not in _STOP_WORDS and len(w) > 1]


def _empty() -> dict:
    return {
        "source_types":         {"academic": 0, "news": 0, "practitioner": 0, "official": 0, "general": 0},
        "convergence_points":   [],
        "divergence_points":    [],
        "key_claims":           [],
        "temporal_signals":     [],
        "authority_gradient":   "weak",
        "debate_surface":       [],
        "competing_approaches": [],
        "source_count":         0,
    }
