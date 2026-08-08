import json
import uuid
from datetime import datetime, timezone
from typing import Optional
from backend.utils.db import get_connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_collection(row) -> dict:
    return {
        "collection_id":  row["collection_id"],
        "name":           row["name"],
        "description":    row["description"] or "",
        "color":          row["color"] or "blue",
        "created_at":     row["created_at"],
        "updated_at":     row["updated_at"],
        "bookmark_count": row["bookmark_count"] if "bookmark_count" in row.keys() else 0,
    }


def _row_to_bookmark(row) -> dict:
    return {
        "bookmark_id":             row["bookmark_id"],
        "collection_id":           row["collection_id"],
        "title":                   row["title"],
        "summary":                 row["summary"] or "",
        "content_type":            row["content_type"],
        "source_url":              row["source_url"] or "",
        "project_id":              row["project_id"] or "",
        "project_name":            row["project_name"] or "",
        "tags":                    json.loads(row["tags"] or "[]"),
        "saved_at":                row["saved_at"],
        "ai_generated_notes":      row["ai_generated_notes"] or "",
        "retrieval_metadata":      json.loads(row["retrieval_metadata"] or "{}"),
        "related_topics":          json.loads(row["related_topics"] or "[]"),
        "source_type":             row["source_type"] or "feed",
        "conversation_reference":  row["conversation_reference"] or "",
        "deep_research_reference": row["deep_research_reference"] or "",
        "content_snapshot":        row["content_snapshot"] or "",
    }


# ── Collections ───────────────────────────────────────────────────────────────

def list_collections(user_id: str | None = None) -> list[dict]:
    with get_connection() as conn:
        if user_id:
            rows = conn.execute("""
                SELECT bc.*, COUNT(b.bookmark_id) as bookmark_count
                FROM bookmark_collections bc
                LEFT JOIN bookmarks b ON b.collection_id = bc.collection_id
                WHERE bc.user_id = ?
                GROUP BY bc.collection_id
                ORDER BY bc.updated_at DESC
            """, (user_id,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT bc.*, COUNT(b.bookmark_id) as bookmark_count
                FROM bookmark_collections bc
                LEFT JOIN bookmarks b ON b.collection_id = bc.collection_id
                GROUP BY bc.collection_id
                ORDER BY bc.updated_at DESC
            """).fetchall()
    return [_row_to_collection(r) for r in rows]


def create_collection(name: str, description: str = "", color: str = "blue", user_id: str | None = None) -> dict:
    cid = str(uuid.uuid4())
    now = _now()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO bookmark_collections (collection_id, name, description, color, created_at, updated_at, user_id) VALUES (?,?,?,?,?,?,?)",
            (cid, name.strip(), description.strip(), color, now, now, user_id),
        )
    return {
        "collection_id":  cid,
        "name":           name.strip(),
        "description":    description.strip(),
        "color":          color,
        "created_at":     now,
        "updated_at":     now,
        "bookmark_count": 0,
    }


def update_collection(collection_id: str, name: Optional[str] = None, description: Optional[str] = None, color: Optional[str] = None) -> Optional[dict]:
    now = _now()
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM bookmark_collections WHERE collection_id=?", (collection_id,)).fetchone()
        if not row:
            return None
        new_name  = name.strip()        if name        is not None else row["name"]
        new_desc  = description.strip() if description is not None else row["description"]
        new_color = color               if color       is not None else row["color"]
        conn.execute(
            "UPDATE bookmark_collections SET name=?, description=?, color=?, updated_at=? WHERE collection_id=?",
            (new_name, new_desc, new_color, now, collection_id),
        )
        count = conn.execute("SELECT COUNT(*) FROM bookmarks WHERE collection_id=?", (collection_id,)).fetchone()[0]
    return {
        "collection_id":  collection_id,
        "name":           new_name,
        "description":    new_desc,
        "color":          new_color,
        "created_at":     row["created_at"],
        "updated_at":     now,
        "bookmark_count": count,
    }


def delete_collection(collection_id: str) -> bool:
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM bookmark_collections WHERE collection_id=?", (collection_id,))
    return cur.rowcount > 0


def get_collection_owner(collection_id: str) -> str | None:
    """
    Return the recorded user_id for collection_id, or None if the collection
    doesn't exist OR predates per-collection ownership tracking (Chat-R10e:
    3 of 5 real rows have a NULL user_id). Fails closed — DB errors propagate.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT user_id FROM bookmark_collections WHERE collection_id=?", (collection_id,)
        ).fetchone()
    return row["user_id"] if row else None


# ── Bookmarks ─────────────────────────────────────────────────────────────────

def list_bookmarks(
    collection_id: Optional[str] = None,
    content_type:  Optional[str] = None,
    source_type:   Optional[str] = None,
    project_id:    Optional[str] = None,
    search:        Optional[str] = None,
    limit: int = 100,
    user_id:       Optional[str] = None,
) -> list[dict]:
    clauses = []
    params  = []
    if user_id:
        clauses.append("bc.user_id = ?");      params.append(user_id)
    if collection_id:
        clauses.append("b.collection_id = ?"); params.append(collection_id)
    if content_type:
        clauses.append("b.content_type = ?");  params.append(content_type)
    if source_type:
        clauses.append("b.source_type = ?");   params.append(source_type)
    if project_id:
        clauses.append("b.project_id = ?");    params.append(project_id)
    if search:
        clauses.append("(b.title LIKE ? OR b.summary LIKE ? OR b.tags LIKE ?)")
        term = f"%{search}%"
        params += [term, term, term]
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    with get_connection() as conn:
        rows = conn.execute(f"""
            SELECT b.*, bc.name as collection_name, bc.color as collection_color
            FROM bookmarks b
            JOIN bookmark_collections bc ON bc.collection_id = b.collection_id
            {where}
            ORDER BY b.saved_at DESC
            LIMIT ?
        """, params).fetchall()
    result = []
    for r in rows:
        bm = _row_to_bookmark(r)
        bm["collection_name"]  = r["collection_name"]
        bm["collection_color"] = r["collection_color"]
        result.append(bm)
    return result


def create_bookmark(
    collection_id:            str,
    title:                    str,
    summary:                  str = "",
    content_type:             str = "feed_article",
    source_url:               str = "",
    project_id:               str = "",
    project_name:             str = "",
    tags:                     list = None,
    ai_generated_notes:       str = "",
    retrieval_metadata:       dict = None,
    related_topics:           list = None,
    source_type:              str = "feed",
    conversation_reference:   str = "",
    deep_research_reference:  str = "",
    content_snapshot:         str = "",
) -> Optional[dict]:
    with get_connection() as conn:
        col_exists = conn.execute("SELECT 1 FROM bookmark_collections WHERE collection_id=?", (collection_id,)).fetchone()
        if not col_exists:
            return None

        # Deduplicate: if same title already exists in this collection, return it as-is
        existing = conn.execute(
            "SELECT bookmark_id FROM bookmarks WHERE collection_id=? AND title=?",
            (collection_id, title.strip()),
        ).fetchone()
        if existing:
            return get_bookmark(existing["bookmark_id"])

    bid = str(uuid.uuid4())
    now = _now()
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO bookmarks (
                bookmark_id, collection_id, title, summary, content_type,
                source_url, project_id, project_name, tags, saved_at,
                ai_generated_notes, retrieval_metadata, related_topics,
                source_type, conversation_reference, deep_research_reference, content_snapshot
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            bid, collection_id, title.strip(), summary, content_type,
            source_url, project_id, project_name,
            json.dumps(tags or []), now,
            ai_generated_notes,
            json.dumps(retrieval_metadata or {}),
            json.dumps(related_topics or []),
            source_type, conversation_reference, deep_research_reference, content_snapshot,
        ))
        conn.execute("UPDATE bookmark_collections SET updated_at=? WHERE collection_id=?", (now, collection_id))
    return get_bookmark(bid)


def get_bookmark(bookmark_id: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute("""
            SELECT b.*, bc.name as collection_name, bc.color as collection_color
            FROM bookmarks b
            JOIN bookmark_collections bc ON bc.collection_id = b.collection_id
            WHERE b.bookmark_id=?
        """, (bookmark_id,)).fetchone()
    if not row:
        return None
    bm = _row_to_bookmark(row)
    bm["collection_name"]  = row["collection_name"]
    bm["collection_color"] = row["collection_color"]
    return bm


def update_bookmark(
    bookmark_id: str,
    tags:                  Optional[list] = None,
    ai_generated_notes:    Optional[str]  = None,
    collection_id:         Optional[str]  = None,
) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM bookmarks WHERE bookmark_id=?", (bookmark_id,)).fetchone()
        if not row:
            return None
        new_tags   = json.dumps(tags)              if tags                is not None else row["tags"]
        new_notes  = ai_generated_notes            if ai_generated_notes  is not None else row["ai_generated_notes"]
        new_cid    = collection_id                 if collection_id       is not None else row["collection_id"]
        conn.execute(
            "UPDATE bookmarks SET tags=?, ai_generated_notes=?, collection_id=? WHERE bookmark_id=?",
            (new_tags, new_notes, new_cid, bookmark_id),
        )
    return get_bookmark(bookmark_id)


def delete_bookmark(bookmark_id: str) -> bool:
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM bookmarks WHERE bookmark_id=?", (bookmark_id,))
    return cur.rowcount > 0


def get_bookmark_owner(bookmark_id: str) -> str | None:
    """
    Return the user_id that owns bookmark_id's collection, or None if the
    bookmark doesn't exist OR its collection is legacy/unclaimed (NULL
    user_id — bookmarks have no owner column of their own, ownership is
    always derived through bookmark_collections). Fails closed.
    """
    with get_connection() as conn:
        row = conn.execute(
            """SELECT bc.user_id
               FROM bookmarks b
               JOIN bookmark_collections bc ON bc.collection_id = b.collection_id
               WHERE b.bookmark_id = ?""",
            (bookmark_id,),
        ).fetchone()
    return row["user_id"] if row else None
