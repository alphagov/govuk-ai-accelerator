"""Tests for POST /ontology/ingest handling the domain parameter end-to-end."""
import importlib
import sys
from unittest.mock import patch

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


@pytest.fixture
def _stub_background_deps():
    """Prevent the endpoint from hitting AWS or scheduling real ingestion."""
    with patch("govuk_ai_accelerator_app.create_bucket_folder") as folder, \
         patch("govuk_ai_accelerator_app.executor") as executor:
        yield folder, executor


def test_ingest_rejects_missing_domain(_stub_background_deps):
    response = _client().post(
        "/ontology/ingest",
        json={"links": ["https://www.gov.uk/x/print"]},
    )

    assert response.status_code == 400
    assert b"Domain" in response.get_data()


def test_ingest_rejects_missing_links(_stub_background_deps):
    response = _client().post(
        "/ontology/ingest",
        json={"domain": "visa"},
    )

    assert response.status_code == 400


def test_ingest_accepts_domain_and_links_and_schedules_job(_stub_background_deps):
    folder_mock, executor_mock = _stub_background_deps

    response = _client().post(
        "/ontology/ingest",
        json={
            "domain": "visa",
            "links": ["https://www.gov.uk/a/print", "https://www.gov.uk/b/print"],
        },
    )

    assert response.status_code == 202
    payload = response.get_json()
    assert "job_id" in payload
    assert payload["status"] == "pending"

    folder_mock.assert_called_once()
    bucket_arg, folder_arg = folder_mock.call_args.args
    assert folder_arg == "visa"
    assert bucket_arg  # non-empty bucket resolved from env/default

    executor_mock.submit.assert_called_once()
    kwargs = executor_mock.submit.call_args.kwargs
    assert kwargs["domain"] == "visa"
    assert kwargs["links_list"] == [
        "https://www.gov.uk/a/print",
        "https://www.gov.uk/b/print",
    ]


def test_ingest_persists_domain_on_processing_job(_stub_background_deps):
    client = _client()
    response = client.post(
        "/ontology/ingest",
        json={"domain": "asylum", "links": ["https://www.gov.uk/z/print"]},
    )
    assert response.status_code == 202
    job_id = response.get_json()["job_id"]

    app_module = _app_module()
    app = app_module.create_flask_app()
    with app.app_context():
        job = app_module.db.session.get(app_module.ProcessingJob, job_id)
        assert job is not None
        assert job.domain == "asylum"
        assert job.pipeline == "ingestion"
