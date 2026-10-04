# Admin log stars — design

Approved in chat 2026-10-03 ("all features are good to go").

## Goal

An admin can star any operation group or any single call in the admin call log, so it
can be found again later when working on improvements, and can filter the log down to
starred items. Nothing about the existing log, its filters, sorting, paging, summaries
or export changes when the filter is off.

## Data

New table, created with the others in `backend/database/schema.py` (`CREATE TABLE IF
NOT EXISTS`, so existing databases gain it on boot; `llm_call_log` is untouched):

```sql
CREATE TABLE IF NOT EXISTS admin_log_stars (
    target_kind TEXT NOT NULL CHECK (target_kind IN ('group', 'row')),
    target_key  TEXT NOT NULL,
    starred_by  TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (target_kind, target_key)
)
```

- `group` key = the grouped list's own key, `COALESCE(trace_id, 'row-' || id)` — the
  same key the frontend already derives (`trace_id ?? 'row-' + rows[0].id`).
- `row` key = `llm_call_log.id` as text.
- Stars are shared by every admin; `starred_by` (admin user_id) is kept for reference.
- A single-call group is starred as a group (one star per visible line).

## API (admin router — already admin-only)

- `PUT /admin/stars` body `{kind: "group"|"row", key}` → 204. Idempotent.
- `DELETE /admin/stars?kind=…&key=…` → 204. Idempotent.
- Validation: kind must be `group`/`row`; key 1–200 chars; a `row` key must be digits.
- Every row in `/admin/calls`, `/admin/calls/grouped` and `/admin/calls/export` gains
  `starred: bool` (the row's own star); every group gains `starred: bool` (the group's
  own star).
- New optional query param `starred=true` on `/calls`, `/calls/grouped`,
  `/calls/export`, `/calls/volume`, `/summary`, `/operations/summary`.

## Filter semantics

`starred=true` keeps every group that is starred **or** contains a starred row, and
shows the whole group — the same "surface the whole group" rule search already uses.
It is ONE condition added in `admin_service._build_where`, which every list, count,
summary, volume and export query already shares, so they all agree with each other and
AND with every existing filter:

```sql
COALESCE(l.trace_id, 'row-' || l.id) IN (
  SELECT target_key FROM admin_log_stars WHERE target_kind = 'group'
  UNION
  SELECT COALESCE(s_l.trace_id, 'row-' || s_l.id)
    FROM admin_log_stars s
    JOIN llm_call_log s_l ON s.target_kind = 'row' AND s_l.id = CAST(s.target_key AS INTEGER)
)
```

## UI (AdminPage)

- A ☆/★ button in its own leading column on every group header, single-call row and
  nested call row — desktop grid and mobile cards. Rows stay whole-row buttons; the star
  sits beside them (a button can't nest inside a button), and the column header gets a
  matching spacer so columns stay aligned.
- Clicking stars/unstars immediately (optimistic), with a small stamp animation;
  on failure the star reverts and a short error shows. It never expands a group or
  opens the detail panel.
- A "★ Starred only" toggle in the filter rail beside "Include test data"; it counts as
  an active filter and is sent to the list, summary, volume and bulk export.

## Tests

- Backend (`tests/test_admin_stars.py`, in-memory DB like `test_admin_grouped_sort`):
  star/unstar idempotent; flags on groups and rows; filter with a group star, with a row
  star (whole group surfaces), with a single-call group, combined with another filter,
  page total, summary and export; route validation and non-admin refusal.
- UI harness (admin endpoints stubbed): star a group (PUT body + filled star), the
  Starred toggle sends `starred=true`, a failed save reverts the star.
