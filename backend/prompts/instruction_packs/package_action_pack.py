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
The "action_item" is an investigative mission — completable in 10–15 min with a web search.
Must name something specific from today's package: a company, mechanism, claim, or data point.

Choose ONE action type — pick whichever best fits today's dominant insight:

  COMPARE           — "Compare how [X] and [Y] approach [Z from today] — what does the difference reveal?"
  INVESTIGATE       — "Find one real instance of [claim from today] — name the company, date, and outcome."
  FIND CONTRADICTION — "Today assumes [claim]. Find one market/company/event that contradicts this."
  ANALYZE COMPANY   — "Look at [company from today]: does their [metric/strategy/filing] match today's thesis?"
  IDENTIFY EXAMPLE  — "Find one real example of [mechanism from today] right now — name the specific actors."
  PREDICT OUTCOME   — "Given [mechanism from today], what happens to [actor] if [condition changes]? State your reasoning."
  CHALLENGE ASSUMPTION — "Today claimed [X]. Find one piece of evidence that suggests it's incomplete or wrong."
  MAP DEPENDENCY    — "From today: trace [specific process] step by step. Where are the 2–3 fragile points?"

Beginner → prefer COMPARE or IDENTIFY. Advanced → prefer FIND CONTRADICTION, PREDICT, CHALLENGE ASSUMPTION.\""""
