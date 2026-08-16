"""
Admin query service — read-only aggregation/lookup over llm_call_log and
learning_projects for the Feed-6.3 admin panel API (backend/routes/admin.py).

llm_call_log.user_id is mostly NULL for historical rows (writer calls didn't
consistently tag it). Every query here resolves the real user via a
project_id -> learning_projects.user_id join instead, falling back to the
raw logged column when present.
"""

from datetime import date

from ..utils.db import get_connection

_TEST_DATA_EXCLUSION = "l.call_type IS NOT NULL AND l.call_type NOT LIKE 'smoke_test%'"

# Phase B2 (Admin-8) — action_type values that map directly onto the surface
# column. 'web_search' is deliberately NOT in this set: it isn't a surface,
# it's a cross-cutting "this operation included a real web search" flag (see
# _WEB_SEARCH_CALL_TYPES below), handled separately in _build_where/_build_group_where.
_ACTION_TYPE_SURFACES = {"feed_legacy", "feed_v2", "chat", "explain", "translate", "tts", "intelligence_feed", "chat_upload"}

# The literal call_type that represents an outbound web search. Deliberately
# excludes tinyfish_fetch (fetching a URL you already have isn't "searching"),
# and deliberately NOT chat_web_search/chat_deep_research (those are the
# tool-wrapper rows, not the search itself) — every chat/deep-research/feed
# operation that actually searches always also logs a real tinyfish_search
# row in the same trace_id group, so filtering on this one call_type alone
# correctly flags the whole group without double-counting.
_WEB_SEARCH_CALL_TYPES = ("tinyfish_search",)

# Phase K — target_language bug fix. Two real rows (id 5848/5849, both real
# Hindi DeepL translations, output='संयोग') have l.target_language = NULL:
# confirmed via mtime (translate_service.py last edited 2026-08-14 10:38:10
# IST — the target_language kwarg wiring) vs these rows' created_at (10:07:18
# IST) that they predate that fix by ~31min; row 5910 (fr), written ~30min
# AFTER the file edit, has target_language populated correctly. So the write
# path is NOT currently broken — only these historical rows are. This is NOT
# the created_at bug's shape (a format mismatch on data that's always fully
# present) — the column is genuinely NULL. But the real value is still
# recoverable: _log_translate() is translate_service.py's only writer and
# _call_deepl()'s ONLY caller (confirmed: grep found no other target_language/
# _log_translate/_call_deepl reference anywhere in backend/), and it
# unconditionally builds input_text as
# f"term={term!r} target_language={target_language!r}" — so every translate
# row's `input` ends with target_language='xx' (a real 2-char ALLOWED_LANGUAGES
# code, always quoted, always the last 4 chars). Recovering it from there
# rather than leaving these rows silently unfindable — same "don't silently
# leave historical rows broken" standard as the created_at fix, adapted to
# what's actually wrong here (a missing value, not a format mismatch).
_TARGET_LANGUAGE_EXPR = """COALESCE(
    l.target_language,
    CASE WHEN l.surface = 'translate' AND l.input LIKE '%target_language=%'
         THEN SUBSTR(l.input, -3, 2) END
)"""

# Public — the route layer validates action_type/status query params against these.
ACTION_TYPES = sorted(_ACTION_TYPE_SURFACES | {"web_search"})
STATUSES = ("success", "failed")

# Phase O-Task2: user_email via a correlated scalar subquery, not a JOIN
# folded into _FROM_JOIN — users.user_id would collide with the bare
# `user_id` columns _build_where/_build_group_where already reference
# unqualified elsewhere (and with groups.user_id at the group level below),
# and a real JOIN there would fan into every _groups_cte consumer (the
# candidate-narrowing/window-function pipeline Phase N/O spent three
# phases keeping fast) for a value only the final, already-paginated
# output rows need. A scalar subquery touches neither: it's evaluated only
# for the rows actually selected, and users.user_id never enters the outer
# query's column namespace at all.
_ROW_COLUMNS = """
    l.id, l.run_id, l.parent_run_id, l.timestamp_start, l.timestamp_end,
    l.latency_ms, l.provider, l.model_requested, l.model_used, l.call_type,
    COALESCE(l.user_id, lp.user_id) AS user_id,
    (SELECT email FROM users u WHERE u.user_id = COALESCE(l.user_id, lp.user_id)) AS user_email,
    l.project_id, l.day_ref,
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
    status: str | None = None,
    action_type: str | None = None,
    day_ref: int | None = None,
    target_language: str | None = None,
    search: str | None = None,
) -> tuple[str, list]:
    where = []
    params: list = []

    # created_at is stored in TWO real shapes: 'YYYY-MM-DD HH:MM:SS' (5844
    # rows) and ISO 'YYYY-MM-DDTHH:MM:SS.ffffff+00:00' (221 rows, including
    # every row written today). Compared as raw TEXT, 'T' (0x54) sorts ABOVE
    # ' ' (0x20), so an upper bound of "<date> 23:59:59" silently dropped
    # every T-format row on the final day of the range — a real 0-of-219
    # miss. Normalizing BOTH sides with DATE() is format-agnostic (SQLite's
    # DATE() parses both shapes) and makes the caller's time-of-day suffix
    # irrelevant rather than load-bearing.
    if date_from:
        where.append("DATE(l.created_at) >= DATE(?)")
        params.append(date_from)
    if date_to:
        where.append("DATE(l.created_at) <= DATE(?)")
        params.append(date_to)
    if call_type:
        where.append("l.call_type = ?")
        params.append(call_type)
    if project_id:
        where.append("l.project_id = ?")
        params.append(project_id)
    if user_id:
        where.append("COALESCE(l.user_id, lp.user_id) = ?")
        params.append(user_id)
    if status == "success":
        where.append("l.success = 1")
    elif status == "failed":
        where.append("l.success = 0")
    if action_type in _ACTION_TYPE_SURFACES:
        where.append("l.surface = ?")
        params.append(action_type)
    elif action_type == "web_search":
        placeholders = ",".join("?" * len(_WEB_SEARCH_CALL_TYPES))
        where.append(f"""(
            l.call_type IN ({placeholders})
            OR (l.trace_id IS NOT NULL AND l.trace_id IN (
                SELECT trace_id FROM llm_call_log
                WHERE call_type IN ({placeholders}) AND trace_id IS NOT NULL
            ))
        )""")
        params.extend(_WEB_SEARCH_CALL_TYPES)
        params.extend(_WEB_SEARCH_CALL_TYPES)
    if day_ref is not None:
        where.append("l.day_ref = ?")
        params.append(day_ref)
    if target_language:
        where.append(f"{_TARGET_LANGUAGE_EXPR} = ?")
        params.append(target_language)
    if search:
        # Phase R — real EXPLAIN QUERY PLAN + timing on the live DB (6,453
        # rows, avg input/output ~1.9KB/2.6KB, 18.5MB combined) showed a plain
        # LIKE scan over input/output at 42-125ms even with realistic filter
        # combinations — nowhere near FTS5 territory. Same trace-sibling OR
        # shape as the web_search filter above (l.trace_id IN (SELECT ... )):
        # a match on ANY row in a group must surface the WHOLE group, same
        # "always show the whole group" precedent, confirmed against real
        # data (id 5861's "audit challenges" match pulls in its full 23-row
        # trace_id group, not just the one matching row).
        where.append("""(
            (l.input LIKE ? OR l.output LIKE ?)
            OR (l.trace_id IS NOT NULL AND l.trace_id IN (
                SELECT trace_id FROM llm_call_log
                WHERE (input LIKE ? OR output LIKE ?) AND trace_id IS NOT NULL
            ))
        )""")
        like_term = f"%{search}%"
        params.extend([like_term, like_term, like_term, like_term])

    # Phase B2: real is_test column replaces the call_type-prefix heuristic.
    # A specific call_type filter no longer implicitly bypasses the test-data
    # exclusion — is_test is now an independent, honest dimension.
    if not include_test_data:
        where.append("l.is_test = 0")

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
    status: str | None = None,
    action_type: str | None = None,
    day_ref: int | None = None,
    target_language: str | None = None,
    search: str | None = None,
) -> tuple[int, list[dict]]:
    where_clause, params = _build_where(
        date_from, date_to, call_type, project_id, user_id, include_test_data,
        status, action_type, day_ref, target_language, search,
    )
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


# Phase O — Task 1: bucket size adapts to the selected range so the chart
# stays readable at ~15-40 points regardless of span, instead of always
# bucketing by day (which gives 366 unreadable points for a 1-year range and
# only 1 for "Today"). Real strftime()/DATE() modifiers — verified against
# both real created_at storage shapes (space-separated and ISO-with-'T');
# SQLite's date functions share one flexible parser, same as the existing
# DATE() filter comparisons.
_BUCKET_EXPR = {
    # Zero-padded, lexically sortable, and directly `new Date()`-parseable
    # on the frontend without a synthetic "T00:00:00" suffix.
    "hour":  "strftime('%Y-%m-%dT%H:00:00', l.created_at)",
    "day":   "DATE(l.created_at)",
    # Monday of the row's week. 'weekday N' + fixed offset is the common but
    # WRONG idiom here (it's a no-op when created_at already IS weekday N,
    # so a fixed "-7 days" after it would jump a full week too early for
    # any row that already falls on a Monday). strftime('%w', ..) gives
    # 0=Sunday..6=Saturday; (dow+6)%7 converts to "days since Monday"
    # (0 for Monday itself), which is what to subtract — verified against
    # real rows that the result's own %w is always 1 (Monday).
    "week":  "DATE(l.created_at, '-' || ((CAST(strftime('%w', l.created_at) AS INTEGER) + 6) % 7) || ' days')",
    "month": "strftime('%Y-%m-01', l.created_at)",
}
_GRANULARITY_MAX_BUCKETS = 40  # ceiling; see _pick_granularity


def _pick_granularity(date_from: str | None, date_to: str | None) -> str:
    """Finest granularity (hour > day > week > month) whose bucket count
    over [date_from, date_to] doesn't exceed _GRANULARITY_MAX_BUCKETS.

    Real span/bucket-count data behind this (live DB, Phase O precondition):
    Today/Yesterday (1-day span) -> 24 hourly buckets; 7 Days (7d) -> 168
    hourly (too many) so falls to 7 daily; 30 Days -> 30 daily (in-band);
    90 Days -> 90 daily (too many) falls to ~13 weekly; 6 Months (~182d) ->
    ~26 weekly (in-band); 1 Year (~366d) -> ~53 weekly (too many) falls to
    ~12 monthly. The nominal 15-40 target is a soft floor / hard ceiling in
    practice: avoiding overplotting (the ceiling) matters more than hitting
    the floor, and neither 7-day (7 pts) nor 1-year (~12 pts) can clear 15
    without their next-finer option blowing past 40 — both land on the
    least-bad side of that tradeoff, not a miss.

    An unbounded range (missing date_from or date_to) has no span to derive
    a bucket size from, so it defaults to the coarsest option (month) —
    safe, since an open-ended range could span years.
    """
    if not date_from or not date_to:
        return "month"
    span_days = (date.fromisoformat(date_to[:10]) - date.fromisoformat(date_from[:10])).days + 1
    span_days = max(span_days, 1)
    if span_days * 24 <= _GRANULARITY_MAX_BUCKETS:
        return "hour"
    if span_days <= _GRANULARITY_MAX_BUCKETS:
        return "day"
    if -(-span_days // 7) <= _GRANULARITY_MAX_BUCKETS:  # ceil(span_days / 7)
        return "week"
    return "month"


def get_daily_volume(
    date_from: str | None,
    date_to: str | None,
    call_type: str | None,
    project_id: str | None,
    user_id: str | None,
    include_test_data: bool,
    status: str | None = None,
    action_type: str | None = None,
    day_ref: int | None = None,
    target_language: str | None = None,
    search: str | None = None,
) -> tuple[str, list[dict]]:
    """Real per-bucket call counts over the complete filtered set (no row
    cap). Returns (granularity, buckets) — see _pick_granularity.

    Phase F: status/action_type/day_ref/target_language wired in — previously
    only date/call_type/project/user/test-data were honored, so the trend
    line silently ignored the Action Type filter (and everything else added
    since B2) while every other view on the page already respected it.
    """
    where_clause, params = _build_where(
        date_from, date_to, call_type, project_id, user_id, include_test_data,
        status, action_type, day_ref, target_language, search,
    )
    granularity = _pick_granularity(date_from, date_to)
    bucket_expr = _BUCKET_EXPR[granularity]
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT {bucket_expr} AS date, COUNT(*) AS count
            {_FROM_JOIN}
            {where_clause}
            GROUP BY date
            ORDER BY date
            """,
            params,
        ).fetchall()
    return granularity, [dict(r) for r in rows]


def _build_group_where(
    date_from: str | None,
    date_to: str | None,
    project_id: str | None,
    user_id: str | None,
    include_test_data: bool,
    status: str | None,
    action_type: str | None,
    day_ref: int | None,
    target_language: str | None,
    search: str | None = None,
) -> tuple[str, list]:
    """Filters for the pre-aggregated `groups` CTE in list_grouped_calls — column
    names here are the groups CTE's own aggregate columns (no `l.` prefix, no join).

    Every dimension here is a group-level aggregate (MAX/MIN across the group's
    rows), not a per-row predicate: a TinyFish raw-capture row inside a legacy
    feed group has project_id/user_id/day_ref = NULL (its own metadata never
    carries them — confirmed against real data), while the group's planner/
    writer rows do. Filtering the aggregate means "this group's project_id is X"
    correctly matches even though not every row in it carries that value —
    exactly the "ANY row matches -> return the FULL group" semantics Task 2's
    web_search filter also needs, generalized to every group-level dimension.
    """
    where = []
    params: list = []

    # Same mixed-storage-format normalization as _build_where — started_at is
    # MIN(created_at), so it carries whichever shape that row was written in.
    if date_from:
        where.append("DATE(started_at) >= DATE(?)")
        params.append(date_from)
    if date_to:
        where.append("DATE(started_at) <= DATE(?)")
        params.append(date_to)
    if project_id:
        where.append("project_id = ?")
        params.append(project_id)
    if user_id:
        where.append("user_id = ?")
        params.append(user_id)
    if not include_test_data:
        where.append("is_test = 0")
    if status == "success":
        where.append("all_succeeded = 1")
    elif status == "failed":
        where.append("all_succeeded = 0")
    if action_type in _ACTION_TYPE_SURFACES:
        where.append("surface = ?")
        params.append(action_type)
    elif action_type == "web_search":
        where.append("has_web_search = 1")
    if day_ref is not None:
        where.append("day_ref = ?")
        params.append(day_ref)
    if target_language:
        where.append("target_language = ?")
        params.append(target_language)
    if search:
        # Same "ANY row matches -> whole group" precedent as has_web_search —
        # see _groups_cte's has_search_match aggregate for how this is computed.
        where.append("has_search_match = 1")

    where_clause = f"WHERE {' AND '.join(where)}" if where else ""
    return where_clause, params


GROUP_PAGE_SIZE = 20

# Phase Q — the grouped list's own display-label text, mirrored from
# frontend/src/components/admin/AdminPage.jsx's ACTION_TYPE_LABELS +
# ActionTypeBadge's "Unknown" fallback (there is no way to share one
# definition across Python/JS here — if a label changes on one side, change
# it on both). Sorting the 'Action' column must order by the SAME text the
# badge renders, not the raw surface value ('chat_upload' vs 'feed_v2' would
# alphabetize completely differently from "Chat Upload" vs "Daily Feed (v2)").
_ACTION_LABEL_SQL = """CASE surface
    WHEN 'feed_legacy' THEN 'Daily Feed (Legacy)'
    WHEN 'feed_v2' THEN 'Daily Feed (v2)'
    WHEN 'intelligence_feed' THEN 'Intelligence Feed'
    WHEN 'chat' THEN 'Chat'
    WHEN 'chat_upload' THEN 'Chat Upload'
    WHEN 'explain' THEN 'Explain'
    WHEN 'translate' THEN 'Translate'
    WHEN 'tts' THEN 'Read Aloud'
    ELSE 'Unknown'
END"""

# Phase Q — whitelisted sort keys for /admin/calls/grouped, one per sortable
# column header (Timestamp/User/Action/Latency/Tokens/Status). Column names
# reference `groups`' own output columns (see _groups_cte) or the outer
# query's own user_email alias — never raw llm_call_log columns, since this
# route sorts GROUPS, not rows. 'latency'/'tokens' use the group-level sums
# (op_latency_ms/op_tokens) already displayed for a group row, not any single
# row's own value — same numbers, just made sortable.
GROUP_SORT_COLUMNS = {
    "timestamp": "started_at",
    "user":      "user_email",
    "action":    _ACTION_LABEL_SQL,
    "latency":   "op_latency_ms",
    "tokens":    "op_tokens",
    "status":    "all_succeeded",
}


def _groups_cte(
    date_from: str | None,
    date_to: str | None,
    project_id: str | None,
    user_id: str | None,
    include_test_data: bool,
    status: str | None,
    action_type: str | None,
    day_ref: int | None,
    target_language: str | None,
    search: str | None = None,
) -> tuple[str, list]:
    """The trace_id-grouping CTE shared by list_grouped_calls (Phase B2) and
    get_operation_summary (Phase F) — factored out so the FIRST_VALUE-pick
    logic (B2b/B2c) is fixed in exactly one place instead of drifting between
    two copies. Returns (sql, params); params must be bound first in the
    caller's param list, ahead of _build_group_where's own params (see
    cte_params below).

    Phase N — perf fix. Previously `resolved` read the ENTIRE llm_call_log
    table with no WHERE at all, so every FIRST_VALUE window function (x4)
    and the GROUP BY sorted and scanned the full table before the caller's
    filter ever got applied (that only happened at the very end, against the
    already-fully-materialized `groups`). Real EXPLAIN QUERY PLAN confirmed
    this: `SCAN l` with no search, four nested CO-ROUTINE scans (one full
    pass per FIRST_VALUE column), and the filter WHERE only showing up as
    `SCAN groups` at the end. Measured 5.2-9.0s for a realistic 7-day-range
    /admin/calls/grouped call on the live DB.

    Fix: a `candidates` CTE first narrows to the group_keys that COULD match
    the caller's filter, via a cheap single-pass scan reusing _build_where's
    already-correct, already-tested row-level predicate. `resolved` then
    only pulls in rows whose group_key is a candidate — but ALL of that
    group's rows, not just the ones individually matching the predicate.

    That "all rows, not just matching rows" part is load-bearing: this
    CTE's group-level fields (started_at=MIN(created_at), the FIRST_VALUE
    picks, is_test=MAX(is_test)...) are aggregates over a WHOLE group, and
    filtering rows out of `resolved` directly (instead of via group_key)
    would silently corrupt those aggregates for any group whose rows split
    across the filter boundary — e.g. a trace_id with rows on both sides of
    a date cutoff would get a wrong MIN(created_at) if only the in-range
    rows survived. Candidate narrowing sidesteps this: for every dimension
    _build_group_where checks post-aggregation (date range against
    started_at=MIN(created_at), is_test against MAX(is_test), the
    FIRST_VALUE picks, status against MIN/has_web_search-style aggregates),
    a group can only pass the real filter if AT LEAST ONE of its rows
    individually satisfies the equivalent row-level predicate — so
    _build_where's predicate is a sound superset (false positives only,
    never a false negative) for candidacy. The actual `_build_group_where`
    filter downstream is completely unchanged, so results are provably
    identical to before this change, not just identical on today's data —
    verified byte-for-byte across 15 filter combinations (dates, is_test,
    status, action_type incl. web_search, project_id, user_id, day_ref,
    target_language, and combinations) in Phase N's TESTS.

    Phase B2b: project_id/user_id/day_ref/target_language used to be picked
    via MAX() — "biggest value wins" is meaningless (and wrong, silently)
    whenever two sibling rows carry genuinely different non-NULL values for
    the same field, not just one NULL + one real value. Each is now picked
    from one specific, deterministic row instead: the earliest row (by
    timestamp_start, id as a stable tiebreaker) that has a non-NULL value
    for that field. FIRST_VALUE with this ORDER BY puts non-NULL rows first
    (`col IS NULL` sorts false=0 before true=1), so it naturally skips
    NULL-carrying rows (e.g. TinyFish raw-capture rows) in favor of the
    first row that actually set the field. These are facts about the
    request — "earliest row" is the right pick.

    Phase B2c: is_test is NOT one of those — it's a classification, and the
    safe direction is "if ANY row in the group is test traffic, the whole
    group is test traffic" (so it's hidden under include_test_data=False),
    not whichever row happened to log first. Stays MAX(is_test), untouched
    by B2b's fix.

    Phase F: groups also carries op_latency_ms = SUM(latency_ms) across the
    group's own rows — "per-operation latency" as get_operation_summary needs
    it.

    Phase H: op_tokens = SUM(total_tokens) is the same pattern for tokens, so
    the grouped list can show a group's summed tokens beside its summed
    latency. Bare SUM (not COALESCE(...,0)) mirrors op_latency_ms exactly:
    total_tokens is genuinely NULL on failed/untracked rows, so a group with
    no token data returns NULL and renders as "—" rather than a fake 0.

    Phase K: the target_language pick now reads resolved_target_language
    (see _TARGET_LANGUAGE_EXPR) instead of the raw column — two real rows
    have l.target_language = NULL despite being real, successful Hindi
    translate calls (write-path bug, since fixed; see _TARGET_LANGUAGE_EXPR's
    comment). Without this, those rows' singleton groups would carry the
    recovery fix nowhere, and the grouped list (the actual UI's primary
    view) would keep failing to filter them by language even after the flat
    /admin/calls route was fixed.

    Phase R: has_search_match is the same "ANY row matches -> whole group"
    aggregate pattern as has_web_search, its own LIKE CASE over `picked`
    (the fully-resolved, un-filtered rows of every candidate group) rather
    than reusing candidates' own predicate — candidate_where only decides
    which group_keys make it into `resolved`, it isn't itself a selectable
    per-group column downstream. Real timing on the live DB (6,453 rows,
    avg input/output ~1.9KB/2.6KB): full grouped query with search active,
    115-149ms warm (Phase R precondition check) — no FTS5 needed.
    """
    ws_placeholders = ",".join("?" * len(_WEB_SEARCH_CALL_TYPES))
    candidate_where, candidate_params = _build_where(
        date_from, date_to, None, project_id, user_id, include_test_data,
        status, action_type, day_ref, target_language, search,
    )
    if search:
        search_case = "MAX(CASE WHEN input LIKE ? OR output LIKE ? THEN 1 ELSE 0 END)"
        search_case_params = [f"%{search}%", f"%{search}%"]
    else:
        search_case = "0"
        search_case_params = []
    sql = f"""
        WITH candidates AS (
            SELECT DISTINCT COALESCE(l.trace_id, 'row-' || l.id) AS group_key
            {_FROM_JOIN}
            {candidate_where}
        ),
        resolved AS (
            SELECT l.*, COALESCE(l.user_id, lp.user_id) AS resolved_user_id,
                   COALESCE(l.trace_id, 'row-' || l.id) AS group_key,
                   {_TARGET_LANGUAGE_EXPR} AS resolved_target_language
            {_FROM_JOIN}
            WHERE COALESCE(l.trace_id, 'row-' || l.id) IN (SELECT group_key FROM candidates)
        ),
        picked AS (
            SELECT *,
                FIRST_VALUE(project_id) OVER (
                    PARTITION BY group_key
                    ORDER BY (project_id IS NULL), timestamp_start ASC, id ASC
                ) AS picked_project_id,
                FIRST_VALUE(resolved_user_id) OVER (
                    PARTITION BY group_key
                    ORDER BY (resolved_user_id IS NULL), timestamp_start ASC, id ASC
                ) AS picked_user_id,
                FIRST_VALUE(day_ref) OVER (
                    PARTITION BY group_key
                    ORDER BY (day_ref IS NULL), timestamp_start ASC, id ASC
                ) AS picked_day_ref,
                FIRST_VALUE(resolved_target_language) OVER (
                    PARTITION BY group_key
                    ORDER BY (resolved_target_language IS NULL), timestamp_start ASC, id ASC
                ) AS picked_target_language
            FROM resolved
        ),
        groups AS (
            SELECT
                group_key,
                MAX(trace_id)               AS trace_id,
                MAX(surface)                AS surface,
                MIN(created_at)             AS started_at,
                MAX(created_at)             AS ended_at,
                COUNT(*)                    AS row_count,
                MIN(success)                AS all_succeeded,
                MAX(CASE WHEN call_type IN ({ws_placeholders}) THEN 1 ELSE 0 END) AS has_web_search,
                {search_case}                AS has_search_match,
                MAX(is_test)                AS is_test,
                MAX(picked_project_id)      AS project_id,
                MAX(picked_user_id)         AS user_id,
                MAX(picked_day_ref)         AS day_ref,
                MAX(picked_target_language) AS target_language,
                SUM(latency_ms)             AS op_latency_ms,
                SUM(total_tokens)           AS op_tokens
            FROM picked
            GROUP BY group_key
        )
    """
    return sql, [*candidate_params, *_WEB_SEARCH_CALL_TYPES, *search_case_params]


def list_grouped_calls(
    date_from: str | None,
    date_to: str | None,
    project_id: str | None,
    user_id: str | None,
    include_test_data: bool,
    status: str | None,
    action_type: str | None,
    day_ref: int | None,
    target_language: str | None,
    limit: int,
    offset: int,
    sort_by: str = "timestamp",
    sort_order: str = "desc",
    search: str | None = None,
) -> tuple[int, list[dict]]:
    """Groups llm_call_log rows by trace_id (one page = `limit` GROUPS, not rows).
    A NULL trace_id (any pre-Phase-3 historical row) becomes its own singleton
    group, keyed by COALESCE(trace_id, 'row-' || id) so it sorts and paginates
    alongside real multi-row groups in one result set.

    Phase Q: sort_by/sort_order added — previously hardcoded ORDER BY
    started_at DESC. sort_by is validated by the caller (routes/admin.py)
    against GROUP_SORT_COLUMNS before reaching here, same allowlist shape as
    the flat list_call_logs/SORT_COLUMNS precedent. 'action' sorts by
    _ACTION_LABEL_SQL (the resolved display label), not the raw surface
    column — see that constant's docstring.

    Phase R: search is additive, ANDed with every other active filter — see
    _groups_cte's has_search_match aggregate and _build_group_where."""
    cte, cte_params = _groups_cte(
        date_from, date_to, project_id, user_id, include_test_data,
        status, action_type, day_ref, target_language, search=search,
    )
    where_clause, where_params = _build_group_where(
        date_from, date_to, project_id, user_id, include_test_data,
        status, action_type, day_ref, target_language, search=search,
    )
    order_expr = GROUP_SORT_COLUMNS[sort_by]
    direction = "ASC" if sort_order == "asc" else "DESC"

    with get_connection() as conn:
        total = conn.execute(
            f"{cte} SELECT COUNT(*) FROM groups {where_clause}",
            [*cte_params, *where_params],
        ).fetchone()[0]

        # Group-level email: a scalar subquery against the CTE's already-picked
        # user_id, same reasoning as _ROW_COLUMNS — never touches this query's
        # own FROM (still just `groups`), so `where_clause`'s bare `user_id = ?`
        # stays unambiguous (a real JOIN against `users` here would collide:
        # users.user_id vs. groups.user_id). user_email is computed here (not
        # in the CTE), so the 'user' sort key can only be applied at this
        # outer ORDER BY, referencing this SELECT's own alias — real SQLite
        # behavior, not a hack (confirmed against the live query below).
        group_rows = conn.execute(
            f"""
            {cte}
            SELECT *, (SELECT email FROM users u WHERE u.user_id = groups.user_id) AS user_email
            FROM groups
            {where_clause}
            ORDER BY {order_expr} {direction}
            LIMIT ? OFFSET ?
            """,
            [*cte_params, *where_params, limit, offset],
        ).fetchall()

        groups = [dict(r) for r in group_rows]

        group_keys = [g["group_key"] for g in groups]
        member_rows: dict[str, list[dict]] = {k: [] for k in group_keys}
        if group_keys:
            key_placeholders = ",".join("?" * len(group_keys))
            rows = conn.execute(
                f"""
                SELECT {_ROW_COLUMNS}, COALESCE(l.trace_id, 'row-' || l.id) AS group_key
                {_FROM_JOIN}
                WHERE COALESCE(l.trace_id, 'row-' || l.id) IN ({key_placeholders})
                ORDER BY l.timestamp_start ASC
                """,
                group_keys,
            ).fetchall()
            for r in rows:
                d = _row_to_dict(r)
                gk = d.pop("group_key")
                member_rows[gk].append(d)

    result = [
        {
            "trace_id": g["trace_id"],
            "surface": g["surface"],
            "action_type": g["surface"],
            "started_at": g["started_at"],
            "ended_at": g["ended_at"],
            "row_count": g["row_count"],
            "all_succeeded": bool(g["all_succeeded"]),
            "has_web_search": bool(g["has_web_search"]),
            "user_email": g["user_email"],
            # Phase H: both were already computed in the shared groups CTE but
            # never selected out here, so the grouped list had no group-level
            # latency or token figure to render.
            "op_latency_ms": g["op_latency_ms"],
            "op_tokens": g["op_tokens"],
            "rows": member_rows[g["group_key"]],
        }
        for g in groups
    ]
    return total, result


# Phase I — bulk export ceiling. The real full-DB export today is 5,733 groups
# / 5,853 rows / 16.3 MB of input+output, served as ONE query in ~1.8s, so the
# cap is not currently reached. It exists so that stays safe as the table
# grows: past it the caller is told `truncated=True` and the real total, and
# the UI says so out loud — rather than silently dropping data or trying to
# materialize an unbounded result set.
#
# Paginating the normal /calls/grouped route instead is not viable: it caps at
# 100 groups, so a full export would be 58 round-trips (~182s measured) versus
# 1.8s here.
EXPORT_MAX_GROUPS = 20_000


def export_grouped_calls(
    date_from: str | None,
    date_to: str | None,
    project_id: str | None,
    user_id: str | None,
    include_test_data: bool,
    status: str | None,
    action_type: str | None,
    day_ref: int | None,
    target_language: str | None,
    search: str | None = None,
) -> tuple[int, bool, list[dict]]:
    """The COMPLETE filtered group set for a bulk download — every group the
    same filters would page through, in one call.

    Deliberately a thin wrapper over list_grouped_calls rather than its own
    query: filtering, grouping and ordering stay defined in exactly one place,
    so an export can never disagree with the list it was exported from.

    Returns (total_matching, truncated, groups).
    """
    total, groups = list_grouped_calls(
        date_from, date_to, project_id, user_id, include_test_data,
        status, action_type, day_ref, target_language,
        limit=EXPORT_MAX_GROUPS, offset=0, search=search,
    )
    return total, total > len(groups), groups


def get_operation_summary(
    date_from: str | None,
    date_to: str | None,
    project_id: str | None,
    user_id: str | None,
    include_test_data: bool,
    status: str | None,
    action_type: str | None,
    day_ref: int | None,
    target_language: str | None,
    search: str | None = None,
) -> dict:
    """Phase F — the group-level (trace_id/operation) counterpart to
    get_call_summary's row-level totals. get_call_summary has never computed
    anything at the group level; "total operations" and operation-level
    success rate (all_succeeded, not per-row success) didn't exist as numbers
    anywhere before this. Reuses list_grouped_calls's own CTE/filter functions
    so "total operations" always matches what /admin/calls/grouped would
    actually return for the same filters — verified in Phase F's TESTS.
    """
    where_clause, where_params = _build_group_where(
        date_from, date_to, project_id, user_id, include_test_data,
        status, action_type, day_ref, target_language, search=search,
    )
    cte, cte_params = _groups_cte(
        date_from, date_to, project_id, user_id, include_test_data,
        status, action_type, day_ref, target_language, search=search,
    )

    with get_connection() as conn:
        row = conn.execute(
            f"""
            {cte}
            SELECT
                COUNT(*)                              AS total_operations,
                COALESCE(SUM(all_succeeded), 0)       AS succeeded_operations,
                COALESCE(AVG(op_latency_ms), 0.0)     AS avg_latency_per_operation_ms
            FROM groups
            {where_clause}
            """,
            [*cte_params, *where_params],
        ).fetchone()

    total_operations = row["total_operations"]
    succeeded_operations = row["succeeded_operations"]
    return {
        "total_operations": total_operations,
        "succeeded_operations": succeeded_operations,
        "failed_operations": total_operations - succeeded_operations,
        "operation_success_rate": (succeeded_operations / total_operations) if total_operations else 0.0,
        "avg_latency_per_operation_ms": row["avg_latency_per_operation_ms"],
    }


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


def get_call_summary(
    date_from: str | None,
    date_to: str | None,
    include_test_data: bool,
    call_type: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    status: str | None = None,
    action_type: str | None = None,
    day_ref: int | None = None,
    target_language: str | None = None,
    search: str | None = None,
) -> dict:
    # Phase B1: parity fix — call_type/project_id/user_id used to be hardcoded
    # to None here (summary tiles ignored them regardless of what the caller
    # passed) while list_call_logs()/get_daily_volume() already honored them.
    # Phase B2: status/action_type added as the same pattern; route wiring
    # for all of these now happens in this phase too.
    # Phase F: day_ref/target_language added — _build_where already supported
    # both (B2), but get_call_summary never passed them through, so selecting
    # a Day or Target Language sub-filter narrowed the grouped list while the
    # row-level tiles beside it silently kept showing the unfiltered totals.
    # Phase R: search added, same pattern.
    where_clause, params = _build_where(
        date_from, date_to, call_type, project_id, user_id, include_test_data,
        status, action_type, day_ref, target_language, search,
    )

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

        # Phase F: real surface/action-type breakdown for the Row 3 chart.
        by_surface = conn.execute(
            f"""
            SELECT l.surface AS surface, COUNT(*) AS count
            {_FROM_JOIN}
            {where_clause}
            GROUP BY l.surface
            ORDER BY count DESC
            """,
            params,
        ).fetchall()

        # Phase F — real substitute for a "fallback rate" tile (see report):
        # model_requested != model_used on a single row is NOT a clean
        # fallback signal (99.5% of real mismatches are Gemini's "latest"
        # alias resolving to a pinned version string, not a provider
        # fallback). error_type on failed rows is real, already captured,
        # and honest about what's actually happening instead.
        error_where = f"{where_clause} AND l.success = 0 AND l.error_type IS NOT NULL" \
            if where_clause else "WHERE l.success = 0 AND l.error_type IS NOT NULL"
        by_error_type = conn.execute(
            f"""
            SELECT l.error_type AS error_type, COUNT(*) AS count
            {_FROM_JOIN}
            {error_where}
            GROUP BY l.error_type
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
        "by_surface": [dict(r) for r in by_surface],
        "by_error_type": [dict(r) for r in by_error_type],
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
