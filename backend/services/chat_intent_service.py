"""
Hybrid intent detection for conversational chat messages.

Fast-path: regex patterns select mode (compare / research / analyze / normal)
and provide a baseline format_intent. These are deterministic and low-latency.

Semantic layer: semantic_intent_service scores the message across 9 dimensions
and produces a blended format directive for multi-intent prompts. This runs
after the regex fast-path and enriches the result without overriding mode
selection.

Only activates when the user's selected mode is "normal" — explicit mode
selections always win.

Public API
----------
detect_intent(message)                         → dict
extract_comparison_subjects(message)           → list[str]   (up to 2 items)
"""

from __future__ import annotations

import re

# ── Pattern tables ────────────────────────────────────────────────────────────

_COMPARE_PATTERNS: list[re.Pattern] = [
    re.compile(r'\bcompar\w*\b',              re.I),
    re.compile(r'\bvs\.?\b',                  re.I),
    re.compile(r'\bversus\b',                 re.I),
    re.compile(r'\bdifference[s]?\s+between\b', re.I),
    re.compile(r'\bcontrast\b',               re.I),
    re.compile(r'\bpros\s+and\s+cons\b',      re.I),
]

_RESEARCH_PATTERNS: list[re.Pattern] = [
    re.compile(r'\bresearch\b',                         re.I),
    re.compile(r'\bdeep[\s\-]?dive\b',                  re.I),
    re.compile(r'\bin[\s\-]depth\b',                    re.I),
    re.compile(r'\bcomprehensive\b',                    re.I),
    re.compile(r'\beverything\s+about\b',               re.I),
    re.compile(r'\bfull\s+(analysis|overview|report|breakdown)\b', re.I),
    re.compile(r'\bdeep\s+research\b',                  re.I),
]

_ANALYZE_PATTERNS: list[re.Pattern] = [
    re.compile(r'\banalyz[ei]\w*\b',                            re.I),
    re.compile(r'\banalysis\s+(of|on)\b',                       re.I),
    re.compile(r'\bbreakdown\s+(of|on)\b',                      re.I),
    re.compile(r'\bassess\w*\b',                                re.I),
    re.compile(r'\bevaluat\w*\b',                               re.I),
    re.compile(r'\bsupply[\s\-]chain\b',                        re.I),
    re.compile(r'\bmarket\s+(dynamics|landscape|trends|analysis)\b', re.I),
    re.compile(r'\bsector\s+(analysis|assessment|outlook)\b',   re.I),
    re.compile(r'\bindustry\s+(analysis|assessment|breakdown)\b', re.I),
]

# ── Format intent patterns (do not affect mode selection — only response structure) ──

_EXPLANATION_PATTERNS: list[re.Pattern] = [
    re.compile(r'\bwhat\s+is\b',            re.I),
    re.compile(r'\bwhat\s+are\b',           re.I),
    re.compile(r'\bwhat\s+does\b',          re.I),
    re.compile(r'\bwhat\s+exactly\b',       re.I),
    re.compile(r'\bexplain\b',              re.I),
    re.compile(r'\bteach\s+me\b',           re.I),
    re.compile(r'\bhow\s+does\b',           re.I),
    re.compile(r'\bhow\s+do\b',             re.I),
    re.compile(r'\bhow\s+does\s+it\b',      re.I),
    re.compile(r'\bdefinition\s+of\b',      re.I),
    re.compile(r'\bwhat\s+makes\b',         re.I),
]

_HISTORICAL_PATTERNS: list[re.Pattern] = [
    re.compile(r'\bhistory\s+of\b',         re.I),
    re.compile(r'\bevolution\s+of\b',       re.I),
    re.compile(r'\btimeline\b',             re.I),
    re.compile(r'\borigin[s]?\s+(of|behind)\b', re.I),
    re.compile(r'\bhow\s+did\b',            re.I),
    re.compile(r'\bwhen\s+did\b',           re.I),
    re.compile(r'\bdevelopment\s+of\b',     re.I),
    re.compile(r'\bhow\s+(?:it\s+)?started\b', re.I),
    re.compile(r'\bhistorical\b',           re.I),
    re.compile(r'\bover\s+the\s+(years|decades|time)\b', re.I),
]

_STRATEGIC_PATTERNS: list[re.Pattern] = [
    re.compile(r'\bmarket\b',               re.I),
    re.compile(r'\bexport[s]?\b',           re.I),
    re.compile(r'\bcompetition\b',          re.I),
    re.compile(r'\bcompetitive\b',          re.I),
    re.compile(r'\badoption\b',             re.I),
    re.compile(r'\bregulation[s]?\b',       re.I),
    re.compile(r'\bindustry\b',             re.I),
    re.compile(r'\bsupply[\s\-]chain\b',    re.I),
    re.compile(r'\bgeopolit\w*\b',          re.I),
    re.compile(r'\bstrateg\w*\b',           re.I),
    re.compile(r'\bdomin\w+\b',             re.I),
    re.compile(r'\blandscape\b',            re.I),
    re.compile(r'\boutlook\b',              re.I),
    re.compile(r'\bincentive[s]?\b',        re.I),
]

# Subject extraction — ordered by specificity
_VS_RE         = re.compile(r'(?:compare\s+)?(.+?)\s+vs\.?\s+(.+)',          re.I)
_VERSUS_RE     = re.compile(r'(?:compare\s+)?(.+?)\s+versus\s+(.+)',         re.I)
_BETWEEN_RE    = re.compile(r'difference[s]?\s+between\s+(.+?)\s+and\s+(.+)', re.I)
_COMPARE_AND   = re.compile(r'compare\s+(.+?)\s+and\s+(.+)',                 re.I)

# Verbs to strip from the beginning of a cleaned topic
_STRIP_PREFIX = re.compile(
    r'^(research|analyze|analyse|analysis\s+of|breakdown\s+of|deep\s+dive\s+(into|on)?|'
    r'in[\s\-]depth\s+(look\s+at|overview\s+of)?|tell\s+me\s+(everything\s+)?about|'
    r'give\s+me\s+a\s+(comprehensive\s+)?|do\s+a\s+|run\s+a\s+)\s*',
    re.I,
)


# ── Format intent helper ─────────────────────────────────────────────────────

def _detect_format_intent(message: str, intent: str) -> str:
    """
    Determine response FORMAT intent from message semantics.

    This controls HOW the response is structured, independently of which
    retrieval mode is used. Returned value is injected into context so the
    system prompt can apply intent-specific structural guidance.

    Priority: compare > explicit-analyze > historical > strategic > research > explanation > default.
    Explicit analytical verbs (analyze, assess) override topic-based detection so that
    "analyze the implications of AI regulation" → analysis, not strategic.

    Returns one of:
        "explanation"  — what is X, how does X work
        "comparison"   — compare A vs B, A versus B
        "analysis"     — analyze/assess/evaluate causes, implications, dynamics
        "historical"   — history/evolution/timeline of X
        "strategic"    — market/industry/competition/exports/geopolitics
        "default"      — general or unclear intent
    """
    # Explicit analytical verbs in the message — strong signal for analysis format
    _EXPLICIT_ANALYZE = re.compile(
        r'\b(analyz[ei]|analyse|assess\w*|evaluat\w*|breakdown\s+of|break\s+down)\b', re.I
    )

    if intent == "compare":
        return "comparison"
    # Only override to "analysis" when the user explicitly uses an analytical verb.
    # Implicit analyze matches (e.g. "supply chain") fall through to topic detection.
    if intent == "analyze" and _EXPLICIT_ANALYZE.search(message):
        return "analysis"
    # Historical is more specific than strategic — check first
    if _matches_any(message, _HISTORICAL_PATTERNS):
        return "historical"
    if _matches_any(message, _STRATEGIC_PATTERNS):
        return "strategic"
    # Research/analyze intent without topic-specific signal → general analysis format
    if intent in ("research", "analyze"):
        return "analysis"
    if _matches_any(message, _EXPLANATION_PATTERNS):
        return "explanation"
    return "default"


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def detect_intent(message: str) -> dict:
    """
    Detect research intent from a conversational message.

    Returns
    -------
    {
        "intent":           "compare" | "research" | "analyze" | "normal",
        "recommended_mode": "web_search" | "deep_research" | "normal",
        "query_type":       "comparison" | "research" | "analysis" | "default",
        "subjects":         list[str],   # filled for comparison intent
        "topic":            str,         # cleaned topic string
        "format_intent":    str,         # drives response structure
        "intent_profile":   dict,        # semantic scoring profile
    }

    Priority: compare > research > analyze > normal.
    Regex controls mode routing; semantic layer enriches format_intent and
    provides blended directive for multi-intent prompts.
    """
    msg = message.strip()

    # ── Regex fast-path (mode selection) ─────────────────────────────────────

    # Compare — most specific, check first
    if _matches_any(msg, _COMPARE_PATTERNS):
        subjects = extract_comparison_subjects(msg)
        topic    = " vs ".join(subjects) if subjects else _clean_topic(msg, "compare")
        result = {
            "intent":           "compare",
            "recommended_mode": "web_search",
            "query_type":       "comparison",
            "subjects":         subjects,
            "topic":            topic,
            "format_intent":    _detect_format_intent(msg, "compare"),
        }

    # Research (deep knowledge request)
    elif _matches_any(msg, _RESEARCH_PATTERNS):
        topic = _clean_topic(msg, "research")
        result = {
            "intent":           "research",
            "recommended_mode": "deep_research",
            "query_type":       "research",
            "subjects":         [topic] if topic else [],
            "topic":            topic,
            "format_intent":    _detect_format_intent(msg, "research"),
        }

    # Analyze (structured analysis request)
    elif _matches_any(msg, _ANALYZE_PATTERNS):
        topic = _clean_topic(msg, "analyze")
        result = {
            "intent":           "analyze",
            "recommended_mode": "deep_research",
            "query_type":       "analysis",
            "subjects":         [topic] if topic else [],
            "topic":            topic,
            "format_intent":    _detect_format_intent(msg, "analyze"),
        }

    else:
        result = {
            "intent":           "normal",
            "recommended_mode": "normal",
            "query_type":       "default",
            "subjects":         [],
            "topic":            "",
            "format_intent":    _detect_format_intent(msg, "normal"),
        }

    # ── Semantic scoring layer ────────────────────────────────────────────────
    # Scores the message across 9 dimensions; produces blended format directive
    # for multi-intent prompts. Does NOT override mode routing above.
    from .semantic_intent_service import score_intents
    intent_profile = score_intents(msg)

    # When regex produced no format signal ("default"), let semantic primary win
    if result["format_intent"] == "default" and intent_profile["primary_intent"] != "default":
        result["format_intent"] = intent_profile["primary_intent"]

    result["intent_profile"] = intent_profile
    return result


def extract_comparison_subjects(message: str) -> list[str]:
    """
    Extract [subject_a, subject_b] from compare-style messages.

    Examples
    --------
    "Compare Indian vs Chinese pharma" → ["Indian", "Chinese pharma"]
    "Indian exports versus Chinese exports" → ["Indian exports", "Chinese exports"]
    "difference between PyTorch and TensorFlow" → ["PyTorch", "TensorFlow"]
    """
    for pattern in (_VS_RE, _VERSUS_RE, _BETWEEN_RE, _COMPARE_AND):
        m = pattern.search(message)
        if m:
            a = _strip_compare_verbs(m.group(1).strip())
            b = re.sub(r'[?.!,]+$', '', m.group(2).strip())
            if a and b:
                return [a, b]
    return []


# ═══════════════════════════════════════════════════════════════════════════════
# Private helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _matches_any(text: str, patterns: list[re.Pattern]) -> bool:
    return any(p.search(text) for p in patterns)


def _strip_compare_verbs(text: str) -> str:
    return re.sub(r'^(?:compare|contrast)\s+', '', text, flags=re.I).strip()


def _clean_topic(message: str, intent_verb: str) -> str:
    """Remove intent trigger words to surface the core topic."""
    cleaned = _STRIP_PREFIX.sub('', message.strip())
    # Also strip the raw intent verb if it appears at the start
    cleaned = re.sub(rf'^{re.escape(intent_verb)}\s+', '', cleaned, flags=re.I)
    return re.sub(r'[?.!]+$', '', cleaned.strip())
