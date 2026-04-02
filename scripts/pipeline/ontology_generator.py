from __future__ import annotations

"""Ontology generation pipeline module."""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from fsspec import AbstractFileSystem
import fsspec
from sqlalchemy.exc import OperationalError

from scripts.pipeline.logging_config import logger
from scripts.pipeline.utils import load_config_for_domain, PipelineConfig

if TYPE_CHECKING:
    from taxonomy_ontology_accelerator.ontology_engine.pipeline_builder import OntologyPipelineBuilder


def _with_job_output_path(config_data: dict | None, job_id: str | None) -> dict | None:
    """Ensure every job writes to a unique run-specific output path."""
    if config_data is None:
        return None

    config_copy = json.loads(json.dumps(config_data))
    path_config = config_copy.setdefault("path", {})

    existing_output_dir = path_config.get("output_dir")
    if not existing_output_dir:
        return config_copy

    normalized = str(existing_output_dir).rstrip("/")
    run_id = job_id or str(uuid4())

    if normalized.endswith("/output"):
        normalized = normalized[:-7]

    if run_id in normalized:
        path_config["output_dir"] = f"{normalized}/output"
        return config_copy

    path_config["output_dir"] = f"{normalized}/{run_id}/output"
    return config_copy


def _mark_job_progress(job_id: str | None, stage: str) -> None:
    """Record real pipeline progress so stale detection reflects actual work."""
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
        logger.info(f"[job={job_id}] progress stage={stage}")
    except OperationalError as exc:
        logger.warning(f"[job={job_id}] unable to record progress stage={stage}: {exc}")
    except Exception as exc:
        logger.exception(f"[job={job_id}] error recording progress stage={stage}: {exc}")


async def run_ontology_pipeline(
    config_data: dict | None = None,
    domain_prompt: str | None = None,
    incremental: bool = False,
    job_id: str | None = None,
) -> str:
    """Run the ontology generation pipeline asynchronously."""
    from taxonomy_ontology_accelerator.ontology_engine.pipeline_builder import (
        OntologyPipelineBuilder,
    )

    ontology_config, pipeline_config = load_config_for_domain(config=config_data)
    _mark_job_progress(job_id, "config-loaded")

    logger.info(
        f"[job={job_id}] starting ontology pipeline domain={pipeline_config.domain_name}"
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

    pipeline = _setup_pipeline(pipeline, pipeline_config)
    _mark_job_progress(job_id, "pipeline-setup")

    pipeline = await _extract_ontology(pipeline)
    _mark_job_progress(job_id, "ontology-extracted")

    pipeline = await _process_ontology(pipeline)
    _mark_job_progress(job_id, "ontology-processed")

    pipeline = await _create_ontology_graph(pipeline)
    _mark_job_progress(job_id, "graph-created")

    await _save_pipeline_output(pipeline, pipeline_config, fs)
    _mark_job_progress(job_id, "artifacts-saved")

    logger.info(
        f"[job={job_id}] ontology pipeline completed domain={pipeline_config.domain_name}"
    )
    return str(pipeline.state.output_dir)


def _setup_pipeline(
    pipeline: OntologyPipelineBuilder,
    config: PipelineConfig,
) -> OntologyPipelineBuilder:
    """Setup the ontology pipeline with configuration and load existing data."""
    logger.info("Setting up ontology pipeline")
    pipeline = pipeline.setup_pipeline(
        input_path=config.input_path,
        output_dir=config.output_dir,
        prompt_path=config.prompt_path,
    )
    if pipeline.state.incremental:
        pipeline.load_existing()
    return pipeline


async def _extract_ontology(pipeline: OntologyPipelineBuilder) -> OntologyPipelineBuilder:
    """Extract ontology data from input sources."""
    logger.info("Extracting ontology data")
    return await pipeline.extract_async()


async def _process_ontology(pipeline: OntologyPipelineBuilder) -> OntologyPipelineBuilder:
    """Process extracted ontology data."""
    logger.info("Processing ontology data")
    pipeline = await pipeline.deduplicate()
    pipeline = await pipeline.build_relations()
    pipeline = await pipeline.update_schema()
    return pipeline


async def _create_ontology_graph(pipeline: OntologyPipelineBuilder) -> OntologyPipelineBuilder:
    """Create and validate the ontology graph."""
    logger.info("Creating ontology graph")
    if pipeline.state.incremental:
        pipeline = await pipeline.merge()
    return pipeline.validate().save().export()


async def _save_pipeline_output(
    pipeline: OntologyPipelineBuilder,
    config: PipelineConfig,
    fs: AbstractFileSystem,
) -> None:
    """Save pipeline output and version information."""
    logger.info("Saving pipeline output")
    await pipeline.finalize()
    await _save_version_info(config, pipeline.state.output_dir, fs)


def _resolve_run_root(output_dir: str | Path | None, fallback_output_dir: str | None) -> str | Path:
    """Resolve the run root directory from a finalized output path."""
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
    """Save version metadata to the output directory."""
    run_root = _resolve_run_root(output_dir, config.output_dir)
    _ = (run_root, fs)


def _update_job_status(
    job_id: str,
    status: str,
    error_message: str | None = None,
    job_runs: str | None = None,
    clear_lease: bool = False,
) -> None:
    """Update the processing job status in the database."""
    try:
        from govuk_ai_accelerator_app import ProcessingJob, create_flask_app, db

        app = create_flask_app()
        with app.app_context():
            job = db.session.get(ProcessingJob, job_id)
            if job:
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


def run_ontology_background_task(config: dict, domain_prompt: str, job_id: str | None = None) -> bool:
    """Run the ontology pipeline as a background task, updating job status if provided."""
    try:
        job_config = _with_job_output_path(config, job_id)
        _mark_job_progress(job_id, "execution-started")
        output_dir = asyncio.run(
            run_ontology_pipeline(
                config_data=job_config,
                domain_prompt=domain_prompt,
                job_id=job_id,
            )
        )
        logger.info(f"[job={job_id}] pipeline task completed successfully")

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

        if job_id:
            _update_job_status(job_id, "completed", job_runs=job_runs, clear_lease=True)
        return True
    except Exception as e:
        logger.error(f"[job={job_id}] pipeline task failed error={str(e)}")
        if job_id:
            _update_job_status(job_id, "failed", error_message=str(e), clear_lease=True)
        raise
