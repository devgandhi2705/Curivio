"""
Learning Memory Service — per-project semantic coverage tracking.

Prevents Day 1, Day 1.1, Day 1.2 from repeating the same mechanisms,
framings, examples, and angles by maintaining an evolving LearningMemoryState
per project.  The state is persisted in the `project_learning_memory` table
and updated after every successful feed generation.

Coverage dimensions tracked
---------------------------
  covered_concepts    : category/concept labels from all generated cards
  covered_mechanisms  : title-level mechanism descriptions from educational cards
  covered_industries  : industries identified in generated content
  covered_examples    : named proper-noun examples (companies, events, experiments)
  covered_geographies : countries / regions mentioned
  covered_narratives  : narrative frames used (from card.narrative_frame)
  curiosity_angles    : curiosity card category strings used
  progression_stage   : current depth stage (foundation → synthesis)
  days_at_stage       : packages generated at the current stage

Progression stages (ordered)
-----------------------------
  foundation     → What/why framing, definitions, basic mechanics
  mechanisms     → Causal chains, how things actually work, feedback loops
  dependencies   → Supply chain, prerequisites, fragility, hidden connections
  optimization   → Efficiency, competitive dynamics, benchmarks, trade-offs
  geopolitical   → Political economy, regulatory pressure, national strategies
  disruption     → Emerging tech, startup threats, paradigm shifts
  synthesis      → Cross-domain synthesis, future scenarios, strategic arc

Similarity gate
---------------
  _is_novel(candidate, existing, threshold=0.45)
  Bigram-Jaccard at 0.45 ≈ cosine-similarity 0.82 for short domain phrases.
  Used by filter_novel_topics() to suppress over-similar next-topic suggestions.

Public API
----------
  get_memory(project_id) -> dict
  update_from_package(project_id, package) -> None
  build_memory_prompt_section(memory: dict) -> str
  filter_novel_topics(candidates, memory, max_results=6) -> list[str]
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_DATETIME_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _now() -> str:
    return datetime.now(timezone.utc).strftime(_DATETIME_FMT)


# ── Progression stage definitions ─────────────────────────────────────────────

_STAGES: list[str] = [
    "foundation",
    "mechanisms",
    "dependencies",
    "optimization",
    "geopolitical",
    "disruption",
    "synthesis",
]

_DAYS_PER_STAGE = 3  # packages before advancing to the next stage

_STAGE_DIRECTIVES: dict[str, str] = {
    "foundation": (
        "Introduce core concepts, key players, and basic mechanics. "
        "Assume an intelligent newcomer. Build the mental map of this domain."
    ),
    "mechanisms": (
        "Go below the surface. Explain HOW things work — causal chains, process internals, "
        "system logic, feedback loops. The user now has the what; give them the how."
    ),
    "dependencies": (
        "Map what depends on what. Highlight supply chains, upstream/downstream relationships, "
        "fragile dependencies, hidden prerequisites, and structural vulnerabilities."
    ),
    "optimization": (
        "Explore efficiency, performance benchmarks, competitive dynamics, best practices, "
        "and the trade-off space where practitioners make hard choices."
    ),
    "geopolitical": (
        "Examine political economy, regulatory architecture, national industrial strategies, "
        "trade policy forces, and geopolitical constraints shaping the domain."
    ),
    "disruption": (
        "Track emerging technologies, startup challengers, paradigm shifts, and structural "
        "threats to incumbents. What changes first when the current model breaks?"
    ),
    "synthesis": (
        "Cross-domain synthesis, future scenarios, second-order effects, strategic implications. "
        "Connect this domain to adjacent fields. What's the 10-year arc of this space?"
    ),
}

_STAGE_TODAY_MANDATE: dict[str, list[str]] = {
    "foundation": [
        "Introduce 2–3 new foundational concepts NOT in the covered list above.",
        "Focus on 'what' and 'why' — the mental model building block.",
    ],
    "mechanisms": [
        "Go deeper on mechanisms — explain HOW, not just WHAT.",
        "Each card must expose a causal chain, feedback loop, or process logic.",
    ],
    "dependencies": [
        "Focus on dependencies: what breaks if X fails? What does Y depend on?",
        "Surface supply chain fragility, upstream risks, hidden prerequisites.",
    ],
    "optimization": [
        "Explore efficiency, benchmarks, competitive dynamics, best practices.",
        "Where are practitioners making hard tradeoffs in this domain?",
    ],
    "geopolitical": [
        "Frame content through political economy, regulation, national strategy.",
        "What policy forces are shaping this domain? Who wins geopolitically?",
    ],
    "disruption": [
        "Focus on what's being disrupted and by what. What changes first?",
        "Emerging tech, startup challengers, paradigm shifts.",
    ],
    "synthesis": [
        "Cross-domain synthesis, future scenarios, second-order effects.",
        "Connect this domain to adjacent fields. What's the 10-year arc?",
    ],
}


# ── Coverage extraction: patterns ─────────────────────────────────────────────

_GEOGRAPHY_WORDS: frozenset[str] = frozenset({
    "india", "china", "usa", "us", "united states", "europe", "eu",
    "japan", "germany", "uk", "britain", "brazil", "southeast asia",
    "south korea", "taiwan", "israel", "singapore", "australia",
    "canada", "russia", "africa", "latin america", "middle east",
    "asean", "brics", "g7", "domestic", "global", "international",
})

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

# ── Title pattern detection ───────────────────────────────────────────────────

_TITLE_PATTERN_SIGNALS: dict[str, list[str]] = {
    "myth_busting":             ["myth", "wrong", "misconception", "truth about", "not what", "actually", "lied", "isn't"],
    "contradiction":            ["but ", "yet ", "despite", "however", "paradox", "ironic", "while ", "even as", "and yet"],
    "hidden_dependency":        ["hidden", "secret", "behind", "invisible", "quiet", "silent", "beneath", "under the"],
    "economic_leverage":        ["billion", "revenue", "profit", "cost of", "price of", "dollar", "margin", "leverage", "wealth"],
    "historical_comparison":    ["history of", "decade", "how it began", "before ", "after ", "years ago", "origin", "invented"],
    "geopolitical_tension":     ["china", " us ", "india", "policy", "sanction", "tariff", "trade war", "geopolit", "alliance", "sovereignty"],
    "operational_failure":      ["failure", "collapse", "crisis", "flaw", "mistake", "risk", "broke", "weakness", "danger", "why it failed"],
    "strategic_moat":           ["advantage", "moat", "dominance", "lead", "ahead", "win", "edge", "monopoly", "barrier to"],
    "invisible_infrastructure": ["infrastructure", "network", "supply chain", "platform", "wiring", "rewiring", "quietly", "stack"],
}

_TITLE_PATTERN_ORDER = list(_TITLE_PATTERN_SIGNALS.keys())


def _detect_title_pattern(title: str) -> str:
    """Classify a title into one of 9 style categories, or 'general'."""
    title_lower = title.lower()
    for pattern, signals in _TITLE_PATTERN_SIGNALS.items():
        if any(sig in title_lower for sig in signals):
            return pattern
    return "general"


def _extract_opening_hook(summary: str) -> str:
    """Return the first 10 words of a summary as a normalised hook fingerprint."""
    if not summary:
        return ""
    words = summary.split()[:10]
    return " ".join(words).lower().strip(".,;:\"'")


_PROPER_NOUN_RE = re.compile(r'\b([A-Z][a-z]{1,}(?:[\s\-][A-Z][a-z]{1,}){1,3})\b')

_COMMON_STARTERS: frozenset[str] = frozenset({
    "The", "This", "That", "These", "Those", "When", "What", "Where", "Why", "How",
    "While", "As", "If", "Although", "Since", "Because", "Most", "Many", "Some",
    "Few", "Their", "Its", "Our", "Your", "His", "Her", "With", "For", "And", "But",
    "Or", "Not", "Even", "Still", "Also", "Only", "Just", "Both", "Each", "All",
    "More", "Less", "New", "Old", "First", "Last", "Next", "After", "Before",
    "Rather", "Instead", "However", "Therefore", "Thus", "Hence", "Yet", "Despite",
    "During", "Under", "Over", "Between", "Through", "Within", "Without", "Among",
    "Around", "Against", "Beyond", "Across", "Into", "Onto", "Upon", "Along",
})


# ── Similarity helpers ────────────────────────────────────────────────────────

def _normalise_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _bigrams(text: str) -> frozenset[str]:
    words = text.split()
    if len(words) < 2:
        return frozenset(words)
    return frozenset(f"{words[i]} {words[i + 1]}" for i in range(len(words) - 1))


def _jaccard(a: str, b: str) -> float:
    ba = _bigrams(_normalise_text(a))
    bb = _bigrams(_normalise_text(b))
    if not ba and not bb:
        return 1.0 if a.lower().strip() == b.lower().strip() else 0.0
    if not ba or not bb:
        return 0.0
    intersection = len(ba & bb)
    union = len(ba | bb)
    return intersection / union if union else 0.0


def _is_novel(candidate: str, existing: list[str], threshold: float = 0.45) -> bool:
    """
    Return True if candidate is sufficiently unlike every item in existing.
    Bigram-Jaccard 0.45 ≈ sentence-embedding cosine 0.82 for short domain phrases.
    """
    norm = _normalise_text(candidate)
    if not norm:
        return True
    for ex in existing:
        if _jaccard(candidate, ex) >= threshold:
            return False
    return True


# ── Coverage extraction helpers ───────────────────────────────────────────────

def _extract_industries(text: str) -> list[str]:
    text_lower = text.lower()
    return [label for label, keywords in _INDUSTRY_MAP.items() if any(kw in text_lower for kw in keywords)]


def _extract_geographies(text: str) -> list[str]:
    text_lower = text.lower()
    return [g.title() for g in _GEOGRAPHY_WORDS if g in text_lower]


def _extract_proper_nouns(text: str) -> list[str]:
    matches = _PROPER_NOUN_RE.findall(text)
    return [m for m in matches if m.split()[0] not in _COMMON_STARTERS]


def _extract_coverage(package: dict) -> dict:
    """
    Extract all coverage dimensions from a generated package dict.

    Returns {concepts, mechanisms, industries, examples, geographies,
             narratives, curiosity_angles}.
    """
    core_cards      = package.get("insights", []) or []
    curiosity_cards = package.get("curiosity_insights", []) or []
    all_cards       = core_cards + curiosity_cards

    concepts:         list[str] = []
    mechanisms:       list[str] = []
    industries:       list[str] = []
    examples:         list[str] = []
    geographies:      list[str] = []
    narratives:       list[str] = []
    curiosity_angles: list[str] = []

    core_ids = {id(c) for c in core_cards}

    for card in all_cards:
        category = (card.get("category") or "").strip()
        if category:
            concepts.append(category)

        title   = (card.get("title") or "").strip()
        summary = (card.get("summary") or "").strip()
        edu     = (card.get("educational_explanation") or "").strip()
        full_text = f"{title} {summary} {edu}"

        industries.extend(_extract_industries(full_text))
        geographies.extend(_extract_geographies(full_text))

        # Examples: proper nouns from title + first sentence of summary
        first_sentence = summary.split(".")[0] if summary else ""
        examples.extend(_extract_proper_nouns(f"{title} {first_sentence}"))

        if id(card) in core_ids:
            frame = (card.get("narrative_frame") or "").strip().upper()
            if frame:
                narratives.append(frame)
            # Mechanism label: educational card titles are already mechanism-level
            if card.get("content_type") == "educational" and title:
                mechanisms.append(title)

        if id(card) not in core_ids and category:
            curiosity_angles.append(category)

    # Title patterns and opening hooks (all cards, for diversity tracking)
    title_patterns: list[str] = []
    opening_hooks:  list[str] = []
    for card in all_cards:
        t = (card.get("title") or "").strip()
        if t:
            title_patterns.append(_detect_title_pattern(t))
        s = (card.get("summary") or "").strip()
        hook = _extract_opening_hook(s)
        if hook:
            opening_hooks.append(hook)

    return {
        "concepts":          concepts,
        "mechanisms":        mechanisms,
        "industries":        industries,
        "examples":          examples,
        "geographies":       geographies,
        "narratives":        narratives,
        "curiosity_angles":  curiosity_angles,
        "title_patterns":    title_patterns,
        "opening_hooks":     opening_hooks,
    }


# ── Stage advancement ─────────────────────────────────────────────────────────

def _next_stage(current_stage: str, days_at_stage: int) -> tuple[str, int]:
    """Return (new_stage, new_days_at_stage) after one more package."""
    idx = _STAGES.index(current_stage) if current_stage in _STAGES else 0
    new_days = days_at_stage + 1
    if new_days >= _DAYS_PER_STAGE and idx < len(_STAGES) - 1:
        return _STAGES[idx + 1], 0
    return current_stage, new_days


# ── List deduplication ────────────────────────────────────────────────────────

def _dedup_append(existing: list[str], new_items: list[str], max_len: int = 200) -> list[str]:
    """Append new_items to existing without case-insensitive duplicates. Cap at max_len."""
    seen = {s.lower().strip() for s in existing}
    result = list(existing)
    for item in new_items:
        norm = item.lower().strip()
        if norm and norm not in seen:
            result.append(item)
            seen.add(norm)
    return result[-max_len:]


# ── DB persistence ────────────────────────────────────────────────────────────

_LIST_FIELDS = (
    "covered_concepts", "covered_mechanisms", "covered_industries",
    "covered_examples", "covered_geographies", "covered_narratives",
    "curiosity_angles", "title_patterns_used", "opening_hooks_used",
)


def _empty_state() -> dict:
    return {
        "covered_concepts":    [],
        "covered_mechanisms":  [],
        "covered_industries":  [],
        "covered_examples":    [],
        "covered_geographies": [],
        "covered_narratives":  [],
        "curiosity_angles":    [],
        "title_patterns_used": [],
        "opening_hooks_used":  [],
        "progression_stage":   "foundation",
        "days_at_stage":       0,
    }


def _parse_row(d: dict) -> dict:
    for field in _LIST_FIELDS:
        raw = d.get(field, "[]")
        if isinstance(raw, str):
            try:
                d[field] = json.loads(raw)
            except Exception:
                d[field] = []
    d.setdefault("progression_stage", "foundation")
    d.setdefault("days_at_stage", 0)
    return d


def _db_load(project_id: str) -> dict:
    from ..utils.db import get_connection
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM project_learning_memory WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    if row is None:
        return _empty_state()
    return _parse_row(dict(row))


def _db_save(project_id: str, memory: dict) -> None:
    from ..utils.db import get_connection, build_set_clause
    now = _now()

    serialised: dict = {}
    for field in _LIST_FIELDS:
        val = memory.get(field, [])
        serialised[field] = json.dumps(val if isinstance(val, list) else [])
    serialised["progression_stage"] = memory.get("progression_stage", "foundation")
    serialised["days_at_stage"]     = memory.get("days_at_stage", 0)

    with get_connection() as conn:
        exists = conn.execute(
            "SELECT 1 FROM project_learning_memory WHERE project_id = ?",
            (project_id,),
        ).fetchone()

        if exists:
            set_clause = build_set_clause(serialised)
            conn.execute(
                f"UPDATE project_learning_memory SET {set_clause}, updated_at = ? WHERE project_id = ?",
                [*serialised.values(), now, project_id],
            )
        else:
            serialised["project_id"] = project_id
            serialised["updated_at"] = now
            cols         = ", ".join(serialised.keys())
            placeholders = ", ".join("?" * len(serialised))
            conn.execute(
                f"INSERT INTO project_learning_memory ({cols}) VALUES ({placeholders})",
                list(serialised.values()),
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def get_memory(project_id: str) -> dict:
    """Load (or return empty) learning memory state for a project."""
    try:
        return _db_load(project_id)
    except Exception:
        logger.exception("[learning_memory] get_memory failed for %s", project_id)
        return _empty_state()


def update_from_package(project_id: str, package: dict) -> None:
    """
    Extract coverage from a successfully-generated package and persist to DB.
    Called automatically after every successful feed generation.  Non-fatal.
    """
    try:
        memory   = _db_load(project_id)
        coverage = _extract_coverage(package)

        memory["covered_concepts"]    = _dedup_append(memory["covered_concepts"],    coverage["concepts"],         max_len=200)
        memory["covered_mechanisms"]  = _dedup_append(memory["covered_mechanisms"],  coverage["mechanisms"],       max_len=100)
        memory["covered_industries"]  = _dedup_append(memory["covered_industries"],  coverage["industries"],       max_len=50)
        memory["covered_examples"]    = _dedup_append(memory["covered_examples"],    coverage["examples"],         max_len=150)
        memory["covered_geographies"] = _dedup_append(memory["covered_geographies"], coverage["geographies"],      max_len=50)
        memory["covered_narratives"]  = (memory["covered_narratives"] + coverage["narratives"])[-60:]
        memory["curiosity_angles"]    = _dedup_append(memory["curiosity_angles"],    coverage["curiosity_angles"], max_len=50)
        # Title pattern + opening hook tracking (keep last 80 for frequency analysis)
        memory["title_patterns_used"] = (memory.get("title_patterns_used", []) + coverage["title_patterns"])[-80:]
        memory["opening_hooks_used"]  = (memory.get("opening_hooks_used",  []) + coverage["opening_hooks"])[-60:]

        new_stage, new_days = _next_stage(
            memory.get("progression_stage", "foundation"),
            memory.get("days_at_stage", 0),
        )
        memory["progression_stage"] = new_stage
        memory["days_at_stage"]     = new_days

        _db_save(project_id, memory)

        # Phase 4.1: update knowledge graph
        try:
            from .learning_graph import upsert_from_package as _graph_upsert
            _graph_upsert(project_id, package)
        except Exception:
            logger.exception("[learning_memory] graph upsert failed for %s (non-fatal)", project_id)

    except Exception:
        logger.exception("[learning_memory] update_from_package failed for %s (non-fatal)", project_id)


def filter_novel_topics(
    candidates: list[str],
    memory: dict,
    max_results: int = 6,
) -> list[str]:
    """
    Filter candidate next topics to those sufficiently unlike already-covered
    concepts and mechanisms.  Always returns at least 2 items (falls back to
    unfiltered list) to prevent the curriculum from going empty.
    """
    if not candidates:
        return []
    covered = memory.get("covered_concepts", []) + memory.get("covered_mechanisms", [])
    novel   = [c for c in candidates if _is_novel(c, covered)]
    # Guarantee floor: if novelty filter is too aggressive, use original list
    if len(novel) < 2:
        novel = candidates
    return novel[:max_results]


def build_memory_prompt_section(memory: dict) -> str:
    """
    Build the PROGRESSION STAGE & COVERAGE MEMORY section injected into the
    feed generation prompt.  Returns "" when memory is effectively empty
    (first day, nothing covered yet).
    """
    stage   = memory.get("progression_stage", "foundation")
    concepts    = memory.get("covered_concepts",    [])
    mechanisms  = memory.get("covered_mechanisms",  [])
    industries  = memory.get("covered_industries",  [])
    examples    = memory.get("covered_examples",    [])
    geographies = memory.get("covered_geographies", [])
    narratives  = memory.get("covered_narratives",  [])
    curiosity_angles = memory.get("curiosity_angles", [])

    # Nothing meaningful yet — skip section
    if not concepts and not mechanisms:
        return ""

    lines: list[str] = []
    lines.append("══════════════════════════════════════")
    lines.append("PROGRESSION STAGE & COVERAGE MEMORY  ← DO NOT REPEAT WHAT IS LISTED HERE")
    lines.append("══════════════════════════════════════")
    lines.append(f"Current stage: {stage.upper()}")
    directive = _STAGE_DIRECTIVES.get(stage, "")
    if directive:
        lines.append(f"Directive: {directive}")

    # Covered concepts — show most recent 15
    if concepts:
        lines.append("")
        lines.append("Concepts already covered (reinforce with depth, NEVER re-explain at same level):")
        for c in concepts[-15:]:
            lines.append(f"  • {c}")

    # Mechanisms — show most recent 8
    if mechanisms:
        lines.append("")
        lines.append("Mechanisms already explained (do not repeat this causal logic):")
        for m in mechanisms[-8:]:
            lines.append(f"  • {m}")

    # Examples — deduplicated, most recent 8
    if examples:
        seen: set[str] = set()
        deduped: list[str] = []
        for e in reversed(examples):
            key = e.lower().strip()
            if key and key not in seen and len(key) > 3:
                seen.add(key)
                deduped.append(e)
        deduped = list(reversed(deduped))
        if deduped:
            lines.append("")
            lines.append("Examples already cited (use a meaningfully fresh angle or avoid):")
            for e in deduped[-8:]:
                lines.append(f"  • {e}")

    # Narrative frame overuse
    if narratives:
        frame_counts = Counter(narratives)
        overused = [f for f, c in frame_counts.most_common() if c >= 2]
        if overused:
            lines.append("")
            lines.append(f"Narrative frames over-used (diversify — avoid leading with these): {', '.join(overused)}")

    # Geography concentration
    if geographies:
        geo_counts = Counter(geographies)
        top_geos   = [g for g, _ in geo_counts.most_common(3)]
        lines.append("")
        lines.append(f"Geographies over-covered (broaden perspective beyond): {', '.join(top_geos)}")

    # Industry concentration
    if industries:
        ind_counts  = Counter(industries)
        top_inds    = [i for i, _ in ind_counts.most_common(2)]
        lines.append("")
        lines.append(f"Industry angles over-covered (introduce cross-domain perspective): {', '.join(top_inds)}")

    # Curiosity angles used
    if curiosity_angles:
        lines.append("")
        recent_angles = curiosity_angles[-5:]
        lines.append(f"Curiosity angles already used (introduce fresh types): {', '.join(recent_angles)}")

    # Title pattern overuse — show which structural types have been used too much
    title_patterns = memory.get("title_patterns_used", [])
    if title_patterns:
        pattern_counts = Counter(title_patterns)
        overused_patterns = [p for p, c in pattern_counts.most_common() if c >= 3 and p != "general"]
        if overused_patterns:
            lines.append("")
            lines.append(f"Title pattern types over-used (diversify structure away from these): {', '.join(overused_patterns)}")
            # Show which categories are underused — rotate toward these
            all_non_general = set(_TITLE_PATTERN_ORDER)
            used_set = set(overused_patterns) | {p for p in pattern_counts if pattern_counts[p] >= 2}
            fresh_patterns = [p for p in _TITLE_PATTERN_ORDER if p not in used_set]
            if fresh_patterns:
                lines.append(f"Fresh title patterns to use instead: {', '.join(fresh_patterns[:4])}")

    # Opening hook diversity signal
    opening_hooks = memory.get("opening_hooks_used", [])
    if len(opening_hooks) >= 4:
        # Detect if the last 4 hooks start the same way
        hook_starts = [h.split()[:3] for h in opening_hooks[-6:] if h]
        starter_phrases = [" ".join(w) for w in hook_starts if w]
        start_counts = Counter(starter_phrases)
        repeated_starts = [p for p, c in start_counts.most_common() if c >= 2]
        if repeated_starts:
            lines.append("")
            lines.append(f"Opening hooks that are being over-repeated (vary how summaries begin): \"{repeated_starts[0]}...\"")

    # Stage-specific mandate
    mandate_items = _STAGE_TODAY_MANDATE.get(stage, [])
    if mandate_items:
        lines.append("")
        lines.append("TODAY'S MANDATE (from progression stage):")
        for item in mandate_items:
            lines.append(f"  • {item}")

    return "\n".join(lines)
