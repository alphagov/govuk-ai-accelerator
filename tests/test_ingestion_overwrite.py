"""Tests for overwrite-by-default and flat output layout in ingestion commands."""
from unittest.mock import patch, MagicMock

import fsspec
import pytest

from scripts.ingestion.commands.download_content import download_content
from scripts.ingestion.commands.extract_content import extract_content
from scripts.ingestion.commands.utils import IngestionConfig


@pytest.fixture(autouse=True)
def _clean_memory_fs():
    fs = fsspec.filesystem("memory")
    for p in list(fs.store.keys()):
        fs.rm(p)
    yield
    for p in list(fs.store.keys()):
        fs.rm(p)


def _make_config(monkeypatch, links, output_format="markdown"):
    """Build an IngestionConfig pointing at fsspec's in-memory filesystem."""
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
        output_format=output_format,
        log_path="/test-domain/ingestion.log",
        links_list=links,
        domain="test-domain",
    )


def _fake_response(body: bytes):
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    resp.content = body
    return resp


def test_download_writes_flat_html_file_named_after_slug(monkeypatch):
    config = _make_config(
        monkeypatch,
        links=["https://www.gov.uk/foreign-travel-advice/print"],
    )

    with patch(
        "scripts.ingestion.commands.download_content.requests.get",
        return_value=_fake_response(b"<html>fresh</html>"),
    ):
        download_content(config)

    fs = fsspec.filesystem("memory")
    assert fs.exists("/test-domain/html_content/foreign-travel-advice.html")
    # No nested directory created.
    assert not fs.exists("/test-domain/html_content/foreign-travel-advice/print.html")


def test_download_overwrites_existing_file(monkeypatch):
    config = _make_config(
        monkeypatch,
        links=["https://www.gov.uk/foreign-travel-advice/print"],
    )
    fs = fsspec.filesystem("memory")
    fs.makedirs("/test-domain/html_content", exist_ok=True)
    with fs.open(
        "/test-domain/html_content/foreign-travel-advice.html", "wb"
    ) as f:
        f.write(b"<html>stale</html>")

    with patch(
        "scripts.ingestion.commands.download_content.requests.get",
        return_value=_fake_response(b"<html>fresh</html>"),
    ):
        download_content(config)

    with fs.open("/test-domain/html_content/foreign-travel-advice.html", "rb") as f:
        assert f.read() == b"<html>fresh</html>"


def test_extract_writes_flat_markdown_named_after_slug(monkeypatch):
    config = _make_config(monkeypatch, links=[])
    fs = fsspec.filesystem("memory")
    fs.makedirs("/test-domain/html_content", exist_ok=True)
    html_body = (
        b'<html><body><div id="content">Fresh body</div></body></html>'
    )
    with fs.open(
        "/test-domain/html_content/foreign-travel-advice.html", "wb"
    ) as f:
        f.write(html_body)

    with patch(
        "scripts.ingestion.commands.extract_content.pypandoc.convert_text",
        side_effect=lambda content, format, to: "Fresh body",
    ):
        extract_content(config)

    assert fs.exists("/test-domain/input/foreign-travel-advice.md")
    assert not fs.exists("/test-domain/input/foreign-travel-advice/print.md")


def test_extract_overwrites_existing_markdown(monkeypatch):
    config = _make_config(monkeypatch, links=[])
    fs = fsspec.filesystem("memory")
    fs.makedirs("/test-domain/html_content", exist_ok=True)
    fs.makedirs("/test-domain/input", exist_ok=True)
    html_body = (
        b'<html><body><div id="content">Fresh body</div></body></html>'
    )
    with fs.open(
        "/test-domain/html_content/foreign-travel-advice.html", "wb"
    ) as f:
        f.write(html_body)
    with fs.open(
        "/test-domain/input/foreign-travel-advice.md", "w", encoding="utf-8"
    ) as f:
        f.write("stale markdown")

    with patch(
        "scripts.ingestion.commands.extract_content.pypandoc.convert_text",
        side_effect=lambda content, format, to: "Fresh body",
    ):
        extract_content(config)

    with fs.open(
        "/test-domain/input/foreign-travel-advice.md", "r", encoding="utf-8"
    ) as f:
        assert f.read() == "Fresh body"
