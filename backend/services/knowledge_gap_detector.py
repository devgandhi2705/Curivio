"""
Knowledge Gap Detector — Phase 4.2

Compares the user's knowledge graph against a curated domain knowledge
base to surface what they haven't learned yet.

Three gap categories
--------------------
  missing_concepts      — known concepts in the domain not yet in the graph
  missing_mechanisms    — causal processes that should be understood given
                          what the user already knows
  missing_strategic     — cross-domain or high-level strategic connections
                          that a domain expert would draw

Gap priorities
--------------
  high    — adjacent concepts are already known (one step away)
  medium  — same domain is active but the concept has no neighbours yet
  low     — domain is peripheral / not yet entered

Gap score
---------
  0.0 = full coverage, 1.0 = everything unknown
  Computed only over active domains (industries present in the graph).

Public API
----------
  detect_gaps(project_id, max_per_category=6) -> GapReport
  get_gap_summary(project_id, max_gaps=10) -> str
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── Data types ─────────────────────────────────────────────────────────────────

@dataclass
class GapItem:
    label:       str
    gap_type:    str   # "concept" | "mechanism" | "strategic"
    domain:      str
    priority:    str   # "high" | "medium" | "low"
    reason:      str
    known_neighbours: list[str] = field(default_factory=list)

@dataclass
class GapReport:
    missing_concepts:   list[GapItem]
    missing_mechanisms: list[GapItem]
    missing_strategic:  list[GapItem]
    gap_score:          float           # 0.0 = no gaps, 1.0 = everything missing
    active_domains:     list[str]
    recommended_next:   list[str]       # top 5 gap labels to explore next


# ── Domain knowledge base ─────────────────────────────────────────────────────
#
# Each entry: domain → {concepts, mechanisms, strategic}
# "adjacent" lists drive proximity scoring (if user knows any adjacent concept,
# the gap item gets HIGH priority).

_DOMAIN_KB: dict[str, dict[str, list[str]]] = {

    "Pharma": {
        "concepts": [
            "Supply Chain Risk",
            "API Dependency",
            "Generic Entry",
            "Patent Cliff",
            "Price Controls",
            "Drug Safety",
            "Market Access",
            "COGS Pressure",
            "Bioequivalence",
            "Clinical Trial Risk",
            "Regulatory Arbitrage",
            "Drug-Drug Interaction",
            "Reimbursement Dynamics",
            "Formulary Placement",
        ],
        "mechanisms": [
            "ANDA Filing Process",
            "IND Application Pathway",
            "FDA 505(b)(2) Approval Route",
            "GMP Audit Process",
            "Post-Market Surveillance",
            "Pharmacovigilance Reporting",
            "DSCSA Track-and-Trace",
            "Paragraph IV Challenge",
        ],
        "strategic": [
            "Geopolitics of API Sourcing",
            "Biosimilar Cannibalization of Branded Drugs",
            "Patent Expiry Cliff Effect",
            "PBM Price Negotiation Leverage",
            "Pharma-Regulatory Capture Dynamics",
            "India-China API Duopoly Risk",
        ],
    },

    "Finance": {
        "concepts": [
            "Liquidity Risk",
            "Counterparty Risk",
            "Leverage",
            "Drawdown",
            "Alpha Generation",
            "Market Making",
            "Information Asymmetry",
            "Principal-Agent Problem",
            "Systemic Risk",
            "Basis Risk",
            "Duration Risk",
            "Mark-to-Market Volatility",
        ],
        "mechanisms": [
            "Margin Call Cascade",
            "Interest Rate Transmission",
            "Risk-Adjusted Return Calculation",
            "Portfolio Rebalancing",
            "Carry Trade Mechanics",
            "Repo Market Funding Loop",
        ],
        "strategic": [
            "Fed Policy Spillover Effects",
            "Yield Curve Inversion as Recession Signal",
            "Correlation Breakdown During Crisis",
            "HFT Arms Race and Market Fragility",
            "Central Bank Balance Sheet as Market Backstop",
        ],
    },

    "Manufacturing": {
        "concepts": [
            "Capacity Utilization",
            "Unit Economics",
            "Throughput",
            "Cycle Time",
            "Overhead Absorption",
            "CapEx Intensity",
            "Make-vs-Buy Decision",
            "Quality Yield",
            "Scrap and Rework Cost",
            "Plant Utilization Break-Even",
        ],
        "mechanisms": [
            "Bottleneck Analysis",
            "Lean Production Pull System",
            "Statistical Process Control",
            "Setup Time Reduction (SMED)",
            "Overall Equipment Effectiveness (OEE)",
        ],
        "strategic": [
            "Nearshoring vs Offshoring Trade-offs",
            "Labor Arbitrage Decay",
            "Industrial Policy as Competitive Lever",
            "Energy Cost as Manufacturing Competitiveness Driver",
        ],
    },

    "AI/ML": {
        "concepts": [
            "Overfitting",
            "Generalization",
            "Data Efficiency",
            "Inference Cost",
            "Hallucination",
            "Fine-Tuning",
            "Embeddings",
            "Context Window Limits",
            "Latency-Accuracy Trade-off",
            "Model Alignment",
            "Benchmark Saturation",
        ],
        "mechanisms": [
            "Backpropagation",
            "Attention Mechanism",
            "RLHF Pipeline",
            "Retrieval-Augmented Generation",
            "Quantization",
            "Mixture-of-Experts Routing",
        ],
        "strategic": [
            "Commoditization of Foundation Models",
            "Data Moat as Competitive Defence",
            "AI Safety vs Capability Trade-off",
            "GPU Supply Concentration Risk",
            "Open-Source Disruption of Closed AI Labs",
        ],
    },

    "Technology": {
        "concepts": [
            "Network Effects",
            "Switching Costs",
            "Platform Flywheel",
            "API Lock-in",
            "Developer Ecosystem",
            "Technical Debt",
            "Scalability",
            "Latency",
            "Vertical vs Horizontal Integration",
            "Commoditization Pressure",
        ],
        "mechanisms": [
            "Viral Growth Loop",
            "Platform Economics",
            "Build-vs-Buy Decision Framework",
            "Migration Cost Calculation",
            "Churn Compression via Switching Costs",
        ],
        "strategic": [
            "Winner-Take-Most Dynamics in Software",
            "Open-Source as Moat Erosion Strategy",
            "Cloud Infrastructure Dependency Risk",
            "Vertical Integration vs Specialization Trade-off",
        ],
    },

    "Supply Chain": {
        "concepts": [
            "Bullwhip Effect",
            "Lead Time Variability",
            "Safety Stock",
            "Supplier Concentration Risk",
            "Single-Sourcing Risk",
            "Demand Uncertainty",
            "Inventory Carrying Cost",
            "Customs and Tariff Exposure",
            "Last-Mile Logistics Cost",
            "Forecast Accuracy",
        ],
        "mechanisms": [
            "Just-in-Time Replenishment",
            "Safety Stock Calculation",
            "Supplier Qualification Process",
            "Demand Sensing",
            "Cross-Docking",
        ],
        "strategic": [
            "Reshoring Dynamics and Cost Calculus",
            "Geopolitical Disruption Exposure Mapping",
            "Supply Chain Visibility vs Cost Trade-off",
            "Dual Sourcing as Risk Hedge",
            "China+1 Diversification Strategy",
        ],
    },

    "Healthcare": {
        "concepts": [
            "Reimbursement Risk",
            "Clinical Efficacy vs Real-World Effectiveness",
            "Health Technology Assessment",
            "Formulary Tier Placement",
            "Patient Adherence",
            "Health Economics",
            "Quality-Adjusted Life Year (QALY)",
            "Hospital Consolidation Pressure",
            "Value-Based Care",
        ],
        "mechanisms": [
            "HEOR Study Design",
            "Real-World Evidence Generation",
            "Coverage Decision Process",
            "Hospital Group Purchasing Organisation (GPO)",
            "Prior Authorisation Workflow",
        ],
        "strategic": [
            "Value-Based Care Shift Impact on Pharma Revenue",
            "Hospital Consolidation as Buyer Power",
            "Digital Health Disruption of Clinical Pathways",
            "AI Diagnostics FDA Approval Bottleneck",
        ],
    },

    "Energy": {
        "concepts": [
            "Energy Security",
            "Levelized Cost of Energy (LCOE)",
            "Grid Stability",
            "Capacity Factor",
            "Stranded Assets",
            "Energy Transition Risk",
            "Peak Demand Management",
            "Baseload vs Peaking Power",
            "Curtailment",
        ],
        "mechanisms": [
            "Merit Order Dispatch",
            "Grid Frequency Balancing",
            "Carbon Pricing Mechanism",
            "Power Purchase Agreement Structure",
            "Capacity Auction",
        ],
        "strategic": [
            "Geopolitics of Critical Mineral Supply",
            "Fossil Fuel Stranded Asset Risk",
            "Battery Storage Economics and Grid Parity",
            "Energy Sovereignty vs Import Dependency",
        ],
    },

    "Regulatory": {
        "concepts": [
            "Regulatory Capture",
            "Compliance Cost",
            "Rule-Making Process",
            "Enforcement Discretion",
            "Regulatory Arbitrage",
            "Safe Harbor Provisions",
            "Regulatory Lag",
            "Extraterritorial Jurisdiction",
        ],
        "mechanisms": [
            "Notice-and-Comment Rulemaking",
            "Administrative Adjudication",
            "Preemption Doctrine",
            "Consent Decree Process",
        ],
        "strategic": [
            "International Regulatory Divergence",
            "Regulatory Race to the Bottom",
            "Technology-Regulation Lag as Arbitrage Window",
            "Regulatory Moat via Compliance Complexity",
        ],
    },
}


# ── Cross-domain strategic connections ────────────────────────────────────────
#
# Each entry: anchor concepts that, if BOTH are known, suggest a strategic
# connection gap between them.

_CROSS_DOMAIN_STRATEGIC: list[dict] = [
    {
        "label":   "API Sourcing Geopolitics and Supply Chain Resilience",
        "domains": ["Pharma", "Supply Chain"],
        "anchors": ["api dependency", "supply chain risk", "geopolitics"],
        "reason":  "Drug manufacturing depends on active pharmaceutical ingredients concentrated in India and China — a supply chain risk with geopolitical dimensions.",
    },
    {
        "label":   "Regulatory Capital as Competitive Moat in Finance",
        "domains": ["Finance", "Regulatory"],
        "anchors": ["regulatory compliance", "systemic risk", "market making"],
        "reason":  "Basel capital requirements create barriers to entry that incumbents can weaponize as a competitive moat.",
    },
    {
        "label":   "FDA AI Medical Device Approval Bottleneck",
        "domains": ["AI/ML", "Healthcare"],
        "anchors": ["clinical trial", "machine learning", "regulatory"],
        "reason":  "AI models embedded in medical devices require FDA clearance, creating a regulatory bottleneck that slows AI healthcare adoption.",
    },
    {
        "label":   "Energy Cost as Manufacturing Competitiveness Driver",
        "domains": ["Energy", "Manufacturing"],
        "anchors": ["manufacturing", "energy", "capacity utilization"],
        "reason":  "Energy-intensive manufacturing sectors (steel, aluminum, chemicals) are structurally disadvantaged by high energy costs, driving offshoring decisions.",
    },
    {
        "label":   "Fintech Disruption of Traditional Banking Infrastructure",
        "domains": ["Technology", "Finance"],
        "anchors": ["platform flywheel", "network effects", "liquidity risk"],
        "reason":  "Software-native competitors exploit switching costs and network effects to unbundle profitable banking services without carrying regulatory overhead.",
    },
    {
        "label":   "Trade Policy Impact on Supply Chain Restructuring",
        "domains": ["Supply Chain", "Regulatory"],
        "anchors": ["supplier concentration risk", "customs", "compliance"],
        "reason":  "Tariffs and export controls force supply chain restructuring that appears as pure logistics cost but is actually a geopolitical risk management exercise.",
    },
    {
        "label":   "LLM Inference Cost and SaaS Margin Compression",
        "domains": ["AI/ML", "Technology"],
        "anchors": ["inference cost", "saas", "commoditization"],
        "reason":  "As AI becomes embedded in software products, inference costs erode margins — the unit economics of SaaS change structurally.",
    },
    {
        "label":   "Clinical Trial Risk and Biotech Valuation Cliff",
        "domains": ["Healthcare", "Finance"],
        "anchors": ["clinical trial risk", "drawdown", "market access"],
        "reason":  "Binary Phase 3 outcomes create violent valuation discontinuities — understanding both clinical and financial mechanics is necessary to read biotech risk.",
    },
]


# ── Similarity helpers ────────────────────────────────────────────────────────
# (local copies — avoids circular import from learning_memory_service)

def _norm(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _bigrams(text: str) -> frozenset[str]:
    words = text.split()
    if len(words) < 2:
        return frozenset(words)
    return frozenset(f"{words[i]} {words[i+1]}" for i in range(len(words) - 1))


def _jaccard(a: str, b: str) -> float:
    ba, bb = _bigrams(_norm(a)), _bigrams(_norm(b))
    if not ba and not bb:
        return 1.0 if a.lower().strip() == b.lower().strip() else 0.0
    if not ba or not bb:
        return 0.0
    u = len(ba | bb)
    return len(ba & bb) / u if u else 0.0


def _already_known(candidate: str, known_labels: set[str], threshold: float = 0.40) -> bool:
    """Return True if candidate is sufficiently similar to any known label."""
    cn = _norm(candidate)
    for label in known_labels:
        if _jaccard(cn, label) >= threshold:
            return True
    return False


# ── Active domain detection ───────────────────────────────────────────────────

def _active_domains(nodes: list[dict]) -> list[str]:
    """Return industry node labels present in the graph."""
    return [n["label"] for n in nodes if n["node_type"] == "industry"]


def _known_label_set(nodes: list[dict]) -> set[str]:
    """Normalised label set for fast fuzzy matching."""
    return {_norm(n["label"]) for n in nodes}


# ── Domain gap scoring ────────────────────────────────────────────────────────

def _keyword_proximity(candidate: str, known_labels: set[str]) -> list[str]:
    """
    Return known labels that share at least one significant content word
    (≥3 chars) with candidate. Used for proximity-based priority.
    """
    c_words = {w for w in _norm(candidate).split() if len(w) >= 3}
    matches: list[str] = []
    for label in known_labels:
        l_words = {w for w in label.split() if len(w) >= 3}
        if c_words & l_words:
            matches.append(label)
    return matches


def _priority_from_known(
    candidate: str,
    domain_concepts: list[str],
    known_labels: set[str],
    domain_active: bool,
) -> tuple[str, list[str]]:
    """
    Determine gap priority and list of known neighbours.

      high   — adjacent concept OR keyword overlap with a known label
      medium — domain is active but no close neighbours
      low    — domain not even entered yet
    """
    if not domain_active:
        return "low", []

    # Exact domain-level proximity (another KB item is already known)
    exact_neighbours = [
        c for c in domain_concepts
        if c != candidate and _already_known(c, known_labels)
    ]
    if exact_neighbours:
        return "high", exact_neighbours[:3]

    # Keyword-level proximity (a word in the gap item matches a known label)
    kw_matches = _keyword_proximity(candidate, known_labels)
    if kw_matches:
        return "high", kw_matches[:3]

    return "medium", []


def _score_domain_gaps(
    known_labels: set[str],
    active_domains: list[str],
    max_per_category: int,
) -> tuple[list[GapItem], list[GapItem], list[GapItem]]:
    """
    For each active domain, identify missing concepts, mechanisms,
    and strategic insights.
    """
    active_set = {d.lower() for d in active_domains}
    missing_concepts:   list[GapItem] = []
    missing_mechanisms: list[GapItem] = []
    missing_strategic:  list[GapItem] = []

    for domain, kb in _DOMAIN_KB.items():
        domain_active = domain.lower() in active_set

        # All co-domain concepts combined for proximity scoring
        all_domain_items = (
            kb.get("concepts", [])
            + kb.get("mechanisms", [])
            + kb.get("strategic", [])
        )

        for item in kb.get("concepts", []):
            if _already_known(item, known_labels):
                continue
            priority, neighbours = _priority_from_known(item, all_domain_items, known_labels, domain_active)
            missing_concepts.append(GapItem(
                label=item,
                gap_type="concept",
                domain=domain,
                priority=priority,
                reason=f"Core concept in {domain} not yet in your knowledge graph.",
                known_neighbours=neighbours[:3],
            ))

        for item in kb.get("mechanisms", []):
            if _already_known(item, known_labels):
                continue
            priority, neighbours = _priority_from_known(item, all_domain_items, known_labels, domain_active)
            missing_mechanisms.append(GapItem(
                label=item,
                gap_type="mechanism",
                domain=domain,
                priority=priority,
                reason=f"Causal process in {domain} you haven't mapped yet.",
                known_neighbours=neighbours[:3],
            ))

        for item in kb.get("strategic", []):
            if _already_known(item, known_labels):
                continue
            priority, neighbours = _priority_from_known(item, all_domain_items, known_labels, domain_active)
            missing_strategic.append(GapItem(
                label=item,
                gap_type="strategic",
                domain=domain,
                priority=priority,
                reason=f"Strategic insight in {domain} not yet connected in your graph.",
                known_neighbours=neighbours[:3],
            ))

    def _sort_key(g: GapItem) -> tuple[int, int]:
        p_rank = {"high": 0, "medium": 1, "low": 2}[g.priority]
        return (p_rank, -len(g.known_neighbours))

    def _dedup(items: list[GapItem]) -> list[GapItem]:
        seen: set[str] = set()
        result: list[GapItem] = []
        for item in items:
            key = _norm(item.label)
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result

    missing_concepts.sort(key=_sort_key)
    missing_mechanisms.sort(key=_sort_key)
    missing_strategic.sort(key=_sort_key)

    return (
        _dedup(missing_concepts)[:max_per_category],
        _dedup(missing_mechanisms)[:max_per_category],
        _dedup(missing_strategic)[:max_per_category],
    )


# ── Topology gap scoring ──────────────────────────────────────────────────────

def _score_topology_gaps(
    nodes: list[dict],
    edges: list[dict],
    known_labels: set[str],
) -> list[GapItem]:
    """
    Detect structural gaps from graph topology:
      - Isolated nodes (weight=1, degree ≤ 1) → shallow understanding
      - Orphan concepts: in domain KB but zero neighbours in graph
    These are returned as additional 'concept' gap items.
    """
    gaps: list[GapItem] = []

    # Build degree map
    degree: dict[str, int] = defaultdict(int)
    for e in edges:
        degree[e["from_key"]] += 1
        degree[e["to_key"]] += 1

    # Isolated nodes (seen once, almost no connections)
    for n in nodes:
        if n["node_type"] == "industry":
            continue
        if n["weight"] == 1 and degree.get(n["node_key"], 0) <= 1:
            gaps.append(GapItem(
                label=n["label"],
                gap_type="concept",
                domain="(graph topology)",
                priority="medium",
                reason=f"You've encountered '{n['label']}' but it has no connections — explore it deeper.",
                known_neighbours=[],
            ))

    return gaps[:4]  # cap topology hints to avoid noise


# ── Cross-domain strategic gap scoring ───────────────────────────────────────

def _score_cross_domain_gaps(
    known_labels: set[str],
    active_domains: list[str],
) -> list[GapItem]:
    """
    Detect strategic connections that should exist given the user's active
    domains but whose bridge insight isn't in the graph yet.
    """
    active_set = {d.lower() for d in active_domains}
    gaps: list[GapItem] = []

    for conn in _CROSS_DOMAIN_STRATEGIC:
        # Only surface if both domains are active
        conn_domains = {d.lower() for d in conn["domains"]}
        if not conn_domains.issubset(active_set):
            continue
        # Skip if the bridge insight is already known
        if _already_known(conn["label"], known_labels):
            continue
        # Check how many anchor concepts are known
        known_anchors = [a for a in conn["anchors"] if _already_known(a, known_labels)]
        priority = "high" if len(known_anchors) >= 2 else ("medium" if known_anchors else "low")
        gaps.append(GapItem(
            label=conn["label"],
            gap_type="strategic",
            domain=" × ".join(conn["domains"]),
            priority=priority,
            reason=conn["reason"],
            known_neighbours=known_anchors,
        ))

    gaps.sort(key=lambda g: ({"high": 0, "medium": 1, "low": 2}[g.priority], -len(g.known_neighbours)))
    return gaps


# ── Gap score calculation ─────────────────────────────────────────────────────

def _calc_gap_score(known_labels: set[str], active_domains: list[str]) -> float:
    """
    Coverage ratio over active domains only.
    An item counts as covered if exact-fuzzy match OR keyword overlap exists.
    Returns 0.0 (full coverage) to 1.0 (nothing known).
    """
    if not active_domains:
        return 1.0

    active_set = {d.lower() for d in active_domains}
    total, covered = 0, 0

    for domain, kb in _DOMAIN_KB.items():
        if domain.lower() not in active_set:
            continue
        all_items = kb.get("concepts", []) + kb.get("mechanisms", []) + kb.get("strategic", [])
        total += len(all_items)
        for item in all_items:
            if _already_known(item, known_labels) or _keyword_proximity(item, known_labels):
                covered += 1

    if total == 0:
        return 0.0
    return round(1.0 - (covered / total), 3)


# ── Recommended next topics ───────────────────────────────────────────────────

def _build_recommended_next(
    concepts: list[GapItem],
    mechanisms: list[GapItem],
    strategic: list[GapItem],
    n: int = 5,
) -> list[str]:
    """
    Merge all gap items, rank by priority + proximity, return top n labels.
    Prefer high-priority items with the most known neighbours.
    """
    combined = concepts + mechanisms + strategic
    combined.sort(key=lambda g: (
        {"high": 0, "medium": 1, "low": 2}[g.priority],
        -len(g.known_neighbours),
    ))
    seen: set[str] = set()
    result: list[str] = []
    for g in combined:
        if g.label not in seen:
            seen.add(g.label)
            result.append(g.label)
        if len(result) >= n:
            break
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def detect_gaps(project_id: str, max_per_category: int = 6) -> GapReport:
    """
    Analyse the project's knowledge graph and return a full GapReport.

    Raises nothing — returns an empty GapReport on any error.
    """
    try:
        from .learning_graph import get_graph

        graph        = get_graph(project_id)
        nodes        = graph["nodes"]
        edges        = graph["edges"]
        known_labels = _known_label_set(nodes)
        active       = _active_domains(nodes)

        # Domain-level gaps
        concepts, mechanisms, strategic = _score_domain_gaps(
            known_labels, active, max_per_category
        )

        # Add topology-based gaps to concepts
        topo_gaps = _score_topology_gaps(nodes, edges, known_labels)
        concepts = (concepts + topo_gaps)[:max_per_category + 2]

        # Cross-domain strategic gaps
        cross_gaps = _score_cross_domain_gaps(known_labels, active)
        strategic  = (strategic + cross_gaps)[:max_per_category + 2]

        gap_score = _calc_gap_score(known_labels, active)

        recommended = _build_recommended_next(concepts, mechanisms, strategic)

        return GapReport(
            missing_concepts=concepts,
            missing_mechanisms=mechanisms,
            missing_strategic=strategic,
            gap_score=gap_score,
            active_domains=active,
            recommended_next=recommended,
        )

    except Exception:
        logger.exception("[knowledge_gap_detector] detect_gaps failed for %s", project_id)
        return GapReport(
            missing_concepts=[],
            missing_mechanisms=[],
            missing_strategic=[],
            gap_score=1.0,
            active_domains=[],
            recommended_next=[],
        )


def get_gap_summary(project_id: str, max_gaps: int = 10) -> str:
    """
    Compact string representation for prompt injection.
    Returns "" when no active domains have been detected yet.
    """
    try:
        report = detect_gaps(project_id, max_per_category=max_gaps // 3 + 1)

        if not report.active_domains:
            return ""

        coverage_pct = round((1.0 - report.gap_score) * 100)
        lines: list[str] = []
        lines.append("══════════════════════════════════════")
        lines.append("KNOWLEDGE GAPS  ← what the user has NOT yet learned")
        lines.append("══════════════════════════════════════")
        lines.append(
            f"Domain coverage: {coverage_pct}%  |  "
            f"Active domains: {', '.join(report.active_domains)}"
        )

        if report.missing_concepts:
            lines.append("")
            lines.append("Missing Concepts (HIGH PRIORITY — introduce these):")
            high = [g for g in report.missing_concepts if g.priority == "high"]
            med  = [g for g in report.missing_concepts if g.priority != "high"]
            for g in (high + med)[: max_gaps // 3 + 1]:
                neighbours_note = (
                    f" (adjacent to: {', '.join(g.known_neighbours[:2])})"
                    if g.known_neighbours else ""
                )
                lines.append(f"  • [{g.domain}] {g.label}{neighbours_note}")

        if report.missing_mechanisms:
            lines.append("")
            lines.append("Missing Mechanisms (causal processes not yet mapped):")
            for g in report.missing_mechanisms[: max_gaps // 3 + 1]:
                lines.append(f"  • [{g.domain}] {g.label}")

        if report.missing_strategic:
            lines.append("")
            lines.append("Missing Strategic Connections (high-level blind spots):")
            for g in report.missing_strategic[: max_gaps // 3 + 1]:
                lines.append(f"  • [{g.domain}] {g.label}")

        if report.recommended_next:
            lines.append("")
            lines.append(f"Recommended next topics: {', '.join(report.recommended_next[:5])}")

        return "\n".join(lines)

    except Exception:
        logger.exception("[knowledge_gap_detector] get_gap_summary failed for %s", project_id)
        return ""
