"""
Tests for the Feed-card action path: Ask About / Explain Simply.

Covers the three backend halves of that fix:

  1. feed_chat_link_service persists "explain_simply" instead of silently
     coercing it to "ask_about" (the whitelist had gone stale against the
     table's own CHECK constraint, so every Explain Simply session was
     mislabeled "Asked about" in Related Discussions).

  2. build_system_prompt sends a layman turn down the NATURAL prompt even when
     the session is Feed-linked. The layman directive, the mechanism-preservation
     prefix and RESPONSE PRINCIPLES (LAYMAN) only exist there — a Feed-opened
     Explain Simply used to get the full analytical prompt plus the mandatory
     JSON schema and none of the simplification instructions.

  3. chat_modes_service labels the Explain Simply note correctly.

Real in-memory sqlite built from ALL_TABLES, following the project's
established pattern (see test_feed_entry_anchor_service.py). get_connection is
patched at the source module (backend.utils.db) because feed_chat_link_service
imports it lazily inside each function.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager

import pytest

from backend.database.schema import ALL_TABLES
from backend.services import feed_chat_link_service as link_svc
from backend.services.chat_prompt_service import build_system_prompt


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

    import backend.utils.db as db_module
    monkeypatch.setattr(db_module, "get_connection", _get_conn)

    yield conn
    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 1. interaction_type survives the round trip
# ─────────────────────────────────────────────────────────────────────────────

class TestInteractionTypePersistence:
    def test_explain_simply_is_stored_not_coerced_to_ask_about(self, mem_db):
        row = link_svc.create_link(
            session_id="sess-es", project_id="proj-1", article_key="nanotech",
            article_title="Nanotech delivery", interaction_type="explain_simply",
        )
        assert row["interaction_type"] == "explain_simply"

    def test_ask_about_still_round_trips(self, mem_db):
        row = link_svc.create_link(
            session_id="sess-aa", project_id="proj-1", article_key="nanotech",
            article_title="Nanotech delivery", interaction_type="ask_about",
        )
        assert row["interaction_type"] == "ask_about"

    def test_unknown_interaction_type_still_falls_back_to_ask_about(self, mem_db):
        row = link_svc.create_link(
            session_id="sess-bogus", project_id="proj-1", article_key="nanotech",
            article_title="Nanotech delivery", interaction_type="not_a_real_action",
        )
        assert row["interaction_type"] == "ask_about"

    def test_article_lookup_reports_the_real_type(self, mem_db):
        link_svc.create_link(
            session_id="sess-es2", project_id="proj-1", article_key="nanotech",
            article_title="Nanotech delivery", interaction_type="explain_simply",
        )
        links = link_svc.get_links_for_article("proj-1", "nanotech")
        assert [l["interaction_type"] for l in links] == ["explain_simply"]


# ─────────────────────────────────────────────────────────────────────────────
# 2. Feed-linked + layman -> natural prompt, not the structured/JSON one
# ─────────────────────────────────────────────────────────────────────────────

_JSON_SCHEMA_MARKER = "You MUST respond with ONLY a valid JSON object"


class TestLaymanEscapesTheStructuredPrompt:
    def _ctx(self, **over):
        ctx = {
            "feed_linked": True,
            "layman_mode_context": {"active": True, "mechanism": "The 1940 Act assumes simple chemistry."},
            "current_message": "Explain this simply.",
        }
        ctx.update(over)
        return ctx

    def test_feed_linked_layman_gets_no_json_schema(self):
        prompt = build_system_prompt(self._ctx(), mode="layman")
        assert _JSON_SCHEMA_MARKER not in prompt

    def test_feed_linked_layman_gets_the_mechanism_preservation_directive(self):
        prompt = build_system_prompt(self._ctx(), mode="layman")
        assert "MECHANISM TO PRESERVE" in prompt
        assert "The 1940 Act assumes simple chemistry." in prompt

    def test_feed_linked_non_layman_still_gets_the_structured_prompt(self):
        # Ask About must be unaffected — it is the reason the structured path exists.
        prompt = build_system_prompt(
            {"feed_linked": True, "current_message": "How does this work in practice?"},
            mode="normal",
        )
        assert _JSON_SCHEMA_MARKER in prompt

    def test_plain_layman_chat_is_unchanged(self):
        prompt = build_system_prompt(
            {"layman_mode_context": {"active": True, "mechanism": ""}}, mode="layman"
        )
        assert _JSON_SCHEMA_MARKER not in prompt


# ─────────────────────────────────────────────────────────────────────────────
# 3. Feed-context note labels
# ─────────────────────────────────────────────────────────────────────────────

class TestFeedContextNote:
    def test_explain_simply_note_is_labeled_and_forbids_search(self):
        from backend.services.chat_modes_service import build_feed_context_note
        note = build_feed_context_note({
            "action": "explain_simply",
            "insight_title": "Why India's 1940 Drug Law Struggles",
            "mechanism": "Analytical chemistry standards can't characterise nano-DDS.",
        })
        assert note.startswith("[FEED INSIGHT — Simple Explanation]")
        assert "Do NOT search the web" in note

    def test_ask_about_note_is_labeled_discussion(self):
        from backend.services.chat_modes_service import build_feed_context_note
        note = build_feed_context_note({
            "action": "ask_about",
            "insight_title": "Why India's 1940 Drug Law Struggles",
        })
        assert note.startswith("[FEED INSIGHT — Discussion]")
