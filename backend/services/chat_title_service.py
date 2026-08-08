"""
Conversation title generation and management.

Titles are generated during the same AI call — no extra LLM round-trip.
The LLM is asked to prefix its response with [TITLE: <short title>], which
the streaming parser intercepts, strips from the visible content, and stores.

Public API (pure helpers)
-------------------------
make_title_system_note()           → str   system message to inject
extract_title(text)                → str | None   parse from full response text
strip_title_prefix(text)           → str   remove [TITLE: ...] from response

Public API (DB)
---------------
save_session_title(session_id, title)    → None  (won't overwrite a manual rename)
rename_session(session_id, title)        → None  (always overwrites)
get_session_title(session_id)            → str | None
get_session_owner(session_id)            → str | None  (user_id, or None if unowned/missing)
list_sessions_with_titles(limit)         → list[dict]
search_sessions(query, limit)            → list[dict]  (+ match_snippet field)
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# The exact prefix the LLM is asked to produce
_TITLE_START = "[TITLE:"
_TITLE_RE    = re.compile(r"\[TITLE:\s*(.+?)\]", re.DOTALL)
_MAX_TITLE_LEN = 80   # truncate runaway titles
_BUFFER_LIMIT  = 250  # stop looking after this many streamed chars


# ═══════════════════════════════════════════════════════════════════════════════
# Pure helpers — no I/O, fully testable
# ═══════════════════════════════════════════════════════════════════════════════

def make_title_system_note() -> str:
    """
    System message that instructs the LLM to prepend a short title.

    Injected only for new sessions (history is empty).
    """
    return (
        "This is the first message in this conversation. "
        "Begin your response with exactly one line in this format:\n"
        "[TITLE: <4–6 word topic title>]\n"
        "Then write your complete answer starting on the next line. "
        "Keep the title concise and specific — e.g. [TITLE: AI in Manufacturing Overview]."
    )


def extract_title(text: str) -> str | None:
    """
    Extract the title from a response that contains [TITLE: ...].

    Returns the title string (stripped, truncated) or None if not found.
    """
    m = _TITLE_RE.search(text)
    if not m:
        return None
    return m.group(1).strip()[:_MAX_TITLE_LEN] or None


def strip_title_prefix(text: str) -> str:
    """
    Remove the [TITLE: ...] line from a response so the user only sees content.

    Strips any leading whitespace / newlines that follow the title line.
    """
    return _TITLE_RE.sub("", text).lstrip("\n").strip()


def generate_fallback_title(message: str, topic_hint: str | None = None) -> str:
    """
    Derive a session title from the user's first message without an API call.

    Used when the LLM does not output the [TITLE: ...] prefix.
    Preference order: topic_hint → cleaned message text → "Conversation".
    """
    text = (topic_hint or message or "").strip()
    # Strip trailing punctuation
    text = re.sub(r"[?!.…]+$", "", text).strip()
    # Capitalise first letter
    if text:
        text = text[0].upper() + text[1:]
    # Truncate at a word boundary
    if len(text) > 55:
        truncated  = text[:52]
        last_space = truncated.rfind(" ")
        text = (truncated[:last_space] if last_space > 20 else truncated) + "…"
    return text or "Conversation"


def stream_extract_state() -> dict:
    """
    Return the initial state object for the streaming title parser.

    Pass this state to advance_stream_state() on every incoming chunk.
    """
    return {
        "phase":  "buffering",  # "buffering" | "passthrough"
        "buf":    "",
        "title":  None,
    }


def advance_stream_state(state: dict, chunk: str) -> dict:
    """
    Advance the streaming parser state machine with one new chunk.

    Returns a dict:
      {
        "forward":  str | None,  — text to forward to the client (None = suppress)
        "title":    str | None,  — title extracted (only set once, first time found)
        "phase":    str,         — updated phase
      }

    Callers should:
      1. If forward is not None, yield it as a chunk event.
      2. If title is not None, yield a title event.
    """
    if state["phase"] == "passthrough":
        return {"forward": chunk, "title": None, "phase": "passthrough"}

    # --- Buffering phase ---
    state["buf"] += chunk
    buf = state["buf"]

    # Check if buffer contains a complete [TITLE: ...] marker
    stripped = buf.lstrip()
    if stripped.startswith(_TITLE_START):
        if "]" in stripped:
            # Complete title found — extract and switch to passthrough
            m = _TITLE_RE.match(stripped)
            title = m.group(1).strip()[:_MAX_TITLE_LEN] if m else None

            # Everything after the ] is the actual response content
            end = stripped.index("]")
            remainder = stripped[end + 1:].lstrip("\n")

            state["phase"] = "passthrough"
            state["buf"]   = ""
            state["title"] = title
            return {
                "forward": remainder if remainder else None,
                "title":   title,
                "phase":   "passthrough",
            }
        # Title marker started but not yet closed — keep buffering
        if len(buf) < _BUFFER_LIMIT:
            return {"forward": None, "title": None, "phase": "buffering"}

    # Buffer too large or doesn't start with [TITLE: — give up and flush
    state["phase"] = "passthrough"
    state["buf"]   = ""
    return {"forward": buf, "title": None, "phase": "passthrough"}


# ═══════════════════════════════════════════════════════════════════════════════
# DB operations
# ═══════════════════════════════════════════════════════════════════════════════

def save_session_title(session_id: str, title: str) -> None:
    """
    Persist an auto-generated title.

    Creates the row if absent; updates title only when it is still NULL so a
    manual rename is never overwritten by a subsequent auto-generation attempt.
    """
    if not title or not title.strip():
        return
    try:
        from ..utils.db import get_connection
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO chat_sessions (session_id, title) VALUES (?, ?)
                   ON CONFLICT(session_id) DO UPDATE
                   SET title = excluded.title WHERE chat_sessions.title IS NULL""",
                (session_id, title.strip()),
            )
    except Exception:
        logger.debug("[title] save_session_title failed for %r", session_id)


def ensure_session_owner(session_id: str, user_id: str) -> None:
    """Register user_id on a session row (creates if absent; never overwrites an existing owner)."""
    try:
        from ..utils.db import get_connection
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO chat_sessions (session_id, user_id) VALUES (?, ?)
                   ON CONFLICT(session_id) DO UPDATE
                   SET user_id = COALESCE(chat_sessions.user_id, excluded.user_id)""",
                (session_id, user_id),
            )
    except Exception:
        logger.debug("[title] ensure_session_owner failed for %r", session_id)


def rename_session(session_id: str, title: str) -> None:
    """Persist a user-supplied title (always overwrites)."""
    if not title or not title.strip():
        raise ValueError("title must not be blank")
    from ..utils.db import get_connection
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO chat_sessions (session_id, title) VALUES (?, ?)
            ON CONFLICT(session_id) DO UPDATE SET title = excluded.title
            """,
            (session_id, title.strip()[:100]),
        )


def get_session_title(session_id: str) -> str | None:
    """Return the stored title for a session, or None."""
    try:
        from ..utils.db import get_connection
        with get_connection() as conn:
            row = conn.execute(
                "SELECT title FROM chat_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return row["title"] if row else None
    except Exception:
        return None


def get_session_owner(session_id: str) -> str | None:
    """
    Return the recorded user_id for session_id, or None if the session doesn't
    exist OR exists but predates per-session ownership tracking (Chat-R10d:
    99 of 175 real rows have a NULL user_id — legacy/pre-auth sessions and
    smoke-test fixtures). Callers must not distinguish those two cases from
    the return value alone — that's deliberate, see require_session_access.

    Unlike get_session_title, this does not swallow DB errors — an
    authorization check must fail closed, not silently return "no owner".
    """
    from ..utils.db import get_connection
    with get_connection() as conn:
        row = conn.execute(
            "SELECT user_id FROM chat_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    return row["user_id"] if row else None


def search_sessions(query: str, limit: int = 20, user_id: str | None = None) -> list[dict]:
    """
    Full-text search over session titles and message content using LIKE.

    Returns the same shape as list_sessions_with_titles() plus a
    `match_snippet` field: ~100 chars of context around the first match.
    Feed-linked sessions are excluded (same as list_sessions_with_titles).
    """
    from ..utils.db import get_connection

    q = query.strip()
    if not q:
        return []

    q_like = f"%{q.lower()}%"

    user_filter = "AND s.user_id = ?" if user_id else ""
    params = (q_like, q_like, *([user_id] if user_id else []), limit)

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT   agg.session_id,
                     agg.message_count,
                     agg.last_active_at,
                     agg.first_topic_hint,
                     s.title
            FROM (
                SELECT   session_id,
                         COUNT(CASE WHEN role = 'user' THEN 1 END) AS message_count,
                         MAX(created_at)  AS last_active_at,
                         MIN(topic_hint)  AS first_topic_hint
                FROM     chat_messages
                GROUP BY session_id
            ) agg
            LEFT JOIN chat_sessions s ON s.session_id = agg.session_id
            WHERE (
                    EXISTS (
                        SELECT 1 FROM chat_messages m
                        WHERE  m.session_id = agg.session_id
                          AND  LOWER(m.content) LIKE ?
                    )
                 OR LOWER(COALESCE(s.title, '')) LIKE ?
            )
            {user_filter}
            AND NOT EXISTS (
                SELECT 1 FROM feed_chat_links fl
                WHERE  fl.session_id = agg.session_id
            )
            ORDER BY agg.last_active_at DESC
            LIMIT    ?
            """,
            params,
        ).fetchall()

        result = []
        for r in rows:
            snippet_row = conn.execute(
                """SELECT content FROM chat_messages
                   WHERE  session_id = ? AND LOWER(content) LIKE ?
                   ORDER BY created_at ASC LIMIT 1""",
                (r["session_id"], q_like),
            ).fetchone()

            # Extract context window around the match instead of truncating from start
            snippet = None
            if snippet_row:
                content = snippet_row["content"]
                idx = content.lower().find(q.lower())
                if idx == -1:
                    snippet = content[:100]
                else:
                    start = max(0, idx - 25)
                    end   = min(len(content), idx + len(q) + 60)
                    prefix = "…" if start > 0 else ""
                    suffix = "…" if end < len(content) else ""
                    snippet = prefix + content[start:end] + suffix

            result.append({
                "session_id":       r["session_id"],
                "message_count":    r["message_count"],
                "last_active_at":   r["last_active_at"],
                "first_topic_hint": r["first_topic_hint"],
                "title":            r["title"] or r["first_topic_hint"],
                "match_snippet":    snippet,
            })

    return result


def get_session_conversation_mode(session_id: str) -> str:
    """Return the stored conversation_mode for a session ('normal' or 'layman')."""
    try:
        from ..utils.db import get_connection
        with get_connection() as conn:
            row = conn.execute(
                "SELECT conversation_mode FROM chat_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return row["conversation_mode"] if row and row["conversation_mode"] else "normal"
    except Exception:
        return "normal"


def set_session_conversation_mode(session_id: str, mode: str) -> None:
    """Persist the conversation_mode for a session; creates the row if absent."""
    try:
        from ..utils.db import get_connection
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO chat_sessions (session_id, conversation_mode)
                   VALUES (?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET conversation_mode = excluded.conversation_mode""",
                (session_id, mode),
            )
    except Exception:
        logger.debug("[title] set_session_conversation_mode failed for %r", session_id)


def list_sessions_with_titles(limit: int = 20, user_id: str | None = None) -> list[dict]:
    """
    Return recent sessions with titles, message counts, and last-active timestamps.

    Replaces chat_service.list_sessions() — includes title from chat_sessions.
    Title fallback order: chat_sessions.title → first_topic_hint → None.
    """
    from ..utils.db import get_connection
    with get_connection() as conn:
        if user_id:
            rows = conn.execute(
                """
                SELECT   m.session_id,
                         COUNT(CASE WHEN m.role = 'user' THEN 1 END) AS message_count,
                         MAX(m.created_at) AS last_active_at,
                         MIN(m.topic_hint) AS first_topic_hint,
                         s.title
                FROM     chat_messages m
                LEFT JOIN chat_sessions s ON s.session_id = m.session_id
                WHERE NOT EXISTS (
                    SELECT 1 FROM feed_chat_links fl WHERE fl.session_id = m.session_id
                )
                AND s.user_id = ?
                GROUP BY m.session_id
                ORDER BY last_active_at DESC
                LIMIT    ?
                """,
                (user_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT   m.session_id,
                         COUNT(CASE WHEN m.role = 'user' THEN 1 END) AS message_count,
                         MAX(m.created_at) AS last_active_at,
                         MIN(m.topic_hint) AS first_topic_hint,
                         s.title
                FROM     chat_messages m
                LEFT JOIN chat_sessions s ON s.session_id = m.session_id
                WHERE NOT EXISTS (
                    SELECT 1 FROM feed_chat_links fl WHERE fl.session_id = m.session_id
                )
                GROUP BY m.session_id
                ORDER BY last_active_at DESC
                LIMIT    ?
                """,
                (limit,),
            ).fetchall()
    return [
        {
            "session_id":       r["session_id"],
            "message_count":    r["message_count"],
            "last_active_at":   r["last_active_at"],
            "first_topic_hint": r["first_topic_hint"],
            "title":            r["title"] or r["first_topic_hint"],
        }
        for r in rows
    ]
