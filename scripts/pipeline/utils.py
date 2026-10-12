from __future__ import annotations

from pathlib import Path
import yaml
from typing import TYPE_CHECKING, Optional
from flask import jsonify
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

from scripts.pipeline.logging_config import logger
from scripts.pipeline.constants import EXECUTOR_MAX_WORKERS

if TYPE_CHECKING:
    from taxonomy_ontology_accelerator.ontology_engine.config.config import OntologyConfig

executor = ThreadPoolExecutor(max_workers=EXECUTOR_MAX_WORKERS)


def config_builder(path: Optional[Path] = None, config: Optional[dict] = None) -> OntologyConfig:
    """Create the Generator library's OntologyConfig from Workflow configuration.

    Dictionary values are passed through to the library's config model; the
    path-based branch delegates domain-config merging to its loader.
    """
    from taxonomy_ontology_accelerator.ontology_engine.config.config import (
        OntologyConfig,
        OntologyConfigLoader,
    )

    if path is not None:
        base = OntologyConfig()
        config = OntologyConfigLoader()._load_and_merge_domain_config('travel', path, base)
        return config
    
    if config is not None:
        return OntologyConfig(**config)
    
    raise ValueError("Either path or config must be provided")


@dataclass
class PipelineConfig:
    """Workflow-side view of the paths and metadata used for a Generator run."""

    domain_name: Optional[str] = None
    version_number: Optional[str] = None
    version_notes: Optional[str] = None
    input_path: Optional[str] = None
    output_dir: Optional[str] = None
    prompt_path: Optional[str] = None

    def __init__(self, **kwargs):
        """Extract Workflow run settings from the config shared with the Generator."""
        self.config = kwargs
    
        self.domain_name = self.config.get('domain_name', None)
        path = self.config.get('path', {})

        self.input_path = path.get('input_path', None)
        self.output_dir = path.get('output_dir', None)
        self.prompt_path = path.get('prompt_path', None)


def load_config_for_domain(config: dict | Path) -> tuple[OntologyConfig, Optional[PipelineConfig]]:
    """Split shared run config into the Generator model and Workflow settings.

    The returned ``OntologyConfig`` is created by ``taxonomy-ontology-accelerator``;
    ``PipelineConfig`` retains Workflow-facing domain and path values.
    """
    if isinstance(config, Path):
        raise NotImplementedError('Path-based configuration loading not yet implemented')
    
    if isinstance(config, dict):
        pipeline_config = PipelineConfig(**config)
        ontology_config = config_builder(config=pipeline_config.config)
        return ontology_config, pipeline_config
    
    raise TypeError(f"Config must be dict or Path, got {type(config)}")


def error_response(message: str, status_code: int = 400):
    """Format a Flask API error response for Workflow routes.

    The caller must be executing inside a Flask request or application
    context. Tests should push a context when invoking this helper.
    """
    resp = jsonify({"error": message})
    resp.status_code = status_code
    return resp


def is_yaml_file(filename: str) -> bool:
    """Check whether a filename has an extension accepted for Workflow config files.

    Returns ``False`` for ``None`` or empty strings.
    """
    if not filename:
        return False
    return filename.lower().endswith(('.yaml', '.yml'))
