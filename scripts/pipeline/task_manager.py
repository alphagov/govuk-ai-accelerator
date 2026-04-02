import json
import os
import socket
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_
from sqlalchemy.exc import OperationalError

from scripts.pipeline.constants import EXECUTOR_MAX_WORKERS
from scripts.pipeline.logging_config import logger


LEASE_TIMEOUT = timedelta(minutes=10)
HEARTBEAT_INTERVAL_SECONDS = 30
IDLE_POLL_INTERVAL_SECONDS = 5


def _worker_id() -> str:
    return os.getenv("HOSTNAME") or socket.gethostname()


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
            logger.error("Error during stale jobs cleanup: %s", exc)
            db.session.rollback()


def recover_stale_running_jobs(app):
    """Requeue running jobs whose lease has expired."""
    with app.app_context():
        from govuk_ai_accelerator_app import ProcessingJob, db

        cutoff = datetime.now(timezone.utc) - LEASE_TIMEOUT

        try:
            stale_jobs = db.session.query(ProcessingJob).filter(
                ProcessingJob.status == "running",
                or_(
                    ProcessingJob.heartbeat_at < cutoff,
                    and_(
                        ProcessingJob.heartbeat_at.is_(None),
                        ProcessingJob.claimed_at < cutoff,
                    ),
                    and_(
                        ProcessingJob.heartbeat_at.is_(None),
                        ProcessingJob.claimed_at.is_(None),
                    ),
                ),
            ).all()

            for job in stale_jobs:
                logger.info(f"Requeuing stale leased job {job.id}.")
                job.status = "pending"
                job.claimed_by = None
                job.claimed_at = None
                job.heartbeat_at = None
                job.error_message = "Job lease expired; requeued."

            if stale_jobs:
                db.session.commit()
                logger.info(f"Recovered {len(stale_jobs)} stale running jobs.")
        except Exception as exc:
            logger.error("Error recovering stale running jobs: %s", exc)
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
    job.heartbeat_at = now
    job.attempt_count = (job.attempt_count or 0) + 1
    job.error_message = None
    db.session.commit()

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


def touch_job_heartbeat(app, job_id: str, worker_id: str):
    """Refresh the heartbeat for a running job claimed by this worker."""
    with app.app_context():
        from govuk_ai_accelerator_app import ProcessingJob, db

        try:
            job = db.session.get(ProcessingJob, job_id)
            if job and job.status == "running" and job.claimed_by == worker_id:
                job.heartbeat_at = datetime.now(timezone.utc)
                db.session.commit()
        except Exception as exc:
            logger.warning(f"Failed to heartbeat job {job_id}: {exc}")
            db.session.rollback()


def heartbeat_loop(app, job_id: str, worker_id: str, stop_event: threading.Event):
    """Background loop that periodically refreshes a job lease heartbeat."""
    while not stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
        touch_job_heartbeat(app, job_id, worker_id)


def run_claimed_job(app, worker_id: str, claimed_job: dict):
    """Run a claimed job while a background thread keeps its lease alive."""
    from scripts.pipeline.ontology_generator import run_ontology_background_task

    stop_event = threading.Event()
    heartbeat_thread = threading.Thread(
        target=heartbeat_loop,
        args=(app, claimed_job["job_id"], worker_id, stop_event),
        daemon=True,
    )
    heartbeat_thread.start()

    try:
        run_ontology_background_task(
            claimed_job["config_data"],
            claimed_job["domain_prompt"],
            claimed_job["job_id"],
        )
    finally:
        stop_event.set()
        heartbeat_thread.join(timeout=1)


def start_task_manager(app):
    """Start a background daemon thread that polls the database for pending jobs."""

    def worker():
        from scripts.pipeline.utils import executor

        worker_id = _worker_id()
        slots = threading.BoundedSemaphore(EXECUTOR_MAX_WORKERS)
        last_cleanup = 0.0
        cleanup_interval = 60

        while True:
            try:
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

                logger.info(
                    f"Worker {worker_id} claimed job {claimed_job['job_id']}."
                )

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
                time.sleep(5)
            except Exception as exc:
                logger.error(f"Task manager encountered error: {exc}")
                time.sleep(5)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
