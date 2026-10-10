"""
Mechanism-Preserving Simplification — Layman Mode Service.

Builds the enhanced "Explain Simply" directive that:
- Simplifies vocabulary and abstraction without flattening intelligence
- Injects domain-specific analogy bridge suggestions
- Embeds abstraction self-check and strategic meaning tests
- Preserves causal logic, incentive structures, and hidden mechanisms

Public API
----------
build_layman_directive(domain: str, known_concepts: list[str] | None) -> str
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

# No domain match → no example (the directive already says what a good analogy does).
_DEFAULT_ANALOGY_BANK: dict = {}


# ── Directive template ─────────────────────────────────────────────────────────
# Sourced from core_learning_pack.LAYMAN_SIMPLIFICATION_DIRECTIVE.
# {{ANALOGY_BANK}} is replaced at runtime with domain-specific content via .replace().


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def build_layman_directive(
    domain: str = "",
    known_concepts: list[str] | None = None,
) -> str:
    """
    Build the full mechanism-preserving simplification directive.

    Injects a domain-specific analogy example into the base template; an
    unclassified domain gets none.

    Parameters
    ----------
    domain         : Classified domain from domain_classifier_service (e.g. "Pharmaceutical").
    known_concepts : User's known graph nodes — injected as explicit analogy anchors
                     so the simplification references what they've already learned.
    """
    key  = _normalise_domain(domain)
    bank = _ANALOGY_BANKS.get(key, _DEFAULT_ANALOGY_BANK)
    bank_text = _format_bank(bank)
    directive = _DIRECTIVE_TEMPLATE.replace(
        "{{ANALOGY_BANK}}\n\n", f"{bank_text}\n\n" if bank_text else "").strip()

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


def _format_bank(bank: dict) -> str:
    # Framed as calibration, not a mandate: "anchor the analogy to <topic>"
    # made the model force an analogy into every answer.
    seed = bank.get("seed")
    if not seed:
        return ""
    return ("ANALOGY DOMAIN BANK — one analogy that carries a mechanism, for calibration only "
            f"(don't reuse it): {seed}")
