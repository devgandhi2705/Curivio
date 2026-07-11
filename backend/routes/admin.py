"""
Feed-6.3 admin query API. Every route sits behind get_current_admin_user() via
the router-level dependency below. No frontend yet — this is the data layer
the admin panel will call.
"""

from fastapi import APIRouter, Depends, HTTPException

from pydantic import BaseModel

from ..services import admin_service
from ..services.auth_service import get_current_admin_user

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(get_current_admin_user)],
)


# ── Response models ─────────────────────────────────────────────────────────

class AdminCallLogRow(BaseModel):
    id: int
    run_id: str
    parent_run_id: str | None
    timestamp_start: str
    timestamp_end: str
    latency_ms: int
    provider: str
    model_requested: str | None
    model_used: str | None
    call_type: str | None
    user_id: str | None
    project_id: str | None
    day_ref: int | None
    input: str
    output: str | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    success: bool
    error_type: str | None
    error_message: str | None
    retry_count: int
    created_at: str


class AdminCallLogListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    rows: list[AdminCallLogRow]


class AdminDailyVolumeEntry(BaseModel):
    date: str
    count: int


class AdminDailyVolumeResponse(BaseModel):
    total: int
    by_day: list[AdminDailyVolumeEntry]


class AdminCallTreeResponse(BaseModel):
    root: AdminCallLogRow | None
    children: list[AdminCallLogRow]


class AdminSummaryByCallType(BaseModel):
    call_type: str | None
    count: int


class AdminSummaryByModel(BaseModel):
    provider: str
    model_used: str | None
    count: int


class AdminSummaryResponse(BaseModel):
    total_calls: int
    success_count: int
    error_count: int
    success_rate: float
    total_tokens: int
    avg_latency_ms: float
    by_call_type: list[AdminSummaryByCallType]
    by_model: list[AdminSummaryByModel]


class AdminProjectRow(BaseModel):
    project_id: str
    name: str
    user_id: str | None
    user_email: str | None
    created_at: str


class AdminProjectListResponse(BaseModel):
    projects: list[AdminProjectRow]


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("/calls", response_model=AdminCallLogListResponse)
async def admin_list_calls(
    date_from: str | None = None,
    date_to: str | None = None,
    call_type: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    include_test_data: bool = False,
    limit: int = 20,
    offset: int = 0,
    sort_by: str = "created_at",
    sort_order: str = "desc",
):
    if sort_by not in admin_service.SORT_COLUMNS:
        raise HTTPException(status_code=400, detail=f"sort_by must be one of {sorted(admin_service.SORT_COLUMNS)}")
    if sort_order not in ("asc", "desc"):
        raise HTTPException(status_code=400, detail="sort_order must be 'asc' or 'desc'")

    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    total, rows = admin_service.list_call_logs(
        date_from, date_to, call_type, project_id, user_id, include_test_data, limit, offset,
        sort_by, sort_order,
    )
    return AdminCallLogListResponse(total=total, limit=limit, offset=offset, rows=rows)


@router.get("/calls/volume", response_model=AdminDailyVolumeResponse)
async def admin_calls_volume(
    date_from: str | None = None,
    date_to: str | None = None,
    call_type: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    include_test_data: bool = False,
):
    by_day = admin_service.get_daily_volume(date_from, date_to, call_type, project_id, user_id, include_test_data)
    return AdminDailyVolumeResponse(total=sum(d["count"] for d in by_day), by_day=by_day)


@router.get("/calls/{run_id}/tree", response_model=AdminCallTreeResponse)
async def admin_call_tree(run_id: str):
    tree = admin_service.get_call_tree(run_id)
    if tree is None:
        raise HTTPException(status_code=404, detail="No call found for this run_id")
    return AdminCallTreeResponse(**tree)


@router.get("/summary", response_model=AdminSummaryResponse)
async def admin_summary(
    date_from: str | None = None,
    date_to: str | None = None,
    include_test_data: bool = False,
):
    return AdminSummaryResponse(
        **admin_service.get_call_summary(date_from, date_to, include_test_data)
    )


@router.get("/projects", response_model=AdminProjectListResponse)
async def admin_list_projects():
    return AdminProjectListResponse(projects=admin_service.list_projects())
