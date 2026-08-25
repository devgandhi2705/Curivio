"""
Feed-6.3 admin query API. Every route sits behind get_current_admin_user() via
the router-level dependency below. No frontend yet — this is the data layer
the admin panel will call.

Phase N: routes are plain `def`, not `async def` — every body calls sqlite3
(sync, no asyncio support) directly with no `await`. As `async def`, each
blocking DB call monopolized the single event loop thread, so the panel's
concurrent summary/operations-summary/volume/grouped requests serialized
server-side despite firing in parallel from the frontend (measured: ~4x
the slowest individual query, vs ~= the slowest once parallelized). Plain
`def` lets FastAPI dispatch each to its threadpool instead.
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from pydantic import BaseModel

from .. import config as cfg
from ..rate_limiter import limiter
from ..services import admin_service
from ..services.auth_service import get_current_admin_user

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(get_current_admin_user)],
)

ADMIN_READ_RATE_LIMIT   = cfg.ADMIN_READ_RATE_LIMIT
ADMIN_EXPORT_RATE_LIMIT = cfg.ADMIN_EXPORT_RATE_LIMIT


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
    # Phase O-Task2 — real email via admin_service._ROW_COLUMNS' scalar
    # subquery. Null whenever user_id itself is null/unresolved, or when it
    # resolves to something that isn't a real users row (historical synthetic
    # test IDs — see N-recon).
    user_email: str | None
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
    # Phase O — Task 1: which of hour/day/week/month admin_service._pick_granularity
    # chose for this range, so the frontend formats ticks/hover correctly
    # instead of guessing from the bucket string's shape (ambiguous: a
    # day-bucket on the 1st of the month looks identical to a month-bucket).
    granularity: str
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


class AdminSummaryBySurface(BaseModel):
    surface: str | None
    count: int


class AdminSummaryByErrorType(BaseModel):
    error_type: str | None
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
    by_surface: list[AdminSummaryBySurface]
    by_error_type: list[AdminSummaryByErrorType]


class AdminOperationSummaryResponse(BaseModel):
    total_operations: int
    succeeded_operations: int
    failed_operations: int
    operation_success_rate: float
    avg_latency_per_operation_ms: float


class AdminProjectRow(BaseModel):
    project_id: str
    name: str
    user_id: str | None
    user_email: str | None
    created_at: str


class AdminProjectListResponse(BaseModel):
    projects: list[AdminProjectRow]


class AdminCallGroupRow(BaseModel):
    trace_id: str | None
    surface: str | None
    action_type: str | None
    started_at: str
    ended_at: str
    row_count: int
    all_succeeded: bool
    has_web_search: bool
    # Phase H — group-level sums from the shared groups CTE. Nullable: a group
    # whose rows all have NULL total_tokens sums to NULL, not 0.
    op_latency_ms: int | None
    op_tokens: int | None
    # Phase O-Task2 — the group's FIRST_VALUE-picked user resolved to a real
    # email, or null (see admin_service.list_grouped_calls). The frontend
    # picks the fallback label ("Unattributed" vs. "Shared") from `surface`.
    user_email: str | None
    rows: list[AdminCallLogRow]


class AdminCallGroupListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    groups: list[AdminCallGroupRow]


class AdminCallExportResponse(BaseModel):
    """Phase I — the COMPLETE filtered set, not a page. `returned` < `total`
    only when the export cap was hit, and `truncated` says so explicitly so
    the UI can warn instead of silently handing over a partial file."""
    total: int
    returned: int
    truncated: bool
    groups: list[AdminCallGroupRow]


# ── Routes ───────────────────────────────────────────────────────────────────

def _validate_status_action(status: str | None, action_type: str | None) -> None:
    if status is not None and status not in admin_service.STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {list(admin_service.STATUSES)}")
    if action_type is not None and action_type not in admin_service.ACTION_TYPES:
        raise HTTPException(status_code=400, detail=f"action_type must be one of {admin_service.ACTION_TYPES}")


# Phase R — a bare " " search box value must mean "no search", same as "" does
# for every other optional query param here (buildQuery on the frontend
# already drops "" but not whitespace-only input).
def _norm_search(search: str | None) -> str | None:
    return search.strip() or None if search else None


@router.get("/calls", response_model=AdminCallLogListResponse)
@limiter.limit(ADMIN_READ_RATE_LIMIT)
def admin_list_calls(
    request: Request,
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
    status: str | None = None,
    action_type: str | None = None,
    day_ref: int | None = None,
    target_language: str | None = None,
    search: str | None = None,
):
    if sort_by not in admin_service.SORT_COLUMNS:
        raise HTTPException(status_code=400, detail=f"sort_by must be one of {sorted(admin_service.SORT_COLUMNS)}")
    if sort_order not in ("asc", "desc"):
        raise HTTPException(status_code=400, detail="sort_order must be 'asc' or 'desc'")
    _validate_status_action(status, action_type)

    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    total, rows = admin_service.list_call_logs(
        date_from, date_to, call_type, project_id, user_id, include_test_data, limit, offset,
        sort_by, sort_order, status, action_type, day_ref, target_language, search=_norm_search(search),
    )
    return AdminCallLogListResponse(total=total, limit=limit, offset=offset, rows=rows)


@router.get("/calls/grouped", response_model=AdminCallGroupListResponse)
@limiter.limit(ADMIN_READ_RATE_LIMIT)
def admin_list_calls_grouped(
    request: Request,
    date_from: str | None = None,
    date_to: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    include_test_data: bool = False,
    status: str | None = None,
    action_type: str | None = None,
    day_ref: int | None = None,
    target_language: str | None = None,
    limit: int = admin_service.GROUP_PAGE_SIZE,
    offset: int = 0,
    sort_by: str = "timestamp",
    sort_order: str = "desc",
    search: str | None = None,
):
    """Paginated GROUPS (by trace_id), not rows — see admin_service.list_grouped_calls
    for the grouping/filter semantics. A pre-Phase-3 row with no trace_id comes
    back as its own singleton group.

    Phase Q: sort_by/sort_order added, same validate-against-allowlist shape
    as /calls' sort_by/SORT_COLUMNS.

    Phase R: search — matches input/output on ANY row of a group, surfaces
    the whole group (see admin_service._groups_cte's has_search_match),
    ANDed with every other active filter."""
    if sort_by not in admin_service.GROUP_SORT_COLUMNS:
        raise HTTPException(status_code=400, detail=f"sort_by must be one of {sorted(admin_service.GROUP_SORT_COLUMNS)}")
    if sort_order not in ("asc", "desc"):
        raise HTTPException(status_code=400, detail="sort_order must be 'asc' or 'desc'")
    _validate_status_action(status, action_type)

    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)
    total, groups = admin_service.list_grouped_calls(
        date_from, date_to, project_id, user_id, include_test_data,
        status, action_type, day_ref, target_language, limit, offset,
        sort_by, sort_order, search=_norm_search(search),
    )
    return AdminCallGroupListResponse(total=total, limit=limit, offset=offset, groups=groups)


@router.get("/calls/export", response_model=AdminCallExportResponse)
@limiter.limit(ADMIN_EXPORT_RATE_LIMIT)
def admin_export_calls(
    request: Request,
    date_from: str | None = None,
    date_to: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    include_test_data: bool = False,
    status: str | None = None,
    action_type: str | None = None,
    day_ref: int | None = None,
    target_language: str | None = None,
    search: str | None = None,
):
    """Phase I — every group matching these filters, unpaginated, for a bulk
    download. Same filter params and same underlying query as /calls/grouped,
    so an export always matches the list it came from; the only difference is
    that it isn't cut to a page. See admin_service.EXPORT_MAX_GROUPS for the
    ceiling and why paginating /calls/grouped instead isn't viable."""
    _validate_status_action(status, action_type)

    total, truncated, groups = admin_service.export_grouped_calls(
        date_from, date_to, project_id, user_id, include_test_data,
        status, action_type, day_ref, target_language, search=_norm_search(search),
    )
    return AdminCallExportResponse(
        total=total, returned=len(groups), truncated=truncated, groups=groups
    )


@router.get("/calls/volume", response_model=AdminDailyVolumeResponse)
@limiter.limit(ADMIN_READ_RATE_LIMIT)
def admin_calls_volume(
    request: Request,
    date_from: str | None = None,
    date_to: str | None = None,
    call_type: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    include_test_data: bool = False,
    status: str | None = None,
    action_type: str | None = None,
    day_ref: int | None = None,
    target_language: str | None = None,
    search: str | None = None,
):
    _validate_status_action(status, action_type)
    granularity, by_day = admin_service.get_daily_volume(
        date_from, date_to, call_type, project_id, user_id, include_test_data,
        status, action_type, day_ref, target_language, search=_norm_search(search),
    )
    return AdminDailyVolumeResponse(
        total=sum(d["count"] for d in by_day), granularity=granularity, by_day=by_day
    )


@router.get("/calls/{run_id}/tree", response_model=AdminCallTreeResponse)
@limiter.limit(ADMIN_READ_RATE_LIMIT)
def admin_call_tree(request: Request, run_id: str):
    tree = admin_service.get_call_tree(run_id)
    if tree is None:
        raise HTTPException(status_code=404, detail="No call found for this run_id")
    return AdminCallTreeResponse(**tree)


@router.get("/summary", response_model=AdminSummaryResponse)
@limiter.limit(ADMIN_READ_RATE_LIMIT)
def admin_summary(
    request: Request,
    date_from: str | None = None,
    date_to: str | None = None,
    include_test_data: bool = False,
    call_type: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    status: str | None = None,
    action_type: str | None = None,
    day_ref: int | None = None,
    target_language: str | None = None,
    search: str | None = None,
):
    _validate_status_action(status, action_type)
    return AdminSummaryResponse(
        **admin_service.get_call_summary(
            date_from, date_to, include_test_data,
            call_type, project_id, user_id, status, action_type,
            day_ref, target_language, search=_norm_search(search),
        )
    )


@router.get("/operations/summary", response_model=AdminOperationSummaryResponse)
@limiter.limit(ADMIN_READ_RATE_LIMIT)
def admin_operation_summary(
    request: Request,
    date_from: str | None = None,
    date_to: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    include_test_data: bool = False,
    status: str | None = None,
    action_type: str | None = None,
    day_ref: int | None = None,
    target_language: str | None = None,
    search: str | None = None,
):
    """Group-level (trace_id/operation) counterpart to /admin/summary's row
    totals — see admin_service.get_operation_summary. Same filter dimensions
    and same whitelist validation as /admin/calls/grouped."""
    _validate_status_action(status, action_type)
    return AdminOperationSummaryResponse(
        **admin_service.get_operation_summary(
            date_from, date_to, project_id, user_id, include_test_data,
            status, action_type, day_ref, target_language, search=_norm_search(search),
        )
    )


@router.get("/projects", response_model=AdminProjectListResponse)
@limiter.limit(ADMIN_READ_RATE_LIMIT)
def admin_list_projects(request: Request):
    return AdminProjectListResponse(projects=admin_service.list_projects())
