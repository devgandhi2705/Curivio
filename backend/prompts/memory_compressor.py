"""
MemoryCompressor — prevents per-project learning memory from growing forever.

Phase 3.4 deliverable.

The Problem
-----------
`learning_memory_service.build_memory_prompt_section()` injects the last 15
concepts, last 8 mechanisms, etc. from a raw accumulated list.  At Day 200 of
a project, the raw memory holds 200 concepts and 100 mechanisms — almost all
invisible to the prompt — while the section still costs ~400 tokens regardless
of how many *useful* signals it surfaces.

The raw memory never *shrinks*; it grows linearly until the per-list caps hit.
The prompt section grows until those caps hit, then plateaus at a fixed high
cost even when most of the injected items are redundant.

The Solution
-----------
Compress raw accumulated memory into five *semantic* categories — the signal
without the noise — and represent that at four progressive levels:

  Level 0  FULL         Full prompt section (delegates to existing service).
                        ~300–600 tokens for mature projects.

  Level 1  STRUCTURED   The five categories in a clean, labeled layout.
                        ~120–200 tokens.

  Level 2  GRAPH        One line per category with count + top 3–4 items.
                        ~40–60 tokens.

  Level 3  SUMMARY      Single sentence: stage + top 3 concepts.
                        ~15–20 tokens.

Five semantic categories
------------------------
  Concepts Learned   Most representative covered concepts — diverse selection
                     from covered_concepts, not just the most recent 15.
  Mechanisms Covered  Causal explanations already delivered — from
                     covered_mechanisms.
  Open Questions     Stage-derived questions the learner should be asking
                     next, based on progression stage + recent curiosity threads.
  Curiosity Threads  Recent unexplained angles from curiosity_angles — the
                     intellectual rabbit holes still open.
  Key Examples       Most-cited named entities from covered_examples.

Budget integration
------------------
    compressor = MemoryCompressor()
    text, meta = compressor.format_within_budget(memory_dict, budget_tokens=1_200)

Usage
-----
    from backend.prompts.memory_compressor import MemoryCompressor

    memory    = get_memory(project_id)                # from learning_memory_service
    comp_mem  = MemoryCompressor().compress(memory)
    text      = comp_mem.at_level(2)                  # Level 2 for moderate budget
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field


# ── Level constants ────────────────────────────────────────────────────────────

MEM_LEVEL_FULL       = 0   # full build_memory_prompt_section() output
MEM_LEVEL_STRUCTURED = 1   # five-category structured layout
MEM_LEVEL_GRAPH      = 2   # knowledge-graph summary (one line per category)
MEM_LEVEL_SUMMARY    = 3   # single-sentence progression summary

MEM_LEVEL_NAMES: dict[int, str] = {
    MEM_LEVEL_FULL:       "FULL",
    MEM_LEVEL_STRUCTURED: "STRUCTURED",
    MEM_LEVEL_GRAPH:      "GRAPH",
    MEM_LEVEL_SUMMARY:    "SUMMARY",
}

MEM_LEVEL_DESCRIPTIONS: dict[int, str] = {
    MEM_LEVEL_FULL:       "full prompt section, ~400 tokens for mature projects",
    MEM_LEVEL_STRUCTURED: "five-category layout, ~120–200 tokens",
    MEM_LEVEL_GRAPH:      "one-line-per-category knowledge graph, ~40–60 tokens",
    MEM_LEVEL_SUMMARY:    "single-sentence progression summary, ~15–20 tokens",
}

# Selection sizes per level
_LEVEL1_CONCEPTS    = 6    # concepts shown in Level 1
_LEVEL1_MECHANISMS  = 4    # mechanisms shown in Level 1
_LEVEL1_EXAMPLES    = 5    # examples shown in Level 1
_LEVEL1_QUESTIONS   = 3    # open questions shown in Level 1
_LEVEL1_THREADS     = 4    # curiosity threads shown in Level 1

_LEVEL2_CONCEPTS    = 4    # concepts shown in Level 2
_LEVEL2_MECHANISMS  = 3    # mechanisms shown in Level 2
_LEVEL2_EXAMPLES    = 3    # examples shown in Level 2

# Stage-specific open question templates — one per progression stage
_STAGE_QUESTIONS: dict[str, list[str]] = {
    "foundation": [
        "What are the core mechanics that drive {concept}?",
        "What does a newcomer most often misunderstand about this domain?",
        "Which foundational concept unlocks the most downstream understanding?",
    ],
    "mechanisms": [
        "What causal chain explains why {concept} behaves the way it does?",
        "Which feedback loop is least visible but most consequential here?",
        "Where does the mechanism break down under stress?",
    ],
    "dependencies": [
        "What does {concept} depend on that could become a single point of failure?",
        "Which upstream supplier or resource is most fragile?",
        "What breaks first when this system is under pressure?",
    ],
    "optimization": [
        "What trade-off defines the efficiency frontier in {concept}?",
        "Where are practitioners making the hardest choices?",
        "What benchmark matters most, and why is it contested?",
    ],
    "geopolitical": [
        "Which national strategy most shapes the trajectory of {concept}?",
        "What regulatory asymmetry creates a hidden competitive advantage here?",
        "How would a change in trade policy alter the power dynamics?",
    ],
    "disruption": [
        "What emerging technology could make {concept} obsolete in 5 years?",
        "Which incumbent is most exposed and why?",
        "What startup assumption, if correct, rewrites this domain?",
    ],
    "synthesis": [
        "How does {concept} connect to an adjacent field most people overlook?",
        "What second-order effect will surprise analysts in 10 years?",
        "What is the one insight that ties the entire domain together?",
    ],
}


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class CompressedMemory:
    """
    A project's learning memory compressed into five semantic categories
    with pre-built representations at all four levels.
    """

    # Structured categories
    progression_stage:  str
    concepts_learned:   list[str]   # representative covered concepts
    mechanisms_covered: list[str]   # representative covered mechanisms
    open_questions:     list[str]   # stage + curiosity-derived questions
    curiosity_threads:  list[str]   # recent unexplored curiosity angles
    key_examples:       list[str]   # most-cited named entities

    # Pre-built level strings
    level0: str = ""
    level1: str = ""
    level2: str = ""
    level3: str = ""

    original_tokens: int = 0        # tokens of the full Level 0 section

    def at_level(self, level: int) -> str:
        """Return the memory representation at the given compression level."""
        if level <= MEM_LEVEL_FULL:        return self.level0
        if level == MEM_LEVEL_STRUCTURED:  return self.level1
        if level == MEM_LEVEL_GRAPH:       return self.level2
        return self.level3

    def tokens_at_level(self, level: int) -> int:
        return max(1, len(self.at_level(level)) // 4)

    @property
    def compression_ratio(self) -> float:
        """Token reduction from Level 0 → Level 2."""
        if not self.original_tokens:
            return 0.0
        return 1.0 - (self.tokens_at_level(MEM_LEVEL_GRAPH) / self.original_tokens)


@dataclass
class MemoryCompressionResult:
    """Metadata about a format_within_budget() call."""

    level:              int
    level_name:         str
    total_tokens:       int
    token_budget:       int
    fits:               bool
    level0_tokens:      int
    compression_ratio:  float

    def summary(self) -> str:
        saved = self.level0_tokens - self.total_tokens
        pct   = (saved / self.level0_tokens * 100) if self.level0_tokens else 0.0
        status = "OK" if self.fits else "OVER BUDGET"
        return (
            f"Level {self.level} ({self.level_name}) — "
            f"{self.total_tokens:,} / {self.token_budget:,} tokens — "
            f"saved {saved:,} tok ({pct:.0f}% vs full) — {status}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Core compressor
# ═══════════════════════════════════════════════════════════════════════════════

class MemoryCompressor:
    """
    Compresses raw per-project learning memory into semantic categories at
    four progressive levels.

    All methods are stateless (no DB calls).  Pass the memory dict returned
    by ``learning_memory_service.get_memory(project_id)`` directly.
    """

    def compress(self, memory: dict) -> CompressedMemory:
        """
        Compress a raw memory dict into a CompressedMemory.

        Accepts the shape produced by ``learning_memory_service.get_memory()``.
        """
        stage        = (memory.get("progression_stage") or "foundation").lower()
        concepts_raw = memory.get("covered_concepts",    []) or []
        mechs_raw    = memory.get("covered_mechanisms",  []) or []
        examples_raw = memory.get("covered_examples",    []) or []
        curiosity_raw= memory.get("curiosity_angles",    []) or []
        narratives   = memory.get("covered_narratives",  []) or []
        industries   = memory.get("covered_industries",  []) or []
        geographies  = memory.get("covered_geographies", []) or []

        # ── Extract five semantic categories ─────────────────────────────────

        concepts   = _select_representative(concepts_raw, _LEVEL1_CONCEPTS)
        mechanisms = _select_representative(mechs_raw,    _LEVEL1_MECHANISMS)
        examples   = _select_top_by_frequency(examples_raw, _LEVEL1_EXAMPLES)

        # Curiosity threads: recent unique angles
        threads = _dedup_recent(curiosity_raw, _LEVEL1_THREADS)

        # Open questions: derived from stage + top concept + curiosity threads
        top_concept = concepts[0] if concepts else (stage + " fundamentals")
        questions   = _derive_open_questions(stage, top_concept, threads)

        # ── Build level strings ───────────────────────────────────────────────

        level0 = _build_level0(memory)
        level1 = _build_level1(stage, concepts, mechanisms, questions, threads, examples)
        level2 = _build_level2(
            stage, concepts, mechanisms, examples, threads,
            len(concepts_raw), len(mechs_raw), len(examples_raw),
            industries, geographies,
        )
        level3 = _build_level3(stage, concepts, len(concepts_raw), len(mechs_raw))

        # Enforce monotonic invariant
        if len(level1) > len(level0):
            level1 = level0
        if len(level2) > len(level1):
            level2 = level1

        orig_tokens = max(1, len(level0) // 4)

        return CompressedMemory(
            progression_stage  = stage,
            concepts_learned   = concepts,
            mechanisms_covered = mechanisms,
            open_questions     = questions,
            curiosity_threads  = threads,
            key_examples       = examples,
            level0             = level0,
            level1             = level1,
            level2             = level2,
            level3             = level3,
            original_tokens    = orig_tokens,
        )

    # ── Batch convenience ─────────────────────────────────────────────────────

    def format_at_level(self, memory: dict, level: int) -> str:
        """Compress and format in one call."""
        return self.compress(memory).at_level(level)

    # ── Budget-aware auto-selection ───────────────────────────────────────────

    def format_within_budget(
        self,
        memory: dict,
        budget_tokens: int,
    ) -> tuple[str, MemoryCompressionResult]:
        """
        Auto-select the lowest compression level that fits within budget_tokens.

        Returns
        -------
        (formatted_text, MemoryCompressionResult)
        """
        cm = self.compress(memory)

        for level in (MEM_LEVEL_FULL, MEM_LEVEL_STRUCTURED, MEM_LEVEL_GRAPH, MEM_LEVEL_SUMMARY):
            text   = cm.at_level(level)
            tokens = max(1, len(text) // 4)
            if tokens <= budget_tokens:
                ratio = 1.0 - (tokens / cm.original_tokens) if cm.original_tokens else 0.0
                return text, MemoryCompressionResult(
                    level             = level,
                    level_name        = MEM_LEVEL_NAMES[level],
                    total_tokens      = tokens,
                    token_budget      = budget_tokens,
                    fits              = True,
                    level0_tokens     = cm.original_tokens,
                    compression_ratio = ratio,
                )

        # Even Level 3 doesn't fit — return it anyway
        text   = cm.at_level(MEM_LEVEL_SUMMARY)
        tokens = max(1, len(text) // 4)
        ratio  = 1.0 - (tokens / cm.original_tokens) if cm.original_tokens else 0.0
        return text, MemoryCompressionResult(
            level             = MEM_LEVEL_SUMMARY,
            level_name        = MEM_LEVEL_NAMES[MEM_LEVEL_SUMMARY],
            total_tokens      = tokens,
            token_budget      = budget_tokens,
            fits              = False,
            level0_tokens     = cm.original_tokens,
            compression_ratio = ratio,
        )

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def compression_report(self, memory: dict) -> str:
        """
        Return a formatted comparison of token counts across all four levels.

        Example::

            MemoryCompressor — mechanisms stage — 47 concepts, 18 mechanisms
            Level 0  FULL         412 tokens  (      baseline)
            Level 1  STRUCTURED   148 tokens  ( 64% reduction)
            Level 2  GRAPH         48 tokens  ( 88% reduction)
            Level 3  SUMMARY       17 tokens  ( 96% reduction)
        """
        cm = self.compress(memory)
        n_con = len(memory.get("covered_concepts",   []) or [])
        n_mec = len(memory.get("covered_mechanisms", []) or [])
        base  = cm.original_tokens

        lines = [
            f"MemoryCompressor — {cm.progression_stage} stage "
            f"— {n_con} concepts, {n_mec} mechanisms"
        ]
        for level in (MEM_LEVEL_FULL, MEM_LEVEL_STRUCTURED, MEM_LEVEL_GRAPH, MEM_LEVEL_SUMMARY):
            tok    = cm.tokens_at_level(level)
            pct    = (1.0 - tok / base) * 100 if base else 0.0
            detail = "baseline" if level == MEM_LEVEL_FULL else f"{pct:.0f}% reduction"
            lines.append(
                f"  Level {level}  {MEM_LEVEL_NAMES[level]:<12s}"
                f" {tok:>6,} tokens  ({detail:>14})"
            )
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Category extraction helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _normalise(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _bigrams(text: str) -> frozenset[str]:
    words = _normalise(text).split()
    if len(words) < 2:
        return frozenset(words)
    return frozenset(f"{words[i]} {words[i+1]}" for i in range(len(words) - 1))


def _jaccard(a: str, b: str) -> float:
    ba, bb = _bigrams(a), _bigrams(b)
    if not ba and not bb:
        return 1.0 if _normalise(a) == _normalise(b) else 0.0
    if not ba or not bb:
        return 0.0
    return len(ba & bb) / len(ba | bb)


def _select_representative(items: list[str], n: int) -> list[str]:
    """
    Pick N maximally diverse items from a list using greedy bigram-Jaccard.

    Starts with the most recent item, then repeatedly picks the candidate
    LEAST similar to any already selected item.  This surfaces the broadest
    coverage of what has been learned rather than just the last N items.
    """
    items = [s for s in items if s and s.strip()]
    if len(items) <= n:
        return list(items)

    selected   = [items[-1]]  # seed with most recent
    candidates = list(items[:-1])

    while len(selected) < n and candidates:
        best_cand  = None
        best_score = float("inf")
        for c in candidates:
            sim = max(_jaccard(c, s) for s in selected)
            if sim < best_score:
                best_score = sim
                best_cand  = c
        if best_cand is not None:
            selected.append(best_cand)
            candidates.remove(best_cand)

    return list(reversed(selected))


def _select_top_by_frequency(items: list[str], n: int) -> list[str]:
    """Return the N most frequently mentioned items (case-insensitive dedup)."""
    normed: dict[str, str] = {}
    for item in items:
        key = _normalise(item)
        if key and len(key) > 3:
            normed.setdefault(key, item)

    counts = Counter(_normalise(i) for i in items if _normalise(i) and len(_normalise(i)) > 3)
    top = [normed[k] for k, _ in counts.most_common(n) if k in normed]
    return top


def _dedup_recent(items: list[str], n: int) -> list[str]:
    """Return the N most recent unique items (case-insensitive dedup)."""
    seen: set[str] = set()
    result: list[str] = []
    for item in reversed(items):
        key = _normalise(item)
        if key and key not in seen:
            seen.add(key)
            result.append(item)
            if len(result) >= n:
                break
    return list(reversed(result))


def _derive_open_questions(
    stage: str,
    top_concept: str,
    curiosity_threads: list[str],
) -> list[str]:
    """
    Derive open questions for the learner based on stage and curiosity threads.

    Three sources:
      1. Stage-specific template (filled with top_concept).
      2. Curiosity-thread derived questions (from category labels).
      3. A general "what comes next" question.
    """
    questions: list[str] = []

    # Source 1: stage template
    templates = _STAGE_QUESTIONS.get(stage, _STAGE_QUESTIONS["foundation"])
    primary   = templates[0].format(concept=top_concept) if "{concept}" in templates[0] else templates[0]
    questions.append(primary)

    # Source 2: curiosity threads → questions
    for thread in curiosity_threads[:2]:
        q = _thread_to_question(thread, top_concept)
        if q and q not in questions:
            questions.append(q)

    # Source 3: generic progression question
    if len(templates) > 1:
        secondary = templates[1].format(concept=top_concept) if "{concept}" in templates[1] else templates[1]
        if secondary not in questions:
            questions.append(secondary)

    return questions[:_LEVEL1_QUESTIONS]


# Curiosity category labels → implied question framing
_THREAD_QUESTION_MAP: dict[str, str] = {
    "hidden mechanism":      "What hidden mechanism explains an outcome most people attribute to surface-level causes?",
    "origin myth shattered": "What commonly accepted origin story about this domain turns out to be wrong?",
    "the failure that explained everything": "Which notable failure revealed the most about how this system actually works?",
    "geopolitical leverage":  "How does geopolitical positioning create invisible leverage in this domain?",
    "contrarian view":        "What would a well-informed contrarian argue about the consensus view here?",
    "second order effect":    "What second-order effect is most underweighted in current analysis?",
    "competitive dynamics":   "What structural force actually determines who wins in this space?",
    "regulatory arbitrage":   "Where does regulatory asymmetry create an opportunity or vulnerability?",
}


def _thread_to_question(thread: str, concept: str) -> str:
    """Convert a curiosity thread label to an open question."""
    tl = thread.lower().strip()
    for key, q in _THREAD_QUESTION_MAP.items():
        if key in tl:
            return q
    # Generic fallback
    return f"What aspect of '{thread}' is still unexplored in the context of {concept}?"


# ═══════════════════════════════════════════════════════════════════════════════
# Level format builders
# ═══════════════════════════════════════════════════════════════════════════════

def _build_level0(memory: dict) -> str:
    """Level 0 — delegates to the existing learning_memory_service."""
    try:
        from ..services.learning_memory_service import build_memory_prompt_section
        result = build_memory_prompt_section(memory)
        return result or "(no memory yet)"
    except Exception:
        return "(memory unavailable)"


def _build_level1(
    stage: str,
    concepts: list[str],
    mechanisms: list[str],
    open_questions: list[str],
    curiosity_threads: list[str],
    key_examples: list[str],
) -> str:
    """Level 1 — Structured five-category memory section."""
    lines: list[str] = []
    lines.append(f"LEARNING MEMORY — {stage.upper()} stage")
    lines.append("─" * 42)

    if concepts:
        lines.append(f"Concepts Learned ({len(concepts)} selected):")
        for c in concepts:
            lines.append(f"  • {c}")

    if mechanisms:
        lines.append(f"Mechanisms Covered ({len(mechanisms)} selected):")
        for m in mechanisms:
            lines.append(f"  • {m}")

    if key_examples:
        lines.append(f"Key Examples: {', '.join(key_examples)}")

    if curiosity_threads:
        lines.append(f"Curiosity Threads: {', '.join(curiosity_threads)}")

    if open_questions:
        lines.append("Open Questions:")
        for q in open_questions:
            lines.append(f"  • {q}")

    return "\n".join(lines)


def _build_level2(
    stage: str,
    concepts: list[str],
    mechanisms: list[str],
    examples: list[str],
    threads: list[str],
    total_concepts: int,
    total_mechanisms: int,
    total_examples: int,
    industries: list[str],
    geographies: list[str],
) -> str:
    """Level 2 — Knowledge graph summary: one line per category."""
    top_concepts  = ", ".join(concepts[:_LEVEL2_CONCEPTS])
    top_mechs     = ", ".join(mechanisms[:_LEVEL2_MECHANISMS]) if mechanisms else "none yet"
    top_examples  = ", ".join(examples[:_LEVEL2_EXAMPLES]) if examples else "none yet"
    top_threads   = ", ".join(threads[:2]) if threads else "none yet"

    top_industries   = ", ".join(sorted(set(industries))[:2]) if industries else ""
    top_geographies  = ", ".join(sorted(set(geographies))[:2]) if geographies else ""

    lines: list[str] = [f"[Memory: {stage} | {total_concepts}c / {total_mechanisms}m]"]
    if top_concepts:
        lines.append(f"  Concepts:   {top_concepts}")
    if mechanisms:
        lines.append(f"  Mechanisms: {top_mechs}")
    if examples:
        lines.append(f"  Examples:   {top_examples}")
    if threads:
        lines.append(f"  Curiosity:  {top_threads}")
    if top_industries:
        lines.append(f"  Industries: {top_industries}")
    if top_geographies:
        lines.append(f"  Coverage:   {top_geographies}")

    return "\n".join(lines)


def _build_level3(
    stage: str,
    concepts: list[str],
    total_concepts: int,
    total_mechanisms: int,
) -> str:
    """Level 3 — Single-sentence progression summary."""
    top3 = ", ".join(concepts[:3]) if concepts else "foundational topics"
    return (
        f"[Memory: {stage} stage — {total_concepts} concepts, "
        f"{total_mechanisms} mechanisms covered — top: {top3}]"
    )
