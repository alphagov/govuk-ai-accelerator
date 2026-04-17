import configparser
import logging
import fsspec
import os
import io
from datetime import datetime, timezone
from typing import Any, cast, Optional, TextIO
from urllib.parse import urlparse
from dataclasses import dataclass, field

DEFAULT_S3_BUCKET = "govuk-ai-accelerator-data-integration"


def slug_from_url(url: str) -> str:
    """Convert a gov.uk URL into a flat, filesystem-safe slug.

    https://www.gov.uk/foreign-travel-advice/print       -> foreign-travel-advice
    https://www.gov.uk/government/publications/visa/print -> government-publications-visa
    https://www.gov.uk/evisa                              -> evisa
    https://www.report-error-evisa.homeoffice.gov.uk/     -> report-error-evisa.homeoffice.gov.uk
    """
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if path.endswith("/print"):
        path = path[: -len("/print")]
    elif path == "print":
        path = ""
    slug = path.replace("/", "-")
    if not slug and parsed.netloc and parsed.netloc != "www.gov.uk":
        slug = parsed.netloc.removeprefix("www.")
    return slug


@dataclass
class IngestionConfig:
    output_dir: str
    html_dir: str
    protocol: str
    links_file: str
    output_format: str
    log_path: str = "ingestion.log"
    links_list: Optional[list[str]] = None
    domain: Optional[str] = None

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


def _domain_defaults(domain: str) -> dict:
    bucket = os.getenv("S3_BUCKET_NAME", DEFAULT_S3_BUCKET)
    base = f"s3://{bucket}/{domain}"
    return {
        "output_dir": f"{base}/input",
        "html_dir": f"{base}/html_content",
        "protocol": "s3",
        "log_path": f"{base}/ingestion.log",
    }


def load_config(
    config_path: str = None,
    config_content: Any = None,
    links_list: list[str] = None,
    domain: str = None,
) -> IngestionConfig:
    overrides = _domain_defaults(domain) if domain else {}

    if isinstance(config_content, dict):
        merged = {**overrides, **{k: v for k, v in config_content.items() if v is not None}}
        return IngestionConfig(
            output_dir=merged.get("output_dir", "output"),
            html_dir=merged.get("html_dir", "html_content"),
            protocol=merged.get("protocol", "local"),
            links_file=merged.get("links_file", "links.txt"),
            output_format=merged.get("output_format", "markdown"),
            log_path=merged.get("log_path", "ingestion.log"),
            links_list=links_list,
            domain=domain,
        )

    config = configparser.ConfigParser()
    if config_path:
        config.read(config_path)
    elif isinstance(config_content, str):
        config.read_string(config_content)

    section = "general" if config.has_section("general") else "DEFAULT"

    return IngestionConfig(
        output_dir=config.get(section, "output_dir", fallback=overrides.get("output_dir", "output")),
        html_dir=config.get(section, "html_dir", fallback=overrides.get("html_dir", "html_content")),
        protocol=config.get(section, "protocol", fallback=overrides.get("protocol", "local")),
        links_file=config.get(section, "links_file", fallback="links.txt"),
        output_format=config.get(section, "output_format", fallback="markdown"),
        log_path=config.get(section, "log_path", fallback=overrides.get("log_path", "ingestion.log")),
        links_list=links_list,
        domain=domain,
    )

def get_logger(log_path: str = None, stream: TextIO = None) -> logging.Logger:
    """Return the shared ingestion logger.

    When called with a `stream` or `log_path`, existing handlers are dropped and
    fresh ones attached — so each ingestion run writes to its own buffer/file
    without leaking into the previous run.
    """
    logger = logging.getLogger("ontology-ingestion")
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    if stream is not None or log_path is not None:
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

        logger.setLevel(logging.INFO)
        logger.propagate = False

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        if stream is not None:
            stream_handler = logging.StreamHandler(stream)
            stream_handler.setFormatter(formatter)
            logger.addHandler(stream_handler)
        elif log_path:
            file_handler = logging.FileHandler(log_path)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
    elif not logger.handlers:
        logger.setLevel(logging.INFO)
        logger.propagate = False
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger