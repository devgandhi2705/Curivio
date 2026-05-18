"""
Research intent detection for conversational chat messages.

Detects when a user message contains a research intent (compare, research,
analyze) and returns the recommended chat mode and structured query metadata.

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
    }

    Priority: compare > research > analyze > normal.
    """
    msg = message.strip()

    # Compare — most specific, check first
    if _matches_any(msg, _COMPARE_PATTERNS):
        subjects = extract_comparison_subjects(msg)
        topic    = " vs ".join(subjects) if subjects else _clean_topic(msg, "compare")
        return {
            "intent":           "compare",
            "recommended_mode": "web_search",
            "query_type":       "comparison",
            "subjects":         subjects,
            "topic":            topic,
        }

    # Research (deep knowledge request)
    if _matches_any(msg, _RESEARCH_PATTERNS):
        topic = _clean_topic(msg, "research")
        return {
            "intent":           "research",
            "recommended_mode": "deep_research",
            "query_type":       "research",
            "subjects":         [topic] if topic else [],
            "topic":            topic,
        }

    # Analyze (structured analysis request)
    if _matches_any(msg, _ANALYZE_PATTERNS):
        topic = _clean_topic(msg, "analyze")
        return {
            "intent":           "analyze",
            "recommended_mode": "deep_research",
            "query_type":       "analysis",
            "subjects":         [topic] if topic else [],
            "topic":            topic,
        }

    return {
        "intent":           "normal",
        "recommended_mode": "normal",
        "query_type":       "default",
        "subjects":         [],
        "topic":            "",
    }


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
