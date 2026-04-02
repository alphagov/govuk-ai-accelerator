import threading
import time
import json
from sqlalchemy.exc import OperationalError
from scripts.pipeline.logging_config import logger
from scripts.pipeline.constants import EXECUTOR_MAX_WORKERS

from datetime import datetime, timedelta, timezone

def cleanup_stale_jobs(app):
    """Mark jobs older than 24 hours as failed if they are still in non-terminal states."""
    with app.app_context():
        from govuk_ai_accelerator_app import db, ProcessingJob
        
        stale_threshold = datetime.now(timezone.utc) - timedelta(hours=24)
        
        try:
            stale_jobs = db.session.query(ProcessingJob).filter(
                ProcessingJob.status.in_(['pending', 'running']),
                ProcessingJob.created_at < stale_threshold
            ).all()
            
            for job in stale_jobs:
                logger.info(f"Marking stale job {job.id} (created at {job.created_at}) as failed.")
                job.status = 'failed'
                job.error_message = "Job timed out after 24 hours"
            
            if stale_jobs:
                db.session.commit()
                logger.info(f"Cleaned up {len(stale_jobs)} stale jobs.")
        except Exception as e:
            logger.error(f"Error during stale jobs cleanup: {e}")
            db.session.rollback()


def claim_next_pending_job(db, job_model, max_running_jobs=EXECUTOR_MAX_WORKERS):
    """Claim the oldest pending job only when executor capacity is available."""
    running_jobs = db.session.query(job_model).filter_by(status='running').count()
    if running_jobs >= max_running_jobs:
        return None

    job = (
        db.session.query(job_model)
        .filter_by(status='pending')
        .order_by(job_model.created_at.asc())
        .with_for_update(skip_locked=True)
        .first()
    )
    if job is None:
        return None

    job.status = 'running'
    db.session.commit()

    return {
        "job_id": job.id,
        "config_data": json.loads(job.config_data) if job.config_data else {},
        "domain_prompt": job.domain_prompt,
    }


def return_job_to_pending(db, job_model, job_id, error_message=None):
    """Return a claimed job to pending if it could not be submitted for execution."""
    job = db.session.get(job_model, job_id)
    if job is None:
        return

    job.status = 'pending'
    if error_message is not None:
        job.error_message = error_message
    db.session.commit()

def start_task_manager(app):
    """Start a background daemon thread that polls the database for pending jobs."""
    def worker():
        with app.app_context():
            from govuk_ai_accelerator_app import db, ProcessingJob
            from scripts.pipeline.utils import executor
            from scripts.pipeline.ontology_generator import run_ontology_background_task

            # Basic crash recovery: reset stuck 'running' jobs to 'pending' on startup
            try:
                running_jobs = db.session.query(ProcessingJob).filter_by(status='running').all()
                for job in running_jobs:
                    job.status = 'pending'
                if running_jobs:
                    db.session.commit()
                    logger.info(f"Recovered {len(running_jobs)} stuck jobs to pending state.")
            except OperationalError:
                pass # db not ready yet
            except Exception as e:
                logger.error(f"Error recovering running jobs: {e}")

            # Initial stale job cleanup
            cleanup_stale_jobs(app)

        last_cleanup = time.time()
        cleanup_interval = 900 # 15 minutes

        while True:
            try:
                # Periodic stale job cleanup
                if time.time() - last_cleanup > cleanup_interval:
                    cleanup_stale_jobs(app)
                    last_cleanup = time.time()

                with app.app_context():
                    from govuk_ai_accelerator_app import db, ProcessingJob
                    from scripts.pipeline.utils import executor
                    from scripts.pipeline.ontology_generator import run_ontology_background_task

                    claimed_job = claim_next_pending_job(
                        db=db,
                        job_model=ProcessingJob,
                    )
                    if claimed_job:
                        logger.info(
                            "Picked up job %s from queue. Submitting to background executor.",
                            claimed_job["job_id"],
                        )
                        try:
                            executor.submit(
                                run_ontology_background_task,
                                claimed_job["config_data"],
                                claimed_job["domain_prompt"],
                                claimed_job["job_id"],
                            )
                        except Exception as exc:
                            logger.error(
                                "Failed to submit job %s to background executor: %s",
                                claimed_job["job_id"],
                                exc,
                            )
                            return_job_to_pending(
                                db=db,
                                job_model=ProcessingJob,
                                job_id=claimed_job["job_id"],
                                error_message=None,
                            )
                            raise
                    else:
                        time.sleep(5)
            except OperationalError:
                time.sleep(10) # wait for db
            except Exception as e:
                logger.error(f"Task manager encountered error: {e}")
                time.sleep(10)
    
    t = threading.Thread(target=worker, daemon=True)
    t.start()
