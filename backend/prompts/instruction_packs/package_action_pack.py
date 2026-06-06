"""
Package Action Design Instruction Pack
========================================
Action item design philosophy, 8 action type templates, and selection rules
for the daily package generation prompt. Fully static — no runtime formatting needed.

Canonical owner
---------------
ACTION_DESIGN — was project_insight_prompt.py (inline, lines 646–700)

Usage
-----
from ..instruction_packs.package_action_pack import ACTION_DESIGN
"""

ACTION_DESIGN: str = """\
══════════════════════════════════════
ACTION DESIGN — MANDATORY
══════════════════════════════════════
The "action_item" is NOT homework. It is an investigative mission.

PHILOSOPHY:
  A good action makes the reader DO something active — not just research more.
  It should create mild intellectual discomfort, deepen retention, and connect
  directly to a specific mechanism, company, or claim from TODAY's cards.
  It must be completable in 10–15 minutes with a web search.

  BAD: "Research the FDA approval process."
  GOOD: "Find the last 3 FDA warning letters issued to Indian manufacturing plants.
         What was the most common violation type? Compare against today's card on data integrity."

CHOOSE ONE of these 8 action types — pick the one that best fits today's dominant mechanism or insight:

  COMPARE
    Put two things from today in direct tension. Force a structural difference to surface.
    Template: "Compare how [X] and [Y] approach [Z from today's cards] — what does the difference reveal?"

  INVESTIGATE
    Send the reader to find a real case that proves or complicates today's mechanism.
    Template: "Find one real instance of [specific claim from today's cards] — name the company, date, and outcome."

  FIND CONTRADICTION
    Force the reader to locate evidence that breaks the narrative from today.
    Template: "Today's analysis assumes [claim]. Find one market/company/event that contradicts this."

  ANALYZE COMPANY
    Apply today's mechanism to a specific company named in the cards (or closely related).
    Template: "Look at [company from today's cards]: does their [metric/strategy/filing] match today's thesis?"

  IDENTIFY REAL-WORLD EXAMPLE
    Make abstract concrete by finding a living instance of the mechanism.
    Template: "Find one real example of [mechanism from today] happening right now — name the specific actors."

  PREDICT OUTCOME
    Anchor forward reasoning in today's mechanism and force a specific forecast.
    Template: "Given [mechanism from today], what happens to [specific actor] if [condition changes]? State your reasoning."

  CHALLENGE ASSUMPTION
    Pick the most confident claim from today and find evidence that complicates it.
    Template: "Today claimed [X]. Find one piece of evidence that suggests this is incomplete, wrong, or overstated."

  MAP DEPENDENCY
    Build a dependency chain directly from today's content.
    Template: "From today's content: trace [specific process] step by step. Where are the 2–3 fragile points?"

SELECTION RULES:
  • The action MUST name something specific from today's package — a company, mechanism, claim, or data point
  • Beginner level → prefer COMPARE or IDENTIFY; avoid PREDICT and MAP DEPENDENCY
  • Advanced level → prefer FIND CONTRADICTION, PREDICT, CHALLENGE ASSUMPTION
  • Intermediate → any type works; vary from prior days if possible
  • The action should feel like a natural continuation of the most intellectually charged card\""""
