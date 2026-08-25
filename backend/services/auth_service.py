"""
Auth service — user registration, login, JWT issuance, and FastAPI dependency.
"""

import hashlib
import hmac
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

import bcrypt as _bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from ..utils.db import get_connection

# ── Config ────────────────────────────────────────────────────────────────────

SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "change-me-in-production-use-a-long-random-string")
ALGORITHM  = "HS256"
from ..config import AUTH_TOKEN_EXPIRE_DAYS as TOKEN_EXPIRE_DAYS
from ..config import ADMIN_EMAILS

bearer_scheme = HTTPBearer(auto_error=False)

# ── Password helpers ──────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ── JWT helpers ───────────────────────────────────────────────────────────────

def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRE_DAYS)
    # jti: per-token identity so a single issued token can be individually
    # revoked (logout / password change) without touching every other token
    # already issued to this user — see revoke_token/is_token_revoked below.
    jti = str(uuid.uuid4())
    return jwt.encode({"sub": user_id, "jti": jti, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def _decode_token(token: str) -> dict:
    """Decode a JWT and return its full payload. Raises HTTPException on failure."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if not payload.get("sub"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return payload
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


# ── Token revocation ──────────────────────────────────────────────────────────
# Right-sized to this phase: a jti blocklist, not a full refresh-token system.
# Populated on logout and on password change, checked on every authenticated
# request. It can only revoke the ONE token presented at the time of that
# action — it has no way to enumerate every token ever issued to a user, so a
# different still-live session (another device, another browser tab that
# logged in earlier) is NOT revoked by this. Closing that fully would need a
# per-user "valid_after" timestamp checked against each token's issued-at
# claim — a bigger change, deliberately out of scope here.

def is_token_revoked(jti: str) -> bool:
    with get_connection() as conn:
        row = conn.execute("SELECT 1 FROM revoked_tokens WHERE jti = ?", (jti,)).fetchone()
    return row is not None


def revoke_token(jti: str, exp: int) -> None:
    """Blocklist one JWT by its jti until its own natural expiry. Opportunistic
    cleanup on every insert keeps the table bounded by revocations within one
    token TTL window, not by all-time history."""
    expires_at = datetime.fromtimestamp(exp, tz=timezone.utc).isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO revoked_tokens (jti, expires_at) VALUES (?, ?)",
            (jti, expires_at),
        )
        conn.execute("DELETE FROM revoked_tokens WHERE expires_at < ?", (now_iso,))


# ── DB helpers ────────────────────────────────────────────────────────────────

def _row_to_user(row) -> dict:
    return {
        "user_id":      row["user_id"],
        "email":        row["email"],
        "name":         row["name"],
        "created_at":   row["created_at"],
        # Feed v2 (Phase 1) per-user toggle. Read side: surfaced here so /auth/me,
        # login and register all carry it to the frontend + the /v2 route gate.
        "feed_version": row["feed_version"] if "feed_version" in row.keys() else "legacy",
    }


def get_user_by_email(email: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email.lower().strip(),)
        ).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


# ── Registration ──────────────────────────────────────────────────────────────

def register_user(email: str, name: str, password: str) -> dict:
    """
    Create a new user. Raises HTTPException 409 if email already taken.
    Returns the new user dict (no password).
    """
    email = email.lower().strip()
    if get_user_by_email(email):
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    if len(password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")

    user_id   = str(uuid.uuid4())
    hashed_pw = hash_password(password)

    with get_connection() as conn:
        conn.execute(
            "INSERT INTO users (user_id, email, name, hashed_pw) VALUES (?, ?, ?, ?)",
            (user_id, email, name.strip(), hashed_pw),
        )
    token = create_access_token(user_id)
    user_dict = {"user_id": user_id, "email": email, "name": name.strip(), "created_at": None, "feed_version": "legacy"}
    return {"access_token": token, "token_type": "bearer", "user": user_dict}


# ── Login ─────────────────────────────────────────────────────────────────────

def login_user(email: str, password: str) -> dict:
    """
    Authenticate and return a JWT token + user dict.
    Raises HTTPException 401 on bad credentials.
    """
    row = get_user_by_email(email.lower().strip())
    if not row or not verify_password(password, row["hashed_pw"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token(row["user_id"])
    return {"access_token": token, "token_type": "bearer", "user": _row_to_user(row)}


# ── Update profile ────────────────────────────────────────────────────────────

def update_profile(user_id: str, name: str | None, email: str | None) -> dict:
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    new_name  = name.strip()  if name  else user["name"]
    new_email = email.lower().strip() if email else user["email"]

    if new_email != user["email"]:
        existing = get_user_by_email(new_email)
        if existing and existing["user_id"] != user_id:
            raise HTTPException(status_code=409, detail="Email already in use")

    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET name = ?, email = ? WHERE user_id = ?",
            (new_name, new_email, user_id),
        )
    return {"user_id": user_id, "email": new_email, "name": new_name}


# ── Feed v2 toggle (Phase 1) ──────────────────────────────────────────────────

def set_feed_version(user_id: str, feed_version: str) -> dict:
    """Write side of the Feed v2 toggle. Sets users.feed_version for one user.

    Returns the refreshed user dict (same shape as get_current_user) so callers
    can hand it straight back to the frontend.
    """
    if feed_version not in ("legacy", "v2"):
        raise HTTPException(status_code=422, detail="feed_version must be 'legacy' or 'v2'")
    if not get_user_by_id(user_id):
        raise HTTPException(status_code=404, detail="User not found")

    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET feed_version = ? WHERE user_id = ?",
            (feed_version, user_id),
        )
    return _row_to_user(get_user_by_id(user_id))


# ── Change password ───────────────────────────────────────────────────────────

def change_password(user_id: str, current_pw: str, new_pw: str) -> None:
    row = get_user_by_id(user_id)
    if not row or not verify_password(current_pw, row["hashed_pw"]):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    if len(new_pw) < 8:
        raise HTTPException(status_code=422, detail="New password must be at least 8 characters")

    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET hashed_pw = ? WHERE user_id = ?",
            (hash_password(new_pw), user_id),
        )


# ── Delete account ────────────────────────────────────────────────────────────

def delete_account(user_id: str, password: str) -> None:
    row = get_user_by_id(user_id)
    if not row or not verify_password(password, row["hashed_pw"]):
        raise HTTPException(status_code=401, detail="Password is incorrect")

    with get_connection() as conn:
        # ALTER TABLE-added FK columns have no ON DELETE CASCADE, so delete
        # child rows explicitly in dependency order before removing the user.
        conn.execute("DELETE FROM password_reset_tokens WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM prior_recommendations WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM concept_memory WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM user_preferences WHERE user_id = ?", (user_id,))

        # Chat: messages → sessions
        conn.execute("""
            DELETE FROM chat_messages WHERE session_id IN (
                SELECT session_id FROM chat_sessions WHERE user_id = ?
            )
        """, (user_id,))
        conn.execute("DELETE FROM chat_sessions WHERE user_id = ?", (user_id,))

        # Bookmarks: bookmarks → collections
        conn.execute("""
            DELETE FROM bookmarks WHERE collection_id IN (
                SELECT collection_id FROM bookmark_collections WHERE user_id = ?
            )
        """, (user_id,))
        conn.execute("DELETE FROM bookmark_collections WHERE user_id = ?", (user_id,))

        # Projects and all dependent tables (feed reads, chat links, notes, progression, insights)
        conn.execute("""
            DELETE FROM feed_article_reads WHERE project_id IN (
                SELECT project_id FROM learning_projects WHERE user_id = ?
            )
        """, (user_id,))
        conn.execute("""
            DELETE FROM feed_chat_links WHERE project_id IN (
                SELECT project_id FROM learning_projects WHERE user_id = ?
            )
        """, (user_id,))
        conn.execute("""
            DELETE FROM card_notes WHERE project_id IN (
                SELECT project_id FROM learning_projects WHERE user_id = ?
            )
        """, (user_id,))
        conn.execute("""
            DELETE FROM project_insights WHERE project_id IN (
                SELECT project_id FROM learning_projects WHERE user_id = ?
            )
        """, (user_id,))
        conn.execute("""
            DELETE FROM project_progression WHERE project_id IN (
                SELECT project_id FROM learning_projects WHERE user_id = ?
            )
        """, (user_id,))
        conn.execute("DELETE FROM learning_projects WHERE user_id = ?", (user_id,))

        conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))


# ── Verify current password ───────────────────────────────────────────────────

def check_current_password(user_id: str, password: str) -> bool:
    row = get_user_by_id(user_id)
    if not row:
        return False
    return verify_password(password, row["hashed_pw"])


# ── Verification hardening (shared by reset + signup codes) ─────────────────
# Per-TARGET (email), not per-caller-IP — the IP-keyed slowapi limits on the
# routes stay as a first line of defense, but they only throttle one caller;
# an attacker rotating source IPs sails past an IP limit untouched. Keying on
# the email means the budget is the same no matter how many IPs are used.

_MAX_VERIFY_ATTEMPTS   = 5    # brute-forcing a 6-digit code (1e6 space) in 5
                              # guesses has ~0.0005% success odds — tight enough
                              # to stop guessing, loose enough to absorb a couple
                              # of legitimate typos before locking the target out.
_LOCKOUT_MINUTES        = 15  # independent of the code's own TTL (Task 4) — a
                              # fresh code does NOT clear this; only a genuinely
                              # correct/valid verification does (see
                              # _clear_verify_lockout call sites below). Without
                              # that rule, an attacker could just request a new
                              # code every _RESEND_COOLDOWN_SECONDS to reset
                              # their guess budget and the lockout would do nothing.
_RESEND_COOLDOWN_SECONDS = 60  # minimum gap between resend requests for the SAME
                                # target email, independent of caller IP (Task 3).


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()


def _codes_match(stored_hash: str, submitted_code: str) -> bool:
    return hmac.compare_digest(stored_hash, _hash_code(submitted_code))


def _check_lockout(email: str, purpose: str) -> None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT locked_until FROM verification_lockouts WHERE email = ? AND purpose = ?",
            (email, purpose),
        ).fetchone()
    if row and row["locked_until"]:
        if datetime.now(timezone.utc) < datetime.fromisoformat(row["locked_until"]):
            raise HTTPException(
                status_code=429,
                detail=f"Too many attempts. Please try again in {_LOCKOUT_MINUTES} minutes.",
            )


def _record_verify_failure(email: str, purpose: str) -> None:
    now = datetime.now(timezone.utc)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT fail_count FROM verification_lockouts WHERE email = ? AND purpose = ?",
            (email, purpose),
        ).fetchone()
        fail_count = (row["fail_count"] if row else 0) + 1
        locked_until = (
            (now + timedelta(minutes=_LOCKOUT_MINUTES)).isoformat()
            if fail_count >= _MAX_VERIFY_ATTEMPTS else None
        )
        conn.execute(
            """INSERT INTO verification_lockouts (email, purpose, fail_count, locked_until, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(email, purpose) DO UPDATE SET
                   fail_count   = excluded.fail_count,
                   locked_until = excluded.locked_until,
                   updated_at   = excluded.updated_at""",
            (email, purpose, fail_count, locked_until, now.isoformat()),
        )


def _clear_verify_lockout(email: str, purpose: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM verification_lockouts WHERE email = ? AND purpose = ?", (email, purpose)
        )


def _check_resend_cooldown(email: str, purpose: str) -> None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT last_sent_at FROM resend_cooldowns WHERE email = ? AND purpose = ?",
            (email, purpose),
        ).fetchone()
    if row:
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(row["last_sent_at"])).total_seconds()
        if elapsed < _RESEND_COOLDOWN_SECONDS:
            raise HTTPException(
                status_code=429,
                detail=f"Please wait {int(_RESEND_COOLDOWN_SECONDS - elapsed)}s before requesting another code.",
            )


def _record_resend(email: str, purpose: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO resend_cooldowns (email, purpose, last_sent_at) VALUES (?, ?, ?)
               ON CONFLICT(email, purpose) DO UPDATE SET last_sent_at = excluded.last_sent_at""",
            (email, purpose, datetime.now(timezone.utc).isoformat()),
        )


# ── Password reset (6-digit code) ────────────────────────────────────────────

_RESET_EXPIRY_MINUTES = 5  # was 15 — secondary hardening. The primary fix
                           # against guessing is _MAX_VERIFY_ATTEMPTS above;
                           # shortening the window only shrinks the time a
                           # correct-but-unused code stays valid if it leaks.


def create_reset_token(email: str) -> None:
    """Generate, store, and email a 6-digit reset code. Silent on unknown email."""
    email = email.lower().strip()
    _check_resend_cooldown(email, "reset")

    user = get_user_by_email(email)
    if not user:
        _record_resend(email, "reset")
        return

    code = str(secrets.randbelow(1_000_000)).zfill(6)
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=_RESET_EXPIRY_MINUTES)).isoformat()

    with get_connection() as conn:
        conn.execute(
            "UPDATE password_reset_tokens SET used = 1 WHERE user_id = ? AND used = 0",
            (user["user_id"],),
        )
        conn.execute(
            "INSERT INTO password_reset_tokens (user_id, code_hash, expires_at) VALUES (?, ?, ?)",
            (user["user_id"], _hash_code(code), expires_at),
        )
    _record_resend(email, "reset")

    _send_code_email(user["email"], user["name"], code)


def _build_email_bodies(display_name: str, code: str) -> tuple[str, str]:
    text = (
        f"Hi {display_name},\n\n"
        f"Your Curivio password reset code is:\n\n  {code}\n\n"
        f"This code expires in {_RESET_EXPIRY_MINUTES} minutes. "
        "If you didn't request this, you can safely ignore this email.\n\n"
        "— The Curivio Team"
    )
    html = f"""<html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1a1a1a;max-width:480px;margin:0 auto;padding:40px 24px;background:#fff">
<div style="text-align:center;margin-bottom:28px">
  <div style="display:inline-flex;align-items:center;justify-content:center;width:52px;height:52px;border-radius:14px;background:#2563eb;margin-bottom:12px">
    <span style="color:#fff;font-size:24px">&#128161;</span>
  </div>
  <h1 style="font-size:22px;font-weight:800;color:#0f172a;margin:0">Curivio</h1>
</div>
<h2 style="font-size:18px;font-weight:700;color:#0f172a;margin-bottom:6px">Password Reset Code</h2>
<p style="color:#475569;margin-bottom:24px">Hi {display_name}, use the code below to reset your Curivio password.</p>
<div style="text-align:center;margin:32px 0">
  <div style="display:inline-block;background:#f1f5f9;border:1px solid #e2e8f0;border-radius:12px;padding:20px 36px">
    <span style="font-size:36px;font-weight:800;letter-spacing:0.25em;color:#1e3a5f;font-family:monospace">{code}</span>
  </div>
  <p style="color:#64748b;font-size:12px;margin-top:10px">Expires in {_RESET_EXPIRY_MINUTES} minutes</p>
</div>
<p style="color:#94a3b8;font-size:12px;text-align:center">If you didn't request this, you can safely ignore this email.</p>
<hr style="border:none;border-top:1px solid #f1f5f9;margin:28px 0">
<p style="color:#cbd5e1;font-size:11px;text-align:center">— The Curivio Team</p>
</body></html>"""
    return text, html


def _brevo_send(to_email: str, subject: str, text_body: str, html_body: str) -> None:
    import httpx
    brevo_key = os.getenv("BREVO_API_KEY", "")
    if not brevo_key:
        raise HTTPException(status_code=503, detail="Email service is not configured on this server.")
    brevo_from = os.getenv("BREVO_FROM", "studywallahdev@gmail.com")
    resp = httpx.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={"api-key": brevo_key, "Content-Type": "application/json"},
        json={
            "sender":      {"name": "Curivio", "email": brevo_from},
            "to":          [{"email": to_email}],
            "subject":     subject,
            "textContent": text_body,
            "htmlContent": html_body,
        },
        timeout=15.0,
    )
    if not resp.is_success:
        logger.error("[auth] Brevo error %s: %s", resp.status_code, resp.text)
        raise HTTPException(status_code=503, detail="Failed to send email. Please try again.")
    logger.info("[auth] Email sent via Brevo to %s", to_email)


def _send_code_email(email: str, name: str, code: str) -> None:
    display_name = name or "there"
    text_body, html_body = _build_email_bodies(display_name, code)
    _brevo_send(email, "Your Curivio password reset code", text_body, html_body)


def verify_reset_code(email: str, code: str) -> None:
    """Check the 6-digit code is valid and unexpired without consuming it. Raises HTTPException on failure."""
    email = email.lower().strip()
    _check_lockout(email, "reset")

    user = get_user_by_email(email)
    if not user:
        _record_verify_failure(email, "reset")
        raise HTTPException(status_code=400, detail="Incorrect code. Please try again.")

    with get_connection() as conn:
        # Only the latest unused token for this user is valid
        latest = conn.execute(
            "SELECT * FROM password_reset_tokens WHERE user_id = ? AND used = 0 ORDER BY id DESC LIMIT 1",
            (user["user_id"],),
        ).fetchone()

        if not latest or not _codes_match(latest["code_hash"], code):
            _record_verify_failure(email, "reset")
            raise HTTPException(status_code=400, detail="Incorrect code. Please try again.")

        expires_at = datetime.fromisoformat(latest["expires_at"])
        if datetime.now(timezone.utc) > expires_at:
            _record_verify_failure(email, "reset")
            raise HTTPException(status_code=400, detail="This code has expired. Please request a new one.")

    _clear_verify_lockout(email, "reset")


def consume_reset_token(email: str, code: str, new_password: str) -> None:
    """Validate the 6-digit code for the given email and reset the password."""
    if len(new_password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters.")

    email = email.lower().strip()
    _check_lockout(email, "reset")

    user = get_user_by_email(email)
    if not user:
        _record_verify_failure(email, "reset")
        raise HTTPException(status_code=400, detail="Invalid or expired code.")

    with get_connection() as conn:
        # Only the latest unused token for this user is valid
        latest = conn.execute(
            "SELECT * FROM password_reset_tokens WHERE user_id = ? AND used = 0 ORDER BY id DESC LIMIT 1",
            (user["user_id"],),
        ).fetchone()

        if not latest or not _codes_match(latest["code_hash"], code):
            _record_verify_failure(email, "reset")
            raise HTTPException(status_code=400, detail="Incorrect code. Please try again.")

        expires_at = datetime.fromisoformat(latest["expires_at"])
        if datetime.now(timezone.utc) > expires_at:
            _record_verify_failure(email, "reset")
            raise HTTPException(status_code=400, detail="This code has expired. Please request a new one.")

        conn.execute(
            "UPDATE users SET hashed_pw = ? WHERE user_id = ?",
            (hash_password(new_password), user["user_id"]),
        )
        conn.execute(
            "UPDATE password_reset_tokens SET used = 1 WHERE id = ?",
            (latest["id"],),
        )
    _clear_verify_lockout(email, "reset")


# ── Email verification for signup ────────────────────────────────────────────

_SIGNUP_EXPIRY_MINUTES = 5  # was 15 — see _RESET_EXPIRY_MINUTES's comment,
                            # same reasoning applies here.

# Pending signups live in the `pending_signups` table, not a module-level
# dict. The old in-memory dict was lost on every restart and, in any
# multi-worker/multi-instance deployment, only visible to whichever worker
# happened to handle the /auth/send-verify-email request — a signup whose
# /auth/complete-signup landed on a different worker would 400 with "no
# pending signup" even with the correct code. A DB row (same pattern already
# used for password_reset_tokens) is visible to every worker and survives a
# restart.


def _build_signup_email_bodies(display_name: str, code: str) -> tuple[str, str]:
    text = (
        f"Hi {display_name},\n\n"
        f"Your Curivio email verification code is:\n\n  {code}\n\n"
        f"This code expires in {_SIGNUP_EXPIRY_MINUTES} minutes. "
        "If you did not create a Curivio account, you can safely ignore this email.\n\n"
        "— The Curivio Team"
    )
    html = f"""<html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1a1a1a;max-width:480px;margin:0 auto;padding:40px 24px;background:#fff">
<div style="text-align:center;margin-bottom:28px">
  <div style="display:inline-flex;align-items:center;justify-content:center;width:52px;height:52px;border-radius:14px;background:#2563eb;margin-bottom:12px">
    <span style="color:#fff;font-size:24px">&#128161;</span>
  </div>
  <h1 style="font-size:22px;font-weight:800;color:#0f172a;margin:0">Curivio</h1>
</div>
<h2 style="font-size:18px;font-weight:700;color:#0f172a;margin-bottom:6px">Verify your email</h2>
<p style="color:#475569;margin-bottom:24px">Hi {display_name}, use the code below to verify your email address and complete your Curivio account setup.</p>
<div style="text-align:center;margin:32px 0">
  <div style="display:inline-block;background:#f1f5f9;border:1px solid #e2e8f0;border-radius:12px;padding:20px 36px">
    <span style="font-size:36px;font-weight:800;letter-spacing:0.25em;color:#1e3a5f;font-family:monospace">{code}</span>
  </div>
  <p style="color:#64748b;font-size:12px;margin-top:10px">Expires in {_SIGNUP_EXPIRY_MINUTES} minutes</p>
</div>
<p style="color:#94a3b8;font-size:12px;text-align:center">If you did not create a Curivio account, you can safely ignore this email.</p>
<hr style="border:none;border-top:1px solid #f1f5f9;margin:28px 0">
<p style="color:#cbd5e1;font-size:11px;text-align:center">— The Curivio Team</p>
</body></html>"""
    return text, html


def create_signup_verification(email: str, name: str, password: str) -> None:
    """Validate signup data, store a pending record, and email a 6-digit code."""
    email = email.lower().strip()
    _check_resend_cooldown(email, "signup")

    if get_user_by_email(email):
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    if len(password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")

    code       = str(secrets.randbelow(1_000_000)).zfill(6)
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=_SIGNUP_EXPIRY_MINUTES)).isoformat()

    with get_connection() as conn:
        conn.execute(
            """INSERT INTO pending_signups (email, name, hashed_pw, code_hash, expires_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(email) DO UPDATE SET
                   name       = excluded.name,
                   hashed_pw  = excluded.hashed_pw,
                   code_hash  = excluded.code_hash,
                   expires_at = excluded.expires_at""",
            (email, name.strip(), hash_password(password), _hash_code(code), expires_at),
        )
    _record_resend(email, "signup")

    display_name = name.strip() or "there"
    text_body, html_body = _build_signup_email_bodies(display_name, code)
    _brevo_send(email, "Verify your Curivio email", text_body, html_body)
    logger.info("[auth] Signup verification email sent to %s", email)


def complete_signup_verification(email: str, code: str) -> dict:
    """Verify the 6-digit code and create the user account. Returns token + user."""
    email = email.lower().strip()
    _check_lockout(email, "signup")

    with get_connection() as conn:
        pending = conn.execute(
            "SELECT * FROM pending_signups WHERE email = ?", (email,)
        ).fetchone()

    if not pending:
        _record_verify_failure(email, "signup")
        raise HTTPException(status_code=400, detail="No pending signup for this email. Please start over.")

    if not _codes_match(pending["code_hash"], code):
        _record_verify_failure(email, "signup")
        raise HTTPException(status_code=400, detail="Incorrect code. Please try again.")

    if datetime.now(timezone.utc) > datetime.fromisoformat(pending["expires_at"]):
        with get_connection() as conn:
            conn.execute("DELETE FROM pending_signups WHERE email = ?", (email,))
        _record_verify_failure(email, "signup")
        raise HTTPException(status_code=400, detail="This code has expired. Please request a new one.")

    # Check again in case email was registered by someone else during the window
    if get_user_by_email(email):
        with get_connection() as conn:
            conn.execute("DELETE FROM pending_signups WHERE email = ?", (email,))
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    user_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO users (user_id, email, name, hashed_pw) VALUES (?, ?, ?, ?)",
            (user_id, email, pending["name"], pending["hashed_pw"]),
        )
        conn.execute("DELETE FROM pending_signups WHERE email = ?", (email,))

    _clear_verify_lockout(email, "signup")

    token     = create_access_token(user_id)
    user_dict = {"user_id": user_id, "email": email, "name": pending["name"], "created_at": None}
    logger.info("[auth] New user registered after email verification: %s", email)
    return {"access_token": token, "token_type": "bearer", "user": user_dict}


# ── FastAPI dependency ────────────────────────────────────────────────────────

def _valid_payload(credentials: HTTPAuthorizationCredentials | None) -> dict:
    """Shared by get_current_user and get_current_token: decode + revocation
    check. A token minted before the jti claim existed has no "jti" key —
    treated as never-revoked (can't be individually blocklisted), it simply
    rides out its original expiry."""
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = _decode_token(credentials.credentials)
    jti = payload.get("jti")
    if jti and is_token_revoked(jti):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked")
    return payload


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    """
    FastAPI dependency. Inject with `user: dict = Depends(get_current_user)`.
    Returns the user dict on success; raises 401 if token is missing, invalid,
    or has been revoked (logout / password change since it was issued).
    """
    payload = _valid_payload(credentials)
    user    = get_user_by_id(payload["sub"])
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return _row_to_user(user)


def get_current_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    """
    FastAPI dependency for routes that need the raw JWT payload (jti/exp) to
    revoke the presented token itself — logout, change-password — rather than
    the user row. Same validity/revocation checks as get_current_user.
    """
    return _valid_payload(credentials)


def get_current_admin_user(current_user: dict = Depends(get_current_user)) -> dict:
    """
    FastAPI dependency. Inject with `user: dict = Depends(get_current_admin_user)`.
    Sub-dependency on get_current_user, so missing/invalid JWT behaves identically
    (401). A valid JWT for a non-admin email raises 404 instead of 403 — it must
    not reveal that a restricted area exists.
    """
    admin_emails = {e.strip().lower() for e in ADMIN_EMAILS.split(",") if e.strip()}
    if current_user["email"].lower() not in admin_emails:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return current_user
