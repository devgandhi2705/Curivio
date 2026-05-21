"""
Auth service — user registration, login, JWT issuance, and FastAPI dependency.
"""

import logging
import os
import secrets
import smtplib
import uuid
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

import bcrypt as _bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from ..utils.db import get_connection

# ── Config ────────────────────────────────────────────────────────────────────

SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "change-me-in-production-use-a-long-random-string")
ALGORITHM  = "HS256"
from ..config import AUTH_TOKEN_EXPIRE_DAYS as TOKEN_EXPIRE_DAYS, SMTP_HOST, SMTP_PORT

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
    return jwt.encode({"sub": user_id, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def _decode_token(token: str) -> str:
    """Decode a JWT and return the user_id (sub claim). Raises HTTPException on failure."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str | None = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return user_id
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


# ── DB helpers ────────────────────────────────────────────────────────────────

def _row_to_user(row) -> dict:
    return {
        "user_id":    row["user_id"],
        "email":      row["email"],
        "name":       row["name"],
        "created_at": row["created_at"],
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
    user_dict = {"user_id": user_id, "email": email, "name": name.strip(), "created_at": None}
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


# ── Password reset (6-digit code) ────────────────────────────────────────────

_RESET_EXPIRY_MINUTES = 15


def create_reset_token(email: str) -> dict:
    """
    Generate a 6-digit code, store it, and email it. Silent on unknown email.

    Returns:
      {}                                  — email sent (or unknown email, silenced)
      {"code": "123456", "smtp_not_configured": True}  — SMTP not set up; code shown inline
    """
    user = get_user_by_email(email.lower().strip())
    if not user:
        return {}

    code = str(secrets.randbelow(1_000_000)).zfill(6)
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=_RESET_EXPIRY_MINUTES)).isoformat()

    with get_connection() as conn:
        conn.execute(
            "UPDATE password_reset_tokens SET used = 1 WHERE user_id = ? AND used = 0",
            (user["user_id"],),
        )
        conn.execute(
            "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (?, ?, ?)",
            (user["user_id"], code, expires_at),
        )

    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")
    if not smtp_user or not smtp_pass:
        logger.warning("[auth] SMTP not configured — returning code inline for %s", email)
        return {"code": code, "smtp_not_configured": True}

    _send_code_email(user["email"], user["name"], code)
    return {}


def _send_code_email(email: str, name: str, code: str) -> None:
    smtp_host = SMTP_HOST
    smtp_port = SMTP_PORT
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")
    smtp_from = os.getenv("SMTP_FROM", smtp_user)

    if not smtp_user or not smtp_pass:
        logger.warning("[auth] SMTP not configured — reset code for %s: %s", email, code)
        raise HTTPException(
            status_code=503,
            detail="Email service is not configured on this server. Contact the administrator.",
        )

    display_name = name or "there"
    text_body = (
        f"Hi {display_name},\n\n"
        f"Your Curivio password reset code is:\n\n  {code}\n\n"
        f"This code expires in {_RESET_EXPIRY_MINUTES} minutes. "
        "If you didn't request this, you can safely ignore this email.\n\n"
        "— The Curivio Team"
    )
    html_body = f"""<html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1a1a1a;max-width:480px;margin:0 auto;padding:40px 24px;background:#fff">
<div style="text-align:center;margin-bottom:28px">
  <div style="display:inline-flex;align-items:center;justify-content:center;width:52px;height:52px;border-radius:14px;background:#2563eb;margin-bottom:12px">
    <span style="color:#fff;font-size:24px">💡</span>
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

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Your Curivio password reset code"
    msg["From"]    = f"Curivio <{smtp_from}>"
    msg["To"]      = email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as srv:
            srv.starttls()
            srv.login(smtp_user, smtp_pass)
            srv.sendmail(smtp_from, email, msg.as_string())
    except Exception as exc:
        logger.error("[auth] Failed to send reset email to %s: %s", email, exc)
        raise HTTPException(status_code=500, detail="Failed to send reset email. Please try again later.")


def verify_reset_code(email: str, code: str) -> None:
    """Check the 6-digit code is valid and unexpired without consuming it. Raises HTTPException on failure."""
    user = get_user_by_email(email.lower().strip())
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect code. Please try again.")

    with get_connection() as conn:
        # Only the latest unused token for this user is valid
        latest = conn.execute(
            "SELECT * FROM password_reset_tokens WHERE user_id = ? AND used = 0 ORDER BY id DESC LIMIT 1",
            (user["user_id"],),
        ).fetchone()

        if not latest or latest["token"] != code.strip():
            raise HTTPException(status_code=400, detail="Incorrect code. Please try again.")

        expires_at = datetime.fromisoformat(latest["expires_at"])
        if datetime.now(timezone.utc) > expires_at:
            raise HTTPException(status_code=400, detail="This code has expired. Please request a new one.")


def consume_reset_token(email: str, code: str, new_password: str) -> None:
    """Validate the 6-digit code for the given email and reset the password."""
    if len(new_password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters.")

    user = get_user_by_email(email.lower().strip())
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired code.")

    with get_connection() as conn:
        # Only the latest unused token for this user is valid
        latest = conn.execute(
            "SELECT * FROM password_reset_tokens WHERE user_id = ? AND used = 0 ORDER BY id DESC LIMIT 1",
            (user["user_id"],),
        ).fetchone()

        if not latest or latest["token"] != code.strip():
            raise HTTPException(status_code=400, detail="Incorrect code. Please try again.")

        expires_at = datetime.fromisoformat(latest["expires_at"])
        if datetime.now(timezone.utc) > expires_at:
            raise HTTPException(status_code=400, detail="This code has expired. Please request a new one.")

        conn.execute(
            "UPDATE users SET hashed_pw = ? WHERE user_id = ?",
            (hash_password(new_password), user["user_id"]),
        )
        conn.execute(
            "UPDATE password_reset_tokens SET used = 1 WHERE id = ?",
            (latest["id"],),
        )


# ── FastAPI dependency ────────────────────────────────────────────────────────

def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    """
    FastAPI dependency. Inject with `user: dict = Depends(get_current_user)`.
    Returns the user dict on success; raises 401 if token is missing or invalid.
    """
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    user_id = _decode_token(credentials.credentials)
    user    = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return _row_to_user(user)
