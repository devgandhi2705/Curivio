"""
Conversational research action router.

Detects structured research intents in user messages (via regex) and dispatches
them to existing cached backend workflows — no new LLM calls during detection.

Actions
-------
  explain_simply     — surface deep-research summary at beginner depth
  compare            — show topic relationships via expansion data
  find_tutorials     — search for practical tutorial resources (Tavily, cached)
  beginner_resources — extract beginner steps from stored learning path
  show_repos         — retrieve / fetch GitHub repositories (cache-first)
  learning_roadmap   — return full structured learning path (cache-first)

Each action returns a dict with:
  action      : str            — action type key
  topic       : str
  found       : bool           — whether workflow data was available
  data        : dict           — raw payload from the backend service
  instruction : str            — ready-to-inject system-prompt fragment

Public API
----------
detect_action(message)                        -> str | None
dispatch_action(action, topic, context)       -> dict
route(message, topic, context)                -> dict | None
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ── Intent detection ──────────────────────────────────────────────────────────

# Ordered by priority — first match wins.
_ACTION_PATTERNS: list[tuple[str, list[str]]] = [
    ("industry_brief", [
        r"\bindustry (trend|outlook|intelligence|analysis|brief|insight)\w*\b",
        r"\bmarket (trend|outlook|intelligence|analysis|brief|update)\w*\b",
        r"\bwhat('s| is) happening in\b",
        r"\b(finance|pharma|manufacturing|export|trade) (trends?|news|outlook|update)\b",
        r"\bai (business|ecosystem|market|landscape)\b",
        r"\bindustry news\b",
        r"\bsector (analysis|outlook|brief)\b",
        r"\bbusiness (intelligence|impact|climate)\b",
    ]),
    ("compare", [
        r"\bcompar\w*\b",
        r"\bvs\.?\b",
        r"\bversus\b",
        r"\bdifference between\b",
        r"\bpros and cons\b",
        r"\bwhat('s| is) the difference\b",
    ]),
    ("show_repos", [
        r"\brepos?\b",
        r"\brepositor\w+\b",
        r"\bgithub\b",
        r"\bopen.?source\b",
        r"\bcode example\w*\b",
        r"\bimplementation example\w*\b",
        r"\bshow.{0,20}\bcode\b",
    ]),
    ("learning_roadmap", [
        r"\broadmap\b",
        r"\blearning path\b",
        r"\bcurriculum\b",
        r"\bstudy plan\b",
        r"\bstep.by.step\b",
        r"\bwhere (should i|do i|to) start\b",
        r"\bfull (course|guide|plan)\b",
    ]),
    ("find_tutorials", [
        r"\btutorial\w*\b",
        r"\bpractical\b.{0,30}\b(guide|example|resource)\b",
        r"\bhands.?on\b",
        r"\bhow.to guide\b",
    ]),
    ("research_report", [
        r"\b(generate|create|produce|build|make)\s+(a\s+)?(research\s+|deep\s+)?report\b",
        r"\bresearch report\b",
        r"\bdeep.?research report\b",
        r"\bfull report\b",
        r"\bdetailed report\b",
        r"\bstructured report\b",
        r"\bexport (my\s+)?research\b",
        r"\bformat (my\s+)?(findings|research|analysis)\b",
        r"\bwrite (up\s+)?a report\b",
    ]),
    ("find_reports", [
        r"\breport\w*\b",
        r"\bmarket (analysis|intelligence|research)\b",
        r"\bindustry (analysis|insight|data)\b",
        r"\btrade (data|report|analysis)\b",
        r"\bwhite.?paper\b",
        r"\bcase study\b",
        r"\bsupply chain\b",
        r"\bregulatory (guidance|update|doc)\b",
        r"\bclinical (trial|data|evidence)\b",
        r"\bquantitative research\b",
        r"\bmacro trend\b",
    ]),
    ("beginner_resources", [
        r"\bbeginner\b",
        r"\bget(?:ting)? started\b",
        r"\bnewbie\b",
        r"\bfor dummies\b",
        r"\brecommend\w*\b.{0,40}\bresource\w*\b",
        r"\bresource\w*\b.{0,40}\brecommend\w*\b",
        r"\bwhere (should i|do i) start\b",
        r"\bstart (learning|with)\b",
    ]),
    ("explain_simply", [
        r"\bexplain\b.{0,40}\bsimpl\w+\b",
        r"\bsimpl\w+\b.{0,40}\bexplain\b",
        r"\beli5\b",
        r"\blike i('m| am) (5|five|a kid|a beginner|new)\b",
        r"\bin simple terms\b",
        r"\blayperson\b",
        r"\bno jargon\b",
    ]),
]


def detect_action(message: str) -> str | None:
    """
    Return the action key if *message* matches a known intent, else None.

    Detection is purely regex-based — deterministic, fast, no AI call.
    The first pattern group to match wins (priority order in _ACTION_PATTERNS).
    """
    lower = message.lower()
    for action_key, patterns in _ACTION_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, lower):
                return action_key
    return None


# ── Action dispatch ───────────────────────────────────────────────────────────

def dispatch_action(action: str, topic: str, context: dict) -> dict:
    """
    Run the workflow for *action* on *topic* and return a result dict.

    Uses cache-first pipelines where possible so chat responses stay fast.
    Falls back to a graceful "not found" result rather than raising.
    """
    handlers = {
        "industry_brief":     _handle_industry_brief,
        "research_report":    _handle_research_report,
        "explain_simply":     _handle_explain_simply,
        "compare":            _handle_compare,
        "find_tutorials":     _handle_find_tutorials,
        "find_reports":       _handle_find_reports,
        "beginner_resources": _handle_beginner_resources,
        "show_repos":         _handle_show_repos,
        "learning_roadmap":   _handle_learning_roadmap,
    }
    handler = handlers.get(action)
    if handler is None:
        return _empty(action, topic)

    try:
        return handler(topic, context)
    except Exception:
        logger.exception("action_router: dispatch failed for action=%r topic=%r", action, topic)
        return _empty(action, topic)


def route(
    message: str,
    topic: str | None,
    context: dict,
) -> dict | None:
    """
    Detect the action in *message* and dispatch it.

    Returns None when no action is detected or *topic* is missing.
    """
    action = detect_action(message)
    if action is None:
        return None
    if not topic or not topic.strip():
        return None
    return dispatch_action(action, topic.strip(), context)


# ── Individual action handlers ────────────────────────────────────────────────

def _handle_industry_brief(topic: str, context: dict) -> dict:
    """
    Generate or retrieve a cached industry intelligence brief.

    Detects which industry to brief based on (in priority order):
    1. The domain_context already in context (set by chat_service)
    2. Topic-keyword matching via detect_industry_from_text
    3. Falls back to the user's message topic as a generic brief request
    """
    from .industry_intelligence_service import (
        analyze_industry,
        detect_industry_from_text,
    )

    # Try to identify the industry from context or topic text
    domain_ctx  = context.get("domain_context", {})
    domain_name = domain_ctx.get("domain", "")

    # Map chat domain classifier names → industry keys
    _DOMAIN_TO_INDUSTRY = {
        "Finance":        "finance",
        "Pharmaceutical": "pharma",
        "Manufacturing":  "manufacturing",
        "Export/Trade":   "exports",
        "AI":             "ai_business",
    }
    industry_key = _DOMAIN_TO_INDUSTRY.get(domain_name) or detect_industry_from_text(topic)

    if industry_key is None:
        instruction = (
            f"Action: INDUSTRY BRIEF\n"
            f"The user wants an industry intelligence brief related to \"{topic}\", "
            "but no specific industry was detected.\n"
            "Ask which of these industries they are most interested in: "
            "Finance, Pharma, Manufacturing, Export/Trade, or AI Business Ecosystem. "
            "Then explain what kind of intelligence brief you can generate for each."
        )
        return _result("industry_brief", topic, False, {}, instruction)

    try:
        brief = analyze_industry(industry_key)
    except Exception:
        logger.exception(
            "action_router: industry_brief generation failed for %r", industry_key
        )
        instruction = (
            f"Action: INDUSTRY BRIEF\n"
            f"Failed to retrieve a live intelligence brief for industry {industry_key!r}. "
            "Draw on your own knowledge to summarise the most important current trends, "
            "3 notable market developments, and 3 emerging opportunities in this industry. "
            "Be specific and business-impact-focused."
        )
        return _result("industry_brief", topic, False, {}, instruction)

    # Build the prompt injection from the brief
    developments = brief.get("market_developments", [])
    opportunities = brief.get("emerging_opportunities", [])
    key_signals   = brief.get("key_signals", [])

    dev_block = "\n".join(
        f"  - {d.get('title', '')}: {d.get('business_impact', '')}"
        for d in developments[:3]
    )
    opp_block = "\n".join(
        f"  - [{o.get('time_horizon', '')}] {o.get('opportunity', '')}"
        for o in opportunities[:3]
    )
    signals_block = "\n".join(f"  - {s}" for s in key_signals[:3])

    instruction = (
        f"Action: INDUSTRY BRIEF — {brief.get('industry', industry_key)}\n"
        f"Trend summary: {brief.get('trend_summary', '')}\n\n"
        f"Market developments:\n{dev_block}\n\n"
        f"Emerging opportunities:\n{opp_block}\n\n"
        f"Key signals:\n{signals_block}\n\n"
        "Present this as a concise, decision-ready industry intelligence brief. "
        "Lead with the trend summary. Group developments, then opportunities. "
        "Close with 1–2 sentences connecting this to what the user has been learning."
    )
    return _result("industry_brief", topic, True, brief, instruction)


def _handle_research_report(topic: str, context: dict) -> dict:
    """
    Generate a structured research report from stored deep-research data.

    If deep research has already been run for the topic, formats it into a
    professional multi-section report (executive summary, key findings, trend
    analysis, opportunities/risks, resources, sources) and returns the
    markdown as the LLM instruction.

    Falls back gracefully when no research is stored — prompts the user to
    run deep research first.
    """
    from .deep_research_service       import get_stored_research
    from .research_report_service     import generate_report, format_report_as_markdown

    research = get_stored_research(topic)
    if not research:
        instruction = (
            f"Action: RESEARCH REPORT\n"
            f"No deep research has been stored for \"{topic}\" yet.\n"
            "Tell the user that you need to perform deep research first before "
            "generating a report.  Offer to run deep research now and then produce "
            "the report once it completes.  Explain briefly what the report will include: "
            "executive summary, key findings, trend analysis, opportunities and risks, "
            "important resources, and source references."
        )
        return _result("research_report", topic, False, {}, instruction)

    industry_data = context.get("industry_brief")  # optional enrichment
    report        = generate_report(topic, research, industry_data)
    md            = format_report_as_markdown(report)

    instruction = (
        f"Action: RESEARCH REPORT\n"
        f"A structured deep research report for \"{topic}\" has been generated.\n"
        f"Present the following report to the user exactly as formatted.\n"
        f"Do not add commentary before or after — the report is self-contained.\n\n"
        f"{md}"
    )
    return _result("research_report", topic, True, report, instruction)


def _handle_explain_simply(topic: str, context: dict) -> dict:
    """Use stored deep-research summary; fall back to expansion overview."""
    from .deep_research_service import get_stored_research

    research = get_stored_research(topic)
    if research:
        analysis = research.get("analysis", {})
        summary  = analysis.get("summary") or analysis.get("overview", "")
        concepts = analysis.get("key_concepts", [])
        data = {"summary": summary[:500], "key_concepts": concepts[:6]}
        instruction = (
            f"Action: EXPLAIN SIMPLY\n"
            f"The user wants a clear, beginner-friendly explanation of \"{topic}\".\n"
            f"Use the following research as your basis:\n"
            f"Summary: {summary[:400]}\n"
            + (f"Key concepts: {', '.join(str(c) for c in concepts[:6])}\n" if concepts else "")
            + "Present a jargon-free explanation with at least one real-world analogy. "
            "Build from the summary — do not just repeat it verbatim."
        )
        return _result("explain_simply", topic, True, data, instruction)

    # No stored research — instruct AI to explain from its own knowledge
    instruction = (
        f"Action: EXPLAIN SIMPLY\n"
        f"The user wants a simple explanation of \"{topic}\" (no prior research stored).\n"
        "Explain from first principles using plain language. "
        "No jargon. Use at least one relatable analogy."
    )
    return _result("explain_simply", topic, False, {}, instruction)


def _handle_compare(topic: str, context: dict) -> dict:
    """Use stored topic expansion to show relationships and contrasts."""
    from .topic_expansion_service import get_stored_expansion

    expansion = get_stored_expansion(topic)
    if expansion:
        related  = expansion.get("related_topics", [])[:5]
        prereqs  = expansion.get("prerequisites", [])[:4]
        advanced = expansion.get("advanced_follow_ups", [])[:3]
        data = {"related": related, "prerequisites": prereqs, "advanced": advanced}
        instruction = (
            f"Action: COMPARE / CONTEXTUALISE\n"
            f"The user wants to compare or contextualise \"{topic}\" against peers.\n"
            f"Related / peer technologies: {', '.join(related) or 'none stored'}.\n"
            f"Prerequisites (what you need first): {', '.join(prereqs) or 'none stored'}.\n"
            f"What builds on top: {', '.join(advanced) or 'none stored'}.\n"
            "Use this to contrast how these technologies differ, when to choose each, "
            "and where they sit in the broader landscape."
        )
        return _result("compare", topic, True, data, instruction)

    instruction = (
        f"Action: COMPARE / CONTEXTUALISE\n"
        f"The user wants to compare \"{topic}\" with related technologies "
        f"(no expansion data stored yet).\n"
        "Draw on your own knowledge to compare this technology against its closest peers. "
        "Be specific about trade-offs and use-case fit."
    )
    return _result("compare", topic, False, {}, instruction)


def _handle_find_tutorials(topic: str, context: dict) -> dict:
    """
    Search for practical tutorials using a domain-aware query.

    For Technology/AI domains the first resource group (repos + docs) is
    surfaced; for other domains the tutorial group is used.  Falls back to
    a generic Tavily query when domain discovery fails.
    """
    domain_ctx = context.get("domain_context", {})
    domain     = domain_ctx.get("domain")

    try:
        from .domain_resource_service import discover_resources, build_resource_instruction
        resource_result = discover_resources(topic, domain=domain)
        groups = resource_result.get("resource_groups", [])

        # For tutorial intent, prefer groups labelled with tutorial/docs/repos content
        tutorial_groups = [
            g for g in groups
            if g["resource_type"] in ("tutorials", "docs", "repos", "papers")
        ] or groups   # fall back to whatever was found

        if tutorial_groups:
            items = []
            for group in tutorial_groups[:2]:  # at most 2 groups for tutorials
                for item in group["items"][:3]:
                    items.append(item)

            lines = [
                f"- {item.get('title') or item.get('name', 'Resource')}: {item.get('url', '')}"
                for item in items
            ]
            resource_block = "\n".join(lines)
            data = {"resource_groups": tutorial_groups, "domain": resource_result.get("domain")}
            instruction = (
                f"Action: FIND TUTORIALS\n"
                f"Domain: {resource_result.get('domain', 'General')}\n"
                f"The user wants hands-on resources for \"{topic}\".\n"
                f"Found resources:\n{resource_block}\n"
                "Present these resources grouped by type. For each one, briefly explain what it "
                "covers and why it is useful. Recommend which to start with based on their level."
            )
            return _result("find_tutorials", topic, True, data, instruction)

    except Exception:
        logger.exception("action_router: domain resource discovery failed for %r", topic)

    # Generic fallback
    try:
        from .tavily_service import search_articles
        results = search_articles(f"{topic} practical tutorial hands-on guide")[:5]
    except Exception:
        logger.exception("action_router: tavily fallback failed for %r", topic)
        results = []

    if results:
        lines = [f"- {r.get('title', 'Resource')}: {r.get('url', '')}" for r in results]
        instruction = (
            f"Action: FIND TUTORIALS\n"
            f"The user wants practical tutorials for \"{topic}\".\n"
            f"Found resources:\n" + "\n".join(lines) + "\n"
            "Present these resources. For each one, briefly explain what it covers "
            "and why it is useful. Recommend which to start with based on their level."
        )
        return _result("find_tutorials", topic, True, {"results": results}, instruction)

    instruction = (
        f"Action: FIND TUTORIALS\n"
        f"The user wants practical tutorials for \"{topic}\" (search unavailable or no results).\n"
        "Recommend 3–5 types of resources (documentation, courses, projects) they should look "
        "for, explaining what makes a good tutorial for this topic."
    )
    return _result("find_tutorials", topic, False, {}, instruction)


def _handle_find_reports(topic: str, context: dict) -> dict:
    """
    Domain-aware resource discovery for reports, analysis, and research.

    Prioritises non-tutorial resource types: reports, articles, papers.
    Best suited for Finance, Business, Manufacturing, Export/Trade, and Pharma.
    """
    domain_ctx = context.get("domain_context", {})
    domain     = domain_ctx.get("domain")

    try:
        from .domain_resource_service import discover_resources, build_resource_instruction
        resource_result = discover_resources(topic, domain=domain)
        groups = resource_result.get("resource_groups", [])

        # Prefer report/article/paper groups for this action
        report_groups = [
            g for g in groups
            if g["resource_type"] in ("reports", "articles", "papers")
        ] or groups

        if report_groups:
            data = {"resource_groups": report_groups, "domain": resource_result.get("domain")}
            instruction = build_resource_instruction(topic, {
                "domain":          resource_result.get("domain", domain or "General"),
                "resource_groups": report_groups,
            })
            return _result("find_reports", topic, True, data, instruction)

    except Exception:
        logger.exception("action_router: domain report discovery failed for %r", topic)

    instruction = (
        f"Action: FIND REPORTS\n"
        f"The user wants domain-specific reports or analysis for \"{topic}\" "
        f"(search unavailable or no results).\n"
        "Recommend the key data sources, publications, and research organisations "
        "practitioners in this field rely on. Be specific about what to search for."
    )
    return _result("find_reports", topic, False, {}, instruction)


def _handle_beginner_resources(topic: str, context: dict) -> dict:
    """Extract beginner steps from stored learning path."""
    from .learning_path_service import get_stored_path

    path = get_stored_path(topic)
    if path:
        beginner_steps = path.get("beginner", [])[:5]
        step_titles = [
            s.get("concept", "") for s in beginner_steps if isinstance(s, dict)
        ]
        step_descs = {
            s.get("concept", ""): s.get("description", "")
            for s in beginner_steps if isinstance(s, dict)
        }
        data = {"beginner_steps": beginner_steps}
        steps_block = "\n".join(
            f"  {i+1}. {t} — {step_descs.get(t, '')}"
            for i, t in enumerate(step_titles)
        )
        instruction = (
            f"Action: BEGINNER RESOURCES\n"
            f"The user wants beginner-friendly resources and a starting point for \"{topic}\".\n"
            f"Stored learning path (beginner stage):\n{steps_block}\n"
            "Present these as a welcoming, structured starting point. "
            "Be encouraging and explain why each step matters."
        )
        return _result("beginner_resources", topic, True, data, instruction)

    instruction = (
        f"Action: BEGINNER RESOURCES\n"
        f"The user wants beginner resources for \"{topic}\" (no learning path stored yet).\n"
        "Recommend a 3–5 step beginner starting point from your own knowledge. "
        "Suggest free resources (docs, courses, projects) and explain how to progress."
    )
    return _result("beginner_resources", topic, False, {}, instruction)


def _handle_show_repos(topic: str, context: dict) -> dict:
    """Retrieve or fetch GitHub repositories (cache-first pipeline)."""
    from .github_service import get_topic_repos

    repos = get_topic_repos(topic)  # cache-first; calls GitHub API on miss
    if repos:
        lines = [
            f"- {r.get('name', 'repo')} "
            f"({r.get('stars', 0):,}★): "
            f"{r.get('description', '')[:120]} — {r.get('url', '')}"
            for r in repos[:6]
        ]
        repo_block = "\n".join(lines)
        data = {"repos": repos[:6]}
        instruction = (
            f"Action: SHOW REPOSITORIES\n"
            f"The user wants GitHub repositories for \"{topic}\".\n"
            f"Repositories:\n{repo_block}\n"
            "Present these repositories. For each one explain what it does, "
            "why it is notable, and who it is best suited for."
        )
        return _result("show_repos", topic, True, data, instruction)

    instruction = (
        f"Action: SHOW REPOSITORIES\n"
        f"No GitHub repositories found for \"{topic}\".\n"
        "Describe what types of open-source projects exist in this space and "
        "what keywords the user should search for on GitHub."
    )
    return _result("show_repos", topic, False, {}, instruction)


def _handle_learning_roadmap(topic: str, context: dict) -> dict:
    """Return a full structured learning path (cache-first pipeline)."""
    from .learning_path_service import get_learning_path

    path = get_learning_path(topic)  # cache-first; generates on miss
    if path:
        def _extract(steps: list, limit: int = 4) -> list[str]:
            return [
                s.get("concept", "") for s in steps[:limit] if isinstance(s, dict)
            ]

        beginner     = _extract(path.get("beginner",     []))
        intermediate = _extract(path.get("intermediate", []))
        advanced     = _extract(path.get("advanced",     []))

        data = {"beginner": beginner, "intermediate": intermediate, "advanced": advanced}
        instruction = (
            f"Action: LEARNING ROADMAP\n"
            f"The user wants a full learning roadmap for \"{topic}\".\n"
            f"Beginner stage: {', '.join(beginner) or 'see below'}.\n"
            f"Intermediate stage: {', '.join(intermediate) or 'see below'}.\n"
            f"Advanced stage: {', '.join(advanced) or 'see below'}.\n"
            "Present this as a clear, sequential roadmap. For each stage briefly explain "
            "what the learner will be able to do. Make it motivating and actionable."
        )
        return _result("learning_roadmap", topic, True, data, instruction)

    instruction = (
        f"Action: LEARNING ROADMAP\n"
        f"The user wants a learning roadmap for \"{topic}\" (none stored yet — generating).\n"
        "Create a practical 3-stage roadmap (beginner → intermediate → advanced) "
        "from your own knowledge. Be specific about concrete skills and milestones."
    )
    return _result("learning_roadmap", topic, False, {}, instruction)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _result(action: str, topic: str, found: bool, data: dict, instruction: str) -> dict:
    return {
        "action":      action,
        "topic":       topic,
        "found":       found,
        "data":        data,
        "instruction": instruction,
    }


def _empty(action: str, topic: str) -> dict:
    return _result(action, topic, False, {}, "")
