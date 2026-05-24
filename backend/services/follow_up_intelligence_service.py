"""
Strategic Follow-Up Intelligence.

Generates thread-aware follow-up questions by synthesizing:
  - active conversation state (mechanisms, contradictions, comparisons, causal chains)
  - 8 analytical categories (contradiction, scenario, future_shift, strategic_risk,
    hidden_dependency, economic_implication, geopolitical_implication, second_order_effect)
  - topic and domain context

Every follow-up is phrased as a specific question, not a topic name.

BAD:  {"topic": "Learn more about APIs", "reason": "Builds on the topic."}
GOOD: {"topic": "If India depends on Chinese APIs, could geopolitical tensions
        become a pharmaceutical supply risk?", "reason": "Exposes the hidden
        upstream dependency that the current analysis doesn't fully control."}

Public API
----------
generate_strategic_followups(
    state, topic_hint, intent_profile, domain, max_items
) -> list[dict]
"""

from __future__ import annotations

import re

# ── Category definitions ──────────────────────────────────────────────────────

CATEGORIES = [
    "contradiction",
    "hidden_dependency",
    "second_order_effect",
    "strategic_risk",
    "scenario",
    "future_shift",
    "economic_implication",
    "geopolitical_implication",
]

_CATEGORY_REASON: dict[str, str] = {
    "contradiction":          "Deepens a structural tension from this session — the contradiction that makes both sides simultaneously true.",
    "hidden_dependency":      "Exposes what the current position depends on but cannot fully control.",
    "second_order_effect":    "Traces what the established mechanism produces two steps out.",
    "strategic_risk":         "Surfaces the underpriced risk that the current framing may underweight.",
    "scenario":               "Tests the analysis against the specific condition that would change the conclusion.",
    "future_shift":           "Names the force currently building that will disrupt the equilibrium described here.",
    "economic_implication":   "Follows the value flow — who captures the most from this structure, and why.",
    "geopolitical_implication": "Connects the mechanism to the cross-border power dynamic with the most leverage.",
}


# ── Intent → category affinity ────────────────────────────────────────────────
# Higher-indexed lists → lower priority.

_INTENT_CATEGORY_AFFINITY: dict[str, list[str]] = {
    "causal":      ["second_order_effect",  "hidden_dependency",  "scenario"],
    "comparison":  ["contradiction",        "strategic_risk",     "economic_implication"],
    "historical":  ["future_shift",         "second_order_effect","scenario"],
    "strategic":   ["strategic_risk",       "hidden_dependency",  "future_shift"],
    "research":    ["contradiction",        "second_order_effect","hidden_dependency"],
    "prediction":  ["future_shift",         "strategic_risk",     "scenario"],
    "critique":    ["strategic_risk",       "contradiction",      "hidden_dependency"],
    "synthesis":   ["second_order_effect",  "economic_implication","geopolitical_implication"],
    "explanation": ["hidden_dependency",    "scenario",           "second_order_effect"],
    "default":     ["contradiction",        "hidden_dependency",  "strategic_risk"],
}


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def generate_strategic_followups(
    state:          dict,
    topic_hint:     str | None  = None,
    intent_profile: dict | None = None,
    domain:         str         = "",
    max_items:      int         = 4,
) -> list[dict]:
    """
    Generate up to *max_items* thread-aware follow-up questions.

    Returns a list of dicts: {"topic": str, "reason": str, "category": str}

    The "topic" field contains the full question text (not a topic name), for
    forward-compatibility with the recommendations display layer.

    Returns an empty list when the state is too sparse to generate specific items.
    """
    intent_profile = intent_profile or {}
    primary_intent = intent_profile.get("primary_intent", "default")

    # Need at least one state element to generate specific questions
    if not _has_useful_state(state) and not topic_hint:
        return []

    # Rank categories by intent affinity + state availability
    ranked = _rank_categories(primary_intent, state, domain)
    results: list[dict] = []

    for category in ranked:
        if len(results) >= max_items:
            break
        q = _generate_for_category(category, state, topic_hint, domain)
        if q:
            results.append({
                "topic":    q,
                "reason":   _CATEGORY_REASON[category],
                "category": category,
            })

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Category generators
# ═══════════════════════════════════════════════════════════════════════════════

def _generate_for_category(
    category:   str,
    state:      dict,
    topic_hint: str | None,
    domain:     str,
) -> str | None:
    """Generate one specific question for the given category, or return None."""
    fn = _GENERATORS.get(category)
    if not fn:
        return None
    return fn(state, topic_hint, domain)


def _gen_contradiction(state: dict, topic: str | None, domain: str) -> str | None:
    contradiction = _first_contradiction(state)
    if contradiction:
        # Turn the raw contradiction sentence into a deepening question
        clean = re.sub(r'^[•\-\*]\s*', '', contradiction).rstrip(".").strip()
        return f"{clean} — what structural logic makes both sides simultaneously true rather than a paradox?"

    mechs = _top_mechanisms(state, n=2)
    if len(mechs) == 2:
        a = _truncate(mechs[0], 60)
        b = _truncate(mechs[1], 60)
        return f"This session established both that {a} and that {b} — does that create a structural tension, and which gives way first?"

    a, b = _comparison_pair(state)
    if a and b:
        thread = _thread(state) or topic or "this topic"
        return f"Why does {a} perform differently from {b} on {thread} — what specific structural asymmetry explains the divergence?"

    return None


def _gen_hidden_dependency(state: dict, topic: str | None, domain: str) -> str | None:
    mech = _best_mechanism(state)
    if mech:
        clean = _truncate(mech, 70)
        return f"What does '{clean}' depend on that the current analysis doesn't fully control — and what breaks first when that upstream changes?"

    thread = _thread(state) or topic
    if thread:
        domain_note = f" in {domain}" if domain else ""
        return f"What is the single upstream dependency that {thread}{domain_note} cannot afford to lose — and how exposed is it currently?"

    return None


def _gen_second_order_effect(state: dict, topic: str | None, domain: str) -> str | None:
    chain = _first_causal_chain(state)
    if chain:
        clean = _truncate(chain, 80)
        return f"If the causal logic behind '{clean}' plays out fully, what does it produce two steps out that isn't currently being discussed?"

    mech = _best_mechanism(state)
    if mech:
        clean = _truncate(mech, 70)
        return f"What is the second-order consequence of '{clean}' — the effect that follows from the effect?"

    thread = _thread(state) or topic
    if thread:
        return f"What does {thread} produce indirectly — the downstream consequence that no one is currently tracking?"

    return None


def _gen_strategic_risk(state: dict, topic: str | None, domain: str) -> str | None:
    themes = state.get("strategic_themes", [])
    if themes:
        theme = _truncate(themes[0], 60)
        return f"What is the underpriced risk in '{theme}' — the specific vulnerability that the current framing is systematically discounting?"

    mech = _best_mechanism(state)
    if mech:
        clean = _truncate(mech, 65)
        return f"Who loses most if '{clean}' breaks down — and what would the early warning signal look like?"

    a, b = _comparison_pair(state)
    if a and b:
        return f"What is the strategic risk that {a} carries by depending on the current dynamic with {b} — and how would it materialise?"

    thread = _thread(state) or topic
    if thread:
        return f"What is the specific risk in {thread} that the mainstream framing systematically underweights?"

    return None


def _gen_scenario(state: dict, topic: str | None, domain: str) -> str | None:
    mech = _best_mechanism(state)
    if mech:
        clean = _truncate(mech, 65)
        return f"What specific condition would have to change for '{clean}' to reverse — and how plausible is that scenario?"

    chain = _first_causal_chain(state)
    if chain:
        clean = _truncate(chain, 70)
        return f"What breaks first if the core assumption behind '{clean}' turns out to be wrong?"

    thread = _thread(state) or topic
    if thread:
        return f"What is the most important scenario that challenges the current analysis of {thread} — the one that stress-tests the key assumption?"

    return None


def _gen_future_shift(state: dict, topic: str | None, domain: str) -> str | None:
    themes = state.get("strategic_themes", [])
    if themes:
        theme = _truncate(themes[0], 55)
        return f"What specific force is currently building that would reverse '{theme}' — and what's the earliest visible signal?"

    mech = _best_mechanism(state)
    if mech:
        clean = _truncate(mech, 65)
        return f"What changes if '{clean}' is disrupted by a technological or regulatory shift over the next five years?"

    thread = _thread(state) or topic
    if thread:
        domain_note = f" in {domain}" if domain else ""
        return f"What is the specific equilibrium-disrupting force building in {thread}{domain_note} — and who does it threaten most?"

    return None


def _gen_economic_implication(state: dict, topic: str | None, domain: str) -> str | None:
    a, b = _comparison_pair(state)
    if a and b:
        mech = _best_mechanism(state)
        if mech:
            clean = _truncate(mech, 55)
            return f"Why does {a} capture different economic value than {b} from '{clean}' — who extracts margin, and who absorbs cost?"
        return f"Why does {a} capture more economic value than {b} despite comparable activity — what determines where the margin actually sits?"

    mech = _best_mechanism(state)
    if mech:
        clean = _truncate(mech, 65)
        return f"Who actually captures the economic value created by '{clean}' — and is that the same actor doing the work?"

    thread = _thread(state) or topic
    if thread:
        return f"Where does the economic value actually concentrate in {thread} — which actor captures the margin, and which absorbs the cost?"

    return None


def _gen_geopolitical_implication(state: dict, topic: str | None, domain: str) -> str | None:
    a, b = _comparison_pair(state)
    if a and b:
        mech = _best_mechanism(state)
        if mech:
            clean = _truncate(mech, 55)
            return f"If geopolitical tension between {a} and {b} escalates, how does '{clean}' hold up — and who loses leverage first?"
        return f"How does the strategic dynamic between {a} and {b} change if cross-border policy shifts — and which side has more structural resilience?"

    thread = _thread(state) or topic
    if thread:
        domain_note = f" in {domain}" if domain else ""
        return (
            f"What cross-border power dynamic has the most leverage over {thread}{domain_note} — "
            f"and how would a policy shift between the key players materialise?"
        )

    return None


_GENERATORS: dict[str, object] = {
    "contradiction":          _gen_contradiction,
    "hidden_dependency":      _gen_hidden_dependency,
    "second_order_effect":    _gen_second_order_effect,
    "strategic_risk":         _gen_strategic_risk,
    "scenario":               _gen_scenario,
    "future_shift":           _gen_future_shift,
    "economic_implication":   _gen_economic_implication,
    "geopolitical_implication": _gen_geopolitical_implication,
}


# ═══════════════════════════════════════════════════════════════════════════════
# Category ranking
# ═══════════════════════════════════════════════════════════════════════════════

def _rank_categories(primary_intent: str, state: dict, domain: str) -> list[str]:
    """
    Rank all 8 categories by: intent affinity + state availability.
    Returns ordered list (most relevant first).
    """
    affinity = _INTENT_CATEGORY_AFFINITY.get(primary_intent, _INTENT_CATEGORY_AFFINITY["default"])
    scores: dict[str, float] = {}

    for i, cat in enumerate(affinity):
        scores[cat] = 3.0 - (i * 0.5)   # 3.0, 2.5, 2.0 for top 3 affinity

    # Boost categories that have direct state support
    if state.get("contradictions_surfaced"):
        scores["contradiction"] = scores.get("contradiction", 0) + 1.5
    if state.get("causal_chains"):
        scores["second_order_effect"] = scores.get("second_order_effect", 0) + 1.2
        scores["scenario"]            = scores.get("scenario", 0)            + 0.8
    if state.get("comparative_contexts"):
        scores["geopolitical_implication"] = scores.get("geopolitical_implication", 0) + 1.0
        scores["economic_implication"]     = scores.get("economic_implication", 0)     + 0.8
        scores["contradiction"]            = scores.get("contradiction", 0)            + 0.6
    if state.get("strategic_themes"):
        scores["strategic_risk"]  = scores.get("strategic_risk", 0)  + 1.0
        scores["future_shift"]    = scores.get("future_shift", 0)    + 0.8
    if state.get("mechanisms_covered"):
        scores["hidden_dependency"] = scores.get("hidden_dependency", 0) + 0.8

    # Ensure every category has at least a base score
    for cat in CATEGORIES:
        if cat not in scores:
            scores[cat] = 0.5

    return sorted(CATEGORIES, key=lambda c: scores.get(c, 0), reverse=True)


# ═══════════════════════════════════════════════════════════════════════════════
# State extraction helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _has_useful_state(state: dict) -> bool:
    return bool(
        state.get("mechanisms_covered")
        or state.get("contradictions_surfaced")
        or state.get("comparative_contexts")
        or state.get("causal_chains")
        or state.get("strategic_themes")
        or state.get("unresolved_questions")
    )


def _first_contradiction(state: dict) -> str:
    items = state.get("contradictions_surfaced", [])
    return items[0] if items else ""


def _top_mechanisms(state: dict, n: int = 2) -> list[str]:
    return state.get("mechanisms_covered", [])[:n]


def _best_mechanism(state: dict) -> str:
    """Return the most informative (closest to 80 chars) mechanism."""
    mechs = state.get("mechanisms_covered", [])
    if not mechs:
        return ""
    return min(mechs[:4], key=lambda m: abs(len(m) - 80))


def _comparison_pair(state: dict) -> tuple[str, str]:
    comparative = state.get("comparative_contexts", [])
    if comparative:
        parts = comparative[0].split(" vs ")
        if len(parts) == 2:
            return parts[0].strip(), parts[1].strip()
    return "", ""


def _first_causal_chain(state: dict) -> str:
    chains = state.get("causal_chains", [])
    return chains[0] if chains else ""


def _thread(state: dict) -> str:
    return (state.get("current_thread") or "").strip()


def _truncate(text: str, max_len: int) -> str:
    text = text.strip().rstrip(".")
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "…"
