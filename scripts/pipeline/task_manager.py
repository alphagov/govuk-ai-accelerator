import json
import os
import socket
import threading
import time
from concurrent.futures import CancelledError
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, text
from sqlalchemy.exc import OperationalError

from scripts.pipeline.constants import EXECUTOR_MAX_WORKERS
from scripts.pipeline.logging_config import logger


PROGRESS_TIMEOUT = timedelta(minutes=10)
IDLE_POLL_INTERVAL_SECONDS = 5
LEADER_LOCK_ID = 420021


def _worker_id() -> str:
    return os.getenv("HOSTNAME") or socket.gethostname()


def _uses_postgres(db) -> bool:
    return db.engine.url.get_backend_name().startswith("postgresql")


def _try_acquire_leader_connection(db):
    """Acquire a dedicated Postgres advisory lock connection for the queue leader."""
    if not _uses_postgres(db):
        logger.info("[queue] sqlite mode detected; treating this pod as leader")
        return True

    connection = db.engine.connect()
    acquired = connection.execute(
        text("SELECT pg_try_advisory_lock(:lock_id)"),
        {"lock_id": LEADER_LOCK_ID},
    ).scalar()

    if acquired:
        logger.info(f"[queue] advisory lock {LEADER_LOCK_ID} acquired")
        return connection

    connection.close()
    logger.info(f"[queue] advisory lock {LEADER_LOCK_ID} not acquired")
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
        logger.info(f"[queue] advisory lock {LEADER_LOCK_ID} released")
    except Exception:
        pass
    finally:
        connection.close()



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
                    f"[job={job.id}] marking 24h stale job as failed "
                    f"status={job.status} domain={job.domain} created_at={job.created_at}"
                )
                job.status = "failed"
                job.error_message = "Job timed out after 24 hours"
                job.claimed_by = None
                job.claimed_at = None
                job.heartbeat_at = None

            if stale_jobs:
                db.session.commit()
                logger.info(f"[queue] cleaned up {len(stale_jobs)} stale jobs")
        except Exception as exc:
            logger.error(f"[queue] error during stale jobs cleanup: {exc}")
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
                    f"[job={job.id}] requeueing stale job "
                    f"domain={job.domain} worker={job.claimed_by} "
                    f"claimed_at={job.claimed_at} last_progress_at={job.last_progress_at} "
                    f"attempt={job.attempt_count}"
                )
                job.status = "pending"
                job.claimed_by = None
                job.claimed_at = None
                job.heartbeat_at = None
                job.error_message = "Job progress timed out; requeued."

            if stale_jobs:
                db.session.commit()
                logger.info(f"[queue] recovered {len(stale_jobs)} stale running jobs")
        except Exception as exc:
            logger.error(f"[queue] error recovering stale running jobs: {exc}")
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
        f"[job={job.id}] claimed domain={job.domain} worker={worker_id} "
        f"attempt={job.attempt_count} claimed_at={job.claimed_at}"
    )

    return {
        "job_id": job.id,
        "domain": job.domain,
        "config_data": json.loads(job.config_data) if job.config_data else {},
        "domain_prompt": job.domain_prompt,
        "attempt_count": job.attempt_count,
    }


def requeue_claimed_job(db, job_model, job_id: str, error_message: str | None = None):
    """Return a claimed job to pending if submission fails before execution starts."""
    job = db.session.get(job_model, job_id)
    if job is None:
        return

    logger.info(f"[job={job_id}] requeueing after executor submission failure")
    job.status = "pending"
    job.claimed_by = None
    job.claimed_at = None
    job.heartbeat_at = None
    if error_message is not None:
        job.error_message = error_message
    db.session.commit()


def mark_job_failed_if_still_running(db, job_model, job_id: str, error_message: str) -> bool:
    """Mark a job failed after worker failure, unless another path already finalized it."""
    job = db.session.get(job_model, job_id)
    if job is None or job.status != "running":
        return False

    logger.info(f"[job={job_id}] marking running job as failed after worker failure")
    job.status = "failed"
    job.error_message = error_message
    job.claimed_by = None
    job.claimed_at = None
    job.heartbeat_at = None
    db.session.commit()
    return True


def run_claimed_job(app, worker_id: str, claimed_job: dict):
    """Run a claimed job without a synthetic heartbeat thread."""
    from scripts.pipeline.ontology_generator import run_ontology_background_task

    logger.info(
        f"[job={claimed_job['job_id']}] execution starting "
        f"worker={worker_id} domain={claimed_job['domain']} attempt={claimed_job['attempt_count']}"
    )
    run_ontology_background_task(
        claimed_job["config_data"],
        claimed_job["domain_prompt"],
        claimed_job["job_id"],
    )
    logger.info(
        f"[job={claimed_job['job_id']}] execution returned "
        f"worker={worker_id} domain={claimed_job['domain']}"
    )


def handle_finished_job_future(app, worker_id: str, claimed_job: dict, future) -> None:
    """Persist a terminal failure if the worker future failed before updating the job row."""
    try:
        exception = future.exception()
    except CancelledError as exc:
        exception = exc

    if exception is None:
        return

    job_id = claimed_job["job_id"]
    logger.error(
        f"[job={job_id}] worker future failed worker={worker_id} "
        f"domain={claimed_job['domain']} error={exception}"
    )

    with app.app_context():
        from govuk_ai_accelerator_app import ProcessingJob, db

        try:
            mark_job_failed_if_still_running(
                db=db,
                job_model=ProcessingJob,
                job_id=job_id,
                error_message=f"Pipeline task failed: {exception}",
            )
        except Exception as exc:
            db.session.rollback()
            logger.error(f"[job={job_id}] failed to persist worker failure: {exc}")


def _try_run_maintenance(app, db):
    """Run stale-job recovery and cleanup if this pod can acquire the advisory lock."""
    connection = _try_acquire_leader_connection(db)
    if connection is None:
        return

    try:
        recover_stale_running_jobs(app)
        cleanup_stale_jobs(app)
    finally:
        _release_leader_connection(connection)


def start_task_manager(app):
    """Start a background daemon thread that polls the database for pending jobs."""

    def worker():
        from scripts.pipeline.utils import executor

        worker_id = _worker_id()
        slots = threading.BoundedSemaphore(EXECUTOR_MAX_WORKERS)
        last_cleanup = 0.0
        cleanup_interval = 60

        logger.info(
            f"[queue] task manager thread started worker={worker_id} max_workers={EXECUTOR_MAX_WORKERS}"
        )

        while True:
            try:
                if time.time() - last_cleanup > cleanup_interval:
                    with app.app_context():
                        from govuk_ai_accelerator_app import db

                        _try_run_maintenance(app, db)
                    last_cleanup = time.time()

                if not slots.acquire(blocking=False):
                    logger.info(f"[queue] no free worker slots on worker={worker_id}")
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

                def _release_slot(_future):
                    handle_finished_job_future(app, worker_id, claimed_job, _future)
                    logger.info(
                        f"[job={claimed_job['job_id']}] releasing worker slot on worker={worker_id}"
                    )
                    slots.release()

                future.add_done_callback(_release_slot)

            except OperationalError:
                time.sleep(5)
            except Exception as exc:
                logger.error(f"[queue] task manager encountered error: {exc}")
                time.sleep(5)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
