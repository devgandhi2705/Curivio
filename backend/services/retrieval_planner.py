"""
Retrieval Planner

Turns intent and knowledge state into goal-driven search queries.
Called once per feed generation; replaces keyword-only query construction.

Distribution
------------
  80%  core_queries      — directly aligned with current learning intent
  10%  adjacent_queries  — one step sideways; related territory not yet covered
  10%  serendipity_queries — surprising angle; sparks curiosity

Public API
----------
plan(intent_profile, knowledge_state, keywords) -> dict
    Returns {core_queries: list[str], adjacent_queries: list[str], serendipity_queries: list[str]}
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)


_MIN_CORE_QUERIES: int   = 1
_MIN_CORE_RATIO:   float = 0.50   # core must be ≥ 50% of all planned queries


def plan(
    intent_profile:  dict | None,
    knowledge_state: dict | None,
    keywords:        list[str],
    project_name:    str = "",
    today_plan:      dict | None = None,
) -> dict:
    """
    Produce goal-driven search queries from the learner's context.
    Falls back to keyword-based queries if the LLM call fails.
    Validates and repairs composition before returning.
    """
    try:
        result = _llm_plan(intent_profile, knowledge_state, keywords, project_name, today_plan)
    except Exception as e:
        logger.warning("[retrieval_planner] LLM planning failed (%s) — using keyword fallback", e)
        result = _keyword_fallback(intent_profile, keywords, project_name)
    return _validate_and_repair(result, intent_profile, keywords, project_name)


# ── LLM path ───────────────────────────────────────────────────────────────────

def _llm_plan(
    intent_profile:  dict | None,
    knowledge_state: dict | None,
    keywords:        list[str],
    project_name:    str,
    today_plan:      dict | None = None,
) -> dict:
    context = _build_context(intent_profile, knowledge_state, keywords, project_name, today_plan)
    _shape  = _detect_shape(today_plan)
    logger.info("[retrieval_planner] today_plan shape=%s", _shape)

    if _shape == "fixed_sequence":
        _recency_weight = ""
        _recency_rule   = ""
    else:
        _recency_weight = '\n  10% RECENCY  — exactly ONE core query must include "2025" or "2026" for fresh coverage'
        _recency_rule   = '\n  → Exactly 1 of the core queries must include "2025" or "2026"'

    prompt = f"""You are a search strategist for a personalised learning system.
Your task: produce search queries that retrieve the best articles for today's learning session.

{context}

QUERY WEIGHTING — follow this exactly:
  60% INTENT   — queries must reflect the learner's persona, goal, and search lens above all else
  30% KEYWORDS — keywords inform topic scope but must not override persona framing{_recency_weight}

SUBJECT vs CONTEXT — this is the most common failure mode:
  Learning subject = WHAT is retrieved. Core queries must be about this.
  Industry context = HOW content is framed. It shapes examples and adjacent queries, NOT core topics.
  Example: learning_subject "AI Agents & Marketing Automation", industry_context "Pharmaceutical"
    CORRECT core: "AI agents marketing automation", "agentic campaign workflows 2025", "LLM-powered CRM tools"
    WRONG core:   "pharma marketing strategy", "drug company digital marketing", "healthcare advertising"
  The industry context appears in adjacent/serendipity queries as framing, e.g. "AI marketing agents pharma use cases".

PERSONA FRAMING — the same topic produces different queries for different personas:

  Topic: Globalization | Persona: Economics Student | Search lens: Educational
    core → "globalization theory explained", "WTO trade rules overview", "comparative advantage examples"
    adjacent → "supply chain globalization economics"
    serendipity → "anti-globalization movements history"

  Topic: Globalization | Persona: Startup Founder | Search lens: Business Strategy
    core → "export strategy for startups", "international market entry guide", "global supply chain risk 2025"
    adjacent → "cross-border hiring compliance"
    serendipity → "unexpected globalization failures startups"

Apply the same persona-driven differentiation using the PRIMARY SIGNAL above.
The search_lens determines the framing: Educational → concepts/theory/history; Business Strategy → tactics/decisions/risk; Technical → implementation/architecture/benchmarks; Policy & Regulation → legislation/compliance/enforcement; Investment & Markets → returns/valuation/signals; Scientific Research → findings/methodology/evidence; Investigative → hidden mechanisms/failures/surprises.

QUERY RULES:
- Every query: 3–8 words, real search engine query, no operators
- core_queries (2–3): what this learner should learn NEXT — framed for their persona and search lens
  → Avoid already-covered topics; prioritise knowledge gaps{_recency_rule}
- adjacent_queries (exactly 1): neighbouring concept not yet covered, framed for their industry context
- serendipity_queries (exactly 1): counterintuitive, surprising, or hidden-mechanism angle
  → Genuinely related to the topic but feels like a discovery; match persona (student ≠ founder)

Return ONLY valid JSON:
{{
  "core_queries":        ["query 1", "query 2", "query 3"],
  "adjacent_queries":    ["query 1"],
  "serendipity_queries": ["query 1"]
}}"""

    from .grok_service import ask_grok
    raw  = ask_grok(prompt, json_mode=True)
    data = _parse_json(raw)

    return {
        "core_queries":        _str_list(data.get("core_queries"),        max_n=3),
        "adjacent_queries":    _str_list(data.get("adjacent_queries"),    max_n=1),
        "serendipity_queries": _str_list(data.get("serendipity_queries"), max_n=1),
    }


# ── Journey plan helpers ───────────────────────────────────────────────────────

def _is_fallback_plan(today_plan: dict | None) -> bool:
    """True when today_plan carries no meaningful specific topic signal."""
    if not today_plan:
        return True
    if today_plan.get("rationale", "").startswith("Fallback"):
        return True
    if today_plan.get("focus") == "General exploration":
        return True
    theme = today_plan.get("theme") or {}
    if theme and theme.get("description") == f"Explore {theme.get('name', '')}":
        return True
    return False


def _detect_shape(today_plan: dict | None) -> str | None:
    """
    Return "fixed_sequence", "rotating_theme", or None (fallback/unknown).
    Inferred from keys present in the day-entry dict returned by get_today_plan().
    """
    if _is_fallback_plan(today_plan):
        return None
    if today_plan and "focus" in today_plan:
        return "fixed_sequence"
    if today_plan and "theme" in today_plan:
        return "rotating_theme"
    return None


def _build_context(
    intent_profile:  dict | None,
    knowledge_state: dict | None,
    keywords:        list[str],
    project_name:    str,
    today_plan:      dict | None = None,
) -> str:
    lines: list[str] = []

    # TODAY'S PLAN — prepend when a non-fallback journey plan is available.
    # fixed_sequence: today's `focus` is the specific topic to retrieve for.
    # rotating_theme: today's rotated `theme` is the primary topic driver.
    _shape = _detect_shape(today_plan)
    if _shape == "fixed_sequence":
        _tp_focus = (today_plan or {}).get("focus", "")
        _tp_title = (today_plan or {}).get("display_title", "")
        lines.append("TODAY'S PLAN — PRIMARY DRIVER FOR CORE QUERIES")
        lines.append(f"  Focus:     {_tp_focus}")
        if _tp_title:
            lines.append(f"  Day title: {_tp_title}")
        lines.append("")
        lines.append(f'Core queries MUST be specifically about "{_tp_focus}" — not the broader subject.')
        lines.append("Primary_focus, keywords, and search_lens below provide supporting context for today.")
        lines.append("")
    elif _shape == "rotating_theme":
        _tp_theme = (today_plan or {}).get("theme") or {}
        _tp_name  = _tp_theme.get("name", "")
        _tp_desc  = _tp_theme.get("description", "")
        lines.append("TODAY'S THEME — PRIMARY DRIVER FOR CORE QUERIES")
        lines.append(f"  Theme:       {_tp_name}")
        if _tp_desc:
            lines.append(f"  Description: {_tp_desc}")
        lines.append("")
        lines.append(f'Core queries MUST be specifically about "{_tp_name}".')
        lines.append("Primary_focus, keywords, and search_lens below provide supporting context for today.")
        lines.append("")

    # PRIMARY SIGNAL (60%) — intent profile drives query persona and framing
    if intent_profile:
        lines.append("PRIMARY SIGNAL — LEARNER INTENT (weight: 60%)")
        if intent_profile.get("learning_subject"):
            lines.append(f"  Learning subject: {intent_profile['learning_subject']}  ← WHAT to retrieve")
        if intent_profile.get("persona"):
            lines.append(f"  Persona:          {intent_profile['persona']}")
        if intent_profile.get("goal"):
            lines.append(f"  Goal:             {intent_profile['goal']}")
        if intent_profile.get("industry_context"):
            lines.append(f"  Industry context: {intent_profile['industry_context']}  ← frames examples only")
        if intent_profile.get("primary_focus"):
            lines.append(f"  Primary focus:    {intent_profile['primary_focus']}")
        if intent_profile.get("search_lens"):
            lines.append(f"  Search lens:      {intent_profile['search_lens']}")
        lines.append("")

    # Knowledge state
    if knowledge_state:
        active  = ", ".join(knowledge_state.get("active_topics",  [])[:6])  or "none yet"
        recent  = ", ".join(knowledge_state.get("recent_topics",  [])[:6])  or "none yet"
        gaps    = ", ".join(knowledge_state.get("knowledge_gaps", [])[:8])  or "none identified"
        covered = ", ".join(knowledge_state.get("covered_topics", [])[-15:]) or "none yet"
        lines.append("KNOWLEDGE STATE")
        lines.append(f"  Active topics:  {active}")
        lines.append(f"  Recent topics:  {recent}")
        lines.append(f"  Known gaps:     {gaps}")
        lines.append(f"  Already covered (avoid repeating): {covered}")
        lines.append("")

    # SECONDARY SIGNAL (30%) — keywords inform topic scope, not framing
    if keywords:
        lines.append(f"SECONDARY SIGNAL — PROJECT KEYWORDS (weight: 30%): {', '.join(keywords[:10])}")
        lines.append("")

    if project_name:
        lines.append(f"PROJECT: {project_name}")

    return "\n".join(lines)


# ── Composition validation ────────────────────────────────────────────────────

def _validate_and_repair(
    plan:           dict,
    intent_profile: dict | None,
    keywords:       list[str],
    project_name:   str,
) -> dict:
    """
    Check that the planned query set has a dominant core component.
    Logs composition ratios.  Repairs with keyword fallback when core is
    absent or a minority.
    """
    core  = plan.get("core_queries",        [])
    adj   = plan.get("adjacent_queries",    [])
    sernd = plan.get("serendipity_queries", [])
    total = len(core) + len(adj) + len(sernd)

    core_ratio  = round(len(core)  / total, 2) if total else 0.0
    adj_ratio   = round(len(adj)   / total, 2) if total else 0.0
    sernd_ratio = round(len(sernd) / total, 2) if total else 0.0

    logger.info(
        "[retrieval_planner] composition: total=%d"
        " core=%d(%.0f%%) adj=%d(%.0f%%) serendipity=%d(%.0f%%)",
        total,
        len(core),  core_ratio  * 100,
        len(adj),   adj_ratio   * 100,
        len(sernd), sernd_ratio * 100,
    )

    needs_repair = (len(core) < _MIN_CORE_QUERIES) or (total > 0 and core_ratio < _MIN_CORE_RATIO)
    if needs_repair:
        logger.warning(
            "[retrieval_planner] composition repair:"
            " core=%d(%.0f%%) < min=%d(%.0f%%) — rebuilding core from keyword fallback",
            len(core), core_ratio * 100, _MIN_CORE_QUERIES, _MIN_CORE_RATIO * 100,
        )
        fallback = _keyword_fallback(intent_profile, keywords, project_name)
        plan = {
            "core_queries":        fallback["core_queries"],
            "adjacent_queries":    adj   or fallback.get("adjacent_queries",    []),
            "serendipity_queries": sernd or fallback.get("serendipity_queries", []),
        }

    return plan


# ── Keyword fallback ───────────────────────────────────────────────────────────

def _keyword_fallback(
    intent_profile: dict | None,
    keywords: list[str],
    project_name: str,
) -> dict:
    focus = (intent_profile or {}).get("learning_subject") or (intent_profile or {}).get("primary_focus") or " ".join(keywords[:3]) or project_name
    lens  = (intent_profile or {}).get("search_lens") or ""
    adj_seed = " ".join(keywords[3:5]) if len(keywords) > 3 else project_name
    serendipity_frame = "surprising failures" if "Business" in lens else "counterintuitive history"
    return {
        "core_queries": [
            f"{focus} explained 2025",
            f"{focus} concepts framework",
        ],
        "adjacent_queries":    [f"{adj_seed} {project_name} context"],
        "serendipity_queries": [f"{project_name} {serendipity_frame}"],
    }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_json(text: str) -> dict:
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start : end + 1])
    return json.loads(text.strip())


def _str_list(value, max_n: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if v and str(v).strip()][:max_n]
