"""
Learning Graph Engine — Phase 4.1

Per-project knowledge graph: tracks concepts, mechanisms, industries,
examples, companies, and trends as nodes with typed relationships.

Runs automatically after every feed generation. No extra LLM calls —
extraction is rule-based and structural.

Node types
----------
  concept   — abstract idea (Trust, Regulatory Moat, Drug Pricing)
  mechanism — causal process (FDA Approval Gate, Price Anchoring)
  industry  — sector (Pharma, Finance, Supply Chain)
  example   — concrete named instance (Vioxx recall, mRNA rollout)
  company   — named organisation (Pfizer, Sun Pharma)
  trend     — directional shift (Biosimilar growth, AI in drug discovery)

Relation types
--------------
  depends_on    — X requires Y to function or exist
  leads_to      — X causally produces Y
  enables       — X makes Y possible
  part_of       — X is a component or sub-element of Y
  example_of    — X is a concrete instance of Y
  regulates     — X exerts control/oversight over Y
  disrupts      — X undermines or replaces Y
  competes_with — X and Y are rivals (symmetric)
  related_to    — generic co-occurrence (weakest signal)

Public API
----------
  upsert_from_package(project_id, package) -> None
  get_graph(project_id) -> GraphDict
  get_neighbors(project_id, node_key, depth=2) -> list[dict]
  get_graph_summary(project_id, max_nodes=20) -> str
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict, deque
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

VALID_NODE_TYPES = frozenset(
    {"concept", "mechanism", "industry", "example", "company", "trend"}
)

VALID_RELATIONS = frozenset({
    "depends_on", "leads_to", "enables", "part_of",
    "example_of", "regulates", "disrupts", "competes_with", "related_to",
})

_REVERSE_RELATION: dict[str, str] = {
    "depends_on":  "leads_to",
    "leads_to":    "depends_on",
    "enables":     "part_of",
    "part_of":     "enables",
    "regulates":   "related_to",
    "disrupts":    "related_to",
}

# ── Industry map (mirrors learning_memory_service) ─────────────────────────────

_INDUSTRY_MAP: dict[str, list[str]] = {
    "Pharma":        ["pharma", "pharmaceutical", "drug", "fda", "anda", "api ", "generics", "biosimilar", "clinical trial"],
    "Finance":       ["finance", "financial market", "invest", "stock", "quant", "hedge fund", "trading", "portfolio", "asset"],
    "Manufacturing": ["manufactur", "factory", "production", "plant", "assembly", "automation", "industrial"],
    "AI/ML":         ["machine learning", "deep learning", "ml model", "artificial intelligence", "neural network", "llm"],
    "Technology":    ["software", "algorithm", "compute", "cloud", "platform", "saas", "hardware"],
    "Supply Chain":  ["supply chain", "logistics", "procurement", "inventory", "distribution", "sourcing"],
    "Healthcare":    ["hospital", "clinical", "patient", "treatment", "medical device", "biotech"],
    "Energy":        ["energy", "oil ", "gas ", "solar", "wind power", "renewable", "battery", "grid"],
    "Regulatory":    ["regulat", "compliance", "fda", "ema", "sec ", "ftc ", "policy maker", "legislation"],
}

# ── Trend signal words ─────────────────────────────────────────────────────────

_TREND_SIGNALS = [
    "growing", "rising", "emerging", "shifting", "expanding", "declining",
    "surge", "boom", "collapse", "transition", "revolution", "disruption",
    "adoption", "growth of", "rise of", "fall of", "future of",
]

# ── Proper-noun extraction ─────────────────────────────────────────────────────

_PROPER_NOUN_RE = re.compile(r'\b([A-Z][a-z]{1,}(?:[\s\-][A-Z][a-z]{1,}){0,3})\b')

_COMMON_STARTERS: frozenset[str] = frozenset({
    "The", "This", "That", "These", "Those", "When", "What", "Where", "Why", "How",
    "While", "As", "If", "Although", "Since", "Because", "Most", "Many", "Some",
    "Few", "Their", "Its", "Our", "Your", "His", "Her", "With", "For", "And", "But",
    "Or", "Not", "Even", "Still", "Also", "Only", "Just", "Both", "Each", "All",
    "More", "Less", "New", "Old", "First", "Last", "Next", "After", "Before",
    "Rather", "Instead", "However", "Therefore", "Thus", "Hence", "Yet", "Despite",
    "During", "Under", "Over", "Between", "Through", "Within", "Without", "Among",
    "Around", "Against", "Beyond", "Across", "Into", "Onto", "Upon", "Along",
    "Today", "Here", "There", "Now", "Then", "Once", "Key", "Major", "Global",
})

# Known company name signals (short list to avoid FP)
_COMPANY_SIGNALS = [
    "inc", "corp", "ltd", "llc", "plc", "gmbh", "pharma", "bio", "tech",
    "labs", "systems", "group", "holdings", "ventures",
]

# ── Relation keyword patterns ─────────────────────────────────────────────────

_RELATION_KEYWORDS: dict[str, list[str]] = {
    "depends_on":    ["depends on", "requires", "relies on", "needs", "contingent on"],
    "leads_to":      ["leads to", "results in", "causes", "drives", "produces", "triggers"],
    "enables":       ["enables", "allows", "facilitates", "powers", "supports", "unlocks"],
    "regulates":     ["regulates", "governs", "controls", "oversees", "mandates", "approves"],
    "disrupts":      ["disrupts", "threatens", "replaces", "undermines", "displaces", "erodes"],
    "competes_with": ["competes with", "rivals", "challenges", "versus"],
    "part_of":       ["part of", "component of", "within", "belongs to", "subset of"],
}


# ── Node key normalisation ─────────────────────────────────────────────────────

def _make_key(label: str) -> str:
    """Normalise a label to a stable node key (max 64 chars)."""
    key = label.lower().strip()
    key = re.sub(r"[^\w\s\-]", "", key)
    key = re.sub(r"[\s\-]+", "_", key)
    return key[:64]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Node type classification ──────────────────────────────────────────────────

def _classify_proper_noun(label: str, context: str) -> str:
    """Heuristically classify a proper noun as company or example."""
    label_lower = label.lower()
    ctx_lower = context.lower()
    if any(sig in label_lower for sig in _COMPANY_SIGNALS):
        return "company"
    # If context is about a company/org, call it a company
    if any(kw in ctx_lower for kw in ["company", "firm", "corporation", "startup", "founded"]):
        return "company"
    return "example"


def _extract_industries(text: str) -> list[str]:
    t = text.lower()
    return [label for label, kws in _INDUSTRY_MAP.items() if any(kw in t for kw in kws)]


def _is_trend(text: str) -> bool:
    t = text.lower()
    return any(sig in t for sig in _TREND_SIGNALS)


def _extract_proper_nouns(text: str) -> list[str]:
    matches = _PROPER_NOUN_RE.findall(text)
    return [m for m in matches if m.split()[0] not in _COMMON_STARTERS and len(m) > 3]


# ── Relation extraction from text ─────────────────────────────────────────────

def _find_relation_between(text: str, label_a: str, label_b: str) -> str | None:
    """
    Detect a typed relation between label_a and label_b within text.
    Searches within a 150-char window after either label appears.
    Returns the relation type or None (falls back to related_to by caller).
    """
    t = text.lower()
    la = label_a.lower()
    lb = label_b.lower()

    for first, second, forward in [(la, lb, True), (lb, la, False)]:
        idx = t.find(first)
        if idx == -1:
            continue
        after = t[idx + len(first): idx + len(first) + 150]
        if second not in after:
            continue
        bridge = after[: after.find(second) + len(second)]
        for relation, keywords in _RELATION_KEYWORDS.items():
            if any(kw in bridge for kw in keywords):
                if forward:
                    return relation
                # Reverse the relation direction
                return _REVERSE_RELATION.get(relation, relation)
    return None


# ── Card-level extraction ──────────────────────────────────────────────────────

def _extract_from_card(
    card: dict,
    is_core: bool,
) -> tuple[list[dict], list[tuple[str, str, str]]]:
    """
    Extract (nodes, edges) from a single card.

    nodes: list of {label, node_type, node_key}
    edges: list of (from_key, to_key, relation)
    """
    title   = (card.get("title") or "").strip()
    summary = (card.get("summary") or "").strip()
    edu     = (card.get("educational_explanation") or "").strip()
    category = (card.get("category") or "").strip()
    full_text = f"{title} {summary} {edu}"

    nodes: list[dict] = []
    seen_keys: set[str] = set()

    def _add_node(label: str, node_type: str) -> str | None:
        if not label or len(label) < 3:
            return None
        k = _make_key(label)
        if not k or k in seen_keys:
            return k
        seen_keys.add(k)
        nodes.append({"label": label, "node_type": node_type, "node_key": k})
        return k

    # 1. Category → concept
    if category:
        _add_node(category, "concept")

    # 2. Educational card title → mechanism
    if is_core and card.get("content_type") == "educational" and title:
        _add_node(title, "mechanism")
    elif title and _is_trend(title):
        _add_node(title, "trend")

    # 3. Industries → industry nodes
    for ind in _extract_industries(full_text):
        _add_node(ind, "industry")

    # 4. Proper nouns from title + first sentence → company or example
    first_sentence = summary.split(".")[0] if summary else ""
    for pn in _extract_proper_nouns(f"{title} {first_sentence}"):
        ntype = _classify_proper_noun(pn, full_text)
        _add_node(pn, ntype)

    # ── Edge extraction ──────────────────────────────────────────────────────

    edges: list[tuple[str, str, str]] = []
    node_keys = [n["node_key"] for n in nodes]
    node_labels = {n["node_key"]: n["label"] for n in nodes}

    # Structural: examples/companies → example_of → their industry
    industry_keys = [n["node_key"] for n in nodes if n["node_type"] == "industry"]
    instance_keys = [n["node_key"] for n in nodes if n["node_type"] in ("example", "company")]
    for ik in instance_keys:
        for indk in industry_keys:
            edges.append((ik, indk, "example_of"))

    # Structural: mechanisms → part_of → industry (first one)
    mech_keys = [n["node_key"] for n in nodes if n["node_type"] == "mechanism"]
    if mech_keys and industry_keys:
        for mk in mech_keys:
            edges.append((mk, industry_keys[0], "part_of"))

    # Text-pattern: for each pair of nodes, try to find a typed relation
    rich_text = f"{summary} {edu}"
    for i, ka in enumerate(node_keys):
        for kb in node_keys[i + 1:]:
            la = node_labels[ka]
            lb = node_labels[kb]
            rel = _find_relation_between(rich_text, la, lb)
            if rel:
                edges.append((ka, kb, rel))
            else:
                # Fall back to generic co-occurrence only if both appear in the text
                if la.lower() in rich_text.lower() and lb.lower() in rich_text.lower():
                    edges.append((ka, kb, "related_to"))

    return nodes, edges


# ── Package-level extraction ───────────────────────────────────────────────────

def extract_graph_data(
    package: dict,
) -> tuple[list[dict], list[tuple[str, str, str]]]:
    """
    Extract all nodes and edges from a generated feed package.

    Returns (nodes, edges) where:
      nodes: list of {label, node_type, node_key}
      edges: list of (from_key, to_key, relation)
    """
    core_cards      = package.get("insights", []) or []
    curiosity_cards = package.get("curiosity_insights", []) or []

    all_nodes: list[dict] = []
    all_edges: list[tuple[str, str, str]] = []

    for card in core_cards:
        ns, es = _extract_from_card(card, is_core=True)
        all_nodes.extend(ns)
        all_edges.extend(es)

    for card in curiosity_cards:
        ns, es = _extract_from_card(card, is_core=False)
        all_nodes.extend(ns)
        all_edges.extend(es)

    # Cross-card: nodes seen in multiple cards are strongly related
    key_count: dict[str, int] = defaultdict(int)
    for n in all_nodes:
        key_count[n["node_key"]] += 1
    # Merge cross-card co-occurrences — if node appears >1 time it's a hub candidate
    # (no extra edges needed; weight is handled in upsert via increment)

    return all_nodes, all_edges


# ── DB persistence ────────────────────────────────────────────────────────────

def _db_upsert_node(
    conn,
    project_id: str,
    node_key: str,
    label: str,
    node_type: str,
) -> None:
    now = _now()
    conn.execute(
        """
        INSERT INTO knowledge_graph_nodes (project_id, node_key, label, node_type, weight, first_seen, last_seen)
        VALUES (?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT(project_id, node_key) DO UPDATE SET
            weight   = weight + 1,
            last_seen = excluded.last_seen
        """,
        (project_id, node_key, label, node_type, now, now),
    )


def _db_upsert_edge(
    conn,
    project_id: str,
    from_key: str,
    to_key: str,
    relation: str,
) -> None:
    now = _now()
    conn.execute(
        """
        INSERT INTO knowledge_graph_edges (project_id, from_key, to_key, relation, weight, created_at)
        VALUES (?, ?, ?, ?, 1, ?)
        ON CONFLICT(project_id, from_key, to_key, relation) DO UPDATE SET
            weight = weight + 1
        """,
        (project_id, from_key, to_key, relation, now),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def upsert_from_package(project_id: str, package: dict) -> None:
    """
    Extract graph data from a generated feed package and persist to DB.
    Called automatically after every successful feed generation. Non-fatal.
    """
    try:
        from ..utils.db import get_connection

        nodes, edges = extract_graph_data(package)

        with get_connection() as conn:
            # Only insert nodes whose keys are valid
            for node in nodes:
                k = node["node_key"]
                nt = node["node_type"]
                if k and nt in VALID_NODE_TYPES:
                    _db_upsert_node(conn, project_id, k, node["label"], nt)

            # Only insert edges where both nodes were registered
            node_keys = {n["node_key"] for n in nodes if n["node_type"] in VALID_NODE_TYPES}
            for from_key, to_key, relation in edges:
                if (
                    from_key != to_key
                    and from_key in node_keys
                    and to_key in node_keys
                    and relation in VALID_RELATIONS
                ):
                    _db_upsert_edge(conn, project_id, from_key, to_key, relation)

    except Exception:
        logger.exception("[learning_graph] upsert_from_package failed for %s (non-fatal)", project_id)


def get_graph(project_id: str) -> dict:
    """
    Return the full knowledge graph for a project.

    {
      "nodes": [{"node_key", "label", "node_type", "weight"}, ...],
      "edges": [{"from_key", "to_key", "relation", "weight"}, ...],
    }
    """
    try:
        from ..utils.db import get_connection

        with get_connection() as conn:
            node_rows = conn.execute(
                "SELECT node_key, label, node_type, weight FROM knowledge_graph_nodes WHERE project_id = ? ORDER BY weight DESC",
                (project_id,),
            ).fetchall()
            edge_rows = conn.execute(
                "SELECT from_key, to_key, relation, weight FROM knowledge_graph_edges WHERE project_id = ? ORDER BY weight DESC",
                (project_id,),
            ).fetchall()

        return {
            "nodes": [dict(r) for r in node_rows],
            "edges": [dict(r) for r in edge_rows],
        }
    except Exception:
        logger.exception("[learning_graph] get_graph failed for %s", project_id)
        return {"nodes": [], "edges": []}


def get_neighbors(
    project_id: str,
    node_key: str,
    depth: int = 2,
) -> list[dict]:
    """
    BFS from node_key up to `depth` hops. Returns list of neighbor node dicts
    with an added `distance` and `via_relation` field.
    """
    try:
        from ..utils.db import get_connection

        with get_connection() as conn:
            edge_rows = conn.execute(
                """
                SELECT from_key, to_key, relation, weight
                FROM knowledge_graph_edges
                WHERE project_id = ?
                """,
                (project_id,),
            ).fetchall()

            node_rows = conn.execute(
                "SELECT node_key, label, node_type, weight FROM knowledge_graph_nodes WHERE project_id = ?",
                (project_id,),
            ).fetchall()

        node_map: dict[str, dict] = {r["node_key"]: dict(r) for r in node_rows}

        # Build adjacency: node_key → [(neighbour_key, relation, weight)]
        adj: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
        for e in edge_rows:
            adj[e["from_key"]].append((e["to_key"], e["relation"], e["weight"]))
            # Graph is treated as undirected for neighbour discovery
            adj[e["to_key"]].append((e["from_key"], e["relation"], e["weight"]))

        visited: dict[str, int] = {node_key: 0}
        queue: deque[tuple[str, int, str]] = deque([(node_key, 0, "")])
        results: list[dict] = []

        while queue:
            current, dist, via_rel = queue.popleft()
            if dist >= depth:
                continue
            for neighbour, rel, wt in adj[current]:
                if neighbour not in visited:
                    visited[neighbour] = dist + 1
                    node_info = node_map.get(neighbour, {"node_key": neighbour, "label": neighbour, "node_type": "concept", "weight": 1})
                    results.append({
                        **node_info,
                        "distance": dist + 1,
                        "via_relation": rel,
                    })
                    queue.append((neighbour, dist + 1, rel))

        results.sort(key=lambda x: (x["distance"], -x["weight"]))
        return results

    except Exception:
        logger.exception("[learning_graph] get_neighbors failed for %s / %s", project_id, node_key)
        return []


def get_graph_summary(project_id: str, max_nodes: int = 20) -> str:
    """
    Return a compact graph summary string for prompt injection.
    Empty string if graph is too sparse (< 3 nodes).
    """
    try:
        graph = get_graph(project_id)
        nodes = graph["nodes"]
        edges = graph["edges"]

        if len(nodes) < 3:
            return ""

        # Top nodes by weight (most-seen = most central)
        top_nodes = nodes[:max_nodes]

        # Group by type
        by_type: dict[str, list[str]] = defaultdict(list)
        for n in top_nodes:
            by_type[n["node_type"]].append(n["label"])

        # Build edge chains: find high-weight paths (weight > 1)
        strong_edges = [e for e in edges if e["weight"] > 1]
        # Build a readable "A → B" chain from strong edges
        chains: list[str] = []
        seen_chains: set[tuple[str, str]] = set()
        for e in strong_edges[:10]:
            pair = (e["from_key"], e["to_key"])
            if pair not in seen_chains:
                seen_chains.add(pair)
                # Find labels
                fl = next((n["label"] for n in nodes if n["node_key"] == e["from_key"]), e["from_key"])
                tl = next((n["label"] for n in nodes if n["node_key"] == e["to_key"]), e["to_key"])
                chains.append(f"{fl} —[{e['relation']}]→ {tl}")

        lines: list[str] = []
        lines.append("══════════════════════════════════════")
        lines.append("KNOWLEDGE GRAPH  ← what the user understands and how it connects")
        lines.append("══════════════════════════════════════")
        lines.append(f"Total nodes: {len(nodes)}  |  Total edges: {len(edges)}")

        if by_type.get("industry"):
            lines.append(f"Industries mapped: {', '.join(by_type['industry'][:6])}")
        if by_type.get("concept"):
            lines.append(f"Concepts understood: {', '.join(by_type['concept'][:8])}")
        if by_type.get("mechanism"):
            lines.append(f"Mechanisms learned: {', '.join(by_type['mechanism'][:6])}")
        if by_type.get("company"):
            lines.append(f"Companies tracked: {', '.join(by_type['company'][:6])}")
        if by_type.get("trend"):
            lines.append(f"Trends identified: {', '.join(by_type['trend'][:4])}")

        if chains:
            lines.append("")
            lines.append("Learned relationships (build on these, do not re-explain):")
            for chain in chains[:6]:
                lines.append(f"  • {chain}")

        return "\n".join(lines)

    except Exception:
        logger.exception("[learning_graph] get_graph_summary failed for %s", project_id)
        return ""
