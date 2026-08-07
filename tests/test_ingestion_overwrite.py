"""Tests for the merged download+extract stage.

The pipeline no longer writes intermediate HTML files; downloading a URL should
produce the cleaned markdown directly in `<domain>/input/<slug>.md`.
"""
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


def _make_config(monkeypatch, links, output_format="markdown"):
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


def _ok_response(body: bytes):
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    resp.content = body
    return resp


HTML_WITH_GUIDE_CONTENTS = (
    b'<html><body><div id="guide-contents">'
    b'<h1>Travel</h1><p>Some guidance.</p>'
    b'</div></body></html>'
)

HTML_WITH_CONTENT_ONLY = (
    b'<html><body><main id="content">'
    b'<h1>Visa</h1><p>Visa info.</p>'
    b'</main></body></html>'
)

HTML_WITH_MAIN_CONTENT_ONLY = (
    b'<html><body><main id="main-content">'
    b'<h1>Software Developer</h1><p>Role levels</p>'
    b'</main></body></html>'
)

HTML_WITH_NEITHER = (
    b'<html><body><h1>Orphan</h1><p>No known id on wrappers.</p></body></html>'
)


def test_download_writes_markdown_directly_to_output_dir(monkeypatch):
    config = _make_config(
        monkeypatch,
        links=["https://www.gov.uk/foreign-travel-advice/print"],
    )
    with patch(
        "scripts.ingestion.commands.download_content.requests.get",
        return_value=_ok_response(HTML_WITH_GUIDE_CONTENTS),
    ):
        download_content(config)

    fs = fsspec.filesystem("memory")
    md_path = "/test-domain/input/foreign-travel-advice.md"
    assert fs.exists(md_path), "merged pipeline should write markdown directly"
    with fs.open(md_path, "r", encoding="utf-8") as f:
        body = f.read()
    assert "Travel" in body
    assert "Some guidance." in body


def test_download_never_writes_html_content_directory(monkeypatch):
    config = _make_config(
        monkeypatch,
        links=["https://www.gov.uk/foreign-travel-advice/print"],
    )
    with patch(
        "scripts.ingestion.commands.download_content.requests.get",
        return_value=_ok_response(HTML_WITH_GUIDE_CONTENTS),
    ):
        download_content(config)

    fs = fsspec.filesystem("memory")
    html_leaks = [p for p in fs.store.keys() if "/html_content" in p]
    assert html_leaks == [], f"no html_content/ files should be written, got: {html_leaks}"


def test_download_overwrites_existing_markdown(monkeypatch):
    fs = fsspec.filesystem("memory")
    fs.makedirs("/test-domain/input", exist_ok=True)
    with fs.open("/test-domain/input/foreign-travel-advice.md", "w", encoding="utf-8") as f:
        f.write("stale markdown from a prior run")

    config = _make_config(
        monkeypatch,
        links=["https://www.gov.uk/foreign-travel-advice/print"],
    )
    with patch(
        "scripts.ingestion.commands.download_content.requests.get",
        return_value=_ok_response(HTML_WITH_GUIDE_CONTENTS),
    ):
        download_content(config)

    with fs.open("/test-domain/input/foreign-travel-advice.md", "r", encoding="utf-8") as f:
        body = f.read()
    assert "stale markdown" not in body
    assert "Travel" in body


def test_download_falls_back_to_content_id_when_guide_contents_missing(monkeypatch):
    config = _make_config(
        monkeypatch,
        links=["https://www.gov.uk/visa/print"],
    )
    with patch(
        "scripts.ingestion.commands.download_content.requests.get",
        return_value=_ok_response(HTML_WITH_CONTENT_ONLY),
    ):
        download_content(config)

    fs = fsspec.filesystem("memory")
    md_path = "/test-domain/input/visa.md"
    assert fs.exists(md_path)
    with fs.open(md_path, "r", encoding="utf-8") as f:
        assert "Visa info." in f.read()

def test_download_falls_back_to_main_content_id_when_guide_contents_and_content_missing(monkeypatch):
    config = _make_config(
        monkeypatch,
        links=["https://ddat-capability-framework.service.gov.uk/role/software-developer"],
    )
    with patch(
        "scripts.ingestion.commands.download_content.requests.get",
        return_value=_ok_response(HTML_WITH_MAIN_CONTENT_ONLY),
    ):
        download_content(config)

    fs = fsspec.filesystem("memory")
    md_path = "/test-domain/input/role-software-developer.md"
    assert fs.exists(md_path)
    with fs.open(md_path, "r", encoding="utf-8") as f:
        assert "Role levels" in f.read()


def test_download_skips_page_with_no_extractable_content(monkeypatch):
    config = _make_config(
        monkeypatch,
        links=["https://www.gov.uk/orphan-page/print"],
    )
    with patch(
        "scripts.ingestion.commands.download_content.requests.get",
        return_value=_ok_response(HTML_WITH_NEITHER),
    ):
        download_content(config)

    fs = fsspec.filesystem("memory")
    assert not fs.exists("/test-domain/input/orphan-page.md")
    # Sidecar should not exist either — no successful extractions.
    assert not fs.exists("/test-domain/input/sources.json")
