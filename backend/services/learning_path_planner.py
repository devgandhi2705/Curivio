"""
Learning Path Planner — Phase 4.3

Synthesises the knowledge graph (what the user knows), knowledge gaps
(what's missing), progression stage (depth), and project interests to
produce a deliberate, sequenced learning plan.

Three outputs
-------------
  next_concepts      — top-ranked concepts ready to learn right now,
                       scored by readiness (proximity + stage fit + interest)
  progression_path   — ordered 5-7 step sequence toward mastery, each step
                       explaining why it comes next and what it unlocks
  curiosity_areas    — adjacent/cross-domain hooks that connect to what's
                       already known

Readiness score
---------------
  base          : high=0.80, medium=0.50, low=0.20  (from gap priority)
  +neighbour    : +0.05 per known neighbour, cap +0.20
  +stage_fit    : +0.10 if gap type matches current learning stage
  +interest     : +0.05 per matching project keyword, cap +0.15
  capped at 1.0

Public API
----------
  plan(project_id, max_next=8, path_length=7) -> LearningPlan
  get_plan_for_prompt(project_id) -> str
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger(__name__)


# ── Data types ─────────────────────────────────────────────────────────────────

@dataclass
class NextConcept:
    label:           str
    domain:          str
    gap_type:        str    # "concept" | "mechanism" | "strategic"
    readiness_score: float  # 0.0 – 1.0
    reason:          str
    known_context:   list[str] = field(default_factory=list)


@dataclass
class PathStep:
    step_number:        int
    label:              str
    domain:             str
    gap_type:           str
    why_next:           str
    unlocks:            list[str] = field(default_factory=list)
    estimated_sessions: int = 2


@dataclass
class CuriosityArea:
    label:              str
    domain:             str
    connection:         str   # how it links to what the user already knows
    hook:               str   # the surprising or interesting angle


@dataclass
class LearningPlan:
    project_id:       str
    current_stage:    str
    active_domains:   list[str]
    next_concepts:    list[NextConcept]
    progression_path: list[PathStep]
    curiosity_areas:  list[CuriosityArea]
    coverage_pct:     int         # 0–100


# ── Stage → gap-type affinity ──────────────────────────────────────────────────

_STAGE_GAP_FIT: dict[str, frozenset[str]] = {
    "foundation":   frozenset({"concept"}),
    "mechanisms":   frozenset({"concept", "mechanism"}),
    "dependencies": frozenset({"mechanism", "concept"}),
    "optimization": frozenset({"mechanism", "strategic"}),
    "geopolitical": frozenset({"strategic"}),
    "disruption":   frozenset({"strategic", "concept"}),
    "synthesis":    frozenset({"strategic"}),
}

_STAGE_ORDER = [
    "foundation", "mechanisms", "dependencies",
    "optimization", "geopolitical", "disruption", "synthesis",
]


# ── Cross-domain curiosity hooks ───────────────────────────────────────────────

_CURIOSITY_HOOKS: dict[frozenset[str], CuriosityArea] = {
    frozenset({"Pharma", "Finance"}): CuriosityArea(
        label="Biotech Valuation and Clinical Trial Risk",
        domain="Finance",
        connection="The pharma companies you're learning about are publicly traded",
        hook="FDA Phase 3 outcomes are binary events — a single trial result can halve or double a company's market cap overnight.",
    ),
    frozenset({"Pharma", "Supply Chain"}): CuriosityArea(
        label="API Sourcing Concentration Risk",
        domain="Supply Chain",
        connection="Every drug you've studied has active ingredients sourced from somewhere",
        hook="India and China together supply ~70% of global active pharmaceutical ingredients. One export ban can freeze Western drug production.",
    ),
    frozenset({"Pharma", "Regulatory"}): CuriosityArea(
        label="Regulatory Arbitrage in Drug Markets",
        domain="Regulatory",
        connection="You've seen how FDA shapes pharma — now see how companies play regulators against each other",
        hook="Drug makers choose where to seek first approval strategically. FDA approval can be a stepping stone to faster EMA clearance.",
    ),
    frozenset({"Finance", "Technology"}): CuriosityArea(
        label="Fintech Unbundling of Traditional Banking",
        domain="Technology",
        connection="Financial systems you've studied are being disaggregated by software",
        hook="Stripe, Square, and Robinhood each took one profitable slice of banking and rebuilt it with zero branches. The rest is still exposed.",
    ),
    frozenset({"AI/ML", "Healthcare"}): CuriosityArea(
        label="AI Diagnostics and the FDA Bottleneck",
        domain="Healthcare",
        connection="AI models you know about are entering clinical settings",
        hook="The FDA has approved ~700 AI medical devices — but the approval framework was written for drugs, creating a structural mismatch.",
    ),
    frozenset({"AI/ML", "Technology"}): CuriosityArea(
        label="Inference Cost and SaaS Margin Compression",
        domain="Technology",
        connection="AI you've studied is now embedded in software products you pay for",
        hook="Every ChatGPT query costs OpenAI ~$0.01. At scale, inference costs eat SaaS margins unless you own the chips.",
    ),
    frozenset({"Supply Chain", "Regulatory"}): CuriosityArea(
        label="Export Controls as Supply Chain Weapons",
        domain="Regulatory",
        connection="Supply chain risks you've mapped have a regulatory dimension",
        hook="The US chip export controls aren't trade policy — they're supply chain warfare. Understanding the BIS Entity List is now a supply chain skill.",
    ),
    frozenset({"Energy", "Manufacturing"}): CuriosityArea(
        label="Energy Cost as Industrial Competitiveness",
        domain="Energy",
        connection="Manufacturing economics you've explored depend on a hidden input",
        hook="Germany's industrial base ran on cheap Russian gas for 20 years. The 2022 price spike wiped 20% of German chemical industry profitability overnight.",
    ),
    frozenset({"Finance", "Regulatory"}): CuriosityArea(
        label="Regulatory Capital as a Competitive Moat",
        domain="Finance",
        connection="Regulatory frameworks you've studied create structural advantages",
        hook="JPMorgan's biggest competitive advantage isn't its bankers — it's that complying with Basel III costs $2B/year, which only giants can afford.",
    ),
    frozenset({"Technology", "Regulatory"}): CuriosityArea(
        label="Technology-Regulation Lag as Arbitrage Window",
        domain="Regulatory",
        connection="Technology you've studied always moves faster than the regulators watching it",
        hook="Uber launched in 2009. Cities started banning it in 2014. By then it had 1 million drivers. The regulation lag IS the growth window.",
    ),
}


# ── Domain KB (mirrors knowledge_gap_detector — local access avoids re-import) ──

_DOMAIN_KB_SEQUENCE: dict[str, list[str]] = {
    "Pharma":        ["Supply Chain Risk", "API Dependency", "Generic Entry", "Patent Cliff",
                      "Price Controls", "COGS Pressure", "Clinical Trial Risk",
                      "ANDA Filing Process", "FDA 505(b)(2) Approval Route", "GMP Audit Process",
                      "Geopolitics of API Sourcing", "Biosimilar Cannibalization of Branded Drugs",
                      "Patent Expiry Cliff Effect", "India-China API Duopoly Risk"],
    "Finance":       ["Liquidity Risk", "Counterparty Risk", "Leverage", "Drawdown",
                      "Market Making", "Information Asymmetry", "Systemic Risk",
                      "Margin Call Cascade", "Interest Rate Transmission", "Carry Trade Mechanics",
                      "Fed Policy Spillover Effects", "Yield Curve Inversion as Recession Signal",
                      "Correlation Breakdown During Crisis"],
    "Manufacturing": ["Capacity Utilization", "Unit Economics", "Throughput", "Overhead Absorption",
                      "Bottleneck Analysis", "Lean Production Pull System",
                      "Nearshoring vs Offshoring Trade-offs", "Industrial Policy as Competitive Lever"],
    "AI/ML":         ["Overfitting", "Generalization", "Data Efficiency", "Inference Cost",
                      "Hallucination", "Fine-Tuning", "Embeddings",
                      "Backpropagation", "RLHF Pipeline", "Retrieval-Augmented Generation",
                      "Commoditization of Foundation Models", "Data Moat as Competitive Defence",
                      "Open-Source Disruption of Closed AI Labs"],
    "Technology":    ["Network Effects", "Switching Costs", "Platform Flywheel", "API Lock-in",
                      "Technical Debt", "Scalability",
                      "Viral Growth Loop", "Platform Economics",
                      "Winner-Take-Most Dynamics in Software", "Open-Source as Moat Erosion Strategy"],
    "Supply Chain":  ["Bullwhip Effect", "Lead Time Variability", "Safety Stock",
                      "Supplier Concentration Risk", "Inventory Carrying Cost",
                      "Just-in-Time Replenishment", "Demand Sensing",
                      "Reshoring Dynamics and Cost Calculus", "China+1 Diversification Strategy"],
    "Healthcare":    ["Reimbursement Risk", "Health Technology Assessment", "Patient Adherence",
                      "Quality-Adjusted Life Year (QALY)", "Hospital Consolidation Pressure",
                      "HEOR Study Design", "Coverage Decision Process",
                      "Value-Based Care Shift Impact on Pharma Revenue"],
    "Energy":        ["Energy Security", "Levelized Cost of Energy (LCOE)", "Stranded Assets",
                      "Energy Transition Risk",
                      "Merit Order Dispatch", "Carbon Pricing Mechanism",
                      "Geopolitics of Critical Mineral Supply", "Battery Storage Economics and Grid Parity"],
    "Regulatory":    ["Regulatory Capture", "Compliance Cost", "Regulatory Arbitrage",
                      "Safe Harbor Provisions", "Regulatory Lag",
                      "Notice-and-Comment Rulemaking", "Consent Decree Process",
                      "International Regulatory Divergence", "Regulatory Moat via Compliance Complexity"],
}


# ── Text helpers ───────────────────────────────────────────────────────────────

def _norm(text: str) -> str:
    t = text.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _word_overlap(a: str, b: str) -> int:
    aw = {w for w in _norm(a).split() if len(w) >= 3}
    bw = {w for w in _norm(b).split() if len(w) >= 3}
    return len(aw & bw)


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _load_project_context(project_id: str) -> tuple[list[str], str]:
    """Return (keywords, difficulty) for the project."""
    try:
        from ..utils.db import get_connection
        with get_connection() as conn:
            row = conn.execute(
                "SELECT keywords, difficulty FROM learning_projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        if not row:
            return [], "intermediate"
        kw = json.loads(row["keywords"] or "[]")
        return kw, (row["difficulty"] or "intermediate")
    except Exception:
        logger.exception("[learning_path_planner] _load_project_context failed")
        return [], "intermediate"


def _load_progression_stage(project_id: str) -> str:
    """Return the current learning stage from project_learning_memory."""
    try:
        from .learning_memory_service import get_memory
        mem = get_memory(project_id)
        return mem.get("progression_stage", "foundation")
    except Exception:
        return "foundation"


# ── Readiness scoring ──────────────────────────────────────────────────────────

_PRIORITY_BASE = {"high": 0.80, "medium": 0.50, "low": 0.20}


def _readiness_score(
    gap_item,          # GapItem
    stage: str,
    project_keywords: list[str],
) -> float:
    base = _PRIORITY_BASE.get(gap_item.priority, 0.50)

    # Neighbour boost: +0.05 per known neighbour, cap +0.20
    neighbour_boost = min(len(gap_item.known_neighbours) * 0.05, 0.20)

    # Stage fit: +0.10 if this gap type is recommended at the current stage
    stage_types = _STAGE_GAP_FIT.get(stage, frozenset())
    stage_boost = 0.10 if gap_item.gap_type in stage_types else 0.0

    # Interest alignment: +0.05 per project keyword matching the concept, cap +0.15
    interest_matches = sum(
        1 for kw in project_keywords if _word_overlap(kw, gap_item.label) > 0
    )
    interest_boost = min(interest_matches * 0.05, 0.15)

    return min(base + neighbour_boost + stage_boost + interest_boost, 1.0)


# ── Next concept ranking ───────────────────────────────────────────────────────

def _reason_for_concept(gap_item, stage: str) -> str:
    if gap_item.known_neighbours:
        neighbours_str = ", ".join(gap_item.known_neighbours[:2])
        return f"Directly adjacent to what you already know ({neighbours_str}) — one step deeper."
    if gap_item.priority == "high":
        return f"Core {gap_item.domain} concept with high contextual readiness."
    if gap_item.gap_type == "mechanism":
        return f"You know the 'what' in {gap_item.domain} — this explains the 'how'."
    if gap_item.gap_type == "strategic":
        return f"Strategic insight that connects multiple {gap_item.domain} concepts you'll encounter."
    return f"Important {gap_item.domain} concept not yet in your knowledge graph."


def _rank_next_concepts(
    gap_report,     # GapReport
    stage: str,
    keywords: list[str],
    max_n: int,
) -> list[NextConcept]:
    all_gaps = (
        gap_report.missing_concepts
        + gap_report.missing_mechanisms
        + gap_report.missing_strategic
    )

    scored: list[tuple[float, object]] = []
    seen: set[str] = set()

    for gap in all_gaps:
        key = _norm(gap.label)
        if key in seen:
            continue
        seen.add(key)
        score = _readiness_score(gap, stage, keywords)
        scored.append((score, gap))

    scored.sort(key=lambda x: -x[0])

    return [
        NextConcept(
            label=gap.label,
            domain=gap.domain,
            gap_type=gap.gap_type,
            readiness_score=round(score, 2),
            reason=_reason_for_concept(gap, stage),
            known_context=gap.known_neighbours[:3],
        )
        for score, gap in scored[:max_n]
    ]


# ── Progression path building ──────────────────────────────────────────────────

def _unlocks_for_concept(
    label: str,
    domain: str,
    gap_report,     # GapReport
) -> list[str]:
    """
    Find concepts in the same domain KB that come AFTER this concept and
    are still gaps. These are what this step "unlocks".
    """
    sequence = _DOMAIN_KB_SEQUENCE.get(domain, [])
    all_gap_labels = {
        _norm(g.label)
        for g in (gap_report.missing_concepts + gap_report.missing_mechanisms + gap_report.missing_strategic)
    }
    try:
        idx = next(i for i, item in enumerate(sequence) if _word_overlap(label, item) >= 2)
        return [
            sequence[j] for j in range(idx + 1, min(idx + 4, len(sequence)))
            if _norm(sequence[j]) in all_gap_labels
        ]
    except StopIteration:
        # Concept not found in sequence by overlap — use label-based fallback
        return []


def _why_next(
    step_idx: int,
    concept: NextConcept,
    prev_concept: NextConcept | None,
    stage: str,
) -> str:
    if step_idx == 0:
        if concept.known_context:
            ctx = ", ".join(concept.known_context[:2])
            return f"Start here — it's one step from what you already know ({ctx})."
        return f"Entry point into {concept.domain} at the {stage} stage."

    prev_label = prev_concept.label if prev_concept else "previous concept"

    if concept.gap_type == "mechanism" and (not prev_concept or prev_concept.gap_type == "concept"):
        return f"You now have the 'what' ({prev_label}). This explains the 'how'."

    if concept.gap_type == "strategic" and (not prev_concept or prev_concept.gap_type in ("concept", "mechanism")):
        return f"The mechanisms are clear. Now see the strategic picture that emerges from {prev_label}."

    if prev_concept and prev_concept.domain != concept.domain:
        return f"Cross-domain step — connects {prev_concept.domain} logic to {concept.domain} patterns."

    return f"Natural next layer after {prev_label} — same domain, higher abstraction."


def _estimate_sessions(gap_type: str) -> int:
    return {"concept": 2, "mechanism": 3, "strategic": 2}.get(gap_type, 2)


def _build_progression_path(
    next_concepts: list[NextConcept],
    gap_report,     # GapReport
    stage: str,
    path_length: int,
) -> list[PathStep]:
    """
    Build an ordered path from next_concepts.

    Sequencing rules:
    1. Lead with the highest-readiness concept.
    2. Prefer concept → mechanism → strategic ordering within each domain.
    3. Interleave domains to avoid monotony.
    4. Each step carries a 'why_next' narrative and an 'unlocks' list.
    """
    if not next_concepts:
        return []

    # Sort: by readiness desc, then by gap_type order within same domain
    type_order = {"concept": 0, "mechanism": 1, "strategic": 2}
    ranked = sorted(next_concepts, key=lambda c: (-c.readiness_score, type_order.get(c.gap_type, 1)))

    # Interleave: alternate domains where possible
    domain_buckets: dict[str, list[NextConcept]] = defaultdict(list)
    for c in ranked:
        domain_buckets[c.domain].append(c)

    interleaved: list[NextConcept] = []
    seen_paths: set[str] = set()
    while len(interleaved) < path_length and any(domain_buckets.values()):
        for domain in list(domain_buckets.keys()):
            if not domain_buckets[domain]:
                del domain_buckets[domain]
                continue
            candidate = domain_buckets[domain].pop(0)
            key = _norm(candidate.label)
            if key not in seen_paths:
                seen_paths.add(key)
                interleaved.append(candidate)
            if len(interleaved) >= path_length:
                break

    path: list[PathStep] = []
    for i, concept in enumerate(interleaved):
        prev = interleaved[i - 1] if i > 0 else None
        path.append(PathStep(
            step_number=i + 1,
            label=concept.label,
            domain=concept.domain,
            gap_type=concept.gap_type,
            why_next=_why_next(i, concept, prev, stage),
            unlocks=_unlocks_for_concept(concept.label, concept.domain, gap_report),
            estimated_sessions=_estimate_sessions(concept.gap_type),
        ))

    return path


# ── Curiosity area detection ───────────────────────────────────────────────────

def _find_curiosity_areas(
    graph: dict,
    gap_report,     # GapReport
    keywords: list[str],
) -> list[CuriosityArea]:
    """
    Generate 3–5 cross-domain curiosity areas by:
    1. Matching active domain pairs against pre-defined hooks
    2. Surfacing trend nodes from the graph
    3. Falling back to unexplored adjacent domains
    """
    active_domains = set(gap_report.active_domains)
    areas: list[CuriosityArea] = []
    seen_domains: set[str] = set()

    # 1. Pre-defined cross-domain hooks
    for domain_pair, area in _CURIOSITY_HOOKS.items():
        overlap = domain_pair & active_domains
        new_domains = domain_pair - active_domains
        if overlap and new_domains:
            if area.domain not in seen_domains:
                seen_domains.add(area.domain)
                areas.append(area)
        elif len(overlap) == 2 and area.domain not in seen_domains:
            # Both domains active — still surface the cross-domain connection
            seen_domains.add(area.domain)
            areas.append(area)

    # 2. Trend nodes from the graph — these are natural curiosity hooks
    trend_nodes = [n for n in graph.get("nodes", []) if n["node_type"] == "trend"]
    for node in trend_nodes[:2]:
        domain = next(
            (n["label"] for n in graph.get("nodes", []) if n["node_type"] == "industry"),
            "Adjacent domain"
        )
        if domain not in seen_domains:
            areas.append(CuriosityArea(
                label=node["label"],
                domain=domain,
                connection="You've encountered this trend in your recent learning",
                hook=f"'{node['label']}' is still unfolding — the full implications haven't been mapped yet.",
            ))

    # 3. Domains in cross-domain strategic gaps not yet active
    for gap in gap_report.missing_strategic:
        if " × " in gap.domain:
            for d in gap.domain.split(" × "):
                d = d.strip()
                if d not in active_domains and d not in seen_domains and len(areas) < 5:
                    seen_domains.add(d)
                    areas.append(CuriosityArea(
                        label=gap.label,
                        domain=d,
                        connection=f"Bridges your {list(active_domains)[0] if active_domains else 'current'} knowledge to {d}",
                        hook=gap.reason,
                    ))

    return areas[:5]


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def plan(
    project_id: str,
    max_next: int = 8,
    path_length: int = 7,
) -> LearningPlan:
    """
    Build a full LearningPlan for the project.
    Non-fatal — returns an empty plan on any error.
    """
    try:
        from .knowledge_gap_detector import detect_gaps
        from .learning_graph import get_graph

        keywords, difficulty = _load_project_context(project_id)
        all_keywords = keywords
        stage = _load_progression_stage(project_id)
        gap_report = detect_gaps(project_id)
        graph = get_graph(project_id)

        next_concepts = _rank_next_concepts(gap_report, stage, all_keywords, max_next)
        progression = _build_progression_path(next_concepts, gap_report, stage, path_length)
        curiosity = _find_curiosity_areas(graph, gap_report, all_keywords)

        coverage_pct = round((1.0 - gap_report.gap_score) * 100)

        return LearningPlan(
            project_id=project_id,
            current_stage=stage,
            active_domains=gap_report.active_domains,
            next_concepts=next_concepts,
            progression_path=progression,
            curiosity_areas=curiosity,
            coverage_pct=coverage_pct,
        )

    except Exception:
        logger.exception("[learning_path_planner] plan() failed for %s", project_id)
        return LearningPlan(
            project_id=project_id,
            current_stage="foundation",
            active_domains=[],
            next_concepts=[],
            progression_path=[],
            curiosity_areas=[],
            coverage_pct=0,
        )


def get_plan_for_prompt(project_id: str) -> str:
    """
    Compact multi-line string for injection into feed generation prompts.
    Returns "" when the plan is empty (new project, no graph yet).
    """
    try:
        lp = plan(project_id)

        if not lp.active_domains and not lp.next_concepts:
            return ""

        lines: list[str] = []
        lines.append("══════════════════════════════════════")
        lines.append("LEARNING PLAN  <- generate content that advances this plan")
        lines.append("══════════════════════════════════════")
        lines.append(
            f"Stage: {lp.current_stage.upper()}  |  "
            f"Domains: {', '.join(lp.active_domains)}  |  "
            f"Coverage: {lp.coverage_pct}%"
        )

        if lp.next_concepts:
            lines.append("")
            lines.append("Next Concepts (introduce in order of readiness):")
            for i, c in enumerate(lp.next_concepts[:6], 1):
                ctx = f" <- {', '.join(c.known_context[:2])}" if c.known_context else ""
                lines.append(
                    f"  {i}. [{c.readiness_score:.2f}] {c.label} [{c.domain}]{ctx}"
                )

        if lp.progression_path:
            lines.append("")
            lines.append("Learning Progression (follow this sequence):")
            for step in lp.progression_path:
                unlocks_str = (
                    "  -> unlocks: " + ", ".join(step.unlocks[:2])
                    if step.unlocks else ""
                )
                lines.append(
                    f"  Step {step.step_number}: {step.label}"
                    f"{unlocks_str}"
                )
                lines.append(f"    Why: {step.why_next}")

        if lp.curiosity_areas:
            lines.append("")
            lines.append("Curiosity Areas (spark cross-domain thinking):")
            for ca in lp.curiosity_areas[:3]:
                lines.append(f"  * [{ca.domain}] {ca.label}")
                lines.append(f"    {ca.hook}")

        return "\n".join(lines)

    except Exception:
        logger.exception("[learning_path_planner] get_plan_for_prompt failed for %s", project_id)
        return ""
