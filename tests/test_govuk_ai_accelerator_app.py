import builtins
import importlib
import sys

from werkzeug.test import Client
from werkzeug.wrappers import Response


def _client():
    app_module = importlib.import_module("govuk_ai_accelerator_app")
    return Client(app_module.create_app(), Response)


def test_create_app_redirects_visualizer_without_trailing_slash():
    response = _client().get("/visualizer", follow_redirects=False)

    assert response.status_code in {307, 308}
    assert response.headers["Location"].endswith("/visualizer/")


def test_create_app_serves_visualizer_root():
    response = _client().get("/visualizer/")

    assert response.status_code == 200
    assert response.content_type.startswith("text/html")


def test_create_app_still_serves_ontology_dashboard():
    response = _client().get("/ontology/")

    assert response.status_code == 200


def test_create_app_imports_without_visualizer_dependency(monkeypatch):
    original_import = builtins.__import__

    def patched_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith("taxonomy_ontology_accelerator"):
            raise ModuleNotFoundError("No module named 'taxonomy_ontology_accelerator'")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.delitem(sys.modules, "govuk_ai_accelerator_app", raising=False)
    monkeypatch.setattr(builtins, "__import__", patched_import)

    app_module = importlib.import_module("govuk_ai_accelerator_app")
    client = Client(app_module.create_app(), Response)

    ontology_response = client.get("/ontology/")
    visualizer_response = client.get("/visualizer/")

    assert ontology_response.status_code == 200
    assert visualizer_response.status_code == 503
    assert "Visualizer is unavailable" in visualizer_response.get_data(as_text=True)
