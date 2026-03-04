"""Ontology generation pipeline module."""

import asyncio
from typing import cast
from fsspec import AbstractFileSystem
import fsspec
from sqlalchemy.exc import OperationalError

from taxonomy_ontology_accelerator.ontology_engine.pipeline_builder import OntologyPipelineBuilder
from taxonomy_ontology_accelerator.ontology_engine.config.config import OntologyConfig
from taxonomy_ontology_accelerator.commons.io.fsspec_utils import safe_write_json_fsspec

from scripts.pipeline.logging_config import logger
from scripts.pipeline.utils import load_config_for_domain, PipelineConfig


async def run_ontology_pipeline(
    config_data: dict | None = None,
    domain_prompt: str | None = None,
    incremental: bool = False,
) -> bool:
    """Run the ontology generation pipeline asynchronously."""
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
    return True


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
    await _save_version_info(config, fs)


async def _save_version_info(config: PipelineConfig, fs: AbstractFileSystem) -> None:
    """Save version metadata to the output directory."""
    version_info = {
        "version": config.version_number,
        "notes": config.version_notes,
    }
    version_file_path = f"{config.output_dir}/version.json"
    try:
        safe_write_json_fsspec(version_file_path, version_info, pretty=True, fs=fs)
        logger.info(f"Version info saved to {version_file_path}")
    except Exception as e:
        logger.warning(f"Failed to save version info: {e}")


def _update_job_status(job_id: str, status: str, error_message: str | None = None) -> None:
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
                db.session.commit()
    except OperationalError as exc:
        logger.warning("Unable to update job status (%s): %s", status, exc)
    except Exception as exc:
        logger.exception("Error updating job status: %s", exc)


def run_ontology_background_task(config: dict, domain_prompt: str, job_id: str | None = None) -> bool:
    """Run the ontology pipeline as a background task, updating job status if provided."""
    try:
        asyncio.run(run_ontology_pipeline(config_data=config, domain_prompt=domain_prompt))
        logger.info("Pipeline task completed successfully")
        if job_id:
            _update_job_status(job_id, "completed")
        return True
    except Exception as e:
        logger.error(f"Pipeline task failed: {str(e)}")
        if job_id:
            _update_job_status(job_id, "failed", error_message=str(e))
        raise
