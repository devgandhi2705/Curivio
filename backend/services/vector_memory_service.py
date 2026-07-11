"""
Semantic long-term memory — Chat-3's additive third memory layer.

conversation_state_service.py (session-scoped regex extraction) and
continuity_service.py (cross-session exact topic-string matching) both stay
untouched. Neither can recall a past discussion phrased differently ("neural
nets" vs "neural networks") — continuity_service keys on
value.strip().lower(), an exact match. This module fills that specific gap:
embeds conversation_knowledge_state's extracted entries (not raw messages)
into a sqlite-vec vec0 table and retrieves by cosine similarity, hard-scoped
to user_id so memory never crosses users.

Storage: conversation_memory_vec (vec0 virtual table, backend/database/schema.py)
  embedding float[3072] (Gemini, via backend/llm/embeddings.py) +
  user_id / session_id / topic / entry_text / created_at auxiliary columns.

Population cadence matches conversation_state_service exactly: record_entry()
is called right after every conversation_state_service.update_state() call
(chat_service.py's stream path only — mirrors that path's existing user_id
availability; sync chat() has no user_id and is already dead in production).

Public API
----------
record_entry(user_id, session_id, state) -> None    fire-and-forget, mirrors
                                                     conversation_state_service's
                                                     own error-swallowing contract
search(user_id, query_text, top_k=5) -> list[dict]  hard-scoped to user_id
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from ..llm.embeddings import get_embedding
from ..utils.db import get_connection

logger = logging.getLogger(__name__)

_TOP_K_DEFAULT = 5

# Real cosine distances measured against production data in conversation_memory_vec
# (2026-07-07): genuinely-related pairs (neural nets/neural networks phrasing;
# quantum entanglement asked in web_search vs layman mode) scored 0.0704 and
# 0.2566. Genuinely-unrelated pairs (breakfast vs neural nets; tidal locking vs
# neural nets; tidal locking vs quantum entanglement; etc., 6 pairs total)
# scored between 0.4507 and 0.5385 — a clean, non-overlapping gap. Threshold
# is the midpoint of that gap (max related + min unrelated) / 2, not a round
# guess: (0.2566 + 0.4507) / 2 = 0.3537, rounded down slightly for margin.
_MAX_DISTANCE = 0.35


def _entry_text_from_state(state: dict) -> str:
    """
    Compact text representation of the extracted knowledge state (never raw
    messages). Real rows are often sparse — current_thread + curiosity_momentum
    populated, mechanisms/unresolved empty — so this degrades gracefully.
    """
    parts: list[str] = []
    thread = (state.get("current_thread") or "").strip()
    if thread:
        parts.append(f"Thread: {thread}")
    parts += [m for m in state.get("mechanisms_covered", [])[-3:] if m]
    parts += [q for q in state.get("unresolved_questions", [])[-2:] if q]
    momentum = state.get("curiosity_momentum", [])
    if momentum:
        parts.append(momentum[0])
    return ". ".join(p.strip() for p in parts if p and p.strip())


def record_entry(user_id: str | None, session_id: str, state: dict) -> None:
    """
    Embed and store the current knowledge-state snapshot for later semantic
    recall. Fire-and-forget — errors are logged, never raised.

    user_id is a hard requirement, not a soft default: memory is never stored
    without an owner, since search() scopes strictly by user_id.
    """
    if not user_id:
        return
    text = _entry_text_from_state(state)
    if not text:
        return
    topic = (state.get("current_thread") or "").strip()
    try:
        embedding = get_embedding(text)
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO conversation_memory_vec
                       (embedding, user_id, session_id, topic, entry_text, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    json.dumps(embedding),
                    user_id, session_id, topic, text,
                    datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
    except Exception:
        logger.exception(
            "vector_memory_service: record_entry failed for session %r (non-fatal)",
            session_id,
        )


def search(user_id: str | None, query_text: str, top_k: int = _TOP_K_DEFAULT) -> list[dict]:
    """
    Return up to top_k semantically related past entries for this user only,
    or [] when nothing clears _MAX_DISTANCE — matches the clean-empty-result
    behavior of conversation_state_service/continuity_service instead of
    always forcing the nearest neighbor regardless of actual relevance.

    Hard privacy boundary: user_id is required; results are scoped via a SQL
    WHERE clause on the vec0 table's own user_id column — never cross-user.
    Returns [] on missing user_id/query_text or any error (non-fatal).
    """
    if not user_id or not query_text or not query_text.strip():
        return []
    try:
        query_vec = get_embedding(query_text)
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT entry_text, topic, session_id,
                          vec_distance_cosine(embedding, ?) AS distance
                   FROM   conversation_memory_vec
                   WHERE  user_id = ?
                   ORDER  BY distance ASC
                   LIMIT  ?""",
                (json.dumps(query_vec), user_id, top_k),
            ).fetchall()
        return [dict(r) for r in rows if r["distance"] < _MAX_DISTANCE]
    except Exception:
        logger.exception(
            "vector_memory_service: search failed for user %r (non-fatal)", user_id
        )
        return []


def format_for_prompt(entries: list[dict], max_items: int = 3) -> str:
    """
    Format search() results into a compact, clearly-labeled prompt section.
    Returns "" when entries is empty (composer skips empty sections).
    """
    if not entries:
        return ""
    lines = ["Related past discussion (different session, same user):"]
    for e in entries[:max_items]:
        topic = e.get("topic") or ""
        text  = e.get("entry_text") or ""
        if topic:
            lines.append(f"  • [{topic}] {text}")
        else:
            lines.append(f"  • {text}")
    return "\n".join(lines)
