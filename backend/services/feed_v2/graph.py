"""
Feed v2 LangGraph orchestration (Phase 7) — the full daily pipeline end to end,
running against STUB agents that return canned-but-realistic data.

This phase proves the shared infrastructure works before Phase 8+ swaps stubs for
real agents ONE AT A TIME:
  * a single typed state (FeedState) — the contract every later phase reads/writes;
  * the graph: lesson_planner -> [web_researcher, corpus_researcher] (parallel) ->
    source_ranker -> section_writer -> claim_validator -> assembler, with THREE
    real, capped feedback loops;
  * SqliteSaver checkpointing on the SAME curivio.db file (resume-after-crash);
  * the concurrency lease enforced by mas_runs' unique partial index (Phase 3);
  * the reaper (startup sweep of expired 'running' leases);
  * SSE streaming of node transitions, reattachable by trace_id via the checkpointer.

Nothing here needs touching when a stub becomes real — a real agent just replaces
the body of its stub node, writing the same state keys.

Isolation: imports only feed_v2's own db/provider/projects/journeys + third-party
langgraph; never backend.services.* / backend.llm.*.

State type choice: TypedDict, not Pydantic. LangGraph's native state is a TypedDict
with per-key reducers; parallel nodes here write DISJOINT keys so plain last-writer
merge is correct and no reducer/validation layer is needed. Pydantic would add
validation cost for no benefit at this contract-defining stage.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import TypedDict
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from . import db as v2db
from . import journeys, projects
from .agents import corpus_researcher as corpus_agent  # Phase 8: real RAG node body
from .agents import web_researcher as web_agent        # Phase 9: real search node body
from .agents import source_ranker as ranker_agent      # Phase 10: real origin-aware ranking
from .agents import lesson_planner as lesson_agent      # Phase 11: real decision-layer node body
from .agents import section_writer as writer_agent      # Phase 11: real four-group writer node body
from .db import get_connection

logger = logging.getLogger(__name__)

# ── Loop caps (tracked in state, enforced by the conditional routers) ─────────
MAX_WEB_ITERS = 3          # web_researcher self-loop ("evidence too thin")
MAX_REWRITES = 2           # claim_validator -> section_writer ("writing weak")
MAX_RESEARCH_REENTRY = 1   # claim_validator -> web_researcher ("evidence weak")

# Lease duration. A real Phase-8+ run is ~3-4 min wall-clock (mentor-deck target);
# 15 min comfortably exceeds that with margin for slow LLM legs / rotation retries,
# while staying short enough that a crashed run's lease expires and gets reaped in a
# reasonable window. Not meant to be exact yet — revisit once real runs exist.
LEASE_SECONDS = 15 * 60

# ── Test rig hooks (module-level so a test can drive the stubs deterministically).
# Production defaults make the stubs run straight through with no loops.
STUB_EVIDENCE_THIN = False    # web_researcher reports "evidence too thin" every run
STUB_WRITING_WEAK = False     # claim_validator reports "writing weak"
STUB_EVIDENCE_WEAK = False    # claim_validator reports "evidence weak"
STUB_SLEEP_SECONDS = 0.0      # lesson_planner sleeps this long (SSE slow-node test)
USE_REAL_SOURCE_RANKER = True # source_ranker makes the one real provider.call_agent
# Phase 8: corpus_researcher is real now (module default True = production RAG).
# _reset_rig() flips it False so the Phase-7 offline mechanics tests keep getting
# canned corpus data (no key / no embedded materials needed for loop-cap/barrier/
# resume assertions). Tests that want real retrieval set it True explicitly.
USE_REAL_CORPUS_RESEARCHER = True
# Phase 9: web_researcher is real now (module default True = production search + the
# real coverage assessor driving the self-loop). _reset_rig() flips it False so the
# Phase-7 loop-cap/barrier/resume tests keep using the canned stub whose loop is
# driven by STUB_EVIDENCE_THIN (no search key / no LLM needed for those mechanics).
USE_REAL_WEB_RESEARCHER = True
# Phase 11: lesson_planner + section_writer are real now (module default True = production).
# _reset_rig() flips both False so the Phase-7 offline mechanics tests keep the canned stubs
# (no key needed; exec order/counts + the rewrite loop driven by section_writer_runs unchanged).
USE_REAL_LESSON_PLANNER = True
USE_REAL_SECTION_WRITER = True
_CRASH_ONCE: set[str] = set() # node names that raise once then succeed (resume test)
_EXEC_LOG: list[str] = []     # every node appends its name (resume/loop assertions)


def _reset_rig() -> None:
    """Test helper: restore all rig hooks to production defaults."""
    global STUB_EVIDENCE_THIN, STUB_WRITING_WEAK, STUB_EVIDENCE_WEAK
    global STUB_SLEEP_SECONDS, USE_REAL_SOURCE_RANKER, USE_REAL_CORPUS_RESEARCHER
    global USE_REAL_WEB_RESEARCHER, USE_REAL_LESSON_PLANNER, USE_REAL_SECTION_WRITER
    STUB_EVIDENCE_THIN = STUB_WRITING_WEAK = STUB_EVIDENCE_WEAK = False
    STUB_SLEEP_SECONDS = 0.0
    USE_REAL_SOURCE_RANKER = True
    USE_REAL_CORPUS_RESEARCHER = False   # offline default for the mechanics tests
    USE_REAL_WEB_RESEARCHER = False      # offline default: canned stub, STUB_EVIDENCE_THIN drives the loop
    USE_REAL_LESSON_PLANNER = False      # offline default: canned lesson_plan stub (no key)
    USE_REAL_SECTION_WRITER = False      # offline default: canned draft stub, rewrite loop via section_writer_runs
    _CRASH_ONCE.clear()
    _EXEC_LOG.clear()


# ── Typed state: the contract Phases 9-13 write against ───────────────────────
class FeedState(TypedDict, total=False):
    # inputs (seeded from the real profile + journey entry)
    trace_id: str
    user_id: str
    project_id: str
    day_number: int
    profile: dict
    coverage_mode: str
    journey_entry: dict
    # per-node outputs
    lesson_plan: dict
    web_findings: list
    corpus_findings: list
    ranked_sources: list
    section_drafts: list
    verdicts: list
    assembled: dict
    # loop counters + condition flags
    web_research_iters: int
    section_writer_runs: int
    rewrite_iters: int
    research_reentry_iters: int
    evidence_thin: bool
    writing_weak: bool
    evidence_weak: bool
    # terminal
    degraded_reason: str
    error: str


def _crash_if_rigged(node: str) -> None:
    if node in _CRASH_ONCE:
        _CRASH_ONCE.discard(node)  # crash once, then let the resume succeed
        raise RuntimeError(f"simulated crash in {node}")


# ── Stub nodes: each READS and WRITES state in the real shape ─────────────────
def lesson_planner(state: FeedState) -> dict:
    """Phase 11: REAL decision layer — one cheap LLM call deciding today's objectives +
    whether section 3 (prerequisites) renders; worked-example mode + section-4b='pending'
    derived mechanically. NO research / NO source consumption. Writes the same state key
    (lesson_plan) the stub did. Offline mechanics tests set USE_REAL_LESSON_PLANNER=False
    (via _reset_rig) to keep the canned stub (no key)."""
    _EXEC_LOG.append("lesson_planner")
    if STUB_SLEEP_SECONDS:
        time.sleep(STUB_SLEEP_SECONDS)   # SSE slow-node test
    _crash_if_rigged("lesson_planner")
    if not USE_REAL_LESSON_PLANNER:
        je = state.get("journey_entry") or {}
        return {"lesson_plan": {"day": state.get("day_number"),
                                "objectives": [je.get("focus") or "objective-1", "objective-2"],
                                "stub": True}}
    return lesson_agent.run_lesson_planner(
        project_id=state.get("project_id"),
        journey_entry=state.get("journey_entry") or {},
        coverage_mode=state.get("coverage_mode") or "open",
        profile=state.get("profile") or {},
        meta={"trace_id": state.get("trace_id"), "user_id": state.get("user_id"),
              "project_id": state.get("project_id"), "day_number": state.get("day_number")})


def web_researcher(state: FeedState) -> dict:
    """Phase 9: REAL web search (query construction + uncapped TinyFish search + claim
    extraction) governed by a real coverage assessor that sets evidence_thin, which
    drives graph.py's existing _web_route self-loop (cap 3, unchanged). Writes the same
    state keys/shape the stub did. material_bound reads the project's material from the
    DB to fence queries (Phase 9 decision — corpus_researcher's parallel output isn't
    visible in the same super-step). Offline mechanics tests set USE_REAL_WEB_RESEARCHER
    =False (via _reset_rig) to keep the canned stub whose loop is driven by STUB_EVIDENCE_THIN."""
    _EXEC_LOG.append("web_researcher")
    _crash_if_rigged("web_researcher")
    if not USE_REAL_WEB_RESEARCHER:
        it = state.get("web_research_iters", 0) + 1
        return {"web_findings": [{"src": "web", "iter": it, "stub": True,
                                  "text": "stub web finding", "url": f"https://stub.example/{it}"}],
                "web_research_iters": it,
                "evidence_thin": bool(STUB_EVIDENCE_THIN)}
    return web_agent.run_web_research(
        project_id=state.get("project_id"),
        journey_entry=state.get("journey_entry") or {},
        coverage_mode=state.get("coverage_mode") or "open",
        keywords=(state.get("profile") or {}).get("keywords"),
        iteration=state.get("web_research_iters", 0) + 1,
        prior_findings=state.get("web_findings") or [],
        meta={"trace_id": state.get("trace_id"), "user_id": state.get("user_id"),
              "project_id": state.get("project_id"), "day_number": state.get("day_number"),
              "step_index": 1})


def corpus_researcher(state: FeedState) -> dict:
    """Phase 8: REAL RAG over the project's uploaded materials (retrieval + one
    extraction LLM call). Writes the same state key/shape the stub did
    (corpus_findings: list[dict]); a project with no materials yields []. Offline
    mechanics tests set USE_REAL_CORPUS_RESEARCHER=False (via _reset_rig) to get
    canned data with no key / no embedded corpus."""
    _EXEC_LOG.append("corpus_researcher")
    _crash_if_rigged("corpus_researcher")
    if not USE_REAL_CORPUS_RESEARCHER:
        return {"corpus_findings": [{"src": "corpus", "stub": True, "text": "stub corpus finding"}]}
    return corpus_agent.run_corpus_research(
        project_id=state.get("project_id"),
        journey_entry=state.get("journey_entry") or {},
        coverage_mode=state.get("coverage_mode") or "open",
        keywords=(state.get("profile") or {}).get("keywords"),
        meta={"trace_id": state.get("trace_id"), "user_id": state.get("user_id"),
              "project_id": state.get("project_id"), "day_number": state.get("day_number"),
              "step_index": 2})


def source_ranker(state: FeedState) -> dict:
    """Phase 10: REAL origin-aware ranking — two passes (corpus + web) on the same 0-1
    scale, budget-batched, mechanically merged into one uncapped sorted list; sets a
    degraded_reason in state when the merged pool is below the floor. Writes the same
    state key (ranked_sources) the stub did. Offline mechanics tests set
    USE_REAL_SOURCE_RANKER=False (via _reset_rig) to get a canned merge with no LLM."""
    _EXEC_LOG.append("source_ranker")
    _crash_if_rigged("source_ranker")
    if not USE_REAL_SOURCE_RANKER:
        return {"ranked_sources": (state.get("web_findings") or []) + (state.get("corpus_findings") or [])}
    return ranker_agent.run_source_ranker(
        coverage_mode=state.get("coverage_mode") or "open",
        web_findings=state.get("web_findings") or [],
        corpus_findings=state.get("corpus_findings") or [],
        journey_entry=state.get("journey_entry") or {},
        meta={"trace_id": state.get("trace_id"), "user_id": state.get("user_id"),
              "project_id": state.get("project_id"), "day_number": state.get("day_number")})


def section_writer(state: FeedState) -> dict:
    """Phase 11: REAL four-group writer (A: 1-3, B: 4-5, C: 6-7 + retrieval checks, D: 8-9),
    each its own call sharing the lesson-plan contract, beats structure, per-group source
    routing (protected forced into core), inline citations, and per-group DB persistence for
    sub-node crash-resume. Writes the same state keys the stub did (section_drafts +
    section_writer_runs + rewrite_iters), so the rewrite loop is unchanged. Offline mechanics
    tests set USE_REAL_SECTION_WRITER=False (via _reset_rig) to keep the canned draft stub."""
    _EXEC_LOG.append("section_writer")
    _crash_if_rigged("section_writer")
    if not USE_REAL_SECTION_WRITER:
        runs = state.get("section_writer_runs", 0) + 1
        return {"section_drafts": [{"section_group": "grp-1", "text": f"stub draft (write #{runs})", "run": runs}],
                "section_writer_runs": runs,
                "rewrite_iters": runs - 1}   # first write isn't a rewrite
    return writer_agent.run_section_writer(
        project_id=state.get("project_id"), user_id=state.get("user_id"),
        day_number=state.get("day_number"), coverage_mode=state.get("coverage_mode") or "open",
        lesson_plan=state.get("lesson_plan") or {}, ranked_sources=state.get("ranked_sources") or [],
        section_writer_runs=state.get("section_writer_runs", 0),
        meta={"trace_id": state.get("trace_id"), "user_id": state.get("user_id"),
              "project_id": state.get("project_id"), "day_number": state.get("day_number")})


def claim_validator(state: FeedState) -> dict:
    _EXEC_LOG.append("claim_validator")
    _crash_if_rigged("claim_validator")
    return {"verdicts": [{"claim": "stub-claim", "verdict": "supported", "stub": True}],
            "writing_weak": bool(STUB_WRITING_WEAK),
            "evidence_weak": bool(STUB_EVIDENCE_WEAK)}


def web_gate(state: FeedState) -> dict:
    """Passthrough marking 'web research done looping'. Exists so source_ranker can
    barrier on [web_gate, corpus_researcher] — without it, source_ranker's fan-in
    would fire early on corpus's arrival while web is still self-looping, running the
    whole tail twice. Not crash-rigged; carries no state of its own."""
    _EXEC_LOG.append("web_gate")
    return {}


def research_reentry(state: FeedState) -> dict:
    """Tiny increment node on the claim_validator -> web_researcher re-entry edge, so
    the re-entry cap has its own counter distinct from the web self-loop counter.
    Resets evidence_thin so the re-run doesn't self-loop on stale state."""
    _EXEC_LOG.append("research_reentry")
    return {"research_reentry_iters": state.get("research_reentry_iters", 0) + 1,
            "evidence_thin": False}


def assembler(state: FeedState) -> dict:
    _EXEC_LOG.append("assembler")
    _crash_if_rigged("assembler")
    return {"assembled": {"trace_id": state.get("trace_id"), "day": state.get("day_number"),
                          "objectives": (state.get("lesson_plan") or {}).get("objectives"),
                          "sources": state.get("ranked_sources"),
                          "sections": state.get("section_drafts"),
                          "verdicts": state.get("verdicts"), "stub": True}}


# ── Conditional routers (REAL: they check counters and route differently) ─────
def _web_route(state: FeedState) -> str:
    if state.get("evidence_thin") and state.get("web_research_iters", 0) < MAX_WEB_ITERS:
        return "web_researcher"        # loop back — evidence too thin
    return "web_gate"                   # done looping -> barrier with corpus at source_ranker


def _validate_route(state: FeedState) -> str:
    if state.get("writing_weak") and state.get("rewrite_iters", 0) < MAX_REWRITES:
        return "section_writer"        # rewrite — writing was weak
    if state.get("evidence_weak") and state.get("research_reentry_iters", 0) < MAX_RESEARCH_REENTRY:
        return "research_reentry"      # back to research — evidence was weak
    return "assembler"


def build_graph() -> StateGraph:
    g = StateGraph(FeedState)
    for name, fn in (("lesson_planner", lesson_planner), ("web_researcher", web_researcher),
                     ("web_gate", web_gate), ("corpus_researcher", corpus_researcher),
                     ("source_ranker", source_ranker), ("section_writer", section_writer),
                     ("claim_validator", claim_validator), ("research_reentry", research_reentry),
                     ("assembler", assembler)):
        g.add_node(name, fn)
    g.add_edge(START, "lesson_planner")
    g.add_edge("lesson_planner", "web_researcher")     # fan-out (parallel)
    g.add_edge("lesson_planner", "corpus_researcher")
    g.add_conditional_edges("web_researcher", _web_route,
                            {"web_researcher": "web_researcher", "web_gate": "web_gate"})
    # TRUE barrier: source_ranker waits for BOTH the web loop (via web_gate) AND
    # corpus — a plain fan-in would fire early on corpus while web still loops.
    g.add_edge(["web_gate", "corpus_researcher"], "source_ranker")
    g.add_edge("source_ranker", "section_writer")
    g.add_edge("section_writer", "claim_validator")
    g.add_conditional_edges("claim_validator", _validate_route,
                            {"section_writer": "section_writer", "research_reentry": "research_reentry",
                             "assembler": "assembler"})
    # Re-entry re-fans-out to BOTH researchers so the barrier is satisfied again.
    g.add_edge("research_reentry", "web_researcher")
    g.add_edge("research_reentry", "corpus_researcher")
    g.add_edge("assembler", END)
    return g


# ── Checkpointer: SqliteSaver on the SAME curivio.db (its own connection) ──────
def _saver() -> SqliteSaver:
    """A SqliteSaver over a dedicated connection to v2db.DB_PATH — the SAME file the
    rest of v2 uses (its checkpoints/writes tables just coexist with the v2 tables).
    Separate connection on purpose: the saver doesn't need sqlite-vec/FK, and v2's
    get_connection stays untouched. Reads DB_PATH at call time so tests' monkeypatch
    of v2db.DB_PATH is honored."""
    conn = sqlite3.connect(str(v2db.DB_PATH), check_same_thread=False)
    # DELETE, not WAL — see v2db.get_connection's comment: WAL doesn't work on
    # HF Spaces' network-backed persistent volume and was corrupting this
    # shared curivio.db file's schema catalog.
    conn.execute("PRAGMA journal_mode=DELETE")
    return SqliteSaver(conn)


def compile_graph(checkpointer=None):
    return build_graph().compile(checkpointer=checkpointer)


# ── Lease + reaper (mas_runs) ─────────────────────────────────────────────────
def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class ConcurrentRunError(Exception):
    """A run for this (project_id, day_number) is already 'running' — rejected by the
    unique partial index, not by any application-level check."""


def acquire_lease(trace_id: str, user_id: str, project_id: str, day_number: int,
                  *, surface: str = "feed_v2", lease_seconds: int = LEASE_SECONDS) -> None:
    """INSERT a 'running' mas_runs row. The unique partial index
    (project_id, day_number) WHERE status='running' makes a concurrent second run
    impossible by construction — a race loses with IntegrityError, no check-then-act.
    Raises ConcurrentRunError if another run holds the slot."""
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(seconds=lease_seconds)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO mas_runs
                       (trace_id, surface, user_id, project_id, day_number, status,
                        lease_expires_at, started_at)
                   VALUES (?, ?, ?, ?, ?, 'running', ?, ?)""",
                (trace_id, surface, user_id, project_id, day_number, expires,
                 now.strftime("%Y-%m-%d %H:%M:%S")),
            )
    except sqlite3.IntegrityError as exc:
        raise ConcurrentRunError(
            f"a run is already active for project {project_id} day {day_number}") from exc


def finalize_run(trace_id: str, status: str, *, degraded_reason: str | None = None,
                 error: str | None = None) -> None:
    """Set terminal status + real token/call totals (summed from llm_call_log by
    trace_id) and clear the lease."""
    with get_connection() as conn:
        tot = conn.execute(
            """SELECT COUNT(*) c, COALESCE(SUM(input_tokens),0) i, COALESCE(SUM(output_tokens),0) o
                   FROM llm_call_log WHERE trace_id = ?""",
            (trace_id,),
        ).fetchone()
        conn.execute(
            """UPDATE mas_runs
                   SET status = ?, ended_at = ?, degraded_reason = ?, error = ?,
                       total_calls = ?, total_in_tokens = ?, total_out_tokens = ?,
                       lease_expires_at = NULL
                   WHERE trace_id = ?""",
            (status, _now_str(), degraded_reason, error, tot["c"], tot["i"], tot["o"], trace_id),
        )


def reap_expired_runs() -> int:
    """Startup sweep: flip any 'running' row whose lease has expired to 'failed'.
    Idempotent (only touches status='running' AND lease_expires_at < now — a second
    call finds none). A genuinely-still-running row has a FUTURE lease and is left
    alone; across an app restart any prior in-flight run's process is already dead, so
    reaping its expired lease is correct, not premature."""
    now = _now_str()
    with get_connection() as conn:
        cur = conn.execute(
            """UPDATE mas_runs SET status = 'failed', ended_at = ?,
                       error = 'lease expired — reaped on startup', lease_expires_at = NULL
                   WHERE status = 'running' AND lease_expires_at IS NOT NULL AND lease_expires_at < ?""",
            (now, now),
        )
        return cur.rowcount


# ── Seed state + run/stream ───────────────────────────────────────────────────
def seed_state(user_id: str, project_id: str, day_number: int, trace_id: str) -> FeedState:
    """Wire the REAL profile + journey day entry into the initial graph state (they
    are not graph nodes — different frequencies — their outputs are inputs here)."""
    proj = projects.get_project(user_id, project_id)
    if proj is None:
        raise ValueError(f"project {project_id} not found for user {user_id}")
    entry = journeys.get_day_entry(user_id, project_id, day_number) or {}
    return {
        "trace_id": trace_id, "user_id": user_id, "project_id": project_id,
        "day_number": day_number, "profile": proj.get("profile") or {},
        "coverage_mode": proj.get("coverage_mode") or "open", "journey_entry": entry,
        "web_findings": [], "corpus_findings": [],
        "web_research_iters": 0, "section_writer_runs": 0,
        "rewrite_iters": 0, "research_reentry_iters": 0,
    }


def run_graph(user_id: str, project_id: str, day_number: int) -> tuple[str, FeedState]:
    """Blocking run: acquire lease, invoke the checkpointed graph, finalize. Returns
    (trace_id, final_state)."""
    trace_id = uuid4().hex
    acquire_lease(trace_id, user_id, project_id, day_number)
    cfg = {"configurable": {"thread_id": trace_id}}
    try:
        final = compile_graph(_saver()).invoke(seed_state(user_id, project_id, day_number, trace_id), cfg)
        finalize_run(trace_id, "done")
        return trace_id, final
    except Exception as exc:
        finalize_run(trace_id, "failed", error=str(exc))
        raise


_LOOP_LABELS = {
    "web_researcher": "evidence too thin — searching again",
    "section_writer": "revising the draft",
    "research_reentry": "evidence was weak — re-researching",
}


def stream_events(trace_id: str, initial: FeedState | None):
    """Yield one NDJSON line per node transition. initial=None RESUMES an existing
    checkpoint for trace_id (reattach); a real seed state starts fresh. A node seen a
    second time is labeled a loop-back event so the UI can show 'searching again'."""
    app = compile_graph(_saver())
    cfg = {"configurable": {"thread_id": trace_id}}
    seen: set[str] = set()
    yield json.dumps({"t": "start", "trace_id": trace_id, "resumed": initial is None}) + "\n"
    for chunk in app.stream(initial, cfg, stream_mode="updates"):
        for node in chunk:
            if node in seen and node in _LOOP_LABELS:
                yield json.dumps({"t": "loop", "agent": node, "label": _LOOP_LABELS[node],
                                  "trace_id": trace_id}) + "\n"
            else:
                yield json.dumps({"t": "node", "agent": node, "trace_id": trace_id}) + "\n"
            seen.add(node)
    yield json.dumps({"t": "done", "trace_id": trace_id}) + "\n"


def start_feed_stream(user_id: str, project_id: str, day_number: int,
                      trace_id: str | None = None):
    """Entry for the SSE route. The lease is acquired EAGERLY here (before any event
    is yielded) so ConcurrentRunError surfaces to the route as a 409 rather than mid
    stream. If trace_id names an existing checkpoint, RESUME it (reattach) with no new
    lease. Returns a generator of NDJSON lines."""
    if trace_id:
        existing = compile_graph(_saver()).get_state({"configurable": {"thread_id": trace_id}})
        if existing.created_at is not None:          # a checkpoint exists — reattach
            return stream_events(trace_id, None)

    if projects.get_project(user_id, project_id) is None:   # eager -> route can 404
        raise ValueError(f"project {project_id} not found for user {user_id}")
    tid = trace_id or uuid4().hex
    acquire_lease(tid, user_id, project_id, day_number)   # eager: may raise ConcurrentRunError

    def _gen():
        try:
            yield from stream_events(tid, seed_state(user_id, project_id, day_number, tid))
            finalize_run(tid, "done")
        except Exception as exc:  # noqa: BLE001
            finalize_run(tid, "failed", error=str(exc))
            yield json.dumps({"t": "error", "message": str(exc), "trace_id": tid}) + "\n"

    return _gen()
