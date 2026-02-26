from typing import cast
from taxonomy_ontology_accelerator.ontology_engine.pipeline_builder import OntologyPipelineBuilder
from taxonomy_ontology_accelerator.ontology_engine.config.config import OntologyConfig, EmbeddingsConfig, OntologyConfigLoader
from taxonomy_ontology_accelerator.commons.config.config_loader import FilesystemConfig
from taxonomy_ontology_accelerator.commons.io.fsspec_utils import safe_write_json_fsspec
from taxonomy_ontology_accelerator.commons.utils.logger import get_logger
from scripts.pipeline.utils import load_config_for_domain, PipelineConfig
from dotenv import load_dotenv
import fsspec 
import asyncio
from fsspec import AbstractFileSystem



logger = cast('RichLogger', get_logger())

load_dotenv()





async def run_ontology_pipeline(config_data: dict | None = None, domain_prompt: str=None, incremental: bool = False) -> bool:
    """Execute the complete ontology generation pipeline"""

    
    ontology_config, pipeline_config = load_config_for_domain(config=config_data)
    domain_prompt = domain_prompt
    logger.info(f"Starting ontology pipeline for domain: {pipeline_config.domain_name}")
    # ontology_configuration = build_ontology_config(pipeline_config)
    fs = fsspec.filesystem(ontology_config.filesystem.protocol)
    # Initialize pipeline builder
    pipeline = OntologyPipelineBuilder(
        domain=pipeline_config.domain_name, 
        config= ontology_config, 
        incremental=incremental,
        input_path = pipeline_config.input_path,
        fs= fs,
        domain_prompt = domain_prompt
    )
    


    # Execute pipeline stages
    pipeline = _setup_pipeline(pipeline, pipeline_config)
    pipeline = await _extract_ontology(pipeline)
    pipeline = await _process_ontology(pipeline)
    pipeline = await _create_ontology_graph(pipeline)
    await _save_pipeline_output(pipeline, pipeline_config,fs)
    
    logger.info(f"Ontology pipeline completed successfully for domain: {pipeline_config.domain_name}")
    return True


def _setup_pipeline(pipeline: OntologyPipelineBuilder, config: PipelineConfig) -> OntologyPipelineBuilder:
    """Setup the ontology pipeline with configuration and load existing data."""
    logger.info("Setting up ontology pipeline")
    pipeline =  (
        pipeline
        .setup_pipeline(
            input_path=config.input_path,
            output_dir=config.output_dir,
            prompt_path=config.prompt_path,
        )
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
    
    pipeline =  ( pipeline.validate()  
            .save()  
            .export()
    )
    return pipeline


async def _save_pipeline_output(
    pipeline: OntologyPipelineBuilder, 
    config: PipelineConfig, 
    fs: AbstractFileSystem

) -> None:
    """Save pipeline output and version information."""
    logger.info("Saving pipeline output")
    
    
    await pipeline.finalize()
    
    # Save version information
    await _save_version_info(config, fs)


async def _save_version_info(config: PipelineConfig, fs:AbstractFileSystem) -> None:
    """Save version information to output directory."""
    version_info = {
        "version": config.version_number,
        "notes": config.version_notes
    }
    
    version_file_path = f"{config.output_dir}/version.json"
    # version_file_path = f"{config.output_dir.rstrip('/')}/version.json"
    
    try:
        safe_write_json_fsspec(version_file_path, version_info, pretty=True, fs= fs)
        logger.info(f"Version info saved to {version_file_path}")
    except Exception as e:
        logger.warning(f"Failed to save version info: {e}")


def run_ontology_background_task(config:dict, domain_prompt: str):

    try:
        asyncio.run(run_ontology_pipeline(config_data=config, domain_prompt=domain_prompt))
        logger.info(f"Pipeline Task Completed for domain")
        return True
    except Exception as e:
        print(f"Pipeline Task Failed: {str(e)}")
        raise



