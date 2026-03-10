from __future__ import annotations

"""Ontology generation pipeline module."""

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, cast
from fsspec import AbstractFileSystem
import fsspec
from sqlalchemy.exc import OperationalError

from scripts.pipeline.logging_config import logger
from scripts.pipeline.utils import load_config_for_domain, PipelineConfig

if TYPE_CHECKING:
    from taxonomy_ontology_accelerator.ontology_engine.pipeline_builder import OntologyPipelineBuilder


async def run_ontology_pipeline(
    config_data: dict | None = None,
    domain_prompt: str | None = None,
    incremental: bool = False,
) -> str:
    """Run the ontology generation pipeline asynchronously."""
    from taxonomy_ontology_accelerator.ontology_engine.pipeline_builder import (
        OntologyPipelineBuilder,
    )

    ontology_config, pipeline_config = load_config_for_domain(config=config_data)

    logger.info(f"Starting ontology pipeline for domain: {pipeline_config.domain_name}")

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
    pipeline = await _extract_ontology(pipeline)
    pipeline = await _process_ontology(pipeline)
    pipeline = await _create_ontology_graph(pipeline)
    await _save_pipeline_output(pipeline, pipeline_config, fs)

    logger.info(f"Ontology pipeline completed successfully for domain: {pipeline_config.domain_name}")
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
    version_info = {
        "version": config.version_number,
        "notes": config.version_notes,
    }
    run_root = _resolve_run_root(output_dir, config.output_dir)
    version_file_path = f"{str(run_root).rstrip('/')}/version.json"
    try:
        parent_dir = version_file_path.rsplit("/", 1)[0]
        if parent_dir:
            fs.makedirs(parent_dir, exist_ok=True)
        with fs.open(version_file_path, "w", encoding="utf-8") as handle:
            json.dump(version_info, handle, indent=2)
            handle.write("\n")
        logger.info(f"Version info saved to {version_file_path}")
    except Exception as e:
        logger.warning(f"Failed to save version info: {e}")


def _update_job_status(job_id: str, status: str, error_message: str | None = None, job_runs: str | None = None) -> None:
    """Update the processing job status in the database."""
    try:
        from govuk_ai_accelerator_app import create_app, db, ProcessingJob
        app = create_app()
        with app.app_context():
            job = db.session.get(ProcessingJob, job_id)
            if job:
                job.status = status
                if error_message is not None:
                    job.error_message = error_message
                if job_runs is not None:
                    job.job_runs = job_runs
                db.session.commit()
    except OperationalError as exc:
        logger.warning("Unable to update job status (%s): %s", status, exc)
    except Exception as exc:
        logger.exception("Error updating job status: %s", exc)


def run_ontology_background_task(config: dict, domain_prompt: str, job_id: str | None = None) -> bool:
    """Run the ontology pipeline as a background task, updating job status if provided."""
    try:
        output_dir = asyncio.run(run_ontology_pipeline(config_data=config, domain_prompt=domain_prompt))
        logger.info("Pipeline task completed successfully")
        
        job_runs = None
        if output_dir:
            import re
            match = re.search(r'(run_\d{8}_v[\d\.]+)', output_dir)
            if match:
                job_runs = match.group(1)

        if job_id:
            _update_job_status(job_id, "completed", job_runs=job_runs)
        return True
    except Exception as e:
        logger.error(f"Pipeline task failed: {str(e)}")
        if job_id:
            _update_job_status(job_id, "failed", error_message=str(e))
        raise
