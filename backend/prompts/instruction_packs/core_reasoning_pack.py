"""
Core Reasoning Instruction Pack
================================
Single source of truth for Curivio's reasoning-quality directives:
  - Mechanism reveal & causality-first rules
  - Specificity mandate & source signal extraction
  - Real-world tension injection
  - Insight density & synthesis standards
  - Hidden drivers & second-order effects

Canonical owners
----------------
SOURCE_SIGNAL_EXTRACTION   ← was project_insight_prompt.py (lines 574–617)
REAL_WORLD_TENSION         ← was project_insight_prompt.py (lines 605–617)
INSIGHT_DENSITY_RULE       ← was deep_research_prompt.py (line 125)
                              and chat_prompt_service.py (line 522) — exact duplicate
MECHANISM_NAMING_RULE      ← was deep_research_prompt.py (line 110)
CAUSALITY_FIRST_RULE       ← was chat_prompt_service.py _NATURAL_GUIDELINES (line 432)
SYNTHESIS_ACROSS_SOURCES   ← was deep_research_prompt.py (lines 121–122)

Usage
-----
from ..instruction_packs.core_reasoning_pack import (
    SOURCE_SIGNAL_EXTRACTION, REAL_WORLD_TENSION,
    INSIGHT_DENSITY_RULE, MECHANISM_NAMING_RULE,
)
"""

# ── Atomic rules ─────────────────────────────────────────────────────────────
# These are single sentences used individually across multiple prompts.

MECHANISM_NAMING_RULE: str = (
    "Name mechanisms and causality — not 'X is important' but "
    "'X works because Y, which causes Z'."
)

CAUSALITY_FIRST_RULE: str = (
    "Prioritise causality over description: explain WHY things work the way they do, "
    "not just WHAT they are."
)

INSIGHT_DENSITY_RULE: str = (
    "Increase insight density per sentence — "
    "if a sentence doesn't add something new, cut it."
)

SECOND_ORDER_EFFECTS_RULE: str = (
    "Surface the non-obvious: second-order effects and hidden implications "
    "are more valuable than restating what the user likely already knows."
)

SYNTHESIS_ACROSS_SOURCES: str = (
    "Synthesise ACROSS sources — not just summarise the best article. "
    "Identify where sources AGREE (establish foundation), where they CONTRADICT "
    "(surface it explicitly), and what is UNDERWEIGHTED across all coverage."
)

TRADEOFFS_NAMING_RULE: str = (
    "Every tradeoff must name a concrete dimension and two real, specific alternatives — "
    "never vague 'pros and cons'."
)


# ── Full sections ─────────────────────────────────────────────────────────────
# Complete instruction blocks used verbatim in prompt f-strings.

SOURCE_SIGNAL_EXTRACTION: str = """\
══════════════════════════════════════
SOURCE SIGNAL EXTRACTION
══════════════════════════════════════
When synthesising the provided articles, extract SIGNAL-LEVEL information — not topic-level summaries.

Prioritize extracting:
  • Specific shifts: what changed, when, and the strategic consequence
  • Implications: downstream effects, second-order consequences
  • Operational insights: what practitioners actually encounter trying to implement this
  • Strategic moves: what companies/institutions are doing and the real reason why
  • Real-world examples: named actors, specific outcomes, measurable stakes
  • Regulatory/market pressure: external forces accelerating or blocking adoption
  • Hidden causes: the real driver behind a visible outcome
  • Market reactions: how actors responded and what that reveals about the system

SPECIFICITY MANDATE — ZERO TOLERANCE FOR VAGUENESS:
Every abstraction must be replaced with a real noun, number, name, or date.

BANNED → REQUIRED replacements:
  "Foreign investments increased"   → name the companies, the country, the amount, the year
  "advanced technology"             → name it: diffusion models, RISC-V, mRNA synthesis, factor investing
  "significant growth"              → a specific % or metric and timeframe
  "various companies"               → name them
  "some economists"                 → name them or their institution
  "major transformation"            → what specifically changed, when, triggered by what event
  "enhanced efficiency"             → cut [what] by [how much] at [which operation or company]
  "increasing adoption"             → who adopted it, when, at what scale
  "regulatory pressure"             → name the regulation, the body, and the deadline

If you cannot name it, do not say it. Specificity IS credibility."""

REAL_WORLD_TENSION: str = """\
══════════════════════════════════════
REAL-WORLD TENSION
══════════════════════════════════════
Inject genuine complexity: tradeoffs, controversies, failures, risks, competitive dynamics,
regulatory pressure, and unresolved uncertainty. This is what makes the feed feel alive — not sanitized."""
