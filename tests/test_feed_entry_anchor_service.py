"""
Tests for backend.services.feed_entry_anchor_service — Chat-3 feed-entry
persistent anchor (direct DB read via feed_chat_links, independent of the
per-request feed_context, so it survives the whole conversation).

Uses a real in-memory sqlite DB built from ALL_TABLES (this project's
established pattern, see test_document_memory_service.py) with real rows,
rather than mocking the query layer, so insight_to_markdown (export_service)
runs for real too. get_connection is patched at both call sites per the
project's patch-at-source rule for deferred imports:
  - feed_entry_anchor_service.get_connection (module-level import there)
  - backend.utils.db.get_connection (export_service.insight_to_markdown's
    own deferred `from ..utils.db import get_connection`)

Critically covers the silent-degrade behavior found in the pipeline recon:
a stale/deleted insight_id (or any internal failure) must produce "" and
never raise -- this must stay a silent, safe skip.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

import pytest

from backend.database.schema import ALL_TABLES
from backend.services import feed_entry_anchor_service as anchor_svc


@pytest.fixture
def mem_db(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    for stmt in ALL_TABLES:
        conn.execute(stmt)
    conn.commit()

    @contextmanager
    def _get_conn():
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    monkeypatch.setattr(anchor_svc, "get_connection", _get_conn)
    import backend.utils.db as db_module
    monkeypatch.setattr(db_module, "get_connection", _get_conn)

    yield conn
    conn.close()


def _make_project(conn, project_id="proj-1", name="Quantum Computing", intent_summary="A deep dive into qubits and gates."):
    conn.execute(
        "INSERT INTO learning_projects (project_id, name, intent_profile) VALUES (?, ?, ?)",
        (project_id, name, json.dumps({"intent_summary": intent_summary})),
    )
    conn.commit()


def _make_insight(conn, project_id="proj-1", day_number=1, headline="Day 1: Superposition", action_item="Read the Feynman lectures on QM.") -> int:
    pkg = {
        "package_headline": headline,
        "learning_thread": "Building from classical bits to qubits.",
        "insights": [{"title": "Superposition", "summary": "A qubit can be 0 and 1 at once."}],
        "curiosity_insights": [],
        "action_item": action_item,
    }
    cur = conn.execute(
        "INSERT INTO project_insights (project_id, day_number, insight_json, status) VALUES (?, ?, ?, 'done')",
        (project_id, day_number, json.dumps(pkg)),
    )
    conn.commit()
    return cur.lastrowid


def _link(conn, session_id, project_id, insight_id):
    conn.execute(
        "INSERT INTO feed_chat_links (session_id, project_id, insight_id, article_key) VALUES (?, ?, ?, 'k1')",
        (session_id, project_id, insight_id),
    )
    conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Direct-DB-read mechanism — real chain: feed_chat_links -> project_insights
# + learning_projects, real markdown rendered via export_service
# ─────────────────────────────────────────────────────────────────────────────

class TestGetAnchorForSession:
    def test_real_anchor_resolves_project_and_insight(self, mem_db):
        _make_project(mem_db)
        insight_id = _make_insight(mem_db)
        _link(mem_db, "sess-1", "proj-1", insight_id)

        anchor = anchor_svc.get_anchor_for_session("sess-1")

        assert anchor.startswith(
            "FEED ENTRY ANCHOR — background from the project this conversation started from:"
        )
        assert "PROJECT: Quantum Computing" in anchor
        assert "A deep dive into qubits and gates." in anchor
        assert "Day 1: Superposition" in anchor
        assert "A qubit can be 0 and 1 at once." in anchor
        assert "Read the Feynman lectures on QM." in anchor

    def test_uses_most_recent_link_when_multiple_exist(self, mem_db):
        _make_project(mem_db)
        day1 = _make_insight(mem_db, day_number=1, headline="Day 1: Superposition")
        day2 = _make_insight(mem_db, day_number=2, headline="Day 2: Entanglement")
        # Insert in order so day2's link has the later created_at (ORDER BY created_at DESC).
        mem_db.execute(
            "INSERT INTO feed_chat_links (session_id, project_id, insight_id, article_key, created_at) "
            "VALUES ('sess-multi', 'proj-1', ?, 'k1', '2026-01-01T00:00:00')",
            (day1,),
        )
        mem_db.execute(
            "INSERT INTO feed_chat_links (session_id, project_id, insight_id, article_key, created_at) "
            "VALUES ('sess-multi', 'proj-1', ?, 'k2', '2026-01-02T00:00:00')",
            (day2,),
        )
        mem_db.commit()

        anchor = anchor_svc.get_anchor_for_session("sess-multi")
        assert "Day 2: Entanglement" in anchor
        assert "Day 1: Superposition" not in anchor

    def test_anchor_is_scoped_to_the_clicked_card_not_the_whole_day(self, mem_db):
        # The anchor used to render the ENTIRE day package on every turn, with
        # no marker of which card the conversation started from. It now renders
        # only the card the feed_chat_links row's article_key points at.
        _make_project(mem_db)
        pkg = {
            "package_headline": "Day 1: Two Cards",
            "insights": [
                {"title": "Superposition", "summary": "A qubit can be 0 and 1 at once."},
                {"title": "Decoherence",   "summary": "Qubits lose state to their environment."},
            ],
            "curiosity_insights": [],
            "action_item": "Read the Feynman lectures on QM.",
        }
        cur = mem_db.execute(
            "INSERT INTO project_insights (project_id, day_number, insight_json, status) "
            "VALUES ('proj-1', 1, ?, 'done')",
            (json.dumps(pkg),),
        )
        mem_db.commit()
        mem_db.execute(
            "INSERT INTO feed_chat_links (session_id, project_id, insight_id, article_key) "
            "VALUES ('sess-scoped', 'proj-1', ?, 'superposition')",
            (cur.lastrowid,),
        )
        mem_db.commit()

        anchor = anchor_svc.get_anchor_for_session("sess-scoped")

        assert "A qubit can be 0 and 1 at once." in anchor
        assert "Decoherence" not in anchor
        assert "Qubits lose state to their environment." not in anchor
        # Day framing survives; the day's action item does not (it belongs to
        # the package, not to this card).
        assert "Day 1: Two Cards" in anchor
        assert "Read the Feynman lectures on QM." not in anchor

    def test_unmatched_article_key_falls_back_to_the_full_day(self, mem_db):
        # Renamed title / legacy row: the whole day is still better than nothing.
        _make_project(mem_db)
        insight_id = _make_insight(mem_db)
        _link(mem_db, "sess-nomatch", "proj-1", insight_id)  # article_key 'k1'

        anchor = anchor_svc.get_anchor_for_session("sess-nomatch")

        assert "A qubit can be 0 and 1 at once." in anchor
        assert "Read the Feynman lectures on QM." in anchor

    def test_session_with_no_feed_link_returns_empty(self, mem_db):
        assert anchor_svc.get_anchor_for_session("unlinked-session") == ""

    def test_empty_session_id_returns_empty(self, mem_db):
        assert anchor_svc.get_anchor_for_session("") == ""


# ─────────────────────────────────────────────────────────────────────────────
# 20,000-char cap
# ─────────────────────────────────────────────────────────────────────────────

class TestAnchorCharCap:
    def test_oversized_package_is_capped_at_max_anchor_chars(self, mem_db):
        _make_project(mem_db)
        # One insight card with a huge body -- pushes the rendered markdown
        # well past the 20,000-char cap.
        pkg = {
            "package_headline": "Huge Day",
            "insights": [{"title": "Big", "summary": "This is a long sentence about qubits. " * 2000}],
            "curiosity_insights": [],
        }
        cur = mem_db.execute(
            "INSERT INTO project_insights (project_id, day_number, insight_json, status) VALUES ('proj-1', 1, ?, 'done')",
            (json.dumps(pkg),),
        )
        mem_db.commit()
        _link(mem_db, "sess-huge", "proj-1", cur.lastrowid)

        # Confirm the raw content actually exceeds the cap, so a pass here
        # proves truncation engaged rather than coincidentally staying short.
        from backend.services.export_service import insight_to_markdown
        raw = insight_to_markdown("proj-1", cur.lastrowid)
        assert len(raw) > anchor_svc._MAX_ANCHOR_CHARS

        anchor = anchor_svc.get_anchor_for_session("sess-huge")
        assert len(anchor) <= anchor_svc._MAX_ANCHOR_CHARS


# ─────────────────────────────────────────────────────────────────────────────
# Silent-degrade behavior (pipeline recon finding) -- LOCK THIS IN. A stale
# insight_id, or any internal failure, must produce "" and never raise, and
# nothing should signal the omission back to the caller.
# ─────────────────────────────────────────────────────────────────────────────

class TestSilentDegrade:
    def test_stale_deleted_insight_id_returns_empty_not_exception(self, mem_db):
        _make_project(mem_db)
        # feed_chat_links references an insight_id that does not exist in
        # project_insights (simulates the row having been deleted later).
        _link(mem_db, "sess-stale", "proj-1", 99999)

        anchor = anchor_svc.get_anchor_for_session("sess-stale")
        assert anchor == ""

    def test_stale_insight_does_not_raise(self, mem_db):
        _make_project(mem_db)
        _link(mem_db, "sess-stale-2", "proj-1", 99999)
        try:
            anchor_svc.get_anchor_for_session("sess-stale-2")
        except Exception as e:
            pytest.fail(f"get_anchor_for_session must never raise, got: {e!r}")

    def test_unexpected_internal_failure_also_degrades_silently(self, mem_db, monkeypatch):
        # Not just the "row missing" case -- any internal exception must be
        # swallowed by the top-level try/except, never surfaced to the caller.
        def _boom(session_id):
            raise RuntimeError("simulated internal failure")

        monkeypatch.setattr(anchor_svc, "_resolve_project_day", _boom)
        assert anchor_svc.get_anchor_for_session("any-session") == ""

    def test_deleted_project_also_degrades_silently(self, mem_db):
        # project_id in feed_chat_links no longer exists in learning_projects
        # (LEFT JOIN in insight_to_markdown handles this; project_summary's
        # own lookup also handles a missing project_id row).
        insight_id = _make_insight(mem_db, project_id="ghost-project")
        _link(mem_db, "sess-ghost", "ghost-project", insight_id)

        anchor = anchor_svc.get_anchor_for_session("sess-ghost")
        # insight still resolves (project_id/insight_id pair matches the row),
        # just with no project name/summary prefix -- confirms partial data
        # renders gracefully rather than failing outright.
        assert anchor != ""
        assert "PROJECT:" not in anchor
