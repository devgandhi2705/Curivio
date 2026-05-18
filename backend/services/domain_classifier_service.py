"""
Domain classification for the AI research companion.

Classifies any user query or topic into one of 7 business domains and returns
domain-specific configuration for retrieval, resource discovery, and explanation
style.  Entirely rule-based — no ML models, no API calls.

Domains
-------
  Technology      General software, hardware, cloud, DevOps, cybersecurity
  AI              Machine learning, LLMs, neural networks, data science
  Finance         Markets, banking, investment, fintech, accounting
  Business        Strategy, management, operations, HR, marketing
  Pharmaceutical  Drug development, clinical trials, biotech, regulatory
  Manufacturing   Production, supply chain, Industry 4.0, quality control
  Export/Trade    International trade, customs, logistics, compliance, tariffs

Public API
----------
classify_domain(text)         → str   one of DOMAINS
get_domain_context(text)      → dict  retrieval + resources + explanation config
format_domain_directive(text) → str   ready-to-inject prompt section
"""

from __future__ import annotations

import re
from ..config.retrieval_config import (
    get_domain_config,
    build_retrieval_query as _config_build_query,
    CLASSIFIER_NAME_MAP,
)

# ── Domain taxonomy ───────────────────────────────────────────────────────────

DOMAIN_UNCATEGORIZED = "General"

DOMAIN_PRIORITY: list[str] = [
    "Pharmaceutical",   # very specific vocabulary — classify before Business
    "AI",               # specific ML vocab — classify before Technology
    "Finance",          # financial terms overlap with Business; goes first
    "Manufacturing",
    "Export/Trade",
    "Technology",
    "Business",
    DOMAIN_UNCATEGORIZED,
]

DOMAINS: list[str] = DOMAIN_PRIORITY

_DOMAIN_KEYWORDS: dict[str, frozenset[str]] = {
    "Pharmaceutical": frozenset({
        "pharma", "pharmaceutical", "drug", "clinical", "trial", "fda",
        "ema", "biotech", "biotechnology", "molecule", "compound",
        "therapeutics", "oncology", "genomics", "proteomics", "antibody",
        "vaccine", "pharmacology", "pharmacokinetics", "regulatory",
        "gmp", "ich", "nda", "biologics", "biosimilar", "cro",
        "preclinical", "phase", "efficacy", "safety", "adverse",
        "indication", "medtech", "diagnostics",
    }),
    "AI": frozenset({
        "machine", "learning", "neural", "network", "deep", "llm",
        "language", "model", "transformer", "gpt", "bert", "embedding",
        "inference", "training", "finetuning", "rag", "vector",
        "diffusion", "generative", "reinforcement", "agent", "agents",
        "classification", "regression", "clustering", "nlp", "computer",
        "vision", "multimodal", "dataset", "benchmark", "pytorch",
        "tensorflow", "huggingface", "openai", "anthropic", "groq",
        "artificial", "intelligence", "algorithm", "prediction",
    }),
    "Finance": frozenset({
        "finance", "financial", "market", "stock", "equity", "bond",
        "trading", "investment", "portfolio", "hedge", "fund",
        "banking", "bank", "credit", "risk", "derivative", "option",
        "options", "pricing", "futures", "forex", "cryptocurrency",
        "crypto", "blockchain", "fintech", "payment", "insurance",
        "actuarial", "accounting", "audit", "tax", "valuation",
        "capital", "asset", "liability", "balance", "cashflow",
        "revenue", "ebitda", "roi", "blackscholes",
    }),
    "Manufacturing": frozenset({
        "manufacturing", "production", "factory", "plant", "assembly",
        "automation", "robot", "robotics", "plc", "scada", "iot",
        "industry", "lean", "sixsigma", "kaizen", "kanban", "quality",
        "control", "defect", "yield", "throughput", "oee", "maintenance",
        "predictive", "cnc", "additive", "printing", "casting", "welding",
        "procurement", "bom", "erp", "mes", "iso9001",
    }),
    "Export/Trade": frozenset({
        "export", "import", "trade", "tariff", "customs", "logistics",
        "shipping", "freight", "container", "incoterm", "fob", "cif",
        "letter", "credit", "documentary", "compliance", "sanction",
        "embargo", "quota", "wto", "fta", "gst", "vat", "duty",
        "clearance", "forwarder", "3pl", "warehouse", "crossborder",
        "bilateral", "multilateral", "exim", "dgft", "hscode",
    }),
    "Technology": frozenset({
        "software", "hardware", "cloud", "aws", "azure", "gcp",
        "kubernetes", "docker", "devops", "cicd", "api", "microservices",
        "database", "sql", "nosql", "architecture", "backend", "frontend",
        "mobile", "web", "cybersecurity", "security", "encryption",
        "networking", "protocol", "linux", "kernel", "compiler",
        "programming", "code", "developer", "engineering", "system",
        "platform", "infrastructure", "saas", "paas", "serverless",
    }),
    "Business": frozenset({
        "business", "strategy", "management", "leadership", "operations",
        "marketing", "sales", "growth", "startup", "venture", "vc",
        "funding", "revenue", "customer", "product", "launch", "pivot",
        "team", "hr", "hiring", "culture", "okr", "kpi", "agile",
        "scrum", "consulting", "mckinsey", "merger", "acquisition",
        "governance", "compliance", "ceo", "cfo", "cto",
    }),
    DOMAIN_UNCATEGORIZED: frozenset(),
}

_MIN_MATCH = 1


# ── Resource discovery ────────────────────────────────────────────────────────

_RESOURCE_CONFIG: dict[str, dict] = {
    "AI": {
        "primary_sources":  ["arXiv", "Hugging Face", "Papers With Code", "GitHub"],
        "databases":        ["Semantic Scholar", "Google Scholar"],
        "communities":      ["r/MachineLearning", "AI Twitter/X", "Discord ML servers"],
        "tools":            ["Jupyter", "PyTorch", "Weights & Biases"],
    },
    "Finance": {
        "primary_sources":  ["SEC EDGAR", "Bloomberg", "Financial Times", "Reuters"],
        "databases":        ["WRDS", "Compustat", "FRED"],
        "communities":      ["CFA Institute", "r/finance", "QuantLib community"],
        "tools":            ["Bloomberg Terminal", "FactSet", "Python (pandas, yfinance)"],
    },
    "Pharmaceutical": {
        "primary_sources":  ["PubMed / MEDLINE", "ClinicalTrials.gov", "FDA", "EMA"],
        "databases":        ["DrugBank", "ChEMBL", "UniProt"],
        "communities":      ["BioMed Central", "AAPS", "Drug Information Association"],
        "tools":            ["RDKit", "Benchling", "Certara"],
    },
    "Manufacturing": {
        "primary_sources":  ["ISO standards", "Industry Week", "SAE International"],
        "databases":        ["IHS Markit", "Dun & Bradstreet supply chain data"],
        "communities":      ["SME (Society of Manufacturing Engineers)", "ASQ"],
        "tools":            ["SAP ERP", "Siemens MindSphere", "PTC ThingWorx"],
    },
    "Export/Trade": {
        "primary_sources":  ["WTO", "World Bank Trade Data", "ITC Trade Map"],
        "databases":        ["UN Comtrade", "WITS", "DGFT (India)"],
        "communities":      ["ICC (International Chamber of Commerce)", "FIEO"],
        "tools":            ["Trade compliance software", "HS code classifiers"],
    },
    "Technology": {
        "primary_sources":  ["GitHub", "MDN Web Docs", "AWS/Azure/GCP docs"],
        "databases":        ["npm registry", "PyPI", "CNCF landscape"],
        "communities":      ["Stack Overflow", "Dev.to", "Hacker News"],
        "tools":            ["VS Code", "Postman", "Terraform", "k9s"],
    },
    "Business": {
        "primary_sources":  ["Harvard Business Review", "McKinsey Insights", "BCG"],
        "databases":        ["Statista", "IBISWorld", "Crunchbase"],
        "communities":      ["YC Startup School", "Indie Hackers", "LinkedIn groups"],
        "tools":            ["Notion", "Tableau", "Salesforce"],
    },
    DOMAIN_UNCATEGORIZED: {
        "primary_sources":  ["Wikipedia", "Google Scholar"],
        "databases":        [],
        "communities":      [],
        "tools":            [],
    },
}


# ── Tokenisation (shared with topic_cluster pattern) ─────────────────────────

def _tokenise(text: str) -> frozenset[str]:
    lower  = text.lower()
    merged = re.sub(r"-", "", lower)
    raw    = re.sub(r"[^\w\s]", " ", lower)
    tokens: set[str] = set()
    for source in (raw, merged):
        for w in source.split():
            if len(w) >= 3:
                tokens.add(w)
    return frozenset(tokens)


# ── Public API ────────────────────────────────────────────────────────────────

def classify_domain(text: str) -> str:
    """
    Return the best-matching business domain for a query or topic string.

    Uses keyword overlap scoring with priority-order tie-breaking.
    Returns DOMAIN_UNCATEGORIZED ("General") when nothing matches.
    """
    tokens = _tokenise(text)
    best   = DOMAIN_UNCATEGORIZED
    best_score = _MIN_MATCH - 1

    for domain in DOMAIN_PRIORITY:
        keywords = _DOMAIN_KEYWORDS.get(domain, frozenset())
        score    = len(tokens & keywords)
        if score > best_score:
            best_score = score
            best       = domain

    return best


def get_domain_context(text: str) -> dict:
    """
    Return a rich context dict for a query or topic string.

    Shape
    -----
    {
      "domain":     str,                    # classifier domain name
      "config_key": str,                    # retrieval_config key (e.g. "pharma")
      "retrieval":  DomainRetrievalConfig,  # full retrieval config object
      "resources":  dict,                   # databases, communities, tools
      "directive":  str,                    # ready-to-inject prompt fragment
    }
    """
    domain     = classify_domain(text)
    config_key = CLASSIFIER_NAME_MAP.get(domain, "default")
    cfg        = get_domain_config(config_key)
    return {
        "domain":     domain,
        "config_key": config_key,
        "retrieval":  cfg,
        "resources":  _RESOURCE_CONFIG.get(domain, _RESOURCE_CONFIG[DOMAIN_UNCATEGORIZED]),
        "directive":  cfg.prompt_context,
    }


def format_domain_directive(text: str) -> str:
    """
    Convenience wrapper — returns only the directive string for a query or topic.

    Returns an empty string for unclassified input so the caller can safely
    omit the section without special-casing.
    """
    return get_domain_context(text)["directive"]


def build_retrieval_query(topic: str, template_index: int = 0) -> str:
    """
    Return a domain-optimised Tavily search query for a topic.

    template_index selects which query template to use (0 = primary).
    Falls back to the first template when the index is out of range.
    Delegates to retrieval_config.build_retrieval_query.
    """
    domain     = classify_domain(topic)
    config_key = CLASSIFIER_NAME_MAP.get(domain, "default")
    return _config_build_query(topic, config_key, template_index)
