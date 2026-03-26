import threading
import time
import json
from sqlalchemy.exc import OperationalError
from scripts.pipeline.logging_config import logger

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

                    job = db.session.query(ProcessingJob).filter_by(status='pending').order_by(ProcessingJob.created_at.asc()).with_for_update(skip_locked=True).first()
                    if job:
                        # Mark running to prevent double processing
                        job.status = 'running'
                        db.session.commit()
                        
                        config_data = json.loads(job.config_data) if job.config_data else {}
                        domain_prompt = job.domain_prompt
                        
                        logger.info(f"Picked up job {job.id} from queue. Submitting to background executor.")
                        executor.submit(
                            run_ontology_background_task,
                            config_data,
                            domain_prompt,
                            job.id
                        )
                    else:
                        time.sleep(5)
            except OperationalError:
                time.sleep(10) # wait for db
            except Exception as e:
                logger.error(f"Task manager encountered error: {e}")
                time.sleep(10)
    
    t = threading.Thread(target=worker, daemon=True)
    t.start()
