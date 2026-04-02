import json
import os
import socket
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, text
from sqlalchemy.exc import OperationalError

from scripts.pipeline.constants import EXECUTOR_MAX_WORKERS
from scripts.pipeline.logging_config import logger


PROGRESS_TIMEOUT = timedelta(minutes=10)
IDLE_POLL_INTERVAL_SECONDS = 5
LEADER_RETRY_INTERVAL_SECONDS = 5
LEADER_LOCK_ID = 420021


def _worker_id() -> str:
    return os.getenv("HOSTNAME") or socket.gethostname()


def _uses_postgres(db) -> bool:
    return db.engine.url.get_backend_name().startswith("postgresql")


def _try_acquire_leader_connection(db):
    """Acquire a dedicated Postgres advisory lock connection for the queue leader."""
    if not _uses_postgres(db):
        return True

    connection = db.engine.connect()
    acquired = connection.execute(
        text("SELECT pg_try_advisory_lock(:lock_id)"),
        {"lock_id": LEADER_LOCK_ID},
    ).scalar()

    if acquired:
        logger.info(f"Queue leadership acquired with advisory lock {LEADER_LOCK_ID}.")
        return connection

    connection.close()
    return None


def _release_leader_connection(connection):
    """Release the dedicated advisory lock connection."""
    if connection is None or connection is True:
        return

    try:
        connection.execute(
            text("SELECT pg_advisory_unlock(:lock_id)"),
            {"lock_id": LEADER_LOCK_ID},
        )
    except Exception:
        pass
    finally:
        connection.close()


def _leader_connection_is_healthy(connection) -> bool:
    if connection is None:
        return False
    if connection is True:
        return True

    try:
        connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def cleanup_stale_jobs(app):
    """Mark jobs older than 24 hours as failed if they are still in non-terminal states."""
    with app.app_context():
        from govuk_ai_accelerator_app import ProcessingJob, db

        stale_threshold = datetime.now(timezone.utc) - timedelta(hours=24)

        try:
            stale_jobs = db.session.query(ProcessingJob).filter(
                ProcessingJob.status.in_(["pending", "running"]),
                ProcessingJob.created_at < stale_threshold,
            ).all()

            for job in stale_jobs:
                logger.info(
                    f"Marking stale job {job.id} (created at {job.created_at}) as failed."
                )
                job.status = "failed"
                job.error_message = "Job timed out after 24 hours"
                job.claimed_by = None
                job.claimed_at = None
                job.heartbeat_at = None

            if stale_jobs:
                db.session.commit()
                logger.info(f"Cleaned up {len(stale_jobs)} stale jobs.")
        except Exception as exc:
            logger.error(f"Error during stale jobs cleanup: {exc}")
            db.session.rollback()


def recover_stale_running_jobs(app):
    """Requeue running jobs whose last real progress has expired."""
    with app.app_context():
        from govuk_ai_accelerator_app import ProcessingJob, db

        cutoff = datetime.now(timezone.utc) - PROGRESS_TIMEOUT

        try:
            stale_jobs = db.session.query(ProcessingJob).filter(
                ProcessingJob.status == "running",
                or_(
                    ProcessingJob.last_progress_at < cutoff,
                    and_(
                        ProcessingJob.last_progress_at.is_(None),
                        ProcessingJob.claimed_at < cutoff,
                    ),
                    and_(
                        ProcessingJob.last_progress_at.is_(None),
                        ProcessingJob.claimed_at.is_(None),
                    ),
                ),
            ).all()

            for job in stale_jobs:
                logger.info(
                    f"Requeuing stale progress job {job.id}. "
                    f"claimed_by={job.claimed_by} claimed_at={job.claimed_at} "
                    f"last_progress_at={job.last_progress_at}"
                )
                job.status = "pending"
                job.claimed_by = None
                job.claimed_at = None
                job.heartbeat_at = None
                job.error_message = "Job progress timed out; requeued."

            if stale_jobs:
                db.session.commit()
                logger.info(f"Recovered {len(stale_jobs)} stale running jobs.")
        except Exception as exc:
            logger.error(f"Error recovering stale running jobs: {exc}")
            db.session.rollback()


def claim_next_pending_job(db, job_model, worker_id: str):
    """Claim the oldest pending job using a DB-backed lease."""
    job = (
        db.session.query(job_model)
        .filter_by(status="pending")
        .order_by(job_model.created_at.asc())
        .with_for_update(skip_locked=True)
        .first()
    )
    if job is None:
        return None

    now = datetime.now(timezone.utc)
    job.status = "running"
    job.claimed_by = worker_id
    job.claimed_at = now
    job.heartbeat_at = None
    job.last_progress_at = now
    job.attempt_count = (job.attempt_count or 0) + 1
    job.error_message = None
    db.session.commit()

    logger.info(
        f"[job={job.id}] claimed by worker={worker_id} "
        f"attempt={job.attempt_count} claimed_at={job.claimed_at}"
    )

    return {
        "job_id": job.id,
        "config_data": json.loads(job.config_data) if job.config_data else {},
        "domain_prompt": job.domain_prompt,
    }


def requeue_claimed_job(db, job_model, job_id: str, error_message: str | None = None):
    """Return a claimed job to pending if submission fails before execution starts."""
    job = db.session.get(job_model, job_id)
    if job is None:
        return

    job.status = "pending"
    job.claimed_by = None
    job.claimed_at = None
    job.heartbeat_at = None
    if error_message is not None:
        job.error_message = error_message
    db.session.commit()


def run_claimed_job(app, worker_id: str, claimed_job: dict):
    """Run a claimed job without a synthetic heartbeat thread."""
    from scripts.pipeline.ontology_generator import run_ontology_background_task

    logger.info(f"[job={claimed_job['job_id']}] starting execution on worker={worker_id}")
    run_ontology_background_task(
        claimed_job["config_data"],
        claimed_job["domain_prompt"],
        claimed_job["job_id"],
    )


def start_task_manager(app):
    """Start a background daemon thread that polls the database for pending jobs."""

    def worker():
        from scripts.pipeline.utils import executor

        worker_id = _worker_id()
        slots = threading.BoundedSemaphore(EXECUTOR_MAX_WORKERS)
        last_cleanup = 0.0
        cleanup_interval = 60
        leader_connection = None

        while True:
            try:
                with app.app_context():
                    from govuk_ai_accelerator_app import db

                    if not _leader_connection_is_healthy(leader_connection):
                        if leader_connection not in (None, True):
                            _release_leader_connection(leader_connection)
                        leader_connection = _try_acquire_leader_connection(db)

                if leader_connection is None:
                    time.sleep(LEADER_RETRY_INTERVAL_SECONDS)
                    continue

                if time.time() - last_cleanup > cleanup_interval:
                    recover_stale_running_jobs(app)
                    cleanup_stale_jobs(app)
                    last_cleanup = time.time()

                if not slots.acquire(blocking=False):
                    time.sleep(1)
                    continue

                with app.app_context():
                    from govuk_ai_accelerator_app import ProcessingJob, db

                    claimed_job = claim_next_pending_job(
                        db=db,
                        job_model=ProcessingJob,
                        worker_id=worker_id,
                    )

                if claimed_job is None:
                    slots.release()
                    time.sleep(IDLE_POLL_INTERVAL_SECONDS)
                    continue

                try:
                    future = executor.submit(run_claimed_job, app, worker_id, claimed_job)
                except Exception as exc:
                    with app.app_context():
                        from govuk_ai_accelerator_app import ProcessingJob, db

                        requeue_claimed_job(
                            db=db,
                            job_model=ProcessingJob,
                            job_id=claimed_job["job_id"],
                            error_message=f"Executor submission failed: {exc}",
                        )
                    slots.release()
                    raise

                future.add_done_callback(lambda _future: slots.release())

            except OperationalError:
                if leader_connection not in (None, True):
                    _release_leader_connection(leader_connection)
                leader_connection = None
                time.sleep(5)
            except Exception as exc:
                logger.error(f"Task manager encountered error: {exc}")
                time.sleep(5)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
