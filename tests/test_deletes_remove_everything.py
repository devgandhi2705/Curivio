"""
Deleting something in the app removes what it owns — database rows AND stored files.

  * Chat: deleting a conversation used to remove two rows (messages + session). Every
    attached file stayed in R2, every document's text + embeddings stayed in the
    vector index, and the memories derived from it stayed searchable. Now
    chat_service.purge_session removes all of it; "clear history" does the same but
    keeps the (now empty) session; deleting the last turn keeps the files because
    Retry re-sends them.
  * Legacy feed: deleting a project removed only the project row; its reads, notes,
    progression, learning state, knowledge graph, provenance and metrics stayed.
"""
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.utils import db as legacy_db
from backend.services import chat_service, project_service
from backend.services import auth_service


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "deletes.db"
    monkeypatch.setattr(legacy_db, "DB_PATH", path)
    legacy_db.init_db()
    with legacy_db.get_connection() as c:
        c.execute("INSERT INTO users(user_id,email,name,hashed_pw) VALUES('u1','u1@x.com','u','x')")
    return path


def _vec(conn, table, **cols):
    names = ", ".join(["embedding", *cols])
    marks = ", ".join(["?"] * (len(cols) + 1))
    conn.execute(f"INSERT INTO {table} ({names}) VALUES ({marks})",
                 (json.dumps([0.0] * 3072), *cols.values()))


def _count(sql, *args):
    with legacy_db.get_connection() as c:
        return c.execute(sql, args).fetchone()[0]


def _chat(session_id="s1", other="s2"):
    """A conversation with a document, a code file and an image attached, their chunks
    and memories — plus an unrelated conversation that must survive."""
    with legacy_db.get_connection() as c:
        for sid in (session_id, other):
            c.execute("INSERT INTO chat_sessions (session_id, title, user_id) VALUES (?, 't', 'u1')", (sid,))
        attachments = [
            {"uri": "doc://docA", "filename": "notes.docx", "mime_type": "x"},
            {"uri": "file://fileB", "filename": "data.bin", "mime_type": "x"},
            {"uri": "https://gemini/img", "filename": "photo.png", "mime_type": "image/png",
             "r2_attachment_id": "imgC"},
        ]
        c.execute("INSERT INTO chat_messages (session_id, role, content, attachments) VALUES (?, 'user', 'hi', ?)",
                  (session_id, json.dumps(attachments)))
        c.execute("INSERT INTO chat_messages (session_id, role, content) VALUES (?, 'assistant', 'hello')", (session_id,))
        c.execute("INSERT INTO chat_messages (session_id, role, content) VALUES (?, 'user', 'other')", (other,))
        c.execute("INSERT INTO document_attachment_sessions (attachment_id, session_id) VALUES ('docA', ?)", (session_id,))
        # a document whose message entry the retention sweep already dropped
        c.execute("INSERT INTO document_attachment_sessions (attachment_id, session_id) VALUES ('docOld', ?)", (session_id,))
        for aid in ("docA", "docA", "docOld", "docKeep"):
            _vec(c, "document_chunks_vec", attachment_id=aid, filename="f", chunk_index="0", chunk_text="t", created_at="x")
        _vec(c, "conversation_memory_vec", user_id="u1", session_id=session_id, topic="t", entry_text="e", created_at="x")
        _vec(c, "conversation_memory_vec", user_id="u1", session_id=other, topic="t", entry_text="e", created_at="x")
        c.execute("INSERT INTO conversation_knowledge_state (session_id, state_json, updated_at) VALUES (?, '{}', 'x')", (session_id,))
        c.execute("INSERT INTO share_links (id, type, resource_id, created_by, created_at) VALUES ('tok', 'chat', ?, 'u1', 'x')", (session_id,))


R2_KEYS = {"chat-attachments/docA.docx", "chat-attachments/fileB.bin", "chat-attachments/imgC.png"}


def test_deleting_a_chat_removes_its_files_text_and_memories(db):
    _chat()
    with patch.object(chat_service.r2_storage_service, "delete") as r2:
        out = chat_service.delete_session("s1")
    assert {c.args[0] for c in r2.call_args_list} == R2_KEYS
    assert out["files_removed"] == 3 and out["document_chunks"] == 3
    assert _count("SELECT COUNT(*) FROM chat_sessions WHERE session_id='s1'") == 0
    assert _count("SELECT COUNT(*) FROM chat_messages WHERE session_id='s1'") == 0
    assert _count("SELECT COUNT(*) FROM document_chunks_vec WHERE attachment_id IN ('docA','docOld')") == 0
    assert _count("SELECT COUNT(*) FROM document_attachment_sessions WHERE session_id='s1'") == 0
    assert _count("SELECT COUNT(*) FROM conversation_memory_vec WHERE session_id='s1'") == 0
    assert _count("SELECT COUNT(*) FROM conversation_knowledge_state WHERE session_id='s1'") == 0
    assert _count("SELECT COUNT(*) FROM share_links WHERE resource_id='s1'") == 0
    # the other conversation and its data are untouched
    assert _count("SELECT COUNT(*) FROM chat_messages WHERE session_id='s2'") == 1
    assert _count("SELECT COUNT(*) FROM conversation_memory_vec WHERE session_id='s2'") == 1
    assert _count("SELECT COUNT(*) FROM document_chunks_vec WHERE attachment_id='docKeep'") == 1


def test_clearing_history_removes_the_same_but_keeps_the_session(db):
    _chat()
    with patch.object(chat_service.r2_storage_service, "delete") as r2:
        assert chat_service.clear_history("s1") == 2
    assert {c.args[0] for c in r2.call_args_list} == R2_KEYS
    assert _count("SELECT COUNT(*) FROM chat_sessions WHERE session_id='s1'") == 1
    assert _count("SELECT COUNT(*) FROM document_chunks_vec WHERE attachment_id='docA'") == 0


def test_a_storage_failure_never_leaves_a_half_deleted_chat(db):
    _chat()
    with patch.object(chat_service.r2_storage_service, "delete", side_effect=RuntimeError("R2 down")):
        out = chat_service.delete_session("s1")
    assert out["files_removed"] == 0 and out["files"] == 3
    assert _count("SELECT COUNT(*) FROM chat_messages WHERE session_id='s1'") == 0


@pytest.fixture
def client(db):
    from backend.main import app
    yield TestClient(app, raise_server_exceptions=False)


def _auth():
    return {"Authorization": f"Bearer {auth_service.create_access_token('u1')}"}


def test_the_delete_route_uses_the_full_purge(client):
    _chat()
    with patch.object(chat_service.r2_storage_service, "delete") as r2:
        r = client.delete("/chat/sessions/s1", headers=_auth())
    assert r.status_code == 200 and r.json()["files_removed"] == 3 and r2.call_count == 3, r.text


def test_deleting_the_last_turn_keeps_its_files_for_retry(client):
    _chat()
    with patch.object(chat_service.r2_storage_service, "delete") as r2:
        r = client.delete("/chat/sessions/s1/last_turn", headers=_auth())
    assert r.status_code == 200 and not r2.called
    assert _count("SELECT COUNT(*) FROM document_chunks_vec WHERE attachment_id='docA'") == 2


# ── legacy feed project ───────────────────────────────────────────────────────

def test_deleting_a_legacy_project_removes_every_row_it_owns(db):
    pid = "lp1"
    with legacy_db.get_connection() as c:
        c.execute("INSERT INTO learning_projects (project_id, name, user_id) VALUES (?, 'P', 'u1')", (pid,))
        c.execute("INSERT INTO learning_projects (project_id, name, user_id) VALUES ('lp2', 'Keep', 'u1')")
        c.execute("INSERT INTO project_insights (project_id, day_number, status) VALUES (?, 1, 'done')", (pid,))
        iid = c.execute("SELECT id FROM project_insights WHERE project_id=?", (pid,)).fetchone()[0]
        c.execute("INSERT INTO feed_article_reads (project_id, insight_id, article_key) VALUES (?, ?, 'a')", (pid, iid))
        c.execute("INSERT INTO card_notes (project_id, insight_id, card_id, content) VALUES (?, ?, 'c', 'n')", (pid, iid))
        c.execute("INSERT INTO read_later_items (user_id, article_key, title, project_id) VALUES ('u1', 'k', 't', ?)", (pid,))
        c.execute("INSERT INTO share_links (id, type, resource_id, created_by, created_at) VALUES ('t1', 'feed', ?, 'u1', 'x')", (f"{pid}/1",))
        c.execute("INSERT INTO bookmark_collections (collection_id, name) VALUES ('col', 'Saved')")
        c.execute("""INSERT INTO bookmarks (bookmark_id, collection_id, title, content_type, project_id, project_name)
                     VALUES ('b1', 'col', 'kept', 'article', ?, 'P')""", (pid,))
    assert project_service.delete_project(pid)
    for table in ("learning_projects", "project_insights", "feed_article_reads", "card_notes", "read_later_items"):
        assert _count(f"SELECT COUNT(*) FROM {table} WHERE project_id=?", pid) == 0, table
    assert _count("SELECT COUNT(*) FROM share_links WHERE resource_id LIKE 'lp1/%'") == 0
    assert _count("SELECT COUNT(*) FROM bookmarks WHERE bookmark_id='b1'") == 1      # a saved copy, kept
    assert _count("SELECT COUNT(*) FROM learning_projects WHERE project_id='lp2'") == 1
