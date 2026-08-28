"""
Backup / restore API.

Two audiences, two gates:

  * /admin/backups/*        — admin only (get_current_admin_user, same gate as
                              the rest of routes/admin.py). Lists snapshots,
                              takes one on demand, previews and runs restores.
  * /me/data-loss-request   — any signed-in user reporting their own data
                              missing, so an admin has something concrete to act
                              on instead of a support message that gets lost.

This is deliberately NOT the same thing as routes/db_recovery.py. That one is
gated by AUTH_SECRET_KEY in a header rather than by login, because it exists for
the case where corruption wiped the users table and there is no admin account
left to log in with. This module is the routine path for when the app is
healthy and someone needs data put back.

Restore is merge-only (INSERT OR IGNORE) — see backup_service.restore. It can
add rows back but can never overwrite or delete, which is what makes it safe to
put behind a button.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import config as cfg
from ..rate_limiter import limiter
from ..services import backup_service
from ..services.auth_service import get_current_admin_user, get_current_user
from ..utils.db import get_connection

logger = logging.getLogger(__name__)

admin_router = APIRouter(
    prefix="/admin",
    tags=["backups"],
    dependencies=[Depends(get_current_admin_user)],
)
requests_router = APIRouter(tags=["backups"])


# ── models ───────────────────────────────────────────────────────────────────

class RestoreRequest(BaseModel):
    filename: str
    # None = restore everything in the snapshot. A user_id restricts the merge
    # to rows the schema attributes to that user (see derive_user_scope).
    user_id: str | None = None


class DataLossRequestIn(BaseModel):
    description: str = Field(default="", max_length=2000)


class DataLossResolution(BaseModel):
    status: str
    admin_note: str = Field(default="", max_length=2000)


# ── admin: snapshots ─────────────────────────────────────────────────────────

@admin_router.get("/backups")
def list_backups():
    """Snapshots plus any quarantined corrupt files, newest first."""
    return {"backups": backup_service.list_snapshots(),
            "retention": {"max_snapshots": backup_service.MAX_SNAPSHOTS,
                          "interval_seconds": backup_service.INTERVAL_SECONDS}}


@admin_router.post("/backups/create")
def create_backup():
    result = backup_service.create_snapshot("manual", force=True)
    if not result["ok"]:
        raise HTTPException(status_code=500, detail=result["reason"])
    return result


@admin_router.get("/backups/users")
def users_in_backup(filename: str):
    """Accounts present in one snapshot — the pick list for a per-user restore."""
    try:
        return {"users": backup_service.users_in_snapshot(filename)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@admin_router.post("/backups/preview")
def preview_restore(body: RestoreRequest):
    """Dry run. Reports per-table what a restore would pull in and what is
    already live, and writes nothing. `unattributed_in_snapshot` on a per-user
    preview counts rows the snapshot cannot attribute to anyone (user_id was
    added as a nullable column by a later migration, so older rows carry NULL) —
    those need a full restore, a per-user one will never find them."""
    try:
        return backup_service.restore(body.filename, body.user_id, dry_run=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@admin_router.post("/backups/restore")
def run_restore(body: RestoreRequest, admin: dict = Depends(get_current_admin_user)):
    """Merge a snapshot back into the live DB. Additive only — never overwrites
    or deletes — and idempotent per (file, table, scope), so running it twice
    cannot double rows the way the pre-restore_log recovery tooling could."""
    # Snapshot the current state first. Restore can only add rows, so this is
    # not needed to undo it — it is here so an admin can diff before/after and
    # prove exactly what a restore changed.
    backup_service.create_snapshot("prerestore", force=True)
    try:
        result = backup_service.restore(body.filename, body.user_id, dry_run=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    logger.warning("[backup] restore by %s: file=%s scope=%s rows=%d",
                   admin["email"], body.filename, result["scope"], result["rows_restored"])
    return result


# ── admin: data-loss requests ────────────────────────────────────────────────

@admin_router.get("/data-loss-requests")
def list_data_loss_requests(status: str | None = None):
    sql = ("SELECT r.request_id, r.user_id, r.description, r.status, r.created_at, "
           "r.resolved_at, r.admin_note, u.email AS user_email, u.name AS user_name "
           "FROM data_loss_requests r LEFT JOIN users u ON u.user_id = r.user_id")
    params: tuple = ()
    if status:
        sql += " WHERE r.status = ?"
        params = (status,)
    sql += " ORDER BY r.created_at DESC LIMIT 200"
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return {"requests": [dict(r) for r in rows]}


@admin_router.patch("/data-loss-requests/{request_id}")
def resolve_data_loss_request(request_id: str, body: DataLossResolution):
    if body.status not in ("open", "resolved", "rejected"):
        raise HTTPException(status_code=400, detail="status must be open, resolved or rejected")
    resolved_at = None if body.status == "open" else datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE data_loss_requests SET status = ?, admin_note = ?, resolved_at = ? "
            "WHERE request_id = ?",
            (body.status, body.admin_note, resolved_at, request_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="no such request")
    return {"request_id": request_id, "status": body.status}


# ── user: report my data is missing ──────────────────────────────────────────

@requests_router.post("/me/data-loss-request")
@limiter.limit(cfg.AUTH_STRICT_RATE_LIMIT)
def raise_data_loss_request(
    request: Request,
    body: DataLossRequestIn,
    user: dict = Depends(get_current_user),
):
    """Let a user flag that their data is missing. Rate limited because any
    signed-in account can call it. One open request per user at a time — a
    second call while one is still open returns the existing one rather than
    filling the admin queue with duplicates of the same report."""
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT request_id FROM data_loss_requests WHERE user_id = ? AND status = 'open'",
            (user["user_id"],),
        ).fetchone()
        if existing:
            return {"request_id": existing["request_id"], "status": "open", "duplicate": True}
        request_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO data_loss_requests (request_id, user_id, description) VALUES (?,?,?)",
            (request_id, user["user_id"], body.description.strip()),
        )
    logger.warning("[backup] data-loss request %s raised by %s", request_id, user["email"])
    return {"request_id": request_id, "status": "open", "duplicate": False}


@requests_router.get("/me/data-loss-requests")
def my_data_loss_requests(user: dict = Depends(get_current_user)):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT request_id, description, status, created_at, resolved_at, admin_note "
            "FROM data_loss_requests WHERE user_id = ? ORDER BY created_at DESC LIMIT 20",
            (user["user_id"],),
        ).fetchall()
    return {"requests": [dict(r) for r in rows]}
