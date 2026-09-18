"""
Phase 12c — the SqliteSaver WAL lock.

Root cause: langgraph's SqliteSaver.setup() runs `PRAGMA journal_mode=WAL` on the SHARED
curivio.db, and graph._saver() opened a new connection per call and never closed it.
While any connection is open in WAL mode, every other connection's per-connect
`PRAGMA journal_mode=DELETE` (feed_v2's AND the legacy app's get_connection) fails
INSTANTLY with 'database is locked' — the WAL->DELETE switch needs exclusive access and
does not use the busy handler, so busy_timeout can't help. And a get_connection that
failed its pragma leaked its own (WAL-attached) connection, keeping the lock alive
until the cycle collector ran.

Proves: the file never leaves DELETE mode; the saver's connection is closed after a run
(direct AND stream); get_connection doesn't leak on a failed pragma; concurrent runs
alongside legacy app traffic finish with zero lock errors.
"""
import gc
import json
import sqlite3
import threading

import pytest

from backend.utils import db as legacy_db
from backend.services.feed_v2 import db as v2db
from backend.services.feed_v2 import projects as P
from backend.services.feed_v2 import graph as G

from tests.test_feed_v2_graph import _build_db


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "ckpt.db")
    _build_db(path)
    monkeypatch.setattr(v2db, "DB_PATH", path)
    monkeypatch.setattr(legacy_db, "DB_PATH", path)
    return path


@pytest.fixture(autouse=True)
def _rig():
    G._reset_rig()
    G.USE_REAL_SOURCE_RANKER = False
    yield
    G._reset_rig()


def _mode(path) -> str:
    c = sqlite3.connect(path)
    try:
        return c.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        c.close()


def _can_switch_to_delete(path) -> bool:
    """Only succeeds when NO connection holds the file in WAL — the exact operation
    every get_connection performs."""
    c = sqlite3.connect(path)
    try:
        c.execute("PRAGMA journal_mode=DELETE")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        c.close()


def _ready_project(name="Subject"):
    pid = P.create_project("u1", name, "learn it", "intermediate")["project_id"]
    with v2db.get_connection() as c:
        c.execute("UPDATE v2_projects SET coverage_mode='open', profile_status='ready' WHERE project_id=?", (pid,))
    return pid


def test_saver_setup_keeps_db_in_delete_mode(db):
    with G._saver() as saver:
        saver.setup()                              # the call that used to flip the file to WAL
        assert _mode(db) == "delete"
        assert _can_switch_to_delete(db)           # other connections are not locked out
    assert _mode(db) == "delete"


def test_run_graph_leaves_no_open_connection(db):
    gc.disable()                                   # a leak must not be hidden by the cycle collector
    try:
        G.run_graph("u1", _ready_project(), 1)
        assert _mode(db) == "delete"
        assert _can_switch_to_delete(db)
        with legacy_db.get_connection() as c:      # the rest of the app still works
            assert c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    finally:
        gc.enable()


def test_stream_path_leaves_no_open_connection(db):
    gc.disable()
    try:
        lines = [json.loads(x) for x in G.start_feed_stream("u1", _ready_project(), 1)]
        assert lines[-1]["t"] == "done"
        assert _can_switch_to_delete(db)
    finally:
        gc.enable()


@pytest.mark.parametrize("get_connection", [v2db.get_connection, legacy_db.get_connection],
                         ids=["feed_v2", "legacy"])
def test_get_connection_closes_its_connection_when_setup_fails(db, get_connection):
    """Hold the file in WAL from outside, so get_connection's pragma fails. Once that
    outside connection closes, the NEXT get_connection must work without a gc pass —
    i.e. the failed attempt didn't leak a WAL-attached connection of its own."""
    gc.disable()
    try:
        holder = sqlite3.connect(db)
        holder.execute("PRAGMA journal_mode=WAL")
        holder.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()   # attach to the WAL, like setup()'s DDL
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            with get_connection():
                pass
        holder.close()
        with get_connection() as c:
            assert c.execute("SELECT 1").fetchone()[0] == 1
    finally:
        gc.enable()


def test_concurrent_runs_and_app_traffic_no_lock_errors(db, capsys):
    """HF serves several users at once: 3 direct runs + 2 streamed runs on different
    projects, overlapping (each node sleeps), while a legacy-app thread keeps reading and
    writing the same file. Zero lock errors, file stays DELETE and intact."""
    G.STUB_SLEEP_SECONDS = 0.05
    pids = [_ready_project(f"S{i}") for i in range(5)]
    errors: list[str] = []
    done: list[str] = []
    stop = threading.Event()

    def direct(pid):
        try:
            G.run_graph("u1", pid, 1)
            done.append("direct")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"direct {type(exc).__name__}: {exc}")

    def streamed(pid):
        try:
            events = [json.loads(x) for x in G.start_feed_stream("u1", pid, 1)]
            if events[-1]["t"] != "done":
                errors.append(f"stream ended {events[-1]}")
            else:
                done.append("stream")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"stream {type(exc).__name__}: {exc}")

    app_ops = [0]

    def app_traffic():
        while not stop.is_set():
            try:
                with legacy_db.get_connection() as c:
                    c.execute("UPDATE users SET name = name WHERE user_id = 'u1'")
                    c.execute("SELECT COUNT(*) FROM users").fetchone()
                app_ops[0] += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"app {type(exc).__name__}: {exc}")

    traffic = threading.Thread(target=app_traffic)
    traffic.start()
    runs = ([threading.Thread(target=direct, args=(p,)) for p in pids[:3]]
            + [threading.Thread(target=streamed, args=(p,)) for p in pids[3:]])
    for t in runs:
        t.start()
    for t in runs:
        t.join()
    stop.set()
    traffic.join()

    with v2db.get_connection() as c:
        statuses = [r[0] for r in c.execute("SELECT status FROM mas_runs")]
        integrity = c.execute("PRAGMA quick_check").fetchone()[0]
    with capsys.disabled():
        print(f"\nruns done={sorted(done)} app_ops={app_ops[0]} errors={errors}"
              f"\nmas_runs statuses={statuses} journal_mode={_mode(db)} quick_check={integrity}")
    assert errors == []
    assert sorted(done) == ["direct", "direct", "direct", "stream", "stream"]
    assert statuses == ["done"] * 5
    assert _mode(db) == "delete" and integrity == "ok"


@pytest.mark.parametrize("get_connection", [v2db.get_connection, legacy_db.get_connection],
                         ids=["feed_v2", "legacy"])
def test_get_connection_waits_30s_for_a_busy_db(db, get_connection):
    """Rollback-journal writers queue behind each other. Under concurrent runs + app
    traffic on a slow mount, sqlite3's 5s default expired ('database is locked' after
    5.18s, measured) — 30s lets a writer wait its turn instead of failing the request."""
    with get_connection() as c:
        assert c.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
