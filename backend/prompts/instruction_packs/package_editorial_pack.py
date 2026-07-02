"""
Package Editorial Instruction Pack
=====================================
Static editorial philosophy and writing mechanics for the daily package generation prompt.

Canonical owners
----------------
EDITORIAL_PHILOSOPHY     — was project_insight_prompt.py (inline, lines 254–271)
HOOK_FIRST_RULES         — was project_insight_prompt.py (inline, lines 330–360)
                           Template: use .format(domain=project_name) before injecting.

Usage
-----
from ..instruction_packs.package_editorial_pack import (
    EDITORIAL_PHILOSOPHY, HOOK_FIRST_RULES,
)
hook_section = HOOK_FIRST_RULES.format(domain=project_name)
"""

EDITORIAL_PHILOSOPHY: str = """\
══════════════════════════════════════
EDITORIAL PHILOSOPHY  ← READ FIRST
══════════════════════════════════════
The feed is NOT a textbook. It is an intelligent editorial briefing system.
Every card must deliver a SPECIFIC, NON-OBVIOUS insight — not a topic overview.

ASSUME the user already knows the basics. Skip definitions.
START with what matters: implications, shifts, hidden patterns, expert-level observations.

TEST each card before writing: "Would a smart person learn something non-obvious from this?"
  If YES → write it. If NO → rewrite the angle.

BAD CARD ANGLE: "Machine learning is a subset of AI that uses algorithms to learn from data."
GOOD CARD ANGLE: "The reason ML engineers obsess over data quality isn't accuracy — it's that bad data teaches models the wrong patterns with high confidence."

BAD CARD ANGLE: "Digital manufacturing uses automation."
GOOD CARD ANGLE: "Indian manufacturers are accelerating automation because global compliance pressure from Western regulators is creating an adoption gap that late movers may not recover from.\""""

# Template — call .format(domain=project_name) before injecting into prompt.
HOOK_FIRST_RULES: str = """\
══════════════════════════════════════
HOOK-FIRST WRITING RULES  ← MANDATORY
══════════════════════════════════════
Every card follows this structure:
  HOOK → INSIGHT → EVIDENCE/EXAMPLE → IMPLICATION

NOT:
  DEFINITION → EXPLANATION → CONCLUSION

HOOK (first 1–2 sentences of summary):
  Open with curiosity tension — not a definition.

  Good hooks (three distinct techniques — use the structure, not the phrase):
  • "Most [experts/practitioners/analysts] assume..."   — challenge authority expectation
  • "When [specific company/event] happened, it revealed..."   — narrative entry point
  • "Ironically, the harder they pushed on X, the worse Y became."   — reversal/irony structure

  BAD opening: "X is a technology that enables..."
  GOOD opening: "When X collapsed at [Company], the failure exposed something practitioners had quietly known for years..."

INSIGHT: The non-obvious observation. Not what it is — what it means, why experts care.
EVIDENCE: One specific example — company, metric, event, or decision — that makes it concrete.
IMPLICATION: What this means for the user's understanding of {domain}.

ASSUMPTION RULE:
The user is intelligent, already curious, and not reading a textbook.
  • Skip orientation paragraphs — open directly on the non-obvious part
  • If a concept appears in the Knowledge State's covered topics, treat it as KNOWN — build on it, never re-explain it
  • One sentence of framing is enough before the insight lands
  • The implication always earns more space than the explanation
  • Speed through the "what" to arrive at the "why it's strange" and "what happens next\""""
