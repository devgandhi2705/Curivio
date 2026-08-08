"""
Tests for Chat-R10e's ownership gates on projects/bookmarks/share/feed-chat-links.

Mirrors existing conventions rather than inventing new ones:
  - Owner-lookup unit tests: mocked get_connection, same shape as
    test_chat_title_service.py's TestGetSessionOwner.
  - Endpoint-level 404 tests: dependency_overrides for auth, same shape as
    test_chat.py's TestChatEndpoints. Not exhaustive across all 28 wired
    endpoints (no prior test coverage existed for projects/bookmarks/share/
    feed-chat-links at all) — one representative endpoint per resource type
    proves the wiring pattern; the live two-user verification covers breadth.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _make_conn(rows=None):
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = rows[0] if rows else None
    conn.execute.return_value = cursor
    conn.__enter__ = lambda s: conn
    conn.__exit__ = MagicMock(return_value=False)
    return conn


def _row(user_id):
    row = MagicMock()
    row.__getitem__ = lambda s, k: user_id if k == "user_id" else None
    return row


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Owner-lookup unit tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetProjectOwner:
    def test_returns_owner_when_set(self):
        from backend.services.project_service import get_project_owner
        conn = _make_conn(rows=[_row("user-abc")])
        with patch("backend.utils.db.get_connection", return_value=conn):
            assert get_project_owner("p1") == "user-abc"

    def test_returns_none_for_null_owner(self):
        from backend.services.project_service import get_project_owner
        conn = _make_conn(rows=[_row(None)])
        with patch("backend.utils.db.get_connection", return_value=conn):
            assert get_project_owner("p1") is None

    def test_returns_none_when_missing(self):
        from backend.services.project_service import get_project_owner
        conn = _make_conn(rows=[])
        with patch("backend.utils.db.get_connection", return_value=conn):
            assert get_project_owner("no-such") is None

    def test_does_not_swallow_db_errors(self):
        from backend.services.project_service import get_project_owner
        with patch("backend.utils.db.get_connection", side_effect=RuntimeError("db down")):
            with pytest.raises(RuntimeError):
                get_project_owner("p1")


class TestGetCollectionOwner:
    # bookmark_service.py imports get_connection at module top-level (unlike
    # chat_title_service/project_service, which do a deferred import per
    # call) — the source-of-truth patch target is bookmark_service's own
    # bound name, not backend.utils.db directly.
    def test_returns_owner_when_set(self):
        from backend.services.bookmark_service import get_collection_owner
        conn = _make_conn(rows=[_row("user-abc")])
        with patch("backend.services.bookmark_service.get_connection", return_value=conn):
            assert get_collection_owner("c1") == "user-abc"

    def test_returns_none_for_null_owner(self):
        from backend.services.bookmark_service import get_collection_owner
        conn = _make_conn(rows=[_row(None)])
        with patch("backend.services.bookmark_service.get_connection", return_value=conn):
            assert get_collection_owner("c1") is None

    def test_returns_none_when_missing(self):
        from backend.services.bookmark_service import get_collection_owner
        conn = _make_conn(rows=[])
        with patch("backend.services.bookmark_service.get_connection", return_value=conn):
            assert get_collection_owner("no-such") is None

    def test_does_not_swallow_db_errors(self):
        from backend.services.bookmark_service import get_collection_owner
        with patch("backend.services.bookmark_service.get_connection", side_effect=RuntimeError("db down")):
            with pytest.raises(RuntimeError):
                get_collection_owner("c1")


class TestGetBookmarkOwner:
    def test_returns_collection_owner_when_set(self):
        from backend.services.bookmark_service import get_bookmark_owner
        conn = _make_conn(rows=[_row("user-abc")])
        with patch("backend.services.bookmark_service.get_connection", return_value=conn):
            assert get_bookmark_owner("b1") == "user-abc"

    def test_returns_none_for_null_owner(self):
        from backend.services.bookmark_service import get_bookmark_owner
        conn = _make_conn(rows=[_row(None)])
        with patch("backend.services.bookmark_service.get_connection", return_value=conn):
            assert get_bookmark_owner("b1") is None

    def test_returns_none_when_bookmark_missing(self):
        # JOIN yields no row whether the bookmark or its collection is missing.
        from backend.services.bookmark_service import get_bookmark_owner
        conn = _make_conn(rows=[])
        with patch("backend.services.bookmark_service.get_connection", return_value=conn):
            assert get_bookmark_owner("no-such") is None

    def test_does_not_swallow_db_errors(self):
        from backend.services.bookmark_service import get_bookmark_owner
        with patch("backend.services.bookmark_service.get_connection", side_effect=RuntimeError("db down")):
            with pytest.raises(RuntimeError):
                get_bookmark_owner("b1")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Endpoint-level gate wiring (representative sample per resource type)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from backend.main import app, get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "test-user", "email": "test@example.com"}
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


class TestProjectEndpointGate:
    def test_get_project_blocks_other_owner_404(self, client):
        with patch("backend.services.project_service.get_project_owner", return_value="someone-else"), \
             patch("backend.services.project_service.get_project") as mock_get:
            resp = client.get("/projects/p1")
        assert resp.status_code == 404
        mock_get.assert_not_called()

    def test_get_project_allows_real_owner(self, client):
        with patch("backend.services.project_service.get_project_owner", return_value="test-user"), \
             patch("backend.services.project_service.get_project", return_value={"project_id": "p1"}):
            resp = client.get("/projects/p1")
        assert resp.status_code == 200

    def test_get_project_allows_null_owner_legacy(self, client):
        with patch("backend.services.project_service.get_project_owner", return_value=None), \
             patch("backend.services.project_service.get_project", return_value={"project_id": "p1"}):
            resp = client.get("/projects/p1")
        assert resp.status_code == 200

    def test_delete_project_blocks_other_owner_404(self, client):
        with patch("backend.services.project_service.get_project_owner", return_value="someone-else"), \
             patch("backend.services.project_service.delete_project") as mock_delete:
            resp = client.delete("/projects/p1")
        assert resp.status_code == 404
        mock_delete.assert_not_called()


class TestBookmarkEndpointGate:
    def test_update_collection_blocks_other_owner_404(self, client):
        with patch("backend.services.bookmark_service.get_collection_owner", return_value="someone-else"), \
             patch("backend.main.update_collection") as mock_update:
            resp = client.put("/bookmarks/collections/c1", json={"name": "renamed"})
        assert resp.status_code == 404
        mock_update.assert_not_called()

    def test_get_bookmark_blocks_other_owner_404(self, client):
        with patch("backend.services.bookmark_service.get_bookmark_owner", return_value="someone-else"), \
             patch("backend.main.get_bookmark") as mock_get:
            resp = client.get("/bookmarks/b1")
        assert resp.status_code == 404
        mock_get.assert_not_called()

    def test_update_bookmark_blocks_move_into_unowned_collection_404(self, client):
        # Bookmark itself is owned by test-user, but the destination
        # collection (the move target) belongs to someone else.
        with patch("backend.services.bookmark_service.get_bookmark_owner", return_value="test-user"), \
             patch("backend.services.bookmark_service.get_collection_owner", return_value="someone-else"), \
             patch("backend.main.update_bookmark") as mock_update:
            resp = client.put("/bookmarks/b1", json={"collection_id": "c-not-mine"})
        assert resp.status_code == 404
        mock_update.assert_not_called()

    def test_create_bookmark_blocks_unowned_collection_404(self, client):
        with patch("backend.services.bookmark_service.get_collection_owner", return_value="someone-else"), \
             patch("backend.main.create_bookmark") as mock_create:
            resp = client.post("/bookmarks", json={"collection_id": "c-not-mine", "title": "x"})
        assert resp.status_code == 404
        mock_create.assert_not_called()


class TestFeedChatLinksEndpointGate:
    def test_create_link_blocks_unowned_project_404(self, client):
        with patch("backend.services.project_service.get_project_owner", return_value="someone-else"), \
             patch("backend.services.feed_chat_link_service.create_link") as mock_create:
            resp = client.post("/feed-chat-links", json={
                "session_id": "s1", "project_id": "p1", "article_key": "a1",
            })
        assert resp.status_code == 404
        mock_create.assert_not_called()

    def test_get_links_blocks_unowned_project_404(self, client):
        with patch("backend.services.project_service.get_project_owner", return_value="someone-else"), \
             patch("backend.services.feed_chat_link_service.get_links_for_article") as mock_get:
            resp = client.get("/feed-chat-links", params={"project_id": "p1", "article_key": "a1"})
        assert resp.status_code == 404
        mock_get.assert_not_called()


class TestShareCreateGate:
    def test_chat_type_blocks_unowned_session_404(self, client):
        with patch("backend.services.chat_title_service.get_session_owner", return_value="someone-else"), \
             patch("backend.services.share_service.create_share_link") as mock_create:
            resp = client.post("/share/create", json={"type": "chat", "resource_id": "s1"})
        assert resp.status_code == 404
        mock_create.assert_not_called()

    def test_chat_type_allows_owner(self, client):
        with patch("backend.services.chat_title_service.get_session_owner", return_value="test-user"), \
             patch("backend.services.share_service.create_share_link",
                   return_value={"token": "tok", "share_url": "http://x/share/tok"}):
            resp = client.post("/share/create", json={"type": "chat", "resource_id": "s1"})
        assert resp.status_code == 200

    def test_feed_type_blocks_unowned_project_404(self, client):
        with patch("backend.services.project_service.get_project_owner", return_value="someone-else"), \
             patch("backend.services.share_service.create_share_link") as mock_create:
            resp = client.post("/share/create", json={"type": "feed", "resource_id": "p1/3"})
        assert resp.status_code == 404
        mock_create.assert_not_called()

    def test_feed_type_allows_owner(self, client):
        with patch("backend.services.project_service.get_project_owner", return_value="test-user"), \
             patch("backend.services.share_service.create_share_link",
                   return_value={"token": "tok", "share_url": "http://x/share/tok"}):
            resp = client.post("/share/create", json={"type": "feed", "resource_id": "p1/3"})
        assert resp.status_code == 200

    def test_dashboard_type_blocks_other_users_id_404(self, client):
        with patch("backend.services.share_service.create_share_link") as mock_create:
            resp = client.post("/share/create", json={"type": "dashboard", "resource_id": "someone-else"})
        assert resp.status_code == 404
        mock_create.assert_not_called()

    def test_dashboard_type_allows_own_id(self, client):
        with patch("backend.services.share_service.create_share_link",
                   return_value={"token": "tok", "share_url": "http://x/share/tok"}):
            resp = client.post("/share/create", json={"type": "dashboard", "resource_id": "test-user"})
        assert resp.status_code == 200

    def test_resolve_share_link_has_no_auth_dependency(self):
        # GET /share/{token} must stay callable with zero auth — that's the
        # feature. Confirm the route has no Depends(get_current_user).
        from backend.main import app
        route = next(r for r in app.routes if getattr(r, "path", None) == "/share/{token}" and "GET" in r.methods)
        assert not any(
            getattr(dep.call, "__name__", "") == "get_current_user"
            for dep in route.dependant.dependencies
        )
