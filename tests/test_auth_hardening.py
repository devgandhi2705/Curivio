"""
Regression coverage for the OTP-hardening / session-revocation phase:
  - code hashing + constant-time compare (pure functions, no DB)
  - per-target verification lockout / resend cooldown (mocked DB, same
    shape as test_ownership_gates.py's owner-lookup unit tests)
  - jti-based token revocation, both the pure DB helpers and that
    /auth/logout and /auth/me/password actually call revoke_token()

Live, end-to-end proof (real DB, real cross-IP requests, real lockout
triggering, real two-account IDOR attempt) lives outside the committed
suite — see the security-hardening report for that run's pasted output.
These tests are the fast, mocked, CI-safe regression net on top of it,
mirroring test_ownership_gates.py / test_admin_gate.py's established
conventions rather than inventing new ones.
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


def _row(**kv):
    row = MagicMock()
    row.__getitem__ = lambda s, k: kv.get(k)
    row.keys = lambda: list(kv.keys())
    return row


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Pure functions — hashing / constant-time compare
# ═══════════════════════════════════════════════════════════════════════════════

class TestCodeHashing:
    def test_hash_is_not_the_code(self):
        from backend.services.auth_service import _hash_code
        assert _hash_code("123456") != "123456"

    def test_hash_is_deterministic_sha256(self):
        import hashlib
        from backend.services.auth_service import _hash_code
        assert _hash_code("123456") == hashlib.sha256(b"123456").hexdigest()

    def test_codes_match_accepts_correct_code(self):
        from backend.services.auth_service import _hash_code, _codes_match
        assert _codes_match(_hash_code("123456"), "123456") is True

    def test_codes_match_rejects_wrong_code(self):
        from backend.services.auth_service import _hash_code, _codes_match
        assert _codes_match(_hash_code("123456"), "654321") is False

    def test_codes_match_strips_whitespace_same_as_hash_code(self):
        from backend.services.auth_service import _hash_code, _codes_match
        assert _codes_match(_hash_code("123456"), " 123456 ") is True


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Per-target verification lockout (Task 1)
# ═══════════════════════════════════════════════════════════════════════════════

class TestVerifyLockout:
    def test_no_lockout_row_passes(self):
        from backend.services.auth_service import _check_lockout
        conn = _make_conn(rows=[])
        with patch("backend.services.auth_service.get_connection", return_value=conn):
            _check_lockout("a@example.com", "reset")  # must not raise

    def test_locked_until_in_future_raises_429(self):
        from datetime import datetime, timedelta, timezone
        from fastapi import HTTPException
        from backend.services.auth_service import _check_lockout
        future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        conn = _make_conn(rows=[_row(locked_until=future)])
        with patch("backend.services.auth_service.get_connection", return_value=conn):
            with pytest.raises(HTTPException) as exc:
                _check_lockout("a@example.com", "reset")
        assert exc.value.status_code == 429

    def test_locked_until_in_past_passes(self):
        from datetime import datetime, timedelta, timezone
        from backend.services.auth_service import _check_lockout
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        conn = _make_conn(rows=[_row(locked_until=past)])
        with patch("backend.services.auth_service.get_connection", return_value=conn):
            _check_lockout("a@example.com", "reset")  # must not raise

    def test_record_failure_locks_at_max_attempts(self):
        from backend.services.auth_service import _record_verify_failure, _MAX_VERIFY_ATTEMPTS
        conn = _make_conn(rows=[_row(fail_count=_MAX_VERIFY_ATTEMPTS - 1)])
        with patch("backend.services.auth_service.get_connection", return_value=conn):
            _record_verify_failure("a@example.com", "reset")
        insert_call = conn.execute.call_args_list[-1]
        params = insert_call.args[1]
        # (email, purpose, fail_count, locked_until, updated_at)
        assert params[2] == _MAX_VERIFY_ATTEMPTS
        assert params[3] is not None  # locked_until got set

    def test_record_failure_below_threshold_does_not_lock(self):
        from backend.services.auth_service import _record_verify_failure, _MAX_VERIFY_ATTEMPTS
        conn = _make_conn(rows=[_row(fail_count=0)])
        with patch("backend.services.auth_service.get_connection", return_value=conn):
            _record_verify_failure("a@example.com", "reset")
        insert_call = conn.execute.call_args_list[-1]
        params = insert_call.args[1]
        assert params[2] == 1
        assert params[3] is None
        assert 1 < _MAX_VERIFY_ATTEMPTS

    def test_clear_lockout_deletes_row(self):
        from backend.services.auth_service import _clear_verify_lockout
        conn = _make_conn()
        with patch("backend.services.auth_service.get_connection", return_value=conn):
            _clear_verify_lockout("a@example.com", "reset")
        sql = conn.execute.call_args.args[0]
        assert "DELETE FROM verification_lockouts" in sql


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Resend cooldown, per target (Task 3)
# ═══════════════════════════════════════════════════════════════════════════════

class TestResendCooldown:
    def test_no_prior_send_passes(self):
        from backend.services.auth_service import _check_resend_cooldown
        conn = _make_conn(rows=[])
        with patch("backend.services.auth_service.get_connection", return_value=conn):
            _check_resend_cooldown("a@example.com", "reset")  # must not raise

    def test_recent_send_raises_429(self):
        from datetime import datetime, timezone
        from fastapi import HTTPException
        from backend.services.auth_service import _check_resend_cooldown
        conn = _make_conn(rows=[_row(last_sent_at=datetime.now(timezone.utc).isoformat())])
        with patch("backend.services.auth_service.get_connection", return_value=conn):
            with pytest.raises(HTTPException) as exc:
                _check_resend_cooldown("a@example.com", "reset")
        assert exc.value.status_code == 429

    def test_old_send_passes(self):
        from datetime import datetime, timedelta, timezone
        from backend.services.auth_service import _check_resend_cooldown, _RESEND_COOLDOWN_SECONDS
        old = (datetime.now(timezone.utc) - timedelta(seconds=_RESEND_COOLDOWN_SECONDS + 5)).isoformat()
        conn = _make_conn(rows=[_row(last_sent_at=old)])
        with patch("backend.services.auth_service.get_connection", return_value=conn):
            _check_resend_cooldown("a@example.com", "reset")  # must not raise


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Token revocation (Task 7)
# ═══════════════════════════════════════════════════════════════════════════════

class TestTokenRevocation:
    def test_is_token_revoked_true(self):
        from backend.services.auth_service import is_token_revoked
        conn = _make_conn(rows=[_row()])
        with patch("backend.services.auth_service.get_connection", return_value=conn):
            assert is_token_revoked("some-jti") is True

    def test_is_token_revoked_false(self):
        from backend.services.auth_service import is_token_revoked
        conn = _make_conn(rows=[])
        with patch("backend.services.auth_service.get_connection", return_value=conn):
            assert is_token_revoked("some-jti") is False

    def test_get_current_user_rejects_revoked_token(self):
        """A syntactically valid, unexpired JWT whose jti is on the
        blocklist must still be rejected — this is the whole point of
        Task 7, so it gets a direct unit test independent of the live run."""
        from fastapi import HTTPException
        from backend.services.auth_service import get_current_user
        creds = MagicMock()
        creds.credentials = "fake.jwt.token"
        with patch("backend.services.auth_service._decode_token",
                   return_value={"sub": "user-1", "jti": "revoked-jti"}), \
             patch("backend.services.auth_service.is_token_revoked", return_value=True):
            with pytest.raises(HTTPException) as exc:
                get_current_user(creds)
        assert exc.value.status_code == 401

    def test_get_current_user_accepts_non_revoked_token(self):
        from backend.services.auth_service import get_current_user
        creds = MagicMock()
        creds.credentials = "fake.jwt.token"
        with patch("backend.services.auth_service._decode_token",
                   return_value={"sub": "user-1", "jti": "live-jti"}), \
             patch("backend.services.auth_service.is_token_revoked", return_value=False), \
             patch("backend.services.auth_service.get_user_by_id",
                   return_value={"user_id": "user-1", "email": "a@example.com", "name": "A",
                                 "created_at": None, "feed_version": "legacy"}):
            user = get_current_user(creds)
        assert user["user_id"] == "user-1"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Endpoint wiring — /auth/logout and /auth/me/password actually revoke
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from backend.main import app
    yield TestClient(app, raise_server_exceptions=False)


class TestLogoutRevokes:
    def test_logout_calls_revoke_token_with_presented_jti(self, client):
        from backend.main import app
        from backend.services.auth_service import get_current_token
        app.dependency_overrides[get_current_token] = lambda: {"sub": "u1", "jti": "jti-123", "exp": 9999999999}
        try:
            with patch("backend.main.revoke_token") as mock_revoke:
                resp = client.post("/auth/logout")
        finally:
            app.dependency_overrides.pop(get_current_token, None)
        assert resp.status_code == 200
        mock_revoke.assert_called_once_with("jti-123", 9999999999)

    def test_logout_requires_auth(self, client):
        resp = client.post("/auth/logout")
        assert resp.status_code == 401


class TestChangePasswordRevokes:
    def test_change_password_revokes_current_token(self, client):
        from backend.main import app
        from backend.services.auth_service import get_current_user, get_current_token
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "u1", "email": "a@example.com", "name": "A",
            "created_at": None, "feed_version": "legacy",
        }
        app.dependency_overrides[get_current_token] = lambda: {"sub": "u1", "jti": "jti-456", "exp": 9999999999}
        try:
            with patch("backend.main.change_password") as mock_change, \
                 patch("backend.main.revoke_token") as mock_revoke:
                resp = client.put("/auth/me/password", json={
                    "current_password": "old12345", "new_password": "new123456",
                })
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_current_token, None)
        assert resp.status_code == 200
        mock_change.assert_called_once_with("u1", "old12345", "new123456")
        mock_revoke.assert_called_once_with("jti-456", 9999999999)
