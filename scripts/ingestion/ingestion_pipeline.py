import os
import fsspec
import shutil
import io
from datetime import datetime, timezone
from scripts.ingestion.commands.utils import load_config, get_logger
from scripts.ingestion.commands import download_content, clean_content
from scripts.pipeline.logging_config import logger

def run_ingestion_background_task(config_path: str = None, config_content: str = None, links_list: list[str] = None, job_id: str = None, domain: str = None):

    from govuk_ai_accelerator_app import db, ProcessingJob, create_flask_app

    app = create_flask_app()

    logger.info(f"[job={job_id}] Running ingestion pipeline domain={domain}")

    with app.app_context():
        if job_id:
            try:
                job = db.session.get(ProcessingJob, job_id)
                if job:
                    job.status = "running"
                    db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.warning(f"[job={job_id}] unable to set running status domain={domain}: {e}")

        config_obj = None
        try:
            config_obj = load_config(config_path=config_path, config_content=config_content, links_list=links_list, domain=domain)

            log_buffer = io.StringIO()
            run_log = get_logger(stream=log_buffer)
            run_log.info(f"Starting ingestion pipeline for job {job_id or 'manual'}")

            download_content(config_obj)
            clean_content(config_obj)

            if job_id:
                try:
                    job = db.session.get(ProcessingJob, job_id)
                    if job:
                        job.status = "completed"
                        db.session.commit()
                        run_log.info(f"Ingestion job {job_id} completed successfully")
                except Exception as e:
                    db.session.rollback()
                    logger.warning(f"[job={job_id}] unable to set completed status domain={domain}: {e}")

            logger.info(f"[job={job_id}] Successfully ran ingestion pipeline domain={domain}")

        except Exception as e:
            error_msg = str(e)
            run_log = get_logger()
            run_log.error(f"Ingestion job {job_id or 'unknown'} failed: {error_msg}")
            logger.error(f"[job={job_id}] Error running ingestion pipeline domain={domain}: {error_msg}")
            if job_id:
                try:
                    job = db.session.get(ProcessingJob, job_id)
                    if job:
                        job.status = "failed"
                        job.error_message = error_msg
                        db.session.commit()
                except Exception as db_err:
                    db.session.rollback()
                    logger.warning(f"[job={job_id}] unable to set failed status domain={domain}: {db_err}")
        finally:
            if config_obj and getattr(config_obj, "final_log_url", None):
                try:
                    final_url = config_obj.final_log_url
                    logger.debug(f"[job={job_id}] finalizing ingestion log to {final_url}")

                    fs, fs_path = fsspec.core.url_to_fs(final_url)
                    parent = fs._parent(fs_path)
                    if parent:
                        fs.makedirs(parent, exist_ok=True)
                    with fs.open(fs_path, 'w') as remote_f:
                        remote_f.write(log_buffer.getvalue())
                except Exception as log_err:
                    logger.error(f"[job={job_id}] error finalizing ingestion log file: {log_err}")
