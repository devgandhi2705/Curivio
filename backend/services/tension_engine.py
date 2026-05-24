"""
Cognitive Tension Engine.

Prevents flat informational responses by generating targeted intellectual
friction directives. Every complex analytical response receives a tension
directive specifying which tension types to surface and how.

Tension types (7 dimensions):
  contradiction      — two true things that appear to conflict
  hidden_dependency  — what the "winner" depends on it cannot control
  invisible_incentive — why rational actors produced this outcome
  paradox            — something that is simultaneously its own opposite
  strategic_tradeoff — the real cost of the dominant position
  systemic_weakness  — where today's strength becomes tomorrow's vulnerability
  future_instability — the specific force currently building toward disruption

Public API
----------
build_tension_directive(message, intent_profile, domain, conv_state, mode) → str
score_tension(response_text)                                               → dict
"""

from __future__ import annotations

import re

# ── Tension type definitions ──────────────────────────────────────────────────
# Each entry: directive text injected into the prompt.

_TENSION_DIRECTIVES: dict[str, str] = {
    "contradiction": (
        "CONTRADICTION: Name two true things that appear to conflict. "
        "Don't resolve the tension — explain what structural logic makes both simultaneously true. "
        "The contradiction IS the insight. "
        'BAD: "India dominates exports." '
        'GOOD: "India dominates exports, yet captures far less pharma profit than the US — '
        "the scale advantage and the value capture problem are structurally connected.\""
    ),
    "hidden_dependency": (
        "HIDDEN DEPENDENCY: Identify what the winner, leader, or success story depends on that it "
        "does not fully control. The hidden dependency is the ceiling that the surface narrative ignores. "
        "Name the specific supply chain, institution, or actor that holds the upstream leverage."
    ),
    "invisible_incentive": (
        "INVISIBLE INCENTIVE: Name why rational actors chose paths that produced this outcome. "
        "The surprising result is usually not incompetence — it is the logical product of incentives "
        "the surface narrative misses. Identify who was doing exactly what they were supposed to do, "
        "and why that produced this collective outcome."
    ),
    "paradox": (
        "PARADOX: Surface a genuine paradox — something that appears to be its own opposite, "
        "or where the solution creates the problem it was meant to solve. "
        "Do not paper over it. Acknowledge what no simple framework currently resolves."
    ),
    "strategic_tradeoff": (
        "STRATEGIC TRADEOFF: Name the real cost of the dominant position. "
        "Every strategic advantage was purchased with a specific sacrifice. "
        "Identify what was given up, who bears that cost, and when it will be called."
    ),
    "systemic_weakness": (
        "SYSTEMIC WEAKNESS: Identify where today's strength becomes tomorrow's vulnerability. "
        "The most dangerous weaknesses are structural — embedded in the mechanism of the strength "
        "itself, not visible from outside. Name the specific scenario that converts the strength."
    ),
    "future_instability": (
        "FUTURE INSTABILITY: Name the specific force currently building that will disrupt the "
        "current equilibrium. Not a vague 'things will change' — name the mechanism, the timeline "
        "signal, and who it threatens most when it arrives."
    ),
}

# ── Domain-specific tension hints (appended to directive when domain matches) ─

_DOMAIN_HINTS: dict[str, dict[str, str]] = {
    "contradiction": {
        "pharmaceutical": (
            "India manufactures for global health access yet profits far less than the US companies "
            "whose markets it supplies — the access mission and the value capture gap are linked."
        ),
        "ai": (
            "Foundation models democratize AI capability while concentrating power in the labs "
            "that control training infrastructure — the same technology that democratizes also centralises."
        ),
        "finance": (
            "Markets are simultaneously efficient (making consistent alpha impossible) and exploitable "
            "(making sustained alpha real) — address what makes both simultaneously true."
        ),
    },
    "hidden_dependency": {
        "pharmaceutical": (
            "Indian generic export strength requires Chinese API supply — the upstream constraint "
            "on downstream success. India's biggest export strength sits on inputs it does not control."
        ),
        "ai": (
            "Model performance depends on training data quality and volume — who controls the data "
            "pipeline controls the effective ceiling on what any downstream model can achieve."
        ),
        "manufacturing": (
            "Supply chain efficiency depends on just-in-time components from suppliers who may be "
            "geopolitical adversaries — concentration risk is invisible during stability."
        ),
    },
    "invisible_incentive": {
        "pharmaceutical": (
            "FDA compliance wasn't chosen as branding — it was forced by market access requirements. "
            "The trust signal was an unintended byproduct of a regulatory hurdle, not a strategic choice."
        ),
        "finance": (
            "Financial intermediaries are paid to trade, not to generate returns — incentive alignment "
            "with client outcomes is the exception, not the structural default."
        ),
        "ai": (
            "AI labs publish research and open-source models not from altruism but because talent "
            "recruitment, standards-setting power, and regulatory goodwill all reward openness "
            "even when it costs competitive advantage."
        ),
    },
    "strategic_tradeoff": {
        "pharmaceutical": (
            "Regulatory compliance investment vs. R&D innovation — the resources spent maintaining "
            "FDA trust are resources not spent on proprietary drug pipelines."
        ),
        "ai": (
            "Scale vs. efficiency — larger models perform better but become economically deployable "
            "only at inference scale that few actors can sustain."
        ),
    },
    "systemic_weakness": {
        "pharmaceutical": (
            "Volume leadership in generics creates price transparency that compresses margins — "
            "the scale advantage that enables market dominance is the same force that "
            "prevents premium pricing."
        ),
        "ai": (
            "Current model architectures require exponentially increasing compute for linear capability "
            "gains — the growth trajectory that created the current leaders is the same one that "
            "makes their position economically fragile."
        ),
    },
    "future_instability": {
        "pharmaceutical": (
            "AI-driven compliance automation threatens to commoditize the FDA trust moat — "
            "if regulatory compliance becomes cheap and fast, what replaces it as the "
            "competitive barrier protecting Indian generic exporters?"
        ),
        "ai": (
            "Current compute economics and data moats favour incumbents — but hardware "
            "efficiency improvements and synthetic data generation could rapidly erode both, "
            "within a single product generation cycle."
        ),
        "finance": (
            "Carry trades and leverage cycles work until the correlation breakdown — "
            "the specific trigger (central bank pivot, credit event, geopolitical shock) "
            "is unknowable, but the mechanism is structural."
        ),
    },
    "paradox": {
        "pharmaceutical": (
            "The companies that develop the drugs that save lives capture most of the economic value, "
            "while the companies that make them accessible at scale capture little — "
            "patent law makes both facts simultaneously necessary."
        ),
        "ai": (
            "The more capable AI becomes at creative tasks, the more valuable original human "
            "creativity becomes — the substitution effect and the complementarity effect "
            "operate at the same time in the same market."
        ),
    },
}

# ── Open loop endings per tension type ───────────────────────────────────────

_OPEN_LOOP_ENDINGS: dict[str, str] = {
    "contradiction": (
        "End with the contradiction this analysis reveals but does not resolve. "
        "Phrase it as a direct tension, not a question with an implied answer."
    ),
    "hidden_dependency": (
        "End with what happens when the hidden dependency is disrupted — "
        "what breaks first, and who loses most? Frame it as an emerging risk, not a prediction."
    ),
    "invisible_incentive": (
        "End with what happens when the invisible incentive changes — "
        "whose behaviour shifts, and which apparent strength evaporates?"
    ),
    "paradox": (
        "Leave the paradox genuinely unresolved. Acknowledge what current frameworks "
        "do not explain, and why that gap is intellectually important."
    ),
    "strategic_tradeoff": (
        "End with the specific decision point that has not yet been made — "
        "the tradeoff that is still open, phrased as what choosing either path would cost."
    ),
    "systemic_weakness": (
        "End by naming the specific scenario — not the vague possibility — "
        "that converts the strength into a liability. What would have to be true for it to happen?"
    ),
    "future_instability": (
        "End with the specific force currently building. Not 'things may change' — "
        "name the mechanism, the earliest visible signal of it arriving, and "
        "who loses most when it does."
    ),
}

# ── Tension framing rules (injected for all analytical responses) ─────────────

_FRAMING_RULES = """\
TENSION FRAMING RULES:
- State facts as tensions, not conclusions:
  BAD:  "India dominates generic exports."
  GOOD: "India dominates generic exports, yet captures far less pharmaceutical profit than the US — the competitive strength and the value capture problem are structurally linked."
- Every major strength should carry its shadow: what is the cost? Who loses for this to be true?
- Name the non-obvious mechanism: what invisible structural force makes this outcome surprising?
- Earn the reader's surprise: the most valuable sentence is the one they didn't see coming.
- Avoid hedged generalities: "there are trade-offs" is noise. Name the specific trade-off."""

_OPEN_LOOP_HEADER = """\
OPEN LOOP (mandatory for analytical responses):
End with ONE specific unresolved question or emerging risk — the single most intellectually alive thing this analysis leaves open."""

# ── Intent → tension type mapping ────────────────────────────────────────────

_INTENT_TENSION_MAP: dict[str, list[str]] = {
    "causal":      ["hidden_dependency", "invisible_incentive", "contradiction"],
    "comparison":  ["contradiction",     "strategic_tradeoff",  "systemic_weakness"],
    "historical":  ["contradiction",     "systemic_weakness",   "invisible_incentive"],
    "strategic":   ["strategic_tradeoff","invisible_incentive", "future_instability"],
    "research":    ["hidden_dependency", "contradiction",       "systemic_weakness"],
    "prediction":  ["future_instability","strategic_tradeoff",  "paradox"],
    "critique":    ["systemic_weakness", "hidden_dependency",   "contradiction"],
    "synthesis":   ["paradox",           "strategic_tradeoff",  "contradiction"],
    "explanation": [],  # simple explanations rarely need tension forcing
}

# ── Priority ordering for de-duplication and capping ─────────────────────────

_PRIORITY_ORDER = [
    "contradiction",
    "hidden_dependency",
    "invisible_incentive",
    "strategic_tradeoff",
    "systemic_weakness",
    "future_instability",
    "paradox",
]

# ── Scoring signal tables ─────────────────────────────────────────────────────

_CONTRAST_RE = re.compile(
    r'\b(yet\b|despite|however|paradoxically|counterintuitively|although|'
    r'even though|on the other hand|but [a-z]+ actually|'
    r'surprisingly|at the same time)\b',
    re.I,
)
_QUESTION_RE  = re.compile(r'\?', re.I)
_MECHANISM_RE = re.compile(
    r'\b(mechanism|incentive|structural|dependency|moat|leverage|'
    r'equilibrium|constraint|upstream|downstream|tradeoff|trade.off|'
    r'vulnerability|fragile|asymmetr\w+|invisible|underlying)\b',
    re.I,
)
_HIDDEN_RE = re.compile(
    r'\b(invisible|hidden|underlying|root cause|structural|'
    r'misalign\w+|unintended|byproduct|side effect|second.order|'
    r'counter.intuitive|non.obvious|not obvious)\b',
    re.I,
)

# Trivial-message signals
_GREETING_TOKENS = frozenset(
    "hi hey hello thanks thank bye goodbye ok okay cool noted lol "
    "good morning good afternoon good evening howdy".split()
)


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def build_tension_directive(
    message:        str,
    intent_profile: dict,
    domain:         str       = "",
    conv_state:     dict      = None,
    mode:           str       = "normal",
) -> str:
    """
    Build a cognitive tension directive for this response.

    Returns empty string for trivial/casual messages or when no tension
    types are applicable. Structured mode returns a shorter version since
    the structured format directive already enforces insight density.

    Parameters
    ----------
    message        : The user's current message.
    intent_profile : Output of semantic_intent_service.score_intents().
    domain         : Classified domain name (e.g. "Pharmaceutical", "AI").
    conv_state     : Current conversation knowledge state dict (optional).
    mode           : Chat mode — "normal", "layman", "web_search", "deep_research".
    """
    conv_state = conv_state or {}

    # Skip trivial messages
    if _is_trivial(message, intent_profile):
        return ""

    # Skip layman mode — tension language conflicts with ELI5 framing
    if mode == "layman":
        return ""

    types = _select_tension_types(message, intent_profile, domain)
    if not types:
        return ""

    domain_key = _normalise_domain(domain)
    parts: list[str] = ["COGNITIVE TENSION DIRECTIVE:"]

    # Message-specific framing hook (generated from comparison subjects / causal question)
    hook = _build_message_hook(message, intent_profile)
    if hook:
        parts.append(hook)

    # For structured mode: shorter version — framing rules + open loop only
    if mode in ("web_search", "deep_research"):
        parts.append(_build_short_version(types, domain_key))
        return "\n\n".join(p for p in parts if p)

    # Full version for natural mode
    parts.append("\nSurface these specific tensions in your response:\n")
    for t in types[:3]:
        directive = _TENSION_DIRECTIVES[t]
        hint = _DOMAIN_HINTS.get(t, {}).get(domain_key, "")
        block = directive
        if hint:
            block += f"\n  Signal for this domain: {hint}"
        parts.append(block)

    parts.append(_FRAMING_RULES)
    parts.append(_build_open_loop_instruction(types, conv_state))

    return "\n\n".join(p for p in parts if p)


def score_tension(response_text: str) -> dict:
    """
    Score a response on four tension dimensions (0.0–1.0 each).

    Used for analytics — not for gating or looping responses.

    Returns
    -------
    {
      "contradiction_intensity": float,
      "curiosity_pull":          float,
      "strategic_tension":       float,
      "hidden_mechanism":        float,
      "composite":               float,
    }
    """
    if not response_text:
        return _zero_scores()

    words = response_text.split()
    word_count = max(len(words), 1)
    # Normaliser: 1 match per 60 words = score ~1.0
    norm = word_count / 60.0

    contrast_hits  = len(_CONTRAST_RE.findall(response_text))
    question_hits  = len(_QUESTION_RE.findall(response_text))
    mechanism_hits = len(_MECHANISM_RE.findall(response_text))
    hidden_hits    = len(_HIDDEN_RE.findall(response_text))

    contra_score    = min(1.0, contrast_hits  / max(norm * 0.6, 1))
    curiosity_score = min(1.0, question_hits  / max(norm * 0.5, 1))
    strategic_score = min(1.0, mechanism_hits / max(norm * 0.8, 1))
    hidden_score    = min(1.0, hidden_hits    / max(norm * 0.6, 1))
    composite       = round((contra_score + curiosity_score + strategic_score + hidden_score) / 4, 3)

    return {
        "contradiction_intensity": round(contra_score,    3),
        "curiosity_pull":          round(curiosity_score, 3),
        "strategic_tension":       round(strategic_score, 3),
        "hidden_mechanism":        round(hidden_score,    3),
        "composite":               composite,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Private helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _select_tension_types(message: str, intent_profile: dict, domain: str) -> list[str]:
    """Return up to 3 tension types ordered by analytical relevance."""
    types: set[str] = set()
    scores = intent_profile.get("intent_scores", {})
    primary    = intent_profile.get("primary_intent",    "default")
    secondary  = intent_profile.get("secondary_intents", [])

    # Intent-based selection (primary + secondaries)
    for intent_dim in ([primary] + secondary):
        for t in _INTENT_TENSION_MAP.get(intent_dim, []):
            types.add(t)

    # Message keyword boosters
    msg_lower = message.lower()

    if re.search(r'\b(dominat|lead\w*|biggest|largest|best|top|ahead)\b', msg_lower):
        types.add("systemic_weakness")   # success creates vulnerability

    if re.search(r'\bdespite\b|\balthough\b|\beven though\b', msg_lower):
        types.add("contradiction")

    if re.search(r'\bdepend\w*\b|\breliant\b|\bimport\w*\b|\bsourc\w*\b', msg_lower):
        types.add("hidden_dependency")

    if re.search(r'\bfuture\b|\bwill\b|\bnext\b|\btrend\b|\bforecast\b', msg_lower):
        types.add("future_instability")

    if re.search(r'\bprofit\b|\bmargin\b|\brevenue\b|\bvalue\b|\bcapture\b', msg_lower):
        types.add("strategic_tradeoff")

    if re.search(r'\bparadox\b|\bironic\b|\bironically\b|\bstrangely\b', msg_lower):
        types.add("paradox")

    # Domain boosters
    domain_key = _normalise_domain(domain)
    if "pharma" in domain_key:
        types.add("hidden_dependency")   # API sourcing is always relevant
        types.add("strategic_tradeoff")

    if domain_key == "ai":
        types.add("future_instability")
        types.add("paradox")

    if "finance" in domain_key:
        types.add("invisible_incentive")
        types.add("paradox")

    if "manufacturing" in domain_key:
        types.add("hidden_dependency")
        types.add("systemic_weakness")

    # Prioritise and cap at 3
    result = [t for t in _PRIORITY_ORDER if t in types][:3]
    return result


def _is_trivial(message: str, intent_profile: dict) -> bool:
    """True for greetings, very short questions, simple factual lookups."""
    tokens = message.strip().lower().split()
    if not tokens:
        return True

    # Pure greeting
    if set(tokens) <= _GREETING_TOKENS or (len(tokens) <= 3 and set(tokens) & _GREETING_TOKENS):
        return True

    # Very short with no analytical intent
    scores = intent_profile.get("intent_scores", {})
    if len(tokens) <= 5:
        if not scores:
            return True
        max_score = max(scores.values(), default=0)
        if max_score < 0.35:
            return True

    return False


def _build_message_hook(message: str, intent_profile: dict) -> str:
    """One-sentence framing hook derived from the message content."""
    # Comparison subjects → "The central tension: why did A outperform B?"
    try:
        from .chat_intent_service import extract_comparison_subjects
        subjects = extract_comparison_subjects(message)
        if len(subjects) == 2:
            a, b = subjects
            return (
                f"Central tension for this question: why did [{a}] diverge from [{b}]? "
                f"Name the structural mechanism — not just the outcome."
            )
    except Exception:
        pass

    # Strong causal framing → rephrase as structural question
    scores = intent_profile.get("intent_scores", {})
    if scores.get("causal", 0) >= 0.55:
        msg_clean = message.strip().rstrip("?.")
        return (
            f"This is a causal question. Do not answer WHAT happened — answer WHY the structural "
            f"logic made it almost inevitable: \"{msg_clean[:100]}\"."
        )

    return ""


def _build_open_loop_instruction(types: list[str], conv_state: dict) -> str:
    """Generate the open loop instruction based on active tension types."""
    parts = [_OPEN_LOOP_HEADER]

    # Use the dominant tension type to pick the ending style
    primary_type = types[0] if types else None
    if primary_type and primary_type in _OPEN_LOOP_ENDINGS:
        parts.append(_OPEN_LOOP_ENDINGS[primary_type])

    # If conversation has established unresolved questions, reference them
    unresolved = (conv_state or {}).get("unresolved_questions", [])
    if unresolved:
        parts.append(
            f"Prior unresolved tension from this conversation: \"{unresolved[0][:100]}\" — "
            f"deepen it or raise a harder version of it."
        )

    parts.append(
        "Do not frame the ending as a conclusion or summary. "
        "It should feel like the beginning of the next question, not the end of this one."
    )

    return "\n".join(parts)


def _build_short_version(types: list[str], domain_key: str) -> str:
    """Shorter tension directive for structured/research mode."""
    if not types:
        return ""
    # For structured mode: just framing rules + open loop
    return (
        f"Surface at least one of these tensions: {', '.join(types[:3])}. "
        "Every key_takeaway must reveal a mechanism, not state a fact. "
        "The summary should open with the core tension, not background context. "
        + _OPEN_LOOP_ENDINGS.get(types[0], "")
    )


def _normalise_domain(domain: str) -> str:
    """Normalise domain name to a lookup key."""
    d = (domain or "").lower()
    if "pharma" in d:
        return "pharmaceutical"
    if "financ" in d or "banking" in d:
        return "finance"
    if d == "ai" or "machine" in d or "intellig" in d:
        return "ai"
    if "manufact" in d:
        return "manufacturing"
    if "export" in d or "trade" in d:
        return "trade"
    if "tech" in d or "software" in d:
        return "technology"
    return d


def _zero_scores() -> dict:
    return {
        "contradiction_intensity": 0.0,
        "curiosity_pull":          0.0,
        "strategic_tension":       0.0,
        "hidden_mechanism":        0.0,
        "composite":               0.0,
    }
