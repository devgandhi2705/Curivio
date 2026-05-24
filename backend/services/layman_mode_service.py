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

# ── Domain → analogy bank ──────────────────────────────────────────────────────
# Each entry:
#   domains   — familiar systems to draw analogies from
#   seed      — a concrete worked example of a mechanism-carrying analogy
#   caution   — the specific intelligence dimension most at risk of being lost

_ANALOGY_BANKS: dict[str, dict] = {
    "pharmaceutical": {
        "domains": [
            "restaurant kitchens and food safety inspection",
            "certification marks and trust signals",
            "supply chains and ingredient sourcing",
        ],
        "seed": (
            "FDA approval → a restaurant with a health inspection certificate in the window: "
            "the certificate doesn't make the food tastier, but buyers assume a company that "
            "passed strict scrutiny is less likely to fail them — and that assumption is worth "
            "more than advertising because it cannot be purchased."
        ),
        "caution": (
            "Preserve the economic asymmetry: who does the manufacturing vs. who captures the profit — "
            "scale advantage and value capture are structurally decoupled."
        ),
    },
    "ai": {
        "domains": [
            "hiring and skill screening",
            "human learning and pattern recognition",
            "tools that amplify existing skills",
        ],
        "seed": (
            "Training a model → hiring 1 million interns to read every book ever written and "
            "extract patterns, then distilling everything they learned into one entity's intuition — "
            "the patterns are implicit, not explicit rules."
        ),
        "caution": (
            "Preserve: data is leverage, compute is capital, and the moment of inference is "
            "where costs scale — the same dynamic that makes models powerful makes them expensive to deploy."
        ),
    },
    "finance": {
        "domains": [
            "sports betting and probability",
            "insurance and risk pooling",
            "water flow and pressure",
        ],
        "seed": (
            "Liquidity → water pressure in a pipe: abundant flow makes movement easy and cheap; "
            "a sudden drop creates friction everywhere simultaneously, even for parties that weren't "
            "the source of the problem."
        ),
        "caution": (
            "Preserve incentive misalignment: who earns fees on transactions vs. who bears the risk "
            "of the outcome — the advisor and the investor do not have identical incentives."
        ),
    },
    "technology": {
        "domains": [
            "plumbing and standardised connections",
            "roads and traffic infrastructure",
            "electrical standards and plug sockets",
        ],
        "seed": (
            "API → a standardised plug socket: any device that conforms to the spec can draw power "
            "without knowing how the national grid works — standardisation creates leverage for "
            "whoever controls the spec."
        ),
        "caution": (
            "Preserve: abstraction layers create dependency, and dependency creates leverage — "
            "the platform owner who defines the interface captures disproportionate value."
        ),
    },
    "manufacturing": {
        "domains": [
            "restaurant mise en place and prep timing",
            "construction site logistics",
            "orchestra and timing dependencies",
        ],
        "seed": (
            "Just-in-time supply → a restaurant that orders only what it needs for tonight's reservations: "
            "zero storage cost, maximum freshness, but if a single supplier fails, the kitchen stops — "
            "efficiency and fragility are the same thing."
        ),
        "caution": (
            "Preserve: concentration risk is invisible during stability and catastrophic during disruption — "
            "the optimisation that looks smart in a spreadsheet breaks under stress."
        ),
    },
    "economics": {
        "domains": [
            "ecosystems and incentive feedback loops",
            "auctions and bidding dynamics",
            "games with rules that reward specific behaviour",
        ],
        "seed": (
            "Price signals → a traffic light system for scarcity: rising prices tell producers "
            "'make more of this' without anyone coordinating — the signal emerges from millions "
            "of individual decisions, not a central plan."
        ),
        "caution": (
            "Preserve: who designs the rules captures the most value — the market is not neutral, "
            "it reflects the incentives of whoever structured it."
        ),
    },
}

_DEFAULT_ANALOGY_BANK: dict = {
    "domains": ["everyday systems the user already understands: sports, cooking, roads, construction"],
    "seed": "Match the analogy to the mechanism (why things happen), not the surface shape (what it looks like).",
    "caution": "The analogy must carry the causal logic — surface resemblance without mechanism is decoration.",
}


# ── Directive template ─────────────────────────────────────────────────────────
# {{ANALOGY_BANK}} is replaced at runtime with domain-specific content.

_DIRECTIVE_TEMPLATE = """\
ACTIVE RESPONSE MODE — MECHANISM-PRESERVING SIMPLIFICATION:

THE FUNDAMENTAL RULE:
Simplify vocabulary, abstraction, and jargon.
NEVER simplify the underlying mechanism.

The user is smart but new to this domain. They can handle complexity — they cannot handle unfamiliar vocabulary.
Give them the full intelligence of the idea in language they already know.

WHAT TO SIMPLIFY:
- Technical jargon → plain English (define immediately in parentheses when unavoidable)
- Abbreviations → full names on first use
- Abstract structure → concrete analogies grounded in familiar systems

WHAT TO NEVER SIMPLIFY:
- Causal logic: WHY A caused B — not just that it did
- Incentive structures: WHY actors made the choices they made — not just what they chose
- Strategic insight: WHAT the mechanism reveals about power, position, or outcome
- Hidden mechanisms: the non-obvious force that produces the surprising result

BAD:  "FDA helps exports because countries trust approved medicines."
GOOD: "FDA approval works like a global trust certificate — buyers assume a company that passed strict inspections is less likely to fail them, and that assumption is worth more than a marketing budget because scrutiny earned it, money didn't."

Structure your response in this sequence:
1. THE CORE IDEA — One plain sentence. What is this, in the simplest honest terms?
2. THE ANALOGY BRIDGE — See analogy system below. Carry the mechanism, not just the shape.
   Bridge back explicitly: "In the same way, [concept] works by [mechanism]…"
3. THE MECHANISM — How it actually works, in plain language.
   Every step of the causal chain must survive. If a term is unavoidable, define it inline:
   "asymmetric encryption (a lock anyone can close, but only you can open)".
4. WHY IT EXISTS — What problem did it solve? What was broken or missing before it?
5. THE INSIGHT — The one genuinely non-obvious thing worth knowing. What would surprise
   someone who just learned the basics? This is the most important section — never skip it.

{{ANALOGY_BANK}}

ANALOGY QUALITY TEST (apply before using any analogy):
- Does it carry the causal mechanism, or just the visual shape?
  SHAPE ONLY: "Like a filter."
  MECHANISM:  "Like a bouncer with a list — the stricter the door policy, the more the implicit guarantee of quality inside is worth to the people who got in."
- Could someone use the analogy to explain the mechanism back, not just identify it?
- Does it preserve WHO benefits, WHO pays the cost, and WHY?

ABSTRACTION SELF-CHECK (run internally before finalising):
1. Jargon: Can a smart person new to this domain understand every sentence without stopping?
   — If not: replace or immediately define the term in parentheses.
2. Mechanism vs. shape: Are you describing the causal chain, or just what it looks like?
   — "It acts like a filter" is shape. "It selects by X because actors face incentive Y" is mechanism.
3. Compression: Have you simplified away the key tension or strategic insight?
   — The full intelligence of the idea must survive. Only the vocabulary is simplified.

STRATEGIC MEANING TEST (confirm before finalising):
- Does this still show WHY the outcome happened? (causal logic preserved)
- Does this show WHO drove it and WHAT motivated them? (incentive structure preserved)
- Does this surface something non-obvious? (insight density preserved)
- Would a smart person feel genuinely smarter after reading this, not just more informed?

Tone: speak like a brilliant friend explaining over coffee — direct, warm, not condescending.
Never open with a definition. Lead with intuition, then mechanism, then implication."""


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def build_layman_directive(domain: str = "", topic_hint: str | None = None) -> str:
    """
    Build the full mechanism-preserving simplification directive.

    Injects a domain-specific analogy bank into the base template.
    Falls back to the generic bank when domain is unclassified.

    Parameters
    ----------
    domain     : Classified domain from domain_classifier_service (e.g. "Pharmaceutical").
    topic_hint : Current topic, used to anchor the analogy suggestion.
    """
    key  = _normalise_domain(domain)
    bank = _ANALOGY_BANKS.get(key, _DEFAULT_ANALOGY_BANK)
    return _DIRECTIVE_TEMPLATE.replace("{{ANALOGY_BANK}}", _format_bank(bank, topic_hint)).strip()


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
    domains = bank.get("domains", [])
    if isinstance(domains, list):
        domains_str = "; ".join(domains)
    else:
        domains_str = str(domains)

    lines = [
        "ANALOGY DOMAIN BANK:",
        f"- Draw from: {domains_str}",
        f"- Seed example: {bank.get('seed', '')}",
        f"- Mechanism caution: {bank.get('caution', '')}",
    ]
    if topic_hint:
        lines.append(
            f"- Anchor the analogy to the specific topic: \"{topic_hint}\" — "
            "a specific analogy sticks far better than a general one."
        )
    return "\n".join(lines)
