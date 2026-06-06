"""
Package Narrative Instruction Pack
=====================================
Narrative frames, tones, title patterns, editorial roles, and section assembly instructions
for the daily package generation prompt.

Canonical owners
----------------
NARRATIVE_FRAMES          — was project_insight_prompt.py (inline, lines 294–310)
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
    NARRATIVE_FRAMES, EMOTIONAL_TONE_PALETTE, TITLE_STYLE_LIBRARY,
    EDITORIAL_ROLES, PACKAGE_COMPOSITION, ARTICLE_MIX, SECTION_1_INSTRUCTIONS,
)
section1 = SECTION_1_INSTRUCTIONS.format(count=count, project_name=name, difficulty=diff)
"""

NARRATIVE_FRAMES: str = """\
══════════════════════════════════════
NARRATIVE FRAME LIBRARY  ← MANDATORY
══════════════════════════════════════
Each core card MUST use exactly ONE of these editorial frames.
Different cards in the same package MUST use different frames.
The frame determines the card's narrative structure and angle.

INVESTIGATIVE — Expose the mechanism or cause others miss; start with what's hidden. ("The real reason behind X is...")
FUTURE-FOCUSED — Frame around what's coming; build forward tension around an emerging shift. ("What's about to change — and why it matters now...")
STORY-DRIVEN — Ground the insight in a specific story, company decision, or turning point. ("It started when [actor] decided...")
STRATEGIC ANALYSIS — Expose competing forces, underappreciated risks, or the real incentive structure. ("The hidden tradeoff between X and Y...")
TREND ACCELERATION — Connect a structural trend to recent events forcing it into the mainstream. ("This was always true — but now it's becoming urgent because...")
MARKET SHIFT — Frame around how competitive dynamics, business models, or industry economics shifted. ("The rules changed when...")
PRACTICAL IMPLEMENTATION — Show the gap between theory and practice; real-world friction from inside. ("The gap between theory and practice here is...")
FOUNDER/OPERATOR VIEW — The practitioner's perspective: what's different when you're actually doing it. ("From the inside, the hardest part is...")
CONTROVERSY/FAILURE — Use a failure, controversy, or widely-held misconception as the entry point. ("The experiment everyone cites — and what they get wrong about it...")
HIDDEN SYSTEMS — Surface an invisible mechanism, incentive, or infrastructure shaping outcomes. ("The thing quietly driving X that almost no one talks about...")\""""

EMOTIONAL_TONE_PALETTE: str = """\
══════════════════════════════════════
EMOTIONAL TONE PALETTE  ← MANDATORY
══════════════════════════════════════
Each card must carry a distinct emotional weight. The feed must feel TONALLY VARIED — not uniformly analytical.

Assign one of these tones to each card before writing. No two consecutive cards share the same tone.
The full package must cycle through at least 4–5 distinct tones:

  SHOCKING      — challenges a widely-held assumption. Reader thinks: "Wait, that's actually true?"
  OPTIMISTIC    — surfaces an unexpected positive development most aren't tracking.
  UNSETTLING    — exposes a risk, fragility, or problem that most people are not taking seriously.
  STRATEGIC     — gives the reader a competitive edge or decision-making frame.
  VISIONARY     — connects current signals to a bigger structural shift still taking shape.
  INVESTIGATIVE — exposes the real cause or hidden actor behind a visible outcome.
  PROVOCATIVE   — makes a claim that will make the reader want to argue back — and then realize you're right.
  PRACTICAL     — "here is what this means for someone actually doing the work" — grounded, operational.
  MYSTERIOUS    — something strange happened, and the full explanation is not what anyone expected.\""""

TITLE_STYLE_LIBRARY: str = """\
══════════════════════════════════════
TITLE STYLE LIBRARY — ROTATE MANDATORY
══════════════════════════════════════
Every title MUST fit one of these 9 structural patterns.
Different cards in the same package MUST use different patterns.
Check the "Recent card titles" list above and avoid repeating the same pattern type.

1. MYTH-BUSTING
   Structure: Challenge a widely-held assumption directly.
   Example: "Why India's Pharma 'Quality Problem' Is Actually a Regulatory Strategy"

2. CONTRADICTION
   Structure: Name two things that should be in tension but aren't — or should align but don't.
   Example: "Why Pharma Supply Chains Are Strongest Where Regulation Is Weakest"

3. HIDDEN DEPENDENCY
   Structure: Expose what an outcome is actually contingent on, which the standard story misses.
   Example: "India's $27B Export Machine Runs on a Single US Approval Cycle"

4. ECONOMIC LEVERAGE
   Structure: Surface the specific economic mechanism that creates disproportionate power or return.
   Example: "The 3% Margin That Controls 40% of Global Generic Supply"

5. HISTORICAL COMPARISON
   Structure: Use a past event to sharpen understanding of the present.
   Example: "The 1998 FDA Inspection Blitz That Shaped Everything India Exports Today"

6. GEOPOLITICAL TENSION
   Structure: Surface the political-economic constraint or competition reshaping a domain.
   Example: "Why China's API Dominance Is a Problem India Can't Solve Through Manufacturing"

7. OPERATIONAL FAILURE
   Structure: Use a specific failure as the lens for understanding how a system works.
   Example: "The Ranbaxy Collapse That Rewrote How the FDA Inspects Foreign Plants"

8. STRATEGIC MOAT
   Structure: Identify the specific structural advantage that incumbents hold (or are losing).
   Example: "Why Cipla's 30-Year Generics Lead Is Harder to Replicate Than It Looks"

9. INVISIBLE INFRASTRUCTURE
   Structure: Surface the hidden system, platform, or network that quietly enables a visible outcome.
   Example: "The API Supplier Database That Controls Access to 80% of Global Generics"\""""

EDITORIAL_ROLES: str = """\
INTERNAL EDITORIAL PLANNING (do NOT include in output):
Before writing any card, assign each an editorial role AND an emotional tone from the palette above.

Editorial roles — each package needs these represented:
  CENTERPIECE      — the anchor story. Most depth, highest insight density. Carries the day's thesis.
  PRACTICAL INTEL  — what a practitioner does differently after reading this. Operational, grounded.
  FAST SIGNAL      — crisp, news-driven, high-stakes. Short and sharp — one claim, clearly stated.
  FUTURE PREDICTION — forward-looking tension. What shifts next and who feels it first.
  STRATEGIC SHIFT  — how competitive dynamics, business models, or incentive structures changed.
  WILD CARD        — the card that surprises. Unexpected angle, cross-domain leap, or hidden system.\""""

# Template — call .format(count=count) before injecting.
PACKAGE_COMPOSITION: str = """\
PACKAGE COMPOSITION RULES:
  • Open with the highest-energy card (SHOCKING or INVESTIGATIVE tone) — hook the reader immediately
  • Place PRACTICAL INTEL in the middle — grounding after conceptual intensity
  • End the core section with FUTURE PREDICTION — leaving the reader with forward tension
  • The two curiosity cards continue the emotional or thematic thread from the core section
  • Escalate complexity: accessible hook → deeper mechanism → most sophisticated insight → forward tension

The package must feel like a deliberate intellectual journey — not {count} independent blocks.\""""

ARTICLE_MIX: str = """\
ARTICLE MIX FOR CORE CARDS (target distribution):
  • 1–2 reinforcement/evolution cards: revisit prior concepts at higher sophistication
  • 2–3 new progression cards: introduce suggested next topics and adjacent ideas
  • 1 real-world/news card: current event, trend, or recent development
  • 1 practical/case-study card: implementation story, company story, applied example\""""

# Template — call .format(count=count, project_name=..., difficulty=...) before injecting.
# "Assume the user knows the basics. Skip definitions." is already in EDITORIAL_PHILOSOPHY.
SECTION_1_INSTRUCTIONS: str = """\
SECTION 1 — "insights" array  (EXACTLY {count} CORE LEARNING cards)
  • Use CORE articles as primary sources. Synthesise across multiple sources.
  • content_type: "news" for current events/developments, "educational" for durable concepts.
  • narrative_frame: MUST be one of the 10 frames from the Narrative Frame Library above.
  • Titles must be specific and compelling — ≤ 12 words, never generic.
    BAD: "Understanding Neural Networks in Finance"
    GOOD: "Why Neural Networks Overfit — and What Quants Actually Do About It"
  • Each title MUST use one of the 9 structural patterns from TITLE STYLE LIBRARY above.
    Different cards in the same package MUST use different pattern types.
    Compare against the "Recent card titles" list — reject any title structurally similar to a recent one.
  • Never use banned phrases from BANNED PHRASES section above.
  • summary: 2–3 sentences structured as HOOK → INSIGHT. Not a definition summary.
  • educational_explanation: 4–6 sentences following INSIGHT → EVIDENCE → IMPLICATION.
    Surface what's non-obvious. Build on the hook — do not re-explain the summary.
  • Reflect {difficulty} conceptual depth — avoid glossary-level content.
  • Cards must feel tightly scoped to {project_name}, not generic commentary.
  • Each card must use a DIFFERENT narrative frame.\""""
