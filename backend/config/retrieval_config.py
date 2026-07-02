"""
Centralized retrieval intelligence configuration.

Single source of truth for:
  - Trusted sources and their reputation scores (per domain)
  - Query expansion terms and search templates
  - Tavily API usage strategy (search / extract / crawl / map)
  - Ranking weight preferences per domain
  - Feed and deep-research retrieval rules

Usage
-----
from config.retrieval_config import get_domain_config, CLASSIFIER_NAME_MAP

cfg = get_domain_config("finance")          # DomainRetrievalConfig
cfg = get_domain_config("Finance")          # auto-lowercased, resolves alias

Retrieval strategies
--------------------
  search_first   — run Tavily search, then extract known high-value URLs
  extract_first  — extract from known trusted URLs, fall back to search
  mixed          — parallel search + targeted extract
  crawl_primary  — crawl a seed domain, use search as supplement
"""

from __future__ import annotations
from dataclasses import dataclass, field


# ── Building blocks ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RankingWeights:
    """
    Per-domain override for scoring dimension weights.
    Must sum to 1.0 (enforced at runtime via __post_init__).
    """
    keyword_relevance: float = 0.30
    technical_depth:   float = 0.25
    content_quality:   float = 0.20
    educational_value: float = 0.15
    recency:           float = 0.10

    def __post_init__(self):
        total = round(
            self.keyword_relevance + self.technical_depth +
            self.content_quality + self.educational_value + self.recency,
            6,
        )
        if abs(total - 1.0) > 1e-4:
            raise ValueError(f"RankingWeights must sum to 1.0, got {total}")


@dataclass(frozen=True)
class ExtractTarget:
    """A known URL to extract directly via Tavily extract() instead of search."""
    url: str
    label: str          # human-readable name for logging
    category: str       # "regulatory" | "research" | "market" | "documentation"


@dataclass(frozen=True)
class CrawlTarget:
    """A domain or URL to crawl via Tavily crawl() for domain exploration."""
    url: str
    label: str
    max_depth: int = 2
    limit: int = 20


@dataclass(frozen=True)
class FeedRetrievalRules:
    """Rules for the daily feed generation flow (3 news + 2 educational)."""
    search_queries_per_package: int = 4    # Tavily search() calls per daily package
    max_results_per_query: int = 15
    search_depth: str = "advanced"            # "basic" | "advanced"
    use_extract_for_known_urls: bool = True
    deduplicate_across_days: bool = True


@dataclass(frozen=True)
class DeepResearchRules:
    """Rules for deep research / chat mode flows."""
    max_search_queries: int = 8
    search_depth: str = "advanced"
    use_crawl: bool = False                # only crawl_primary strategy uses this
    use_map_for_discovery: bool = False
    max_extract_targets: int = 5


@dataclass(frozen=True)
class DomainRetrievalConfig:
    # ── Identity ──────────────────────────────────────────────────────────────
    key: str                                    # canonical key ("ai", "finance", …)
    display_name: str                           # human-readable

    # ── Source authority ──────────────────────────────────────────────────────
    trusted_domains: dict[str, float]           # domain → reputation score [0,1]
    include_domains: list[str]                  # Tavily include_domains filter

    # ── Query construction ────────────────────────────────────────────────────
    query_expansion_terms: list[str]            # appended to raw topic for search
    query_templates: list[str]                  # {topic} placeholders

    # ── Scoring ───────────────────────────────────────────────────────────────
    ranking_weights: RankingWeights

    # ── Content preferences ───────────────────────────────────────────────────
    preferred_content_types: list[str]          # "research" | "news" | "tutorial" | "official"

    # ── Tavily strategy ───────────────────────────────────────────────────────
    retrieval_strategy: str                     # see module docstring
    extract_targets: list[ExtractTarget] = field(default_factory=list)
    crawl_targets: list[CrawlTarget]     = field(default_factory=list)

    # ── Flow rules ────────────────────────────────────────────────────────────
    feed_retrieval_rules: FeedRetrievalRules   = field(default_factory=FeedRetrievalRules)
    deep_research_rules: DeepResearchRules     = field(default_factory=DeepResearchRules)

    # ── Source-type trust hierarchy ───────────────────────────────────────────
    # Multipliers applied to the final rank score based on classified source type.
    # > 1.0 = boost, < 1.0 = penalty.  Domain-specific because Finance values SEC
    # filings (official_docs) more than AI does; AI values research_paper more.
    # If empty, source_quality_filter falls back to its generic _TYPE_MULTIPLIERS.
    source_type_multipliers: dict[str, float] = field(default_factory=dict)

    # ── Prompt injection ──────────────────────────────────────────────────────
    prompt_context: str = ""                    # domain directive injected into LLM prompts


# ── Domain configurations ─────────────────────────────────────────────────────

_AI = DomainRetrievalConfig(
    key="ai",
    display_name="AI / Machine Learning",
    trusted_domains={
        "arxiv.org":                        1.00,
        "openai.com":                       1.00,
        "anthropic.com":                    1.00,
        "deepmind.google":                  1.00,
        "research.google":                  1.00,
        "ai.meta.com":                      0.95,
        "huggingface.co":                   0.95,
        "pytorch.org":                      0.95,
        "tensorflow.org":                   0.90,
        "fast.ai":                          0.90,
        "distill.pub":                      1.00,
        "lilianweng.github.io":             1.00,
        "paperswithcode.com":               0.90,
        "semanticscholar.org":              0.90,
        "github.com":                       0.85,
        "blog.langchain.dev":               0.85,
        "simonwillison.net":                0.85,
        "eugeneyan.com":                    0.90,
        "towardsdatascience.com":           0.80,
        "wandb.ai":                         0.80,
        "newsletter.pragmaticengineer.com": 0.85,
    },
    include_domains=[
        "arxiv.org", "huggingface.co", "paperswithcode.com",
        "github.com", "openai.com", "anthropic.com",
    ],
    query_expansion_terms=["research 2025", "paper", "implementation", "benchmark"],
    query_templates=[
        "{topic} latest research 2025",
        "{topic} arxiv paper implementation",
        "{topic} benchmark comparison state of the art",
    ],
    ranking_weights=RankingWeights(
        keyword_relevance=0.25,
        technical_depth=0.30,
        content_quality=0.20,
        educational_value=0.15,
        recency=0.10,
    ),
    preferred_content_types=["research", "tutorial", "official"],
    # AI trust hierarchy: research > official docs > engineering blog > educational > news
    source_type_multipliers={
        "research_paper":   1.35,
        "official_docs":    1.25,
        "engineering_blog": 1.20,
        "educational":      1.15,
        "news":             1.00,
        "unknown":          0.95,
        "content_farm":     0.35,
    },
    retrieval_strategy="mixed",
    extract_targets=[
        ExtractTarget("https://arxiv.org/search/", "arXiv search", "research"),
        ExtractTarget("https://paperswithcode.com/sota", "PapersWithCode SOTA", "research"),
    ],
    crawl_targets=[
        CrawlTarget("https://arxiv.org/list/cs.LG/recent", "arXiv ML recent", max_depth=1, limit=30),
        CrawlTarget("https://github.com/trending/python", "GitHub trending Python", max_depth=1, limit=20),
    ],
    feed_retrieval_rules=FeedRetrievalRules(
        search_queries_per_package=2,
        max_results_per_query=8,
        search_depth="advanced",
        use_extract_for_known_urls=True,
    ),
    deep_research_rules=DeepResearchRules(
        max_search_queries=4,
        search_depth="advanced",
        use_crawl=False,
        use_map_for_discovery=True,
        max_extract_targets=5,
    ),
    prompt_context=(
        "Domain context: AI / Machine Learning\n"
        "- Use precise ML terminology (loss functions, gradients, attention, etc.).\n"
        "- Prefer concrete code snippets or pseudocode over abstract descriptions.\n"
        "- Reference benchmarks and papers where relevant (e.g. arxiv IDs).\n"
        "- Highlight practical implementation trade-offs, not just theory."
    ),
)

_TECHNOLOGY = DomainRetrievalConfig(
    key="technology",
    display_name="Technology / Software Engineering",
    trusted_domains={
        "github.com":               0.85,
        "stackoverflow.com":        0.80,
        "developer.mozilla.org":    0.95,
        "docs.python.org":          0.90,
        "docs.aws.amazon.com":      0.90,
        "cloud.google.com":         0.90,
        "docs.microsoft.com":       0.90,
        "kubernetes.io":            0.90,
        "docker.com":               0.85,
        "nginx.org":                0.85,
        "postgresql.org":           0.90,
        "redis.io":                 0.85,
        "hashicorp.com":            0.85,
        "news.ycombinator.com":     0.80,
        "newsletter.pragmaticengineer.com": 0.90,
        "staffeng.com":             0.85,
        "martinfowler.com":         0.90,
    },
    include_domains=[
        "github.com", "stackoverflow.com", "developer.mozilla.org",
        "docs.aws.amazon.com", "kubernetes.io",
    ],
    query_expansion_terms=["documentation", "best practices", "2025", "tutorial"],
    query_templates=[
        "{topic} technical documentation tutorial",
        "{topic} best practices implementation 2025",
        "{topic} architecture comparison alternatives",
    ],
    ranking_weights=RankingWeights(
        keyword_relevance=0.30,
        technical_depth=0.30,
        content_quality=0.20,
        educational_value=0.10,
        recency=0.10,
    ),
    preferred_content_types=["official", "tutorial", "research"],
    # Technology trust hierarchy: official docs > engineering blog > research > educational > news
    source_type_multipliers={
        "official_docs":    1.30,
        "engineering_blog": 1.20,
        "research_paper":   1.15,
        "educational":      1.15,
        "news":             1.00,
        "unknown":          0.90,
        "content_farm":     0.35,
    },
    retrieval_strategy="search_first",
    extract_targets=[],
    crawl_targets=[
        CrawlTarget("https://github.com/trending", "GitHub trending", max_depth=1, limit=20),
    ],
    feed_retrieval_rules=FeedRetrievalRules(
        search_queries_per_package=2,
        max_results_per_query=8,
        search_depth="advanced",
    ),
    deep_research_rules=DeepResearchRules(
        max_search_queries=4,
        search_depth="advanced",
    ),
    prompt_context=(
        "Domain context: Technology / Software Engineering\n"
        "- Prefer concrete examples with code, CLI commands, or architecture diagrams.\n"
        "- Distinguish clearly between different cloud providers and open-source stacks.\n"
        "- Address scalability, security, and operational concerns proactively.\n"
        "- Link to official documentation or reference implementations when available."
    ),
)

_FINANCE = DomainRetrievalConfig(
    key="finance",
    display_name="Finance",
    trusted_domains={
        "bloomberg.com":        0.95,
        "ft.com":               0.95,
        "wsj.com":              0.90,
        "reuters.com":          0.90,
        "sec.gov":              1.00,
        "federalreserve.gov":   1.00,
        "imf.org":              0.95,
        "bis.org":              0.95,
        "worldbank.org":        0.90,
        "investopedia.com":     0.75,
        "seekingalpha.com":     0.70,
        "morningstar.com":      0.80,
        "fool.com":             0.65,
        "cfainstitute.org":     0.90,
        "quantlib.org":         0.85,
    },
    include_domains=[
        "reuters.com", "ft.com", "sec.gov",
        "federalreserve.gov", "imf.org",
    ],
    query_expansion_terms=["market analysis", "2025", "regulatory", "risk"],
    query_templates=[
        "{topic} market analysis 2025",
        "{topic} regulatory update compliance",
        "{topic} investment strategy risk factor",
    ],
    ranking_weights=RankingWeights(
        keyword_relevance=0.30,
        technical_depth=0.20,
        content_quality=0.25,
        educational_value=0.10,
        recency=0.15,
    ),
    preferred_content_types=["news", "official", "research"],
    # Finance trust hierarchy: official docs (SEC/Fed) > news > research > educational > blogs
    source_type_multipliers={
        "official_docs":    1.40,
        "news":             1.25,
        "research_paper":   1.15,
        "engineering_blog": 0.90,
        "educational":      0.80,
        "unknown":          0.80,
        "content_farm":     0.35,
    },
    retrieval_strategy="extract_first",
    extract_targets=[
        ExtractTarget("https://www.sec.gov/cgi-bin/browse-edgar", "SEC EDGAR", "regulatory"),
        ExtractTarget("https://www.federalreserve.gov/releases/", "Federal Reserve releases", "regulatory"),
        ExtractTarget("https://www.imf.org/en/Publications", "IMF publications", "research"),
    ],
    crawl_targets=[],
    feed_retrieval_rules=FeedRetrievalRules(
        search_queries_per_package=2,
        max_results_per_query=7,
        search_depth="advanced",
        use_extract_for_known_urls=True,
    ),
    deep_research_rules=DeepResearchRules(
        max_search_queries=4,
        search_depth="advanced",
        max_extract_targets=5,
    ),
    prompt_context=(
        "Domain context: Finance\n"
        "- Ground analysis in quantitative evidence (P/E ratios, yield curves, etc.).\n"
        "- Distinguish clearly between market analysis and regulatory/compliance context.\n"
        "- Flag risk factors explicitly — never present speculation as certainty.\n"
        "- Reference authoritative sources: SEC filings, central bank publications."
    ),
)

_PHARMA = DomainRetrievalConfig(
    key="pharma",
    display_name="Pharmaceutical / Biotech",
    trusted_domains={
        "pubmed.ncbi.nlm.nih.gov":  1.00,
        "clinicaltrials.gov":       1.00,
        "fda.gov":                  1.00,
        "ema.europa.eu":            1.00,
        "who.int":                  0.95,
        "nature.com":               0.95,
        "science.org":              0.95,
        "thelancet.com":            0.95,
        "nejm.org":                 0.95,
        "bmj.com":                  0.90,
        "fiercepharma.com":         0.75,
        "biopharmadive.com":        0.75,
        "statnews.com":             0.80,
        "drugbank.com":             0.85,
        "chembl.ebi.ac.uk":         0.90,
        "ich.org":                  0.95,
    },
    include_domains=[
        "pubmed.ncbi.nlm.nih.gov", "clinicaltrials.gov",
        "fda.gov", "ema.europa.eu", "nature.com",
    ],
    query_expansion_terms=["clinical trial", "FDA", "2025", "regulatory approval"],
    query_templates=[
        "{topic} clinical trial results FDA 2025",
        "{topic} drug development pipeline approval",
        "{topic} regulatory EMA ICH guideline",
    ],
    ranking_weights=RankingWeights(
        keyword_relevance=0.25,
        technical_depth=0.30,
        content_quality=0.25,
        educational_value=0.10,
        recency=0.10,
    ),
    preferred_content_types=["research", "official", "news"],
    # Pharma trust hierarchy: research journals > regulatory (FDA/EMA) > news > industry analysis
    source_type_multipliers={
        "research_paper":   1.40,
        "official_docs":    1.30,
        "news":             1.10,
        "educational":      0.95,
        "engineering_blog": 0.85,
        "unknown":          0.80,
        "content_farm":     0.35,
    },
    retrieval_strategy="extract_first",
    extract_targets=[
        ExtractTarget("https://clinicaltrials.gov/search", "ClinicalTrials.gov", "regulatory"),
        ExtractTarget("https://www.fda.gov/drugs/development-approval-process-drugs", "FDA drug approvals", "regulatory"),
        ExtractTarget("https://www.ema.europa.eu/en/medicines", "EMA medicines", "regulatory"),
        ExtractTarget("https://pubmed.ncbi.nlm.nih.gov/", "PubMed", "research"),
    ],
    crawl_targets=[],
    feed_retrieval_rules=FeedRetrievalRules(
        search_queries_per_package=2,
        max_results_per_query=7,
        search_depth="advanced",
        use_extract_for_known_urls=True,
    ),
    deep_research_rules=DeepResearchRules(
        max_search_queries=4,
        search_depth="advanced",
        max_extract_targets=5,
    ),
    prompt_context=(
        "Domain context: Pharmaceutical / Biotech\n"
        "- Cite clinical evidence levels (Phase I/II/III, RCT, meta-analysis).\n"
        "- Distinguish approved drugs from investigational compounds.\n"
        "- Reference regulatory frameworks (FDA, EMA, ICH guidelines) where relevant.\n"
        "- Use standard scientific nomenclature; define acronyms on first use."
    ),
)

_MANUFACTURING = DomainRetrievalConfig(
    key="manufacturing",
    display_name="Manufacturing",
    trusted_domains={
        "industryweek.com":          0.80,
        "manufacturingglobal.com":   0.75,
        "iso.org":                   1.00,
        "sme.org":                   0.85,
        "asq.org":                   0.85,
        "nist.gov":                  0.95,
        "iiot-world.com":            0.70,
        "themanufacturer.com":       0.75,
        "automationworld.com":       0.75,
        "controleng.com":            0.75,
        "sae.org":                   0.85,
        "abb.com":                   0.75,
        "siemens.com":               0.75,
        "ptc.com":                   0.70,
    },
    include_domains=[
        "iso.org", "industryweek.com", "sme.org",
        "asq.org", "nist.gov",
    ],
    query_expansion_terms=["industry 4.0", "automation", "2025", "lean manufacturing"],
    query_templates=[
        "{topic} industry 4.0 implementation 2025",
        "{topic} lean manufacturing best practices",
        "{topic} automation technology ROI",
    ],
    ranking_weights=RankingWeights(
        keyword_relevance=0.30,
        technical_depth=0.25,
        content_quality=0.20,
        educational_value=0.15,
        recency=0.10,
    ),
    preferred_content_types=["news", "tutorial", "official"],
    # Manufacturing trust hierarchy: official standards > research > news > educational
    source_type_multipliers={
        "official_docs":    1.30,
        "research_paper":   1.20,
        "news":             1.15,
        "educational":      1.10,
        "engineering_blog": 1.00,
        "unknown":          0.90,
        "content_farm":     0.35,
    },
    retrieval_strategy="search_first",
    extract_targets=[
        ExtractTarget("https://www.iso.org/standards.html", "ISO standards", "official"),
        ExtractTarget("https://www.nist.gov/manufacturing", "NIST manufacturing", "official"),
    ],
    crawl_targets=[],
    feed_retrieval_rules=FeedRetrievalRules(
        search_queries_per_package=2,
        max_results_per_query=6,
        search_depth="basic",
    ),
    deep_research_rules=DeepResearchRules(
        max_search_queries=3,
        search_depth="advanced",
    ),
    prompt_context=(
        "Domain context: Manufacturing\n"
        "- Frame insights in terms of OEE, throughput, quality, and cost impact.\n"
        "- Connect concepts to established frameworks (Lean, Six Sigma, ISO).\n"
        "- Emphasise practical, shop-floor applicability.\n"
        "- Reference real-world case studies where possible."
    ),
)

_EXPORT_TRADE = DomainRetrievalConfig(
    key="export_trade",
    display_name="Export / International Trade",
    trusted_domains={
        "wto.org":         1.00,
        "trade.gov":       0.95,
        "worldbank.org":   0.90,
        "iccwbo.org":      0.90,
        "unctad.org":      0.90,
        "customs.gov":     0.95,
        "dgft.gov.in":     0.90,
        "exim.gov":        0.85,
        "comtrade.un.org": 0.90,
        "fieo.org":        0.80,
        "tradeindiacom":   0.65,
        "freightos.com":   0.70,
    },
    include_domains=[
        "wto.org", "trade.gov", "iccwbo.org",
        "worldbank.org", "unctad.org",
    ],
    query_expansion_terms=["trade policy", "2025", "compliance", "tariff"],
    query_templates=[
        "{topic} trade policy tariff update 2025",
        "{topic} customs compliance regulations",
        "{topic} international trade agreement WTO",
    ],
    ranking_weights=RankingWeights(
        keyword_relevance=0.35,
        technical_depth=0.15,
        content_quality=0.25,
        educational_value=0.10,
        recency=0.15,
    ),
    preferred_content_types=["official", "news", "research"],
    # Export/Trade trust hierarchy: official policy > news > research > educational
    source_type_multipliers={
        "official_docs":    1.35,
        "news":             1.25,
        "research_paper":   1.10,
        "educational":      0.95,
        "engineering_blog": 0.85,
        "unknown":          0.80,
        "content_farm":     0.35,
    },
    retrieval_strategy="search_first",
    extract_targets=[
        ExtractTarget("https://www.wto.org/english/news_e/news_e.htm", "WTO news", "official"),
        ExtractTarget("https://www.trade.gov/topical-articles", "trade.gov articles", "official"),
    ],
    crawl_targets=[],
    feed_retrieval_rules=FeedRetrievalRules(
        search_queries_per_package=2,
        max_results_per_query=6,
        search_depth="basic",
    ),
    deep_research_rules=DeepResearchRules(
        max_search_queries=3,
        search_depth="advanced",
    ),
    prompt_context=(
        "Domain context: Export / International Trade\n"
        "- Reference the correct HS codes, Incoterms, and trade agreements.\n"
        "- Distinguish between compliance requirements across jurisdictions.\n"
        "- Flag currency and geopolitical risk factors where relevant.\n"
        "- Use standardised trade terminology (FOB, CIF, LC, etc.)."
    ),
)

_BUSINESS = DomainRetrievalConfig(
    key="business",
    display_name="Business / Strategy",
    trusted_domains={
        "hbr.org":            0.90,
        "mckinsey.com":       0.90,
        "bcg.com":            0.90,
        "bain.com":           0.85,
        "strategy-business.com": 0.85,
        "forbes.com":         0.70,
        "fortune.com":        0.75,
        "inc.com":            0.65,
        "entrepreneur.com":   0.60,
        "ycombinator.com":    0.80,
        "a16z.com":           0.80,
        "sequoiacap.com":     0.80,
        "crunchbase.com":     0.75,
        "statista.com":       0.75,
    },
    include_domains=[
        "hbr.org", "mckinsey.com", "bcg.com",
        "strategy-business.com", "ycombinator.com",
    ],
    query_expansion_terms=["strategy", "framework", "case study", "2025"],
    query_templates=[
        "{topic} business strategy framework",
        "{topic} case study examples 2025",
        "{topic} best practices execution",
    ],
    ranking_weights=RankingWeights(
        keyword_relevance=0.30,
        technical_depth=0.15,
        content_quality=0.25,
        educational_value=0.20,
        recency=0.10,
    ),
    preferred_content_types=["news", "research", "tutorial"],
    # Business trust hierarchy: analyst research > official > news > educational > blogs
    source_type_multipliers={
        "research_paper":   1.25,
        "official_docs":    1.20,
        "news":             1.15,
        "educational":      1.10,
        "engineering_blog": 1.10,
        "unknown":          0.90,
        "content_farm":     0.35,
    },
    retrieval_strategy="search_first",
    extract_targets=[],
    crawl_targets=[],
    feed_retrieval_rules=FeedRetrievalRules(
        search_queries_per_package=2,
        max_results_per_query=6,
        search_depth="basic",
    ),
    deep_research_rules=DeepResearchRules(
        max_search_queries=3,
        search_depth="advanced",
    ),
    prompt_context=(
        "Domain context: Business / Strategy\n"
        "- Ground recommendations in established frameworks (Porter's 5, SWOT, OKR, etc.).\n"
        "- Provide concrete examples from recognisable companies where helpful.\n"
        "- Balance strategic thinking with execution-level practicality.\n"
        "- Avoid jargon; favour clear, actionable language."
    ),
)

_DEFAULT = DomainRetrievalConfig(
    key="default",
    display_name="General",
    trusted_domains={
        "wikipedia.org":      0.75,
        "github.com":         0.80,
        "stackoverflow.com":  0.75,
    },
    include_domains=[],
    query_expansion_terms=["overview", "guide", "2025"],
    query_templates=[
        "{topic} overview guide 2025",
        "{topic} explained examples",
    ],
    ranking_weights=RankingWeights(),
    preferred_content_types=["tutorial", "news"],
    retrieval_strategy="search_first",
    feed_retrieval_rules=FeedRetrievalRules(
        search_queries_per_package=1,
        max_results_per_query=5,
        search_depth="basic",
    ),
    deep_research_rules=DeepResearchRules(
        max_search_queries=2,
        search_depth="basic",
    ),
    prompt_context="",
)


# ── Registry ──────────────────────────────────────────────────────────────────

DOMAIN_CONFIGS: dict[str, DomainRetrievalConfig] = {
    "ai":           _AI,
    "technology":   _TECHNOLOGY,
    "finance":      _FINANCE,
    "pharma":       _PHARMA,
    "manufacturing": _MANUFACTURING,
    "export_trade": _EXPORT_TRADE,
    "business":     _BUSINESS,
    "default":      _DEFAULT,
}

# Maps classifier domain names (from domain_classifier_service) to config keys.
CLASSIFIER_NAME_MAP: dict[str, str] = {
    "AI":                  "ai",
    "Technology":          "technology",
    "Finance":             "finance",
    "Pharmaceutical":      "pharma",
    "Manufacturing":       "manufacturing",
    "Export/Trade":        "export_trade",
    "Business":            "business",
    "General":             "default",
}


# ── Public API ────────────────────────────────────────────────────────────────

def get_domain_config(domain: str) -> DomainRetrievalConfig:
    """
    Return the DomainRetrievalConfig for a given key or classifier domain name.

    Accepts:
      - Canonical config keys: "ai", "finance", "pharma", …
      - Classifier names: "AI", "Finance", "Pharmaceutical", …
      - Case-insensitive canonical keys: "Finance" → "finance"

    Falls back to the "default" config for unknown domains.
    """
    # Direct canonical key (lowercase)
    normalized = domain.strip().lower().replace("/", "_").replace(" ", "_")
    if normalized in DOMAIN_CONFIGS:
        return DOMAIN_CONFIGS[normalized]

    # Classifier name mapping
    mapped = CLASSIFIER_NAME_MAP.get(domain)
    if mapped and mapped in DOMAIN_CONFIGS:
        return DOMAIN_CONFIGS[mapped]

    return DOMAIN_CONFIGS["default"]


def get_authority_domains(domain: str) -> dict[str, float]:
    """Convenience accessor — returns the editorial authority-reputation map for a learning domain."""
    return get_domain_config(domain).trusted_domains


def get_query_templates(domain: str) -> list[str]:
    """Convenience accessor — returns query templates for a domain."""
    return get_domain_config(domain).query_templates


def get_source_type_multipliers(domain: str) -> dict[str, float]:
    """
    Return the source-type multiplier table for a domain.

    Returns an empty dict when the domain has no overrides, signalling the
    caller to fall back to its own generic multiplier table.
    """
    return get_domain_config(domain).source_type_multipliers


def build_retrieval_query(topic: str, domain: str, template_index: int = 0) -> str:
    """
    Return a domain-optimised Tavily search query for a topic.

    template_index selects which query template to use (0 = primary).
    Falls back to the first template when the index is out of range.
    """
    templates = get_query_templates(domain)
    template = templates[min(template_index, len(templates) - 1)]
    return template.format(topic=topic)
