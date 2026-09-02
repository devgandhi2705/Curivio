"""
Tests that POST /projects/generate-all is gated by get_current_admin_user(),
plus a sweep asserting EVERY /admin/* route is behind that same dependency
(Feed-6's admin dependency), not just get_current_user(). Any authenticated
user could previously trigger generation across every user's projects.

Same client-fixture shape as test_ownership_gates.py: override get_current_user,
let the real dependency chain (get_current_admin_user -> ADMIN_EMAILS) run.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from backend.main import app, get_current_user
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "test-user", "email": "not-admin@example.com",
    }
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


class TestGenerateAllAdminGate:
    def test_non_admin_blocked_404(self, client):
        with patch("backend.services.auth_service.ADMIN_EMAILS", "admin@example.com"), \
             patch("backend.services.project_service.generate_all_projects") as mock_gen:
            resp = client.post("/projects/generate-all")
        assert resp.status_code == 404
        mock_gen.assert_not_called()

    def test_admin_allowed_200(self, client):
        from backend.main import app, get_current_user
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "admin-user", "email": "admin@example.com",
        }
        summary = {"total": 3, "generated": 3, "skipped": 0, "failed": 0, "errors": []}
        try:
            with patch("backend.services.auth_service.ADMIN_EMAILS", "admin@example.com"), \
                 patch("backend.services.project_service.generate_all_projects", return_value=summary) as mock_gen:
                resp = client.post("/projects/generate-all")
        finally:
            app.dependency_overrides.pop(get_current_user, None)
        assert resp.status_code == 200
        assert resp.json() == summary
        mock_gen.assert_called_once()


# ── every /admin route, not just the ones someone remembered to test ─────────


def _admin_routes():
    """Every route mounted under /admin. Collected at import time so the sweep
    below parametrises over the real router table."""
    from backend.main import app
    return [r for r in app.routes if getattr(r, "path", "").startswith("/admin")]


def _is_admin_gated(dependant) -> bool:
    from backend.services.auth_service import get_current_admin_user
    return any(d.call is get_current_admin_user or _is_admin_gated(d)
               for d in dependant.dependencies)


class TestEveryAdminRouteIsGated:
    """The gate is per-router, so a new endpoint added to the wrong router — or
    a router mounted without its dependencies — is silently world-readable to
    any signed-in account. Checking the dependency tree of every /admin route
    catches that at the moment the route is added, without each new endpoint
    needing someone to remember to write a gate test for it."""

    def test_the_sweep_actually_found_routes(self):
        """If the prefix ever changes, the parametrised test below would pass
        vacuously on an empty list. This is what stops that."""
        assert len(_admin_routes()) > 10

    @pytest.mark.parametrize(
        "route", _admin_routes(),
        ids=lambda r: f"{sorted(r.methods)[0]}:{r.path}",
    )
    def test_route_is_behind_get_current_admin_user(self, route):
        assert _is_admin_gated(route.dependant), (
            f"{sorted(route.methods)[0]} {route.path} is mounted under /admin but is "
            "not behind get_current_admin_user — any signed-in user can reach it"
        )
