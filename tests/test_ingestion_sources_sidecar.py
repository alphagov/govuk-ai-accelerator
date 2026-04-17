"""Tests for the sources.json sidecar written alongside ingested content."""
import json
from unittest.mock import patch, MagicMock

import fsspec
import pytest

from scripts.ingestion.commands.download_content import download_content
from scripts.ingestion.commands.utils import IngestionConfig


@pytest.fixture(autouse=True)
def _clean_memory_fs():
    fs = fsspec.filesystem("memory")
    for p in list(fs.store.keys()):
        fs.rm(p)
    yield
    for p in list(fs.store.keys()):
        fs.rm(p)


def _make_config(monkeypatch, links):
    """IngestionConfig pointing at fsspec memory filesystem."""
    monkeypatch.setattr(
        IngestionConfig,
        "get_fsspec_url",
        lambda self, path: path if "://" in path else f"memory://{path}",
    )
    return IngestionConfig(
        output_dir="/test-domain/input",
        html_dir="/test-domain/html_content",
        protocol="memory",
        links_file="/test-domain/links.txt",
        output_format="markdown",
        log_path="/test-domain/ingestion.log",
        links_list=links,
        domain="test-domain",
    )


_VALID_HTML = (
    b'<html><body><div id="content"><h1>Hi</h1><p>Body.</p></div></body></html>'
)


def _ok_response(body=_VALID_HTML):
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    resp.content = body
    return resp


def _err_response(status=404):
    resp = MagicMock()
    resp.ok = False
    resp.status_code = status
    return resp


def test_sidecar_written_with_slug_to_url_mapping(monkeypatch):
    config = _make_config(
        monkeypatch,
        links=[
            "https://www.gov.uk/foreign-travel-advice/print",
            "https://www.gov.uk/get-document-legalised/print",
        ],
    )

    with patch(
        "scripts.ingestion.commands.download_content.requests.get",
        return_value=_ok_response(),
    ):
        download_content(config)

    fs = fsspec.filesystem("memory")
    assert fs.exists("/test-domain/input/sources.json")
    with fs.open("/test-domain/input/sources.json", "r", encoding="utf-8") as f:
        sources = json.load(f)
    assert sources == {
        "memory:///test-domain/input/foreign-travel-advice.md": "https://www.gov.uk/foreign-travel-advice/print",
        "memory:///test-domain/input/get-document-legalised.md": "https://www.gov.uk/get-document-legalised/print",
    }


def test_sidecar_overwrites_stale_entries(monkeypatch):
    fs = fsspec.filesystem("memory")
    fs.makedirs("/test-domain/input", exist_ok=True)
    with fs.open("/test-domain/input/sources.json", "w", encoding="utf-8") as f:
        json.dump({"old-removed-page": "https://www.gov.uk/old-removed-page/print"}, f)

    config = _make_config(
        monkeypatch,
        links=["https://www.gov.uk/foreign-travel-advice/print"],
    )

    with patch(
        "scripts.ingestion.commands.download_content.requests.get",
        return_value=_ok_response(),
    ):
        download_content(config)

    with fs.open("/test-domain/input/sources.json", "r", encoding="utf-8") as f:
        sources = json.load(f)
    assert sources == {
        "memory:///test-domain/input/foreign-travel-advice.md": "https://www.gov.uk/foreign-travel-advice/print"
    }


def test_sidecar_not_written_when_no_successful_downloads(monkeypatch):
    config = _make_config(
        monkeypatch,
        links=["https://www.gov.uk/missing/print"],
    )

    with patch(
        "scripts.ingestion.commands.download_content.requests.get",
        return_value=_err_response(404),
    ):
        download_content(config)

    fs = fsspec.filesystem("memory")
    assert not fs.exists("/test-domain/input/sources.json")


def test_sidecar_excludes_invalid_links(monkeypatch):
    config = _make_config(
        monkeypatch,
        links=[
            "https://www.gov.uk/foreign-travel-advice/print",
            "http://www.gov.uk/insecure/print",
            "https://example.com/wrong-host/print",
            "https://www.gov.uk/missing-print-suffix",
        ],
    )

    with patch(
        "scripts.ingestion.commands.download_content.requests.get",
        return_value=_ok_response(),
    ):
        download_content(config)

    fs = fsspec.filesystem("memory")
    with fs.open("/test-domain/input/sources.json", "r", encoding="utf-8") as f:
        sources = json.load(f)
    assert sources == {
        "memory:///test-domain/input/foreign-travel-advice.md": "https://www.gov.uk/foreign-travel-advice/print"
    }
