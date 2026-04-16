"""Tests for IngestionConfig deriving S3 paths from a domain parameter."""
import re

from scripts.ingestion.commands.utils import load_config


def test_load_config_with_domain_derives_s3_paths(monkeypatch):
    monkeypatch.setenv("S3_BUCKET_NAME", "my-bucket")

    config = load_config(domain="visa", links_list=["https://www.gov.uk/x/print"])

    assert config.protocol == "s3"
    assert config.output_dir_url == "s3://my-bucket/visa/input"
    assert config.html_dir_url == "s3://my-bucket/visa/html_content"
    # Log file lives at the root of the domain folder with a timestamp.
    assert re.match(
        r"^s3://my-bucket/visa/ingestion_\d{8}_\d{6}\.log$",
        config.final_log_url,
    )
    assert config.links_list == ["https://www.gov.uk/x/print"]


def test_load_config_with_domain_uses_default_bucket_when_env_unset(monkeypatch):
    monkeypatch.delenv("S3_BUCKET_NAME", raising=False)

    config = load_config(domain="visa", links_list=["https://www.gov.uk/x/print"])

    assert "govuk-ai-accelerator-data-integration" in config.output_dir_url
    assert "/visa/" in config.output_dir_url


def test_load_config_without_domain_keeps_legacy_defaults(monkeypatch):
    monkeypatch.delenv("S3_BUCKET_NAME", raising=False)

    config = load_config(links_list=["https://www.gov.uk/x/print"])

    # No domain → stays on local protocol + relative paths (legacy behaviour).
    assert config.protocol == "local"
    assert config.output_dir_url.startswith("file://")


def test_explicit_config_content_wins_over_domain(monkeypatch):
    monkeypatch.setenv("S3_BUCKET_NAME", "my-bucket")

    config = load_config(
        domain="visa",
        config_content={
            "output_dir": "s3://explicit-bucket/custom/output",
            "html_dir": "s3://explicit-bucket/custom/html",
            "protocol": "s3",
            "log_path": "s3://explicit-bucket/custom/custom.log",
        },
        links_list=["https://www.gov.uk/x/print"],
    )

    assert config.output_dir_url == "s3://explicit-bucket/custom/output"
    assert config.html_dir_url == "s3://explicit-bucket/custom/html"
    assert config.final_log_url.startswith("s3://explicit-bucket/custom/")
