"""
Semantic intent scoring engine.

Scores each message across 9 intent dimensions using weighted lexical signals.
Replaces single-category regex routing with a continuous score vector that
enables blended format composition for multi-intent prompts.

Public API
----------
score_intents(message: str) -> dict
"""

from __future__ import annotations
import re

# ── Secondary intent inclusion threshold ─────────────────────────────────────
_SECONDARY_THRESHOLD = 0.35

# ── Intent signal tables ──────────────────────────────────────────────────────
# Each entry: (compiled_pattern, weight)
# Strong ≈ 0.38–0.45, medium ≈ 0.18–0.28, weak ≈ 0.08–0.15
# Scores accumulate and are clamped to [0.0, 1.0].

_SIGNALS: dict[str, list[tuple[re.Pattern, float]]] = {

    "explanation": [
        (re.compile(r'\bwhat\s+(?:is|are|does|exactly)\b',        re.I), 0.38),
        (re.compile(r'\bexplain\b',                                re.I), 0.38),
        (re.compile(r'\bhow\s+does\s+\w+\s+work\b',               re.I), 0.38),
        (re.compile(r'\bdefinition\s+of\b',                        re.I), 0.38),
        (re.compile(r'\bteach\s+me\b',                             re.I), 0.32),
        (re.compile(r'\bwhat\s+makes\b',                           re.I), 0.22),
        (re.compile(r'\bhow\s+does\b',                             re.I), 0.22),
        (re.compile(r'\bhow\s+do\b',                               re.I), 0.16),
        (re.compile(r'\bmeaning\s+of\b',                           re.I), 0.22),
        (re.compile(r'\bunderstand\b',                             re.I), 0.11),
    ],

    "comparison": [
        (re.compile(r'\bvs\.?\b',                                  re.I), 0.42),
        (re.compile(r'\bversus\b',                                 re.I), 0.42),
        (re.compile(r'\bcompar\w*\b',                              re.I), 0.42),
        (re.compile(r'\bdifference[s]?\s+between\b',               re.I), 0.42),
        (re.compile(r'\bcontrast\b',                               re.I), 0.36),
        (re.compile(r'\boutperform\w*\b',                          re.I), 0.26),
        (re.compile(r'\bbetter\s+than\b',                          re.I), 0.26),
        (re.compile(r'\bworse\s+than\b',                           re.I), 0.26),
        (re.compile(r'\bwhereas\b',                                re.I), 0.26),
        (re.compile(r'\bunlike\b',                                 re.I), 0.22),
        (re.compile(r'\brelative\s+to\b',                          re.I), 0.16),
        # Implicit comparative constructions
        (re.compile(r'\bsucceed(?:ed|s)?\s+where\b',              re.I), 0.38),
        (re.compile(r'\bfail(?:ed|s)?\s+where\b',                 re.I), 0.38),
        (re.compile(r'\bstrug\w+\s+where\b',                      re.I), 0.38),
        (re.compile(r'\bwhile\s+\w+\s+(?:struggles|fails|succeeded|grew)\b', re.I), 0.22),
        (re.compile(r'\bdespite\s+(?:lower|higher|similar|less|more)\b', re.I), 0.24),
    ],

    "historical": [
        (re.compile(r'\bhistory\s+of\b',                           re.I), 0.42),
        (re.compile(r'\bevolution\s+of\b',                         re.I), 0.42),
        (re.compile(r'\btimeline\b',                               re.I), 0.38),
        (re.compile(r'\borigin[s]?\s+(?:of|behind)\b',             re.I), 0.38),
        (re.compile(r'\bhow\s+did\b',                              re.I), 0.28),
        (re.compile(r'\bwhen\s+did\b',                             re.I), 0.28),
        (re.compile(r'\bhistorical(?:ly)?\b',                      re.I), 0.26),
        (re.compile(r'\bover\s+the\s+(?:years|decades|time)\b',    re.I), 0.22),
        (re.compile(r'\bhow\s+(?:it\s+)?started\b',                re.I), 0.22),
        (re.compile(r'\btraditionally\b',                          re.I), 0.16),
        (re.compile(r'\bsince\s+the\s+\d{4}s?\b',                 re.I), 0.22),
        (re.compile(r'\bdecades\b',                                re.I), 0.11),
    ],

    "strategic": [
        (re.compile(r'\bstrateg\w*\b',                             re.I), 0.32),
        (re.compile(r'\bcompetitive\s+advantage\b',                re.I), 0.42),
        (re.compile(r'\bpositioning\b',                            re.I), 0.28),
        (re.compile(r'\bgeopolit\w*\b',                            re.I), 0.32),
        (re.compile(r'\bincentive[s]?\b',                          re.I), 0.22),
        (re.compile(r'\bmoat\b',                                   re.I), 0.28),
        (re.compile(r'\bbrand(?:ing|ed|s)?\b',                    re.I), 0.22),
        (re.compile(r'\bregulation[s]?\b',                         re.I), 0.22),
        (re.compile(r'\bcompetition\b',                            re.I), 0.22),
        (re.compile(r'\bdomin\w+\b',                               re.I), 0.16),
        (re.compile(r'\blandscape\b',                              re.I), 0.16),
        (re.compile(r'\bmarket\b',                                 re.I), 0.16),
        (re.compile(r'\bindustry\b',                               re.I), 0.14),
        (re.compile(r'\bsupply[\s\-]chain\b',                     re.I), 0.22),
        (re.compile(r'\binnovation\b',                             re.I), 0.16),
        (re.compile(r'\bspending\b',                               re.I), 0.11),
        (re.compile(r'\binvestment\b',                             re.I), 0.11),
        (re.compile(r'\boutlook\b',                                re.I), 0.16),
    ],

    "causal": [
        (re.compile(r'\bwhy\s+did\b',                              re.I), 0.42),
        (re.compile(r'\bwhy\s+(?:has|have|is|are|does|do)\b',     re.I), 0.36),
        (re.compile(r'\bdespite\b',                                re.I), 0.36),
        (re.compile(r'\balthough\b',                               re.I), 0.26),
        (re.compile(r'\beven\s+though\b',                          re.I), 0.32),
        (re.compile(r'\bcause[sd]?\s+by\b',                       re.I), 0.36),
        (re.compile(r'\breason\s+(?:for|behind|why)\b',            re.I), 0.36),
        (re.compile(r'\bled\s+to\b',                               re.I), 0.26),
        (re.compile(r'\bdrove\b',                                  re.I), 0.26),
        (re.compile(r'\bresult(?:ed|s)?\s+in\b',                  re.I), 0.26),
        (re.compile(r'\benabled\b',                                re.I), 0.22),
        (re.compile(r'\bprevented\b',                              re.I), 0.22),
        (re.compile(r'\bhow\s+come\b',                             re.I), 0.32),
        (re.compile(r'\bwhat\s+(?:caused|drove|enabled|led)\b',   re.I), 0.36),
        (re.compile(r'\bexplain\s+why\b',                          re.I), 0.42),
        (re.compile(r'\bwhy\b',                                    re.I), 0.14),
    ],

    "research": [
        (re.compile(r'\bdeep[\s\-]?dive\b',                        re.I), 0.48),
        (re.compile(r'\bin[\s\-]depth\b',                          re.I), 0.42),
        (re.compile(r'\bcomprehensive\b',                          re.I), 0.42),
        (re.compile(r'\beverything\s+about\b',                     re.I), 0.42),
        (re.compile(r'\bfull\s+(?:analysis|overview|report)\b',    re.I), 0.38),
        (re.compile(r'\bdeep\s+research\b',                        re.I), 0.48),
        (re.compile(r'\bdetailed\s+(?:analysis|breakdown)\b',      re.I), 0.32),
        (re.compile(r'\bthorough\b',                               re.I), 0.22),
        (re.compile(r'\bexhaustive\b',                             re.I), 0.32),
        (re.compile(r'\bresearch\b',                               re.I), 0.22),
    ],

    "prediction": [
        (re.compile(r'\bforecast\b',                               re.I), 0.42),
        (re.compile(r'\bpredict\w*\b',                             re.I), 0.42),
        (re.compile(r'\bfuture\s+of\b',                           re.I), 0.38),
        (re.compile(r'\boutlook\b',                                re.I), 0.32),
        (re.compile(r'\bwhere\s+(?:is|will)\s+\w+\s+(?:going|headed)\b', re.I), 0.32),
        (re.compile(r'\bnext\s+(?:\d+\s+)?(?:years?|decade)\b',   re.I), 0.32),
        (re.compile(r'\bby\s+20[2-5]\d\b',                        re.I), 0.26),
        (re.compile(r'\bwhat\s+(?:will|would|might)\s+happen\b',  re.I), 0.28),
        (re.compile(r'\btrend[s]?\b',                              re.I), 0.14),
    ],

    "critique": [
        (re.compile(r'\bflaw[s]?\b',                               re.I), 0.38),
        (re.compile(r'\bproblem[s]?\s+with\b',                    re.I), 0.38),
        (re.compile(r'\bcritici(?:se|ze|sm)\b',                   re.I), 0.42),
        (re.compile(r'\bcritique\b',                               re.I), 0.42),
        (re.compile(r'\blimitation[s]?\b',                         re.I), 0.32),
        (re.compile(r'\bweakness(?:es)?\b',                        re.I), 0.32),
        (re.compile(r"\bwhat(?:'s|\s+is)\s+wrong\b",              re.I), 0.38),
        (re.compile(r'\bshortcoming[s]?\b',                        re.I), 0.32),
        (re.compile(r'\bcounterargument\b',                        re.I), 0.38),
        (re.compile(r'\bdownside[s]?\b',                           re.I), 0.26),
        (re.compile(r'\bchallenge[s]?\b',                          re.I), 0.14),
    ],

    "synthesis": [
        (re.compile(r'\bimplication[s]?\b',                        re.I), 0.32),
        (re.compile(r'\bsignificance\b',                           re.I), 0.32),
        (re.compile(r'\btakeaway[s]?\b',                           re.I), 0.32),
        (re.compile(r'\bwhat\s+does\s+this\s+(?:mean|tell|reveal)\b', re.I), 0.42),
        (re.compile(r'\bbig\s+picture\b',                          re.I), 0.32),
        (re.compile(r'\bwhat\s+(?:can\s+we\s+learn|is\s+the\s+lesson)\b', re.I), 0.38),
        (re.compile(r'\boverall\b',                                re.I), 0.14),
        (re.compile(r'\bin\s+context\b',                           re.I), 0.14),
        (re.compile(r'\blesson[s]?\b',                             re.I), 0.26),
    ],
}


# ── Single-intent directives (new dimensions not in chat_prompt_service) ─────

_SINGLE_DIRECTIVES: dict[str, str] = {
    "causal": """\
FORMAT GUIDANCE — CAUSAL ANALYSIS:
The question asks WHY — start with the mechanism, not the outcome.
Trace backward from effect to root cause. Don't stop at the first explanation — ask what produced THAT.
Name actors, structural forces, and constraints specifically. Generic explanations fail.
Surface the counterintuitive: why did rational actors produce this outcome?
End with the implication: what does the causal logic reveal about what would change the outcome?""",

    "prediction": """\
FORMAT GUIDANCE — PREDICTIVE ANALYSIS:
Anchor predictions in current structural dynamics — not optimism or trend extrapolation.
Name the specific forces that would accelerate, decelerate, or reverse for different outcomes.
Surface where genuine uncertainty exists vs. where the trajectory is relatively clear.
A good prediction names the conditions under which it fails — that is what makes it useful.""",

    "critique": """\
FORMAT GUIDANCE — CRITICAL ANALYSIS:
Start with the strongest version of the position being critiqued. No strawmen.
Name specific flaws: which assumption fails? Where does evidence not support the claim?
Distinguish fatal flaws from superficial weaknesses.
End with the verdict: what does the critique change about how we should understand or use this?""",

    "synthesis": """\
FORMAT GUIDANCE — SYNTHESIS:
The goal is integration, not summary. What do the pieces reveal together that no single part shows?
Surface hidden connections, unexpected tensions, and emergent patterns.
The synthetic insight should be something you couldn't have said before seeing the whole picture.
End with the one load-bearing insight the rest of the answer supports.""",
}


# ── Blended pair directives ───────────────────────────────────────────────────

_D_CAUSAL_COMPARISON = """\
BLENDED INTENT — Causal + Comparative:
This is a WHY question framed comparatively. The comparison is a frame, not the destination.

Analytical arc:
→ Open with the asymmetry — state what actually differed in outcome, directly and specifically
→ Reject the surface explanation — the obvious first reason is usually a symptom; excavate one level
  deeper to the structural, economic, or incentive-based force that produced that symptom
→ For each side: explain the position — what made this path attractive or forced?
  What would have had to be different for the outcome to flip?
→ Causal verdict — not "A did better" but WHY the structural logic made A's outcome near-inevitable
  and what that reveals about how this domain actually works

Avoid the parallel-summary trap: "A did X, B did Y" is description. Name the MECHANISM."""

_D_CAUSAL_STRATEGIC = """\
BLENDED INTENT — Causal + Strategic:
Why did strategic outcomes unfold this way? Causality is the primary lens.

Analytical arc:
→ Name the strategic outcome concisely — what actually happened?
→ Trace the causal chain backward — what sequence of forces, decisions, or structural conditions
  produced this result?
→ Interrogate incentives — which actors were doing what they were supposed to do, and why did
  rational behaviour produce this collective outcome?
→ Strategic implication — what does the causal logic reveal about what would shift the equilibrium?
  Name the lever, not the vague opportunity."""

_D_CAUSAL_HISTORICAL = """\
BLENDED INTENT — Causal + Historical:
Causality traced through time — not just when events happened, but why they had to.

Analytical arc:
→ Identify the key inflection point — when the outcome became structurally more likely
→ Trace backward — what conditions, decisions, or forces made that inflection point possible?
→ Show path dependence — how did earlier choices constrain later options?
→ Extract the causal lesson — what does this history reveal about how this domain's logic works today?"""

_D_CAUSAL_SYNTHESIS = """\
BLENDED INTENT — Causal + Synthesis:
Understand why things work this way AND what that understanding means taken together.

Analytical arc:
→ Name the causal mechanism — the structural force that explains the outcome
→ Surface what the cause reveals — if THIS is the mechanism, what does that imply for adjacent phenomena?
→ Connect the threads — what looks unrelated is often the same mechanism in different contexts
→ The synthesis — not a summary of causes, but what they collectively reveal about the domain's
  underlying logic"""

_D_COMPARISON_STRATEGIC = """\
BLENDED INTENT — Comparative + Strategic:
Analyse structural differences across strategic dimensions — incentive structures and competitive
forces explaining why each subject occupies its position.

Analytical arc:
→ Structural differences — for each meaningful dimension: WHY does each subject occupy this position?
  Name the economic, regulatory, or competitive force behind it, not just the fact
→ Strategic incentives — which actors benefit from the current configuration?
  What makes incumbent positions durable or fragile?
→ Long-term implications — what does the structural divergence mean for competitive dynamics?
  Which advantage compounds and which erodes?
→ Verdict — name which side has the structural advantage, on what terms, with reasoning

Avoid: "A has X, B has Y" parallel summaries. The analysis must explain WHY, not list WHAT."""

_D_COMPARISON_HISTORICAL = """\
BLENDED INTENT — Comparative + Historical:
Understand how the subjects came to differ — comparison is most informative traced through history.

Analytical arc:
→ Historical roots — where did the divergence begin? What earlier conditions set each on a different path?
→ Key inflection points — when and why did the gap widen or narrow?
→ Current asymmetry — how much of the present state is structural vs. contingent on historical accident?
→ What the history reveals — not just what happened, but what this trajectory tells us about the
  domain's underlying dynamics"""

_D_COMPARISON_CRITIQUE = """\
BLENDED INTENT — Comparative + Critical:
Compare with critical depth — not "A vs B" but which claims about the comparison hold up under scrutiny.

Analytical arc:
→ The strongest version of each position — no strawmen
→ Where the conventional comparison misleads — which differences are overstated, which similarities
  are underweighted?
→ The real asymmetry — after stripping away surface differences, what actually distinguishes them?
→ Verdict with caveats — who wins on what terms, and where the answer genuinely depends on
  contested assumptions"""

_D_STRATEGIC_HISTORICAL = """\
BLENDED INTENT — Strategic + Historical:
Current strategic dynamics make most sense when traced to historical roots.

Analytical arc:
→ The structural landscape today — current competitive configuration, briefly
→ Historical forces that shaped it — which decisions or events created today's dynamics?
  Name turning points with their causal logic, not just trends
→ What persists vs. what changed — which historical forces still operate today as active constraints?
→ Strategic outlook — given the historical trajectory, which forces will produce further change
  and which will maintain the current equilibrium?"""

_D_STRATEGIC_PREDICTION = """\
BLENDED INTENT — Strategic + Predictive:
Where are the strategic dynamics heading? Anchor predictions in structural forces, not trends.

Analytical arc:
→ Current structural configuration — the forces that maintain the present equilibrium
→ Pressures on that equilibrium — which dynamics are building toward change?
→ Conditional predictions — what happens if X accelerates? What if Y resolves?
  Name the conditions, not just the outcomes
→ Where genuine uncertainty lives — which assumptions, if wrong, change the prediction most?"""

_D_RESEARCH_SYNTHESIS = """\
BLENDED INTENT — Research + Synthesis:
Comprehensive coverage AND integrative understanding — not just what we know, but what it means together.

Analytical arc:
→ Core mechanisms — fundamental forces at work, named specifically
→ Multiple perspectives — where do credible viewpoints diverge? Surface disagreements explicitly
→ What comprehensive coverage reveals — what isolated views miss when you look across the whole picture
→ Synthesis — not a summary of sources but a constructed argument about what this all means and
  what the most important insight is"""

_D_RESEARCH_CRITIQUE = """\
BLENDED INTENT — Research + Critical:
Comprehensive review with critical depth — cover the field AND assess what holds up.

Analytical arc:
→ What we know — the established consensus with its strongest evidence
→ What's contested — where expert views diverge and why; name the core disagreement
→ What's underweighted — what does conventional coverage miss or paper over?
→ Implications of the critique — what should change about how we understand or use this knowledge?"""

_D_CRITIQUE_SYNTHESIS = """\
BLENDED INTENT — Critical + Synthesis:
Critique with integrative purpose — not just what's wrong but what the critique reveals about the whole.

Analytical arc:
→ The strongest version of what's being critiqued — no strawmen
→ The specific failure — which assumption, evidence gap, or logical problem underlies the flaw?
→ What the critique reveals — if this is wrong, what does that imply about adjacent claims or frameworks?
→ The revised understanding — not just "X is flawed" but the more accurate picture given the failure"""

_D_PREDICTION_HISTORICAL = """\
BLENDED INTENT — Predictive + Historical:
Use historical patterns to calibrate predictions — the future is most readable through historical analogy.

Analytical arc:
→ The historical pattern — when has this type of situation occurred before? What happened?
→ Structural similarities and differences — how closely does the current situation match precedents?
  Where do the analogies break down?
→ What history predicts vs. where it's silent — which aspects have historical guidance, which are novel?
→ The calibrated forecast — grounded in historical base rates, with explicit uncertainty"""


# ── Triple-intent directives ──────────────────────────────────────────────────

_D_CAUSAL_COMPARISON_STRATEGIC = """\
BLENDED INTENT — Causal + Comparative + Strategic:
WHY did outcomes diverge across strategic dimensions? The comparison frames the question;
causality is the engine; strategic context explains the forces.

Analytical arc:
→ State the divergence directly — what actually happened differently? Name the specific asymmetry
→ Reject surface explanations — the first obvious answer is usually a symptom; trace one level
  deeper to the structural root: what drove that symptom? Follow the incentives, not the headlines
→ Strategic forces — which actors rationally produced this outcome pursuing their own interests?
  What structural constraints made alternative paths difficult or impossible?
→ Competitive implications — what does the causal logic reveal about the durability of the current
  strategic configuration? What specific force would change it?
→ Verdict with reasoning — name which side has the structural advantage, why, and what would have
  to change for the conclusion to flip

Every claim should name a mechanism, not just an outcome."""

_D_CAUSAL_COMPARISON_HISTORICAL = """\
BLENDED INTENT — Causal + Comparative + Historical:
Why did these subjects diverge historically? Trace the causal arc across time.

Analytical arc:
→ Historical point of divergence — when did the trajectories split and what triggered the split?
→ Causal engine — what structural force or constraint drove each subject down its path?
  Why did the divergence compound rather than correct?
→ Path dependence — how did earlier choices close off alternatives for each subject?
→ Current asymmetry as result — the present state IS this history; explain how past causality
  produced today's comparative position
→ What would change it — given the causal logic, what force would actually alter the trajectory?"""

_D_CAUSAL_STRATEGIC_HISTORICAL = """\
BLENDED INTENT — Causal + Strategic + Historical:
Why do current strategic dynamics exist? Trace their causal and historical roots.

Analytical arc:
→ Current strategic state — the configuration that needs explaining
→ Historical forces that created it — which decisions or structural shifts set the trajectory?
  Name the turning points with their causal logic
→ Why rational actors maintained the current equilibrium — what incentives or constraints explain
  why this persisted rather than correcting?
→ Strategic implications — given the historical-causal understanding, which forces will sustain or
  disrupt the current configuration? Name the specific lever, not the vague trend"""


# ── Pair directive lookup (primary-first keying with mirror entries) ──────────

_PAIR_DIRECTIVES: dict[tuple[str, str], str] = {
    ("causal",      "comparison"):  _D_CAUSAL_COMPARISON,
    ("comparison",  "causal"):      _D_CAUSAL_COMPARISON,
    ("causal",      "strategic"):   _D_CAUSAL_STRATEGIC,
    ("strategic",   "causal"):      _D_CAUSAL_STRATEGIC,
    ("causal",      "historical"):  _D_CAUSAL_HISTORICAL,
    ("historical",  "causal"):      _D_CAUSAL_HISTORICAL,
    ("causal",      "synthesis"):   _D_CAUSAL_SYNTHESIS,
    ("synthesis",   "causal"):      _D_CAUSAL_SYNTHESIS,
    ("comparison",  "strategic"):   _D_COMPARISON_STRATEGIC,
    ("strategic",   "comparison"):  _D_COMPARISON_STRATEGIC,
    ("comparison",  "historical"):  _D_COMPARISON_HISTORICAL,
    ("historical",  "comparison"):  _D_COMPARISON_HISTORICAL,
    ("comparison",  "critique"):    _D_COMPARISON_CRITIQUE,
    ("critique",    "comparison"):  _D_COMPARISON_CRITIQUE,
    ("strategic",   "historical"):  _D_STRATEGIC_HISTORICAL,
    ("historical",  "strategic"):   _D_STRATEGIC_HISTORICAL,
    ("strategic",   "prediction"):  _D_STRATEGIC_PREDICTION,
    ("prediction",  "strategic"):   _D_STRATEGIC_PREDICTION,
    ("research",    "synthesis"):   _D_RESEARCH_SYNTHESIS,
    ("synthesis",   "research"):    _D_RESEARCH_SYNTHESIS,
    ("research",    "critique"):    _D_RESEARCH_CRITIQUE,
    ("critique",    "research"):    _D_RESEARCH_CRITIQUE,
    ("critique",    "synthesis"):   _D_CRITIQUE_SYNTHESIS,
    ("synthesis",   "critique"):    _D_CRITIQUE_SYNTHESIS,
    ("prediction",  "historical"):  _D_PREDICTION_HISTORICAL,
    ("historical",  "prediction"):  _D_PREDICTION_HISTORICAL,
}


# ── Public API ────────────────────────────────────────────────────────────────

def score_intents(message: str) -> dict:
    """
    Score a message across 9 intent dimensions.

    Returns
    -------
    {
        "intent_scores":     {dim: score, ...}  # all dims with score > 0.05, desc order
        "primary_intent":    str                # highest-scoring dimension
        "secondary_intents": list[str]          # dims with score >= _SECONDARY_THRESHOLD
        "blended_format":    bool               # True when secondary_intents is non-empty
        "composed_directive": str               # ready-to-inject structural guidance
    }
    """
    msg = message.strip()

    scores: dict[str, float] = {}
    for dim, signals in _SIGNALS.items():
        raw = sum(w for pat, w in signals if pat.search(msg))
        scores[dim] = min(raw, 1.0)

    significant = {k: round(v, 3) for k, v in scores.items() if v > 0.05}
    if not significant:
        return {
            "intent_scores":     {},
            "primary_intent":    "default",
            "secondary_intents": [],
            "blended_format":    False,
            "composed_directive": "",
        }

    sorted_dims = sorted(significant.items(), key=lambda x: x[1], reverse=True)
    primary       = sorted_dims[0][0]
    secondaries   = [d for d, s in sorted_dims[1:] if s >= _SECONDARY_THRESHOLD]
    blended       = bool(secondaries)
    composed      = _compose_directive(primary, secondaries) if blended else _SINGLE_DIRECTIVES.get(primary, "")

    return {
        "intent_scores":     dict(sorted_dims),
        "primary_intent":    primary,
        "secondary_intents": secondaries,
        "blended_format":    blended,
        "composed_directive": composed,
    }


# ── Private helpers ───────────────────────────────────────────────────────────

def _compose_directive(primary: str, secondaries: list[str]) -> str:
    """Select the most specific blended directive for the intent combination."""
    top = set([primary] + secondaries[:2])

    # Triple combinations (check first for specificity)
    if top >= {"causal", "comparison", "strategic"}:
        return _D_CAUSAL_COMPARISON_STRATEGIC
    if top >= {"causal", "comparison", "historical"}:
        return _D_CAUSAL_COMPARISON_HISTORICAL
    if top >= {"causal", "strategic", "historical"}:
        return _D_CAUSAL_STRATEGIC_HISTORICAL

    # Pair combinations — primary + first secondary
    first_secondary = secondaries[0] if secondaries else ""
    pair = _PAIR_DIRECTIVES.get((primary, first_secondary))
    if pair:
        return pair

    # Fall back to single-intent directive
    return _SINGLE_DIRECTIVES.get(primary, "")
