"""
Curiosity Orchestrator — Phase 4.4

Makes curiosity cards strategic instead of independently generated.

Every curiosity card is assigned one of four roles:

  CONNECT   — bridge two concepts the user knows separately but hasn't linked.
              Uses the knowledge graph to find weakly-connected node pairs.
              Emotional target: "I knew both things — I didn't know they were the same system."

  CHALLENGE — take a concept the user understands and contradict it.
              Uses the gap detector to find adjacent gaps that invert the user's model.
              Emotional target: "I'll never look at [X] the same way."

  EXPAND    — open an adjacent domain the user hasn't entered.
              Uses the learning planner's curiosity areas as targets.
              Emotional target: "I didn't know I needed to understand this to understand that."

  REINFORCE — take the most-seen concept and reveal a non-obvious deeper layer.
              Uses the highest-weight node as anchor, finds the gap that unlocks its hidden structure.
              Emotional target: "Now I actually understand [X]."

Role → Tension category affinities (from package_curiosity_pack.py):
  connect   → INVISIBLE_DEPENDENCY, UNINTENDED_CONSEQUENCE, HIDDEN_FAILURE
  challenge → INDUSTRY_MYTH, INVERSE_CAUSALITY, SURPRISING_INCENTIVE
  expand    → GEOPOLITICAL_MANIPULATION, BILLION_DOLLAR_MISTAKE, UNINTENDED_CONSEQUENCE
  reinforce → HIDDEN_FAILURE, SURPRISING_INCENTIVE, SCANDAL / INSTITUTIONAL_FAILURE

Slot assignment:
  Slot 1 — anchored card (connect or challenge — stays close to known territory)
  Slot 2 — outward card (expand or challenge from different domain)
  Fallback — any available role if preferred is unavailable

Public API
----------
  orchestrate(project_id) -> CuriosityBriefing
  get_curiosity_directives(project_id) -> str   (for prompt injection)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger(__name__)


# ── Data types ─────────────────────────────────────────────────────────────────

@dataclass
class CuriosityBrief:
    slot:             int     # 1 or 2
    role:             str     # connect | challenge | expand | reinforce
    tension_category: str     # one of the 9 tension categories
    anchor_concept:   str     # the known concept being departed from
    target_concept:   str     # what the card is pulling toward
    domain:           str     # primary domain context
    directive:        str     # full instruction for the LLM
    why_strategic:    str     # human-readable selection rationale


@dataclass
class CuriosityBriefing:
    card_1:           CuriosityBrief
    card_2:           CuriosityBrief | None
    prompt_injection: str     # formatted block ready for project_insight_prompt.py


# ── Tension category constants ─────────────────────────────────────────────────

_ALL_CATEGORIES = [
    "HIDDEN_FAILURE",
    "UNINTENDED_CONSEQUENCE",
    "SCANDAL",
    "INVISIBLE_DEPENDENCY",
    "SURPRISING_INCENTIVE",
    "GEOPOLITICAL_MANIPULATION",
    "BILLION_DOLLAR_MISTAKE",
    "INDUSTRY_MYTH",
    "INVERSE_CAUSALITY",
]

_ROLE_TENSION_AFFINITIES: dict[str, list[str]] = {
    "connect":   ["INVISIBLE_DEPENDENCY", "UNINTENDED_CONSEQUENCE", "HIDDEN_FAILURE"],
    "challenge": ["INDUSTRY_MYTH", "INVERSE_CAUSALITY", "SURPRISING_INCENTIVE"],
    "expand":    ["GEOPOLITICAL_MANIPULATION", "BILLION_DOLLAR_MISTAKE", "UNINTENDED_CONSEQUENCE"],
    "reinforce": ["HIDDEN_FAILURE", "SURPRISING_INCENTIVE", "SCANDAL"],
}


def _pick_tension(role: str, used: set[str]) -> str:
    """Pick the best available tension category for a role, avoiding already-used ones."""
    affinities = _ROLE_TENSION_AFFINITIES.get(role, _ALL_CATEGORIES)
    for cat in affinities:
        if cat not in used:
            return cat
    for cat in _ALL_CATEGORIES:
        if cat not in used:
            return cat
    return "INVISIBLE_DEPENDENCY"


# ── Text helpers ───────────────────────────────────────────────────────────────

def _norm(text: str) -> str:
    t = text.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# ── Candidate finders ─────────────────────────────────────────────────────────

def _find_connect_candidate(
    graph: dict,
) -> tuple[str, str, str] | None:
    """
    Find a pair of high-weight nodes (weight >= 2) linked only by `related_to`
    edges — the weakest possible connection. These represent an unexplored
    relationship the user has circled but not mapped.

    Returns (anchor_label, target_label, domain) or None.
    """
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    if len(nodes) < 2:
        return None

    # Build edge type map: (from_key, to_key) → set of relations
    relation_map: dict[tuple[str, str], set[str]] = defaultdict(set)
    for e in edges:
        pair = (e["from_key"], e["to_key"])
        relation_map[pair].add(e["relation"])
        relation_map[(e["to_key"], e["from_key"])].add(e["relation"])

    # High-weight content nodes (not industry, weight >= 2)
    content_nodes = [
        n for n in nodes
        if n["weight"] >= 2 and n["node_type"] not in ("industry",)
    ]

    best_pair: tuple[str, str] | None = None
    best_weight = 0

    node_map = {n["node_key"]: n for n in nodes}

    for i, a in enumerate(content_nodes):
        for b in content_nodes[i + 1:]:
            pair_key = (a["node_key"], b["node_key"])
            relations = relation_map.get(pair_key, set())
            # Only related_to (or no edges at all) — unexplored structural relationship
            if relations and relations - {"related_to"}:
                continue  # already has typed edges — skip
            combined = a["weight"] + b["weight"]
            if combined > best_weight:
                best_weight = combined
                best_pair = (a["node_key"], b["node_key"])

    if not best_pair:
        return None

    a_node = node_map.get(best_pair[0])
    b_node = node_map.get(best_pair[1])
    if not a_node or not b_node:
        return None

    # Determine domain from nearby industry node
    industry_nodes = [n for n in nodes if n["node_type"] == "industry"]
    domain = industry_nodes[0]["label"] if industry_nodes else "the domain"

    return a_node["label"], b_node["label"], domain


def _find_challenge_candidate(
    gap_report,   # GapReport
    graph: dict,
) -> tuple[str, str, str, str] | None:
    """
    Find a HIGH-priority gap that is adjacent to a known concept and
    conceptually challenges or inverts the user's understanding.

    Returns (anchor_label, gap_label, domain, challenge_reason) or None.
    """
    # Prefer HIGH priority concept or strategic gaps
    candidates = [
        g for g in (gap_report.missing_concepts + gap_report.missing_strategic)
        if g.priority == "high" and g.known_neighbours
    ]
    if not candidates:
        return None

    # Pick the gap with the most known neighbours (most contextually embedded)
    candidates.sort(key=lambda g: -len(g.known_neighbours))
    gap = candidates[0]
    anchor = gap.known_neighbours[0]

    # Build a challenge reason: what mental model does this invert?
    challenge_reason = _infer_challenge_reason(anchor, gap.label, gap.domain)

    return anchor, gap.label, gap.domain, challenge_reason


def _infer_challenge_reason(anchor: str, gap: str, domain: str) -> str:
    """Generate a short description of what mental model this challenges."""
    a, g = anchor.lower(), gap.lower()

    # Pattern-based reason generation
    if "compliance" in a and ("capture" in g or "moat" in g or "arbitrage" in g):
        return f"Compliance feels like a neutral quality gate. {gap} reveals it is also a competitive weapon."
    if "regulatory" in a and "arbitrage" in g:
        return f"Regulatory frameworks feel like constraints. {gap} reveals they are also opportunities to exploit asymmetry."
    if "fda" in a and ("incentive" in g or "lobbying" in g or "campaign" in g):
        return f"FDA actions feel objective and scientific. The hidden incentive structure behind them is economic, not purely scientific."
    if "export" in a and ("geopolit" in g or "dependency" in g or "supply" in g):
        return f"Export success looks like economic strength. {gap} reveals the structural fragility hidden inside it."
    if "innovation" in a and ("incumben" in g or "moat" in g or "barrier" in g):
        return f"Innovation feels like disruption. {gap} shows how incumbents use innovation language to build defensive moats."
    if "supply chain" in a and ("single" in g or "concentrat" in g or "risk" in g):
        return f"Supply chain efficiency feels like an optimization achievement. {gap} reveals efficiency creates concentration risk."
    if "market" in a and ("manipulation" in g or "incentive" in g or "myth" in g):
        return f"Market outcomes feel like neutral price discovery. {gap} reveals the political economy underneath."

    # Generic fallback
    return (
        f"The reader understands '{anchor}' as it's typically framed. "
        f"'{gap}' introduces a dimension that complicates or contradicts that standard framing."
    )


def _find_expand_candidate(
    learning_plan,   # LearningPlan | None
) -> tuple[str, str, str, str] | None:
    """
    Find the strongest curiosity area from the learning plan — a cross-domain
    hook that pulls the user into adjacent territory.

    Returns (anchor_concept, area_label, domain, hook) or None.
    """
    if learning_plan is None or not learning_plan.curiosity_areas:
        return None

    # Prefer areas with a strong connection statement
    area = learning_plan.curiosity_areas[0]
    return area.connection, area.label, area.domain, area.hook


def _find_reinforce_candidate(
    graph: dict,
    gap_report,   # GapReport
) -> tuple[str, str, str] | None:
    """
    Take the most-seen concept (highest weight) and find the gap that
    would reveal its non-obvious deeper structure.

    Returns (anchor_label, target_gap_label, domain) or None.
    """
    nodes = graph.get("nodes", [])
    if not nodes:
        return None

    # Highest-weight non-industry node (the concept the user knows best)
    content_nodes = [n for n in nodes if n["node_type"] not in ("industry",)]
    if not content_nodes:
        return None
    content_nodes.sort(key=lambda n: -n["weight"])
    anchor_node = content_nodes[0]
    anchor = anchor_node["label"]

    # Find a gap in the same domain that deepens this concept
    all_gaps = (
        gap_report.missing_mechanisms
        + gap_report.missing_concepts
        + gap_report.missing_strategic
    )
    anchor_norm = _norm(anchor)

    # Prefer gaps that share keywords with anchor or are in the same domain
    a_words = {w for w in anchor_norm.split() if len(w) >= 3}

    target: str | None = None
    domain: str = gap_report.active_domains[0] if gap_report.active_domains else "the domain"

    for g in all_gaps:
        g_words = {w for w in _norm(g.label).split() if len(w) >= 3}
        if a_words & g_words:
            target = g.label
            domain = g.domain
            break

    if not target:
        # Fall back to first high-priority mechanism gap
        mech_gaps = [g for g in gap_report.missing_mechanisms if g.priority in ("high", "medium")]
        if mech_gaps:
            target = mech_gaps[0].label
            domain = mech_gaps[0].domain

    if not target:
        return None

    return anchor, target, domain


# ── Directive builders ────────────────────────────────────────────────────────

def _build_connect_directive(anchor: str, target: str, domain: str, tension: str) -> str:
    return (
        f"STRATEGIC ROLE: CONNECT\n"
        f"Anchor (the reader knows this): {anchor}\n"
        f"Target (the hidden structural link): {target}\n"
        f"Domain: {domain}\n"
        f"Tension category: {tension}\n\n"
        f"The reader has encountered both '{anchor}' and '{target}' but has never seen the "
        f"mechanism that links them. This card makes that hidden connection visible — not as a "
        f"summary of both, but as the specific system behavior that only exists at their intersection.\n\n"
        f"Write this as a discovery, not a lesson. The reader should finish thinking: "
        f"'I knew both things separately — I didn't realize they were the same system.'\n\n"
        f"Ground the card in a specific named event, company decision, or measurable consequence "
        f"from {domain}. The tension should feel structural, not anecdotal."
    )


def _build_challenge_directive(
    anchor: str, target: str, domain: str, tension: str, challenge_reason: str
) -> str:
    return (
        f"STRATEGIC ROLE: CHALLENGE\n"
        f"Anchor (the belief being challenged): {anchor}\n"
        f"Challenge target (the gap that complicates it): {target}\n"
        f"Domain: {domain}\n"
        f"Tension category: {tension}\n\n"
        f"Challenge framing: {challenge_reason}\n\n"
        f"The reader has built a working mental model of '{anchor}'. This card introduces "
        f"a specific contradiction, inversion, or hidden layer that forces them to update "
        f"that model. Do not soften the contradiction — the card should feel slightly unsettling.\n\n"
        f"The reader should finish thinking: 'I'll never look at {anchor} the same way.'\n\n"
        f"Use one specific historical example, regulatory action, or named company decision "
        f"to make the challenge concrete. Avoid vague generalizations."
    )


def _build_expand_directive(
    anchor: str, target: str, domain: str, tension: str, hook: str
) -> str:
    return (
        f"STRATEGIC ROLE: EXPAND\n"
        f"Bridge from (what the reader already knows): {anchor}\n"
        f"Expansion target: {target}\n"
        f"New domain: {domain}\n"
        f"Tension category: {tension}\n\n"
        f"Cross-domain hook: {hook}\n\n"
        f"The reader is fluent in their current domain. This card opens a door into adjacent "
        f"territory by showing how their existing knowledge directly explains something in "
        f"a domain they haven't mapped yet.\n\n"
        f"The connection is the card — not a summary of {domain}, but the specific moment "
        f"where the reader's domain knowledge and {domain} produce the same structural pattern.\n\n"
        f"The reader should finish thinking: 'I didn't know I needed to understand {domain} "
        f"to understand this.'"
    )


def _build_reinforce_directive(anchor: str, target: str, domain: str, tension: str) -> str:
    return (
        f"STRATEGIC ROLE: REINFORCE\n"
        f"Core concept (deeply familiar to the reader): {anchor}\n"
        f"Deeper layer to reveal: {target}\n"
        f"Domain: {domain}\n"
        f"Tension category: {tension}\n\n"
        f"The reader has encountered '{anchor}' multiple times and understands its surface "
        f"structure. This card goes underneath — revealing the non-obvious mechanism, "
        f"incentive structure, or historical failure that the standard explanation omits.\n\n"
        f"Because the reader already understands the basics, they are ready for the harder "
        f"structural insight. The depth should feel earned.\n\n"
        f"The reader should finish thinking: 'Now I actually understand {anchor}.'\n\n"
        f"Anchor in a specific data point, institutional decision, or named failure that "
        f"most coverage of {domain} systematically misses."
    )


def _make_brief(
    slot: int,
    role: str,
    anchor: str,
    target: str,
    domain: str,
    tension: str,
    directive: str,
    why: str,
) -> CuriosityBrief:
    return CuriosityBrief(
        slot=slot,
        role=role,
        tension_category=tension,
        anchor_concept=anchor,
        target_concept=target,
        domain=domain,
        directive=directive,
        why_strategic=why,
    )


# ── Prompt injection formatter ────────────────────────────────────────────────

def _format_injection(card_1: CuriosityBrief, card_2: CuriosityBrief | None) -> str:
    lines: list[str] = []
    lines.append("══════════════════════════════════════")
    lines.append("CURIOSITY STRATEGY  <- MANDATORY: use these directives for the two curiosity cards")
    lines.append("══════════════════════════════════════")
    lines.append(
        "The two curiosity cards below have been strategically assigned based on this user's "
        "knowledge graph and learning gaps. Follow the directives exactly — do NOT use generic "
        "category selection for these cards."
    )
    lines.append("")
    lines.append("CURIOSITY CARD 1:")
    lines.append(card_1.directive)
    lines.append("")
    lines.append(f"Selection rationale: {card_1.why_strategic}")

    if card_2:
        lines.append("")
        lines.append("CURIOSITY CARD 2:")
        lines.append(card_2.directive)
        lines.append("")
        lines.append(f"Selection rationale: {card_2.why_strategic}")
        lines.append("")
        lines.append(
            f"CONSTRAINT: Card 1 uses tension category {card_1.tension_category}. "
            f"Card 2 MUST use {card_2.tension_category}. Do not swap or change these."
        )

    return "\n".join(lines)


# ── Fallback brief ────────────────────────────────────────────────────────────

def _fallback_brief(slot: int, used_categories: set[str], domain: str = "the domain") -> CuriosityBrief:
    tension = _pick_tension("expand", used_categories)
    directive = (
        f"STRATEGIC ROLE: EXPAND\n"
        f"Tension category: {tension}\n\n"
        f"No specific strategic target identified yet — the user's knowledge graph is still building. "
        f"Generate the most surprising, counterintuitive card you can find in {domain}. "
        f"Prefer INVISIBLE_DEPENDENCY or INDUSTRY_MYTH framings — pick whichever scores higher "
        f"on the tension scoring rubric."
    )
    return CuriosityBrief(
        slot=slot,
        role="expand",
        tension_category=tension,
        anchor_concept="",
        target_concept="",
        domain=domain,
        directive=directive,
        why_strategic="Fallback: knowledge graph too sparse for targeted selection.",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def orchestrate(project_id: str) -> CuriosityBriefing:
    """
    Analyse the project's knowledge graph, gaps, and learning plan to produce
    a CuriosityBriefing with strategic directives for both curiosity card slots.

    Non-fatal — returns fallback briefs on any error.
    """
    try:
        from .learning_graph import get_graph
        from .knowledge_gap_detector import detect_gaps
        from .learning_path_planner import plan as build_plan

        graph       = get_graph(project_id)
        gap_report  = detect_gaps(project_id)
        learning_plan = None
        try:
            learning_plan = build_plan(project_id)
        except Exception:
            pass  # plan is optional

        used_categories: set[str] = set()
        domain = gap_report.active_domains[0] if gap_report.active_domains else "the domain"

        # ── Slot 1: ANCHORED card (connect or challenge) ────────────────────

        brief_1: CuriosityBrief | None = None

        # Try CONNECT first
        connect_result = _find_connect_candidate(graph)
        if connect_result:
            a, b, d = connect_result
            tension = _pick_tension("connect", used_categories)
            used_categories.add(tension)
            brief_1 = _make_brief(
                slot=1, role="connect",
                anchor=a, target=b, domain=d, tension=tension,
                directive=_build_connect_directive(a, b, d, tension),
                why=f"Both '{a}' and '{b}' are known — only weakly linked. Deepening this connection accelerates cross-concept understanding.",
            )

        # Fallback to CHALLENGE
        if not brief_1:
            challenge_result = _find_challenge_candidate(gap_report, graph)
            if challenge_result:
                a, g, d, reason = challenge_result
                tension = _pick_tension("challenge", used_categories)
                used_categories.add(tension)
                brief_1 = _make_brief(
                    slot=1, role="challenge",
                    anchor=a, target=g, domain=d, tension=tension,
                    directive=_build_challenge_directive(a, g, d, tension, reason),
                    why=f"'{g}' is a HIGH-priority gap adjacent to what the reader knows ('{a}'). Challenging their model now accelerates gap closure.",
                )

        # Final fallback for slot 1
        if not brief_1:
            brief_1 = _fallback_brief(1, used_categories, domain)
            used_categories.add(brief_1.tension_category)

        # ── Slot 2: OUTWARD card (expand or challenge from different domain) ─

        brief_2: CuriosityBrief | None = None

        # Try EXPAND first (from learning plan curiosity areas)
        expand_result = _find_expand_candidate(learning_plan)
        if expand_result:
            conn, area_label, d, hook = expand_result
            tension = _pick_tension("expand", used_categories)
            used_categories.add(tension)
            brief_2 = _make_brief(
                slot=2, role="expand",
                anchor=conn, target=area_label, domain=d, tension=tension,
                directive=_build_expand_directive(conn, area_label, d, tension, hook),
                why=f"Learning plan identified '{area_label}' as a cross-domain curiosity target. Opens adjacent territory.",
            )

        # Fallback: REINFORCE
        if not brief_2:
            reinforce_result = _find_reinforce_candidate(graph, gap_report)
            if reinforce_result:
                a, t, d = reinforce_result
                tension = _pick_tension("reinforce", used_categories)
                used_categories.add(tension)
                brief_2 = _make_brief(
                    slot=2, role="reinforce",
                    anchor=a, target=t, domain=d, tension=tension,
                    directive=_build_reinforce_directive(a, t, d, tension),
                    why=f"'{a}' is the most-seen concept. Revealing '{t}' as its hidden layer deepens mastery without adding surface breadth.",
                )

        # Fallback: CHALLENGE from a different domain
        if not brief_2:
            challenge_result = _find_challenge_candidate(gap_report, graph)
            if challenge_result:
                a, g, d, reason = challenge_result
                if d != brief_1.domain:
                    tension = _pick_tension("challenge", used_categories)
                    used_categories.add(tension)
                    brief_2 = _make_brief(
                        slot=2, role="challenge",
                        anchor=a, target=g, domain=d, tension=tension,
                        directive=_build_challenge_directive(a, g, d, tension, reason),
                        why=f"Second challenge card from a different domain for cross-domain breadth.",
                    )

        if not brief_2:
            brief_2 = _fallback_brief(2, used_categories, domain)

        return CuriosityBriefing(
            card_1=brief_1,
            card_2=brief_2,
            prompt_injection=_format_injection(brief_1, brief_2),
        )

    except Exception:
        logger.exception("[curiosity_orchestrator] orchestrate() failed for %s", project_id)
        fb1 = _fallback_brief(1, set())
        fb2 = _fallback_brief(2, {fb1.tension_category})
        return CuriosityBriefing(
            card_1=fb1,
            card_2=fb2,
            prompt_injection=_format_injection(fb1, fb2),
        )


def get_curiosity_directives(project_id: str) -> str:
    """
    Return the prompt injection string for the two curiosity card slots.
    Returns "" if the project has no graph data yet.
    """
    try:
        from .learning_graph import get_graph
        graph = get_graph(project_id)
        if not graph.get("nodes"):
            return ""
        briefing = orchestrate(project_id)
        return briefing.prompt_injection
    except Exception:
        logger.exception("[curiosity_orchestrator] get_curiosity_directives failed for %s", project_id)
        return ""
