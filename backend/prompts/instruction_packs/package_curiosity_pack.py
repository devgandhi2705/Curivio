"""
Package Curiosity Engine Instruction Pack
==========================================
Curiosity section instructions, tension scoring, tension categories,
and card-writing rules for the daily package generation prompt.

Canonical owners
----------------
CURIOSITY_TARGET       — was project_insight_prompt.py (SECTION 2 header, lines 505–511)
TENSION_SCORING        — was project_insight_prompt.py (lines 513–539)
TENSION_CATEGORIES     — was project_insight_prompt.py (lines 541–597)
CURIOSITY_TITLE_RULES  — was project_insight_prompt.py (lines 599–616)
CURIOSITY_SUMMARY_RULES — was project_insight_prompt.py (lines 618–625)
CURIOSITY_CARD_RULES   — was project_insight_prompt.py (lines 627–644)
                         Template: .format(project_name=project_name)

Usage
-----
from ..instruction_packs.package_curiosity_pack import (
    CURIOSITY_TARGET, TENSION_SCORING, TENSION_CATEGORIES,
    CURIOSITY_TITLE_RULES, CURIOSITY_SUMMARY_RULES, CURIOSITY_CARD_RULES,
)
curiosity_rules = CURIOSITY_CARD_RULES.format(project_name=project_name)
"""

CURIOSITY_TARGET: str = """\
SECTION 2 — "curiosity_insights" array  (EXACTLY 2 curiosity cards)
  ───────────────────────────────────────────────────────────────────
  EMOTIONAL TARGET: "Wait… seriously?" — NOT "That's informative."

  If you read the summary and think "that's interesting" → it's not good enough. Find something better.
  If you read it and think "that can't be right" → you're close.
  If you read it and feel mild anger, disbelief, or delight → write it.\""""

TENSION_SCORING: str = """\
  ── TENSION SCORING (internal only — do NOT include in JSON output) ────────────
  Score each candidate on 4 dimensions (0–3 each):
    NOVELTY · CONTRADICTION · EMOTIONAL SURPRISE · NARRATIVE TENSION
  Select the two highest-scoring candidates. Minimum acceptable total: 7/12.\""""

TENSION_CATEGORIES: str = """\
  ── TENSION CATEGORY LIBRARY ─────────────────────────────────────────────────
  Pick ONE category per card. The two cards MUST use different categories.

  1. HIDDEN FAILURE — Core emotion: betrayal.
     The outcome everyone calls a success hides unreported damage.

  2. UNINTENDED CONSEQUENCE — Core emotion: irony.
     Solving problem A quietly created problem B nobody wanted to admit.

  3. SCANDAL / INSTITUTIONAL FAILURE — Core emotion: outrage.
     A trusted institution was complicit in or blind to the exact harm it was meant to prevent.

  4. INVISIBLE DEPENDENCY — Core emotion: vertigo.
     The entire outcome depends on a hidden input nobody tracks until it fails.

  5. SURPRISING INCENTIVE — Core emotion: suspicion.
     Actors operated on a hidden incentive that explains the outcome better than the official story.

  6. GEOPOLITICAL MANIPULATION — Core emotion: disillusionment.
     A market outcome is a political decision dressed as one.

  7. BILLION-DOLLAR MISTAKE — Core emotion: schadenfreude + dread.
     A catastrophically expensive decision that seemed perfectly reasonable at the time.

  8. INDUSTRY MYTH — Core emotion: vindication or betrayal.
     The thing everyone inside the domain believes is true — demonstrably isn't.

  9. INVERSE CAUSALITY — Core emotion: disorientation.
     Cause and effect are reversed from what the standard story claims.\""""

CURIOSITY_TITLE_RULES: str = """\
  ── TITLE RULES ───────────────────────────────────────────────────────────────
  Titles must make the reader think: "I have to know how this ends."

  TIER 1 (aim for these):
    Titles containing implicit betrayal: "The [trusted actor] That [betrayed something]"
    Titles inverting belief: "Why [conventional wisdom] Is [the opposite truth]"
    Titles naming a figure + consequence: "The [amount/$] [decision] That [specific outcome]"

  STRUCTURAL EXAMPLES (domain-neutral):
    "The [Trusted Institution] That [Enabled/Caused] the Outcome It Was Created to Prevent"
    "How [Historical Event/Policy] Accidentally Created [Unexpected Modern Consequence]"
    "The [Hidden Actor] Quietly Determining [High-Stakes Outcome] — and Nobody Tracks It"

  FORBIDDEN titles (never use):
    Any title that could appear on a textbook chapter or Wikipedia article
    — specific banned patterns: see BANNED PHRASES section above\""""

CURIOSITY_SUMMARY_RULES: str = """\
  ── SUMMARY RULES ─────────────────────────────────────────────────────────────
  First sentence: the specific "Wait… seriously?" fact — name the thing, the actor, the consequence
  Second sentence: who it affects and what the stakes are
  Third sentence: tease the payoff — what does this reveal about the system's hidden structure?

  BAD opening: "India's pharmaceutical industry has faced significant challenges in recent years."
  GOOD opening: "Every major US flu vaccine shortage was determined 6 months earlier in a single
  factory complex in Ankleshwar, Gujarat — and the FDA had no mechanism to track it."\""""

# Template — call .format(project_name=project_name) before injecting.
CURIOSITY_CARD_RULES: str = """\
  ── CARD RULES ────────────────────────────────────────────────────────────────
  • content_type MUST be "curiosity"
  • summary: 2–3 sentences — first sentence IS the "Wait… seriously?" trigger
  • blocks: 3–4 blocks that deliver the payoff — what this reveals about the system's hidden structure.
    Use insight, counterpoint, mechanism, and reflection blocks. Make the reader feel let in on something.
  • Must feel like a DISCOVERY, not a mini-lesson — the reader should feel they've been let in on something
  • Still connected to {project_name}, but through a surprising angle
  • Use CURIOSITY articles if available; otherwise synthesise from domain knowledge
  • The two cards MUST use different tension categories from the library above

RULES FOR ALL CARDS:
  • primary_source and supporting_sources: URLs taken verbatim from provided articles only — see SOURCE GROUNDING section
  • Each card must feel tonally and structurally distinct from every other card
  • Never repeat a concept at the same surface level it was first introduced
  • Hook-first, always — see HOOK-FIRST WRITING RULES above
  • Block content tone must feel editorial, not framework — avoid generic framings:
      YES: "The Silent Pressure", "What Changed", "The Real Constraint", "Under the Surface", "What Experts Are Watching"
      NO:  "WHY THIS MATTERS", "DEEP LEARNING", "KEY INSIGHT", "BACKGROUND", "CONCLUSION"
  • Each card's narrative_frame field must be populated — it determines the card's angle and structure\""""
