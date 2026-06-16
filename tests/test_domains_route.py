"""Tests for the GET /ontology/domains page that IAs use to launch ingestion."""
import importlib
import sys

import pytest
from werkzeug.test import Client
from werkzeug.wrappers import Response


def _app_module():
    return importlib.import_module("govuk_ai_accelerator_app")


def _client():
    return Client(_app_module().create_app(), Response)


@pytest.fixture(autouse=True)
def _in_memory_db(monkeypatch):
    monkeypatch.setenv("ALLOW_IN_MEMORY_DB", "true")
    monkeypatch.setenv("DISABLE_TASK_MANAGER", "true")
    app_module = sys.modules.get("govuk_ai_accelerator_app")
    if app_module is not None:
        app_module._cached_app = None
    yield
    app_module = sys.modules.get("govuk_ai_accelerator_app")
    if app_module is not None:
        app_module._cached_app = None


def test_domains_page_renders_form():
    response = _client().get("/ontology/domains")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'name="domain"' in body
    assert 'type="file"' in body


def test_header_links_to_create_domains_page():
    response = _client().get("/ontology/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "/ontology/domains" in body
    assert "Create Domains" in body


def test_header_links_to_review_tests_after_create_domains():
    response = _client().get("/ontology/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "/ontology/review-tests" in body
    assert "Review Tests" in body
    assert body.index("Create Domains") < body.index("Review Tests")
    assert "File Explorer" not in body
    assert "/viewer/bucket/govuk-ai-accelerator-data-integration" not in body
