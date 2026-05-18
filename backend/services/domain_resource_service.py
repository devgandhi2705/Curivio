"""
Domain-aware resource discovery for the AI research companion.

Each business domain has a tailored "fetch plan" — a set of Tavily query
templates plus an optional GitHub lookup — that returns resources meaningful
to practitioners in that domain rather than generic tutorial links.

Domain resource strategies
--------------------------
  Technology    : GitHub repos + official docs + tutorials
  AI            : GitHub repos + arXiv/HF papers + benchmarks
  Finance       : macro trends + quant research + market intelligence
  Business      : industry reports + market analysis + case studies
  Pharmaceutical: PubMed/clinical + regulatory guidance + pipeline news
  Manufacturing : industry benchmarks + supply-chain + trade reports
  Export/Trade  : trade data + customs/compliance + logistics analysis

Public API
----------
discover_resources(topic, domain=None, max_per_group=5) -> dict
get_domain_search_queries(topic, domain=None)           -> list[str]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── Resource-group descriptor ─────────────────────────────────────────────────

@dataclass
class _ResourceGroup:
    label:         str          # human-readable label shown to the user
    resource_type: str          # "articles" | "repos" | "reports" | "papers"
    query_template: str         # {topic} placeholder → Tavily query
    include_repos:  bool = False # whether to also fetch GitHub repos for this group


# ── Per-domain fetch plans ────────────────────────────────────────────────────
# Each list entry is fetched as a separate Tavily call (or GitHub call if
# include_repos=True). Order matters: primary resources come first.

_DOMAIN_PLANS: dict[str, list[_ResourceGroup]] = {
    "Technology": [
        _ResourceGroup(
            label="GitHub Repositories",
            resource_type="repos",
            query_template="{topic} open source library github",
            include_repos=True,
        ),
        _ResourceGroup(
            label="Official Documentation & Guides",
            resource_type="docs",
            query_template="{topic} official documentation guide site:docs.* OR site:github.io OR site:readthedocs.io",
        ),
        _ResourceGroup(
            label="Tutorials & How-Tos",
            resource_type="tutorials",
            query_template="{topic} step by step tutorial beginner 2024 2025",
        ),
    ],
    "AI": [
        _ResourceGroup(
            label="GitHub Repositories",
            resource_type="repos",
            query_template="{topic} machine learning implementation github",
            include_repos=True,
        ),
        _ResourceGroup(
            label="Research Papers & Benchmarks",
            resource_type="papers",
            query_template="{topic} arxiv paper benchmark results 2024 2025",
        ),
        _ResourceGroup(
            label="Practical Guides & Notebooks",
            resource_type="tutorials",
            query_template="{topic} huggingface colab notebook tutorial practical",
        ),
    ],
    "Finance": [
        _ResourceGroup(
            label="Macro Trends & Economic Analysis",
            resource_type="reports",
            query_template="{topic} macro trend economic analysis 2025",
        ),
        _ResourceGroup(
            label="Quantitative Research",
            resource_type="papers",
            query_template="{topic} quantitative research white paper methodology",
        ),
        _ResourceGroup(
            label="Market Intelligence",
            resource_type="articles",
            query_template="{topic} market intelligence report outlook Bloomberg Reuters 2025",
        ),
    ],
    "Business": [
        _ResourceGroup(
            label="Industry Reports",
            resource_type="reports",
            query_template="{topic} industry report analysis McKinsey BCG 2025",
        ),
        _ResourceGroup(
            label="Market Analysis",
            resource_type="articles",
            query_template="{topic} market analysis competitive landscape 2025",
        ),
        _ResourceGroup(
            label="Case Studies & Company Insights",
            resource_type="articles",
            query_template="{topic} company case study business insights examples",
        ),
    ],
    "Pharmaceutical": [
        _ResourceGroup(
            label="Clinical & Research Papers",
            resource_type="papers",
            query_template="{topic} clinical trial results pubmed 2024 2025",
        ),
        _ResourceGroup(
            label="Regulatory Guidance",
            resource_type="articles",
            query_template="{topic} FDA EMA regulatory guidance approval 2025",
        ),
        _ResourceGroup(
            label="Pipeline & Industry News",
            resource_type="articles",
            query_template="{topic} drug pipeline development biotech news 2025",
        ),
    ],
    "Manufacturing": [
        _ResourceGroup(
            label="Industry Benchmarks & Standards",
            resource_type="reports",
            query_template="{topic} manufacturing benchmark lean six sigma ISO standard",
        ),
        _ResourceGroup(
            label="Supply Chain & Logistics Analysis",
            resource_type="articles",
            query_template="{topic} supply chain logistics analysis 2025",
        ),
        _ResourceGroup(
            label="Trade & Production Reports",
            resource_type="reports",
            query_template="{topic} manufacturing trade report production insight 2025",
        ),
    ],
    "Export/Trade": [
        _ResourceGroup(
            label="Trade Data & Reports",
            resource_type="reports",
            query_template="{topic} WTO trade data report statistics 2025",
        ),
        _ResourceGroup(
            label="Customs & Compliance Guidance",
            resource_type="articles",
            query_template="{topic} customs compliance tariff regulation guide",
        ),
        _ResourceGroup(
            label="Logistics & Freight Analysis",
            resource_type="articles",
            query_template="{topic} logistics freight shipping analysis 2025",
        ),
    ],
}

_FALLBACK_PLAN: list[_ResourceGroup] = [
    _ResourceGroup(
        label="Articles & Resources",
        resource_type="articles",
        query_template="{topic} overview guide resource 2025",
    ),
]


# ── Public API ────────────────────────────────────────────────────────────────

def discover_resources(
    topic: str,
    domain: str | None = None,
    max_per_group: int = 5,
) -> dict:
    """
    Fetch and return domain-appropriate resources for *topic*.

    Return shape
    ------------
    {
      "domain":          str,
      "resource_groups": [
        {
          "label":         str,   # e.g. "GitHub Repositories"
          "resource_type": str,   # "repos" | "articles" | "reports" | "papers" | "docs" | "tutorials"
          "items":         list[dict],  # {title, url, content/description}
          "query_used":    str,
        },
        ...
      ],
    }

    Partial failures (one group's fetch failing) are logged and skipped;
    the remaining groups are still returned.
    """
    from .domain_classifier_service import classify_domain

    if not domain:
        domain = classify_domain(topic)

    plan = _DOMAIN_PLANS.get(domain, _FALLBACK_PLAN)

    resource_groups: list[dict] = []

    for group in plan:
        query = group.query_template.format(topic=topic)
        items: list[dict] = []

        # Repos group: try GitHub first, fall back to Tavily articles
        if group.include_repos:
            try:
                from .github_service import get_topic_repos
                repos = get_topic_repos(topic)
                items = [
                    {
                        "title":       r.get("name", ""),
                        "url":         r.get("url",  ""),
                        "description": r.get("description", ""),
                        "stars":       r.get("stars", 0),
                    }
                    for r in repos[:max_per_group]
                ]
            except Exception:
                logger.warning(
                    "[domain_resource] GitHub fetch failed for %r, falling back to Tavily", topic
                )

        # All groups also run Tavily if repos didn't fill the quota
        if len(items) < max_per_group:
            try:
                from .tavily_service import search_articles
                results = search_articles(query)
                for r in results[: max_per_group - len(items)]:
                    items.append({
                        "title":   r.get("title",   ""),
                        "url":     r.get("url",     ""),
                        "content": r.get("content", ""),
                    })
            except Exception:
                logger.warning(
                    "[domain_resource] Tavily fetch failed for query %r", query
                )

        if not items:
            continue  # skip empty groups rather than returning blank sections

        resource_groups.append({
            "label":         group.label,
            "resource_type": group.resource_type,
            "items":         items,
            "query_used":    query,
        })

    return {
        "domain":          domain,
        "resource_groups": resource_groups,
    }


def get_domain_search_queries(topic: str, domain: str | None = None) -> list[str]:
    """
    Return the ordered list of Tavily query strings for a topic and domain.

    Useful for `deep_research_service._expand_queries` — lets the deep-research
    workflow use domain-optimised angles instead of the generic fallback templates.
    """
    from .domain_classifier_service import classify_domain

    if not domain:
        domain = classify_domain(topic)

    plan = _DOMAIN_PLANS.get(domain, _FALLBACK_PLAN)
    return [g.query_template.format(topic=topic) for g in plan]


def build_resource_instruction(topic: str, resource_result: dict) -> str:
    """
    Build a ready-to-inject prompt section from a discover_resources() result.

    Used by action_router_service to tell the AI what domain resources were
    found and how to present them.
    """
    domain  = resource_result.get("domain", "General")
    groups  = resource_result.get("resource_groups", [])

    if not groups:
        return (
            f"Action: FIND DOMAIN RESOURCES\n"
            f"Domain: {domain}\n"
            f"No resources found for \"{topic}\" in the {domain} domain. "
            "Recommend the key sources practitioners in this field use, "
            "and explain what the user should search for."
        )

    lines = [
        f"Action: FIND DOMAIN RESOURCES",
        f"Domain: {domain}",
        f"The user wants {domain}-specific resources for \"{topic}\".",
        "Found the following resource groups:",
    ]
    for group in groups:
        lines.append(f"\n[{group['label']}]")
        for item in group["items"][:4]:
            title = item.get("title") or item.get("name", "Resource")
            url   = item.get("url", "")
            lines.append(f"  - {title}: {url}")

    lines.append(
        "\nPresent these resources clearly grouped by type. For each group, "
        "briefly explain what the user will find there and which resource to "
        "start with given their level. Prioritise the most actionable items."
    )
    return "\n".join(lines)
