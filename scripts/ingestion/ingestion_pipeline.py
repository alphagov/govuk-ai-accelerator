import os
import logging
import fsspec
import shutil
import io
from datetime import datetime, timezone
from scripts.ingestion.commands.utils import load_config, get_logger
from scripts.ingestion.commands import download_content, extract_content, clean_content

def run_ingestion_background_task(config_path: str = None, config_content: str = None, links_list: list[str] = None, job_id: str = None, domain: str = None):

    from govuk_ai_accelerator_app import db, ProcessingJob, create_flask_app

    app = create_flask_app()

    print(f"DEBUG: Starting ingestion job {job_id} (domain={domain})")

    with app.app_context():
        if job_id:
            try:
                job = db.session.get(ProcessingJob, job_id)
                if job:
                    job.status = "running"
                    db.session.commit()
            except Exception as e:
                db.session.rollback()
                logging.warning(f"Could not update status for job {job_id}: {e}")

        config_obj = None
        try:
            config_obj = load_config(config_path=config_path, config_content=config_content, links_list=links_list, domain=domain)
            
            log_buffer = io.StringIO()
            logger = get_logger(stream=log_buffer)
            logger.info(f"🚀 Starting ingestion pipeline for job {job_id or 'manual'}")
            
            download_content(config_obj)
            
            extract_content(config_obj)
            
            clean_content(config_obj)
            
            if job_id:
                try:
                    job = db.session.get(ProcessingJob, job_id)
                    if job:
                        job.status = "completed"
                        db.session.commit()
                        logger.info(f"✅ Ingestion job {job_id} completed successfully")
                except Exception as e:
                    db.session.rollback()
                    logging.warning(f"Could not update status for job {job_id}: {e}")
                   
        except Exception as e:
            error_msg = str(e)
            logger = get_logger() # fallback if config_obj failed
            logger.error(f"❌ Ingestion job {job_id or 'unknown'} failed: {error_msg}")
            if job_id:
                try:
                    job = db.session.get(ProcessingJob, job_id)
                    if job:
                        job.status = "failed"
                        job.error_message = error_msg
                        db.session.commit()
                except Exception as db_err:
                    db.session.rollback()
                    logging.warning(f"Could not update status for job {job_id}: {db_err}")
        finally:
            if config_obj:
                try:
                    final_url = config_obj.final_log_url
                    print(f"DEBUG: Finalizing log to {final_url}")
                    
                    fs, fs_path = fsspec.core.url_to_fs(final_url)
                    
                    parent = fs._parent(fs_path)
                    if parent:
                        fs.makedirs(parent, exist_ok=True)
                        
                    with fs.open(fs_path, 'w') as remote_f:
                        remote_f.write(log_buffer.getvalue())
                            
                except Exception as log_err:
                    print(f"Error finalizing log file: {log_err}")
