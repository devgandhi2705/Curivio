"""
Cognitive Tension Engine.

The per-response prompt-injected tension directive and everything only it
used (the tension-type directive text, domain hints, open-loop endings,
intent→tension mapping) were deleted by chat-routing v2 — replaced by one
RESPONSE PRINCIPLES line in the new prompt builder.

What remains scores a response after the fact, for analytics — it does not
gate or shape generation:

Public API
----------
score_tension(response_text) → dict
"""

from __future__ import annotations

import re

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


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

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

def _zero_scores() -> dict:
    return {
        "contradiction_intensity": 0.0,
        "curiosity_pull":          0.0,
        "strategic_tension":       0.0,
        "hidden_mechanism":        0.0,
        "composite":               0.0,
    }
