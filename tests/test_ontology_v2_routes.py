import importlib
import json
import sys
import uuid

import pytest
from werkzeug.test import Client
from werkzeug.wrappers import Response


def _purge_modules():
    for name in list(sys.modules):
        if name == "govuk_ai_accelerator_app" or name.startswith("ontology_v2"):
            sys.modules.pop(name, None)


@pytest.fixture(autouse=True)
def _isolated_app(monkeypatch):
    monkeypatch.setenv("ALLOW_IN_MEMORY_DB", "true")
    _purge_modules()
    monkeypatch.setattr("ontology_v2.schemas.ALLOWED_TASKS", frozenset({"placeholder_task"}))
    yield
    _purge_modules()


def _client():
    return Client(importlib.import_module("govuk_ai_accelerator_app").create_app(), Response)


def _post(client, body, content_type="application/json"):
    headers = {"Content-Type": content_type} if content_type else {}
    return client.post("/ontology-v2/runs", data=body, headers=headers)


def test_post_creates_pending_run():
    response = _post(_client(), json.dumps({"domain": "transport", "tasks": ["placeholder_task"]}))
    assert response.status_code == 201
    body = json.loads(response.get_data())
    uuid.UUID(body["run_id"])
    assert body["status"] == "pending"
    assert body["domain"] == "transport"
    assert body["tasks"] == ["placeholder_task"]
    assert body["created_at"]
    assert response.headers["Location"].endswith(f"/ontology-v2/runs/{body['run_id']}")


def test_get_returns_existing_run():
    client = _client()
    created = json.loads(_post(client, json.dumps({"domain": "tax", "tasks": ["placeholder_task"]})).get_data())
    response = client.get(f"/ontology-v2/runs/{created['run_id']}")
    assert response.status_code == 200
    assert json.loads(response.get_data()) == created


@pytest.mark.parametrize("payload, expected", [
    ({"tasks": ["placeholder_task"]}, "validation_error"),
    ({"domain": "BadDomain", "tasks": ["placeholder_task"]}, "validation_error"),
    ({"domain": "x" * 256, "tasks": ["placeholder_task"]}, "validation_error"),
    ({"domain": "tax"}, "validation_error"),
    ({"domain": "tax", "tasks": []}, "validation_error"),
    ({"domain": "tax", "tasks": [123]}, "validation_error"),
    ({"domain": "tax", "tasks": ["   "]}, "validation_error"),
    ({"domain": "tax", "tasks": ["nope"]}, "unknown_task"),
])
def test_post_rejects_invalid(payload, expected):
    response = _post(_client(), json.dumps(payload))
    assert response.status_code == 400
    assert json.loads(response.get_data())["error"] == expected


def test_post_rejects_malformed_json():
    response = _post(_client(), "{not json")
    assert response.status_code == 400
    assert json.loads(response.get_data())["error"] == "malformed_request"


@pytest.mark.parametrize("content_type", [None, "text/plain", "application/xml"])
def test_post_rejects_wrong_content_type(content_type):
    response = _post(_client(), json.dumps({"domain": "tax", "tasks": ["placeholder_task"]}), content_type)
    assert response.status_code == 415
    assert json.loads(response.get_data())["error"] == "unsupported_media_type"


def test_get_unknown_run():
    response = _client().get("/ontology-v2/runs/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert json.loads(response.get_data())["error"] == "run_not_found"


def test_get_invalid_uuid():
    response = _client().get("/ontology-v2/runs/not-a-uuid")
    assert response.status_code == 400
    assert json.loads(response.get_data())["error"] == "invalid_run_id"


def test_rejected_requests_do_not_save():
    app_module = importlib.import_module("govuk_ai_accelerator_app")
    client = Client(app_module.create_app(), Response)
    flask_app = app_module._cached_app

    _post(client, json.dumps({"domain": "BadDomain", "tasks": ["placeholder_task"]}))
    _post(client, "{not json")
    _post(client, json.dumps({"domain": "tax", "tasks": ["nope"]}))
    _post(
        client,
        json.dumps({"domain": "tax", "tasks": ["placeholder_task"]}),
        content_type="text/plain",
    )

    from ontology_v2.models import V2OntologyRun
    with flask_app.app_context():
        assert app_module.db.session.query(V2OntologyRun).count() == 0

def test_openapi_lists_both_endpoints():
    spec = json.loads(_client().get("/ontology-v2/openapi.json").get_data())
    assert "/ontology-v2/runs" in spec["paths"]
    assert "/ontology-v2/runs/{run_id}" in spec["paths"]
    schemas = spec["components"]["schemas"]
    assert "CreateRunRequest" in schemas
    assert "RunResponse" in schemas
    assert "ErrorResponse" in schemas

def test_scalar_docs_renders():
    response = _client().get("/ontology-v2/docs")
    assert response.status_code == 200
    assert response.content_type.startswith("text/html")
    assert b"@scalar/api-reference" in response.get_data()