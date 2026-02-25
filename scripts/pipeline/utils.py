from taxonomy_ontology_accelerator.ontology_engine.config.config import ModelConfig, OntologyConfig, OntologyConfigLoader
from pathlib import Path
import yaml
from typing import cast, Optional
from taxonomy_ontology_accelerator.commons.utils.logger import get_logger
import fsspec
from flask import jsonify
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
executor = ThreadPoolExecutor(max_workers=4)



logger = cast('RichLogger', get_logger())


def config_builder(path: Optional[Path]= None, config: Optional[dict[str, str]]=None)-> OntologyConfig:

    if path is not None:
        base = OntologyConfig() #instantiate ontology base config
        config = OntologyConfigLoader()._load_and_merge_domain_config('travel', path, base)
        return config
    
    else:
        config = OntologyConfig(**config)
        return config





@dataclass
class PipelineConfig:

    def __init__(self, **kwargs):
        self.config = kwargs
    
        version = self.config.get('version', {})
        self.domain_name = self.config.get('domain_name', None)
        path = self.config.get('path', {})

        del self.config['version']
        del self.config['path']
    

        self.version_number = version.get('number', None)
        self.version_notes = version.get('notes', None)
        self.input_path = path.get('input_path', None)
        self.output_dir = path.get('output_dir', None)
        self.prompt_path = path.get('prompt_path', None)

        if self.output_dir and self.version_number:
                from datetime import datetime
                date_str = datetime.now().strftime("%Y%m%d")
                # Ensure clean path joining for both local and s3
                base_dir = self.output_dir.rstrip('/')
                run_folder = f"run_{date_str}_v{self.version_number}"
                self.output_dir = f"{base_dir}/{run_folder}"


def load_config_for_domain(config: dict | Path):

    if isinstance(config, Path):
        # raise NotImplementedError ('Error!!!')
        return config_builder(path = pipeline_config), None
    
    if isinstance(config, dict):
        pipeline_config =PipelineConfig(**config)
        return config_builder(config=pipeline_config.config), pipeline_config




def _error_response(message, status_code=400):
    """Helper function to create error responses."""
    return jsonify({"error": message}), status_code

def _is_yaml_file(filename):
    """Check if the filename has a YAML extension."""
    return filename and (filename.endswith('.yaml') or filename.endswith('.yml'))



