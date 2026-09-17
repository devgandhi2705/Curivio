"""
Mechanism-Preserving Simplification — Layman Mode Service.

Builds the enhanced "Explain Simply" directive that:
- Simplifies vocabulary and abstraction without flattening intelligence
- Injects domain-specific analogy bridge suggestions
- Embeds abstraction self-check and strategic meaning tests
- Preserves causal logic, incentive structures, and hidden mechanisms

Public API
----------
build_layman_directive(domain: str, topic_hint: str | None) -> str
"""

from __future__ import annotations

from ..prompts.instruction_packs.core_learning_pack import LAYMAN_SIMPLIFICATION_DIRECTIVE as _DIRECTIVE_TEMPLATE

# ── Domain → analogy bank ──────────────────────────────────────────────────────
# Each entry:
#   seed      — a concrete worked example of a mechanism-carrying analogy
# (a "domains" list and a "caution" note used to live here too, dropped once
# grep confirmed _format_bank only ever reads "seed" — the prompt's block
# table never surfaced them.)

_ANALOGY_BANKS: dict[str, dict] = {
    "pharmaceutical": {
        "seed": (
            "FDA approval → a restaurant with a health inspection certificate in the window: "
            "the certificate doesn't make the food tastier, but buyers assume a company that "
            "passed strict scrutiny is less likely to fail them — and that assumption is worth "
            "more than advertising because it cannot be purchased."
        ),
    },
    "ai": {
        "seed": (
            "Training a model → hiring 1 million interns to read every book ever written and "
            "extract patterns, then distilling everything they learned into one entity's intuition — "
            "the patterns are implicit, not explicit rules."
        ),
    },
    "finance": {
        "seed": (
            "Liquidity → water pressure in a pipe: abundant flow makes movement easy and cheap; "
            "a sudden drop creates friction everywhere simultaneously, even for parties that weren't "
            "the source of the problem."
        ),
    },
    "technology": {
        "seed": (
            "API → a standardised plug socket: any device that conforms to the spec can draw power "
            "without knowing how the national grid works — standardisation creates leverage for "
            "whoever controls the spec."
        ),
    },
    "manufacturing": {
        "seed": (
            "Just-in-time supply → a restaurant that orders only what it needs for tonight's reservations: "
            "zero storage cost, maximum freshness, but if a single supplier fails, the kitchen stops — "
            "efficiency and fragility are the same thing."
        ),
    },
    "economics": {
        "seed": (
            "Price signals → a traffic light system for scarcity: rising prices tell producers "
            "'make more of this' without anyone coordinating — the signal emerges from millions "
            "of individual decisions, not a central plan."
        ),
    },
}

_DEFAULT_ANALOGY_BANK: dict = {
    "seed": "Match the analogy to the mechanism (why things happen), not the surface shape (what it looks like).",
}


# ── Directive template ─────────────────────────────────────────────────────────
# Sourced from core_learning_pack.LAYMAN_SIMPLIFICATION_DIRECTIVE.
# {{ANALOGY_BANK}} is replaced at runtime with domain-specific content via .replace().


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def build_layman_directive(
    domain: str = "",
    topic_hint: str | None = None,
    known_concepts: list[str] | None = None,
) -> str:
    """
    Build the full mechanism-preserving simplification directive.

    Injects a domain-specific analogy bank into the base template.
    Falls back to the generic bank when domain is unclassified.

    Parameters
    ----------
    domain         : Classified domain from domain_classifier_service (e.g. "Pharmaceutical").
    topic_hint     : Current topic, used to anchor the analogy suggestion.
    known_concepts : User's known graph nodes — injected as explicit analogy anchors
                     so the simplification references what they've already learned.
    """
    key  = _normalise_domain(domain)
    bank = _ANALOGY_BANKS.get(key, _DEFAULT_ANALOGY_BANK)
    directive = _DIRECTIVE_TEMPLATE.replace("{{ANALOGY_BANK}}", _format_bank(bank, topic_hint)).strip()

    # Phase 4.6: prepend known-concept anchors when available
    if known_concepts:
        anchors = ", ".join(f"'{c}'" for c in known_concepts[:5])
        anchor_block = (
            f"KNOWN CONCEPT ANCHORS — use these as bridges to the new idea:\n"
            f"  {anchors}\n"
            f"When explaining a new concept, open with: "
            f"\"Remember how [anchor] works? This is the same mechanism, one step [upstream/downstream].\"\n"
        )
        directive = anchor_block + "\n" + directive

    return directive


# ═══════════════════════════════════════════════════════════════════════════════
# Private helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _normalise_domain(domain: str) -> str:
    d = (domain or "").lower()
    if "pharma" in d:                              return "pharmaceutical"
    if "financ" in d or "bank" in d:               return "finance"
    if d == "ai" or "machine" in d or "intellig" in d: return "ai"
    if "manufact" in d:                            return "manufacturing"
    if "tech" in d or "software" in d or "comput" in d: return "technology"
    if "econ" in d or "trade" in d or "market" in d:   return "economics"
    return d


def _format_bank(bank: dict, topic_hint: str | None) -> str:
    lines = ["ANALOGY DOMAIN BANK:", f"- Seed example: {bank.get('seed', '')}"]
    if topic_hint:
        lines.append(
            f'- Anchor the analogy to the specific topic: "{topic_hint}" — '
            "a specific analogy sticks far better than a general one.")
    return "\n".join(lines)
