"""
Core Writing Instruction Pack
==============================
Single source of truth for Curivio's writing-quality directives:
  - Writing style standards (REDUCE / INCREASE / ENDING RULES)
  - Banned phrases (titles and summaries)
  - Strict URL rule
  - No-filler / ending rules

Canonical owners
----------------
WRITING_STYLE_STANDARDS  ← was project_insight_prompt.py (lines 426–469)
BANNED_PHRASES           ← was project_insight_prompt.py (lines 471–503)
STRICT_URL_RULE          ← was learning_prompt.py (line 16),
                            intelligence_prompt.py (line 11),
                            industry_intelligence_prompt.py (line 11)
                            — three independent near-identical copies
NO_FILLER_ENDING_RULE    ← was chat_prompt_service.py _NATURAL_GUIDELINES (line 441),
                            deep_research_prompt.py synthesis rules (line 125 variant),
                            project_insight_prompt.py ENDING RULES

Usage
-----
from ..instruction_packs.core_writing_pack import (
    WRITING_STYLE_STANDARDS, BANNED_PHRASES, STRICT_URL_RULE,
)
"""

# ── Atomic rules ─────────────────────────────────────────────────────────────

STRICT_URL_RULE: str = (
    "STRICT URL RULE: Only include URLs from the provided articles — "
    "never fabricate, guess, or hallucinate URLs. Use [] if no relevant URL exists."
)

NO_FILLER_ENDING_RULE: str = (
    "End when you've said the essential thing — "
    "no padding, no 'in summary' closers, no sentences that restate what was just said."
)


# ── Full sections ─────────────────────────────────────────────────────────────

WRITING_STYLE_STANDARDS: str = """\
══════════════════════════════════════
WRITING STYLE STANDARDS
══════════════════════════════════════
Write like: FT Alphaville, premium Substack analytical pieces, The Economist data briefings, expert analyst memos.

NOT like: Wikipedia summaries, course slides, or AI-generated educational content.

REDUCE:
  • "Understanding X is important because..."
  • "This highlights the importance of..."
  • "This plays a crucial role in..."
  • "This is a significant/major development..."
  • "X is a key concept in the field of..."
  • "X refers to the process of..."
  • "It is worth noting that..."
  • "transformative impact", "strategic importance", "innovation ecosystem", "economic advancement"
  • "advanced technology", "significant growth", "enhanced efficiency", "major transformation"
  • Excessive transition phrases and filler connectors
  • Definitions that belong in a glossary
  • Any closing sentence that summarizes what was just said

INCREASE:
  • Strategic framing ("The real tension here is...")
  • Named specifics with stakes ("When [Company] did X, the result was Y")
  • Counterintuitive observations backed by evidence
  • Expert-level asides and implications
  • Real-world consequences and market reactions

ENDING RULES — MANDATORY:
Never end a card with a generic educational close. Every card must end with SOMETHING AT STAKE.

BAD endings (never use):
  "Understanding X will be crucial for..."
  "As X continues to evolve, it will..."

GOOD endings (pick the form that fits the card's argument):
  Forward consequence:   "If this accelerates, [specific group] faces [specific risk or shift]."
  Unresolved tension:    "What remains unclear is whether [specific mechanism] survives [specific pressure]."
  Strategic implication: "[Actor] now holds a structural advantage — and most competitors haven't priced it in yet."
  Prediction with stakes: "The next 18 months will test whether [specific claim] holds when [specific condition] changes."
  Exposed contradiction:  "The uncomfortable implication is that [conventional wisdom] may be precisely wrong.\""""

BANNED_PHRASES: str = """\
══════════════════════════════════════
BANNED PHRASES — ZERO TOLERANCE
══════════════════════════════════════
These phrases make the feed sound AI-generated. If any appear, rewrite immediately.

BANNED IN TITLES:
  × "The Future of X"                      → "How X Is Quietly Rewiring Y"
  × "The Rise of X"                        → "Why X Took 20 Years to Become Inevitable"
  × "Hidden Drivers of X"                  → "The Structural Constraint Nobody Prices In"
  × "What's Changing in X"                 → "The Specific Rule Change That Shifted Everything"
  × "Unexpected Reason X"                  → "Why X Works Backwards from What the Model Predicts"
  × "What Surprised Experts"               → name the specific expert and the specific surprise
  × "The X Revolution"                     → "How X Broke One Industry Without Touching Another"
  × "Understanding X"                      → never use as a title or header
  × "Deep Dive Into X"                     → never use as a title or header
  × "The Power of X"                       → name the specific mechanism that creates the power
  × "X Explained"                          → name the specific mechanism that confuses people
  × "Everything You Need to Know About X"  → never use
  × "X: A Comprehensive Guide"             → never use

BANNED IN SUMMARIES AND EXPLANATIONS:
  × "In recent years, X has..."            → name the year and the specific event
  × "X is a rapidly evolving field"        → say what changed last quarter
  × "As X continues to grow..."            → specify the growth and what triggered it
  × "In today's world..."                  → never use
  × "X has become increasingly important"  → state WHY now, not that it's growing
  × "It is worth noting that..."           → delete; just say the thing
  × "This highlights the importance of..." → delete; state the implication directly
  × "X plays a crucial role in..."         → say what causal mechanism it activates
  × "transformative impact"               → name what specifically transformed
  × "innovation ecosystem"                → name the specific actors and their relationships
  × "strategic importance"                → state the strategic logic explicitly
  × "significant/major/key development"   → quantify it or name the specific consequence"""
