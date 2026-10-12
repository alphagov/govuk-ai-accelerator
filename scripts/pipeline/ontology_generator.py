from __future__ import annotations


import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from fsspec import AbstractFileSystem
import fsspec
from sqlalchemy import update
from sqlalchemy.exc import OperationalError

from scripts.pipeline.logging_config import log_step, logger
from scripts.pipeline.utils import load_config_for_domain, PipelineConfig

if TYPE_CHECKING:
    from taxonomy_ontology_accelerator.ontology_engine.pipeline_builder import OntologyPipelineBuilder


STOPPED_JOB_STATUS = "stopped"
STOPPED_JOB_MESSAGE = "Manually stopped from Jobs UI"


class JobStoppedError(RuntimeError):
    """Signal that the Workflow stopped a queued ontology-generation job."""

    pass


class JobSupersededError(RuntimeError):
    """Signal that a newer worker attempt now owns the Workflow job."""

    pass


def _with_job_output_path(config_data: dict | None, job_id: str | None) -> dict | None:
    """Copy shared job config before the Generator pipeline consumes it."""
    if config_data is None:
        return None
    return json.loads(json.dumps(config_data))


def _mark_job_progress(job_id: str | None, stage: str) -> None:
    """Record Generator pipeline progress in the Workflow's ProcessingJob row."""
    if not job_id:
        return

    try:
        from govuk_ai_accelerator_app import ProcessingJob, create_flask_app, db

        app = create_flask_app()
        with app.app_context():
            job = db.session.get(ProcessingJob, job_id)
            if job:
                job.last_progress_at = datetime.now(timezone.utc)
                db.session.commit()
        logger.debug(f"[job={job_id}] progress stage={stage}")
    except OperationalError as exc:
        logger.warning(f"[job={job_id}] unable to record progress stage={stage}: {exc}")
    except Exception as exc:
        logger.exception(f"[job={job_id}] error recording progress stage={stage}: {exc}")


def _clear_toa_runtime_caches(job_id: str | None = None) -> None:
    """Clear process-local caches owned by the taxonomy ontology library between jobs."""
    from taxonomy_ontology_accelerator.ontology_engine.storage.cache import clear_caches

    clear_caches()
    logger.debug(f"[job={job_id}] cleared ontology engine runtime caches")


def _raise_if_job_stopped(job_id: str | None) -> None:
    """Stop invoking the Generator when the Workflow marks its job as stopped."""
    if not job_id:
        return

    try:
        from govuk_ai_accelerator_app import ProcessingJob, create_flask_app, db

        app = create_flask_app()
        with app.app_context():
            job = db.session.get(ProcessingJob, job_id)
            if job and job.status == STOPPED_JOB_STATUS:
                raise JobStoppedError(f"Job {job_id} was manually stopped")
    except JobStoppedError:
        raise
    except OperationalError as exc:
        logger.warning(f"[job={job_id}] unable to check stop status: {exc}")
    except Exception as exc:
        logger.exception(f"[job={job_id}] error checking stop status: {exc}")


def _raise_if_superseded(
    job_id: str | None,
    attempt_count: int | None,
    worker_id: str | None = None,
) -> None:
    """Prevent an obsolete Generator worker attempt from continuing or updating job state."""
    if not job_id or attempt_count is None:
        return

    try:
        from govuk_ai_accelerator_app import ProcessingJob, create_flask_app, db

        app = create_flask_app()
        with app.app_context():
            job = db.session.get(ProcessingJob, job_id)
            if job is not None and (job.attempt_count or 0) != attempt_count:
                raise JobSupersededError(
                    f"Job {job_id} superseded: db attempt={job.attempt_count} "
                    f"claimed_by={job.claimed_by}; mine attempt={attempt_count} worker={worker_id}"
                )
    except JobSupersededError:
        raise
    except OperationalError as exc:
        logger.warning(f"[job={job_id}] unable to check supersede status: {exc}")
    except Exception as exc:
        logger.exception(f"[job={job_id}] error checking supersede status: {exc}")


async def run_ontology_pipeline(
    config_data: dict | None = None,
    domain_prompt: str | None = None,
    incremental: bool = False,
    job_id: str | None = None,
    attempt_count: int | None = None,
    worker_id: str | None = None,
) -> str:
    """Run the taxonomy ontology library's builder for a Workflow ontology job.

    Workflow config is converted into the library's ``OntologyConfig`` and
    ``OntologyPipelineBuilder``; this wrapper sequences setup, extraction,
    processing, graph export, and artifact persistence while updating and
    checking Workflow job ownership between stages.
    """
    from taxonomy_ontology_accelerator.ontology_engine.pipeline_builder import (
        OntologyPipelineBuilder,
    )

    _clear_toa_runtime_caches(job_id)

    ontology_config, pipeline_config = load_config_for_domain(config=config_data)
    _mark_job_progress(job_id, "config-loaded")
    _raise_if_job_stopped(job_id)
    _raise_if_superseded(job_id, attempt_count, worker_id)

    logger.info(
        f"[job={job_id}] Generating ontology for domain={pipeline_config.domain_name} worker={worker_id}"
    )

    fs = fsspec.filesystem(ontology_config.filesystem.protocol)

    pipeline = OntologyPipelineBuilder(
        domain=pipeline_config.domain_name,
        config=ontology_config,
        incremental=incremental,
        input_path=pipeline_config.input_path,
        fs=fs,
        domain_prompt=domain_prompt,
    )

    with log_step("Setting up ontology pipeline", "set up ontology pipeline",
                  job=job_id, domain=pipeline_config.domain_name):
        pipeline = _setup_pipeline(pipeline, pipeline_config)
    _mark_job_progress(job_id, "pipeline-setup")
    _raise_if_job_stopped(job_id)
    _raise_if_superseded(job_id, attempt_count, worker_id)

    with log_step("Extracting ontology data", "extracted ontology data",
                  job=job_id, domain=pipeline_config.domain_name):
        pipeline = await _extract_ontology(pipeline)
    _mark_job_progress(job_id, "ontology-extracted")
    _raise_if_job_stopped(job_id)
    _raise_if_superseded(job_id, attempt_count, worker_id)

    with log_step("Processing ontology data", "processed ontology data",
                  job=job_id, domain=pipeline_config.domain_name):
        pipeline = await _process_ontology(pipeline)
    _mark_job_progress(job_id, "ontology-processed")
    _raise_if_job_stopped(job_id)
    _raise_if_superseded(job_id, attempt_count, worker_id)

    with log_step("Creating ontology graph", "created ontology graph",
                  job=job_id, domain=pipeline_config.domain_name):
        pipeline = await _create_ontology_graph(pipeline)
    _mark_job_progress(job_id, "graph-created")
    _raise_if_job_stopped(job_id)
    _raise_if_superseded(job_id, attempt_count, worker_id)

    with log_step("Saving pipeline output", "saved pipeline output",
                  job=job_id, domain=pipeline_config.domain_name):
        await _save_pipeline_output(pipeline, pipeline_config, fs)
    _mark_job_progress(job_id, "artifacts-saved")
    _raise_if_job_stopped(job_id)
    _raise_if_superseded(job_id, attempt_count, worker_id)

    logger.info(
        f"[job={job_id}] Successfully generated ontology for domain={pipeline_config.domain_name} "
        f"worker={worker_id}"
    )
    return str(pipeline.state.output_dir)


def _setup_pipeline(
    pipeline: OntologyPipelineBuilder,
    config: PipelineConfig,
) -> OntologyPipelineBuilder:
    """Apply Workflow paths and prompt settings to the library's pipeline builder."""
    pipeline = pipeline.setup_pipeline(
        input_path=config.input_path,
        output_dir=config.output_dir,
        prompt_path=config.prompt_path,
    )
    if pipeline.state.incremental:
        pipeline.load_existing()
    return pipeline


async def _extract_ontology(pipeline: OntologyPipelineBuilder) -> OntologyPipelineBuilder:
    """Use the library's asynchronous extraction stage to populate ontology data."""
    return await pipeline.extract_async()


async def _process_ontology(pipeline: OntologyPipelineBuilder) -> OntologyPipelineBuilder:
    """Run library deduplication, relationship construction, and schema update stages."""
    pipeline = await pipeline.deduplicate()
    pipeline = await pipeline.build_relations()
    pipeline = await pipeline.update_schema()
    return pipeline


async def _create_ontology_graph(pipeline: OntologyPipelineBuilder) -> OntologyPipelineBuilder:
    """Merge incremental data when needed, then validate, save, and export the ontology."""
    if pipeline.state.incremental:
        pipeline = await pipeline.merge()
    return pipeline.validate().save().export()


async def _save_pipeline_output(
    pipeline: OntologyPipelineBuilder,
    config: PipelineConfig,
    fs: AbstractFileSystem,
) -> None:
    """Finalize and build library outputs, then persist Workflow run metadata."""
    await pipeline.finalize()
    pipeline.build()
    await _save_version_info(config, pipeline.state.output_dir, fs)


def _resolve_run_root(output_dir: str | Path | None, fallback_output_dir: str | None) -> str | Path:
    """Normalize the Generator output path to its containing run directory."""
    if output_dir is not None:
        if isinstance(output_dir, Path):
            return output_dir.parent if output_dir.name == "output" else output_dir

        normalized_output = output_dir.rstrip("/")
        if normalized_output.split("/")[-1] == "output":
            return normalized_output.rsplit("/", 1)[0]
        return normalized_output

    assert fallback_output_dir is not None, "fallback_output_dir must be available"
    return fallback_output_dir


async def _save_version_info(
    config: PipelineConfig,
    output_dir: str | Path | None,
    fs: AbstractFileSystem,
) -> None:
    """Resolve the run root used for library/Workflow version metadata."""
    run_root = _resolve_run_root(output_dir, config.output_dir)
    _ = (run_root, fs)


def _update_job_status(
    job_id: str,
    status: str,
    error_message: str | None = None,
    job_runs: str | None = None,
    clear_lease: bool = False,
) -> None:
    """Update Workflow job state unless a manual stop must remain authoritative."""
    try:
        from govuk_ai_accelerator_app import ProcessingJob, create_flask_app, db

        app = create_flask_app()
        with app.app_context():
            job = db.session.get(ProcessingJob, job_id)
            if job:
                if job.status == STOPPED_JOB_STATUS and status != STOPPED_JOB_STATUS:
                    logger.info(
                        f"[job={job_id}] preserving stopped status; ignoring status={status}"
                    )
                    return
                job.status = status
                if error_message is not None:
                    job.error_message = error_message
                if job_runs is not None:
                    job.job_runs = job_runs
                if clear_lease:
                    job.claimed_by = None
                    job.claimed_at = None
                    job.heartbeat_at = None
                db.session.commit()
        logger.info(f"[job={job_id}] status updated status={status} job_runs={job_runs}")
    except OperationalError as exc:
        logger.warning(f"[job={job_id}] unable to update job status={status}: {exc}")
    except Exception as exc:
        logger.exception(f"[job={job_id}] error updating job status={status}: {exc}")


def _finalize_job_status_if_owner(
    job_id: str,
    status: str,
    attempt_count: int,
    worker_id: str | None = None,
    error_message: str | None = None,
    job_runs: str | None = None,
) -> bool:
    """Finalize job state only if this worker still owns the current attempt."""
    try:
        from govuk_ai_accelerator_app import ProcessingJob, create_flask_app, db

        app = create_flask_app()
        with app.app_context():
            values = {
                "status": status,
                "claimed_by": None,
                "claimed_at": None,
                "heartbeat_at": None,
            }
            if error_message is not None:
                values["error_message"] = error_message
            if job_runs is not None:
                values["job_runs"] = job_runs

            result = db.session.execute(
                update(ProcessingJob)
                .where(
                    ProcessingJob.id == job_id,
                    ProcessingJob.attempt_count == attempt_count,
                    ProcessingJob.status != STOPPED_JOB_STATUS,
                )
                .values(**values)
            )
            db.session.commit()
            applied = (result.rowcount or 0) == 1

        if applied:
            logger.info(
                f"[job={job_id}] status finalized status={status} "
                f"attempt={attempt_count} job_runs={job_runs}"
            )
        else:
            logger.info(
                f"[job={job_id}] finalize skipped (superseded/stopped) "
                f"status={status} attempt={attempt_count} worker={worker_id}"
            )
        return applied
    except OperationalError as exc:
        logger.warning(f"[job={job_id}] unable to finalize status={status}: {exc}")
        return False
    except Exception as exc:
        logger.exception(f"[job={job_id}] error finalizing status={status}: {exc}")
        return False


def _finalize_job_status(
    job_id: str | None,
    status: str,
    attempt_count: int | None = None,
    worker_id: str | None = None,
    error_message: str | None = None,
    job_runs: str | None = None,
) -> None:
    """Choose the Workflow job-finalization path based on whether attempt ownership is tracked."""
    if not job_id:
        return
    if attempt_count is None:
        _update_job_status(
            job_id, status, error_message=error_message, job_runs=job_runs, clear_lease=True
        )
        return
    _finalize_job_status_if_owner(
        job_id,
        status,
        attempt_count,
        worker_id=worker_id,
        error_message=error_message,
        job_runs=job_runs,
    )


def _persist_config_yaml(config: dict, output_dir: str) -> None:
    """Save the Workflow's effective run config beside the Generator artifacts."""
    run_root = _resolve_run_root(output_dir, None)
    config_url = f"{run_root}/config.yaml"
    try:
        fs, fs_path = fsspec.core.url_to_fs(config_url)
        parent = fs._parent(fs_path)
        if parent:
            fs.makedirs(parent, exist_ok=True)
        import yaml as yaml_mod
        with fs.open(fs_path, "w") as f:
            yaml_mod.dump(config, f, default_flow_style=False, sort_keys=False)
        logger.info(f"Persisted config.yaml at {config_url}")
    except Exception as exc:
        logger.warning(f"Could not persist config.yaml: {exc}")


def run_ontology_background_task(
    config: dict,
    domain_prompt: str,
    job_id: str | None = None,
    attempt_count: int | None = None,
    worker_id: str | None = None,
) -> bool:
    """Run a Generator pipeline in a worker thread and finalize its Workflow job.

    This adapter bridges the job manager's synchronous task interface to the
    asynchronous library pipeline, persists the effective config with outputs,
    and maps success, stop, supersession, or failure to Workflow job state.
    """
    try:
        job_config = _with_job_output_path(config, job_id)
        _mark_job_progress(job_id, "execution-started")
        output_dir = asyncio.run(
            run_ontology_pipeline(
                config_data=job_config,
                domain_prompt=domain_prompt,
                job_id=job_id,
                attempt_count=attempt_count,
                worker_id=worker_id,
            )
        )
        logger.debug(f"[job={job_id}] pipeline task completed successfully")

        if output_dir:
            _persist_config_yaml(config, str(output_dir))

        job_runs = None
        if output_dir:
            import re

            match = re.search(r"(run-\d{8}-\d*\/.*)", str(output_dir))
            if match:
                job_runs = match.group(1).rstrip("/")
                if job_runs.endswith("/output"):
                    job_runs = job_runs[:-7]
            elif job_id:
                job_runs = job_id

        _finalize_job_status(job_id, "completed", attempt_count, worker_id, job_runs=job_runs)
        return True
    except JobSupersededError as exc:
        logger.warning(f"[job={job_id}] superseded; abandoning without status write: {exc}")
        return False
    except JobStoppedError as exc:
        logger.info(f"[job={job_id}] pipeline task stopped: {exc}")
        if job_id:
            _update_job_status(
                job_id,
                STOPPED_JOB_STATUS,
                error_message=STOPPED_JOB_MESSAGE,
                clear_lease=True,
            )
        return False
    except Exception as e:
        logger.error(f"[job={job_id}] pipeline task failed error={str(e)}")
        _finalize_job_status(job_id, "failed", attempt_count, worker_id, error_message=str(e))
        raise
