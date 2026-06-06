"""
Core Curiosity Instruction Pack
=================================
Single source of truth for Curivio's curiosity and insight-quality directives:
  - Non-obvious insight generation principle
  - Key takeaway quality standards
  - Next-topic / follow-up quality standards
  - Counterintuitive framing

Canonical owners
----------------
KEY_TAKEAWAY_QUALITY_RULE  ← was chat_prompt_service.py _STRUCTURED_FORMAT_DIRECTIVE (lines 498–502)
NEXT_TOPICS_QUALITY_RULE   ← was chat_prompt_service.py _STRUCTURED_FORMAT_DIRECTIVE (lines 504–507)
NON_OBVIOUS_INSIGHT_RULE   ← implied across project_insight_prompt.py EDITORIAL PHILOSOPHY
                              and chat_prompt_service.py synthesis rules

Usage
-----
from ..instruction_packs.core_curiosity_pack import (
    KEY_TAKEAWAY_QUALITY_RULE, NEXT_TOPICS_QUALITY_RULE,
    NON_OBVIOUS_INSIGHT_RULE,
)
"""

# ── Atomic rules ─────────────────────────────────────────────────────────────

NON_OBVIOUS_INSIGHT_RULE: str = (
    "Every insight must be genuinely non-obvious — not a restatement of what "
    "the reader already knows. Surface the mechanism, tension, or hidden implication "
    "that most coverage skips."
)

COUNTERINTUITIVE_FIRST_PRINCIPLE: str = (
    "Lead with what's counterintuitive, surprising, or structurally hidden — "
    "not with what's already known."
)

CURIOSITY_GENERATION_PRINCIPLE: str = (
    "Curiosity content must feel like a discovery, not a mini-lesson. "
    "Open with a fact or claim that creates cognitive surprise. "
    "End with an unresolved tension or open question — not a neat conclusion."
)


# ── Full sections ─────────────────────────────────────────────────────────────

KEY_TAKEAWAY_QUALITY_RULE: str = """\
key_takeaways: 3-5 items maximum, each under 25 words
  — MUST be genuinely non-obvious insights — not summaries of the obvious
  — Each should reveal a mechanism, tension, implication, or hidden connection
  — "AI is growing fast" is NOT an insight. "China's API dominance gives it veto power over Indian pharma
    exports without direct political leverage" IS an insight."""

NEXT_TOPICS_QUALITY_RULE: str = """\
next_topics: 2-4 items — phrase as specific questions or angles, NOT generic topic names
  — BAD: "Learn more about APIs" | GOOD: "How API pricing power shapes pharma export margins"
  — Should feel like the natural next intellectual question — specific enough to be immediately interesting
  — Make them curiosity-inducing: the reader should think "yes, I want to know exactly that\""""
