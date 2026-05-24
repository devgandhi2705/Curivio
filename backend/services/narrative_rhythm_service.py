"""
Dynamic Narrative Rhythm System.

Prevents "beautifully formatted sameness" — structurally repetitive AI responses
that feel homogeneous even when content is strong.

Rotates between 8 narrative modes, each with distinct pacing, opening style,
section order logic, and density target.  Mode selection is weighted by intent
alignment and anti-repetition: a mode used in the last 4 turns scores lower.

8 narrative modes
-----------------
analytical_memo        tight claim-first paragraphs; evidence follows verdict
investigative_breakdown open with the puzzle; build toward the explanation
strategic_briefing     bottom line first; forces, risks, decision
historical_narrative   causal arc through turning points to present
myth_busting           name the belief, destroy it, reveal what's actually true
systems_analysis       map actors + incentives + feedback loops + equilibrium
executive_summary      compressed; 3-4 paragraphs max; every word earns its place
causal_walkthrough     start with the effect; trace backward to root cause

Public API
----------
build_narrative_directive(session_id, intent_profile, domain, response_depth) -> str
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ── In-memory fingerprint store ───────────────────────────────────────────────
# Tracks recently used modes per session.  Lost on restart — acceptable for
# a development context; prevents same-mode repetition within a session.
_session_fingerprints: dict[str, list[str]] = {}
_FINGERPRINT_DEPTH = 4   # how many recent modes to remember per session


# ── Narrative mode directives ─────────────────────────────────────────────────

_MODES: dict[str, str] = {

    "analytical_memo": """\
NARRATIVE MODE: Analytical Memo
Open with a direct, declarative claim — the single most important insight. Not background context.
Paragraphs: 3–5 tight sentences each. Every sentence adds something new.
Structure: Claim → Evidence → Mechanism → Implication → Verdict.
If you use headers: only for 3+ genuinely distinct analytical sections.
Density target: compressed — cut anything that repeats what an earlier sentence already established.
Do NOT open with "This is a complex topic," "Background," or any framing paragraph.
Do NOT pad: the response ends when the essential point has been made.""",

    "investigative_breakdown": """\
NARRATIVE MODE: Investigative Breakdown
Open with the anomaly or puzzle — the thing that shouldn't be true given what we'd expect.
Structure: Surface paradox → Expected answer → Why the expected answer fails → Real explanation → Implication.
Pacing: expansive at the mystery (let the reader feel the puzzle), tight at the resolution.
Use a counterintuitive fact or a stated contradiction to hook the first sentence.
Do NOT answer the puzzle in the opening — build toward it.
Do NOT frame this as a list of facts. Frame it as a progression of understanding.""",

    "strategic_briefing": """\
NARRATIVE MODE: Strategic Briefing
Bottom line first: one sentence naming the strategic conclusion.
Structure: Verdict → Forces that produced it → Key risks or dependencies → Decision implication.
Tone: direct analyst memo to a decision-maker. Not academic. No hedging.
Short paragraphs. Name who wins, who loses, and what specifically changes the equation.
Do NOT build toward a conclusion — open with it and justify it afterward.
Do NOT use passive voice for strategic claims.""",

    "historical_narrative": """\
NARRATIVE MODE: Historical Narrative
Open with the turning point — the specific decision or moment that changed the trajectory.
Structure: Turning point → What led to it → How it unfolded → What it produced → Present implication.
Phases are defined by dominant dynamics, not dates.
Show causality explicitly: how earlier constraints shaped later outcomes.
End with: what this history reveals about how the domain operates today.
Do NOT open with "The history of X begins in [year]" or any chronological preamble.
Do NOT treat historical facts as self-explanatory — every event needs its mechanism.""",

    "myth_busting": """\
NARRATIVE MODE: Myth-Busting
Open by articulating the belief most people hold — without immediately attacking it.
Structure: The common view → Why it feels plausible → The specific assumption that fails → What's actually true → What believing the myth costs.
State the strongest version of the belief — never a strawman.
Be surgical: name the exact point where the logic breaks.
Do NOT open with "Actually," "Contrary to popular belief," or "Many people think."
Do NOT generalise the myth — name it precisely enough to be falsifiable.""",

    "systems_analysis": """\
NARRATIVE MODE: Systems Analysis
Open by identifying the key actors and what each is optimising for — not the outcome.
Structure: Actors and incentives → How they interact → Feedback loops that emerge → What holds the equilibrium → What specifically disrupts it.
Pacing: methodical. Build the system one layer at a time.
Name the incentive that produces each outcome — not just the outcome.
End with: the precise condition under which the system's behaviour changes.
Do NOT list actors without their incentives. Listing is not analysis.""",

    "executive_summary": """\
NARRATIVE MODE: Executive Summary
3–4 paragraphs maximum. Every word earns its place.
Structure: Core finding → Why it matters → Key risk or dependency → What to watch next.
No academic hedging. No historical context unless directly load-bearing.
The reader should have a complete picture in under 200 words.
Do NOT pad to appear thorough — brevity that covers everything beats length that fills space.
Do NOT use headers: if the structure requires labels, the paragraphs are too long.""",

    "causal_walkthrough": """\
NARRATIVE MODE: Causal Walkthrough
Open with the visible effect — the outcome we're trying to explain.
Structure: Effect → Proximate cause → Underlying mechanism → Root structural force → First-order implication → Second-order implication.
Name each causal link explicitly: "This happened BECAUSE… which led to… which produced…"
Every step: name the actor, the decision, or the structural force — not just what happened.
End with: the implication — what changes if one causal link were broken.
Do NOT open with the cause — start with the effect and trace backward.
Do NOT skip causal links: explain each transition, not just the endpoints.""",
}

_ALL_MODES = list(_MODES.keys())


# ── Intent → mode affinity (ordered: most to least natural fit) ───────────────

_INTENT_MODE_AFFINITY: dict[str, list[str]] = {
    "causal":      ["causal_walkthrough",   "investigative_breakdown", "systems_analysis"],
    "comparison":  ["analytical_memo",      "strategic_briefing",      "myth_busting"],
    "historical":  ["historical_narrative", "causal_walkthrough",      "investigative_breakdown"],
    "strategic":   ["strategic_briefing",   "analytical_memo",         "systems_analysis"],
    "research":    ["analytical_memo",      "systems_analysis",        "investigative_breakdown"],
    "prediction":  ["strategic_briefing",   "systems_analysis",        "analytical_memo"],
    "critique":    ["myth_busting",         "investigative_breakdown",  "analytical_memo"],
    "synthesis":   ["systems_analysis",     "analytical_memo",         "executive_summary"],
    "explanation": ["investigative_breakdown","causal_walkthrough",     "historical_narrative"],
    "default":     ["analytical_memo",      "strategic_briefing",      "investigative_breakdown"],
}

# Base score a mode gets for matching the primary intent (1st, 2nd, 3rd preference)
_AFFINITY_SCORES = [3.0, 2.0, 1.0]

# Penalty applied to modes used in the last N turns (decays with recency)
_RECENCY_PENALTIES = [3.5, 2.5, 1.5, 0.5]  # index 0 = most recent


# ── Domain → mode hints ────────────────────────────────────────────────────────
# Slight boosts for domain-mode combinations that tend to produce strong results.

_DOMAIN_MODE_BOOSTS: dict[str, list[str]] = {
    "pharmaceutical": ["systems_analysis",    "historical_narrative",  "myth_busting"],
    "ai":             ["causal_walkthrough",  "strategic_briefing",    "investigative_breakdown"],
    "finance":        ["systems_analysis",    "analytical_memo",       "strategic_briefing"],
    "technology":     ["causal_walkthrough",  "investigative_breakdown","analytical_memo"],
    "manufacturing":  ["systems_analysis",    "historical_narrative",  "causal_walkthrough"],
    "economics":      ["systems_analysis",    "myth_busting",          "historical_narrative"],
}

_DOMAIN_BOOST_SCORE = 0.8


# ── Depth → eligible modes ────────────────────────────────────────────────────
# Short executive_summary is appropriate for standard depth; the expansive modes
# suit detailed/research depth only.

_DEPTH_ELIGIBLE: dict[str, frozenset] = {
    "quick":    frozenset(),           # skip narrative for quick responses
    "standard": frozenset([
        "analytical_memo", "strategic_briefing",
        "myth_busting", "executive_summary", "causal_walkthrough",
    ]),
    "detailed": frozenset(_ALL_MODES),
    "research": frozenset(_ALL_MODES),
}


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def build_narrative_directive(
    session_id:     str,
    intent_profile: dict | None = None,
    domain:         str         = "",
    response_depth: str         = "standard",
) -> str:
    """
    Select a narrative mode and return its prompt directive.

    Returns an empty string for quick-depth responses (greetings, trivial
    factual lookups) where structural pacing directives are unnecessary.

    The selected mode is recorded in the session fingerprint immediately so
    the next call for the same session automatically avoids repeating it.
    """
    eligible = _DEPTH_ELIGIBLE.get(response_depth, _DEPTH_ELIGIBLE["standard"])
    if not eligible:
        return ""   # quick depth — skip entirely

    intent_profile = intent_profile or {}
    mode           = _select_mode(session_id, intent_profile, domain, eligible)

    if not mode:
        return ""

    _record_mode(session_id, mode)
    return _MODES[mode]


# ═══════════════════════════════════════════════════════════════════════════════
# Private helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _select_mode(
    session_id:     str,
    intent_profile: dict,
    domain:         str,
    eligible:       frozenset,
) -> str | None:
    """
    Score every eligible mode and return the highest-scoring one.

    Scoring:
      + intent affinity (3/2/1 for 1st/2nd/3rd preference)
      + domain boost (0.8 for top-3 domain modes)
      - recency penalty (3.5/2.5/1.5/0.5 for last 4 turns)
    """
    primary_intent = intent_profile.get("primary_intent", "default")
    affinity_list  = _INTENT_MODE_AFFINITY.get(primary_intent, _INTENT_MODE_AFFINITY["default"])
    domain_key     = _normalise_domain(domain)
    domain_boosts  = _DOMAIN_MODE_BOOSTS.get(domain_key, [])
    recent_modes   = _session_fingerprints.get(session_id, [])

    scores: dict[str, float] = {}

    for mode in _ALL_MODES:
        if mode not in eligible:
            continue
        score = 0.0

        # Intent affinity score
        if mode in affinity_list:
            rank = affinity_list.index(mode)
            score += _AFFINITY_SCORES[rank] if rank < len(_AFFINITY_SCORES) else 0.5

        # Domain boost
        if mode in domain_boosts:
            score += _DOMAIN_BOOST_SCORE

        # Recency penalty — heavier for more recently used.
        # recent_modes[-1] is most recent → reversed index 0 → highest penalty.
        if mode in recent_modes:
            recency_idx = recent_modes[::-1].index(mode)
            penalty     = _RECENCY_PENALTIES[recency_idx] if recency_idx < len(_RECENCY_PENALTIES) else 0.0
            score -= penalty

        scores[mode] = score

    if not scores:
        return None

    return max(scores, key=lambda m: scores[m])


def _record_mode(session_id: str, mode: str) -> None:
    history = _session_fingerprints.setdefault(session_id, [])
    history.append(mode)
    if len(history) > _FINGERPRINT_DEPTH:
        history.pop(0)


def _normalise_domain(domain: str) -> str:
    d = (domain or "").lower()
    if "pharma" in d:                              return "pharmaceutical"
    if "financ" in d or "bank" in d:              return "finance"
    if d == "ai" or "machine" in d or "intellig" in d: return "ai"
    if "manufact" in d:                            return "manufacturing"
    if "tech" in d or "software" in d or "comput" in d: return "technology"
    if "econ" in d or "trade" in d or "market" in d:   return "economics"
    return d
