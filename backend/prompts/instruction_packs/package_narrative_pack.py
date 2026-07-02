"""
Package Narrative Instruction Pack
=====================================
Narrative frames, tones, title patterns, editorial roles, and section assembly instructions
for the daily package generation prompt.

Canonical owners
----------------
EMOTIONAL_TONE_PALETTE    — was project_insight_prompt.py (inline, lines 312–328)
TITLE_STYLE_LIBRARY       — was project_insight_prompt.py (inline, lines 398–439)
EDITORIAL_ROLES           — was project_insight_prompt.py (YOUR TASK section, lines 459–468)
PACKAGE_COMPOSITION       — was project_insight_prompt.py (lines 470–477)
                            Template: .format(count=count)
ARTICLE_MIX               — was project_insight_prompt.py (lines 479–483)
SECTION_1_INSTRUCTIONS    — was project_insight_prompt.py (lines 487–503)
                            Template: .format(count=count, project_name=..., difficulty=...)

Usage
-----
from ..instruction_packs.package_narrative_pack import (
    EMOTIONAL_TONE_PALETTE, TITLE_STYLE_LIBRARY,
    EDITORIAL_ROLES, PACKAGE_COMPOSITION, ARTICLE_MIX, SECTION_1_INSTRUCTIONS,
)
section1 = SECTION_1_INSTRUCTIONS.format(count=count, project_name=name, difficulty=diff)
"""

EMOTIONAL_TONE_PALETTE: str = (
    "═" * 38 + "\n"
    "EMOTIONAL TONE PALETTE  ← MANDATORY\n"
    + "═" * 38 + "\n"
    "Each card must carry a distinct emotional weight. No two consecutive cards share the same tone.\n"
    "The full package must cycle through at least 4–5 distinct tones:\n"
    "  SHOCKING · OPTIMISTIC · UNSETTLING · STRATEGIC · VISIONARY"
    " · INVESTIGATIVE · PROVOCATIVE · PRACTICAL · MYSTERIOUS"
)

TITLE_STYLE_LIBRARY: str = (
    "═" * 38 + "\n"
    "TITLE STYLE LIBRARY — ROTATE MANDATORY\n"
    + "═" * 38 + "\n"
    "Every title MUST fit one of these 9 structural patterns.\n"
    "Different cards in the same package MUST use different patterns.\n"
    "\n"
    "1. MYTH-BUSTING — Challenge a widely-held assumption directly.\n"
    "   Pattern: \"Why [Domain]'s '[Conventional Label]' Is Actually [Surprising Reality]\"\n"
    "\n"
    "2. CONTRADICTION — Name two things in tension that shouldn't be — or should align but don't.\n"
    "   Pattern: \"Why [Domain] [Outcome A] Exactly Where You'd Expect [Outcome B]\"\n"
    "\n"
    "3. HIDDEN DEPENDENCY — Expose what an outcome is contingent on that the standard story misses.\n"
    "   Pattern: \"The Entire [Market/System] Runs on a Single [Chokepoint] Nobody Tracks Until It Breaks\"\n"
    "\n"
    "4. ECONOMIC LEVERAGE — Surface the mechanism creating disproportionate power or return.\n"
    "   Pattern: \"The [N]% [Metric] That Controls [X]% of [Market/Outcome]\"\n"
    "\n"
    "5. HISTORICAL COMPARISON — Use a past event to sharpen understanding of the present.\n"
    "   Pattern: \"The [Year] [Policy/Crisis] That Set the Rules for [Domain] for the Next [N] Years\"\n"
    "\n"
    "6. GEOPOLITICAL TENSION — Surface the political-economic constraint reshaping a domain.\n"
    "   Pattern: \"Why [Country A]'s Dominance in [Resource] Is a Problem [Country B] Can't Buy Its Way Out Of\"\n"
    "\n"
    "7. OPERATIONAL FAILURE — Use a specific failure as the lens for how a system works.\n"
    "   Pattern: \"The [Incident/Collapse] That Forced [Institution] to Rethink How It Oversees [Domain]\"\n"
    "\n"
    "8. STRATEGIC MOAT — Identify the structural advantage incumbents hold (or are losing).\n"
    "   Pattern: \"Why [Company/Sector]'s [N]-Year [Advantage] Is Harder to Replicate Than It Looks\"\n"
    "\n"
    "9. INVISIBLE INFRASTRUCTURE — Surface the hidden system enabling a visible outcome.\n"
    "   Pattern: \"The [Hidden System/Network] That Quietly Controls [Market Access/Outcome] — and Who Owns It\""
)

EDITORIAL_ROLES: str = (
    "INTERNAL EDITORIAL PLANNING (do NOT include in output):\n"
    "Before writing any card, assign each an editorial role AND an emotional tone from the palette above.\n"
    "\n"
    "Editorial roles — each package needs these represented:\n"
    "  CENTERPIECE      — the anchor story. Most depth, highest insight density. Carries the day's thesis.\n"
    "  PRACTICAL INTEL  — what a practitioner does differently after reading this. Operational, grounded.\n"
    "  FAST SIGNAL      — crisp, news-driven, high-stakes. Short and sharp — one claim, clearly stated.\n"
    "  FUTURE PREDICTION — forward-looking tension. What shifts next and who feels it first.\n"
    "  STRATEGIC SHIFT  — how competitive dynamics, business models, or incentive structures changed.\n"
    "  WILD CARD        — the card that surprises. Unexpected angle, cross-domain leap, or hidden system."
)

# Template — call .format(count=count) before injecting.
PACKAGE_COMPOSITION: str = (
    "PACKAGE COMPOSITION RULES:\n"
    "  • Open with the highest-energy card (SHOCKING or INVESTIGATIVE tone) — hook the reader immediately\n"
    "  • Place PRACTICAL INTEL in the middle — grounding after conceptual intensity\n"
    "  • End the core section with FUTURE PREDICTION — leaving the reader with forward tension\n"
    "  • The two curiosity cards continue the emotional or thematic thread from the core section\n"
    "  • Escalate complexity: accessible hook → deeper mechanism → most sophisticated insight → forward tension\n"
    "\n"
    "The package must feel like a deliberate intellectual journey — not {count} independent blocks."
)

ARTICLE_MIX: str = (
    "ARTICLE MIX FOR CORE CARDS (target distribution):\n"
    "  • 1–2 reinforcement/evolution cards: revisit prior concepts at higher sophistication\n"
    "  • 2–3 new progression cards: introduce suggested next topics and adjacent ideas\n"
    "  • 1 real-world/news card: current event, trend, or recent development\n"
    "  • 1 practical/case-study card: implementation story, company story, applied example"
)

# Template — call .format(count=count, project_name=..., difficulty=...) before injecting.
# "Assume the user knows the basics. Skip definitions." is already in EDITORIAL_PHILOSOPHY.
SECTION_1_INSTRUCTIONS: str = (
    "SECTION 1 — \"insights\" array  (EXACTLY {count} CORE LEARNING cards)\n"
    "  • Use CORE articles as primary sources. Synthesise across multiple sources.\n"
    "  • content_type: \"news\" for current events/developments, \"educational\" for durable concepts.\n"
    "  • Titles must be specific and compelling — ≤ 12 words, never generic.\n"
    "    BAD: \"Understanding Neural Networks in Finance\"\n"
    "    GOOD: \"Why Neural Networks Overfit — and What Quants Actually Do About It\"\n"
    "  • Each title MUST use one of the 9 structural patterns from TITLE STYLE LIBRARY above.\n"
    "    Different cards in the same package MUST use different pattern types.\n"
    "  • Never use banned phrases from BANNED PHRASES section above.\n"
    "  • summary: 2–3 sentences structured as HOOK → INSIGHT. Not a definition summary.\n"
    "  • blocks: 4–5 blocks that go deeper than the summary — follow INSIGHT → EVIDENCE → IMPLICATION\n"
    "    across them. Surface what's non-obvious. Do not re-explain the summary content in blocks.\n"
    "  • Reflect {difficulty} conceptual depth — avoid glossary-level content.\n"
    "  • Cards must feel tightly scoped to {project_name}, not generic commentary."
)
