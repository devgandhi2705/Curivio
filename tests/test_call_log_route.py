"""route / route_step turn a turn's rows into a readable trail: which list
answered, why that list, what it fell past on the way."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager

import pytest

from backend.database.schema import ALL_TABLES, MIGRATIONS


@pytest.fixture
def db(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    for statement in ALL_TABLES:
        conn.execute(statement)
    for migration in MIGRATIONS:
        for statement in (migration if isinstance(migration, (list, tuple)) else [migration]):
            try:
                conn.execute(statement)
            except sqlite3.OperationalError:
                pass
    conn.commit()

    @contextmanager
    def _get_conn():
        yield conn
        conn.commit()

    monkeypatch.setattr("backend.utils.db.get_connection", _get_conn)
    return conn


def test_write_call_row_persists_route_and_step(db):
    from backend.llm.call_logger import write_call_row
    write_call_row(run_id="r1", parent_run_id=None, timestamp_start="t", timestamp_end="t",
                   latency_ms=1, provider="groq", call_type="chat_turn",
                   route="simple ← classifier+toggle:web_search", route_step=2)
    row = db.execute("SELECT route, route_step FROM llm_call_log WHERE run_id='r1'").fetchone()
    assert row["route"] == "simple ← classifier+toggle:web_search"
    assert row["route_step"] == 2


def test_logger_reads_route_off_the_call_metadata(db):
    from uuid import uuid4
    from langchain_core.outputs import ChatGeneration, LLMResult
    from langchain_core.messages import AIMessage
    from backend.llm.call_logger import LLMCallLogger

    handler, run_id = LLMCallLogger(), uuid4()
    handler.on_chat_model_start(
        {}, [[AIMessage(content="hi")]], run_id=run_id,
        metadata={"call_type": "chat_turn", "ls_provider": "groq", "ls_model_name": "openai/gpt-oss-120b",
                  "route": "complex ← classifier", "route_step": 1})
    handler.on_llm_end(LLMResult(generations=[[ChatGeneration(message=AIMessage(content="answer"))]]),
                       run_id=run_id)
    row = db.execute("SELECT route, route_step, provider FROM llm_call_log").fetchone()
    assert (row["route"], row["route_step"], row["provider"]) == ("complex ← classifier", 1, "groq")


def test_admin_rows_expose_route(db):
    from backend.services import admin_service
    assert "l.route" in admin_service._ROW_COLUMNS
    assert "l.route_step" in admin_service._ROW_COLUMNS
