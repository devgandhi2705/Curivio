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
  Before finalising the two cards, score each candidate on these 4 dimensions (0–3 each).
  Select the two candidates with the highest combined scores. Minimum acceptable: 7/12.

  NOVELTY (0–3)
    0 = widely known to anyone who read a headline
    1 = known to domain experts
    2 = known inside the industry but never framed this way
    3 = almost nobody has connected these two things

  CONTRADICTION (0–3)
    0 = confirms common belief
    1 = slightly unexpected
    2 = inverts a common belief
    3 = destroys a firmly held assumption — the reader's mental model has to change

  EMOTIONAL SURPRISE (0–3)
    0 = neutral
    1 = mildly interesting
    2 = genuinely shocking or counterintuitive
    3 = makes the reader angry, unsettled, or feel like they were misled

  NARRATIVE TENSION (0–3)
    0 = no protagonist, no stakes
    1 = clear outcome
    2 = irony or reversal
    3 = institutional betrayal, villain/victim structure, or billion-dollar mistake arc\""""

TENSION_CATEGORIES: str = """\
  ── TENSION CATEGORY LIBRARY ─────────────────────────────────────────────────
  Pick ONE category per card. The two cards MUST use different categories.

  1. HIDDEN FAILURE
     The outcome everyone calls a success hides unreported damage.
     Core emotion: betrayal. "We were celebrating the wrong thing."
     "India's generic drug export record hides a 15-year data falsification wave
      the FDA systematically missed — and only found when US manufacturers sued."

  2. UNINTENDED CONSEQUENCE
     Solving problem A quietly created problem B that nobody wanted to admit.
     Core emotion: irony. "The solution became the new problem."
     "The 1970 Patent Act that made India a generic drug powerhouse also built its
      dependence on China for the raw inputs that make those drugs work."

  3. SCANDAL / INSTITUTIONAL FAILURE
     A trusted institution was either complicit in or blind to the exact harm it was meant to prevent.
     Core emotion: outrage. "The watchdog was in on it."
     "The FDA inspector whose approvals enabled $2B of Indian pharma exports was later
      found to have accepted bribes. Every approval he issued is now legally uncertain."

  4. INVISIBLE DEPENDENCY
     The entire outcome depends on a hidden input nobody tracks until it fails.
     Core emotion: vertigo. "This is hanging by a thread I didn't know existed."
     "80% of the world's paracetamol supply chain runs through one chemical step
      performed in three factories — all in the same Chinese province."

  5. SURPRISING INCENTIVE
     The actors operated on a hidden incentive that explains the outcome better than the official story.
     Core emotion: suspicion. "Of course they weren't doing it for the reason they claimed."
     "The FDA's aggressive India inspection campaign of 2013–2016 coincided precisely with
      a lobbying blitz by US generic manufacturers losing market share to Indian imports."

  6. GEOPOLITICAL MANIPULATION
     A market outcome is not a market outcome — it's a political decision dressed as one.
     Core emotion: disillusionment. "There is no such thing as a neutral supply chain."
     "China's API dominance was not an accident of cost efficiency — it was a deliberate
      state subsidy campaign designed to create pharmaceutical dependency in export markets."

  7. BILLION-DOLLAR MISTAKE
     An institution made a catastrophically expensive decision that seemed perfectly reasonable at the time.
     Core emotion: schadenfreude + dread. "How did they not see it coming?"
     "The US government's 1990s policy to offshore API manufacturing to cut drug costs worked —
      it reduced production costs by 40% and created the supply fragility that now keeps the
      Pentagon awake."

  8. INDUSTRY MYTH
     The thing everyone inside the domain believes is true — demonstrably isn't.
     Core emotion: vindication or betrayal depending on which side you're on.
     "The industry assumes FDA warning letters track quality failures. The data suggests they
      correlate more reliably with US trade policy shifts than with actual inspection findings."

  9. INVERSE CAUSALITY
     The cause and effect are reversed from what the industry story claims.
     Core emotion: disorientation. "I was looking at this backwards the whole time."
     "Indian companies didn't improve quality because of FDA pressure. FDA pressure
      intensified because Indian companies grew large enough to threaten American generics players."\""""

CURIOSITY_TITLE_RULES: str = """\
  ── TITLE RULES ───────────────────────────────────────────────────────────────
  Titles must make the reader think: "I have to know how this ends."

  TIER 1 (aim for these):
    Titles containing implicit betrayal: "The [trusted actor] That [betrayed something]"
    Titles inverting belief: "Why [conventional wisdom] Is [the opposite truth]"
    Titles naming a figure + consequence: "The [amount/$] [decision] That [specific outcome]"

  FORBIDDEN titles (never use):
    Any title that could appear on a textbook chapter or Wikipedia article
    — specific banned patterns: see BANNED PHRASES section above

  GOOD titles:
    "The Chinese Dependency India's Pharma Boom Has Been Hiding for 20 Years"
    "The FDA Inspector Whose Approvals Turned Out to Be Bribes"
    "How a Cold War Nuclear Policy Accidentally Created India's Generic Drug Empire"
    "The Quality Audit System That Made Indian Exports Possible — and Meaningless Simultaneously"
    "The US Lobbying Campaign That Launched India's FDA Inspection Crisis"\""""

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
  • educational_explanation: 3–5 sentences of payoff — what this reveals about the system's hidden structure
  • Must feel like a DISCOVERY, not a mini-lesson — the reader should feel they've been let in on something
  • Still connected to {project_name}, but through a surprising angle
  • Use CURIOSITY articles if available; otherwise synthesise from domain knowledge
  • The two cards MUST use different tension categories from the library above

RULES FOR ALL CARDS:
  • source_links ONLY from provided articles (never fabricate URLs)
  • Each card must feel tonally and structurally distinct from every other card
  • Never repeat a concept at the same surface level it was first introduced
  • Hook-first, always — no card should open with a definition
  • Sub-headers inside educational_explanation must feel editorial, not framework:
      YES: "The Silent Pressure", "What Changed", "The Real Constraint", "Under the Surface", "What Experts Are Watching"
      NO:  "WHY THIS MATTERS", "DEEP LEARNING", "KEY INSIGHT", "BACKGROUND", "CONCLUSION"
  • Each card's narrative_frame field must be populated — it determines the card's angle and structure\""""
