"""
Package Editorial Instruction Pack
=====================================
Static editorial philosophy and writing mechanics for the daily package generation prompt.

Canonical owners
----------------
EDITORIAL_PHILOSOPHY     — was project_insight_prompt.py (inline, lines 254–271)
ACCELERATION_PHILOSOPHY  — was project_insight_prompt.py (inline, lines 274–292)
HOOK_FIRST_RULES         — was project_insight_prompt.py (inline, lines 330–360)
                           Template: use .format(domain=project_name) before injecting.
WHY_IT_WORKS_RULES       — was project_insight_prompt.py (inline, lines 362–392)

Usage
-----
from ..instruction_packs.package_editorial_pack import (
    EDITORIAL_PHILOSOPHY, ACCELERATION_PHILOSOPHY,
    HOOK_FIRST_RULES, WHY_IT_WORKS_RULES,
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

ACCELERATION_PHILOSOPHY: str = """\
══════════════════════════════════════
ACCELERATION PHILOSOPHY
══════════════════════════════════════
The feed should feel FAST-MOVING and INTELLECTUALLY EXCITING — not a slow online course.

GOOD progression (concepts CAN and SHOULD recur, but always evolving):
  Day 1: What is CAPM?
  Day 2: Why hedge funds moved beyond CAPM
  Day 3: How Renaissance Technologies models risk
  Day 4: AI-driven factor investing

BAD progression (never do this):
  Day 2: CAPM definition again

RULES:
  • Previously explored concepts MUST reappear at deeper framing, wider application, or real-world context — NEVER at the same surface level.
  • Connect today's content to prior days explicitly in learning_thread.
  • Introduce at least one suggested next topic naturally.
  • Each card must advance the curriculum — deeper, adjacent, or reinforcing with new angles.\""""

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
  • If a concept appears in explored_concepts, treat it as KNOWN — build on it, never re-explain it
  • One sentence of framing is enough before the insight lands
  • The implication always earns more space than the explanation
  • Speed through the "what" to arrive at the "why it's strange" and "what happens next\""""

WHY_IT_WORKS_RULES: str = """\
══════════════════════════════════════
WHY THIS WORKS — MANDATORY RULES
══════════════════════════════════════
The "why_it_matters" field is NOT a summary. It is a MECHANISM REVEAL.

It must answer ONE question: "What hidden mechanism causes this phenomenon?"

RULE: Every why_it_matters must expose one of:
  • A hidden leverage point (what small input drives a disproportionate output)
  • An invisible incentive structure (why actors behave the way they do, beneath the surface)
  • A causal chain the summary did not explain (A causes B causes C — and most people see only C)
  • A systemic behavior (how a feedback loop, constraint, or structural force produces the outcome)
  • A counterintuitive mechanism (the thing that sounds like it should work one way but actually works another)

LENGTH: 90–120 words. Never shorter. Never longer.
DENSITY: Every sentence must carry signal. Zero filler. Zero repetition of the summary.
STYLE: Expert annotation. The voice of someone who has worked inside the system.

WHAT "WHY THIS WORKS" IS NOT:
  ✗ A restatement of the article headline
  ✗ A definition of the topic
  ✗ A generic "this is important" wrap-up
  ✗ A second summary

BAD EXAMPLE:
  "FDA approvals are rigorous and require extensive clinical trials. This matters because it ensures medicines are safe and effective for patients around the world."
  (This is a topic description — it reveals no mechanism.)

GOOD EXAMPLE:
  "FDA approval functions as a global trust certificate, not a domestic regulation. Countries that lack their own robust inspection capacity use FDA approval as a proxy audit — they're outsourcing due diligence to a credible third party. This creates a structural asymmetry: Indian manufacturers selling into FDA-approved channels enjoy automatic trust in 60+ countries that would otherwise require independent audits. Lose FDA standing and you don't just lose US market access — you collapse the trust signal that underpins your entire international distribution network."
  (This exposes the mechanism: trust-certificate signaling, proxy auditing, the asymmetric value of a single approval.)\""""
