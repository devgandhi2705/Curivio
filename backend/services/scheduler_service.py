"""
Scheduler service — APScheduler 3.x backed daily intelligence feed job.

Configuration (all via .env):
  SCHEDULER_JOB_HOUR              UTC hour for the daily job        (default: 8)
  SCHEDULER_JOB_MINUTE            UTC minute for the daily job      (default: 0)
  SCHEDULER_TIMEZONE              IANA timezone for job scheduling   (default: UTC)
  SCHEDULER_DEFAULT_INTERESTS     Fallback when no liked topics yet  (default: "AI and machine learning")
  SCHEDULER_MAX_RETRIES           Extra attempts on transient error  (default: 2)

Usage:
    from backend.services.scheduler_service import init_scheduler, shutdown_scheduler
    init_scheduler()    # call once at app startup
    shutdown_scheduler()  # call at app shutdown
"""

import os
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .recommendation_service import (
    get_top_user_interests,
    get_learning_stage,
    get_overall_difficulty_preference,
)

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler(timezone="UTC")

_MAX_RETRIES  = int(os.getenv("SCHEDULER_MAX_RETRIES",  "2"))
_SCHEDULER_TZ = os.getenv("SCHEDULER_TIMEZONE", "UTC")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _already_ran_today() -> bool:
    """
    Return True if a scheduler run with status 'completed' or 'skipped'
    already exists for today (UTC).  Prevents duplicate feed generation.
    """
    try:
        from ..utils.db import get_connection
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT id FROM scheduler_runs
                WHERE  status IN ('completed', 'skipped')
                AND    DATE(started_at) = ?
                """,
                (today,),
            ).fetchone()
        return row is not None
    except Exception:
        logger.exception("[scheduler] _already_ran_today: DB error — assuming False")
        return False


def _build_interests() -> str:
    """
    Build the interests string from the user's top liked topics.
    Falls back to SCHEDULER_DEFAULT_INTERESTS when no history exists.
    """
    default = os.getenv("SCHEDULER_DEFAULT_INTERESTS", "AI and machine learning")
    try:
        top = get_top_user_interests(limit=5)
        return ", ".join(r["topic"] for r in top) if top else default
    except Exception:
        logger.warning("[scheduler] failed to fetch user interests — using default")
        return default


def _save_run(
    status: str,
    interests: str | None = None,
    feed_id: int | None = None,
    error_msg: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
) -> int | None:
    """Insert a scheduler run record; returns the new row id or None on error."""
    try:
        from ..utils.db import get_connection
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with get_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO scheduler_runs
                    (status, interests, feed_id, error_msg, started_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (status, interests, feed_id, error_msg, started_at or now, finished_at),
            )
        return cur.lastrowid
    except Exception:
        logger.exception("[scheduler] _save_run: DB error (non-fatal)")
        return None


def _update_run(
    run_id: int | None,
    status: str,
    feed_id: int | None = None,
    error_msg: str | None = None,
    finished_at: str | None = None,
) -> None:
    """Update an existing run record with its final status."""
    if run_id is None:
        return
    try:
        from ..utils.db import get_connection
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE scheduler_runs
                SET    status = ?, feed_id = ?, error_msg = ?, finished_at = ?
                WHERE  id = ?
                """,
                (status, feed_id, error_msg, finished_at or now, run_id),
            )
    except Exception:
        logger.exception("[scheduler] _update_run: DB error (non-fatal)")


def _latest_scheduler_feed_id() -> int | None:
    """Return the id of the most recently inserted scheduler-sourced intelligence feed."""
    try:
        from ..utils.db import get_connection
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT id FROM intelligence_feeds
                WHERE  source = 'scheduler'
                ORDER  BY generated_at DESC
                LIMIT  1
                """
            ).fetchone()
        return row["id"] if row else None
    except Exception:
        logger.exception("[scheduler] _latest_scheduler_feed_id: DB error (non-fatal)")
        return None


# ── Scheduled jobs ────────────────────────────────────────────────────────────

async def daily_feed_job() -> None:
    """
    Automated daily intelligence feed generation.

    Guards:
    1. Skips if a scheduler run already completed or was skipped today (UTC).
    2. Builds the interests string from liked topics; falls back to env default.
    3. Retries up to SCHEDULER_MAX_RETRIES times on transient failures.
    4. Persists every run outcome (started → completed / skipped / failed)
       to scheduler_runs for observability.
    """
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    run_id = _save_run("started", started_at=started_at)

    if _already_ran_today():
        logger.info("[scheduler] daily_feed_job skipped — feed already generated today")
        _update_run(run_id, "skipped")
        return

    interests  = _build_interests()
    stage      = get_learning_stage()
    difficulty = get_overall_difficulty_preference()

    logger.info(
        "[scheduler] daily_feed_job started  |  interests: %s  |  stage: %s  |  difficulty: %s",
        interests, stage, difficulty,
    )

    last_error: Exception | None = None
    total_attempts = 1 + _MAX_RETRIES

    for attempt in range(total_attempts):
        try:
            from .intelligence_service import generate_intelligence_feed
            feed = generate_intelligence_feed(interests)

            headline = feed.get("intelligence_brief", {}).get("headline", "(no title)")
            feed_id  = _latest_scheduler_feed_id()

            _update_run(run_id, "completed", feed_id=feed_id)
            logger.info(
                "[scheduler] daily_feed_job completed  |  attempt: %d/%d  |  feed_id: %s  |  headline: %s",
                attempt + 1, total_attempts, feed_id, headline,
            )
            return

        except Exception as exc:
            last_error = exc
            logger.warning(
                "[scheduler] daily_feed_job attempt %d/%d failed: %s",
                attempt + 1, total_attempts, exc,
            )

    error_msg = str(last_error)[:500] if last_error else "unknown"
    _update_run(run_id, "failed", error_msg=error_msg)
    logger.error(
        "[scheduler] daily_feed_job failed after %d attempts: %s",
        total_attempts, error_msg,
    )


async def daily_project_generation_job() -> None:
    """
    Generate a fresh daily intelligence package for every learning project.

    Runs 15 minutes after the main feed job.
    Each project's daily-guard prevents double-generation on re-trigger.
    """
    try:
        from .project_service import generate_all_projects
        summary = generate_all_projects(force=False)
        logger.info(
            "[scheduler] project generation complete | total=%d generated=%d skipped=%d failed=%d",
            summary["total"], summary["generated"], summary["skipped"], summary["failed"],
        )
        if summary["errors"]:
            for err in summary["errors"]:
                logger.warning("[scheduler] project error: %s", err)
    except Exception:
        logger.exception("[scheduler] daily_project_generation_job failed (non-fatal)")


async def daily_maintenance_job() -> None:
    """
    Purge expired feed-cache entries daily.
    Runs 5 minutes after the feed job to avoid contention.
    """
    try:
        from .feed_cache_service import purge_expired
        deleted = purge_expired()
        logger.info("[scheduler] maintenance: purged %d expired cache entries", deleted)
    except Exception:
        logger.exception("[scheduler] maintenance job failed (non-fatal)")


# ── Observability ─────────────────────────────────────────────────────────────

def get_scheduler_status() -> dict:
    """
    Return scheduler state for the /scheduler/status endpoint.

    Shape::

        {
          "running":  bool,
          "timezone": str,
          "jobs": [{"job_id", "name", "next_run", "running"}, ...],
          "last_run": {"status", "interests", "feed_id",
                       "error_msg", "started_at", "finished_at"} | None
        }
    """
    jobs = [
        {
            "job_id":  job.id,
            "name":    job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "running": _scheduler.running,
        }
        for job in _scheduler.get_jobs()
    ]

    last_run: dict | None = None
    try:
        from ..utils.db import get_connection
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT status, interests, feed_id, error_msg, started_at, finished_at
                FROM   scheduler_runs
                ORDER  BY id DESC
                LIMIT  1
                """
            ).fetchone()
        if row:
            last_run = dict(row)
    except Exception:
        logger.exception("[scheduler] get_scheduler_status: DB error (non-fatal)")

    return {
        "running":  _scheduler.running,
        "timezone": _SCHEDULER_TZ,
        "jobs":     jobs,
        "last_run": last_run,
    }


# ── Lifecycle ─────────────────────────────────────────────────────────────────

def init_scheduler() -> AsyncIOScheduler:
    """
    Register the daily feed and maintenance jobs, then start the scheduler.

    Feed job:        SCHEDULER_JOB_HOUR:SCHEDULER_JOB_MINUTE in SCHEDULER_TIMEZONE.
    Maintenance job: 5 minutes after the feed job (wraps at midnight).
    misfire_grace_time=3600: catch up within one hour if the server was offline.
    replace_existing=True: safe to call multiple times (hot-reload, tests).
    """
    if _scheduler.running:
        logger.info("[scheduler] already running — skipping re-init")
        return _scheduler

    hour   = int(os.getenv("SCHEDULER_JOB_HOUR",   "8"))
    minute = int(os.getenv("SCHEDULER_JOB_MINUTE", "0"))
    tz     = _SCHEDULER_TZ

    _scheduler.add_job(
        daily_feed_job,
        trigger=CronTrigger(hour=hour, minute=minute, timezone=tz),
        id="daily_feed",
        name="Daily intelligence feed generation",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Project generation job: 15 minutes after the main feed job
    proj_total   = hour * 60 + minute + 15
    proj_hour    = (proj_total // 60) % 24
    proj_minute  = proj_total % 60

    _scheduler.add_job(
        daily_project_generation_job,
        trigger=CronTrigger(hour=proj_hour, minute=proj_minute, timezone=tz),
        id="daily_project_generation",
        name="Daily project intelligence generation",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Maintenance job: 20 minutes after the main feed job
    total_maint  = hour * 60 + minute + 20
    maint_hour   = (total_maint // 60) % 24
    maint_minute = total_maint % 60

    _scheduler.add_job(
        daily_maintenance_job,
        trigger=CronTrigger(hour=maint_hour, minute=maint_minute, timezone=tz),
        id="daily_maintenance",
        name="Daily cache maintenance",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    _scheduler.start()
    logger.info(
        "[scheduler] Started  |  feed at %02d:%02d %s  |  maintenance at %02d:%02d %s",
        hour, minute, tz, maint_hour, maint_minute, tz,
    )
    return _scheduler


def shutdown_scheduler() -> None:
    """Gracefully stop the scheduler (waits for running jobs to finish)."""
    if _scheduler.running:
        _scheduler.shutdown(wait=True)
        logger.info("[scheduler] Shutdown complete.")
