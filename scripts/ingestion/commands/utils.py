import configparser
import logging
import fsspec
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, cast, Optional
from dataclasses import dataclass, field

@dataclass
class IngestionConfig:
    output_dir: str
    html_dir: str
    protocol: str
    links_file: str
    output_format: str
    log_path: str = "ingestion.log"
    links_list: Optional[list[str]] = None
    temp_log_path: Optional[str] = None
    
    output_dir_url: str = field(init=False)
    html_dir_url: str = field(init=False)
    links_file_url: str = field(init=False)
    final_log_url: str = field(init=False)

    def __post_init__(self):
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        
        base, ext = os.path.splitext(self.log_path)
        if not ext:
            ext = ".log"
        self.log_path = f"{base}_{timestamp}{ext}"
            
        if not self.temp_log_path:
            temp_dir = tempfile.gettempdir()
            filename = os.path.basename(self.log_path)
            self.temp_log_path = os.path.join(temp_dir, filename)
            with open(self.temp_log_path, 'w') as f:
                f.write("")
                
        # Initialize URLs
        self.output_dir_url = self.get_fsspec_url(self.output_dir)
        self.html_dir_url = self.get_fsspec_url(self.html_dir)
        self.links_file_url = self.get_fsspec_url(self.links_file)
        self.final_log_url = self.get_fsspec_url(self.log_path)

    def resolve_path(self, val: str) -> str:
        return val if "://" in val else f"scripts/ingestion/{val}"

    def get_fsspec_url(self, path: str) -> str:
        protocol = "file" if self.protocol == "local" else self.protocol
        if "://" in path:
            return path
        return f"{protocol}://{self.resolve_path(path)}"

def load_config(config_path: str = None, config_content: Any = None, links_list: list[str] = None) -> IngestionConfig:
    if isinstance(config_content, dict):
        return IngestionConfig(
            output_dir=config_content.get("output_dir", "output"),
            html_dir=config_content.get("html_dir", "html_content"),
            protocol=config_content.get("protocol", "local"),
            links_file=config_content.get("links_file", "links.txt"),
            output_format=config_content.get("output_format", "markdown"),
            log_path=config_content.get("log_path", "ingestion.log"),
            links_list=links_list
        )

    config = configparser.ConfigParser()
    if config_path:
        config.read(config_path)
    elif isinstance(config_content, str):
        config.read_string(config_content)
    
    section = "general" if config.has_section("general") else "DEFAULT"
    
    return IngestionConfig(
        output_dir=config.get(section, "output_dir", fallback="output"),
        html_dir=config.get(section, "html_dir", fallback="html_content"),
        protocol=config.get(section, "protocol", fallback="local"),
        links_file=config.get(section, "links_file", fallback="links.txt"),
        output_format=config.get(section, "output_format", fallback="markdown"),
        log_path=config.get(section, "log_path", fallback="ingestion.log"),
        links_list=links_list
    )

def get_logger(log_path: str = None) -> logging.Logger:

    logger = logging.getLogger("ontology-ingestion")
    
    if log_path:
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

    if not logger.handlers:
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        if log_path:
            file_handler = logging.FileHandler(log_path)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            
        logger.propagate = False
        
    return logger