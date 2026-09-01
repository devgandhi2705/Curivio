/**
 * Admin → Backups. Pick a snapshot, preview what it would put back, restore it
 * whole or for one user, and work the queue of users who reported missing data.
 *
 * The preview step is not optional decoration: a restore is merge-only and so
 * cannot destroy anything, but it CAN be a no-op for reasons that are invisible
 * without looking (already restored, or the snapshot predates the data the user
 * is missing). Showing the row counts first is what stops "I clicked restore and
 * nothing happened".
 */

import { useState, useEffect, useCallback } from "react"
import {
  listBackups, createBackup, usersInBackup, previewRestore, runRestore,
  listDataLossRequests, resolveDataLossRequest,
} from "../../api/backups.js"

const CARD = "bg-slate-900/40 border border-slate-800/60 rounded-2xl"
const BTN = "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium bg-slate-800/60 border border-slate-700/50 text-slate-300 hover:text-slate-100 hover:border-slate-600 transition-colors"
const BTN_PRIMARY = "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium bg-blue-600 hover:bg-blue-500 text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
const LABEL = "text-[10px] font-semibold uppercase tracking-widest text-slate-600"

function formatBytes(n) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function formatWhen(mtimeSeconds) {
  const d = new Date(mtimeSeconds * 1000)
  return d.toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  })
}

// ── snapshot list ────────────────────────────────────────────────────────────

const KIND_BADGE = {
  quarantined: { label: "quarantined", cls: "bg-amber-500/15 text-amber-400" },
  remote:      { label: "remote", cls: "bg-sky-500/15 text-sky-400" },
  snapshot:    { label: "snapshot", cls: "bg-slate-700/40 text-slate-400" },
}

function SnapshotRow({ backup, selected, onSelect }) {
  const badge = KIND_BADGE[backup.kind] ?? KIND_BADGE.snapshot
  return (
    <button
      onClick={() => onSelect(backup.filename)}
      className={`w-full text-left px-3 py-2.5 rounded-xl border transition-colors ${
        selected
          ? "bg-blue-600/10 border-blue-600/40"
          : "bg-slate-900/40 border-slate-800/60 hover:border-slate-700"
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-[12px] text-slate-200 truncate">{formatWhen(backup.mtime)}</span>
        <span className="text-[10px] text-slate-500 flex-shrink-0">{formatBytes(backup.size_bytes)}</span>
      </div>
      <div className="flex items-center gap-1.5 mt-1">
        <span className={`text-[9px] px-1.5 py-0.5 rounded font-medium uppercase tracking-wide ${badge.cls}`}>
          {badge.label}
        </span>
        <span className="text-[10px] text-slate-600 truncate">{backup.filename}</span>
        {backup.kind === "remote" && (
          <span className="text-[10px] text-slate-600 flex-shrink-0">— restoring downloads this first</span>
        )}
      </div>
    </button>
  )
}

// ── preview result table ─────────────────────────────────────────────────────

function PreviewTable({ result }) {
  // Only tables that would actually contribute something are worth showing —
  // the schema has ~60 tables and listing every empty one buries the signal.
  const rows = Object.entries(result.tables)
    .filter(([, r]) => (r.in_snapshot || 0) > 0 || (r.rows_inserted || 0) > 0)
    .sort((a, b) => (b[1].in_snapshot || b[1].rows_inserted || 0) - (a[1].in_snapshot || a[1].rows_inserted || 0))

  const unattributed = Object.entries(result.tables)
    .filter(([, r]) => (r.unattributed_in_snapshot || 0) > 0)

  if (rows.length === 0) {
    return (
      <p className="text-[12px] text-slate-500 py-3">
        Nothing to restore from this file for this scope
        {result.scope !== "*" && " — this snapshot has no rows attributed to that user"}.
      </p>
    )
  }

  return (
    <div className="space-y-3">
      <div className="overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="text-left border-b border-slate-800">
              <th className="py-1.5 pr-3 font-medium text-slate-500">Table</th>
              <th className="py-1.5 pr-3 font-medium text-slate-500 text-right">
                {result.dry_run ? "In snapshot" : "Restored"}
              </th>
              {result.dry_run && (
                <th className="py-1.5 font-medium text-slate-500 text-right">Already live</th>
              )}
            </tr>
          </thead>
          <tbody>
            {rows.map(([name, r]) => (
              <tr key={name} className="border-b border-slate-900">
                <td className="py-1.5 pr-3 text-slate-300 font-mono text-[11px]">{name}</td>
                <td className="py-1.5 pr-3 text-right text-slate-200 tabular-nums">
                  {(result.dry_run ? r.in_snapshot : r.rows_inserted)?.toLocaleString() ?? "—"}
                </td>
                {result.dry_run && (
                  <td className="py-1.5 text-right text-slate-500 tabular-nums">
                    {r.in_live_db?.toLocaleString() ?? "—"}
                    {r.already_restored && (
                      <span className="ml-1.5 text-[9px] text-emerald-500">restored</span>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Rows nobody can claim. Surfaced because a per-user restore silently
          skipping them looks identical to there being nothing to restore. */}
      {result.scope !== "*" && unattributed.length > 0 && (
        <div className="text-[11px] text-amber-400/90 bg-amber-500/5 border border-amber-500/20 rounded-lg px-3 py-2">
          This snapshot also holds rows with no owner recorded
          ({unattributed.map(([n, r]) => `${n}: ${r.unattributed_in_snapshot}`).join(", ")}).
          They predate the migration that added user attribution, so a per-user restore
          cannot find them — only a full restore will bring them back.
        </div>
      )}

      {result.integrity_ok === false && (
        <div className="text-[11px] text-amber-400/90 bg-amber-500/5 border border-amber-500/20 rounded-lg px-3 py-2">
          This file failed an integrity check, so some tables may be unreadable. Everything
          listed above is still recoverable — tables that failed are reported individually.
        </div>
      )}
    </div>
  )
}

// ── data-loss request queue ──────────────────────────────────────────────────

function DataLossQueue({ onRestoreUser }) {
  const [requests, setRequests] = useState([])
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    listDataLossRequests()
      .then(d => setRequests(d.requests))
      .catch(() => setRequests([]))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  async function setStatus(requestId, status) {
    setBusyId(requestId)
    try {
      await resolveDataLossRequest(requestId, status)
      load()
    } finally {
      setBusyId(null)
    }
  }

  if (loading) return <p className="text-[12px] text-slate-600">Loading requests…</p>
  if (requests.length === 0) {
    return <p className="text-[12px] text-slate-600">No data-loss reports.</p>
  }

  return (
    <div className="space-y-2">
      {requests.map(r => (
        <div key={r.request_id} className="px-3 py-2.5 rounded-xl bg-slate-900/40 border border-slate-800/60">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-[12px] text-slate-200 truncate">
                {r.user_email || r.user_id}
                <span className={`ml-2 text-[9px] px-1.5 py-0.5 rounded uppercase tracking-wide ${
                  r.status === "open" ? "bg-amber-500/15 text-amber-400"
                    : r.status === "resolved" ? "bg-emerald-500/15 text-emerald-400"
                    : "bg-slate-700/40 text-slate-500"
                }`}>{r.status}</span>
              </p>
              {r.description && (
                <p className="text-[11px] text-slate-500 mt-1 whitespace-pre-wrap break-words">{r.description}</p>
              )}
              <p className="text-[10px] text-slate-600 mt-1">{r.created_at}</p>
            </div>
            {r.status === "open" && (
              <div className="flex flex-col gap-1.5 flex-shrink-0">
                <button className={BTN} onClick={() => onRestoreUser(r.user_id, r.user_email)}>
                  Restore this user
                </button>
                <div className="flex gap-1.5">
                  <button className={BTN} disabled={busyId === r.request_id}
                    onClick={() => setStatus(r.request_id, "resolved")}>Resolve</button>
                  <button className={BTN} disabled={busyId === r.request_id}
                    onClick={() => setStatus(r.request_id, "rejected")}>Reject</button>
                </div>
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

// ── main panel ───────────────────────────────────────────────────────────────

export default function BackupsPanel() {
  const [backups, setBackups] = useState([])
  const [retention, setRetention] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const [selected, setSelected] = useState(null)
  const [snapshotUsers, setSnapshotUsers] = useState([])
  const [scope, setScope] = useState("*")           // "*" or a user_id

  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(null)            // "snapshot" | "preview" | "restore"
  const [note, setNote] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    listBackups()
      .then(d => { setBackups(d.backups); setRetention(d.retention); setError(null) })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  // Reset the preview whenever the source or scope changes — a stale result
  // shown next to a different selection is worse than no result.
  useEffect(() => {
    setResult(null)
    setNote(null)
  }, [selected, scope])

  useEffect(() => {
    if (!selected) { setSnapshotUsers([]); return }
    setScope("*")
    usersInBackup(selected)
      .then(d => setSnapshotUsers(d.users))
      .catch(() => setSnapshotUsers([]))
  }, [selected])

  async function handleSnapshot() {
    setBusy("snapshot"); setNote(null)
    try {
      const r = await createBackup()
      const remoteNote = r.remote_ok === false
        ? ` Off-volume copy failed: ${r.remote_error}`
        : r.remote_ok === true ? " Also pushed off-volume." : ""
      setNote(`Snapshot taken: ${r.filename} (${formatBytes(r.size_bytes)}).${remoteNote}`)
      load()
    } catch (e) {
      setNote(`Snapshot failed: ${e.message}`)
    } finally {
      setBusy(null)
    }
  }

  async function handlePreview() {
    setBusy("preview"); setNote(null)
    try {
      setResult(await previewRestore(selected, scope === "*" ? null : scope))
    } catch (e) {
      setNote(`Preview failed: ${e.message}`)
    } finally {
      setBusy(null)
    }
  }

  async function handleRestore() {
    setBusy("restore"); setNote(null)
    try {
      const r = await runRestore(selected, scope === "*" ? null : scope)
      setResult(r)
      setNote(r.rows_restored > 0
        ? `Restored ${r.rows_restored.toLocaleString()} rows.`
        : "Nothing new to restore — everything in this file for this scope is already live.")
      load()
    } catch (e) {
      setNote(`Restore failed: ${e.message}`)
    } finally {
      setBusy(null)
    }
  }

  // Restoring a user from the request queue: jump to the newest snapshot that
  // actually contains them rather than making the admin hunt for one.
  async function handleRestoreUserFromRequest(userId, email) {
    for (const b of backups) {
      try {
        const { users } = await usersInBackup(b.filename)
        if (users.some(u => u.user_id === userId)) {
          setSelected(b.filename)
          setSnapshotUsers(users)
          setScope(userId)
          setNote(`Selected ${b.filename} — the newest backup containing ${email || userId}. Preview before restoring.`)
          return
        }
      } catch { /* unreadable file — keep looking */ }
    }
    setNote(`No backup contains ${email || userId}.`)
  }

  const scopeLabel = scope === "*"
    ? "everything"
    : (snapshotUsers.find(u => u.user_id === scope)?.email || scope)

  return (
    <div className="space-y-5">
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-100 tracking-tight">Backups</h1>
          <p className="text-sm text-slate-500 mt-1">
            Automatic snapshots, and restoring data back into the live database
          </p>
        </div>
        <button className={BTN_PRIMARY} onClick={handleSnapshot} disabled={busy === "snapshot"}>
          {busy === "snapshot" ? "Taking snapshot…" : "Take snapshot now"}
        </button>
      </div>

      {retention && (
        <p className="text-[11px] text-slate-600">
          Automatic snapshot every {Math.round(retention.interval_seconds / 3600)}h and on every
          deploy before migrations run. Keeping the {retention.local_max_snapshots} most recent
          locally, {retention.remote_max_snapshots} off-volume.
          Restores only ever add rows back — they never overwrite or delete existing data.
        </p>
      )}

      {note && (
        <div className="text-[12px] text-slate-300 bg-slate-800/40 border border-slate-700/50 rounded-lg px-3 py-2">
          {note}
        </div>
      )}

      <div className="flex flex-col lg:flex-row gap-5 items-start">
        <div className="w-full lg:w-72 flex-shrink-0 space-y-2">
          <p className={LABEL}>Available backups</p>
          {loading && <p className="text-[12px] text-slate-600">Loading…</p>}
          {error && <p className="text-[12px] text-rose-400">{error}</p>}
          {!loading && !error && backups.length === 0 && (
            <p className="text-[12px] text-slate-600">
              No backups yet. The first automatic snapshot is taken on the next deploy.
            </p>
          )}
          {backups.map(b => (
            <SnapshotRow key={b.filename} backup={b} selected={selected === b.filename}
              onSelect={setSelected} />
          ))}
        </div>

        <div className="flex-1 min-w-0 space-y-4">
          {!selected ? (
            <div className={`${CARD} px-4 py-6`}>
              <p className="text-[12px] text-slate-500">Select a backup to preview or restore it.</p>
            </div>
          ) : (
            <>
              <div className={`${CARD} px-4 py-4 space-y-3`}>
                <div>
                  <p className={LABEL}>Restore scope</p>
                  <select
                    value={scope}
                    onChange={e => setScope(e.target.value)}
                    className="mt-1.5 w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-[12px] text-slate-200 focus:outline-none focus:border-blue-500"
                  >
                    <option value="*">Everything in this backup</option>
                    {snapshotUsers.map(u => (
                      <option key={u.user_id} value={u.user_id}>{u.email || u.user_id}</option>
                    ))}
                  </select>
                  {snapshotUsers.length === 0 && (
                    <p className="text-[11px] text-slate-600 mt-1.5">
                      Could not read the account list from this file — a full restore still works.
                    </p>
                  )}
                </div>

                <div className="flex items-center gap-2 flex-wrap">
                  <button className={BTN} onClick={handlePreview} disabled={busy !== null}>
                    {busy === "preview" ? "Checking…" : "Preview"}
                  </button>
                  <button className={BTN_PRIMARY} onClick={handleRestore} disabled={busy !== null}>
                    {busy === "restore" ? "Restoring…" : `Restore ${scopeLabel}`}
                  </button>
                </div>
              </div>

              {result && (
                <div className={`${CARD} px-4 py-4`}>
                  <p className={LABEL}>
                    {result.dry_run ? "Preview — nothing written" : "Restore complete"}
                  </p>
                  <div className="mt-2.5">
                    <PreviewTable result={result} />
                  </div>
                </div>
              )}
            </>
          )}

          <div className={`${CARD} px-4 py-4`}>
            <p className={`${LABEL} mb-2.5`}>Data-loss reports</p>
            <DataLossQueue onRestoreUser={handleRestoreUserFromRequest} />
          </div>
        </div>
      </div>
    </div>
  )
}
