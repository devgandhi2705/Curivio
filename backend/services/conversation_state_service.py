"""
Persistent conversation knowledge state for compound analytical reasoning.

Tracks what has been established, raised, and left unresolved across all turns
in a chat session. Extracted from structured and plain-text responses without
any additional LLM calls.

Injected back into every subsequent prompt so the AI can build on prior
mechanisms, reference established causal chains, and engage open tensions
rather than re-explaining from scratch.

Storage: one JSON blob per session in `conversation_knowledge_state`.

Public API
----------
update_state(session_id, user_message, response_text, topic_hint,
             structured_response, domain)          → None  (fire-and-forget)
get_state(session_id)                              → dict
format_state_for_prompt(state)                     → str   (ready to inject)
enrich_with_thread_followups(recommendations, state) → dict
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from ..utils.db import get_connection

logger = logging.getLogger(__name__)

# Caps on list lengths to keep the state bounded
_MAX_MECHANISMS   = 15
_MAX_UNRESOLVED   = 6
_MAX_STRATEGIC    = 8
_MAX_COMPARATIVE  = 5
_MAX_CAUSAL       = 6
_MAX_CONTRADICTIONS = 6
_MAX_MOMENTUM     = 5  # recent user questions kept for follow-up framing

# Minimum state richness required before injecting into prompt
_MIN_TURNS_FOR_INJECTION = 2
_GENERIC_SECTION_TITLES  = frozenset({
    "overview", "introduction", "summary", "conclusion", "background",
    "key takeaways", "key findings", "resources", "next steps",
})

# Signals for causal sentence detection in plain text
_CAUSAL_RE = re.compile(
    r'\b(because|led to|resulted in|enabled|prevented|drove|caused by|'
    r'therefore|hence|thus|stemm\w+|originat\w+)\b',
    re.I,
)
# Signals for contradictions / tensions
_CONTRAST_RE = re.compile(
    r'\b(despite|however|paradoxically|yet\b|although|even though|'
    r'on the other hand|counterintuitively|surprisingly)\b',
    re.I,
)


# ── Public API ────────────────────────────────────────────────────────────────

def update_state(
    session_id:          str,
    user_message:        str,
    response_text:       str,
    topic_hint:          str | None        = None,
    structured_response: dict | None       = None,
    domain:              str | None        = None,
) -> None:
    """
    Update the knowledge state after each conversational turn.

    Extraction sources (no LLM calls):
    - Structured JSON response: title, key_takeaways, next_topics, section titles
    - Plain text response: first causal sentence, contrast phrases
    - User message: comparison subjects, causal framing, topic signal

    Errors are swallowed (non-fatal — state enrichment is best-effort).
    """
    try:
        state = _load_state(session_id) or _empty_state()

        # ── Domain ────────────────────────────────────────────────────────────
        if domain and domain not in ("", "General"):
            state["active_domain"] = domain

        # ── Current thread ────────────────────────────────────────────────────
        if structured_response:
            title = (structured_response.get("title") or "").strip()
            if title:
                state["current_thread"] = title
        if not state["current_thread"] and topic_hint:
            state["current_thread"] = topic_hint

        # ── Extract from structured JSON response ─────────────────────────────
        if structured_response:
            _extract_from_structured(state, structured_response)

        # ── Extract from plain-text response ──────────────────────────────────
        elif response_text:
            _extract_from_plain_text(state, response_text, topic_hint)

        # ── Extract from user message (always) ────────────────────────────────
        _extract_from_user_message(state, user_message)

        # ── Update knowledge depth estimate ───────────────────────────────────
        state["turn_count"]           = state.get("turn_count", 0) + 1
        state["user_knowledge_depth"] = _assess_knowledge_depth(state)
        state["last_updated_at"]      = _now()

        _save_state(session_id, state)

    except Exception:
        logger.exception(
            "conversation_state_service: update_state failed for session %r (non-fatal)",
            session_id,
        )


def get_state(session_id: str) -> dict:
    """
    Retrieve the current knowledge state for *session_id*.
    Returns an empty state dict on miss or error.
    """
    try:
        return _load_state(session_id) or _empty_state()
    except Exception:
        logger.exception(
            "conversation_state_service: get_state failed for session %r", session_id
        )
        return _empty_state()


def format_state_for_prompt(state: dict) -> str:
    """
    Format the knowledge state into a compact, ready-to-inject system prompt section.

    Returns empty string when the state is too sparse to be useful.
    """
    if not _is_useful(state):
        return ""

    lines: list[str] = []

    thread = state.get("current_thread", "")
    domain = state.get("active_domain", "")

    # Header
    header = "ACTIVE CONVERSATION THREAD:"
    if thread:
        header_body = f"Analyzing: \"{thread}\""
        if domain:
            header_body += f"  [{domain}]"
        lines += [header, header_body]
    else:
        lines.append(header)

    # Established mechanisms
    mechanisms = state.get("mechanisms_covered", [])
    if mechanisms:
        lines.append("\nEstablished this session (build directly on these — do not re-explain):")
        for m in mechanisms[:6]:
            lines.append(f"• {m}")

    # Unresolved tensions
    unresolved = state.get("unresolved_questions", [])
    if unresolved:
        lines.append("\nOpen analytical tensions (address or deepen if relevant):")
        for q in unresolved[:3]:
            lines.append(f"• {q}")

    # Contradictions
    contradictions = state.get("contradictions_surfaced", [])
    if contradictions:
        lines.append("\nContradictions in play:")
        for c in contradictions[:2]:
            lines.append(f"• {c}")

    # Comparative context
    comparative = state.get("comparative_contexts", [])
    if comparative:
        lines.append(f"\nComparative frame: {comparative[0]}")

    # Knowledge depth signal
    depth = state.get("user_knowledge_depth", "surface")
    depth_note = {
        "surface":  "Early in this thread — introduce mechanisms clearly.",
        "building": "Mid-depth — connect new questions to established mechanisms above.",
        "deep":     "Advanced — skip basics, build directly on what's already established.",
    }.get(depth, "")
    if depth_note:
        lines.append(f"\nEngagement depth: {depth} — {depth_note}")

    return "\n".join(lines)


def enrich_with_thread_followups(
    recommendations: dict,
    state:           dict,
    intent_profile:  dict | None = None,
    domain:          str         = "",
) -> dict:
    """
    Replace generic follow-ups with thread-aware, category-specific questions.

    Uses follow_up_intelligence_service to generate questions phrased from
    active conversation state (mechanisms, contradictions, comparisons, causal
    chains).  Falls back to the existing recommendations when the state is too
    sparse to generate specific items.

    Deduplicates strategic follow-ups against existing next_topics so the
    final list never repeats the same question in different forms.
    """
    if not _is_useful(state):
        return recommendations

    topic_hint = state.get("current_thread") or None

    try:
        from .follow_up_intelligence_service import generate_strategic_followups
        strategic = generate_strategic_followups(
            state          = state,
            topic_hint     = topic_hint,
            intent_profile = intent_profile,
            domain         = domain,
            max_items      = 4,
        )
    except Exception:
        logger.exception(
            "conversation_state_service: strategic followup generation failed (non-fatal)"
        )
        strategic = []

    if not strategic:
        return recommendations

    # Merge: strategic items first, then existing next_topics (deduplicated)
    strategic_keys = {t["topic"].lower()[:50] for t in strategic}
    existing_next  = [
        t for t in recommendations.get("next_topics", [])
        if t.get("topic", "").lower()[:50] not in strategic_keys
    ]
    merged_next = (strategic + existing_next)[:5]
    return {**recommendations, "next_topics": merged_next}


# ── Extraction helpers ────────────────────────────────────────────────────────

def _extract_from_structured(state: dict, structured: dict) -> None:
    """Harvest knowledge from a structured JSON response (no LLM)."""
    # key_takeaways → mechanisms_covered
    for tk in structured.get("key_takeaways", [])[:5]:
        if isinstance(tk, str) and tk.strip():
            text = tk.strip()[:160]
            _add_unique(state["mechanisms_covered"], text, _MAX_MECHANISMS)
            # If the takeaway contains contrast language → also a contradiction
            if _CONTRAST_RE.search(text):
                _add_unique(state["contradictions_surfaced"], text[:160], _MAX_CONTRADICTIONS)

    # Section titles → strategic themes
    for sec in structured.get("sections", []):
        title = (sec.get("title") or "").strip()
        if title and title.lower() not in _GENERIC_SECTION_TITLES and len(title) > 4:
            _add_unique(state["strategic_themes"], title, _MAX_STRATEGIC)

    # next_topics → unresolved questions (these are phrased as questions/angles)
    for nt in structured.get("next_topics", [])[:3]:
        if isinstance(nt, str) and nt.strip():
            _add_unique(state["unresolved_questions"], nt.strip()[:130], _MAX_UNRESOLVED)


def _extract_from_plain_text(
    state: dict, response_text: str, topic_hint: str | None
) -> None:
    """Harvest knowledge from a plain-text response (no LLM)."""
    if not response_text:
        return

    # Set thread from topic_hint if not already set
    if topic_hint and not state["current_thread"]:
        state["current_thread"] = topic_hint

    # Scan first 25 sentences for causal and contrast signals
    sentences = re.split(r'(?<=[.!?])\s+', response_text.strip())
    causal_added    = 0
    contrast_added  = 0

    for sent in sentences[:25]:
        sent = sent.strip()
        if len(sent) < 25 or len(sent) > 200:
            continue
        # Skip markdown headings / bullet points
        if sent.startswith(("#", "-", "*", "•")):
            continue

        if causal_added < 2 and _CAUSAL_RE.search(sent):
            _add_unique(state["mechanisms_covered"], sent[:160], _MAX_MECHANISMS)
            causal_added += 1

        if contrast_added < 1 and _CONTRAST_RE.search(sent):
            _add_unique(state["contradictions_surfaced"], sent[:160], _MAX_CONTRADICTIONS)
            contrast_added += 1

        if causal_added >= 2 and contrast_added >= 1:
            break


def _extract_from_user_message(state: dict, user_message: str) -> None:
    """Harvest signals from the user's question itself."""
    if not user_message:
        return

    # Recent curiosity momentum — verbatim question, truncated
    fragment = user_message.strip()[:100]
    if state["curiosity_momentum"] and state["curiosity_momentum"][0] == fragment:
        pass  # don't duplicate
    else:
        state["curiosity_momentum"] = [fragment] + state["curiosity_momentum"][:_MAX_MOMENTUM - 1]

    # Comparative contexts — extract A vs B
    try:
        from .chat_intent_service import extract_comparison_subjects
        subjects = extract_comparison_subjects(user_message)
        if subjects:
            ctx = " vs ".join(subjects[:2])
            _add_unique(state["comparative_contexts"], ctx, _MAX_COMPARATIVE)
    except Exception:
        pass

    # Causal chains — user is asking why something happened
    try:
        from .semantic_intent_service import score_intents
        profile = score_intents(user_message)
        if profile.get("primary_intent") == "causal" and profile.get("intent_scores", {}).get("causal", 0) >= 0.50:
            chain_q = user_message.strip()[:120]
            _add_unique(state["causal_chains"], chain_q, _MAX_CAUSAL)
    except Exception:
        pass


# ── State assessment ──────────────────────────────────────────────────────────

def _assess_knowledge_depth(state: dict) -> str:
    turns      = state.get("turn_count", 0) + 1  # +1 for the current turn
    mechanisms = len(state.get("mechanisms_covered", []))
    if turns >= 7 or mechanisms >= 8:
        return "deep"
    elif turns >= 3 or mechanisms >= 4:
        return "building"
    else:
        return "surface"


def _is_useful(state: dict) -> bool:
    """Return True when the state is rich enough to inject into a prompt."""
    if not state:
        return False
    if state.get("turn_count", 0) < _MIN_TURNS_FOR_INJECTION:
        return False
    has_mechanisms   = bool(state.get("mechanisms_covered"))
    has_unresolved   = bool(state.get("unresolved_questions"))
    has_thread       = bool(state.get("current_thread"))
    return has_mechanisms or has_unresolved or has_thread


# ── Persistence ───────────────────────────────────────────────────────────────

def _empty_state() -> dict:
    return {
        "active_domain":         "",
        "current_thread":        "",
        "mechanisms_covered":    [],
        "unresolved_questions":  [],
        "strategic_themes":      [],
        "comparative_contexts":  [],
        "contradictions_surfaced": [],
        "causal_chains":         [],
        "user_knowledge_depth":  "surface",
        "curiosity_momentum":    [],
        "turn_count":            0,
        "last_updated_at":       "",
    }


def _load_state(session_id: str) -> dict | None:
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT state_json FROM conversation_knowledge_state WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row:
            return json.loads(row["state_json"])
        return None
    except Exception:
        return None


def _save_state(session_id: str, state: dict) -> None:
    now = _now()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO conversation_knowledge_state (session_id, state_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                state_json = excluded.state_json,
                updated_at = excluded.updated_at
            """,
            (session_id, json.dumps(state, ensure_ascii=False), now),
        )


# ── Small utilities ───────────────────────────────────────────────────────────

def _add_unique(lst: list, item: str, max_items: int) -> None:
    """Append *item* to *lst* if not already present (case-insensitive), respecting cap."""
    if len(lst) >= max_items:
        return
    key = item.strip().lower()[:60]
    if not key:
        return
    if any(existing.strip().lower()[:60] == key for existing in lst):
        return
    lst.append(item.strip())


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
