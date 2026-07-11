"""
Admin query service — read-only aggregation/lookup over llm_call_log and
learning_projects for the Feed-6.3 admin panel API (backend/routes/admin.py).

llm_call_log.user_id is mostly NULL for historical rows (writer calls didn't
consistently tag it). Every query here resolves the real user via a
project_id -> learning_projects.user_id join instead, falling back to the
raw logged column when present.
"""

from ..utils.db import get_connection

_TEST_DATA_EXCLUSION = "l.call_type IS NOT NULL AND l.call_type NOT LIKE 'smoke_test%'"

_ROW_COLUMNS = """
    l.id, l.run_id, l.parent_run_id, l.timestamp_start, l.timestamp_end,
    l.latency_ms, l.provider, l.model_requested, l.model_used, l.call_type,
    COALESCE(l.user_id, lp.user_id) AS user_id, l.project_id, l.day_ref,
    l.input, l.output, l.input_tokens, l.output_tokens, l.total_tokens,
    l.success, l.error_type, l.error_message, l.retry_count, l.created_at
"""

_FROM_JOIN = "FROM llm_call_log l LEFT JOIN learning_projects lp ON l.project_id = lp.project_id"

# Whitelisted sort keys -> real ORDER BY expressions. "provider" sorts by the
# same provider+model_used pair the table's combined column displays.
SORT_COLUMNS = {
    "created_at":   "l.created_at",
    "call_type":    "l.call_type",
    "provider":     "l.provider, l.model_used",
    "latency_ms":   "l.latency_ms",
    "total_tokens": "l.total_tokens",
    "success":      "l.success",
}


def _build_where(
    date_from: str | None,
    date_to: str | None,
    call_type: str | None,
    project_id: str | None,
    user_id: str | None,
    include_test_data: bool,
) -> tuple[str, list]:
    where = []
    params: list = []

    if date_from:
        where.append("l.created_at >= ?")
        params.append(date_from)
    if date_to:
        where.append("l.created_at <= ?")
        params.append(date_to)
    if call_type:
        where.append("l.call_type = ?")
        params.append(call_type)
    elif not include_test_data:
        where.append(_TEST_DATA_EXCLUSION)
    if project_id:
        where.append("l.project_id = ?")
        params.append(project_id)
    if user_id:
        where.append("COALESCE(l.user_id, lp.user_id) = ?")
        params.append(user_id)

    where_clause = f"WHERE {' AND '.join(where)}" if where else ""
    return where_clause, params


def _row_to_dict(row) -> dict:
    d = dict(row)
    d["success"] = bool(d["success"])
    return d


def list_call_logs(
    date_from: str | None,
    date_to: str | None,
    call_type: str | None,
    project_id: str | None,
    user_id: str | None,
    include_test_data: bool,
    limit: int,
    offset: int,
    sort_by: str = "created_at",
    sort_order: str = "desc",
) -> tuple[int, list[dict]]:
    where_clause, params = _build_where(date_from, date_to, call_type, project_id, user_id, include_test_data)
    order_expr = SORT_COLUMNS[sort_by]
    direction = "ASC" if sort_order == "asc" else "DESC"

    with get_connection() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) {_FROM_JOIN} {where_clause}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT {_ROW_COLUMNS}
            {_FROM_JOIN}
            {where_clause}
            ORDER BY {order_expr} {direction}
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()

    return total, [_row_to_dict(r) for r in rows]


def get_daily_volume(
    date_from: str | None,
    date_to: str | None,
    call_type: str | None,
    project_id: str | None,
    user_id: str | None,
    include_test_data: bool,
) -> list[dict]:
    """Real per-day call counts over the complete filtered set (no row cap)."""
    where_clause, params = _build_where(date_from, date_to, call_type, project_id, user_id, include_test_data)
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT DATE(l.created_at) AS date, COUNT(*) AS count
            {_FROM_JOIN}
            {where_clause}
            GROUP BY date
            ORDER BY date
            """,
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def get_call_tree(run_id: str) -> dict | None:
    """
    Return {"root": ..., "children": [...]}, or None if run_id matches nothing at all.

    In practice run_id is usually a LangChain orchestrator/chain id that was never
    itself logged as an llm_call_log row — only its leaf LLM sub-calls are, each
    carrying it as parent_run_id. So root is None for essentially every real batch
    today; it's populated only if a logged call itself turns out to have children.
    """
    with get_connection() as conn:
        root = conn.execute(
            f"SELECT {_ROW_COLUMNS} {_FROM_JOIN} WHERE l.run_id = ?", (run_id,)
        ).fetchone()
        children = conn.execute(
            f"SELECT {_ROW_COLUMNS} {_FROM_JOIN} WHERE l.parent_run_id = ? ORDER BY l.created_at ASC",
            (run_id,),
        ).fetchall()

    if not root and not children:
        return None

    return {
        "root": _row_to_dict(root) if root else None,
        "children": [_row_to_dict(r) for r in children],
    }


def get_call_summary(date_from: str | None, date_to: str | None, include_test_data: bool) -> dict:
    # call_type/project_id/user_id fixed at None here — this endpoint's aggregate
    # tiles are date+test-data scoped only (unchanged from Feed-6.4a).
    where_clause, params = _build_where(date_from, date_to, None, None, None, include_test_data)

    with get_connection() as conn:
        totals = conn.execute(
            f"""
            SELECT
                COUNT(*)                          AS total_calls,
                COALESCE(SUM(l.success), 0)       AS success_count,
                COALESCE(SUM(l.total_tokens), 0)  AS total_tokens,
                COALESCE(AVG(l.latency_ms), 0.0)  AS avg_latency_ms
            {_FROM_JOIN}
            {where_clause}
            """,
            params,
        ).fetchone()

        by_call_type = conn.execute(
            f"""
            SELECT l.call_type AS call_type, COUNT(*) AS count
            {_FROM_JOIN}
            {where_clause}
            GROUP BY l.call_type
            ORDER BY count DESC
            """,
            params,
        ).fetchall()

        by_model = conn.execute(
            f"""
            SELECT l.provider AS provider, l.model_used AS model_used, COUNT(*) AS count
            {_FROM_JOIN}
            {where_clause}
            GROUP BY l.provider, l.model_used
            ORDER BY count DESC
            """,
            params,
        ).fetchall()

    total_calls = totals["total_calls"]
    success_count = totals["success_count"]
    return {
        "total_calls": total_calls,
        "success_count": success_count,
        "error_count": total_calls - success_count,
        "success_rate": (success_count / total_calls) if total_calls else 0.0,
        "total_tokens": totals["total_tokens"],
        "avg_latency_ms": totals["avg_latency_ms"],
        "by_call_type": [dict(r) for r in by_call_type],
        "by_model": [dict(r) for r in by_model],
    }


def list_projects() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT lp.project_id, lp.name, lp.user_id, u.email AS user_email, lp.created_at
            FROM learning_projects lp
            LEFT JOIN users u ON lp.user_id = u.user_id
            ORDER BY lp.created_at DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]
