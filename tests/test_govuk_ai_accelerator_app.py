from werkzeug.test import Client
from werkzeug.wrappers import Response

from govuk_ai_accelerator_app import create_app


def _client():
    return Client(create_app(), Response)


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
