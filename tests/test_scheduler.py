"""
Tests for the scheduler service.

Covers:
  - _already_ran_today       (deduplication guard)
  - _build_interests         (interest string construction)
  - daily_feed_job           (full async job: skip / generate / retry / fail)
  - daily_maintenance_job    (cache purge)
  - init_scheduler           (job registration and timing)
  - get_scheduler_status     (observability helper)

All external calls (DB, feed generation, cache) are mocked per project rules:
  - Deferred imports patched at their SOURCE module.
  - Module-level recommendation_service imports patched at scheduler_service scope.
  - asyncio.run() drives async jobs without pytest-asyncio.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import MagicMock, call, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_conn_mock(fetchone_return=None):
    """Return a mock sqlite3-style connection usable as a context manager."""
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__  = MagicMock(return_value=False)
    conn.execute.return_value.fetchone.return_value = fetchone_return
    return conn


def _mock_feed(headline="Test Headline"):
    return {
        "intelligence_brief": {"headline": headline, "executive_summary": "", "key_signals": []},
        "sections":           [],
        "learning_track":     [],
        "action_items":       [],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# _already_ran_today
# ═══════════════════════════════════════════════════════════════════════════════

class TestAlreadyRanToday:

    def test_returns_false_when_no_rows(self):
        conn = _make_conn_mock(fetchone_return=None)
        with patch("backend.utils.db.get_connection", return_value=conn):
            from backend.services.scheduler_service import _already_ran_today
            assert _already_ran_today() is False

    def test_returns_true_when_completed_row_exists(self):
        conn = _make_conn_mock(fetchone_return={"id": 1})
        with patch("backend.utils.db.get_connection", return_value=conn):
            from backend.services.scheduler_service import _already_ran_today
            assert _already_ran_today() is True

    def test_returns_false_on_db_error(self):
        with patch("backend.utils.db.get_connection", side_effect=RuntimeError("db down")):
            from backend.services.scheduler_service import _already_ran_today
            # Must not raise; must default to False so generation can proceed
            assert _already_ran_today() is False


# ═══════════════════════════════════════════════════════════════════════════════
# _build_interests
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildInterests:

    def test_uses_top_liked_topics(self):
        topics = [{"topic": "LLMs"}, {"topic": "RAG"}, {"topic": "transformers"}]
        with patch("backend.services.scheduler_service.get_top_user_interests", return_value=topics):
            from backend.services.scheduler_service import _build_interests
            result = _build_interests()
        assert result == "LLMs, RAG, transformers"

    def test_falls_back_to_default_when_no_topics(self, monkeypatch):
        monkeypatch.setenv("SCHEDULER_DEFAULT_INTERESTS", "AI and machine learning")
        with patch("backend.services.scheduler_service.get_top_user_interests", return_value=[]):
            from backend.services.scheduler_service import _build_interests
            result = _build_interests()
        assert result == "AI and machine learning"

    def test_uses_env_default_on_recommendation_error(self, monkeypatch):
        monkeypatch.setenv("SCHEDULER_DEFAULT_INTERESTS", "cloud computing")
        with patch(
            "backend.services.scheduler_service.get_top_user_interests",
            side_effect=RuntimeError("db down"),
        ):
            from backend.services.scheduler_service import _build_interests
            result = _build_interests()
        assert result == "cloud computing"


# ═══════════════════════════════════════════════════════════════════════════════
# daily_feed_job
# ═══════════════════════════════════════════════════════════════════════════════

class TestDailyFeedJob:
    """All tests mock _already_ran_today, _save_run, _update_run, and the feed generator."""

    def _run(self):
        from backend.services.scheduler_service import daily_feed_job
        asyncio.run(daily_feed_job())

    def test_skips_when_already_ran_today(self):
        with (
            patch("backend.services.scheduler_service._already_ran_today", return_value=True),
            patch("backend.services.scheduler_service._save_run",   return_value=42) as save,
            patch("backend.services.scheduler_service._update_run") as update,
            patch("backend.services.intelligence_service.generate_intelligence_feed") as gen,
        ):
            self._run()
            gen.assert_not_called()
            update.assert_called_once_with(42, "skipped")

    def test_generates_when_not_yet_run(self):
        feed_row = {"id": 99}
        conn = _make_conn_mock(fetchone_return=feed_row)
        with (
            patch("backend.services.scheduler_service._already_ran_today", return_value=False),
            patch("backend.services.scheduler_service._save_run",   return_value=1),
            patch("backend.services.scheduler_service._update_run") as update,
            patch("backend.services.scheduler_service.get_learning_stage", return_value="developing"),
            patch("backend.services.scheduler_service.get_overall_difficulty_preference", return_value="intermediate"),
            patch("backend.services.scheduler_service._build_interests", return_value="LLMs"),
            patch("backend.services.intelligence_service.generate_intelligence_feed", return_value=_mock_feed()),
            patch("backend.utils.db.get_connection", return_value=conn),
        ):
            self._run()
            update.assert_called_once()
            args = update.call_args[0]
            assert args[1] == "completed"

    def test_records_started_then_completed(self):
        conn = _make_conn_mock(fetchone_return={"id": 7})
        with (
            patch("backend.services.scheduler_service._already_ran_today", return_value=False),
            patch("backend.services.scheduler_service._save_run",   return_value=5) as save,
            patch("backend.services.scheduler_service._update_run") as update,
            patch("backend.services.scheduler_service.get_learning_stage", return_value="early"),
            patch("backend.services.scheduler_service.get_overall_difficulty_preference", return_value="beginner"),
            patch("backend.services.scheduler_service._build_interests", return_value="AI"),
            patch("backend.services.intelligence_service.generate_intelligence_feed", return_value=_mock_feed()),
            patch("backend.utils.db.get_connection", return_value=conn),
        ):
            self._run()
            save.assert_called_once()
            assert save.call_args[0][0] == "started"
            update.assert_called_once()
            assert update.call_args[0][1] == "completed"
            assert update.call_args[1].get("feed_id") == 7

    def test_retries_on_transient_failure_then_succeeds(self):
        conn = _make_conn_mock(fetchone_return={"id": 3})
        call_count = {"n": 0}

        def flaky_generate(_interests):
            call_count["n"] += 1
            if call_count["n"] < 2:
                raise RuntimeError("transient")
            return _mock_feed()

        with (
            patch("backend.services.scheduler_service._already_ran_today", return_value=False),
            patch("backend.services.scheduler_service._save_run",   return_value=1),
            patch("backend.services.scheduler_service._update_run") as update,
            patch("backend.services.scheduler_service.get_learning_stage", return_value="developing"),
            patch("backend.services.scheduler_service.get_overall_difficulty_preference", return_value="intermediate"),
            patch("backend.services.scheduler_service._build_interests", return_value="AI"),
            patch("backend.services.intelligence_service.generate_intelligence_feed", side_effect=flaky_generate),
            patch("backend.utils.db.get_connection", return_value=conn),
        ):
            self._run()
            assert call_count["n"] == 2
            assert update.call_args[0][1] == "completed"

    def test_exhausts_retries_and_marks_failed(self):
        with (
            patch("backend.services.scheduler_service._already_ran_today", return_value=False),
            patch("backend.services.scheduler_service._save_run",   return_value=2),
            patch("backend.services.scheduler_service._update_run") as update,
            patch("backend.services.scheduler_service.get_learning_stage", return_value="early"),
            patch("backend.services.scheduler_service.get_overall_difficulty_preference", return_value="beginner"),
            patch("backend.services.scheduler_service._build_interests", return_value="AI"),
            patch(
                "backend.services.intelligence_service.generate_intelligence_feed",
                side_effect=RuntimeError("always fails"),
            ),
        ):
            self._run()
            assert update.call_args[0][1] == "failed"
            assert "always fails" in (update.call_args[1].get("error_msg") or "")

    def test_retry_count_respects_max_retries_env(self, monkeypatch):
        """With SCHEDULER_MAX_RETRIES=1, only 2 total attempts are made."""
        monkeypatch.setenv("SCHEDULER_MAX_RETRIES", "1")
        # Reload the module constant
        import importlib
        import backend.services.scheduler_service as sched_mod
        monkeypatch.setattr(sched_mod, "_MAX_RETRIES", 1)

        call_count = {"n": 0}

        def always_fails(_interests):
            call_count["n"] += 1
            raise RuntimeError("fail")

        with (
            patch("backend.services.scheduler_service._already_ran_today", return_value=False),
            patch("backend.services.scheduler_service._save_run",   return_value=1),
            patch("backend.services.scheduler_service._update_run"),
            patch("backend.services.scheduler_service.get_learning_stage", return_value="early"),
            patch("backend.services.scheduler_service.get_overall_difficulty_preference", return_value="beginner"),
            patch("backend.services.scheduler_service._build_interests", return_value="AI"),
            patch("backend.services.intelligence_service.generate_intelligence_feed", side_effect=always_fails),
        ):
            self._run()
            assert call_count["n"] == 2  # 1 attempt + 1 retry

    def test_records_skipped_status_not_failed(self):
        with (
            patch("backend.services.scheduler_service._already_ran_today", return_value=True),
            patch("backend.services.scheduler_service._save_run",   return_value=10),
            patch("backend.services.scheduler_service._update_run") as update,
            patch("backend.services.intelligence_service.generate_intelligence_feed") as gen,
        ):
            self._run()
            gen.assert_not_called()
            status = update.call_args[0][1]
            assert status == "skipped"
            assert status != "failed"


# ═══════════════════════════════════════════════════════════════════════════════
# daily_maintenance_job
# ═══════════════════════════════════════════════════════════════════════════════

class TestDailyMaintenanceJob:

    def _run(self):
        from backend.services.scheduler_service import daily_maintenance_job
        asyncio.run(daily_maintenance_job())

    def test_purges_expired_cache_entries(self):
        with patch("backend.services.feed_cache_service.purge_expired", return_value=5) as purge:
            self._run()
            purge.assert_called_once()

    def test_handles_purge_error_gracefully(self):
        with patch(
            "backend.services.feed_cache_service.purge_expired",
            side_effect=RuntimeError("db locked"),
        ):
            # Must not raise
            self._run()


# ═══════════════════════════════════════════════════════════════════════════════
# init_scheduler
# ═══════════════════════════════════════════════════════════════════════════════

class TestInitScheduler:

    def _patched_scheduler(self):
        """Return a mock that replaces the module-level _scheduler."""
        mock = MagicMock()
        mock.running = False
        mock.get_jobs.return_value = []
        return mock

    def test_schedules_feed_and_maintenance_jobs(self):
        mock_sched = self._patched_scheduler()
        with patch("backend.services.scheduler_service._scheduler", mock_sched):
            from backend.services.scheduler_service import init_scheduler
            init_scheduler()

        job_ids = [c[1]["id"] for c in mock_sched.add_job.call_args_list]
        assert "daily_feed"        in job_ids
        assert "daily_maintenance" in job_ids

    def test_respects_hour_minute_env_vars(self, monkeypatch):
        monkeypatch.setenv("SCHEDULER_JOB_HOUR",   "14")
        monkeypatch.setenv("SCHEDULER_JOB_MINUTE", "30")

        mock_sched = self._patched_scheduler()
        with patch("backend.services.scheduler_service._scheduler", mock_sched):
            from backend.services.scheduler_service import init_scheduler
            init_scheduler()

        feed_call = next(
            c for c in mock_sched.add_job.call_args_list
            if c[1]["id"] == "daily_feed"
        )
        trigger   = feed_call[1]["trigger"]  # trigger is a keyword arg
        field_map = {f.name: str(f) for f in trigger.fields}
        assert field_map["hour"]   == "14"
        assert field_map["minute"] == "30"

    def test_maintenance_job_runs_5_minutes_after_feed_job(self, monkeypatch):
        monkeypatch.setenv("SCHEDULER_JOB_HOUR",   "8")
        monkeypatch.setenv("SCHEDULER_JOB_MINUTE", "0")

        mock_sched = self._patched_scheduler()
        with patch("backend.services.scheduler_service._scheduler", mock_sched):
            from backend.services.scheduler_service import init_scheduler
            init_scheduler()

        maint_call = next(
            c for c in mock_sched.add_job.call_args_list
            if c[1]["id"] == "daily_maintenance"
        )
        trigger   = maint_call[1]["trigger"]  # trigger is a keyword arg
        field_map = {f.name: str(f) for f in trigger.fields}
        assert field_map["hour"]   == "8"
        assert field_map["minute"] == "5"

    def test_midnight_maintenance_wraps_correctly(self, monkeypatch):
        """Feed at 23:58 → maintenance at 00:03 (next day), not 24:03."""
        monkeypatch.setenv("SCHEDULER_JOB_HOUR",   "23")
        monkeypatch.setenv("SCHEDULER_JOB_MINUTE", "58")

        mock_sched = self._patched_scheduler()
        with patch("backend.services.scheduler_service._scheduler", mock_sched):
            from backend.services.scheduler_service import init_scheduler
            init_scheduler()

        maint_call = next(
            c for c in mock_sched.add_job.call_args_list
            if c[1]["id"] == "daily_maintenance"
        )
        trigger   = maint_call[1]["trigger"]  # trigger is a keyword arg
        field_map = {f.name: str(f) for f in trigger.fields}
        assert field_map["hour"]   == "0"
        assert field_map["minute"] == "3"


# ═══════════════════════════════════════════════════════════════════════════════
# get_scheduler_status
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetSchedulerStatus:

    def test_returns_correct_shape(self):
        conn = _make_conn_mock(fetchone_return=None)
        mock_sched = MagicMock()
        mock_sched.running = True
        mock_sched.get_jobs.return_value = []

        with (
            patch("backend.services.scheduler_service._scheduler", mock_sched),
            patch("backend.utils.db.get_connection", return_value=conn),
        ):
            from backend.services.scheduler_service import get_scheduler_status
            status = get_scheduler_status()

        assert "running"  in status
        assert "timezone" in status
        assert "jobs"     in status
        assert "last_run" in status

    def test_includes_last_run_from_db(self):
        run_row = {
            "status": "completed", "interests": "AI", "feed_id": 3,
            "error_msg": None, "started_at": "2026-05-15 08:00:00", "finished_at": "2026-05-15 08:01:00",
        }
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__  = MagicMock(return_value=False)
        conn.execute.return_value.fetchone.return_value = run_row

        mock_sched = MagicMock()
        mock_sched.running = True
        mock_sched.get_jobs.return_value = []

        with (
            patch("backend.services.scheduler_service._scheduler", mock_sched),
            patch("backend.utils.db.get_connection", return_value=conn),
        ):
            from backend.services.scheduler_service import get_scheduler_status
            status = get_scheduler_status()

        assert status["last_run"] == run_row

    def test_handles_db_error_gracefully(self):
        mock_sched = MagicMock()
        mock_sched.running = False
        mock_sched.get_jobs.return_value = []

        with (
            patch("backend.services.scheduler_service._scheduler", mock_sched),
            patch("backend.utils.db.get_connection", side_effect=RuntimeError("no db")),
        ):
            from backend.services.scheduler_service import get_scheduler_status
            status = get_scheduler_status()

        # Must return a valid dict even when DB is unavailable
        assert status["last_run"] is None
        assert isinstance(status["jobs"], list)
