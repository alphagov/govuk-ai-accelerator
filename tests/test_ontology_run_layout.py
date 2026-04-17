"""Tests for ontology run path construction and config.yaml persistence."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scripts.pipeline.ontology_generator import (
    _with_job_output_path,
    run_ontology_background_task,
)


class TestWithJobOutputPath:
    """_with_job_output_path should pass the config through without injecting a UUID."""

    def test_output_dir_unchanged_when_no_uuid_injected(self):
        config = {"path": {"output_dir": "s3://bucket/test-visa-1"}}
        result = _with_job_output_path(config, "some-uuid-here")

        assert result["path"]["output_dir"] == "s3://bucket/test-visa-1"

    def test_output_dir_with_trailing_output_segment_is_preserved(self):
        config = {"path": {"output_dir": "s3://bucket/test-visa-1/output"}}
        result = _with_job_output_path(config, "some-uuid")

        assert "some-uuid" not in result["path"]["output_dir"]

    def test_none_config_returns_none(self):
        assert _with_job_output_path(None, "x") is None

    def test_missing_output_dir_returns_config_unchanged(self):
        config = {"path": {}}
        result = _with_job_output_path(config, "x")
        assert result == {"path": {}}


class TestConfigYamlPersistence:
    """After a successful ontology run, config.yaml should be saved at the run root."""

    @patch("scripts.pipeline.ontology_generator._mark_job_progress")
    @patch("scripts.pipeline.ontology_generator._update_job_status")
    @patch("scripts.pipeline.ontology_generator.asyncio.run")
    @patch("scripts.pipeline.ontology_generator.fsspec")
    def test_config_persisted_at_run_root(
        self, mock_fsspec, mock_asyncio_run, mock_update, mock_progress
    ):
        mock_asyncio_run.return_value = "s3://bucket/test-visa-1/run-20260417-1/output"
        mock_fs = MagicMock()
        mock_fsspec.core.url_to_fs.return_value = (mock_fs, "bucket/test-visa-1/run-20260417-1/config.yaml")

        config = {
            "domain_name": "test-visa-1",
            "path": {"output_dir": "s3://bucket/test-visa-1"},
        }

        run_ontology_background_task(config, domain_prompt="", job_id="job-1")

        mock_fs.open.assert_called()
        config_call_path = None
        for call in mock_fsspec.core.url_to_fs.call_args_list:
            if "config.yaml" in str(call):
                config_call_path = call.args[0]
                break
        assert config_call_path is not None, "config.yaml should have been written"
        assert config_call_path == "s3://bucket/test-visa-1/run-20260417-1/config.yaml"
