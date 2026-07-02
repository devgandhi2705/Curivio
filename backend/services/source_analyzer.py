"""
Domain-aware source analyzer — pre-processing of ranked search results.

Extracts structured signals from a set of articles before they reach the LLM,
giving the model a concrete analytical scaffold to reason from rather than
asking it to discover patterns cold from raw text.

Domain awareness: trend vocabulary, trust labeling, and source-type distribution
are all domain-specific.  The AI domain's trend signals are benchmarks/papers;
the Finance domain's signals are filings/rates/earnings; Pharma focuses on
FDA/clinical signals.

All analysis is pure string processing — no NLP libraries required.

Public API
----------
analyze_sources(articles, query, domain)    → SourceAnalysis dict
format_analysis_for_prompt(analysis)        → str  (ready to inject into prompt)
"""

import re
from collections import Counter
from urllib.parse import urlparse

# ── Type alias ────────────────────────────────────────────────────────────────
# dict keys:
#   themes             list[str]        words appearing in 2+ article titles
#   repeated_insights  list[str]        2-word phrases in 2+ titles
#   trends             list[str]        trend-signal phrases from titles/content
#   contrastive        list[str]        sentences flagging tensions / trade-offs
#   source_count       int
#   domain_count       int
#   domain_diversity   str              "low" | "moderate" | "high"
#   source_types       dict[str, int]   article counts per source type
#   trust_signals      dict             trusted/unknown/spam article counts
SourceAnalysis = dict


# ── Universal constants ───────────────────────────────────────────────────────

_STOP_WORDS = frozenset(
    "the a an and or but in on at to for of with is are was were be been"
    " being have has had do does did will would could should may might can"
    " this that these those it its from by as how what why when who which"
    " your our their my i we you he she they all any some its".split()
)

_UNIVERSAL_TREND_SIGNALS = frozenset(
    "new novel emerging breakthrough advances next-generation "
    "state-of-the-art introduces launches released latest "
    "2025 2026 growing rapidly increasingly".split()
)

_CONTRASTIVE_SIGNALS = frozenset(
    "however but alternatively challenge challenges limitation limitations "
    "debate controversy disagree competing versus tradeoff trade-off "
    "concern concerns criticism criticized criticized risk risks".split()
)

_MAX_CONTRASTIVE_LEN = 120


# ── Domain-specific trend signal vocabulary ───────────────────────────────────
# These extend the universal signals for domain-targeted trend detection.
# Each frozenset contains terms that are highly meaningful as trend indicators
# within that domain context.

_DOMAIN_TREND_SIGNALS: dict[str, frozenset] = {
    "ai": frozenset({
        "llm", "gpt", "transformer", "diffusion", "multimodal", "rag",
        "fine-tuning", "finetuning", "alignment", "rlhf", "agents", "benchmark",
        "sota", "openai", "anthropic", "gemini", "claude", "reasoning",
        "inference", "quantization", "distillation",
    }),
    "technology": frozenset({
        "kubernetes", "microservices", "devops", "platform", "cloud",
        "serverless", "edge", "open-source", "security", "zero-trust",
        "llm", "api", "sdk", "framework", "release",
    }),
    "finance": frozenset({
        "fed", "rate", "inflation", "recession", "earnings", "revenue",
        "sec", "ipo", "merger", "acquisition", "gdp", "yield", "bonds",
        "equity", "credit", "risk", "regulatory", "filing", "quarter",
        "forecast", "outlook", "markets",
    }),
    "pharma": frozenset({
        "fda", "approval", "clinical", "trial", "phase", "drug", "therapy",
        "biomarker", "efficacy", "pipeline", "ema", "nda", "bla", "anda",
        "indication", "safety", "adverse", "compound", "molecule", "biologic",
        "biosimilar", "generics",
    }),
    "manufacturing": frozenset({
        "automation", "robotics", "iot", "oee", "lean", "six sigma",
        "supply chain", "reshoring", "nearshoring", "ev", "semiconductor",
        "shortage", "digital twin", "predictive maintenance", "cobots",
    }),
    "export_trade": frozenset({
        "tariff", "sanction", "trade war", "wto", "customs", "freight",
        "supply chain", "incoterm", "compliance", "hs code", "duty",
        "export control", "import restriction", "bilateral", "multilateral",
    }),
    "business": frozenset({
        "startup", "venture", "vc", "merger", "ipo", "layoff", "growth",
        "strategy", "pivot", "expansion", "funding", "valuation", "revenue",
        "profitability", "market share", "disruption",
    }),
    "default": frozenset(),
}


# ── Public API ────────────────────────────────────────────────────────────────

def analyze_sources(
    articles: list[dict],
    query:    str,
    domain:   str = "default",
) -> SourceAnalysis:
    """
    Return a structured analysis of the articles as a plain dict.

    The analysis surfaces patterns the LLM should integrate into its synthesis,
    not conclusions it should copy.  Domain context shapes which signals are
    prioritised (trend vocabulary, trust labeling).

    Args:
        articles: Ranked article dicts with at least 'title', 'url', 'content'.
        query:    The original search query / user interests string.
        domain:   Canonical domain key (e.g. "finance") for signal specialisation.
    """
    if not articles:
        return _empty_analysis()

    themes            = _extract_themes(articles, query)
    repeated_insights = _find_repeated_insights(articles)
    trends            = _identify_trends(articles, domain)
    contrastive       = _detect_contrastive_signals(articles)
    domains           = _unique_domains(articles)
    source_types      = _count_source_types(articles)
    trust_signals     = _assess_trust(articles, domain)

    diversity = (
        "high"     if len(domains) >= len(articles) * 0.8 else
        "moderate" if len(domains) >= len(articles) * 0.5 else
        "low"
    )

    return {
        "themes":             themes[:6],
        "repeated_insights":  repeated_insights[:5],
        "trends":             trends[:4],
        "contrastive":        contrastive[:3],
        "source_count":       len(articles),
        "domain_count":       len(domains),
        "domain_diversity":   diversity,
        "source_types":       source_types,
        "trust_signals":      trust_signals,
    }


def format_analysis_for_prompt(analysis: SourceAnalysis) -> str:
    """
    Render a SourceAnalysis dict as a concise, structured text block for
    injection into the LLM prompt.

    Returns a fallback string when analysis contains no signals.
    """
    if not analysis or analysis.get("source_count", 0) == 0:
        return "No source analysis available."

    lines = [
        f"Analyzed {analysis['source_count']} sources "
        f"from {analysis['domain_count']} domains "
        f"(source diversity: {analysis['domain_diversity']})."
    ]

    # Source type breakdown
    st = analysis.get("source_types", {})
    if st:
        type_summary = ", ".join(
            f"{count} {t.replace('_', ' ')}"
            for t, count in sorted(st.items(), key=lambda x: -x[1])
            if count > 0
        )
        if type_summary:
            lines.append(f"Source types: {type_summary}.")

    # Trust signal summary
    trust = analysis.get("trust_signals", {})
    if trust.get("trusted", 0) > 0:
        lines.append(
            f"Authority sources: {trust['trusted']} trusted, "
            f"{trust.get('unknown', 0)} unclassified."
        )

    if analysis["themes"]:
        lines.append(f"Common themes across sources: {', '.join(analysis['themes'])}.")

    if analysis["repeated_insights"]:
        lines.append(
            f"Repeated insights (concepts in 2+ sources): "
            f"{', '.join(analysis['repeated_insights'])}."
        )

    if analysis["trends"]:
        lines.append(f"Emerging / trending signals: {', '.join(analysis['trends'])}.")

    if analysis["contrastive"]:
        lines.append("Tensions and trade-offs flagged in sources:")
        for sentence in analysis["contrastive"]:
            lines.append(f"  - {sentence}")

    return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_themes(articles: list[dict], query: str) -> list[str]:
    """Words appearing in titles of 2+ distinct articles, excluding query words."""
    query_words = _tokenize(query)

    word_to_articles: dict[str, set] = {}
    for idx, article in enumerate(articles):
        for word in _tokenize(article.get("title", "")):
            if word in query_words or len(word) < 4:
                continue
            word_to_articles.setdefault(word, set()).add(idx)

    themes = [w for w, idxs in word_to_articles.items() if len(idxs) >= 2]
    themes.sort(key=lambda w: len(word_to_articles[w]), reverse=True)
    return themes


def _find_repeated_insights(articles: list[dict]) -> list[str]:
    """2-word phrases appearing in titles of 2+ distinct articles."""
    phrase_to_articles: dict[str, set] = {}
    for idx, article in enumerate(articles):
        words = _tokenize(article.get("title", ""))
        bigrams = [f"{words[i]} {words[i+1]}" for i in range(len(words) - 1)]
        for bigram in bigrams:
            phrase_to_articles.setdefault(bigram, set()).add(idx)

    repeated = [p for p, idxs in phrase_to_articles.items() if len(idxs) >= 2]
    repeated.sort(key=lambda p: len(phrase_to_articles[p]), reverse=True)
    return repeated


def _identify_trends(articles: list[dict], domain: str) -> list[str]:
    """
    Return short title phrases that contain trend signals.

    Uses the union of universal trend signals and domain-specific signals so
    that Finance articles surface earnings/rate signals and Pharma surfaces
    FDA/approval signals rather than generic tech vocabulary.
    """
    domain_signals = _DOMAIN_TREND_SIGNALS.get(domain, frozenset())
    all_signals    = _UNIVERSAL_TREND_SIGNALS | domain_signals

    seen: set[str] = set()
    trends: list[str] = []

    for article in articles:
        title_words = article.get("title", "").split()
        for i, word in enumerate(title_words):
            if word.lower().rstrip(".,") in all_signals:
                start  = max(0, i - 1)
                end    = min(len(title_words), i + 3)
                phrase = " ".join(title_words[start:end]).strip(".,")
                if phrase not in seen and len(phrase) > 3:
                    seen.add(phrase)
                    trends.append(phrase)

    return trends


def _detect_contrastive_signals(articles: list[dict]) -> list[str]:
    """Extract sentences flagging tensions, trade-offs, or competing approaches."""
    sentences: list[str] = []
    seen: set[str] = set()

    for article in articles:
        content = article.get("content", "")
        for sent in re.split(r"(?<=[.!?])\s+", content):
            sent = sent.strip()
            if len(sent) < 20:
                continue
            lower = sent.lower()
            if any(signal in lower for signal in _CONTRASTIVE_SIGNALS):
                excerpt = sent[:_MAX_CONTRASTIVE_LEN].rstrip()
                if len(sent) > _MAX_CONTRASTIVE_LEN:
                    excerpt += "…"
                if excerpt not in seen:
                    seen.add(excerpt)
                    sentences.append(excerpt)

    return sentences


def _count_source_types(articles: list[dict]) -> dict[str, int]:
    """Return a count of articles per source type."""
    from .source_quality_filter import classify_source_type
    counts: Counter = Counter(classify_source_type(a) for a in articles)
    return dict(counts)


def _assess_trust(articles: list[dict], domain: str) -> dict[str, int]:
    """
    Classify each article as trusted / unknown / spam based on domain config.

    Returns {"trusted": N, "unknown": N, "spam": N}.
    """
    from ..config.retrieval_config import get_authority_domains

    authority_domains = get_authority_domains(domain)
    result = {"trusted": 0, "unknown": 0, "spam": 0}

    _SPAM = frozenset({"buzzfeed.com", "dailymail.co.uk", "tmz.com",
                       "listverse.com", "boredpanda.com"})

    for article in articles:
        netloc = _unique_netloc(article.get("url", ""))
        if any(td in netloc for td in authority_domains):
            result["trusted"] += 1
        elif any(s in netloc for s in _SPAM):
            result["spam"] += 1
        else:
            result["unknown"] += 1

    return result


def _tokenize(text: str) -> list[str]:
    words = re.sub(r"[^\w\s]", " ", text.lower()).split()
    return [w for w in words if w not in _STOP_WORDS and len(w) > 1]


def _unique_domains(articles: list[dict]) -> set[str]:
    domains = set()
    for article in articles:
        netloc = _unique_netloc(article.get("url", ""))
        if netloc:
            domains.add(netloc)
    return domains


def _unique_netloc(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def _empty_analysis() -> SourceAnalysis:
    return {
        "themes":             [],
        "repeated_insights":  [],
        "trends":             [],
        "contrastive":        [],
        "source_count":       0,
        "domain_count":       0,
        "domain_diversity":   "low",
        "source_types":       {},
        "trust_signals":      {"trusted": 0, "unknown": 0, "spam": 0},
    }
